from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import threading

from opencycletrainer.core.control.ftms_control import FTMSControlError
from opencycletrainer.devices.decoders.ftms import (
    SpinDownStatus,
    decode_fitness_machine_status,
)

_logger = logging.getLogger(__name__)


class SpinDownPhase(Enum):
    """Lifecycle phases of an FTMS spin-down calibration."""

    IDLE = "idle"
    STARTING = "starting"
    SPIN_UP = "spin_up"
    STOP_PEDALING = "stop_pedaling"
    SUCCESS = "success"
    ERROR = "error"


@dataclass(frozen=True)
class SpinDownState:
    """Snapshot of spin-down progress emitted to observers."""

    phase: SpinDownPhase
    target_low_kmh: float | None = None
    target_high_kmh: float | None = None
    message: str | None = None


class _SpinDownControl:
    """Minimal control surface the controller needs (satisfied by FTMSControl)."""

    def start_spin_down(self): ...  # -> SpinDownTargetSpeeds

    def ignore_spin_down(self): ...


def _thread_runner(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="spin-down", daemon=True).start()


class SpinDownController:
    """Orchestrates the FTMS spin-down procedure and reports progress via a callback.

    The control-point handshake blocks while waiting for the trainer's ack, so it is run
    off the caller's thread via ``runner``. Subsequent progress arrives as Fitness Machine
    Status (0x2ADA) notifications routed through ``subscribe_status``.
    """

    def __init__(
        self,
        control: _SpinDownControl,
        *,
        subscribe_status: Callable[[Callable[[bytes], None]], None],
        status_callback: Callable[[SpinDownState], None],
        runner: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._control = control
        self._subscribe_status = subscribe_status
        self._status_callback = status_callback
        self._runner = runner or _thread_runner
        self._active = False
        self._target_low_kmh: float | None = None
        self._target_high_kmh: float | None = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        """Begin a spin-down: subscribe for status, then run the handshake off-thread."""
        if self._active:
            return
        self._active = True
        self._target_low_kmh = None
        self._target_high_kmh = None
        try:
            self._subscribe_status(self._on_status_payload)
        except Exception as exc:
            self._active = False
            self._emit(SpinDownPhase.ERROR, message="Could not subscribe to trainer status.")
            _logger.warning("Spin-down status subscription failed: %s", exc)
            return
        self._runner(self._run_handshake)

    def cancel(self) -> None:
        """Abort an in-progress spin-down, telling the trainer to ignore the request."""
        if not self._active:
            return
        self._active = False
        try:
            self._control.ignore_spin_down()
        except FTMSControlError as exc:
            _logger.warning("Spin-down cancel (ignore) failed: %s", exc)

    def _run_handshake(self) -> None:
        self._emit(SpinDownPhase.STARTING)
        try:
            speeds = self._control.start_spin_down()
        except FTMSControlError as exc:
            self._active = False
            self._emit(SpinDownPhase.ERROR, message="Could not start spin-down on the trainer.")
            _logger.warning("Spin-down start failed: %s", exc)
            return
        self._target_low_kmh = speeds.low_kmh
        self._target_high_kmh = speeds.high_kmh
        self._emit(SpinDownPhase.SPIN_UP)

    def _on_status_payload(self, payload: bytes) -> None:
        if not self._active:
            return
        try:
            status = decode_fitness_machine_status(payload)
        except ValueError:
            return
        spin_down = status.spin_down_status
        if spin_down is None:
            return
        if spin_down is SpinDownStatus.STOP_PEDALING:
            self._emit(SpinDownPhase.STOP_PEDALING)
        elif spin_down is SpinDownStatus.SUCCESS:
            self._active = False
            self._emit(SpinDownPhase.SUCCESS)
        elif spin_down is SpinDownStatus.ERROR:
            self._active = False
            self._emit(SpinDownPhase.ERROR, message="Spin-down failed. Please retry.")

    def _emit(self, phase: SpinDownPhase, *, message: str | None = None) -> None:
        state = SpinDownState(
            phase=phase,
            target_low_kmh=self._target_low_kmh,
            target_high_kmh=self._target_high_kmh,
            message=message,
        )
        self._status_callback(state)
