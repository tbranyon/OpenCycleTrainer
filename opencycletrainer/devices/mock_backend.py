from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
import threading

from .device_manager import DeviceManager, NotificationCallback, completed_future
from .types import DeviceInfo, DeviceType

RELEVANT_DEVICE_TYPES = {
    DeviceType.TRAINER,
    DeviceType.POWER_METER,
    DeviceType.HEART_RATE,
    DeviceType.CADENCE,
}

MockDevice = DeviceInfo


class MockDeviceBackend(DeviceManager):
    """In-memory backend used for UI development and tests."""

    def __init__(self, devices: list[MockDevice] | None = None) -> None:
        self._lock = threading.Lock()
        initial_devices = devices if devices is not None else self._default_devices()
        self._devices: dict[str, MockDevice] = {device.device_id: device for device in initial_devices}

    def scan(self) -> Future[list[DeviceInfo]]:
        with self._lock:
            relevant = [
                device
                for device in self._devices.values()
                if device.device_type in RELEVANT_DEVICE_TYPES
            ]
            ordered = sorted(relevant, key=lambda device: device.name.lower())
        return completed_future(ordered)

    def get_paired_devices(self) -> list[DeviceInfo]:
        with self._lock:
            paired = [
                device
                for device in self._devices.values()
                if device.paired and device.device_type in RELEVANT_DEVICE_TYPES
            ]
            return sorted(paired, key=lambda device: device.name.lower())

    def get_available_devices(self) -> list[DeviceInfo]:
        with self._lock:
            available = [
                device
                for device in self._devices.values()
                if not device.paired and device.device_type in RELEVANT_DEVICE_TYPES
            ]
            return sorted(available, key=lambda device: device.name.lower())

    def pair_device(self, device_id: str) -> Future[None]:
        with self._lock:
            device = self._get_device(device_id)
            self._devices[device_id] = replace(device, paired=True)
        return completed_future(None)

    def unpair_device(self, device_id: str) -> Future[None]:
        with self._lock:
            device = self._get_device(device_id)
            self._devices[device_id] = replace(device, paired=False, connected=False)
        return completed_future(None)

    def connect_device(self, device_id: str) -> Future[None]:
        with self._lock:
            device = self._get_device(device_id)
            self._devices[device_id] = replace(device, connected=True)
        return completed_future(None)

    def disconnect_device(self, device_id: str) -> Future[None]:
        with self._lock:
            device = self._get_device(device_id)
            self._devices[device_id] = replace(device, connected=False)
        return completed_future(None)

    def calibrate_device(self, device_id: str) -> Future[int | None]:
        with self._lock:
            device = self._get_device(device_id)
            supported = (
                device.device_type is DeviceType.POWER_METER and device.supports_calibration
            )
        if not supported:
            f: Future[int | None] = Future()
            f.set_exception(RuntimeError(f"Device {device_id} does not support calibration"))
            return f
        return completed_future(0)

    def subscribe_device_notifications(
        self,
        device_id: str,
        callback: NotificationCallback,  # noqa: ARG002
    ) -> Future[None]:
        self._get_device(device_id)
        return completed_future(None)

    def read_gatt_characteristic(self, device_id: str, characteristic_uuid: str) -> Future[bytes]:  # noqa: ARG002
        """Return empty bytes; override in subclasses to return test data."""
        self._get_device(device_id)
        return completed_future(bytes())

    def _get_device(self, device_id: str) -> MockDevice:
        if device_id not in self._devices:
            raise KeyError(f"Unknown device id: {device_id}")
        return self._devices[device_id]

    @staticmethod
    def _default_devices() -> list[MockDevice]:
        return [
            MockDevice(
                device_id="trainer-kickr",
                name="Wahoo KICKR",
                device_type=DeviceType.TRAINER,
                address="C0:FF:EE:00:00:01",
                rssi=-56,
                paired=True,
                connected=True,
                battery_percent=None,
            ),
            MockDevice(
                device_id="pm-assioma",
                name="Favero Assioma",
                device_type=DeviceType.POWER_METER,
                address="C0:FF:EE:00:00:02",
                rssi=-48,
                paired=True,
                connected=True,
                battery_percent=84,
                supports_calibration=True,
            ),
            MockDevice(
                device_id="hr-strap",
                name="Polar H10",
                device_type=DeviceType.HEART_RATE,
                address="C0:FF:EE:00:00:03",
                rssi=-60,
                paired=True,
                connected=False,
                battery_percent=62,
            ),
            MockDevice(
                device_id="cadence-1",
                name="Magene CAD",
                device_type=DeviceType.CADENCE,
                address="C0:FF:EE:00:00:04",
                rssi=-64,
                paired=False,
                connected=False,
                battery_percent=79,
            ),
            MockDevice(
                device_id="pm-rotor",
                name="Rotor INspider",
                device_type=DeviceType.POWER_METER,
                address="C0:FF:EE:00:00:05",
                rssi=-54,
                paired=False,
                connected=False,
                battery_percent=71,
                supports_calibration=True,
            ),
            MockDevice(
                device_id="watch-noise",
                name="Generic Watch",
                device_type=DeviceType.OTHER,
                address="C0:FF:EE:00:00:06",
                rssi=-67,
                paired=False,
                connected=False,
                battery_percent=90,
            ),
        ]
