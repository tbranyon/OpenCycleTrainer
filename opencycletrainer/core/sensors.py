from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from opencycletrainer.devices.decoders import (
    CyclingPowerDecoder,
    CyclingSpeedCadenceDecoder,
    decode_heart_rate_measurement,
    decode_indoor_bike_data,
)
from opencycletrainer.devices.decoders.base import DecodedMetrics
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
    normalize_uuid,
)


@dataclass(frozen=True)
class SensorSample:
    timestamp_utc: datetime
    source_characteristic_uuid: str
    power_watts: int | None = None
    cadence_rpm: float | None = None
    heart_rate_bpm: int | None = None
    speed_mps: float | None = None


class SensorStreamDecoder:
    """Decode BLE notification payloads into unified timestamped sensor samples."""

    def __init__(self, wheel_circumference_m: float = 2.105) -> None:
        self._cps_decoder = CyclingPowerDecoder()
        self._csc_decoder = CyclingSpeedCadenceDecoder(wheel_circumference_m=wheel_circumference_m)

    def decode_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        received_at_utc: datetime | None = None,
    ) -> SensorSample | None:
        normalized_uuid = normalize_uuid(characteristic_uuid)
        timestamp_utc = received_at_utc or datetime.now(timezone.utc)
        metrics: DecodedMetrics | None

        if normalized_uuid == CPS_MEASUREMENT_CHARACTERISTIC_UUID:
            metrics = self._cps_decoder.decode(payload)
        elif normalized_uuid == HRS_MEASUREMENT_CHARACTERISTIC_UUID:
            metrics = decode_heart_rate_measurement(payload)
        elif normalized_uuid == CSC_MEASUREMENT_CHARACTERISTIC_UUID:
            metrics = self._csc_decoder.decode(payload)
        elif normalized_uuid == FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID:
            metrics = decode_indoor_bike_data(payload)
        else:
            return None

        return SensorSample(
            timestamp_utc=timestamp_utc,
            source_characteristic_uuid=normalized_uuid,
            power_watts=metrics.power_watts,
            cadence_rpm=metrics.cadence_rpm,
            heart_rate_bpm=metrics.heart_rate_bpm,
            speed_mps=metrics.speed_mps,
        )
