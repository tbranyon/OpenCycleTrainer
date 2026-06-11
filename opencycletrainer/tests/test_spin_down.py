from __future__ import annotations

from opencycletrainer.core.control.ftms_control import (
    FTMSControl,
    FTMSControlError,
    SpinDownTargetSpeeds,
)
from opencycletrainer.core.control.spin_down import (
    SpinDownController,
    SpinDownPhase,
)
from opencycletrainer.devices.mock_backend import MockFTMSControlTransport


def _inline(fn) -> None:
    fn()


class _FakeControl:
    def __init__(self, *, target=(30.0, 35.0), fail=False) -> None:
        self.target = target
        self.fail = fail
        self.ignored = 0

    def start_spin_down(self) -> SpinDownTargetSpeeds:
        if self.fail:
            raise FTMSControlError("simulated spin-down failure")
        return SpinDownTargetSpeeds(low_kmh=self.target[0], high_kmh=self.target[1])

    def ignore_spin_down(self) -> None:
        self.ignored += 1


def test_spin_down_happy_path_emits_full_state_sequence():
    states = []
    captured = {}
    control = _FakeControl(target=(30.0, 35.0))
    controller = SpinDownController(
        control,
        subscribe_status=lambda handler: captured.__setitem__("handler", handler),
        status_callback=states.append,
        runner=_inline,
    )

    controller.start()

    assert [s.phase for s in states] == [SpinDownPhase.STARTING, SpinDownPhase.SPIN_UP]
    assert states[-1].target_low_kmh == 30.0
    assert states[-1].target_high_kmh == 35.0

    handler = captured["handler"]
    handler(bytes([0x14, 0x04]))  # Stop Pedaling
    handler(bytes([0x14, 0x02]))  # Success

    assert [s.phase for s in states[-2:]] == [
        SpinDownPhase.STOP_PEDALING,
        SpinDownPhase.SUCCESS,
    ]


def test_spin_down_error_status_emits_error():
    states = []
    captured = {}
    controller = SpinDownController(
        _FakeControl(),
        subscribe_status=lambda handler: captured.__setitem__("handler", handler),
        status_callback=states.append,
        runner=_inline,
    )

    controller.start()
    captured["handler"](bytes([0x14, 0x03]))  # Error

    assert states[-1].phase is SpinDownPhase.ERROR


def test_spin_down_control_failure_emits_error():
    states = []
    controller = SpinDownController(
        _FakeControl(fail=True),
        subscribe_status=lambda handler: None,
        status_callback=states.append,
        runner=_inline,
    )

    controller.start()

    assert states[-1].phase is SpinDownPhase.ERROR


def test_spin_down_cancel_sends_ignore():
    control = _FakeControl()
    controller = SpinDownController(
        control,
        subscribe_status=lambda handler: None,
        status_callback=lambda state: None,
        runner=_inline,
    )

    controller.start()
    controller.cancel()

    assert control.ignored == 1


def test_spin_down_controller_drives_ftms_control_with_mock_transport():
    transport = MockFTMSControlTransport(
        target_low_raw=3000,
        target_high_raw=3500,
        auto_sequence=False,
    )
    control = FTMSControl(transport, ack_timeout_seconds=0.5, write_timeout_seconds=0.5)
    states = []
    controller = SpinDownController(
        control,
        subscribe_status=transport.subscribe_status,
        status_callback=states.append,
        runner=_inline,
    )

    controller.start()

    assert states[-1].phase is SpinDownPhase.SPIN_UP
    assert states[-1].target_low_kmh == 30.0
    assert states[-1].target_high_kmh == 35.0

    transport.emit_spin_down_status(0x04)  # Stop Pedaling
    transport.emit_spin_down_status(0x02)  # Success

    assert [s.phase for s in states[-2:]] == [
        SpinDownPhase.STOP_PEDALING,
        SpinDownPhase.SUCCESS,
    ]


def test_spin_down_ignores_status_after_completion():
    states = []
    captured = {}
    controller = SpinDownController(
        _FakeControl(),
        subscribe_status=lambda handler: captured.__setitem__("handler", handler),
        status_callback=states.append,
        runner=_inline,
    )

    controller.start()
    handler = captured["handler"]
    handler(bytes([0x14, 0x02]))  # Success → procedure complete
    count = len(states)
    handler(bytes([0x14, 0x04]))  # late Stop Pedaling should be ignored

    assert len(states) == count
