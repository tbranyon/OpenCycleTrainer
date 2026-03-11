from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class DeviceType(Enum):
    TRAINER = "trainer"
    POWER_METER = "power_meter"
    HEART_RATE = "heart_rate"
    CADENCE = "cadence"
    OTHER = "other"

    @property
    def label(self) -> str:
        labels = {
            DeviceType.TRAINER: "Trainer",
            DeviceType.POWER_METER: "Power Meter",
            DeviceType.HEART_RATE: "Heart Rate",
            DeviceType.CADENCE: "Cadence",
            DeviceType.OTHER: "Other",
        }
        return labels[self]


FTMS_SERVICE_UUID = "00001826-0000-1000-8000-00805f9b34fb"
CPS_SERVICE_UUID = "00001818-0000-1000-8000-00805f9b34fb"
HRS_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
CSC_SERVICE_UUID = "00001816-0000-1000-8000-00805f9b34fb"

CPS_MEASUREMENT_CHARACTERISTIC_UUID = "00002a63-0000-1000-8000-00805f9b34fb"
HRS_MEASUREMENT_CHARACTERISTIC_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
CSC_MEASUREMENT_CHARACTERISTIC_UUID = "00002a5b-0000-1000-8000-00805f9b34fb"
FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID = "00002ad2-0000-1000-8000-00805f9b34fb"

RELEVANT_SERVICE_UUIDS = {
    FTMS_SERVICE_UUID,
    CPS_SERVICE_UUID,
    HRS_SERVICE_UUID,
    CSC_SERVICE_UUID,
}

NOTIFICATION_CHARACTERISTIC_UUIDS = (
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
)

SHORT_UUID_TO_FULL = {
    "1826": FTMS_SERVICE_UUID,
    "1818": CPS_SERVICE_UUID,
    "180d": HRS_SERVICE_UUID,
    "1816": CSC_SERVICE_UUID,
    "2ad2": FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    "2a63": CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    "2a37": HRS_MEASUREMENT_CHARACTERISTIC_UUID,
    "2a5b": CSC_MEASUREMENT_CHARACTERISTIC_UUID,
}


@dataclass(frozen=True)
class DeviceInfo:
    device_id: str
    name: str
    device_type: DeviceType
    address: str | None = None
    rssi: int | None = None
    paired: bool = False
    connected: bool = False
    battery_percent: int | None = None
    supports_calibration: bool = False

    @property
    def connection_status(self) -> str:
        return "Connected" if self.connected else "Disconnected"


def normalize_uuid(uuid: str) -> str:
    normalized = uuid.strip().lower()
    if len(normalized) == 4:
        return SHORT_UUID_TO_FULL.get(normalized, normalized)
    return normalized


def infer_device_type(service_uuids: Iterable[str]) -> DeviceType | None:
    normalized = {normalize_uuid(uuid) for uuid in service_uuids}
    if FTMS_SERVICE_UUID in normalized:
        return DeviceType.TRAINER
    if CPS_SERVICE_UUID in normalized:
        return DeviceType.POWER_METER
    if HRS_SERVICE_UUID in normalized:
        return DeviceType.HEART_RATE
    if CSC_SERVICE_UUID in normalized:
        return DeviceType.CADENCE
    return None


def is_relevant_device(service_uuids: Iterable[str]) -> bool:
    normalized = {normalize_uuid(uuid) for uuid in service_uuids}
    return bool(normalized.intersection(RELEVANT_SERVICE_UUIDS))
