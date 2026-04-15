from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import time
from concurrent.futures import Future

import pytest

from PySide6.QtWidgets import QApplication

from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.core.sensors import CadenceSource
from opencycletrainer.core.workout_engine import EngineState, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
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
        return SimpleNamespace(
            fit_file_path=Path("Quick_Start_20260311_1200.fit"),
            normalized_power=None,
            kj=0.0,
            avg_hr=None,
        )


class _FakeRecorderWithDataDir(_FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.data_dirs: list[Path] = []

    def set_data_dir(self, data_dir: Path) -> None:
        self.data_dirs.append(data_dir)


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

    def read_resistance_level_range(self):
        return None


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
    assert screen.title_widget.currentWidget() == screen.load_buttons_widget

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


def test_start_uses_workout_data_dir_setting_for_recorder(tmp_path: Path):
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorderWithDataDir()
    settings = AppSettings(workout_data_dir=tmp_path)

    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=fake_recorder,
        monotonic_clock=lambda: 0.0,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    assert fake_recorder.data_dirs == [tmp_path]

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

    # The aggregator holds the partial bin until a second boundary or session end.
    # shutdown() finalizes the session, flushing the aggregator to the recorder.
    controller.shutdown()

    recorded = fake_recorder.samples
    assert recorded, "Expected at least one recorded sample"
    last = recorded[-1]
    assert last.trainer_power_watts == 250
    assert last.heart_rate_bpm == 155
    assert last.cadence_rpm == 95.0
    assert last.speed_mps == 10.5


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

    assert controller._cadence_hist.last_rpm() == 90.0
    assert controller._last_speed_mps == 8.3

    controller.receive_cadence_rpm(None)
    controller.receive_speed_mps(None)

    assert controller._cadence_hist.last_rpm() is None
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

    assert controller._opentrueup_state.controller is None
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

    assert controller._opentrueup_state.controller is not None

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
    assert controller._opentrueup_state.controller is None
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

    # Flush the aggregator's partial bin by ending the session.
    controller.shutdown()

    recorded = fake_recorder.samples
    assert recorded
    last = recorded[-1]
    assert last.trainer_power_watts == 200
    assert last.bike_power_watts == 215


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
    assert not controller._chart_history.chart_timer.isActive()

    screen.start_button.click()
    app.processEvents()
    assert controller._chart_history.chart_timer.isActive()
    assert controller._chart_history.chart_start_monotonic == 0.0

    screen.end_button.click()
    app.processEvents()
    assert not controller._chart_history.chart_timer.isActive()

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
    assert controller._chart_history.chart_timer.isActive()

    # Skip all intervals until finished
    while controller.last_snapshot is not None and controller.last_snapshot.state not in {
        EngineState.FINISHED, EngineState.STOPPED,
    }:
        screen.skip_interval_requested.emit()
        app.processEvents()

    assert not controller._chart_history.chart_timer.isActive()
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
    assert controller._chart_history.hr_history == []

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 1.0
    controller.receive_hr_bpm(140)
    monotonic_now = 2.0
    controller.receive_hr_bpm(145)

    assert len(controller._chart_history.hr_history) == 2
    elapsed_0, bpm_0 = controller._chart_history.hr_history[0]
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
    assert controller._chart_history.chart_timer.isActive()

    # Loading a new workout while running should stop timer and pre-load the new chart
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    assert not controller._chart_history.chart_timer.isActive()
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


def test_cadence_tile_shows_dash_when_no_cadence():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["cadence_rpm"])
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 1.0
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["cadence_rpm"].value_label.text() == "--"

    controller.shutdown()


def test_cadence_tile_shows_1s_averaged_rpm():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["cadence_rpm"])
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 1.0
    controller.receive_cadence_rpm(90.0)
    monotonic_now = 1.5
    controller.receive_cadence_rpm(80.0)

    monotonic_now = 2.0
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["cadence_rpm"].value_label.text() == "85 rpm"

    controller.shutdown()


def test_cadence_tile_excludes_readings_older_than_1s():
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["cadence_rpm"])
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 0.5
    controller.receive_cadence_rpm(60.0)

    monotonic_now = 2.0
    controller.receive_cadence_rpm(90.0)

    # At t=2.5, cutoff is 1.5 so t=0.5 reading is excluded
    monotonic_now = 2.5
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["cadence_rpm"].value_label.text() == "90 rpm"

    controller.shutdown()


def test_cadence_tile_holds_last_value_during_short_dropout():
    """Cadence tile should display the last known value for up to 3s after data stops."""
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["cadence_rpm"])
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 1.0
    controller.receive_cadence_rpm(90.0)

    # At t=2.5, cadence is 1.5s stale — within 3s hold window, should display 90
    monotonic_now = 2.5
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["cadence_rpm"].value_label.text() == "90 rpm"

    controller.shutdown()


def test_cadence_tile_shows_dash_after_dropout_exceeds_3s():
    """Cadence tile should revert to '--' once the last reading is older than 3s."""
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["cadence_rpm"])
    screen = WorkoutScreen(settings=settings)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=_FakeRecorder(),
        monotonic_clock=_monotonic,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    monotonic_now = 1.0
    controller.receive_cadence_rpm(90.0)

    # At t=4.1, cadence is 3.1s stale — beyond the 3s hold window, should show "--"
    monotonic_now = 4.1
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["cadence_rpm"].value_label.text() == "--"

    controller.shutdown()


# ── Trainer control footer visibility ─────────────────────────────────────────


def test_trainer_controls_hidden_by_default():
    """Footer trainer controls should be hidden when no trainer is connected."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    assert screen.trainer_mode_label.isHidden()
    assert screen.mode_selector.isHidden()
    assert screen.opentrueup_label.isHidden()
    assert screen.opentrueup_offset_value.isHidden()


def test_trainer_controls_visible_when_ftms_trainer_connected():
    """Footer trainer controls should appear when a controllable FTMS trainer is set."""
    _get_or_create_qapp()
    transport = _FakeFTMSTransport()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: transport,
        monotonic_clock=lambda: 0.0,
    )

    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")

    assert not screen.trainer_mode_label.isHidden()
    assert not screen.mode_selector.isHidden()
    assert not screen.opentrueup_label.isHidden()
    assert not screen.opentrueup_offset_value.isHidden()

    controller.shutdown()


def test_trainer_controls_hidden_when_power_only_trainer():
    """Footer trainer controls should stay hidden when the transport factory returns None (power-only device)."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: None,
        monotonic_clock=lambda: 0.0,
    )

    controller.set_trainer_control_target(backend="bleak", trainer_device_id="power-meter-1")

    assert screen.trainer_mode_label.isHidden()
    assert screen.mode_selector.isHidden()
    assert screen.opentrueup_label.isHidden()
    assert screen.opentrueup_offset_value.isHidden()

    controller.shutdown()


def test_trainer_controls_hidden_when_trainer_disconnected():
    """Footer trainer controls should hide again when trainer is removed (device_id set to None)."""
    _get_or_create_qapp()
    transport = _FakeFTMSTransport()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: transport,
        monotonic_clock=lambda: 0.0,
    )

    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    assert not screen.trainer_mode_label.isHidden()

    controller.set_trainer_control_target(backend="bleak", trainer_device_id=None)
    assert screen.trainer_mode_label.isHidden()
    assert screen.mode_selector.isHidden()


# ── Strava upload trigger ─────────────────────────────────────────────────────

def _make_controller_with_upload(
    app,
    upload_fn,
    *,
    strava_auto_sync_enabled: bool = True,
):
    """Build a started controller wired with a fake Strava upload function."""
    test_data_dir = Path(__file__).parent / "data"
    screen = WorkoutScreen(settings=AppSettings())
    settings = AppSettings(strava_auto_sync_enabled=strava_auto_sync_enabled)
    controller = WorkoutSessionController(
        screen=screen,
        settings=settings,
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
        strava_upload_fn=upload_fn,
    )
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()
    return controller, screen


def test_finalize_recorder_enqueues_strava_upload_when_enabled():
    app = _get_or_create_qapp()
    uploaded: list[Path] = []

    def fake_upload(path: Path, chart_image_path: Path | None) -> None:  # noqa: ARG001
        uploaded.append(path)

    controller, screen = _make_controller_with_upload(app, fake_upload, strava_auto_sync_enabled=True)

    screen.end_button.click()
    app.processEvents()

    assert _wait_until(app, lambda: len(uploaded) == 1)
    assert uploaded[0].name == "Quick_Start_20260311_1200.fit"

    controller.shutdown()


def test_finalize_recorder_passes_chart_image_path_to_upload_fn():
    """Controller passes a PNG chart image path alongside the FIT path to the upload function."""
    app = _get_or_create_qapp()
    received: list[Path | None] = []

    def fake_upload(_path: Path, chart_image_path: Path | None) -> None:
        received.append(chart_image_path)

    controller, screen = _make_controller_with_upload(app, fake_upload, strava_auto_sync_enabled=True)

    screen.end_button.click()
    app.processEvents()

    assert _wait_until(app, lambda: len(received) == 1)
    assert received[0] is not None
    assert received[0].suffix == ".png"
    assert received[0].parent.name == "png"

    controller.shutdown()


def test_finalize_recorder_skips_strava_upload_when_disabled():
    app = _get_or_create_qapp()
    uploaded: list[Path] = []

    controller, screen = _make_controller_with_upload(
        app,
        lambda p, _c: uploaded.append(p),
        strava_auto_sync_enabled=False,
    )

    screen.end_button.click()
    app.processEvents()

    # Give the executor a moment to run anything it might incorrectly schedule
    _wait_until(app, lambda: False, timeout_seconds=0.1)
    assert uploaded == []

    controller.shutdown()


def test_finalize_recorder_no_error_when_upload_fn_is_none():
    app = _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    settings = AppSettings(strava_auto_sync_enabled=True)
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(strava_auto_sync_enabled=True),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
        # strava_upload_fn not provided (defaults to None)
    )
    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    # Should not raise even with auto_sync enabled
    screen.end_button.click()
    app.processEvents()

    controller.shutdown()


def test_strava_upload_success_shows_success_alert():
    app = _get_or_create_qapp()

    def fake_upload(_path: Path, _chart_image_path: Path | None) -> None:
        pass  # success

    controller, screen = _make_controller_with_upload(app, fake_upload)

    screen.end_button.click()
    app.processEvents()

    assert _wait_until(app, lambda: "Ride synced to Strava" in screen.alert_label.text())

    controller.shutdown()


def test_strava_upload_failure_shows_error_alert():
    app = _get_or_create_qapp()

    def fake_upload(_path: Path, _chart_image_path: Path | None) -> None:
        raise RuntimeError("Strava upload failed after 3 attempts")

    controller, screen = _make_controller_with_upload(app, fake_upload)

    screen.end_button.click()
    app.processEvents()

    assert _wait_until(app, lambda: "Strava sync failed" in screen.alert_label.text())

    controller.shutdown()


def test_strava_duplicate_upload_shows_already_synced_alert():
    from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError
    app = _get_or_create_qapp()

    def fake_upload(_path: Path, _chart_image_path: Path | None) -> None:
        raise DuplicateUploadError("already uploaded")

    controller, screen = _make_controller_with_upload(app, fake_upload)

    screen.end_button.click()
    app.processEvents()

    assert _wait_until(app, lambda: "already synced" in screen.alert_label.text())

    controller.shutdown()


def _make_running_controller(app):
    """Helper: returns (controller, screen) with a workout loaded and started."""
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
    return controller, screen


def test_pause_shows_pause_dialog():
    app = _get_or_create_qapp()
    controller, screen = _make_running_controller(app)

    screen.pause_button.click()
    app.processEvents()

    assert controller._pause_state.pause_dialog is not None
    assert controller._pause_state.pause_dialog.isVisible()

    controller.shutdown()


def test_pause_dialog_resume_confirmed_resumes_workout():
    app = _get_or_create_qapp()
    controller, screen = _make_running_controller(app)

    screen.pause_button.click()
    app.processEvents()
    assert controller.last_snapshot.state == EngineState.PAUSED

    # resume_started is emitted immediately when Resume button is clicked
    controller._pause_state.pause_dialog.resume_started.emit()
    app.processEvents()
    assert controller.last_snapshot.state == EngineState.RAMP_IN

    controller.shutdown()


def test_resume_button_triggers_ramp_in_before_countdown_ends():
    """Clicking Resume should start RAMP_IN immediately, not after the 3s countdown."""
    app = _get_or_create_qapp()
    controller, screen = _make_running_controller(app)

    screen.pause_button.click()
    app.processEvents()
    assert controller.last_snapshot.state == EngineState.PAUSED

    controller._pause_state.pause_dialog.resume_button.click()
    app.processEvents()
    # Engine should be in RAMP_IN right away, without waiting for countdown
    assert controller.last_snapshot.state == EngineState.RAMP_IN

    controller.shutdown()


def test_chart_cursor_frozen_while_paused():
    """Chart cursor elapsed should not advance while the workout is paused."""
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    received: list[float] = []
    screen = WorkoutScreen(settings=AppSettings())
    original_update = screen.update_charts

    def _capture(elapsed, interval_index, power_series, hr_series):
        received.append(elapsed)
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
    controller._on_chart_tick()
    assert received[-1] == pytest.approx(5.0)

    # Pause at t=5
    screen.pause_button.click()
    app.processEvents()

    # Clock advances 5 more seconds while paused
    monotonic_now = 10.0
    controller._on_chart_tick()
    # Cursor must remain frozen at ~5.0
    assert received[-1] == pytest.approx(5.0)

    controller.shutdown()


def test_chart_cursor_frozen_during_ramp_in():
    """Chart cursor elapsed should not advance during RAMP_IN after resume."""
    app = _get_or_create_qapp()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    received: list[float] = []
    screen = WorkoutScreen(settings=AppSettings())
    original_update = screen.update_charts

    def _capture(elapsed, interval_index, power_series, hr_series):
        received.append(elapsed)
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

    # Advance to t=5
    monotonic_now = 5.0
    controller._on_chart_tick()
    assert received[-1] == pytest.approx(5.0)

    # Pause at t=5
    screen.pause_button.click()
    app.processEvents()

    # Resume at t=8 → 3s pause, engine enters RAMP_IN
    monotonic_now = 8.0
    controller._pause_state.pause_dialog.resume_button.click()
    app.processEvents()
    assert controller.last_snapshot.state == EngineState.RAMP_IN

    # Clock advances to t=10 during RAMP_IN — cursor must remain at 5
    monotonic_now = 10.0
    controller._on_chart_tick()
    assert received[-1] == pytest.approx(5.0)

    controller.shutdown()


def test_cadence_dedicated_sensor_overrides_power_meter():
    """CSC (dedicated) cadence should take priority over CPS (power meter) cadence."""
    _get_or_create_qapp()
    monotonic_now = 0.0
    controller = WorkoutSessionController(
        screen=WorkoutScreen(settings=AppSettings()),
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    controller.receive_cadence_rpm(70.0, CadenceSource.POWER_METER)
    controller.receive_cadence_rpm(90.0, CadenceSource.DEDICATED)
    assert controller._cadence_hist.last_rpm() == 90.0

    controller.shutdown()


def test_cadence_power_meter_overrides_trainer():
    """CPS (power meter) cadence should take priority over FTMS (trainer) cadence."""
    _get_or_create_qapp()
    monotonic_now = 0.0
    controller = WorkoutSessionController(
        screen=WorkoutScreen(settings=AppSettings()),
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    controller.receive_cadence_rpm(70.0, CadenceSource.TRAINER)
    controller.receive_cadence_rpm(90.0, CadenceSource.POWER_METER)
    assert controller._cadence_hist.last_rpm() == 90.0

    controller.shutdown()


def test_cadence_lower_priority_ignored_when_higher_priority_active():
    """Trainer cadence should be ignored while a dedicated sensor is active."""
    _get_or_create_qapp()
    monotonic_now = 0.0
    controller = WorkoutSessionController(
        screen=WorkoutScreen(settings=AppSettings()),
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    controller.receive_cadence_rpm(90.0, CadenceSource.DEDICATED)
    controller.receive_cadence_rpm(70.0, CadenceSource.TRAINER)
    assert controller._cadence_hist.last_rpm() == 90.0

    controller.shutdown()


def test_cadence_falls_back_when_higher_priority_source_goes_stale():
    """When the dedicated sensor goes stale, power meter cadence should take over."""
    _get_or_create_qapp()
    monotonic_now = 0.0
    controller = WorkoutSessionController(
        screen=WorkoutScreen(settings=AppSettings()),
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    controller.receive_cadence_rpm(90.0, CadenceSource.DEDICATED)
    assert controller._cadence_hist.last_rpm() == 90.0

    # Advance past the staleness threshold (3 s)
    monotonic_now = 4.0
    controller.receive_cadence_rpm(75.0, CadenceSource.POWER_METER)
    assert controller._cadence_hist.last_rpm() == 75.0

    controller.shutdown()


def test_cadence_history_excludes_rejected_lower_priority_samples():
    """Cadence history should only contain samples from the winning source."""
    _get_or_create_qapp()
    monotonic_now = 0.0
    controller = WorkoutSessionController(
        screen=WorkoutScreen(settings=AppSettings()),
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: monotonic_now,
    )

    controller.receive_cadence_rpm(90.0, CadenceSource.DEDICATED)
    controller.receive_cadence_rpm(70.0, CadenceSource.TRAINER)  # should be rejected

    assert len(controller._cadence_hist.as_deque()) == 1
    assert controller._cadence_hist.as_deque()[0][1] == 90.0

    controller.shutdown()


def test_target_power_tile_title_is_current_slash_target():
    """Target power tile title is 'Current / Target Power'."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    assert screen.target_power_tile.title_label.text() == "Current / Target Power"


def test_target_power_tile_shows_windowed_avg_and_target():
    """Target power tile shows 'windowed_avg / target W' when power data is available."""
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(windowed_power_window_seconds=3)
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

    controller.receive_power_watts(150, now_monotonic=0.5)
    controller.receive_power_watts(152, now_monotonic=1.0)

    monotonic_now = 1.0
    controller.process_tick(monotonic_now)

    tile_text = screen.target_power_tile.value_label.text()
    assert tile_text.startswith("151 / ")
    assert " / " in tile_text
    assert tile_text.endswith(" W")

    controller.shutdown()


def test_target_power_tile_shows_dashes_when_no_power_received():
    """Target power tile shows '-- / X W' when no power data has been received."""
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(windowed_power_window_seconds=3)
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

    monotonic_now = 1.0
    controller.process_tick(monotonic_now)

    tile_text = screen.target_power_tile.value_label.text()
    assert tile_text.startswith("-- / ")
    assert tile_text.endswith(" W")

    controller.shutdown()


def test_windowed_avg_power_not_in_tile_options():
    """Windowed Avg Power is removed from the configurable tile list."""
    from opencycletrainer.ui.tile_config import TILE_OPTIONS
    keys = [key for key, _ in TILE_OPTIONS]
    assert "windowed_avg_power" not in keys


def _make_free_ride_controller(app):
    """Helper to build a screen+controller pair ready for free ride testing."""
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic():
        return monotonic_now

    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=fake_recorder,
        monotonic_clock=_monotonic,
    )
    return screen, controller, fake_recorder, _monotonic


def test_free_ride_starts_engine_in_running_state():
    app = _get_or_create_qapp()
    screen, controller, fake_recorder, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()

    assert controller.last_snapshot is not None
    assert controller.last_snapshot.state == EngineState.RUNNING
    assert fake_recorder.started is True

    controller.shutdown()


def test_free_ride_starts_in_resistance_mode():
    app = _get_or_create_qapp()
    screen, controller, _, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()

    assert screen.mode_selector.currentText() == "Resistance"

    controller.shutdown()


def test_free_ride_time_remaining_shows_dash():
    app = _get_or_create_qapp()
    screen, controller, _, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()

    assert screen.remaining_tile.value_label.text() == "\u2014"
    assert screen.interval_remaining_tile.value_label.text() == "\u2014"

    controller.shutdown()


def test_free_ride_target_power_shows_dash_in_resistance_mode():
    app = _get_or_create_qapp()
    screen, controller, _, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()

    tile_text = screen.target_power_tile.value_label.text()
    assert "/ \u2014" in tile_text or tile_text == "\u2014 / \u2014 W"

    controller.shutdown()


def test_free_ride_erg_target_entry_switches_to_erg_mode():
    app = _get_or_create_qapp()
    screen, controller, _, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()

    screen.erg_target_entered.emit(250)
    app.processEvents()

    assert screen.mode_selector.currentText() == "ERG"
    assert controller._mode_state.free_ride_erg_target == 250

    controller.shutdown()


def test_free_ride_erg_target_reflected_in_target_power_tile():
    app = _get_or_create_qapp()
    screen, controller, _, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()

    screen.erg_target_entered.emit(200)
    app.processEvents()

    tile_text = screen.target_power_tile.value_label.text()
    assert "200" in tile_text

    controller.shutdown()


def test_free_ride_does_not_start_if_already_running():
    app = _get_or_create_qapp()
    screen, controller, _, _ = _make_free_ride_controller(app)

    screen.free_ride_button.click()
    app.processEvents()
    first_snapshot = controller.last_snapshot

    screen.free_ride_button.click()
    app.processEvents()

    assert controller.last_snapshot.state == EngineState.RUNNING

    controller.shutdown()


# ── Device reconnect notifications ───────────────────────────────────────────

def test_trainer_disconnect_during_active_workout_shows_reconnecting_alert():
    """When a trainer disconnects while a workout is running, an info-style 'Reconnecting'
    alert should appear on the workout screen."""
    app = _get_or_create_qapp()
    transport = _FakeFTMSTransport()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: transport,
        monotonic_clock=lambda: 0.0,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    # Trainer was connected
    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    # Now it disconnects unexpectedly
    controller.set_trainer_control_target(backend="bleak", trainer_device_id=None)
    app.processEvents()

    assert "Reconnecting" in screen.alert_label.text()

    controller.shutdown()


def test_trainer_reconnect_during_active_workout_shows_reconnected_alert():
    """When a trainer reconnects after a disconnect during an active workout, a success
    alert should appear on the workout screen."""
    app = _get_or_create_qapp()
    transport = _FakeFTMSTransport()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: transport,
        monotonic_clock=lambda: 0.0,
    )

    test_data_dir = Path(__file__).parent / "data"
    controller._load_workout_from_file(test_data_dir / "ramp.mrc")
    screen.start_button.click()
    app.processEvents()

    # Trainer connects, then disconnects, then reconnects
    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    controller.set_trainer_control_target(backend="bleak", trainer_device_id=None)
    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    app.processEvents()

    assert "reconnected" in screen.alert_label.text().lower()

    controller.shutdown()


def test_trainer_no_reconnect_alert_before_workout_starts():
    """Trainer connection changes before the workout timer is running must not show alerts."""
    app = _get_or_create_qapp()
    transport = _FakeFTMSTransport()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        ftms_transport_factory=lambda backend, trainer_id: transport,
        monotonic_clock=lambda: 0.0,
    )

    # Change trainer before workout starts — timer is not active
    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    controller.set_trainer_control_target(backend="bleak", trainer_device_id=None)
    controller.set_trainer_control_target(backend="bleak", trainer_device_id="trainer-1")
    app.processEvents()

    assert screen.alert_label.text() == ""


# ── Interval plot visibility ──────────────────────────────────────────────────


def test_interval_plot_visible_by_default():
    """Interval plot is not explicitly hidden when show_interval_plot defaults to True."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    assert not screen.chart_widget._interval_plot.isHidden()


def test_apply_settings_hides_interval_plot_when_disabled():
    """apply_settings with show_interval_plot=False hides the interval plot."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    screen.apply_settings(AppSettings(show_interval_plot=False))
    assert screen.chart_widget._interval_plot.isHidden()


def test_apply_settings_shows_interval_plot_when_enabled():
    """apply_settings with show_interval_plot=True un-hides the interval plot."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(show_interval_plot=False))
    screen.apply_settings(AppSettings(show_interval_plot=True))
    assert not screen.chart_widget._interval_plot.isHidden()


# ── Phase 1: free-ride interval forces Resistance mode ───────────────────────

def _make_snapshot(interval_index: int | None, total_seconds: int = 600) -> WorkoutEngineSnapshot:
    """Build a minimal snapshot at the given interval index."""
    return WorkoutEngineSnapshot(
        state=EngineState.RUNNING,
        elapsed_seconds=10.0,
        riding_elapsed_seconds=10.0,
        total_duration_seconds=total_seconds,
        current_interval_index=interval_index,
        current_interval_elapsed_seconds=10.0,
        current_interval_remaining_seconds=float(total_seconds - 10),
        ramp_in_remaining_seconds=0.0,
        recording_active=False,
        pending_kj_extension=0,
    )


def _make_free_ride_workout() -> Workout:
    """Two-interval workout: free_ride=True then normal ERG interval."""
    return Workout(
        name="Free Ride Test",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=300,
                start_percent_ftp=0.0,
                end_percent_ftp=0.0,
                start_target_watts=0,
                end_target_watts=0,
                free_ride=True,
            ),
            WorkoutInterval(
                start_offset_seconds=300,
                duration_seconds=300,
                start_percent_ftp=85.0,
                end_percent_ftp=85.0,
                start_target_watts=170,
                end_target_watts=170,
            ),
        ),
    )


def test_active_control_mode_returns_resistance_for_free_ride_interval_regardless_of_selected_mode():
    """_active_control_mode() forces Resistance when the current interval has free_ride=True."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
    )

    controller._workout = _make_free_ride_workout()
    snapshot = _make_snapshot(interval_index=0)

    for mode in ["ERG", "Resistance", "Hybrid"]:
        controller._mode_state.select_mode(mode)
        assert controller._active_control_mode(snapshot) == "Resistance", (
            f"Expected Resistance for free_ride interval with selected_mode={mode!r}"
        )

    controller.shutdown()


def test_active_control_mode_resumes_normal_selection_after_free_ride_interval():
    """After a free_ride interval, _active_control_mode() returns to the user's selected mode."""
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())
    controller = WorkoutSessionController(
        screen=screen,
        settings=AppSettings(),
        recorder=_FakeRecorder(),
        monotonic_clock=lambda: 0.0,
    )

    controller._workout = _make_free_ride_workout()
    snapshot = _make_snapshot(interval_index=1)

    controller._mode_state.select_mode("ERG")
    assert controller._active_control_mode(snapshot) == "ERG"

    controller._mode_state.select_mode("Resistance")
    assert controller._active_control_mode(snapshot) == "Resistance"

    controller.shutdown()


def test_trainer_bridge_sends_resistance_command_during_free_ride_interval():
    """FTMS opcode 0x04 (resistance) is sent when the current interval is free_ride=True."""
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

    workout = _make_free_ride_workout()
    controller._workout = workout
    controller._engine.load_workout(workout)
    snapshot = controller._engine.start()
    controller._handle_snapshot(snapshot, now_monotonic=0.0)

    assert _wait_until(
        app,
        lambda: any(payload[:1] == b"\x04" for payload in transport.writes),
    ), "Expected resistance command (0x04) to be sent for free_ride interval"


def test_effective_power_prefers_bike_over_trainer_in_workout_avg():
    """When bike power is available, workout avg and kJ reflect bike power, not trainer."""
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["workout_avg_power"])
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

    # Bike arrives first; both subsequent trainer ticks should resolve to 215 (bike preferred).
    controller.receive_bike_power_watts(215, now_monotonic=0.5)
    controller.receive_power_watts(200, now_monotonic=1.0)  # effective = 215
    controller.receive_power_watts(200, now_monotonic=2.0)  # effective = 215

    monotonic_now = 2.0
    controller.process_tick(monotonic_now)

    assert screen._tile_by_key["workout_avg_power"].value_label.text() == "215 W"

    controller.shutdown()


def test_effective_power_falls_back_to_trainer_on_bike_dropout():
    """When bike power is cleared (None), subsequent trainer ticks use trainer power."""
    app = _get_or_create_qapp()
    fake_recorder = _FakeRecorder()
    monotonic_now = 0.0

    def _monotonic() -> float:
        return monotonic_now

    settings = AppSettings(tile_selections=["workout_avg_power"])
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

    controller.receive_bike_power_watts(215, now_monotonic=0.5)
    controller.receive_power_watts(200, now_monotonic=1.0)  # effective = 215 (bike present)
    controller.receive_bike_power_watts(None)                # bike drops out
    controller.receive_power_watts(200, now_monotonic=2.0)  # effective = 200 (trainer fallback)

    monotonic_now = 2.0
    controller.process_tick(monotonic_now)

    # Tick 1: effective=215, Tick 2: effective=200 → avg = round((215+200)/2) = 208
    assert screen._tile_by_key["workout_avg_power"].value_label.text() == "208 W"

    controller.shutdown()

    controller.shutdown()
