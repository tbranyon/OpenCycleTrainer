from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging
import threading
from typing import Protocol

_logger = logging.getLogger(__name__)

from opencycletrainer.core.control.opentrueup import OpenTrueUpController, OpenTrueUpStatus
from opencycletrainer.core.workout_engine import EngineState, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.devices.types import FTMS_CONTROL_POINT_CHARACTERISTIC_UUID

_OPCODE_REQUEST_CONTROL = 0x00
_OPCODE_SET_TARGET_RESISTANCE = 0x04
_OPCODE_SET_TARGET_POWER = 0x05
_OPCODE_RESPONSE_CODE = 0x80

_RESULT_SUCCESS = 0x01

_OPCODE_LABELS = {
    _OPCODE_REQUEST_CONTROL: "request_control",
    _OPCODE_SET_TARGET_RESISTANCE: "set_target_resistance",
    _OPCODE_SET_TARGET_POWER: "set_target_power",
}

_RESULT_LABELS = {
    0x01: "success",
    0x02: "op_code_not_supported",
    0x03: "invalid_parameter",
    0x04: "operation_failed",
    0x05: "control_not_permitted",
}


class ControlMode(str, Enum):
    ERG = "erg"
    RESISTANCE = "resistance"


class FTMSControlError(RuntimeError):
    """Base error for FTMS trainer control failures."""


class FTMSControlAckTimeoutError(FTMSControlError):
    """Raised when a control-point ack does not arrive in time."""


class FTMSControlAckError(FTMSControlError):
    """Raised when a control-point ack returns a non-success result."""


@dataclass(frozen=True)
class FTMSControlAck:
    request_opcode: int
    result_code: int

    @property
    def request_label(self) -> str:
        return _OPCODE_LABELS.get(self.request_opcode, f"opcode_{self.request_opcode}")

    @property
    def result_label(self) -> str:
        return _RESULT_LABELS.get(self.result_code, f"result_{self.result_code}")


class FTMSControlTransport(Protocol):
    """Transport abstraction for FTMS control-point writes and indications."""

    def write_control_point(self, payload: bytes) -> Future[None]:
        """Send a write to the FTMS control point characteristic."""

    def set_indication_handler(self, handler: Callable[[bytes], None]) -> None:
        """Register a callback for FTMS control-point indications."""


@dataclass
class _PendingAck:
    expected_opcode: int
    event: threading.Event
    result_code: int | None = None


class FTMSControl:
    def __init__(
        self,
        transport: FTMSControlTransport,
        *,
        ack_timeout_seconds: float = 2.0,
        write_timeout_seconds: float = 2.0,
    ) -> None:
        self._transport = transport
        self._ack_timeout_seconds = ack_timeout_seconds
        self._write_timeout_seconds = write_timeout_seconds
        self._mode = ControlMode.ERG
        self._command_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending_ack: _PendingAck | None = None
        self._has_control = False

        self._transport.set_indication_handler(self.handle_control_point_indication)

    @property
    def mode(self) -> ControlMode:
        return self._mode

    def set_mode_erg(self) -> None:
        self._mode = ControlMode.ERG

    def set_mode_resistance(self) -> None:
        self._mode = ControlMode.RESISTANCE

    def set_erg_target_watts(self, watts: int) -> FTMSControlAck:
        watts_int = int(watts)
        if watts_int < 0 or watts_int > 32767:
            raise ValueError("ERG target watts must be between 0 and 32767.")
        payload = bytes([_OPCODE_SET_TARGET_POWER]) + watts_int.to_bytes(2, "little", signed=True)
        return self._send_command_with_ack(
            request_opcode=_OPCODE_SET_TARGET_POWER,
            payload=payload,
        )

    def set_resistance_level(self, percent_or_unit: float) -> FTMSControlAck:
        level = float(percent_or_unit)
        if level < 0 or level > 100:
            raise ValueError("Resistance level must be between 0 and 100%.")
        resistance_units = int(round(level * 10.0))
        payload = bytes([_OPCODE_SET_TARGET_RESISTANCE]) + resistance_units.to_bytes(
            2,
            "little",
            signed=True,
        )
        return self._send_command_with_ack(
            request_opcode=_OPCODE_SET_TARGET_RESISTANCE,
            payload=payload,
        )

    def handle_control_point_indication(self, payload: bytes) -> None:
        if len(payload) < 3:
            return
        if payload[0] != _OPCODE_RESPONSE_CODE:
            return

        request_opcode = int(payload[1])
        result_code = int(payload[2])

        with self._pending_lock:
            pending = self._pending_ack
        if pending is None:
            return
        if pending.expected_opcode != request_opcode:
            return

        pending.result_code = result_code
        pending.event.set()

    def _send_command_with_ack(self, *, request_opcode: int, payload: bytes) -> FTMSControlAck:
        with self._command_lock:
            if request_opcode != _OPCODE_REQUEST_CONTROL and not self._has_control:
                try:
                    control_ack = self._send_command_locked(
                        request_opcode=_OPCODE_REQUEST_CONTROL,
                        payload=bytes([_OPCODE_REQUEST_CONTROL]),
                    )
                except FTMSControlError:
                    self._has_control = False
                    raise
                self._has_control = control_ack.result_code == _RESULT_SUCCESS
            try:
                ack = self._send_command_locked(request_opcode=request_opcode, payload=payload)
            except FTMSControlError:
                self._has_control = False
                raise
            if request_opcode == _OPCODE_REQUEST_CONTROL and ack.result_code == _RESULT_SUCCESS:
                self._has_control = True
            return ack

    def _send_command_locked(self, *, request_opcode: int, payload: bytes) -> FTMSControlAck:
        pending = _PendingAck(
            expected_opcode=request_opcode,
            event=threading.Event(),
        )
        with self._pending_lock:
            self._pending_ack = pending

        try:
            write_future = self._transport.write_control_point(payload)
            try:
                write_future.result(timeout=self._write_timeout_seconds)
            except FutureTimeoutError as exc:
                msg = f"Timed out writing FTMS command '{_opcode_label(request_opcode)}'."
                _logger.warning(msg)
                raise FTMSControlAckTimeoutError(msg) from exc
            except Exception as exc:
                msg = f"FTMS write failed for '{_opcode_label(request_opcode)}': {exc}"
                _logger.error(msg)
                raise FTMSControlError(msg) from exc

            if not pending.event.wait(timeout=self._ack_timeout_seconds):
                msg = f"Timed out waiting for FTMS ack for '{_opcode_label(request_opcode)}'."
                _logger.warning(msg)
                raise FTMSControlAckTimeoutError(msg)

            result_code = pending.result_code
            if result_code is None:
                msg = f"FTMS ack missing result code for '{_opcode_label(request_opcode)}'."
                _logger.warning(msg)
                raise FTMSControlAckTimeoutError(msg)
            if result_code != _RESULT_SUCCESS:
                msg = (
                    f"FTMS command '{_opcode_label(request_opcode)}' failed with "
                    f"'{_result_label(result_code)}'."
                )
                _logger.error(msg)
                raise FTMSControlAckError(msg)
            return FTMSControlAck(
                request_opcode=request_opcode,
                result_code=result_code,
            )
        finally:
            with self._pending_lock:
                if self._pending_ack is pending:
                    self._pending_ack = None


class WorkoutEngineFTMSBridge:
    """Applies FTMS trainer commands in response to workout engine snapshots."""

    def __init__(
        self,
        control: FTMSControl,
        *,
        mode: ControlMode = ControlMode.ERG,
        alert_callback: Callable[[str], None] | None = None,
        opentrueup: OpenTrueUpController | None = None,
        opentrueup_status_callback: Callable[[OpenTrueUpStatus], None] | None = None,
        lead_time_seconds: int = 0,
        kj_mode: bool = False,
    ) -> None:
        self._control = control
        self._alert_callback = alert_callback
        self._opentrueup = opentrueup
        self._opentrueup_status_callback = opentrueup_status_callback
        self._lead_time_seconds = lead_time_seconds
        self._kj_mode = kj_mode
        self._last_state: EngineState | None = None
        self._last_interval_index: int | None = None
        self._lead_time_sent_for_interval: int | None = None
        self._current_erg_target_base_watts: int | None = None
        self._last_sent_erg_target_watts: int | None = None
        self._erg_jog_offset_watts: float = 0.0
        if mode is ControlMode.ERG:
            self._control.set_mode_erg()
        else:
            self._control.set_mode_resistance()

    @property
    def mode(self) -> ControlMode:
        return self._control.mode

    def set_mode_erg(self) -> None:
        if self._control.mode is ControlMode.ERG:
            return
        self._control.set_mode_erg()
        self._last_state = None
        self._last_interval_index = None
        self._lead_time_sent_for_interval = None

    def set_mode_resistance(self) -> None:
        if self._control.mode is ControlMode.RESISTANCE:
            return
        self._control.set_mode_resistance()
        self._last_state = None
        self._last_interval_index = None
        self._lead_time_sent_for_interval = None

    def set_erg_jog_offset_watts(self, offset_watts: float) -> None:
        """Apply a manual ERG jog offset and immediately send the updated target."""
        self._erg_jog_offset_watts = offset_watts
        if self._current_erg_target_base_watts is not None:
            jogged = int(round(self._current_erg_target_base_watts + offset_watts))
            self._send_erg_target(self._apply_opentrueup_target(jogged), force=True)

    def on_engine_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> None:
        try:
            self._apply_snapshot(snapshot, workout)
        except FTMSControlError as exc:
            self._report_error("Error communicating with trainer")

    def on_power_sample(
        self,
        *,
        timestamp: datetime | float,
        trainer_power_watts: int | float | None,
        bike_power_watts: int | float | None,
    ) -> None:
        if self._opentrueup is None:
            return

        try:
            status = self._opentrueup.record_power_sample(
                timestamp=timestamp,
                trainer_power_watts=trainer_power_watts,
                bike_power_watts=bike_power_watts,
            )
            if self._opentrueup_status_callback is not None:
                self._opentrueup_status_callback(status)
            if not status.requires_erg_reapply:
                return
            if self._last_state != EngineState.RUNNING:
                return
            if self._control.mode is not ControlMode.ERG:
                return
            if self._current_erg_target_base_watts is None:
                return
            jogged_base = int(round(self._current_erg_target_base_watts + self._erg_jog_offset_watts))
            adjusted_target_watts = self._opentrueup.adjust_erg_target(
                jogged_base,
                apply_offset=True,
            )
            self._send_erg_target(adjusted_target_watts)
        except FTMSControlError as exc:
            self._report_error("Error communicating with trainer")

    def _apply_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> None:
        if workout is None:
            self._last_state = snapshot.state
            self._last_interval_index = snapshot.current_interval_index
            return

        inactive_states = {EngineState.PAUSED, EngineState.STOPPED, EngineState.FINISHED}
        if snapshot.state in inactive_states:
            if self._last_state not in inactive_states:
                self._apply_pause_setpoint()
            self._last_state = snapshot.state
            self._last_interval_index = snapshot.current_interval_index
            return

        if snapshot.state != EngineState.RUNNING:
            self._last_state = snapshot.state
            self._last_interval_index = snapshot.current_interval_index
            return

        interval_changed = snapshot.current_interval_index != self._last_interval_index
        entered_running = self._last_state != EngineState.RUNNING
        if interval_changed or entered_running:
            self._lead_time_sent_for_interval = None
            self._apply_interval_setpoint(snapshot, workout)
        elif (
            snapshot.current_interval_index is not None
            and workout.intervals[snapshot.current_interval_index].is_ramp
        ):
            self._apply_ramp_update(snapshot, workout)
        elif self._should_apply_lead_time(snapshot, workout):
            self._apply_lead_time_setpoint(snapshot, workout)

        self._last_state = snapshot.state
        self._last_interval_index = snapshot.current_interval_index

    def _apply_pause_setpoint(self) -> None:
        if self._control.mode is ControlMode.ERG:
            self._send_erg_target(0, force=True)
            self._current_erg_target_base_watts = 0
        else:
            self._control.set_resistance_level(0)

    def _apply_interval_setpoint(self, snapshot: WorkoutEngineSnapshot, workout: Workout) -> None:
        interval_index = snapshot.current_interval_index
        if interval_index is None:
            return

        interval = workout.intervals[interval_index]
        elapsed_in_interval = snapshot.current_interval_elapsed_seconds or 0.0
        if self._control.mode is ControlMode.ERG:
            self._erg_jog_offset_watts = 0.0
            target_watts = _resolve_interval_target_watts(interval, elapsed_in_interval)
            self._current_erg_target_base_watts = target_watts
            adjusted_target_watts = self._apply_opentrueup_target(target_watts)
            self._send_erg_target(adjusted_target_watts)
        else:
            self._current_erg_target_base_watts = None
            resistance_level = _resolve_interval_percent(interval, elapsed_in_interval)
            self._control.set_resistance_level(resistance_level)

    def _apply_ramp_update(self, snapshot: WorkoutEngineSnapshot, workout: Workout) -> None:
        """Update trainer target for the current tick of an active ramp interval, preserving any jog offset."""
        interval_index = snapshot.current_interval_index
        if interval_index is None:
            return
        interval = workout.intervals[interval_index]
        elapsed_in_interval = snapshot.current_interval_elapsed_seconds or 0.0
        if self._control.mode is ControlMode.ERG:
            target_watts = _resolve_interval_target_watts(interval, elapsed_in_interval)
            self._current_erg_target_base_watts = target_watts
            jogged = int(round(target_watts + self._erg_jog_offset_watts))
            self._send_erg_target(self._apply_opentrueup_target(jogged))
        else:
            self._current_erg_target_base_watts = None
            resistance_level = _resolve_interval_percent(interval, elapsed_in_interval)
            self._control.set_resistance_level(resistance_level)

    def _should_apply_lead_time(
        self, snapshot: WorkoutEngineSnapshot, workout: Workout
    ) -> bool:
        if self._kj_mode or self._lead_time_seconds <= 0:
            return False
        idx = snapshot.current_interval_index
        if idx is None:
            return False
        if self._lead_time_sent_for_interval == idx:
            return False
        if snapshot.current_interval_remaining_seconds is None:
            return False
        if snapshot.current_interval_remaining_seconds > self._lead_time_seconds:
            return False
        if workout.intervals[idx].is_ramp:
            return False
        return idx + 1 < len(workout.intervals)

    def _apply_lead_time_setpoint(
        self, snapshot: WorkoutEngineSnapshot, workout: Workout
    ) -> None:
        next_index = snapshot.current_interval_index + 1  # type: ignore[operator]
        next_interval = workout.intervals[next_index]
        if self._control.mode is ControlMode.ERG:
            target_watts = _resolve_interval_target_watts(next_interval, 0.0)
            self._current_erg_target_base_watts = target_watts
            adjusted_target_watts = self._apply_opentrueup_target(target_watts)
            self._send_erg_target(adjusted_target_watts)
        else:
            self._current_erg_target_base_watts = None
            resistance_level = _resolve_interval_percent(next_interval, 0.0)
            self._control.set_resistance_level(resistance_level)
        self._lead_time_sent_for_interval = snapshot.current_interval_index

    def _report_error(self, message: str) -> None:
        if self._alert_callback is not None:
            self._alert_callback(message)

    def _apply_opentrueup_target(self, base_target_watts: int) -> int:
        if self._opentrueup is None:
            return int(base_target_watts)
        return self._opentrueup.adjust_erg_target(base_target_watts, apply_offset=True)

    def _send_erg_target(self, watts: int, *, force: bool = False) -> None:
        target = int(watts)
        if not force and self._last_sent_erg_target_watts == target:
            return
        self._control.set_erg_target_watts(target)
        self._last_sent_erg_target_watts = target
        if self._opentrueup is not None:
            self._opentrueup.note_applied_erg_target(target)


def _resolve_interval_target_watts(interval: WorkoutInterval, elapsed_in_interval: float) -> int:
    target = _interpolate_interval(
        start_value=float(interval.start_target_watts),
        end_value=float(interval.end_target_watts),
        duration_seconds=interval.duration_seconds,
        elapsed_seconds=elapsed_in_interval,
    )
    return int(round(target))


def _resolve_interval_percent(interval: WorkoutInterval, elapsed_in_interval: float) -> float:
    percent = _interpolate_interval(
        start_value=interval.start_percent_ftp,
        end_value=interval.end_percent_ftp,
        duration_seconds=interval.duration_seconds,
        elapsed_seconds=elapsed_in_interval,
    )
    if percent < 0:
        return 0.0
    return round(percent, 1)


def _interpolate_interval(
    *,
    start_value: float,
    end_value: float,
    duration_seconds: int,
    elapsed_seconds: float,
) -> float:
    if duration_seconds <= 0:
        return end_value
    elapsed_clamped = min(max(float(elapsed_seconds), 0.0), float(duration_seconds))
    ratio = elapsed_clamped / float(duration_seconds)
    return start_value + (end_value - start_value) * ratio


def _opcode_label(opcode: int) -> str:
    return _OPCODE_LABELS.get(opcode, f"opcode_{opcode}")


def _result_label(result_code: int) -> str:
    return _RESULT_LABELS.get(result_code, f"result_{result_code}")
