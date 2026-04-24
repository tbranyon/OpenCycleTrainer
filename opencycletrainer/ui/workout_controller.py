from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
from pathlib import Path
import time

_logger = logging.getLogger(__name__)

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QFileDialog

from opencycletrainer.core.control.ftms_control import FTMSControlTransport
from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.devices.ble_backend import BleakDeviceBackend, BleakFTMSControlTransport
from opencycletrainer.core.mrc_parser import MRCParseError, parse_mrc_file
from opencycletrainer.core.cadence_history import CadenceHistory
from opencycletrainer.core.interval_stats import IntervalStats
from opencycletrainer.core.power_history import PowerHistory
from opencycletrainer.core.recorder import WorkoutRecorder
from opencycletrainer.core.sensors import CadenceSource, PowerSource
from opencycletrainer.core.workout_engine import EngineState, WorkoutEngine, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.storage.settings import AppSettings, save_settings

from .chart_history import ChartHistory
from .ftms_bridge_manager import FTMSBridgeManager
from .opentrueup_state import OpenTrueUpState
from .mode_state import (
    DEFAULT_FREE_RIDE_ERG_TARGET_WATTS,
    DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT,
    ModeState,
)
from .pause_state import PauseState
from .recorder_integration import RecorderIntegration, SensorSnapshot
from .tile_computation import TileComputation
from .trainer_connection import TrainerConnection
from .workout_screen import MODE_OPTIONS, PauseDialog, WorkoutScreen
from .workout_summary_dialog import WorkoutSummary, WorkoutSummaryDialog, compute_tss


_POWER_STALE_PAUSE_SECONDS = 3.0


class WorkoutSessionController(QObject):
    """Connects WorkoutScreen controls/hotkeys to the workout engine runtime loop."""
    _bridge_alert_signal = Signal(str)
    _opentrueup_offset_signal = Signal(object)
    _strava_alert_signal = Signal(str, str)

    def __init__(
        self,
        *,
        screen: WorkoutScreen,
        settings: AppSettings,
        settings_path: Path | None = None,
        recorder: WorkoutRecorder | None = None,
        opentrueup: OpenTrueUpController | None = None,
        ftms_transport_factory: Callable[[object, str], FTMSControlTransport | None] | None = None,
        summary_dialog_factory: Callable[[WorkoutSummary, object], object] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        strava_upload_fn: Callable[[Path, Path | None], None] | None = None,
        tick_interval_ms: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
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
        self._summary_dialog_factory = (
            summary_dialog_factory
            if summary_dialog_factory is not None
            else lambda summary, parent: WorkoutSummaryDialog(summary, parent)
        )
        self._opentrueup_state = (
            OpenTrueUpState(opentrueup, self._opentrueup_offset_signal.emit)
            if opentrueup is not None
            else OpenTrueUpState.from_settings(settings, self._opentrueup_offset_signal.emit)
        )
        self._engine = WorkoutEngine(
            kj_mode=self._settings.default_workout_behavior == "kj_mode",
        )
        self._workout: Workout | None = None
        self._mode_state = ModeState(self._screen.mode_selector.currentText())
        self._interval_extra_seconds: dict[int, int] = {}
        self._last_snapshot: WorkoutEngineSnapshot | None = None

        self._power_history = PowerHistory()
        self._cadence_hist = CadenceHistory()
        self._interval_stats = IntervalStats()
        self._active_interval_index: int | None = None
        self._last_power_watts: int | None = None
        self._last_bike_power_watts: int | None = None
        self._last_hr_bpm: int | None = None
        self._last_speed_mps: float | None = None
        self._last_power_received_at: float | None = None

        self._pause_state = PauseState(self._screen, self._resume_workout)
        self._chart_history = ChartHistory(
            self._screen,
            self._monotonic_clock,
            self._power_history,
            self._pause_state,
        )
        self._recorder_integration = RecorderIntegration(
            recorder=self._recorder,
            screen=self._screen,
            settings=self._settings,
            utc_now=self._utc_now,
            strava_upload_fn=strava_upload_fn,
            alert_signal=self._strava_alert_signal.emit,
            mode_state=self._mode_state,
        )
        self._ftms_bridge_manager = FTMSBridgeManager(
            transport_factory=self._ftms_transport_factory,
            screen=self._screen,
            alert_signal=self._bridge_alert_signal.emit,
            opentrueup_state=self._opentrueup_state,
            mode_state=self._mode_state,
            settings=self._settings,
            engine=self._engine,
        )

        self._tile_computation = TileComputation(
            self._power_history,
            self._cadence_hist,
            self._interval_stats,
            self._monotonic_clock,
            lambda: self._last_hr_bpm,
        )

        self._timer = QTimer(self)
        self._timer.setInterval(max(100, int(tick_interval_ms)))
        self._timer.timeout.connect(self.process_tick)

        self._trainer_connection = TrainerConnection(
            screen=self._screen,
            is_workout_active=self._timer.isActive,
        )
        self._power_source_trainer_id: str | None = None
        self._power_source_meter_id: str | None = None

        self._chart_history.chart_timer.timeout.connect(self._on_chart_tick)

        self._wire_screen_actions()
        self._set_no_workout_state()
        self._bridge_alert_signal.connect(self._screen.show_alert)
        self._opentrueup_offset_signal.connect(self._screen.set_opentrueup_offset_watts)
        self._strava_alert_signal.connect(self._screen.show_alert)

    @property
    def last_snapshot(self) -> WorkoutEngineSnapshot | None:
        return self._last_snapshot

    def set_trainer_control_target(
        self,
        *,
        backend: object,
        trainer_device_id: str | None,
    ) -> None:
        self._trainer_connection.set_target(backend, trainer_device_id)
        self._ftms_bridge_manager.configure(
            backend, trainer_device_id, self._workout, self._last_snapshot
        )

    def set_power_source_pair(
        self,
        trainer_device_id: str | None,
        power_meter_device_id: str | None,
    ) -> None:
        """Update the active trainer + power meter pairing used for persistence."""
        self._power_source_trainer_id = trainer_device_id
        self._power_source_meter_id = power_meter_device_id
        self._opentrueup_state.configure_pair(
            self._settings,
            trainer_device_id,
            power_meter_device_id,
        )

    def apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._engine.kj_mode = settings.default_workout_behavior == "kj_mode"
        self._recorder_integration.configure_data_dir(settings)
        was_enabled = self._opentrueup_state.enabled
        now_enabled = settings.opentrueup_enabled
        if not was_enabled and now_enabled:
            self._opentrueup_state.enable(
                settings,
                self._power_source_trainer_id,
                self._power_source_meter_id,
            )
        elif was_enabled and not now_enabled:
            self._opentrueup_state.disable()
        self._ftms_bridge_manager.configure(
            self._trainer_connection.backend,
            self._trainer_connection.device_id,
            self._workout,
            self._last_snapshot,
        )

    def shutdown(self) -> None:
        self._timer.stop()
        self._chart_history.stop()
        self._ftms_bridge_manager.teardown()
        self._recorder_integration.shutdown()

    def process_tick(self, now_monotonic: float | None = None) -> WorkoutEngineSnapshot | None:
        if self._engine.workout is None:
            return None
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        if (
            self._engine.state == EngineState.RUNNING
            and self._last_power_received_at is not None
            and now - self._last_power_received_at > _POWER_STALE_PAUSE_SECONDS
        ):
            self._pause_workout()
            return self._last_snapshot
        snapshot = self._engine.tick(now)
        self._handle_snapshot(snapshot, now_monotonic=now)
        if snapshot.state == EngineState.FINISHED:
            self._timer.stop()
            recorder_summary = self._recorder_integration.finalize(self._workout)
            self._show_workout_summary(recorder_summary)
        return snapshot

    def _wire_screen_actions(self) -> None:
        self._screen.start_button.clicked.connect(self._start_workout)
        self._screen.pause_button.clicked.connect(self._pause_workout)
        self._screen.resume_button.clicked.connect(self._resume_workout)
        self._screen.end_button.clicked.connect(self._stop_workout)
        self._screen.extend_interval_requested.connect(self._extend_interval)
        self._screen.skip_interval_requested.connect(self._skip_interval)
        self._screen.jog_requested.connect(self._jog_target)
        self._screen.mode_selector.currentTextChanged.connect(self._mode_selected)
        self._screen.load_workout_requested.connect(self._request_load_workout_from_file)
        self._screen.free_ride_requested.connect(self._start_free_ride)
        self._screen.erg_target_entered.connect(self._on_erg_target_entered)

    def _set_no_workout_state(self) -> None:
        self._workout = None
        if self._mode_state.is_free_ride:
            self._mode_state.set_free_ride(False, None)
            self._screen.set_free_ride_mode(False)
            self._screen.set_interval_plot_visible(True)
        self._screen.set_workout_name(None)
        self._screen.set_session_state("idle")
        self._screen.set_mandatory_metrics(
            elapsed_text="--:--:--",
            remaining_text="--:--:--",
            interval_remaining_text="--:--:--",
            target_power_text="-- W",
        )

    def load_workout(self, path: Path) -> None:
        """Load a workout from *path* without opening a file dialog."""
        self._load_workout_from_file(path)

    def _request_load_workout_from_file(self) -> None:
        start_dir = str(self._settings.last_workout_dir or Path.home())
        file_path_str, _ = QFileDialog.getOpenFileName(
            self._screen,
            "Load Workout File",
            start_dir,
            "MRC Files (*.mrc)",
        )
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        self._load_workout_from_file(file_path)

    def _load_workout_from_file(self, path: Path) -> None:
        self._screen.clear_alert()
        ftp = max(1, int(self._settings.ftp))
        try:
            workout = parse_mrc_file(path, ftp_watts=ftp)
        except MRCParseError as exc:
            self._screen.show_alert(f"Could not load '{path.name}' — file format may be invalid")
            return
        except (IOError, OSError) as exc:
            self._screen.show_alert(f"Could not read '{path.name}' — check the file exists and is accessible")
            return

        self._workout = workout
        self._interval_extra_seconds = {}
        self._mode_state._manual_resistance_offset_percent = DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT
        self._mode_state.reset_jog()
        self._chart_history.stop()
        self._screen.load_workout_chart(workout, ftp)
        snapshot = self._engine.load_workout(self._workout)
        self._screen.set_workout_name(self._workout.name)
        self._handle_snapshot(snapshot, now_monotonic=None)
        self._settings.last_workout_dir = path.parent
        save_settings(self._settings, self._settings_path)

    def _start_workout(self) -> None:
        if self._engine.workout is None:
            return 

        if self._engine.state in {EngineState.RUNNING, EngineState.RAMP_IN}:
            return
        if self._engine.state == EngineState.PAUSED:
            self._resume_workout()
            return

        self._interval_extra_seconds = {}
        self._mode_state.reset_jog()
        self._power_history.reset()
        self._interval_stats.reset_workout()
        self._active_interval_index = None
        self._last_power_watts = None
        self._last_bike_power_watts = None
        self._last_hr_bpm = None
        self._last_power_received_at = None
        self._chart_history.reset()
        self._pause_state.reset()
        self._recorder_integration.start(self._workout, self._utc_now())

        self._engine.start()
        now = float(self._monotonic_clock())
        self._chart_history.start(now)
        if self._workout is not None:
            self._screen.load_workout_chart(self._workout, int(self._settings.ftp))
        snapshot = self._engine.tick(now)
        self._timer.start()
        self._handle_snapshot(snapshot, now_monotonic=now)

    def _start_free_ride(self) -> None:
        if self._engine.state in {EngineState.RUNNING, EngineState.RAMP_IN, EngineState.PAUSED}:
            return

        self._mode_state.set_free_ride(True, DEFAULT_FREE_RIDE_ERG_TARGET_WATTS)
        self._mode_state.reset_jog()
        self._interval_extra_seconds = {}
        self._power_history.reset()
        self._interval_stats.reset_workout()
        self._active_interval_index = None
        self._last_power_watts = None
        self._last_bike_power_watts = None
        self._last_hr_bpm = None
        self._last_power_received_at = None
        self._chart_history.reset()
        self._pause_state.reset()

        ftp = max(1, int(self._settings.ftp))
        interval = WorkoutInterval(
            start_offset_seconds=0,
            duration_seconds=86400,
            start_percent_ftp=0.0,
            end_percent_ftp=0.0,
            start_target_watts=0,
            end_target_watts=0,
        )
        synthetic = Workout(name="Free Ride", ftp_watts=ftp, intervals=(interval,))
        self._workout = synthetic
        self._engine.load_workout(synthetic)

        self._mode_state.select_mode("Resistance")
        self._screen.set_mode_state("Resistance")
        self._screen.set_free_ride_mode(True)
        self._screen.set_interval_plot_visible(False)
        self._screen.load_free_ride_chart()
        self._screen.set_workout_name("Free Ride")

        self._recorder_integration.start(self._workout, self._utc_now())
        self._engine.start()
        now = float(self._monotonic_clock())
        self._chart_history.start(now)
        snapshot = self._engine.tick(now)
        self._timer.start()
        self._handle_snapshot(snapshot, now_monotonic=now)

    def _on_erg_target_entered(self, watts: int) -> None:
        """Switch to ERG mode with the given watt target entered by the user in free ride."""
        self._mode_state.set_erg_target(watts)
        self._screen.set_mode_state("ERG")
        jog_offset = 0.0
        self._ftms_bridge_manager.submit_action(
            lambda bridge: bridge.set_erg_jog_offset_watts(jog_offset)
        )
        if self._last_snapshot:
            self._handle_snapshot(self._last_snapshot, now_monotonic=None)

    def _pause_workout(self) -> None:
        now = self._monotonic_clock()
        snapshot = self._engine.pause()
        self._handle_snapshot(snapshot, now_monotonic=None)
        self._pause_state.pause(now)

    def _resume_workout(self) -> None:
        # _pause_start_monotonic remains set intentionally: the cursor stays frozen
        # through RAMP_IN. It is accumulated and cleared when RAMP_IN → RUNNING
        # is detected in _handle_snapshot.
        snapshot = self._engine.resume()
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _stop_workout(self) -> None:
        self._pause_state.close_dialog()
        snapshot = self._engine.stop()
        self._timer.stop()
        self._chart_history.stop()
        if self._mode_state.is_free_ride:
            self._mode_state.set_free_ride(False, None)
            self._screen.set_free_ride_mode(False)
            self._screen.set_interval_plot_visible(True)
        self._handle_snapshot(snapshot, now_monotonic=None)
        recorder_summary = self._recorder_integration.finalize(self._workout)
        self._show_workout_summary(recorder_summary)

    def _extend_interval(self, seconds_or_kj: int, is_kj_mode: bool) -> None:
        if bool(is_kj_mode) != self._engine.kj_mode:
            return
        snapshot = self._engine.extend_interval(int(seconds_or_kj))
        if not is_kj_mode and snapshot.current_interval_index is not None:
            current_index = int(snapshot.current_interval_index)
            current_extra = self._interval_extra_seconds.get(current_index, 0)
            self._interval_extra_seconds[current_index] = current_extra + int(seconds_or_kj)
            self._screen.rebuild_target_series(self._engine.interval_durations)
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _skip_interval(self) -> None:
        elapsed_before = self._last_snapshot.elapsed_seconds if self._last_snapshot else 0.0
        mono_now = float(self._monotonic_clock())
        snapshot = self._engine.skip_interval()
        elapsed_after = snapshot.elapsed_seconds
        if elapsed_after > elapsed_before and self._chart_history.chart_start_monotonic is not None:
            self._chart_history.record_skip(mono_now, elapsed_before, elapsed_after)
            self._screen.add_skip_marker(elapsed_before, elapsed_after)
        self._handle_snapshot(snapshot, now_monotonic=None)
        if snapshot.state == EngineState.FINISHED:
            self._timer.stop()
            self._chart_history.stop()
            recorder_summary = self._recorder_integration.finalize(self._workout)
            self._show_workout_summary(recorder_summary)

    def _jog_target(self, delta_percent: int) -> None:
        snapshot = self._last_snapshot or self._engine.snapshot()
        self._mode_state.jog(delta_percent, max(1, self._settings.ftp), snapshot, self._workout)

        active_mode = self._mode_state.active_control_mode(snapshot, self._workout)
        if active_mode == "ERG":
            jog_watts = self._mode_state.erg_jog_watts
            self._ftms_bridge_manager.submit_action(
                lambda bridge: bridge.set_erg_jog_offset_watts(jog_watts)
            )
        # TODO: Resistance jog needs to send an update to the FTMS bridge when
        # bridge.set_resistance_level() is implemented.

        # Force an immediate update of the trainer target
        if self._last_snapshot:
            self._handle_snapshot(self._last_snapshot, now_monotonic=None)

    def _mode_selected(self, mode: str) -> None:
        if mode not in MODE_OPTIONS:
            return
        self._mode_state.select_mode(mode)
        self._handle_snapshot(self._engine.snapshot(), now_monotonic=None)

    def _handle_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        *,
        now_monotonic: float | None,
    ) -> None:
        prev_state = self._last_snapshot.state if self._last_snapshot is not None else None
        if prev_state == EngineState.RAMP_IN and snapshot.state == EngineState.RUNNING:
            self._pause_state.on_ramp_in_to_running(self._monotonic_clock())
        self._last_snapshot = snapshot
        self._screen.set_session_state(snapshot.state.value)
        self._screen.set_mode_state(self._mode_state.selected_mode)

        active_mode = self._mode_state.active_control_mode(snapshot, self._workout)
        if active_mode == "Resistance":
            value, show_percent = self._mode_state.resistance_display()
            self._screen.set_resistance_level(value, show_percent=show_percent)
        else:
            self._screen.set_resistance_level(None)

        current_index = snapshot.current_interval_index
        if current_index != self._active_interval_index:
            self._active_interval_index = current_index
            self._reset_interval_accumulators()
            self._mode_state.reset_jog()

        elapsed_seconds = int(round(snapshot.riding_elapsed_seconds))
        window = max(1, int(self._settings.windowed_power_window_seconds))
        windowed_avg = self._windowed_avg_power(self._monotonic_clock(), window)
        current_str = str(windowed_avg) if windowed_avg is not None else "--"

        if self._mode_state.is_free_ride:
            remaining_text = "\u2014"
            interval_remaining_text = "\u2014"
            if self._mode_state.active_control_mode(snapshot, self._workout) == "ERG" and self._mode_state.free_ride_erg_target is not None:
                target_watts = self._mode_state.free_ride_erg_target + int(round(self._mode_state.erg_jog_watts))
                target_str = str(target_watts)
            else:
                target_str = "\u2014"
        else:
            remaining_seconds = max(int(snapshot.total_duration_seconds) - int(round(snapshot.elapsed_seconds)), 0)
            interval_remaining_seconds = self._interval_remaining_seconds(snapshot)
            target_watts = self._mode_state.resolve_target_watts(snapshot, self._workout) or self._mode_state.workout_target_watts(snapshot, self._workout)
            remaining_text = _format_hh_mm_ss(remaining_seconds)
            interval_remaining_text = _format_hh_mm_ss(interval_remaining_seconds)
            target_str = str(target_watts) if target_watts is not None else "--"

        self._screen.set_mandatory_metrics(
            elapsed_text=_format_hh_mm_ss(elapsed_seconds),
            remaining_text=remaining_text,
            interval_remaining_text=interval_remaining_text,
            target_power_text=f"{current_str} / {target_str} W",
        )

        self._update_tiles(snapshot)
        self._ftms_bridge_manager.submit_snapshot(snapshot, self._workout)

        if self._recorder_integration.recorder_active:
            self._recorder_integration.sync(
                snapshot,
                now_monotonic,
                SensorSnapshot(
                    last_power_watts=self._last_power_watts,
                    last_bike_power_watts=self._last_bike_power_watts,
                    last_hr_bpm=self._last_hr_bpm,
                    last_cadence_rpm=self._cadence_hist.last_rpm(),
                    last_speed_mps=self._last_speed_mps,
                ),
            )

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

    def _workout_target_watts(self, snapshot: WorkoutEngineSnapshot) -> int | None:
        """Return the raw workout target power regardless of control mode."""
        return self._mode_state.workout_target_watts(snapshot, self._workout)

    def _resolve_target_watts(self, snapshot: WorkoutEngineSnapshot) -> int | None:
        return self._mode_state.resolve_target_watts(snapshot, self._workout)

    def _resistance_display(self) -> tuple[int, bool]:
        return self._mode_state.resistance_display()

    def _active_control_mode(self, snapshot: WorkoutEngineSnapshot) -> str:
        return self._mode_state.active_control_mode(snapshot, self._workout)

    def _show_workout_summary(self, recorder_summary: object = None) -> None:
        """Build a WorkoutSummary from recorder-derived metrics and display the modal.

        *recorder_summary* is the RecorderSummary returned by RecorderIntegration.finalize().
        NP, kJ, and avg HR come from that single FIT-bound sample series; TSS is then
        derived from those values using the current FTP setting.
        """
        elapsed = self._last_snapshot.elapsed_seconds if self._last_snapshot else 0.0
        ftp = max(1, int(self._settings.ftp))

        if recorder_summary is not None:
            np_watts = getattr(recorder_summary, "normalized_power", None)
            kj = float(getattr(recorder_summary, "kj", 0.0))
            avg_hr = getattr(recorder_summary, "avg_hr", None)
        else:
            np_watts = self._compute_normalized_power()
            kj = self._power_history.workout_actual_kj()
            avg_hr = self._interval_stats.workout_avg_hr()

        tss = compute_tss(np_watts, ftp, elapsed)
        summary = WorkoutSummary(
            elapsed_seconds=elapsed,
            kj=kj,
            normalized_power=np_watts,
            tss=tss,
            avg_hr=avg_hr,
        )
        dialog = self._summary_dialog_factory(summary, self._screen)
        if dialog is not None:
            dialog.accepted.connect(self._set_no_workout_state)
            dialog.rejected.connect(self._set_no_workout_state)
            dialog.open()
        else:
            self._set_no_workout_state()

    @staticmethod
    def _resolve_effective_power(
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> int | None:
        """Return the effective power for metrics: bike preferred, trainer fallback."""
        if bike_watts is not None:
            return bike_watts
        return trainer_watts

    def receive_power_watts(self, watts: int | None, now_monotonic: float | None = None) -> None:
        """Feed a live trainer power reading (W) into the metric computation pipeline."""
        self._last_power_watts = watts
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        if watts is None:
            self._power_history.record(
                None,
                now,
                False,
                source=PowerSource.TRAINER,
            )
            return
        self._last_power_received_at = now
        recording_active = self._last_snapshot is not None and self._last_snapshot.recording_active
        accepted = self._power_history.record(
            int(watts),
            now,
            recording_active,
            source=PowerSource.TRAINER,
        )
        if accepted:
            self._interval_stats.record_power(int(watts), now, recording_active)
        self._dispatch_power_sample(
            timestamp=now,
            trainer_watts=watts,
            bike_watts=None,
        )

    def receive_bike_power_watts(self, watts: int | None, now_monotonic: float | None = None) -> None:
        """Feed a live bike power meter reading (W).

        CPS power is treated as the primary metrics stream while fresh, with FTMS
        trainer power used as fallback.
        """
        self._last_bike_power_watts = watts
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        if watts is None:
            self._power_history.record(
                None,
                now,
                False,
                source=PowerSource.POWER_METER,
            )
            return
        self._last_power_received_at = now
        recording_active = self._last_snapshot is not None and self._last_snapshot.recording_active
        accepted = self._power_history.record(
            int(watts),
            now,
            recording_active,
            source=PowerSource.POWER_METER,
        )
        if accepted:
            self._interval_stats.record_power(int(watts), now, recording_active)
        self._dispatch_power_sample(
            timestamp=now,
            trainer_watts=None,
            bike_watts=watts,
        )

    def receive_hr_bpm(self, bpm: int | None) -> None:
        """Feed a live heart rate reading (bpm) into the metric computation pipeline."""
        self._last_hr_bpm = bpm
        if bpm is None:
            return
        self._interval_stats.record_hr(int(bpm))
        if self._recorder_integration.recorder_active:
            self._chart_history.record_hr(int(bpm), float(self._monotonic_clock()))

    def receive_cadence_rpm(
        self, rpm: float | None, source: CadenceSource = CadenceSource.TRAINER
    ) -> None:
        """Feed a live cadence reading (rpm), respecting source priority.

        Sources are accepted in priority order: dedicated sensor > power meter > trainer.
        A lower-priority source is only used when no higher-priority source has been heard
        from within the last staleness window.
        """
        now = float(self._monotonic_clock())
        self._cadence_hist.record(rpm, source, now)

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
        if self._ftms_bridge_manager.active:
            self._ftms_bridge_manager.submit_power_sample(timestamp, trainer_watts, bike_watts)
            return
        self._feed_opentrueup(
            timestamp,
            trainer_watts=trainer_watts,
            bike_watts=bike_watts,
        )

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
        self._opentrueup_state.feed(now, trainer_watts=trainer_watts, bike_watts=bike_watts)

    def _reset_interval_accumulators(self) -> None:
        self._interval_stats.reset_interval()

    def _update_tiles(self, snapshot: WorkoutEngineSnapshot) -> None:
        self._tile_computation.update_screen(self._screen, snapshot, self._settings)

    def _compute_tile_value(self, key: str, snapshot: WorkoutEngineSnapshot) -> str:
        return self._tile_computation.compute(key, snapshot, self._settings)

    def _windowed_avg_power(self, now: float, window_seconds: int) -> int | None:
        return self._power_history.windowed_avg(now, window_seconds)

    def _windowed_avg_cadence(self, now: float) -> int | None:
        return self._cadence_hist.windowed_avg(now)

    def _on_chart_tick(self) -> None:
        self._chart_history.on_tick(
            self._last_snapshot,
            self._workout,
            self._mode_state.is_free_ride,
        )

    def _compute_normalized_power(self) -> int | None:
        return self._power_history.compute_normalized_power()


def _format_hh_mm_ss(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02}"
