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

    assert controller._pause_dialog is not None
    assert controller._pause_dialog.isVisible()

    controller.shutdown()


def test_pause_dialog_resume_confirmed_resumes_workout():
    app = _get_or_create_qapp()
    controller, screen = _make_running_controller(app)

    screen.pause_button.click()
    app.processEvents()
    assert controller.last_snapshot.state == EngineState.PAUSED

    # resume_started is emitted immediately when Resume button is clicked
    controller._pause_dialog.resume_started.emit()
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

    controller._pause_dialog.resume_button.click()
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
    controller._pause_dialog.resume_button.click()
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
    assert controller._last_cadence_rpm == 90.0

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
    assert controller._last_cadence_rpm == 90.0

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
    assert controller._last_cadence_rpm == 90.0

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
    assert controller._last_cadence_rpm == 90.0

    # Advance past the staleness threshold (3 s)
    monotonic_now = 4.0
    controller.receive_cadence_rpm(75.0, CadenceSource.POWER_METER)
    assert controller._last_cadence_rpm == 75.0

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

    assert len(controller._cadence_history) == 1
    assert controller._cadence_history[0][1] == 90.0

    controller.shutdown()
