from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path

from opencycletrainer.core.one_second_aggregator import OneSecondAggregator
from opencycletrainer.core.recorder import RecorderSample, RecorderSummary
from opencycletrainer.core.workout_engine import WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout
from opencycletrainer.storage.paths import get_workout_data_root, get_workout_png_dir
from opencycletrainer.storage.settings import AppSettings

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensorSnapshot:
    """Live sensor readings bundled for a single recorder sync call."""

    last_power_watts: int | None
    last_bike_power_watts: int | None
    last_hr_bpm: int | None
    last_cadence_rpm: float | None
    last_speed_mps: float | None


class RecorderIntegration:
    """Owns the workout recorder lifecycle, kJ tracking, and Strava upload queue."""

    def __init__(
        self,
        recorder: object,
        screen: object,
        settings: AppSettings,
        utc_now: Callable[[], datetime],
        strava_upload_fn: Callable[[Path, Path | None], None] | None,
        alert_signal: Callable[[str, str], None],
        mode_state: object,
    ) -> None:
        self._recorder = recorder
        self._screen = screen
        self._settings = settings
        self._utc_now = utc_now
        self._strava_upload_fn = strava_upload_fn
        self._alert_signal = alert_signal
        self._mode_state = mode_state

        self._recorder_active = False
        self._recorder_started = False
        self._total_kj = 0.0
        self._last_energy_tick_monotonic: float | None = None
        self._upload_executor: ThreadPoolExecutor | None = None
        self._workout: Workout | None = None
        self._aggregator = OneSecondAggregator()

        self._configure_recorder_data_dir()

    @property
    def recorder_active(self) -> bool:
        """True while a recording session is open and accepting samples."""
        return self._recorder_active

    @property
    def total_kj(self) -> float:
        """Accumulated target-based kilojoules for the current session."""
        return self._total_kj

    def start(self, workout: Workout, utc_now: datetime) -> None:
        """Start a new recording session for *workout*."""
        if workout is None or self._recorder_started:
            return
        self._recorder.start(
            workout_name=workout.name,
            started_at_utc=utc_now,
        )
        self._workout = workout
        self._recorder_active = True
        self._recorder_started = True
        self._total_kj = 0.0
        self._last_energy_tick_monotonic = None
        self._aggregator.reset()
        self._aggregator.set_recording_active(True)

    def finalize(self, workout: Workout) -> RecorderSummary | None:  # noqa: ARG002
        """Stop recording, save the file, and trigger any post-workout uploads.

        Returns the RecorderSummary produced by the recorder (containing NP, kJ,
        avg HR, and avg power derived from the FIT-bound sample series), or None
        if no recording was active or the recorder raised on stop.
        """
        if not self._recorder_started:
            return None
        self._recorder_started = False
        self._recorder_active = False
        # Flush any in-progress aggregation bin before handing off to the recorder.
        flush_sample = self._aggregator.flush()
        self._aggregator.reset()
        if flush_sample is not None:
            try:
                self._recorder.record_sample(flush_sample)
            except RuntimeError as exc:
                _logger.warning("Recorder record_sample (flush) failed: %s", exc)
        try:
            summary = self._recorder.stop(finished_at_utc=self._utc_now())
        except RuntimeError as exc:
            _logger.warning("Recorder stop failed: %s", exc)
            return None
        self._screen.show_alert(
            f"Workout saved: {summary.fit_file_path.name}",
            alert_type="success",
        )
        if self._settings.strava_auto_sync_enabled and self._strava_upload_fn is not None:
            data_root = get_workout_data_root(self._settings.workout_data_dir)
            chart_image_path = get_workout_png_dir(data_root) / (
                f"{summary.fit_file_path.stem}.png"
            )
            self._screen.export_chart_image(chart_image_path)
            self._enqueue_strava_upload(summary.fit_file_path, chart_image_path)
        self._workout = None
        return summary

    def sync(
        self,
        snapshot: WorkoutEngineSnapshot,
        now_monotonic: float | None,
        sensor_snapshot: SensorSnapshot,
    ) -> None:
        """Feed one raw sensor snapshot through the 1-second aggregator into the recorder.

        Raw samples are accumulated per UTC second; the recorder only receives completed
        1-second bins, making FIT records deterministic and independent of tick jitter.
        kJ is updated on every call when *now_monotonic* is provided.
        """
        try:
            self._recorder.set_recording_active(snapshot.recording_active)
        except RuntimeError as exc:
            _logger.warning(
                "Recorder set_recording_active failed, halting recording: %s", exc
            )
            self._recorder_active = False
            return

        # Keep the aggregator in sync with the engine's pause/resume state.
        self._aggregator.set_recording_active(snapshot.recording_active)

        if now_monotonic is not None:
            self.update_total_kj(snapshot, now_monotonic)

        target_watts = self._mode_state.resolve_target_watts(snapshot, self._workout)
        active_mode = self._mode_state.active_control_mode(snapshot, self._workout)
        erg_setpoint = target_watts if active_mode == "ERG" else None

        raw_sample = RecorderSample(
            timestamp_utc=self._utc_now(),
            target_power_watts=target_watts,
            trainer_power_watts=sensor_snapshot.last_power_watts,
            bike_power_watts=sensor_snapshot.last_bike_power_watts,
            heart_rate_bpm=sensor_snapshot.last_hr_bpm,
            cadence_rpm=sensor_snapshot.last_cadence_rpm,
            speed_mps=sensor_snapshot.last_speed_mps,
            mode=active_mode,
            erg_setpoint_watts=erg_setpoint,
            total_kj=round(self._total_kj, 3),
        )

        completed = self._aggregator.feed(raw_sample)
        for s in completed:
            try:
                self._recorder.record_sample(s)
            except RuntimeError as exc:
                _logger.warning("Recorder record_sample failed, halting recording: %s", exc)
                self._recorder_active = False
                return

    def update_total_kj(self, snapshot: WorkoutEngineSnapshot, now_monotonic: float) -> None:
        """Integrate target watts over the elapsed tick to accumulate kJ."""
        last_tick = self._last_energy_tick_monotonic
        self._last_energy_tick_monotonic = float(now_monotonic)
        if last_tick is None:
            return
        delta_seconds = float(now_monotonic) - float(last_tick)
        if delta_seconds <= 0:
            return
        if not snapshot.recording_active:
            return
        target_watts = self._mode_state.resolve_target_watts(snapshot, self._workout)
        if target_watts is None or target_watts <= 0:
            return
        self._total_kj += (float(target_watts) * delta_seconds) / 1000.0

    def configure_data_dir(self, settings: AppSettings) -> None:
        """Apply updated settings and push the new data directory to the recorder."""
        self._settings = settings
        self._configure_recorder_data_dir()

    def shutdown(self) -> None:
        """Finalize any in-progress recording and shut down the upload thread pool."""
        if self._recorder_active:
            self.finalize(self._workout)
        if self._upload_executor is not None:
            self._upload_executor.shutdown(wait=False)

    # ── Private ───────────────────────────────────────────────────────────────

    def _configure_recorder_data_dir(self) -> None:
        set_data_dir = getattr(self._recorder, "set_data_dir", None)
        if not callable(set_data_dir):
            return
        data_root = get_workout_data_root(self._settings.workout_data_dir)
        try:
            set_data_dir(data_root)
        except RuntimeError:
            # Recorder is active; new setting takes effect next session.
            return

    def _enqueue_strava_upload(self, fit_path: Path, chart_image_path: Path | None) -> None:
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
        """Called in the upload thread when a Strava upload completes."""
        from concurrent.futures import Future as _Future  # noqa: PLC0415
        from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError  # noqa: PLC0415

        if not isinstance(future, _Future):
            return
        exc = future.exception()
        if exc is None:
            self._alert_signal("Ride synced to Strava", "success")
        elif isinstance(exc, DuplicateUploadError):
            self._alert_signal("Ride already synced to Strava", "info")
        else:
            _logger.warning("Strava upload failed: %s", exc)
            self._alert_signal("Strava sync failed (ride kept locally)", "error")
