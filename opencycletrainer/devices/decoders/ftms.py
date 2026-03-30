from __future__ import annotations

import logging
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ResistanceLevelRange:
    """FTMS Supported Resistance Level Range (0x2AD6). Fields in spec units (0.1 resolution)."""

    minimum: float
    maximum: float
    minimum_increment: float

    @property
    def step_count(self) -> int:
        """Number of discrete resistance steps the trainer supports."""
        if self.minimum_increment <= 0:
            return 0
        return round((self.maximum - self.minimum) / self.minimum_increment)


def decode_resistance_level_range(payload: bytes) -> ResistanceLevelRange:
    """Decode FTMS Supported Resistance Level Range (0x2AD6).

    Three UINT8 fields with 0.1 resolution: minimum, maximum, minimum increment.
    """
    if len(payload) < 3:
        raise ValueError(
            f"Resistance Level Range payload too short: expected 3 bytes, got {len(payload)}"
        )
    return ResistanceLevelRange(
        minimum=payload[0] / 10.0,
        maximum=payload[1] / 10.0,
        minimum_increment=payload[2] / 10.0,
    )


# --- Fitness Machine Feature (0x2ACC) ---

_FITNESS_MACHINE_FEATURE_FLAGS: list[tuple[int, str]] = [
    (1 << 0, "Average Speed"),
    (1 << 1, "Cadence"),
    (1 << 2, "Total Distance"),
    (1 << 3, "Inclination"),
    (1 << 4, "Elevation Gain"),
    (1 << 5, "Pace"),
    (1 << 6, "Step Count"),
    (1 << 7, "Resistance Level"),
    (1 << 8, "Stride Count"),
    (1 << 9, "Expended Energy"),
    (1 << 10, "Heart Rate Measurement"),
    (1 << 11, "Metabolic Equivalent"),
    (1 << 12, "Elapsed Time"),
    (1 << 13, "Remaining Time"),
    (1 << 14, "Power Measurement"),
    (1 << 15, "Force on Belt and Power Output"),
    (1 << 16, "User Data Retention"),
]

_TARGET_SETTING_FEATURE_FLAGS: list[tuple[int, str]] = [
    (1 << 0, "Speed Target Setting"),
    (1 << 1, "Inclination Target Setting"),
    (1 << 2, "Resistance Target Setting"),
    (1 << 3, "Power Target Setting"),
    (1 << 4, "Heart Rate Target Setting"),
    (1 << 5, "Targeted Expended Energy"),
    (1 << 6, "Targeted Step Count"),
    (1 << 7, "Targeted Stride Count"),
    (1 << 8, "Targeted Distance"),
    (1 << 9, "Targeted Training Time"),
    (1 << 10, "Targeted Time in Two HR Zones"),
    (1 << 11, "Targeted Time in Three HR Zones"),
    (1 << 12, "Targeted Time in Five HR Zones"),
    (1 << 13, "Indoor Bike Simulation"),
    (1 << 14, "Wheel Circumference Configuration"),
    (1 << 15, "Spin Down Control"),
    (1 << 16, "Targeted Cadence"),
]


@dataclass(frozen=True)
class FTMSFeatures:
    """Decoded FTMS Fitness Machine Feature characteristic (0x2ACC)."""

    fitness_machine_features: int
    target_setting_features: int

    def fitness_feature_names(self) -> list[str]:
        """Return names of supported fitness machine features."""
        return [name for mask, name in _FITNESS_MACHINE_FEATURE_FLAGS if self.fitness_machine_features & mask]

    def target_setting_names(self) -> list[str]:
        """Return names of supported target setting features."""
        return [name for mask, name in _TARGET_SETTING_FEATURE_FLAGS if self.target_setting_features & mask]

    def all_feature_labels(self) -> list[tuple[str, bool]]:
        """Return (name, supported) for every known fitness machine feature bit."""
        return [(name, bool(self.fitness_machine_features & mask)) for mask, name in _FITNESS_MACHINE_FEATURE_FLAGS]

    def all_target_setting_labels(self) -> list[tuple[str, bool]]:
        """Return (name, supported) for every known target setting feature bit."""
        return [(name, bool(self.target_setting_features & mask)) for mask, name in _TARGET_SETTING_FEATURE_FLAGS]


def decode_ftms_fitness_machine_features(payload: bytes) -> FTMSFeatures:
    """Decode FTMS Fitness Machine Feature (0x2ACC).

    8 bytes: 4-byte Fitness Machine Features (uint32 LE) + 4-byte Target Setting Features (uint32 LE).
    """
    if len(payload) < 8:
        raise ValueError(
            f"Fitness Machine Feature payload too short: expected 8 bytes, got {len(payload)}"
        )
    fitness = int.from_bytes(payload[0:4], "little")
    target = int.from_bytes(payload[4:8], "little")
    return FTMSFeatures(fitness_machine_features=fitness, target_setting_features=target)


# --- Supported Power Range (0x2AD8) ---

@dataclass(frozen=True)
class SupportedPowerRange:
    """FTMS Supported Power Range (0x2AD8). Fields in watts."""

    minimum_watts: int
    maximum_watts: int
    minimum_increment_watts: int


def decode_ftms_supported_power_range(payload: bytes) -> SupportedPowerRange:
    """Decode FTMS Supported Power Range (0x2AD8).

    3 fields: Minimum Power (sint16 LE), Maximum Power (sint16 LE), Minimum Increment (uint16 LE).
    """
    if len(payload) < 6:
        raise ValueError(
            f"Supported Power Range payload too short: expected 6 bytes, got {len(payload)}"
        )
    minimum = int.from_bytes(payload[0:2], "little", signed=True)
    maximum = int.from_bytes(payload[2:4], "little", signed=True)
    increment = int.from_bytes(payload[4:6], "little")
    return SupportedPowerRange(
        minimum_watts=minimum,
        maximum_watts=maximum,
        minimum_increment_watts=increment,
    )


# --- Bundled FTMS capabilities ---

@dataclass(frozen=True)
class FTMSCapabilities:
    """Bundled FTMS trainer capabilities read from multiple service characteristics."""

    features: FTMSFeatures | None
    power_range: SupportedPowerRange | None
    resistance_range: ResistanceLevelRange | None
