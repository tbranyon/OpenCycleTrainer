from __future__ import annotations

from opencycletrainer.core.control.hybrid_mode import (
    HOTKEY_DOWN,
    HOTKEY_LEFT,
    HOTKEY_RIGHT,
    HOTKEY_UP,
    HybridModeController,
)
from opencycletrainer.core.control.ftms_control import ControlMode
from opencycletrainer.core.workout_engine import WorkoutEngine
from opencycletrainer.core.workout_model import Workout, WorkoutInterval


class _StubControl:
    def __init__(self) -> None:
        self.mode = ControlMode.ERG
        self.mode_changes: list[ControlMode] = []
        self.erg_targets: list[int] = []
        self.resistance_levels: list[float] = []

    def set_mode_erg(self) -> None:
        self.mode = ControlMode.ERG
        self.mode_changes.append(ControlMode.ERG)

    def set_mode_resistance(self) -> None:
        self.mode = ControlMode.RESISTANCE
        self.mode_changes.append(ControlMode.RESISTANCE)

    def set_erg_target_watts(self, watts: int) -> None:
        self.erg_targets.append(int(watts))

    def set_resistance_level(self, percent_or_unit: float) -> None:
        self.resistance_levels.append(float(percent_or_unit))


def _build_workout(*interval_defs: tuple[int, float, int]) -> Workout:
    intervals = []
    start_offset = 0
    for duration, start_percent, target_watts in interval_defs:
        intervals.append(
            WorkoutInterval(
                start_offset_seconds=start_offset,
                duration_seconds=duration,
                start_percent_ftp=start_percent,
                end_percent_ftp=start_percent,
                start_target_watts=target_watts,
                end_target_watts=target_watts,
            ),
        )
        start_offset += duration
    return Workout(name="Hybrid Test", ftp_watts=300, intervals=tuple(intervals))


def test_hybrid_mode_switches_at_interval_boundaries():
    workout = _build_workout((10, 50.0, 150), (10, 80.0, 240), (10, 45.0, 135))
    control = _StubControl()
    controller = HybridModeController(control)
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: controller.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0)
    engine.tick(10)
    engine.tick(20)

    assert control.mode_changes == [ControlMode.ERG, ControlMode.RESISTANCE, ControlMode.ERG]
    assert control.erg_targets == [150, 135]
    assert control.resistance_levels == [80.0]


def test_hybrid_mode_remembers_last_work_resistance_across_work_intervals():
    workout = _build_workout((10, 80.0, 240), (10, 50.0, 150), (10, 90.0, 270))
    control = _StubControl()
    controller = HybridModeController(control)
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: controller.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0)
    assert control.resistance_levels == [80.0]

    changed = controller.handle_resistance_hotkey(HOTKEY_RIGHT)
    assert changed is True
    assert control.resistance_levels[-1] == 85.0

    engine.tick(10)
    assert control.mode == ControlMode.ERG

    engine.tick(20)
    assert control.mode == ControlMode.RESISTANCE
    assert control.resistance_levels[-1] == 85.0


def test_hybrid_mode_resistance_hotkeys_apply_only_in_work_intervals():
    workout = _build_workout((10, 50.0, 150), (10, 70.0, 210))
    control = _StubControl()
    controller = HybridModeController(control)
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: controller.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0)

    assert controller.handle_resistance_hotkey(HOTKEY_UP) is False
    assert controller.handle_resistance_hotkey(HOTKEY_LEFT) is False

    engine.tick(10)
    assert controller.handle_resistance_hotkey(HOTKEY_UP) is True
    assert controller.handle_resistance_hotkey(HOTKEY_DOWN) is True
    assert controller.handle_resistance_hotkey(HOTKEY_LEFT) is True

    assert control.resistance_levels == [70.0, 71.0, 70.0, 65.0]


def test_hybrid_mode_pause_sets_zero_in_active_mode():
    workout = _build_workout((10, 80.0, 240), (10, 50.0, 150))
    control = _StubControl()
    controller = HybridModeController(control)
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: controller.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0)
    engine.pause()
    assert control.mode == ControlMode.RESISTANCE
    assert control.resistance_levels[-1] == 0.0

    engine.resume()
    engine.tick(1)
    engine.tick(4)
    engine.skip_interval()
    assert control.mode == ControlMode.ERG
    engine.pause()
    assert control.erg_targets[-1] == 0
