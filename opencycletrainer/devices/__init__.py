"""Device abstractions and backends."""

from .ble_backend import BleakDeviceBackend
from .decoders import (
    CyclingPowerDecoder,
    CyclingSpeedCadenceDecoder,
    DecodedMetrics,
    decode_heart_rate_measurement,
    decode_indoor_bike_data,
)
from .device_manager import DeviceManager, NotificationCallback
from .mock_backend import MockDeviceBackend
from .types import DeviceInfo, DeviceType, infer_device_type, is_relevant_device

__all__ = [
    "BleakDeviceBackend",
    "CyclingPowerDecoder",
    "CyclingSpeedCadenceDecoder",
    "DecodedMetrics",
    "DeviceInfo",
    "DeviceManager",
    "DeviceType",
    "MockDeviceBackend",
    "NotificationCallback",
    "decode_heart_rate_measurement",
    "decode_indoor_bike_data",
    "infer_device_type",
    "is_relevant_device",
]
