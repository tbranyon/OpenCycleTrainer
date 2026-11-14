"""Finishing a ride writes its files off the UI thread, then uploads them."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from opencycletrainer.core.recorder import RecorderSample
from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.recorder_integration import RecorderIntegration

_WAIT_SECONDS = 3.0
_UTC_NOW = datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)


class _FinishedRide:
    """Stands in for WorkoutRecorder.finish()'s result; write() blocks until released."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fit_file_path = Path("Ride_20260311_1200.fit")
        self.release = threading.Event()
        self.written = threading.Event()
        self.write_thread: str | None = None
        self._fail = fail

    def write(self) -> object:
        self.write_thread = threading.current_thread().name
        self.release.wait(_WAIT_SECONDS)
        if self._fail:
            raise OSError("disk full")
        self.written.set()
        return SimpleNamespace(fit_file_path=self.fit_file_path)


class _SplitRecorder:
    """Recorder exposing the finish()/write() split, recording what it was given."""

    def __init__(self, finished: _FinishedRide) -> None:
        self.finished = finished
        self.finish_metrics: object = None
        self.samples: list[RecorderSample] = []
        self.started = False

    def start(self, workout_name: str, started_at_utc: object) -> object:  # noqa: ARG002
        self.started = True
        return SimpleNamespace(workout_name=workout_name)

    def set_recording_active(self, active: bool) -> None:
        pass

    def record_sample(self, sample: RecorderSample) -> bool:
        self.samples.append(sample)
        return True

    def get_recorded_samples(self) -> list[RecorderSample]:
        return list(self.samples)

    def finish(self, finished_at_utc: object = None, activity_name: str | None = None, metrics: object = None):  # noqa: ARG002
        self.finish_metrics = metrics
        return self.finished

    def set_data_dir(self, data_dir: Path) -> None:
        pass


class _Screen:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []
        self.exported_chart_paths: list[Path] = []

    def show_alert(self, message: str, alert_type: str = "info") -> None:
        self.alerts.append((message, alert_type))

    def export_chart_image(self, path: Path) -> None:
        self.exported_chart_paths.append(path)


class _ModeState:
    def resolve_target_watts(self, snapshot, workout):  # noqa: ARG002
        return 200

    def active_control_mode(self, snapshot, workout):  # noqa: ARG002
        return "ERG"


def _ride(finished: _FinishedRide, *, settings: AppSettings | None = None, strava_upload_fn=None):
    alerts: list[tuple[str, str]] = []
    recorder = _SplitRecorder(finished)
    screen = _Screen()
    integration = RecorderIntegration(
        recorder=recorder,
        screen=screen,
        settings=settings or AppSettings(),
        utc_now=lambda: _UTC_NOW,
        strava_upload_fn=strava_upload_fn,
        alert_signal=lambda message, kind: alerts.append((message, kind)),
        mode_state=_ModeState(),
    )
    integration.start(SimpleNamespace(name="Ride"), _UTC_NOW)
    recorder.samples.append(RecorderSample(
        timestamp_utc=_UTC_NOW, target_power_watts=200, trainer_power_watts=210,
        bike_power_watts=None, heart_rate_bpm=140, cadence_rpm=90.0, speed_mps=9.0,
    ))
    return integration, recorder, screen, alerts


def _wait_for(predicate, timeout: float = _WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_commit_returns_before_the_ride_file_is_written():
    finished = _FinishedRide()
    integration, _, _, alerts = _ride(finished)
    integration.prepare_summary()

    integration.commit()

    assert not finished.written.is_set()
    finished.release.set()
    assert _wait_for(lambda: ("Workout saved: Ride_20260311_1200.fit", "success") in alerts)
    assert finished.write_thread != threading.main_thread().name
    integration.shutdown()


def test_uploads_start_only_after_the_ride_file_is_written():
    finished = _FinishedRide()
    uploads: list[tuple[Path, bool]] = []
    settings = AppSettings(strava_auto_sync_enabled=True)
    integration, _, screen, _ = _ride(
        finished, settings=settings,
        strava_upload_fn=lambda path, name: uploads.append((path, finished.written.is_set())),
    )
    integration.prepare_summary()

    integration.commit()

    assert [p.stem for p in screen.exported_chart_paths] == ["Ride_20260311_1200"]
    time.sleep(0.05)
    assert uploads == []
    finished.release.set()
    assert _wait_for(lambda: uploads == [(finished.fit_file_path, True)])
    integration.shutdown()


def test_metrics_computed_for_the_summary_are_reused_when_saving():
    finished = _FinishedRide()
    finished.release.set()
    integration, recorder, _, _ = _ride(finished)

    shown = integration.prepare_summary()
    integration.commit()

    assert recorder.finish_metrics is not None
    assert (recorder.finish_metrics.kj, recorder.finish_metrics.avg_hr) == (shown.kj, shown.avg_hr)
    integration.shutdown()


def test_shutdown_waits_for_a_ride_that_is_still_being_saved():
    finished = _FinishedRide()
    integration, _, _, _ = _ride(finished)
    integration.prepare_summary()
    integration.commit()
    threading.Timer(0.2, finished.release.set).start()

    integration.shutdown()

    assert finished.written.is_set()


def test_failed_background_save_tells_the_rider_where_the_data_is():
    finished = _FinishedRide(fail=True)
    finished.release.set()
    integration, _, _, alerts = _ride(finished)
    integration.prepare_summary()

    integration.commit()

    assert _wait_for(lambda: any(kind == "error" for _, kind in alerts))
    message = next(text for text, kind in alerts if kind == "error")
    assert message.startswith("Couldn't save the workout file")
    integration.shutdown()
