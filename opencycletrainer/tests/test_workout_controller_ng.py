"""Tests for NiceGUI workout session controller (Phase 3)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time

import pytest

from opencycletrainer.core.workout_engine import EngineState
from opencycletrainer.storage.settings import AppSettings

_DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockTimer:
    """Thin mock for nicegui.ui.timer."""

    def __init__(self, interval: float, callback, *, active: bool = True) -> None:
        self.interval = interval
        self.callback = callback
        self.active = active

    def activate(self) -> None:
        self.active = True

    def deactivate(self) -> None:
        self.active = False

    def cancel(self) -> None:
        self.active = False


class _MockScreen:
    """Fake WorkoutScreen_ng for controller tests."""

    def __init__(self) -> None:
        self.session_state: str | None = None
        self.workout_name: str | None = None
        self.alerts: list[tuple[str, str]] = []
        self.mandatory_metrics: dict = {}
        self.tile_values: dict = {}
        self.resistance: int | None = None
        self.opentrueup_offset: int | None = None
        self.trainer_controls_visible = False
        self.pause_elapsed: str | None = None
        self.pause_countdown: int | None = None
        self.callbacks: dict = {}
        self.chart_loaded = False
        self.charts_updated = 0

    def set_session_state(self, state: str) -> None:
        self.session_state = state

    def set_workout_name(self, name: str | None) -> None:
        self.workout_name = name

    def show_alert(self, msg: str, alert_type: str = "error") -> None:
        self.alerts.append((msg, alert_type))

    def clear_alert(self) -> None:
        self.alerts.clear()

    def set_mandatory_metrics(self, **kwargs) -> None:
        self.mandatory_metrics = kwargs

    def set_mode_state(self, mode: str) -> None:
        pass

    def set_resistance_level(self, level: int | None) -> None:
        self.resistance = level

    def set_opentrueup_offset_watts(self, offset: int | None) -> None:
        self.opentrueup_offset = offset

    def set_trainer_controls_visible(self, visible: bool) -> None:
        self.trainer_controls_visible = visible

    def set_tile_value(self, key: str, val: str) -> None:
        self.tile_values[key] = val

    def get_selected_tile_keys(self) -> list[str]:
        return []

    def load_workout_chart(self, workout: object, ftp: int) -> None:
        self.chart_loaded = True

    def update_charts(self, *args) -> None:
        self.charts_updated += 1

    def add_skip_marker(self, before: float, after: float) -> None:
        pass

    def export_chart_image(self, path: object) -> None:
        pass

    def set_pause_elapsed(self, text: str) -> None:
        self.pause_elapsed = text

    def set_pause_countdown(self, n: int | None) -> None:
        self.pause_countdown = n

    def set_callbacks(self, **kwargs) -> None:
        self.callbacks.update(kwargs)


class _FakeRecorder:
    def __init__(self) -> None:
        self.started = False
        self.recording_enabled = False
        self.samples: list[object] = []
        self.stop_calls = 0

    def start(self, workout_name: str, started_at_utc: object) -> object:
        self.started = True
        self.recording_enabled = True
        return SimpleNamespace(workout_name=workout_name)

    def set_recording_active(self, active: bool) -> None:
        if not self.started:
            raise RuntimeError("Recorder not active.")
        self.recording_enabled = bool(active)

    def record_sample(self, sample: object) -> bool:
        if not self.started:
            raise RuntimeError("Recorder not active.")
        self.samples.append(sample)
        return True

    def stop(self, finished_at_utc: object) -> object:
        if not self.started:
            raise RuntimeError("Recorder not active.")
        self.started = False
        self.recording_enabled = False
        self.stop_calls += 1
        return SimpleNamespace(fit_file_path=Path("workout_20260314.fit"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_ui_timer(monkeypatch):
    """Replace nicegui.ui.timer with _MockTimer for all tests in this module."""
    import nicegui.ui as _nicegui_ui
    monkeypatch.setattr(_nicegui_ui, "timer", _MockTimer)


def _make_controller(
    *,
    screen: _MockScreen | None = None,
    recorder: _FakeRecorder | None = None,
    settings: AppSettings | None = None,
    summary_factory=None,
):
    from opencycletrainer.ui.workout_controller_ng import WorkoutSessionController

    _screen = screen or _MockScreen()
    _recorder = recorder or _FakeRecorder()
    _settings = settings or AppSettings(ftp=200)
    # Default summary factory: immediately calls on_done (skip the dialog)
    _summary = summary_factory if summary_factory is not None else (lambda s, cb: cb())

    monotonic_now = [0.0]

    ctrl = WorkoutSessionController(
        screen=_screen,
        settings=_settings,
        recorder=_recorder,
        summary_dialog_factory=_summary,
        monotonic_clock=lambda: monotonic_now[0],
    )
    return ctrl, _screen, _settings, monotonic_now


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def test_init_sets_idle_state() -> None:
    ctrl, screen, _, _ = _make_controller()
    assert screen.session_state == "idle"
    assert screen.workout_name is None


def test_init_wires_callbacks() -> None:
    ctrl, screen, _, _ = _make_controller()
    assert "on_start" in screen.callbacks
    assert "on_pause" in screen.callbacks
    assert "on_stop" in screen.callbacks


# ---------------------------------------------------------------------------
# load_workout
# ---------------------------------------------------------------------------


def test_load_workout_sets_name_and_ready_state() -> None:
    ctrl, screen, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    assert screen.workout_name is not None
    assert screen.session_state == "ready"


def test_load_workout_invalid_file_shows_alert(tmp_path) -> None:
    bad = tmp_path / "bad.mrc"
    bad.write_text("NOT VALID MRC CONTENT")
    ctrl, screen, _, _ = _make_controller()
    ctrl.load_workout(bad)
    assert len(screen.alerts) == 1
    assert screen.alerts[0][1] in ("error", "warning")


def test_load_workout_missing_file_shows_alert(tmp_path) -> None:
    ctrl, screen, _, _ = _make_controller()
    ctrl.load_workout(tmp_path / "does_not_exist.mrc")
    assert len(screen.alerts) == 1


# ---------------------------------------------------------------------------
# process_tick
# ---------------------------------------------------------------------------


def test_process_tick_returns_none_without_workout() -> None:
    ctrl, _, _, _ = _make_controller()
    assert ctrl.process_tick() is None


def test_process_tick_returns_snapshot_after_start(tmp_path) -> None:
    ctrl, screen, _, mono = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    mono[0] = 1.0
    snapshot = ctrl.process_tick(1.0)
    assert snapshot is not None
    assert snapshot.state in {EngineState.RUNNING, EngineState.RAMP_IN}


def test_process_tick_updates_elapsed_metric(tmp_path) -> None:
    ctrl, screen, _, mono = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    mono[0] = 5.0
    ctrl.process_tick(5.0)
    assert "00:00:05" in screen.mandatory_metrics.get("elapsed_text", "")


# ---------------------------------------------------------------------------
# Start / Pause / Resume / Stop
# ---------------------------------------------------------------------------


def test_start_workout_activates_tick_timer() -> None:
    ctrl, _, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    assert ctrl._timer.active


def test_pause_sets_paused_state() -> None:
    ctrl, screen, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    ctrl._pause_workout()
    assert screen.session_state == "paused"


def test_resume_resumes_engine() -> None:
    ctrl, screen, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    ctrl._pause_workout()
    ctrl._resume_workout()
    # State transitions to RAMP_IN or RUNNING after resume
    assert screen.session_state in {"ramp_in", "running"}


def test_stop_deactivates_timers_and_shows_summary() -> None:
    done_called = [False]

    def _factory(summary, on_done):
        done_called[0] = True
        on_done()

    ctrl, screen, _, _ = _make_controller(summary_factory=_factory)
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    ctrl._stop_workout()

    assert not ctrl._timer.active
    assert done_called[0]
    # After summary dismissed, reset to idle
    assert screen.session_state == "idle"


def test_stop_finalises_recorder() -> None:
    recorder = _FakeRecorder()
    ctrl, _, _, _ = _make_controller(recorder=recorder)
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    ctrl._stop_workout()
    assert recorder.stop_calls == 1


# ---------------------------------------------------------------------------
# Sensor data
# ---------------------------------------------------------------------------


def test_receive_power_accumulates_for_tiles() -> None:
    settings = AppSettings(
        ftp=200,
        tile_selections=["workout_avg_power", "heart_rate"],
        windowed_power_window_seconds=3,
    )
    ctrl, screen, _, mono = _make_controller(settings=settings)

    # Re-create so screen has the right tile keys (get_selected_tile_keys)
    class _ScreenWithTiles(_MockScreen):
        def get_selected_tile_keys(self):
            return ["workout_avg_power", "heart_rate"]

    tile_screen = _ScreenWithTiles()
    ctrl2, _, _, mono2 = _make_controller(screen=tile_screen, settings=settings)

    ctrl2.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl2._start_workout()
    ctrl2.receive_power_watts(200, now_monotonic=1.0)
    ctrl2.receive_power_watts(300, now_monotonic=2.0)
    ctrl2.receive_hr_bpm(145)
    mono2[0] = 2.0
    ctrl2.process_tick(2.0)

    assert "250 W" in tile_screen.tile_values.get("workout_avg_power", "")
    assert "145 bpm" in tile_screen.tile_values.get("heart_rate", "")


def test_receive_cadence_rpm() -> None:
    ctrl, _, _, _ = _make_controller()
    ctrl.receive_cadence_rpm(85.0)
    assert ctrl._last_cadence_rpm == 85.0


def test_receive_speed_mps() -> None:
    ctrl, _, _, _ = _make_controller()
    ctrl.receive_speed_mps(7.5)
    assert ctrl._last_speed_mps == 7.5


# ---------------------------------------------------------------------------
# Extend / Skip
# ---------------------------------------------------------------------------


def test_extend_interval_increases_duration() -> None:
    ctrl, screen, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    initial_duration = ctrl.last_snapshot.total_duration_seconds
    ctrl._start_workout()
    ctrl._extend_interval(60, False)
    assert ctrl.last_snapshot.total_duration_seconds == initial_duration + 60


def test_skip_advances_interval() -> None:
    ctrl, _, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    idx_before = ctrl.last_snapshot.current_interval_index
    ctrl._skip_interval()
    assert ctrl.last_snapshot.current_interval_index != idx_before


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def test_shutdown_cancels_timers() -> None:
    ctrl, _, _, _ = _make_controller()
    ctrl.load_workout(_DATA_DIR / "ramp.mrc")
    ctrl._start_workout()
    ctrl.shutdown()
    assert not ctrl._timer.active
    assert not ctrl._chart_timer.active


# ---------------------------------------------------------------------------
# apply_settings
# ---------------------------------------------------------------------------


def test_apply_settings_updates_ftp() -> None:
    ctrl, _, _, _ = _make_controller()
    new_settings = AppSettings(ftp=300)
    ctrl.apply_settings(new_settings)
    assert ctrl._settings.ftp == 300
