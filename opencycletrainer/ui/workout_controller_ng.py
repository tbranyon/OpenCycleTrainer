"""NiceGUI workout session controller — Phase 3.

Ports WorkoutSessionController from PySide6/QObject/QTimer to plain Python
with nicegui.ui.timer for the tick loop.
"""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from pathlib import Path
import time

from nicegui import ui

from opencycletrainer.core.control.ftms_control import (
    ControlMode,
    FTMSControl,
    FTMSControlTransport,
    WorkoutEngineFTMSBridge,
)
from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.devices.ble_backend import BleakDeviceBackend, BleakFTMSControlTransport
from opencycletrainer.core.mrc_parser import MRCParseError, parse_mrc_file
from opencycletrainer.core.recorder import RecorderSample, WorkoutRecorder
from opencycletrainer.core.workout_engine import EngineState, WorkoutEngine, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout
from opencycletrainer.storage.opentrueup_offsets import OpenTrueUpOffsetStore
from opencycletrainer.storage.settings import AppSettings, save_settings

from .workout_screen_ng import WorkoutScreen
from .workout_summary_dialog import WorkoutSummary, compute_tss
from .workout_summary_dialog_ng import show_workout_summary

_logger = logging.getLogger(__name__)

RECOVERY_THRESHOLD_PERCENT = 56.0


class WorkoutSessionController:
    """Connects NiceGUI WorkoutScreen controls/hotkeys to the workout engine."""

    def __init__(
        self,
        *,
        screen: WorkoutScreen,
        settings: AppSettings,
        settings_path: Path | None = None,
        recorder: WorkoutRecorder | None = None,
        opentrueup: OpenTrueUpController | None = None,
        ftms_transport_factory: Callable[[object, str], FTMSControlTransport | None] | None = None,
        summary_dialog_factory: Callable[[WorkoutSummary, Callable[[], None]], None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        strava_upload_fn: Callable[[Path, Path | None], None] | None = None,
        tick_interval_s: float = 0.25,
    ) -> None:
        self._screen = screen
        self._settings = settings
        self._settings_path = settings_path
        self._monotonic_clock = monotonic_clock
        self._utc_now = utc_now if utc_now is not None else lambda: datetime.now(timezone.utc)
        self._recorder = recorder if recorder is not None else WorkoutRecorder()
        self._ftms_transport_factory = (
            ftms_transport_factory
            if ftms_transport_factory is not None
            else self._default_ftms_transport_factory
        )
        self._summary_dialog_factory = summary_dialog_factory or show_workout_summary
        self._opentrueup: OpenTrueUpController | None = (
            opentrueup if opentrueup is not None else self._make_opentrueup(settings)
        )
        self._strava_upload_fn = strava_upload_fn
        self._upload_executor: ThreadPoolExecutor | None = None
        self._trainer_backend: object | None = None
        self._trainer_device_id: str | None = None
        self._ftms_bridge: WorkoutEngineFTMSBridge | None = None
        self._ftms_bridge_executor: ThreadPoolExecutor | None = None

        self._engine = WorkoutEngine(
            kj_mode=self._settings.default_workout_behavior == "kj_mode",
        )
        self._workout: Workout | None = None
        self._selected_mode = "ERG"
        self._manual_resistance_offset_percent = 0.0
        self._manual_erg_jog_watts = 0.0
        self._total_kj = 0.0
        self._interval_extra_seconds: dict[int, int] = {}
        self._last_energy_tick_monotonic: float | None = None
        self._last_snapshot: WorkoutEngineSnapshot | None = None
        self._recorder_active = False
        self._recorder_started = False

        self._power_history: deque[tuple[float, int]] = deque()
        self._cadence_history: deque[tuple[float, float]] = deque()
        self._interval_power_sum = 0.0
        self._interval_power_count = 0
        self._workout_power_sum = 0.0
        self._workout_power_count = 0
        self._interval_actual_kj = 0.0
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick: float | None = None
        self._interval_hr_sum = 0.0
        self._interval_hr_count = 0
        self._workout_hr_sum = 0.0
        self._workout_hr_count = 0
        self._active_interval_index: int | None = None
        self._last_power_watts: int | None = None
        self._last_bike_power_watts: int | None = None
        self._last_hr_bpm: int | None = None
        self._last_cadence_rpm: float | None = None
        self._last_speed_mps: float | None = None

        self._chart_start_monotonic: float | None = None
        self._pause_start_monotonic: float | None = None
        self._total_paused_duration: float = 0.0
        self._hr_history: list[tuple[float, int]] = []
        self._skip_events: list[tuple[float, float, float]] = []

        # Timers are created inactive; activated in _start_workout.
        self._timer = ui.timer(max(0.1, tick_interval_s), self.process_tick, active=False)
        self._chart_timer = ui.timer(1.0, self._on_chart_tick, active=False)

        self._wire_screen_actions()
        self._set_no_workout_state()

    # ── Public interface ──────────────────────────────────────────────────

    @property
    def last_snapshot(self) -> WorkoutEngineSnapshot | None:
        return self._last_snapshot

    def set_trainer_control_target(
        self,
        *,
        backend: object,
        trainer_device_id: str | None,
    ) -> None:
        self._trainer_backend = backend
        self._trainer_device_id = trainer_device_id
        self._reconfigure_ftms_bridge()

    def apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._engine.kj_mode = settings.default_workout_behavior == "kj_mode"
        was_enabled = self._opentrueup is not None
        now_enabled = settings.opentrueup_enabled
        if not was_enabled and now_enabled:
            self._opentrueup = self._make_opentrueup(settings)
        elif was_enabled and not now_enabled:
            self._opentrueup = None
            self._screen.set_opentrueup_offset_watts(None)
        self._reconfigure_ftms_bridge()

    def shutdown(self) -> None:
        self._timer.cancel()
        self._chart_timer.cancel()
        self._teardown_ftms_bridge()
        if self._recorder_active:
            self._finalize_recorder()
        if self._upload_executor is not None:
            self._upload_executor.shutdown(wait=False)

    def load_workout(self, path: Path) -> None:
        """Load a workout from *path* without opening a file dialog."""
        self._load_workout_from_file(path)

    def process_tick(self, now_monotonic: float | None = None) -> WorkoutEngineSnapshot | None:
        if self._engine.workout is None:
            return None
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        snapshot = self._engine.tick(now)
        self._handle_snapshot(snapshot, now_monotonic=now)
        if snapshot.state == EngineState.FINISHED:
            self._timer.deactivate()
            self._chart_timer.deactivate()
            self._finalize_recorder()
            self._show_workout_summary()
        return snapshot

    # ── Private helpers ───────────────────────────────────────────────────

    def _wire_screen_actions(self) -> None:
        self._screen.set_callbacks(
            on_start=self._start_workout,
            on_pause=self._pause_workout,
            on_resume=self._resume_workout,
            on_stop=self._stop_workout,
            on_load_file=self._request_load_workout_from_file,
            on_load_library=self._request_load_workout_from_library,
            on_mode_changed=self._mode_selected,
            on_jog=self._jog_target,
            on_extend=self._extend_interval,
            on_skip=self._skip_interval,
        )

    def _set_no_workout_state(self) -> None:
        self._workout = None
        self._screen.set_workout_name(None)
        self._screen.set_session_state("idle")
        self._screen.set_mandatory_metrics(
            elapsed_text="--:--:--",
            remaining_text="--:--:--",
            interval_remaining_text="--:--:--",
            target_power_text="-- W",
        )

    def _start_workout(self) -> None:
        if self._engine.workout is None:
            return
        if self._engine.state in {EngineState.RUNNING, EngineState.RAMP_IN}:
            return
        if self._engine.state == EngineState.PAUSED:
            self._resume_workout()
            return

        self._total_kj = 0.0
        self._interval_extra_seconds = {}
        self._manual_erg_jog_watts = 0.0
        self._last_energy_tick_monotonic = None
        self._power_history.clear()
        self._interval_power_sum = 0.0
        self._interval_power_count = 0
        self._workout_power_sum = 0.0
        self._workout_power_count = 0
        self._interval_actual_kj = 0.0
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick = None
        self._interval_hr_sum = 0.0
        self._interval_hr_count = 0
        self._workout_hr_sum = 0.0
        self._workout_hr_count = 0
        self._active_interval_index = None
        self._last_power_watts = None
        self._last_hr_bpm = None
        self._chart_start_monotonic = None
        self._pause_start_monotonic = None
        self._total_paused_duration = 0.0
        self._hr_history = []
        self._skip_events = []
        self._start_recorder()

        self._engine.start()
        now = float(self._monotonic_clock())
        self._chart_start_monotonic = now
        if self._workout is not None:
            self._screen.load_workout_chart(self._workout, int(self._settings.ftp))
        snapshot = self._engine.tick(now)
        self._timer.activate()
        self._chart_timer.activate()
        self._handle_snapshot(snapshot, now_monotonic=now)

    def _pause_workout(self) -> None:
        self._pause_start_monotonic = self._monotonic_clock()
        snapshot = self._engine.pause()
        self._handle_snapshot(snapshot, now_monotonic=None)
        if self._last_snapshot is not None:
            elapsed = int(round(self._last_snapshot.riding_elapsed_seconds))
            self._screen.set_pause_elapsed(_format_hh_mm_ss(elapsed))

    def _resume_workout(self) -> None:
        snapshot = self._engine.resume()
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _stop_workout(self) -> None:
        snapshot = self._engine.stop()
        self._timer.deactivate()
        self._chart_timer.deactivate()
        self._handle_snapshot(snapshot, now_monotonic=None)
        self._finalize_recorder()
        self._show_workout_summary()

    def _extend_interval(self, seconds_or_kj: int, is_kj_mode: bool) -> None:
        if bool(is_kj_mode) != self._engine.kj_mode:
            return
        snapshot = self._engine.extend_interval(int(seconds_or_kj))
        if not is_kj_mode and snapshot.current_interval_index is not None:
            current_index = int(snapshot.current_interval_index)
            current_extra = self._interval_extra_seconds.get(current_index, 0)
            self._interval_extra_seconds[current_index] = current_extra + int(seconds_or_kj)
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _skip_interval(self) -> None:
        elapsed_before = self._last_snapshot.elapsed_seconds if self._last_snapshot else 0.0
        mono_now = float(self._monotonic_clock())
        snapshot = self._engine.skip_interval()
        elapsed_after = snapshot.elapsed_seconds
        if elapsed_after > elapsed_before and self._chart_start_monotonic is not None:
            self._skip_events.append((mono_now, elapsed_before, elapsed_after))
            self._screen.add_skip_marker(elapsed_before, elapsed_after)
        self._handle_snapshot(snapshot, now_monotonic=None)
        if snapshot.state == EngineState.FINISHED:
            self._timer.deactivate()
            self._chart_timer.deactivate()
            self._finalize_recorder()
            self._show_workout_summary()

    def _jog_target(self, delta_percent: int) -> None:
        snapshot = self._last_snapshot or self._engine.snapshot()
        active_mode = self._active_control_mode(snapshot)

        if active_mode == "ERG":
            ftp = max(1, self._settings.ftp)
            delta_watts = (ftp * delta_percent) / 100.0
            self._manual_erg_jog_watts += delta_watts
            jog_watts = self._manual_erg_jog_watts
            self._submit_ftms_bridge_action(
                lambda bridge: bridge.set_erg_jog_offset_watts(jog_watts)
            )
        elif active_mode == "Resistance":
            updated = self._manual_resistance_offset_percent + float(delta_percent)
            self._manual_resistance_offset_percent = max(-100.0, min(100.0, updated))

        if self._last_snapshot:
            self._handle_snapshot(self._last_snapshot, now_monotonic=None)

    def _mode_selected(self, mode: str) -> None:
        from .workout_screen_ng import MODE_OPTIONS
        if mode not in MODE_OPTIONS:
            return
        self._selected_mode = mode
        self._handle_snapshot(self._engine.snapshot(), now_monotonic=None)

    def _load_workout_from_file(self, path: Path) -> None:
        self._screen.clear_alert()
        ftp = max(1, int(self._settings.ftp))
        try:
            workout = parse_mrc_file(path, ftp_watts=ftp)
        except MRCParseError:
            self._screen.show_alert(f"Could not load '{path.name}' — file format may be invalid")
            return
        except (IOError, OSError):
            self._screen.show_alert(
                f"Could not read '{path.name}' — check the file exists and is accessible"
            )
            return

        self._workout = workout
        self._interval_extra_seconds = {}
        self._manual_resistance_offset_percent = 0.0
        self._manual_erg_jog_watts = 0.0
        self._chart_timer.deactivate()
        self._screen.load_workout_chart(workout, ftp)
        snapshot = self._engine.load_workout(self._workout)
        self._screen.set_workout_name(self._workout.name)
        self._handle_snapshot(snapshot, now_monotonic=None)
        self._settings.last_workout_dir = path.parent
        save_settings(self._settings, self._settings_path)

    async def _request_load_workout_from_file(self) -> None:
        """Open a native file dialog and load the chosen MRC file."""
        start_dir = str(self._settings.last_workout_dir or Path.home())

        def _open_dialog() -> str:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.wm_attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    title="Load Workout File",
                    initialdir=start_dir,
                    filetypes=[("MRC Files", "*.mrc"), ("All Files", "*.*")],
                )
                root.destroy()
                return path or ""
            except Exception as exc:
                _logger.warning("File dialog failed: %s", exc)
                return ""

        path_str = await asyncio.to_thread(_open_dialog)
        if path_str:
            self._load_workout_from_file(Path(path_str))

    async def _request_load_workout_from_library(self) -> None:
        """Stub — Phase 5 will open the library browser."""

    def _handle_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        *,
        now_monotonic: float | None,
    ) -> None:
        prev_state = self._last_snapshot.state if self._last_snapshot is not None else None
        if prev_state == EngineState.RAMP_IN and snapshot.state == EngineState.RUNNING:
            if self._pause_start_monotonic is not None:
                self._total_paused_duration += self._monotonic_clock() - self._pause_start_monotonic
                self._pause_start_monotonic = None
        self._last_snapshot = snapshot
        self._screen.set_session_state(snapshot.state.value)
        self._screen.set_mode_state(self._selected_mode)

        active_mode = self._active_control_mode(snapshot)
        if active_mode == "Resistance":
            self._screen.set_resistance_level(int(self._manual_resistance_offset_percent))
        else:
            self._screen.set_resistance_level(None)

        current_index = snapshot.current_interval_index
        if current_index != self._active_interval_index:
            self._active_interval_index = current_index
            self._reset_interval_accumulators()
            self._manual_erg_jog_watts = 0.0

        elapsed_seconds = int(round(snapshot.riding_elapsed_seconds))
        remaining_seconds = max(
            int(snapshot.total_duration_seconds) - int(round(snapshot.elapsed_seconds)), 0
        )
        interval_remaining_seconds = self._interval_remaining_seconds(snapshot)
        target_watts = self._resolve_target_watts(snapshot) or self._workout_target_watts(snapshot)
        self._screen.set_mandatory_metrics(
            elapsed_text=_format_hh_mm_ss(elapsed_seconds),
            remaining_text=_format_hh_mm_ss(remaining_seconds),
            interval_remaining_text=_format_hh_mm_ss(interval_remaining_seconds),
            target_power_text=f"{target_watts} W" if target_watts is not None else "-- W",
        )

        self._update_tiles(snapshot)
        self._submit_snapshot_to_ftms_bridge(snapshot)

        if self._recorder_active:
            self._sync_recorder(snapshot, now_monotonic=now_monotonic)

    def _interval_remaining_seconds(self, snapshot: WorkoutEngineSnapshot) -> int:
        index = snapshot.current_interval_index
        if index is None or self._workout is None:
            return 0
        if index < 0 or index >= len(self._workout.intervals):
            return 0
        base_duration = int(self._workout.intervals[index].duration_seconds)
        interval_duration = base_duration + self._interval_extra_seconds.get(index, 0)
        elapsed = int(round(snapshot.current_interval_elapsed_seconds or 0.0))
        return max(interval_duration - elapsed, 0)

    def _sync_recorder(
        self,
        snapshot: WorkoutEngineSnapshot,
        *,
        now_monotonic: float | None,
    ) -> None:
        try:
            self._recorder.set_recording_active(snapshot.recording_active)
        except RuntimeError as exc:
            _logger.warning("Recorder set_recording_active failed: %s", exc)
            self._recorder_active = False
            return

        if now_monotonic is not None:
            self._update_total_kj(snapshot, now_monotonic)

        target_watts = self._resolve_target_watts(snapshot)
        active_mode = self._active_control_mode(snapshot)
        erg_setpoint = target_watts if active_mode == "ERG" else None

        try:
            self._recorder.record_sample(
                RecorderSample(
                    timestamp_utc=self._utc_now(),
                    target_power_watts=target_watts,
                    trainer_power_watts=self._last_power_watts,
                    bike_power_watts=self._last_bike_power_watts,
                    heart_rate_bpm=self._last_hr_bpm,
                    cadence_rpm=self._last_cadence_rpm,
                    speed_mps=self._last_speed_mps,
                    mode=active_mode,
                    erg_setpoint_watts=erg_setpoint,
                    total_kj=round(self._total_kj, 3),
                ),
            )
        except RuntimeError as exc:
            _logger.warning("Recorder record_sample failed: %s", exc)
            self._recorder_active = False

    def _update_total_kj(self, snapshot: WorkoutEngineSnapshot, now_monotonic: float) -> None:
        last_tick = self._last_energy_tick_monotonic
        self._last_energy_tick_monotonic = float(now_monotonic)
        if last_tick is None:
            return
        delta_seconds = float(now_monotonic) - float(last_tick)
        if delta_seconds <= 0 or not snapshot.recording_active:
            return
        target_watts = self._resolve_target_watts(snapshot)
        if target_watts is None or target_watts <= 0:
            return
        self._total_kj += (float(target_watts) * delta_seconds) / 1000.0

    def _workout_target_watts(self, snapshot: WorkoutEngineSnapshot) -> int | None:
        if self._workout is None:
            return None
        index = snapshot.current_interval_index
        if index is None or index < 0 or index >= len(self._workout.intervals):
            return None
        interval = self._workout.intervals[index]
        elapsed = float(snapshot.current_interval_elapsed_seconds or 0.0)
        duration = max(float(interval.duration_seconds), 1.0)
        ratio = min(max(elapsed, 0.0), duration) / duration
        target = float(interval.start_target_watts) + (
            float(interval.end_target_watts) - float(interval.start_target_watts)
        ) * ratio
        return int(round(target))

    def _resolve_target_watts(self, snapshot: WorkoutEngineSnapshot) -> int | None:
        if self._workout is None or self._active_control_mode(snapshot) != "ERG":
            return None
        index = snapshot.current_interval_index
        if index is None or index < 0 or index >= len(self._workout.intervals):
            return None
        interval = self._workout.intervals[index]
        elapsed = float(snapshot.current_interval_elapsed_seconds or 0.0)
        duration = max(float(interval.duration_seconds), 1.0)
        ratio = min(max(elapsed, 0.0), duration) / duration
        target = float(interval.start_target_watts) + (
            float(interval.end_target_watts) - float(interval.start_target_watts)
        ) * ratio
        return int(round(max(0, target + self._manual_erg_jog_watts)))

    def _active_control_mode(self, snapshot: WorkoutEngineSnapshot) -> str:
        if self._selected_mode in ("ERG", "Resistance"):
            return self._selected_mode
        if self._selected_mode != "Hybrid" or self._workout is None:
            return "ERG"
        index = snapshot.current_interval_index
        if index is None or index < 0 or index >= len(self._workout.intervals):
            return "ERG"
        interval = self._workout.intervals[index]
        if interval.start_percent_ftp < RECOVERY_THRESHOLD_PERCENT:
            return "ERG"
        return "Resistance"

    def _start_recorder(self) -> None:
        if self._workout is None or self._recorder_started:
            return
        self._recorder.start(
            workout_name=self._workout.name,
            started_at_utc=self._utc_now(),
        )
        self._recorder_active = True
        self._recorder_started = True

    def _finalize_recorder(self) -> None:
        if not self._recorder_started:
            return
        self._recorder_started = False
        self._recorder_active = False
        try:
            summary = self._recorder.stop(finished_at_utc=self._utc_now())
        except RuntimeError as exc:
            _logger.warning("Recorder stop failed: %s", exc)
            return
        self._screen.show_alert(
            f"Workout saved: {summary.fit_file_path.name}",
            alert_type="success",
        )
        if self._settings.strava_auto_sync_enabled and self._strava_upload_fn is not None:
            chart_image_path = summary.fit_file_path.with_suffix(".png")
            self._screen.export_chart_image(chart_image_path)
            self._enqueue_strava_upload(summary.fit_file_path, chart_image_path)

    def _enqueue_strava_upload(self, fit_path: Path, chart_image_path: Path | None) -> None:
        from concurrent.futures import Future  # noqa: PLC0415
        if self._upload_executor is None:
            self._upload_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="strava_upload",
            )
        fut: Future[None] = self._upload_executor.submit(
            self._strava_upload_fn, fit_path, chart_image_path
        )
        fut.add_done_callback(self._on_upload_done)

    def _on_upload_done(self, future: object) -> None:
        from concurrent.futures import Future  # noqa: PLC0415
        from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError  # noqa: PLC0415
        if not isinstance(future, Future):
            return
        exc = future.exception()
        if exc is None:
            self._screen.show_alert("Ride synced to Strava", "success")
        elif isinstance(exc, DuplicateUploadError):
            self._screen.show_alert("Ride already synced to Strava", "info")
        else:
            _logger.warning("Strava upload failed: %s", exc)
            self._screen.show_alert("Strava sync failed (ride kept locally)", "error")

    def _show_workout_summary(self) -> None:
        elapsed = self._last_snapshot.elapsed_seconds if self._last_snapshot else 0.0
        np_watts = self._compute_normalized_power()
        ftp = max(1, int(self._settings.ftp))
        tss = compute_tss(np_watts, ftp, elapsed)
        avg_hr = (
            int(self._workout_hr_sum / self._workout_hr_count)
            if self._workout_hr_count > 0
            else None
        )
        summary = WorkoutSummary(
            elapsed_seconds=elapsed,
            kj=self._workout_actual_kj,
            normalized_power=np_watts,
            tss=tss,
            avg_hr=avg_hr,
        )
        self._summary_dialog_factory(summary, self._set_no_workout_state)

    def receive_power_watts(self, watts: int | None, now_monotonic: float | None = None) -> None:
        """Feed a live trainer power reading (W) into the metric computation pipeline."""
        self._last_power_watts = watts
        if watts is None:
            return
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        self._power_history.append((now, int(watts)))
        self._interval_power_sum += float(watts)
        self._interval_power_count += 1
        self._workout_power_sum += float(watts)
        self._workout_power_count += 1
        if self._last_actual_power_tick is not None:
            delta = now - self._last_actual_power_tick
            if delta > 0 and self._last_snapshot is not None and self._last_snapshot.recording_active:
                kj = float(watts) * delta / 1000.0
                self._interval_actual_kj += kj
                self._workout_actual_kj += kj
        self._last_actual_power_tick = now
        self._dispatch_power_sample(timestamp=now, trainer_watts=watts, bike_watts=None)

    def receive_bike_power_watts(self, watts: int | None, now_monotonic: float | None = None) -> None:
        """Feed a live bike power meter reading (W) for OpenTrueUp offset computation."""
        self._last_bike_power_watts = watts
        if watts is None:
            return
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        self._dispatch_power_sample(timestamp=now, trainer_watts=None, bike_watts=watts)

    def receive_hr_bpm(self, bpm: int | None) -> None:
        """Feed a live heart rate reading (bpm) into the metric computation pipeline."""
        self._last_hr_bpm = bpm
        if bpm is None:
            return
        self._interval_hr_sum += float(bpm)
        self._interval_hr_count += 1
        self._workout_hr_sum += float(bpm)
        self._workout_hr_count += 1
        if self._recorder_active and self._chart_start_monotonic is not None:
            self._hr_history.append((float(self._monotonic_clock()), int(bpm)))

    def receive_cadence_rpm(self, rpm: float | None) -> None:
        """Feed a live cadence reading (rpm) for inclusion in recorder samples."""
        self._last_cadence_rpm = rpm
        if rpm is not None:
            now = float(self._monotonic_clock())
            self._cadence_history.append((now, rpm))

    def receive_speed_mps(self, mps: float | None) -> None:
        """Feed a live speed reading (m/s) for inclusion in recorder samples."""
        self._last_speed_mps = mps

    def _dispatch_power_sample(
        self,
        *,
        timestamp: float,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> None:
        if self._ftms_bridge is not None and self._ftms_bridge_executor is not None:
            self._submit_ftms_bridge_action(
                lambda bridge: bridge.on_power_sample(
                    timestamp=timestamp,
                    trainer_power_watts=trainer_watts,
                    bike_power_watts=bike_watts,
                ),
            )
            return
        self._feed_opentrueup(timestamp, trainer_watts=trainer_watts, bike_watts=bike_watts)

    def _submit_snapshot_to_ftms_bridge(self, snapshot: WorkoutEngineSnapshot) -> None:
        self._submit_ftms_bridge_action(
            lambda bridge: self._apply_snapshot_to_bridge(bridge, snapshot),
        )

    def _apply_snapshot_to_bridge(
        self,
        bridge: WorkoutEngineFTMSBridge,
        snapshot: WorkoutEngineSnapshot,
    ) -> None:
        active_mode = self._active_control_mode(snapshot)
        if active_mode == "Resistance":
            bridge.set_mode_resistance()
        else:
            bridge.set_mode_erg()
        bridge.on_engine_snapshot(snapshot, self._workout)

    def _submit_ftms_bridge_action(
        self,
        action: Callable[[WorkoutEngineFTMSBridge], None],
    ) -> None:
        bridge = self._ftms_bridge
        executor = self._ftms_bridge_executor
        if bridge is None or executor is None:
            return

        def _run() -> None:
            current_bridge = self._ftms_bridge
            if current_bridge is not bridge:
                return
            action(current_bridge)

        executor.submit(_run)

    def _reconfigure_ftms_bridge(self) -> None:
        self._teardown_ftms_bridge()
        if self._trainer_device_id is None or self._trainer_backend is None:
            self._screen.set_trainer_controls_visible(False)
            return
        transport = self._create_ftms_transport(self._trainer_backend, self._trainer_device_id)
        if transport is None:
            self._screen.set_trainer_controls_visible(False)
            return

        initial_snapshot = (
            self._last_snapshot if self._last_snapshot is not None else self._engine.snapshot()
        )
        initial_mode = (
            ControlMode.RESISTANCE
            if self._active_control_mode(initial_snapshot) == "Resistance"
            else ControlMode.ERG
        )
        try:
            control = FTMSControl(transport)
        except Exception as exc:
            _logger.error("Failed to initialise FTMSControl: %s", exc)
            self._screen.show_alert("Could not connect to trainer")
            self._screen.set_trainer_controls_visible(False)
            return

        self._ftms_bridge = WorkoutEngineFTMSBridge(
            control,
            mode=initial_mode,
            alert_callback=self._screen.show_alert,
            opentrueup=self._opentrueup,
            opentrueup_status_callback=self._handle_bridge_opentrueup_status,
            lead_time_seconds=max(0, int(self._settings.lead_time)),
            kj_mode=self._engine.kj_mode,
        )
        self._ftms_bridge_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ftms-bridge",
        )
        self._submit_snapshot_to_ftms_bridge(initial_snapshot)
        self._screen.set_trainer_controls_visible(True)

    def _teardown_ftms_bridge(self) -> None:
        executor = self._ftms_bridge_executor
        self._ftms_bridge_executor = None
        self._ftms_bridge = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _create_ftms_transport(
        self,
        backend: object,
        trainer_device_id: str,
    ) -> FTMSControlTransport | None:
        try:
            return self._ftms_transport_factory(backend, trainer_device_id)
        except Exception as exc:
            _logger.error("Failed to create FTMS transport: %s", exc)
            self._screen.show_alert("Could not connect to trainer")
            return None

    def _handle_bridge_opentrueup_status(self, status: object) -> None:
        offset = getattr(status, "last_computed_offset_watts", None)
        self._screen.set_opentrueup_offset_watts(offset)

    @staticmethod
    def _default_ftms_transport_factory(
        backend: object,
        trainer_device_id: str,
    ) -> FTMSControlTransport | None:
        if not isinstance(backend, BleakDeviceBackend):
            return None
        return BleakFTMSControlTransport(backend, trainer_device_id)

    def _feed_opentrueup(
        self,
        now: float,
        *,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> None:
        if self._opentrueup is None:
            return
        try:
            status = self._opentrueup.record_power_sample(
                timestamp=now,
                trainer_power_watts=trainer_watts,
                bike_power_watts=bike_watts,
            )
        except ValueError:
            return
        self._screen.set_opentrueup_offset_watts(status.last_computed_offset_watts)

    @staticmethod
    def _make_opentrueup(settings: AppSettings) -> OpenTrueUpController | None:
        if not settings.opentrueup_enabled:
            return None
        return OpenTrueUpController(enabled=True, offset_store=OpenTrueUpOffsetStore())

    def _reset_interval_accumulators(self) -> None:
        self._interval_power_sum = 0.0
        self._interval_power_count = 0
        self._interval_actual_kj = 0.0
        self._last_actual_power_tick = None
        self._interval_hr_sum = 0.0
        self._interval_hr_count = 0

    def _update_tiles(self, snapshot: WorkoutEngineSnapshot) -> None:
        for key in self._screen.get_selected_tile_keys():
            self._screen.set_tile_value(key, self._compute_tile_value(key, snapshot))

    def _compute_tile_value(self, key: str, snapshot: WorkoutEngineSnapshot) -> str:  # noqa: ARG002
        ftp = max(1, int(self._settings.ftp))
        window = max(1, int(self._settings.windowed_power_window_seconds))
        now = self._monotonic_clock()

        if key == "windowed_avg_power":
            val = self._windowed_avg_power(now, window)
            return f"{val} W" if val is not None else "--"
        if key == "windowed_avg_ftp":
            val = self._windowed_avg_power(now, window)
            return f"{round(val / ftp * 100)} %" if val is not None else "--"
        if key == "interval_avg_power":
            if not self._interval_power_count:
                return "--"
            return f"{round(self._interval_power_sum / self._interval_power_count)} W"
        if key == "workout_avg_power":
            if not self._workout_power_count:
                return "--"
            return f"{round(self._workout_power_sum / self._workout_power_count)} W"
        if key == "workout_normalized_power":
            val = self._compute_normalized_power()
            return f"{val} W" if val is not None else "--"
        if key == "heart_rate":
            return f"{self._last_hr_bpm} bpm" if self._last_hr_bpm is not None else "--"
        if key == "workout_avg_hr":
            if not self._workout_hr_count:
                return "--"
            return f"{round(self._workout_hr_sum / self._workout_hr_count)} bpm"
        if key == "interval_avg_hr":
            if not self._interval_hr_count:
                return "--"
            return f"{round(self._interval_hr_sum / self._interval_hr_count)} bpm"
        if key == "kj_work_completed":
            if not self._workout_power_count:
                return "--"
            return f"{self._workout_actual_kj:.1f} kJ"
        if key == "kj_work_completed_interval":
            if not self._interval_power_count:
                return "--"
            return f"{self._interval_actual_kj:.1f} kJ"
        if key == "cadence_rpm":
            val = self._windowed_avg_cadence(now)
            return f"{val} rpm" if val is not None else "--"
        return "--"

    def _windowed_avg_power(self, now: float, window_seconds: int) -> int | None:
        cutoff = now - float(window_seconds)
        in_window = [w for t, w in self._power_history if t >= cutoff]
        if not in_window:
            return None
        return round(sum(in_window) / len(in_window))

    def _windowed_avg_cadence(self, now: float) -> int | None:
        """Return average cadence (rpm) over the last 1 second, or None if no data."""
        cutoff = now - 1.0
        in_window = [rpm for t, rpm in self._cadence_history if t >= cutoff]
        if not in_window:
            return None
        return round(sum(in_window) / len(in_window))

    def _on_chart_tick(self) -> None:
        if self._chart_start_monotonic is None:
            return
        now = self._monotonic_clock()
        skip_offset = sum(after - before for _, before, after in self._skip_events)
        paused = self._total_paused_duration
        if self._pause_start_monotonic is not None:
            paused += now - self._pause_start_monotonic
        elapsed = (now - self._chart_start_monotonic) + skip_offset - paused

        def _adjusted_time(sample_mono: float) -> float:
            offset = sum(
                after - before
                for skip_mono, before, after in self._skip_events
                if skip_mono <= sample_mono
            )
            return (sample_mono - self._chart_start_monotonic) + offset  # type: ignore[operator]

        power_series = [(_adjusted_time(mono), watts) for mono, watts in self._power_history]
        hr_series = [(_adjusted_time(mono), bpm) for mono, bpm in self._hr_history]
        interval_index = (
            self._last_snapshot.current_interval_index
            if self._last_snapshot is not None
            else None
        )
        self._screen.update_charts(elapsed, interval_index, power_series, hr_series)

    def _compute_normalized_power(self) -> int | None:
        samples = list(self._power_history)
        if len(samples) < 2:
            return None
        start_t = samples[0][0]
        end_t = samples[-1][0]
        if end_t - start_t < 30.0:
            return None
        n_bins = int(end_t - start_t) + 1
        bins: list[list[int]] = [[] for _ in range(n_bins)]
        for t, w in samples:
            idx = min(int(t - start_t), n_bins - 1)
            bins[idx].append(w)
        one_sec = [sum(b) / len(b) if b else 0.0 for b in bins]
        if len(one_sec) < 30:
            return None
        window_sum = sum(one_sec[:30])
        fourth_powers = [(window_sum / 30.0) ** 4]
        for i in range(30, len(one_sec)):
            window_sum += one_sec[i] - one_sec[i - 30]
            fourth_powers.append((window_sum / 30.0) ** 4)
        return int(round((sum(fourth_powers) / len(fourth_powers)) ** 0.25))


def _format_hh_mm_ss(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02}"
