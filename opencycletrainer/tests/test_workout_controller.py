from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import time
from concurrent.futures import Future

import pytest

from PySide6.QtWidgets import QApplication

from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.core.workout_engine import EngineState
from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.workout_controller import WorkoutSessionController
from opencycletrainer.ui.workout_screen import WorkoutScreen


class _FakeRecorder:
    def __init__(self) -> None:
        self.started = False
        self.recording_enabled = False
        self.samples: list[object] = []
        self.stop_calls = 0

    def start(self, workout_name: str, started_at_utc: object) -> object:  # noqa: ARG002
        self.started = True
        self.recording_enabled = True
        return SimpleNamespace(workout_name=workout_name)

    def set_recording_active(self, active: bool) -> None:
        if not self.started:
            raise RuntimeError("Recorder is not active.")
        self.recording_enabled = bool(active)

    def record_sample(self, sample: object) -> bool:
        if not self.started:
            raise RuntimeError("Recorder is not active.")
        self.samples.append(sample)
        return True

    def stop(self, finished_at_utc: object) -> object:  # noqa: ARG002
        if not self.started:
            raise RuntimeError("Recorder is not active.")
        self.started = False
        self.recording_enabled = False
        self.stop_calls += 1
        return SimpleNamespace(fit_file_path=Path("Quick_Start_20260311_1200.fit"))


class _FakeFTMSTransport:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self._handler = lambda _: None

    def write_control_point(self, payload: bytes) -> Future[None]:
        self.writes.append(payload)
        future: Future[None] = Future()
        future.set_result(None)
        self._handler(bytes([0x80, payload[0], 0x01]))
        return future

    def set_indication_handler(self, handler) -> None:
        self._handler = handler


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _wait_until(app: QApplication, predicate, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        app.processEvents()
        time.sleep(0.01)
    return predicate()


def test_workout_controller_wires_screen_controls_to_engine_and_recorder():
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=fake_recorder,
        monotonic_clock=_monotonic,
    )

    assert controller.last_snapshot is None
    assert screen.title_widget.currentWidget() == screen.load_workout_button

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    assert screen.title_label.text() == "Ramp Session"
    assert controller.last_snapshot is not None
    assert controller.last_snapshot.state == EngineState.READY

    baseline_total = controller.last_snapshot.total_duration_seconds
    screen.start_button.click()
    app.processEvents()
    assert controller.last_snapshot is not None
    assert controller.last_snapshot.state == EngineState.RUNNING
    assert fake_recorder.started is True

    monotonic_now = 1.0
    controller.process_tick(monotonic_now)
    assert screen.elapsed_time_tile.value_label.text() == "00:00:01"

    screen.extend_interval_requested.emit(60, False)
    app.processEvents()
    assert controller.last_snapshot is not None
    assert controller.last_snapshot.total_duration_seconds == baseline_total + 60

    screen.skip_interval_requested.emit()
    app.processEvents()
    assert controller.last_snapshot is not None
    assert controller.last_snapshot.current_interval_index == 1

    screen.pause_button.click()
    app.processEvents()
    assert controller.last_snapshot is not None
    assert controller.last_snapshot.state == EngineState.PAUSED

    screen.end_button.click()
    app.processEvents()
    assert controller.last_snapshot is not None
    assert controller.last_snapshot.state == EngineState.STOPPED
    assert fake_recorder.stop_calls == 1
    assert fake_recorder.samples

    controller.shutdown()


def test_receive_power_and_hr_updates_tile_values():
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(
        tile_selections=["heart_rate", "workout_avg_power", "interval_avg_power", "kj_work_completed"],
        windowed_power_window_seconds=3,
    )
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=fake_recorder,
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    controller.receive_power_watts(200, now_monotonic=1.0)
    controller.receive_power_watts(210, now_monotonic=2.0)
    controller.receive_hr_bpm(145)

    monotonic_now = 2.0
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["heart_rate"].value_label.text() == "145 bpm"
    assert screen._tile_by_key["workout_avg_power"].value_label.text() == "205 W"
    assert screen._tile_by_key["interval_avg_power"].value_label.text() == "205 W"
    # kJ: second sample at t=2.0 with delta=1.0s → 210 * 1.0 / 1000 = 0.21 kJ
    assert screen._tile_by_key["kj_work_completed"].value_label.text() == "0.2 kJ"

    controller.shutdown()


def test_sensor_data_is_included_in_recorder_samples():
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=fake_recorder,
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    controller.receive_power_watts(250, now_monotonic=0.5)
    controller.receive_hr_bpm(155)
    controller.receive_cadence_rpm(95.0)
    controller.receive_speed_mps(10.5)

    monotonic_now = 1.0
    controller.process_tick(monotonic_now)

    recorded = fake_recorder.samples
    assert recorded, "Expected at least one recorded sample"
    last = recorded[-1]
    assert last.trainer_power_watts == 250
    assert last.heart_rate_bpm == 155
    assert last.cadence_rpm == 95.0
    assert last.speed_mps == 10.5

    controller.shutdown()


def test_receive_cadence_and_speed_are_available():
    app = _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
    )

    controller.receive_cadence_rpm(90.0)
    controller.receive_speed_mps(8.3)

    assert controller._last_cadence_rpm == 90.0
    assert controller._last_speed_mps == 8.3

    controller.receive_cadence_rpm(None)
    controller.receive_speed_mps(None)

    assert controller._last_cadence_rpm is None
    assert controller._last_speed_mps is None

    controller.shutdown()


def test_interval_change_resets_interval_accumulators():
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["interval_avg_power"])
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=fake_recorder,
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    controller.receive_power_watts(200, now_monotonic=1.0)
    monotonic_now = 1.0
    controller.process_tick(monotonic_now)
    assert screen._tile_by_key["interval_avg_power"].value_label.text() == "200 W"

    screen.skip_interval_requested.emit()
    app.processEvents()

    # Interval changed — accumulators reset, no new data yet
    assert screen._tile_by_key["interval_avg_power"].value_label.text() == "--"

    controller.shutdown()


def test_opentrueup_disabled_by_default_and_no_oту_created():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(opentrueup_enabled=False),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
    )

    assert controller._opentrueup is None
    assert screen.opentrueup_offset_value.text() == "-- W"
    controller.shutdown()


def test_opentrueup_enabled_creates_controller_and_updates_offset_display():
    _get_or_create_qapp()
    # Inject a fast-cycling OTU (1s update, 10s window) so the test doesn't need 30s of data.
    oту = OpenTrueUpController(enabled=True, window_seconds=10.0, update_interval_seconds=1.0)
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(opentrueup_enabled=True),
        recorder=_FakeRecorder(),
        opentrueup=oту,
        monotonic_clock=lambda: 0.0,
    )

    assert controller._opentrueup is not None

    # Feed trainer power at t=0, then bike power to establish offset
    controller.receive_power_watts(200, now_monotonic=0.0)
    controller.receive_bike_power_watts(210, now_monotonic=0.5)
    # Feed again past the 1s update interval so OTU computes offset
    controller.receive_power_watts(200, now_monotonic=1.5)
    controller.receive_bike_power_watts(210, now_monotonic=2.0)

    # Offset should be +10 W (bike avg 210 - trainer avg 200)
    assert screen.opentrueup_offset_value.text() == "10 W"
    controller.shutdown()


def test_opentrueup_display_clears_when_disabled_via_apply_settings():
    _get_or_create_qapp()
    oту = OpenTrueUpController(enabled=True, window_seconds=10.0, update_interval_seconds=1.0)
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(opentrueup_enabled=True),
        recorder=_FakeRecorder(),
        opentrueup=oту,
        monotonic_clock=lambda: 0.0,
    )

    controller.receive_power_watts(200, now_monotonic=0.0)
    controller.receive_bike_power_watts(215, now_monotonic=0.5)
    controller.receive_power_watts(200, now_monotonic=1.5)
    controller.receive_bike_power_watts(215, now_monotonic=2.0)
    assert screen.opentrueup_offset_value.text() == "15 W"

    controller.apply_settings(AppSettings(opentrueup_enabled=False))
    assert controller._opentrueup is None
    assert screen.opentrueup_offset_value.text() == "-- W"

    controller.shutdown()


def test_bike_power_is_included_in_recorder_sample():
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=fake_recorder,
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    controller.receive_power_watts(200, now_monotonic=0.5)
    controller.receive_bike_power_watts(215, now_monotonic=0.5)

    monotonic_now = 1.0
    controller.process_tick(monotonic_now)

    recorded = fake_recorder.samples
    assert recorded
    last = recorded[-1]
    assert last.trainer_power_watts == 200
    assert last.bike_power_watts == 215

    controller.shutdown()


def test_chart_timer_starts_on_start_and_stops_on_stop():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    assert not controller._chart_timer.isActive()

    screen.start_button.click()
    app.processEvents()
    assert controller._chart_timer.isActive()
    assert controller._chart_start_monotonic == 0.0

    screen.end_button.click()
    app.processEvents()
    assert not controller._chart_timer.isActive()

    controller.shutdown()


def test_chart_timer_stops_on_skip_to_finish():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()
    assert controller._chart_timer.isActive()

    # Skip all intervals until finished
    while controller.last_snapshot is not None and controller.last_snapshot.state not in {
        EngineState.FINISHED, EngineState.STOPPED,
    }:
        screen.skip_interval_requested.emit()
        app.processEvents()

    assert not controller._chart_timer.isActive()
    controller.shutdown()


def test_hr_history_accumulates_while_recording():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    # HR before start should not accumulate
    controller.receive_hr_bpm(120)
    assert controller._hr_history == []

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 1.0
    controller.receive_hr_bpm(140)
    monotonic_now = 2.0
    controller.receive_hr_bpm(145)

    assert len(controller._hr_history) == 2
    elapsed_0, bpm_0 = controller._hr_history[0]
    assert bpm_0 == 140
    assert elapsed_0 == pytest.approx(1.0)

    controller.shutdown()


def test_on_chart_tick_passes_correct_elapsed_and_series_to_screen():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    received: list[dict] = []

    screen = WorkoutScreen(settings=AppSettings())
    original_update = screen.update_charts

    def _capture(elapsed, interval_index, power_series, hr_series):
        received.append({
            "elapsed": elapsed,
            "interval_index": interval_index,
            "power_len": len(power_series),
            "hr_len": len(hr_series),
        })
        original_update(elapsed, interval_index, power_series, hr_series)

    screen.update_charts = _capture

    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 5.0
    controller.receive_power_watts(200, now_monotonic=1.0)
    controller.receive_power_watts(210, now_monotonic=2.0)
    controller.receive_hr_bpm(130)

    controller._on_chart_tick()

    assert len(received) == 1
    call = received[0]
    assert call["elapsed"] == pytest.approx(5.0)
    assert call["power_len"] == 2
    assert call["hr_len"] == 1

    controller.shutdown()


def test_load_workout_pre_loads_chart_with_target_profile():
    """Chart target series should be populated as soon as a workout file is loaded."""
    _get_or_create_qapp()

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
    )

    # Before loading: target series should be empty
    x_before, _ = screen.chart_widget._workout_target.getData()
    assert x_before is None or len(x_before) == 0

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")

    # After loading (before Start): target series should be populated
    x_after, y_after = screen.chart_widget._workout_target.getData()
    assert x_after is not None and len(x_after) > 0
    assert y_after is not None and len(y_after) > 0

    controller.shutdown()


def test_load_workout_replaces_chart_and_stops_timer():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()
    assert controller._chart_timer.isActive()

    # Loading a new workout while running should stop timer and pre-load the new chart
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    assert not controller._chart_timer.isActive()
    x, _ = screen.chart_widget._workout_target.getData()
    assert x is not None and len(x) > 0

    controller.shutdown()


def test_trainer_bridge_dispatches_erg_and_resistance_commands_when_target_is_configured():
    app = _get_or_create_qapp()
    transport = _FakeFTMSTransport()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: (
            transport if backend == "bleak" and trainer_id == "trainer-1" else None
        ),
        monotonic_clock=lambda: 0.0,
    )

    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "step_only.mrc")
    screen.start_button.click()
    app.processEvents()

    assert _wait_until(
        app,
        lambda: any(payload[:1] == b"\x05" for payload in transport.writes),
    )

    screen.mode_selector.setCurrentText("Resistance")
    app.processEvents()
    assert _wait_until(
        app,
        lambda: any(payload[:1] == b"\x04" for payload in transport.writes),
    )

    controller.shutdown()
