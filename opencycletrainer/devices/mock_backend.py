from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
import struct
import threading

from .decoders.ftms import ResistanceLevelRange
from .device_manager import DeviceManager, NotificationCallback, completed_future
from .types import DeviceInfo, DeviceType

_SPIN_DOWN_CONTROL_OPCODE = 0x13
_SPIN_DOWN_START = 0x01
_RESPONSE_CODE_OPCODE = 0x80
_RESULT_SUCCESS = 0x01
_SPIN_DOWN_STATUS_OPCODE = 0x14
_SPIN_DOWN_STATUS_STOP_PEDALING = 0x04
_SPIN_DOWN_STATUS_SUCCESS = 0x02

RELEVANT_DEVICE_TYPES = {
    DeviceType.TRAINER,
    DeviceType.POWER_METER,
    DeviceType.HEART_RATE,
    DeviceType.CADENCE,
}

MockDevice = DeviceInfo


class MockFTMSControlTransport:
    """In-memory FTMS control transport for spin-down without hardware.

    Auto-acks every control-point write. On a Spin Down Control (0x13) Start it returns a
    sample target speed band and, when ``auto_sequence`` is set, schedules Stop Pedaling
    then Success status notifications to walk a real trainer's flow. Tests can disable the
    timers and drive the sequence manually via :meth:`emit_spin_down_status`.
    """

    def __init__(
        self,
        *,
        target_low_raw: int = 3000,
        target_high_raw: int = 3500,
        auto_sequence: bool = True,
        step_delay_seconds: float = 0.8,
    ) -> None:
        self._target_low_raw = target_low_raw
        self._target_high_raw = target_high_raw
        self._auto_sequence = auto_sequence
        self._step_delay_seconds = step_delay_seconds
        self._indication_handler: Callable[[bytes], None] = lambda _: None
        self._status_handler: Callable[[bytes], None] = lambda _: None
        self._timers: list[threading.Timer] = []

    def write_control_point(self, payload: bytes) -> Future[None]:
        future: Future[None] = Future()
        future.set_result(None)
        opcode = payload[0]
        parameters = b""
        if (
            opcode == _SPIN_DOWN_CONTROL_OPCODE
            and len(payload) > 1
            and payload[1] == _SPIN_DOWN_START
        ):
            parameters = struct.pack("<HH", self._target_low_raw, self._target_high_raw)
            if self._auto_sequence:
                self._schedule_spin_down_sequence()
        self._indication_handler(
            bytes([_RESPONSE_CODE_OPCODE, opcode, _RESULT_SUCCESS]) + parameters
        )
        return future

    def set_indication_handler(self, handler: Callable[[bytes], None]) -> None:
        self._indication_handler = handler

    def subscribe_status(self, handler: Callable[[bytes], None]) -> None:
        self._status_handler = handler

    def read_resistance_level_range(self) -> ResistanceLevelRange | None:
        return None

    def emit_spin_down_status(self, status_value: int) -> None:
        self._status_handler(bytes([_SPIN_DOWN_STATUS_OPCODE, status_value]))

    def _schedule_spin_down_sequence(self) -> None:
        delay = self._step_delay_seconds
        for offset, status in (
            (delay, _SPIN_DOWN_STATUS_STOP_PEDALING),
            (delay * 2, _SPIN_DOWN_STATUS_SUCCESS),
        ):
            timer = threading.Timer(offset, self.emit_spin_down_status, args=(status,))
            timer.daemon = True
            timer.start()
            self._timers.append(timer)


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

    def autoconnect_paired_devices(self) -> Future[list[str]]:
        with self._lock:
            to_connect = [
                device.device_id
                for device in self._devices.values()
                if device.paired
                and not device.connected
                and device.device_type in RELEVANT_DEVICE_TYPES
            ]
            for device_id in to_connect:
                self._devices[device_id] = replace(self._devices[device_id], connected=True)
        return completed_future(to_connect)

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
