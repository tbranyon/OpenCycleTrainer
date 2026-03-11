from __future__ import annotations

from concurrent.futures import Future

import pytest

from opencycletrainer.core.control.ftms_control import (
    ControlMode,
    FTMSControl,
    FTMSControlAckError,
    FTMSControlAckTimeoutError,
    FTMSControlError,
    WorkoutEngineFTMSBridge,
)
from opencycletrainer.core.workout_engine import WorkoutEngine
from opencycletrainer.core.workout_model import Workout, WorkoutInterval


class _FakeFTMSTransport:
    def __init__(self, *, auto_ack: bool = True, ack_result_code: int = 0x01) -> None:
        self.auto_ack = auto_ack
        self.ack_result_code = ack_result_code
        self.writes: list[bytes] = []
        self._handler = lambda _: None

    def write_control_point(self, payload: bytes) -> Future[None]:
        self.writes.append(payload)
        future: Future[None] = Future()
        future.set_result(None)
        if self.auto_ack:
            self._handler(bytes([0x80, payload[0], self.ack_result_code]))
        return future

    def set_indication_handler(self, handler):
        self._handler = handler


class _StubControl:
    def __init__(self, *, mode: ControlMode = ControlMode.ERG, fail_on_apply: bool = False) -> None:
        self.mode = mode
        self.fail_on_apply = fail_on_apply
        self.erg_targets: list[int] = []
        self.resistance_levels: list[float] = []

    def set_mode_erg(self) -> None:
        self.mode = ControlMode.ERG

    def set_mode_resistance(self) -> None:
        self.mode = ControlMode.RESISTANCE

    def set_erg_target_watts(self, watts: int) -> None:
        if self.fail_on_apply:
            raise FTMSControlError("simulated trainer write failure")
        self.erg_targets.append(watts)

    def set_resistance_level(self, level: float) -> None:
        if self.fail_on_apply:
            raise FTMSControlError("simulated trainer write failure")
        self.resistance_levels.append(level)


def _build_workout() -> Workout:
    intervals = (
        WorkoutInterval(
            start_offset_seconds=0,
            duration_seconds=10,
            start_percent_ftp=50.0,
            end_percent_ftp=50.0,
            start_target_watts=150,
            end_target_watts=150,
        ),
        WorkoutInterval(
            start_offset_seconds=10,
            duration_seconds=20,
            start_percent_ftp=75.0,
            end_percent_ftp=75.0,
            start_target_watts=225,
            end_target_watts=225,
        ),
    )
    return Workout(name="Bridge Test", ftp_watts=300, intervals=intervals)


def test_ftms_control_encodes_erg_and_resistance_commands_and_waits_for_ack():
    transport = _FakeFTMSTransport()
    control = FTMSControl(transport, ack_timeout_seconds=0.2, write_timeout_seconds=0.2)

    ack_erg = control.set_erg_target_watts(250)
    ack_res = control.set_resistance_level(42.3)

    assert ack_erg.result_label == "success"
    assert ack_res.result_label == "success"
    assert transport.writes == [
        b"\x00",
        b"\x05\xfa\x00",
        b"\x04\xa7\x01",
    ]


def test_ftms_control_raises_timeout_when_ack_is_missing():
    transport = _FakeFTMSTransport(auto_ack=False)
    control = FTMSControl(transport, ack_timeout_seconds=0.01, write_timeout_seconds=0.2)

    with pytest.raises(FTMSControlAckTimeoutError):
        control.set_erg_target_watts(200)


def test_ftms_control_raises_ack_error_for_non_success_result():
    transport = _FakeFTMSTransport(auto_ack=True, ack_result_code=0x04)
    control = FTMSControl(transport, ack_timeout_seconds=0.2, write_timeout_seconds=0.2)

    with pytest.raises(FTMSControlAckError):
        control.set_erg_target_watts(200)


def test_bridge_interval_changes_trigger_control_commands_via_engine_snapshot_updates():
    stub_control = _StubControl(mode=ControlMode.ERG)
    bridge = WorkoutEngineFTMSBridge(stub_control)
    workout = _build_workout()
    engine = WorkoutEngine(
        on_snapshot_update=lambda snapshot: bridge.on_engine_snapshot(snapshot, workout),
    )

    engine.load_workout(workout)
    engine.start()
    engine.tick(0)
    engine.tick(10)

    assert stub_control.erg_targets == [150, 225]


def test_bridge_pause_sets_zero_for_current_mode():
    workout = _build_workout()

    erg_stub = _StubControl(mode=ControlMode.ERG)
    erg_bridge = WorkoutEngineFTMSBridge(erg_stub)
    erg_engine = WorkoutEngine(
        on_snapshot_update=lambda snapshot: erg_bridge.on_engine_snapshot(snapshot, workout),
    )
    erg_engine.load_workout(workout)
    erg_engine.start()
    erg_engine.pause()
    assert erg_stub.erg_targets[-1] == 0

    resistance_stub = _StubControl(mode=ControlMode.RESISTANCE)
    resistance_bridge = WorkoutEngineFTMSBridge(resistance_stub, mode=ControlMode.RESISTANCE)
    resistance_engine = WorkoutEngine(
        on_snapshot_update=lambda snapshot: resistance_bridge.on_engine_snapshot(snapshot, workout),
    )
    resistance_engine.load_workout(workout)
    resistance_engine.start()
    resistance_engine.pause()
    assert resistance_stub.resistance_levels[-1] == 0


def test_bridge_reports_control_errors_to_alert_callback():
    alerts: list[str] = []
    failing_control = _StubControl(mode=ControlMode.ERG, fail_on_apply=True)
    bridge = WorkoutEngineFTMSBridge(failing_control, alert_callback=alerts.append)
    workout = _build_workout()
    engine = WorkoutEngine(
        on_snapshot_update=lambda snapshot: bridge.on_engine_snapshot(snapshot, workout),
    )

    engine.load_workout(workout)
    engine.start()

    assert alerts
    assert "Trainer control error:" in alerts[0]
