from __future__ import annotations

from dataclasses import dataclass

from .base import DecodedMetrics

_WHEEL_REVOLUTION_DATA_PRESENT = 1 << 0
_CRANK_REVOLUTION_DATA_PRESENT = 1 << 1
_EVENT_TIME_ROLLOVER = 65536
_WHEEL_REVOLUTION_ROLLOVER = 2 ** 32


@dataclass
class CyclingSpeedCadenceDecoderState:
    last_wheel_revolutions: int | None = None
    last_wheel_event_time: int | None = None
    last_crank_revolutions: int | None = None
    last_crank_event_time: int | None = None


class CyclingSpeedCadenceDecoder:
    """Decoder for CSC Measurement (0x2A5B)."""

    def __init__(self, wheel_circumference_m: float = 2.105) -> None:
        self._wheel_circumference_m = wheel_circumference_m
        self._state = CyclingSpeedCadenceDecoderState()

    def decode(self, payload: bytes) -> DecodedMetrics:
        if len(payload) < 1:
            raise ValueError("CSC payload too short")

        flags = payload[0]
        index = 1
        speed_mps: float | None = None
        cadence_rpm: float | None = None

        if flags & _WHEEL_REVOLUTION_DATA_PRESENT:
            if len(payload) < index + 6:
                raise ValueError("CSC payload missing wheel data")
            wheel_revolutions = int.from_bytes(payload[index:index + 4], "little")
            index += 4
            wheel_event_time = int.from_bytes(payload[index:index + 2], "little")
            index += 2
            speed_mps = self._calculate_speed(wheel_revolutions, wheel_event_time)

        if flags & _CRANK_REVOLUTION_DATA_PRESENT:
            if len(payload) < index + 4:
                raise ValueError("CSC payload missing crank data")
            crank_revolutions = int.from_bytes(payload[index:index + 2], "little")
            index += 2
            crank_event_time = int.from_bytes(payload[index:index + 2], "little")
            cadence_rpm = self._calculate_cadence(crank_revolutions, crank_event_time)

        return DecodedMetrics(speed_mps=speed_mps, cadence_rpm=cadence_rpm)

    def _calculate_speed(self, wheel_revolutions: int, wheel_event_time: int) -> float | None:
        previous_revs = self._state.last_wheel_revolutions
        previous_time = self._state.last_wheel_event_time
        self._state.last_wheel_revolutions = wheel_revolutions
        self._state.last_wheel_event_time = wheel_event_time

        if previous_revs is None or previous_time is None:
            return None

        delta_revs = (wheel_revolutions - previous_revs) % _WHEEL_REVOLUTION_ROLLOVER
        delta_time_ticks = (wheel_event_time - previous_time) % _EVENT_TIME_ROLLOVER
        if delta_revs <= 0 or delta_time_ticks <= 0:
            return None

        delta_seconds = delta_time_ticks / 1024.0
        if delta_seconds <= 0:
            return None

        return (delta_revs * self._wheel_circumference_m) / delta_seconds

    def _calculate_cadence(self, crank_revolutions: int, crank_event_time: int) -> float | None:
        previous_revs = self._state.last_crank_revolutions
        previous_time = self._state.last_crank_event_time
        self._state.last_crank_revolutions = crank_revolutions
        self._state.last_crank_event_time = crank_event_time

        if previous_revs is None or previous_time is None:
            return None

        delta_revs = crank_revolutions - previous_revs
        delta_time_ticks = (crank_event_time - previous_time) % _EVENT_TIME_ROLLOVER
        if delta_revs <= 0 or delta_time_ticks <= 0:
            return None

        delta_seconds = delta_time_ticks / 1024.0
        if delta_seconds <= 0:
            return None

        return (delta_revs / delta_seconds) * 60.0
