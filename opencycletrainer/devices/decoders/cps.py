from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging

from .base import DecodedMetrics

_logger = logging.getLogger(__name__)

# --- CPS Capability types (Cycling Power Feature 0x2A65 & Sensor Location 0x2A5D) ---

_CPS_FEATURE_PEDAL_POWER_BALANCE = 1 << 0
_CPS_FEATURE_ACCUMULATED_TORQUE = 1 << 1
_CPS_FEATURE_WHEEL_REVOLUTION_DATA = 1 << 2
_CPS_FEATURE_CRANK_REVOLUTION_DATA = 1 << 3
_CPS_FEATURE_EXTREME_MAGNITUDES = 1 << 4
_CPS_FEATURE_EXTREME_ANGLES = 1 << 5
_CPS_FEATURE_TOP_BOTTOM_DEAD_SPOT_ANGLES = 1 << 6
_CPS_FEATURE_ACCUMULATED_ENERGY = 1 << 7
_CPS_FEATURE_OFFSET_COMPENSATION_INDICATOR = 1 << 8
_CPS_FEATURE_OFFSET_COMPENSATION = 1 << 9
_CPS_FEATURE_CONTENT_MASKING = 1 << 10
_CPS_FEATURE_MULTIPLE_SENSOR_LOCATIONS = 1 << 11
_CPS_FEATURE_CRANK_LENGTH_ADJUSTMENT = 1 << 12
_CPS_FEATURE_CHAIN_LENGTH_ADJUSTMENT = 1 << 13
_CPS_FEATURE_CHAIN_WEIGHT_ADJUSTMENT = 1 << 14
_CPS_FEATURE_SPAN_LENGTH_ADJUSTMENT = 1 << 15
_CPS_FEATURE_MEASUREMENT_CONTEXT = 1 << 16
_CPS_FEATURE_INSTANTANEOUS_MEASUREMENT_DIRECTION = 1 << 17
_CPS_FEATURE_FACTORY_CALIBRATION_DATE = 1 << 18
_CPS_FEATURE_ENHANCED_OFFSET_COMPENSATION = 1 << 19


class CPSSensorLocation(Enum):
    """CPS/BT SIG Sensor Location (0x2A5D) values relevant to cycling power meters."""

    OTHER = 0
    TOP_OF_SHOE = 1
    IN_SHOE = 2
    HIP = 3
    FRONT_WHEEL = 4
    LEFT_CRANK = 5
    RIGHT_CRANK = 6
    LEFT_PEDAL = 7
    RIGHT_PEDAL = 8
    FRONT_HUB = 9
    REAR_DROPOUT = 10
    CHAINSTAY = 11
    REAR_WHEEL = 12
    REAR_HUB = 13
    CHEST = 14
    SPIDER = 15
    CHAIN_RING = 16

    @property
    def label(self) -> str:
        labels = {
            CPSSensorLocation.OTHER: "Other",
            CPSSensorLocation.TOP_OF_SHOE: "Top of Shoe",
            CPSSensorLocation.IN_SHOE: "In Shoe",
            CPSSensorLocation.HIP: "Hip",
            CPSSensorLocation.FRONT_WHEEL: "Front Wheel",
            CPSSensorLocation.LEFT_CRANK: "Left Crank",
            CPSSensorLocation.RIGHT_CRANK: "Right Crank",
            CPSSensorLocation.LEFT_PEDAL: "Left Pedal",
            CPSSensorLocation.RIGHT_PEDAL: "Right Pedal",
            CPSSensorLocation.FRONT_HUB: "Front Hub",
            CPSSensorLocation.REAR_DROPOUT: "Rear Dropout",
            CPSSensorLocation.CHAINSTAY: "Chainstay",
            CPSSensorLocation.REAR_WHEEL: "Rear Wheel",
            CPSSensorLocation.REAR_HUB: "Rear Hub",
            CPSSensorLocation.CHEST: "Chest",
            CPSSensorLocation.SPIDER: "Spider",
            CPSSensorLocation.CHAIN_RING: "Chain Ring",
        }
        return labels[self]


@dataclass(frozen=True)
class CPSFeatures:
    """Decoded CPS Cycling Power Feature (0x2A65) flags."""

    feature_flags: int

    def all_feature_labels(self) -> list[tuple[str, bool]]:
        """Return (label, supported) pairs for each feature bit."""
        flags = self.feature_flags
        return [
            ("Pedal Power Balance", bool(flags & _CPS_FEATURE_PEDAL_POWER_BALANCE)),
            ("Accumulated Torque", bool(flags & _CPS_FEATURE_ACCUMULATED_TORQUE)),
            ("Wheel Revolution Data", bool(flags & _CPS_FEATURE_WHEEL_REVOLUTION_DATA)),
            ("Crank Revolution Data", bool(flags & _CPS_FEATURE_CRANK_REVOLUTION_DATA)),
            ("Extreme Magnitudes", bool(flags & _CPS_FEATURE_EXTREME_MAGNITUDES)),
            ("Extreme Angles", bool(flags & _CPS_FEATURE_EXTREME_ANGLES)),
            ("Top/Bottom Dead Spot Angles", bool(flags & _CPS_FEATURE_TOP_BOTTOM_DEAD_SPOT_ANGLES)),
            ("Accumulated Energy", bool(flags & _CPS_FEATURE_ACCUMULATED_ENERGY)),
            ("Offset Compensation Indicator", bool(flags & _CPS_FEATURE_OFFSET_COMPENSATION_INDICATOR)),
            ("Offset Compensation", bool(flags & _CPS_FEATURE_OFFSET_COMPENSATION)),
            ("Content Masking", bool(flags & _CPS_FEATURE_CONTENT_MASKING)),
            ("Multiple Sensor Locations", bool(flags & _CPS_FEATURE_MULTIPLE_SENSOR_LOCATIONS)),
            ("Crank Length Adjustment", bool(flags & _CPS_FEATURE_CRANK_LENGTH_ADJUSTMENT)),
            ("Chain Length Adjustment", bool(flags & _CPS_FEATURE_CHAIN_LENGTH_ADJUSTMENT)),
            ("Chain Weight Adjustment", bool(flags & _CPS_FEATURE_CHAIN_WEIGHT_ADJUSTMENT)),
            ("Span Length Adjustment", bool(flags & _CPS_FEATURE_SPAN_LENGTH_ADJUSTMENT)),
            ("Instantaneous Measurement Direction", bool(flags & _CPS_FEATURE_INSTANTANEOUS_MEASUREMENT_DIRECTION)),
            ("Factory Calibration Date", bool(flags & _CPS_FEATURE_FACTORY_CALIBRATION_DATE)),
            ("Enhanced Offset Compensation", bool(flags & _CPS_FEATURE_ENHANCED_OFFSET_COMPENSATION)),
        ]

    @property
    def measurement_context(self) -> str:
        """Returns 'Torque-based' or 'Force-based' per bit 16 of the feature flags."""
        return "Torque-based" if self.feature_flags & _CPS_FEATURE_MEASUREMENT_CONTEXT else "Force-based"


@dataclass(frozen=True)
class CPSCapabilities:
    """Bundled CPS power meter capabilities read from service characteristics."""

    features: CPSFeatures | None
    sensor_location: CPSSensorLocation | None


def decode_cps_features(payload: bytes) -> CPSFeatures:
    """Decode CPS Cycling Power Feature (0x2A65). Four-byte little-endian bitmask."""
    if len(payload) < 4:
        raise ValueError("CPS Feature payload too short")
    flags = int.from_bytes(payload[0:4], "little")
    return CPSFeatures(feature_flags=flags)


def decode_cps_sensor_location(payload: bytes) -> CPSSensorLocation:
    """Decode CPS/BT SIG Sensor Location (0x2A5D). Single-byte enum."""
    if len(payload) < 1:
        raise ValueError("CPS Sensor Location payload too short")
    value = payload[0]
    try:
        return CPSSensorLocation(value)
    except ValueError:
        return CPSSensorLocation.OTHER


# --- CPS Measurement decoder (0x2A63) ---

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
        pedal_balance_left_pct: float | None = None

        if flags & _PEDAL_POWER_BALANCE_PRESENT:
            if len(payload) < index + 1:
                raise ValueError("CPS pedal power balance payload too short")
            # BLE CPS spec: value in 0.5% units, represents left-side contribution
            pedal_balance_left_pct = payload[index] * 0.5
            index += 1
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
        accumulated_energy_kj: float | None = None
        if flags & _ACCUMULATED_ENERGY_PRESENT:
            if len(payload) < index + 2:
                raise ValueError("CPS accumulated energy payload too short")
            accumulated_energy_kj = float(int.from_bytes(payload[index:index + 2], "little"))
            index += 2

        return DecodedMetrics(
            power_watts=power_watts,
            cadence_rpm=cadence_rpm,
            accumulated_energy_kj=accumulated_energy_kj,
            pedal_balance_left_pct=pedal_balance_left_pct,
        )

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
