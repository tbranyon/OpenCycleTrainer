from __future__ import annotations

from dataclasses import dataclass
import logging

from .base import DecodedMetrics

_logger = logging.getLogger(__name__)

_PEDAL_POWER_BALANCE_PRESENT = 1 << 0
_ACCUMULATED_TORQUE_PRESENT = 1 << 2
_WHEEL_REVOLUTION_DATA_PRESENT = 1 << 4
_CRANK_REVOLUTION_DATA_PRESENT = 1 << 5
_EXTREME_FORCE_MAGNITUDES_PRESENT = 1 << 6
_EXTREME_TORQUE_MAGNITUDES_PRESENT = 1 << 7
_EXTREME_ANGLES_PRESENT = 1 << 8
_TOP_DEAD_SPOT_ANGLE_PRESENT = 1 << 9
_BOTTOM_DEAD_SPOT_ANGLE_PRESENT = 1 << 10
_ACCUMULATED_ENERGY_PRESENT = 1 << 11
_EVENT_TIME_ROLLOVER = 65536
_CRANK_REVOLUTION_ROLLOVER = 65536
_MAX_CADENCE_RPM = 300.0
_MAX_POWER_WATTS = 3000


@dataclass
class CyclingPowerDecoderState:
    last_crank_revolutions: int | None = None
    last_crank_event_time: int | None = None


class CyclingPowerDecoder:
    """Decoder for CPS Cycling Power Measurement (0x2A63)."""

    def __init__(self) -> None:
        self._state = CyclingPowerDecoderState()

    def decode(self, payload: bytes) -> DecodedMetrics:
        if len(payload) < 4:
            raise ValueError("CPS payload too short")

        index = 0
        flags = int.from_bytes(payload[index:index + 2], "little")
        index += 2

        power_watts = int.from_bytes(payload[index:index + 2], "little", signed=True)
        index += 2
        if power_watts < 0 or power_watts > _MAX_POWER_WATTS:
            _logger.warning("CPS power out of expected range (%d W)", power_watts)
        cadence_rpm: float | None = None

        index = _skip_optional_field(
            payload,
            index,
            flags,
            _PEDAL_POWER_BALANCE_PRESENT,
            1,
            "pedal power balance",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _ACCUMULATED_TORQUE_PRESENT,
            2,
            "accumulated torque",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _WHEEL_REVOLUTION_DATA_PRESENT,
            6,
            "wheel revolution data",
        )
        if flags & _CRANK_REVOLUTION_DATA_PRESENT:
            if len(payload) < index + 4:
                raise ValueError("CPS crank revolution payload too short")
            crank_revolutions = int.from_bytes(payload[index:index + 2], "little")
            index += 2
            crank_event_time = int.from_bytes(payload[index:index + 2], "little")
            index += 2
            cadence_rpm = self._calculate_cadence(crank_revolutions, crank_event_time)

        index = _skip_optional_field(
            payload,
            index,
            flags,
            _EXTREME_FORCE_MAGNITUDES_PRESENT,
            4,
            "extreme force magnitudes",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _EXTREME_TORQUE_MAGNITUDES_PRESENT,
            4,
            "extreme torque magnitudes",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _EXTREME_ANGLES_PRESENT,
            3,
            "extreme angles",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _TOP_DEAD_SPOT_ANGLE_PRESENT,
            2,
            "top dead spot angle",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _BOTTOM_DEAD_SPOT_ANGLE_PRESENT,
            2,
            "bottom dead spot angle",
        )
        index = _skip_optional_field(
            payload,
            index,
            flags,
            _ACCUMULATED_ENERGY_PRESENT,
            2,
            "accumulated energy",
        )

        return DecodedMetrics(power_watts=power_watts, cadence_rpm=cadence_rpm)

    def _calculate_cadence(self, crank_revolutions: int, crank_event_time: int) -> float | None:
        previous_revs = self._state.last_crank_revolutions
        previous_time = self._state.last_crank_event_time
        self._state.last_crank_revolutions = crank_revolutions
        self._state.last_crank_event_time = crank_event_time

        if previous_revs is None or previous_time is None:
            return None

        delta_revs = (crank_revolutions - previous_revs) % _CRANK_REVOLUTION_ROLLOVER
        delta_time_ticks = (crank_event_time - previous_time) % _EVENT_TIME_ROLLOVER
        if delta_revs <= 0 or delta_time_ticks <= 0:
            return None

        delta_seconds = delta_time_ticks / 1024.0
        if delta_seconds <= 0:
            return None

        cadence = (delta_revs / delta_seconds) * 60.0
        if cadence > _MAX_CADENCE_RPM:
            _logger.warning("CPS cadence out of range (%.1f RPM); discarding", cadence)
            return None
        return cadence


def _skip_optional_field(
    payload: bytes,
    index: int,
    flags: int,
    flag_mask: int,
    field_size: int,
    field_name: str,
) -> int:
    if not flags & flag_mask:
        return index
    if len(payload) < index + field_size:
        raise ValueError(f"CPS {field_name} payload too short")
    return index + field_size
