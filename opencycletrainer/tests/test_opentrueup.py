from __future__ import annotations

import json

from opencycletrainer.core.control.ftms_control import ControlMode, WorkoutEngineFTMSBridge
from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.core.workout_engine import WorkoutEngine
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.storage.opentrueup_offsets import OpenTrueUpOffsetStore, build_pair_key


class _MemoryOffsetStore:
    def __init__(self, initial_offset: int = 0) -> None:
        self._offset = int(initial_offset)
        self.set_calls: list[int] = []

    def get_offset_watts(self, trainer_id: str, power_meter_id: str) -> int:
        return self._offset

    def set_offset_watts(self, trainer_id: str, power_meter_id: str, offset_watts: int) -> int:
        self._offset = int(offset_watts)
        self.set_calls.append(self._offset)
        return self._offset


class _StubControl:
    def __init__(self, mode: ControlMode = ControlMode.ERG) -> None:
        self.mode = mode
        self.erg_targets: list[int] = []
        self.resistance_levels: list[float] = []

    def set_mode_erg(self) -> None:
        self.mode = ControlMode.ERG

    def set_mode_resistance(self) -> None:
        self.mode = ControlMode.RESISTANCE

    def set_erg_target_watts(self, watts: int) -> None:
        self.erg_targets.append(int(watts))

    def set_resistance_level(self, level: float) -> None:
        self.resistance_levels.append(float(level))


def _build_workout(*interval_targets: tuple[int, float, int]) -> Workout:
    intervals = []
    start_offset = 0
    for duration_seconds, percent_ftp, target_watts in interval_targets:
        intervals.append(
            WorkoutInterval(
                start_offset_seconds=start_offset,
                duration_seconds=duration_seconds,
                start_percent_ftp=percent_ftp,
                end_percent_ftp=percent_ftp,
                start_target_watts=target_watts,
                end_target_watts=target_watts,
            ),
        )
        start_offset += duration_seconds
    return Workout(name="OpenTrueUp Test", ftp_watts=300, intervals=tuple(intervals))


def test_opentrueup_offset_store_round_trip(tmp_path):
    store_path = tmp_path / "opentrueup_offsets.json"
    store = OpenTrueUpOffsetStore(store_path)

    assert store.get_offset_watts("trainer-1", "pm-1") == 0
    store.set_offset_watts("Trainer-1", "PM-1", 14)

    assert store.get_offset_watts("trainer-1", "pm-1") == 14
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw[build_pair_key("trainer-1", "pm-1")] == 14


def test_opentrueup_uses_30s_window_and_updates_every_5s_when_offset_changes():
    store = _MemoryOffsetStore(initial_offset=0)
    controller = OpenTrueUpController(
        enabled=True,
        window_seconds=30.0,
        update_interval_seconds=5.0,
        dropout_seconds=3.0,
        offset_store=store,
        trainer_id="trainer",
        power_meter_id="pm",
    )

    status_at_5 = None
    for timestamp in range(0, 6):
        status = controller.record_power_sample(
            timestamp=float(timestamp),
            trainer_power_watts=200,
            bike_power_watts=210,
        )
        if timestamp == 5:
            status_at_5 = status
    assert status_at_5 is not None
    assert status_at_5.offset_watts == 10
    assert status_at_5.offset_changed is True
    assert store.set_calls == [10]

    # Keep feeding with the same offset for another update cycle.
    status_at_10 = None
    for timestamp in range(6, 11):
        status = controller.record_power_sample(
            timestamp=float(timestamp),
            trainer_power_watts=205,
            bike_power_watts=215,
        )
        if timestamp == 10:
            status_at_10 = status
    assert status_at_10 is not None
    assert status_at_10.offset_watts == 10
    assert status_at_10.offset_changed is False
    assert store.set_calls == [10]


def test_opentrueup_window_drops_old_samples_before_recomputing_offset():
    controller = OpenTrueUpController(
        enabled=True,
        window_seconds=30.0,
        update_interval_seconds=5.0,
        dropout_seconds=3.0,
        initial_offset_watts=0,
    )

    # An early outlier affects the first 5-second update.
    controller.record_power_sample(timestamp=0.0, trainer_power_watts=100, bike_power_watts=200)
    for timestamp in range(1, 6):
        status = controller.record_power_sample(
            timestamp=float(timestamp),
            trainer_power_watts=200,
            bike_power_watts=210,
        )
    assert status.offset_watts == 25

    # At t=35, the t=0 outlier is outside the 30s window and no longer affects the average.
    status = controller.record_power_sample(
        timestamp=35.0,
        trainer_power_watts=200,
        bike_power_watts=210,
    )
    assert status.offset_watts == 10
    assert status.offset_changed is True


def test_bridge_applies_offset_in_erg_and_holds_setpoint_during_pm_dropout():
    workout = _build_workout((10, 70.0, 200), (10, 80.0, 240))
    control = _StubControl(mode=ControlMode.ERG)
    opentrueup = OpenTrueUpController(
        enabled=True,
        window_seconds=30.0,
        update_interval_seconds=1000.0,
        dropout_seconds=3.0,
        initial_offset_watts=10,
    )
    bridge = WorkoutEngineFTMSBridge(control, opentrueup=opentrueup)
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: bridge.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0.0)
    assert control.erg_targets == [210]

    bridge.on_power_sample(timestamp=1.0, trainer_power_watts=200, bike_power_watts=210)
    bridge.on_power_sample(timestamp=2.0, trainer_power_watts=200, bike_power_watts=210)
    bridge.on_power_sample(timestamp=6.0, trainer_power_watts=200, bike_power_watts=None)

    # Interval changes while PM dropout is active: setpoint should hold.
    engine.tick(10.0)
    assert control.erg_targets == [210]
    assert opentrueup.dropout_active is True

    # PM returns; bridge reapplies current interval target with the last good offset.
    bridge.on_power_sample(timestamp=12.0, trainer_power_watts=230, bike_power_watts=240)
    assert opentrueup.dropout_active is False
    assert control.erg_targets[-1] == 250


def test_opentrueup_reapply_after_pm_dropout_preserves_active_jog_offset():
    """When OpenTrueUp re-applies after PM dropout recovery, the active jog offset must be preserved."""
    workout = _build_workout((30, 70.0, 200))
    control = _StubControl(mode=ControlMode.ERG)
    opentrueup = OpenTrueUpController(
        enabled=True,
        window_seconds=30.0,
        update_interval_seconds=1000.0,
        dropout_seconds=3.0,
        initial_offset_watts=10,
    )
    bridge = WorkoutEngineFTMSBridge(control, opentrueup=opentrueup)
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: bridge.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0.0)
    assert control.erg_targets == [210]  # 200 base + 10 OTU offset

    # User applies a +20W jog: trainer should get 200 + 20 + 10 = 230W.
    bridge.set_erg_jog_offset_watts(20.0)
    assert control.erg_targets[-1] == 230

    # Simulate PM dropout.
    bridge.on_power_sample(timestamp=1.0, trainer_power_watts=200, bike_power_watts=210)
    bridge.on_power_sample(timestamp=5.0, trainer_power_watts=200, bike_power_watts=None)
    assert opentrueup.dropout_active is True

    # PM returns → OTU requires re-apply → jog must be preserved: 200 + 20 + 10 = 230W.
    bridge.on_power_sample(timestamp=9.0, trainer_power_watts=200, bike_power_watts=210)
    assert opentrueup.dropout_active is False
    assert control.erg_targets[-1] == 230


def test_bridge_computes_offset_in_background_when_control_mode_is_resistance():
    workout = _build_workout((15, 70.0, 200))
    control = _StubControl(mode=ControlMode.RESISTANCE)
    opentrueup = OpenTrueUpController(
        enabled=True,
        window_seconds=30.0,
        update_interval_seconds=5.0,
        dropout_seconds=3.0,
        initial_offset_watts=0,
    )
    bridge = WorkoutEngineFTMSBridge(
        control,
        mode=ControlMode.RESISTANCE,
        opentrueup=opentrueup,
    )
    engine = WorkoutEngine(on_snapshot_update=lambda snapshot: bridge.on_engine_snapshot(snapshot, workout))

    engine.load_workout(workout)
    engine.start()
    engine.tick(0.0)
    assert control.resistance_levels == [70.0]
    assert control.erg_targets == []

    for timestamp in range(0, 6):
        bridge.on_power_sample(
            timestamp=float(timestamp),
            trainer_power_watts=200,
            bike_power_watts=212,
        )

    assert opentrueup.offset_watts == 12
    assert control.erg_targets == []
