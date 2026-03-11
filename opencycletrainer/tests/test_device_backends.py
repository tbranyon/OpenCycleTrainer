from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opencycletrainer.devices.ble_backend import BleakDeviceBackend, BleakFTMSControlTransport
from opencycletrainer.devices.mock_backend import MockDeviceBackend
from opencycletrainer.devices.types import (
    CPS_SERVICE_UUID,
    FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
    FTMS_SERVICE_UUID,
    HRS_SERVICE_UUID,
    DeviceInfo,
    DeviceType,
    infer_device_type,
    is_relevant_device,
)


def test_infer_device_type_supports_full_and_short_uuids():
    assert infer_device_type([FTMS_SERVICE_UUID]) is DeviceType.TRAINER
    assert infer_device_type(["1818"]) is DeviceType.POWER_METER
    assert infer_device_type(["180d"]) is DeviceType.HEART_RATE
    assert infer_device_type(["FFFF"]) is None


def test_is_relevant_device_filters_non_target_services():
    assert is_relevant_device([CPS_SERVICE_UUID]) is True
    assert is_relevant_device([HRS_SERVICE_UUID]) is True
    assert is_relevant_device(["FFFF"]) is False


def test_mock_backend_pair_and_connect_flow_uses_manager_contract():
    backend = MockDeviceBackend()

    backend.pair_device("pm-rotor").result(timeout=0.5)
    backend.connect_device("pm-rotor").result(timeout=0.5)
    paired = backend.get_paired_devices()
    rotor = next(device for device in paired if device.device_id == "pm-rotor")
    assert rotor.connected is True

    calibration_result = backend.calibrate_device("pm-rotor").result(timeout=0.5)
    assert calibration_result == 0

    backend.disconnect_device("pm-rotor").result(timeout=0.5)
    backend.unpair_device("pm-rotor").result(timeout=0.5)
    assert all(device.device_id != "pm-rotor" for device in backend.get_paired_devices())


@dataclass
class _FakeBLEDevice:
    name: str
    address: str
    metadata: dict[str, Any]


@dataclass
class _FakeAdvertisement:
    service_uuids: list[str]
    rssi: int


class _FakeScanner:
    @staticmethod
    async def discover(timeout: float, return_adv: bool) -> dict[str, tuple[_FakeBLEDevice, _FakeAdvertisement]]:  # noqa: ARG004
        return {
            "trainer": (
                _FakeBLEDevice(name="Trainer A", address="AA:BB:CC:01", metadata={}),
                _FakeAdvertisement(service_uuids=[FTMS_SERVICE_UUID], rssi=-52),
            ),
            "pm": (
                _FakeBLEDevice(name="Power Meter B", address="AA:BB:CC:02", metadata={}),
                _FakeAdvertisement(service_uuids=["1818"], rssi=-46),
            ),
            "noise": (
                _FakeBLEDevice(name="Noise", address="AA:BB:CC:03", metadata={}),
                _FakeAdvertisement(service_uuids=["FFFF"], rssi=-70),
            ),
        }


class _FakeClient:
    def __init__(self, address: str) -> None:
        self.address = address
        self.is_connected = False
        self.notifications: dict[str, Any] = {}
        self.writes: list[tuple[str, bytes, bool]] = []

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def start_notify(self, uuid: str, handler: Any) -> None:
        self.notifications[uuid] = handler

    async def write_gatt_char(self, uuid: str, payload: bytearray, response: bool = True) -> None:
        self.writes.append((uuid, bytes(payload), bool(response)))


def test_bleak_backend_scan_connect_and_subscribe_plumbing(monkeypatch):
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        scanned = backend.scan().result(timeout=1.0)
        assert [device.name for device in scanned] == ["Power Meter B", "Trainer A"]
        assert all(device.device_type in {DeviceType.TRAINER, DeviceType.POWER_METER} for device in scanned)
        assert scanned[0].address == "AA:BB:CC:02"
        assert scanned[0].rssi == -46

        backend.pair_device("AA:BB:CC:02").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:02").result(timeout=1.0)
        callback_calls: list[tuple[str, str, bytes]] = []
        backend.subscribe_device_notifications(
            "AA:BB:CC:02",
            lambda device_id, characteristic_uuid, payload: callback_calls.append(
                (device_id, characteristic_uuid, payload)
            ),
        ).result(timeout=1.0)

        paired = backend.get_paired_devices()
        assert len(paired) == 1
        assert paired[0].connected is True
        assert paired[0].device_id == "AA:BB:CC:02"
        assert callback_calls == []
    finally:
        backend.shutdown()


def test_bleak_ftms_transport_subscribes_and_writes_control_point(monkeypatch):
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        transport = BleakFTMSControlTransport(backend, "AA:BB:CC:01")
        indications: list[bytes] = []
        transport.set_indication_handler(indications.append)
        transport.write_control_point(b"\x05\xfa\x00").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        assert FTMS_CONTROL_POINT_CHARACTERISTIC_UUID in client.notifications
        assert client.writes == [
            (FTMS_CONTROL_POINT_CHARACTERISTIC_UUID, b"\x05\xfa\x00", True),
        ]

        notify = client.notifications[FTMS_CONTROL_POINT_CHARACTERISTIC_UUID]
        notify(None, bytearray(b"\x80\x05\x01"))
        assert indications == [b"\x80\x05\x01"]
    finally:
        backend.shutdown()
