from __future__ import annotations

import logging

from .base import DecodedMetrics

_logger = logging.getLogger(__name__)

_MAX_CADENCE_RPM = 300.0
_MAX_POWER_WATTS = 3000
_MAX_SPEED_MPS = 33.3
_MAX_HEART_RATE_BPM = 250
_AVERAGE_SPEED_PRESENT = 1 << 1
_INSTANTANEOUS_CADENCE_PRESENT = 1 << 2
_AVERAGE_CADENCE_PRESENT = 1 << 3
_TOTAL_DISTANCE_PRESENT = 1 << 4
_RESISTANCE_LEVEL_PRESENT = 1 << 5
_INSTANTANEOUS_POWER_PRESENT = 1 << 6
_AVERAGE_POWER_PRESENT = 1 << 7
_EXPENDED_ENERGY_PRESENT = 1 << 8
_HEART_RATE_PRESENT = 1 << 9
_METABOLIC_EQUIVALENT_PRESENT = 1 << 10
_ELAPSED_TIME_PRESENT = 1 << 11
_REMAINING_TIME_PRESENT = 1 << 12


def decode_indoor_bike_data(payload: bytes) -> DecodedMetrics:
    """Decoder for FTMS Indoor Bike Data (0x2AD2)."""
    if len(payload) < 4:
        raise ValueError("FTMS Indoor Bike Data payload too short")

    index = 0
    flags = int.from_bytes(payload[index:index + 2], "little")
    index += 2

    speed_raw = int.from_bytes(payload[index:index + 2], "little")
    index += 2
    speed_mps = (speed_raw / 100.0) / 3.6
    if speed_mps > _MAX_SPEED_MPS:
        _logger.warning("FTMS speed out of expected range (%.2f m/s)", speed_mps)

    cadence_rpm: float | None = None
    power_watts: int | None = None
    heart_rate_bpm: int | None = None

    if flags & _AVERAGE_SPEED_PRESENT:
        index += 2

    if flags & _INSTANTANEOUS_CADENCE_PRESENT:
        cadence_raw = int.from_bytes(payload[index:index + 2], "little")
        cadence_rpm = cadence_raw / 2.0
        if cadence_rpm > _MAX_CADENCE_RPM:
            _logger.warning("FTMS cadence out of range (%.1f RPM); discarding", cadence_rpm)
            cadence_rpm = None
        index += 2

    if flags & _AVERAGE_CADENCE_PRESENT:
        index += 2

    if flags & _TOTAL_DISTANCE_PRESENT:
        index += 3

    if flags & _RESISTANCE_LEVEL_PRESENT:
        index += 2

    if flags & _INSTANTANEOUS_POWER_PRESENT:
        power_watts = int.from_bytes(payload[index:index + 2], "little", signed=True)
        index += 2
        if power_watts < 0 or power_watts > _MAX_POWER_WATTS:
            _logger.warning("FTMS power out of expected range (%d W)", power_watts)

    if flags & _AVERAGE_POWER_PRESENT:
        index += 2

    if flags & _EXPENDED_ENERGY_PRESENT:
        index += 5

    if flags & _HEART_RATE_PRESENT:
        heart_rate_bpm = payload[index]
        index += 1
        if heart_rate_bpm > _MAX_HEART_RATE_BPM:
            _logger.warning("FTMS heart rate out of expected range (%d bpm)", heart_rate_bpm)

    if flags & _METABOLIC_EQUIVALENT_PRESENT:
        index += 1

    if flags & _ELAPSED_TIME_PRESENT:
        index += 2

    if flags & _REMAINING_TIME_PRESENT:
        index += 2

    if index > len(payload):
        raise ValueError("FTMS Indoor Bike Data payload shorter than indicated by flags")

    return DecodedMetrics(
        power_watts=power_watts,
        cadence_rpm=cadence_rpm,
        heart_rate_bpm=heart_rate_bpm,
        speed_mps=speed_mps,
    )
