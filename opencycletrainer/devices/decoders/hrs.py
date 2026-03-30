from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .base import DecodedMetrics

_HEART_RATE_16BIT_FLAG = 1 << 0


class HRSBodySensorLocation(Enum):
    """HRS Body Sensor Location (0x2A38) values."""

    OTHER = 0
    CHEST = 1
    WRIST = 2
    FINGER = 3
    HAND = 4
    EAR_LOBE = 5
    FOOT = 6

    @property
    def label(self) -> str:
        labels = {
            HRSBodySensorLocation.OTHER: "Other",
            HRSBodySensorLocation.CHEST: "Chest",
            HRSBodySensorLocation.WRIST: "Wrist",
            HRSBodySensorLocation.FINGER: "Finger",
            HRSBodySensorLocation.HAND: "Hand",
            HRSBodySensorLocation.EAR_LOBE: "Ear Lobe",
            HRSBodySensorLocation.FOOT: "Foot",
        }
        return labels[self]


def decode_hrs_body_sensor_location(payload: bytes) -> HRSBodySensorLocation:
    """Decode HRS Body Sensor Location (0x2A38). Single-byte value."""
    if len(payload) < 1:
        raise ValueError("Body Sensor Location payload too short")
    value = payload[0]
    try:
        return HRSBodySensorLocation(value)
    except ValueError:
        return HRSBodySensorLocation.OTHER


@dataclass(frozen=True)
class HRSCapabilities:
    """Bundled HRS heart rate monitor capabilities read from service characteristics."""

    body_sensor_location: HRSBodySensorLocation | None


def decode_heart_rate_measurement(payload: bytes) -> DecodedMetrics:
    """Decoder for HRS Heart Rate Measurement (0x2A37)."""
    if len(payload) < 2:
        raise ValueError("HRS payload too short")

    flags = payload[0]
    index = 1
    if flags & _HEART_RATE_16BIT_FLAG:
        if len(payload) < index + 2:
            raise ValueError("HRS payload missing 16-bit heart rate field")
        heart_rate_bpm = int.from_bytes(payload[index:index + 2], "little")
    else:
        heart_rate_bpm = payload[index]

    return DecodedMetrics(heart_rate_bpm=heart_rate_bpm)
