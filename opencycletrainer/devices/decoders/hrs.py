from __future__ import annotations

from .base import DecodedMetrics

_HEART_RATE_16BIT_FLAG = 1 << 0


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
