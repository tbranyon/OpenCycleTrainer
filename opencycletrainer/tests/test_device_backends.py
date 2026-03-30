from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opencycletrainer.devices.ble_backend import BleakDeviceBackend, BleakFTMSControlTransport
from opencycletrainer.devices.decoders.ftms import ResistanceLevelRange
from opencycletrainer.devices.mock_backend import MockDeviceBackend
from opencycletrainer.storage.paired_devices import PairedDeviceStore
from opencycletrainer.devices.types import (
    CPS_SERVICE_UUID,
    FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
    FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID,
    FTMS_SERVICE_UUID,
    HRS_SERVICE_UUID,
    NOTIFICATION_CHARACTERISTIC_UUIDS,
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
    def __init__(self, address: str, disconnected_callback: Any = None) -> None:
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.notifications: dict[str, Any] = {}
        self.writes: list[tuple[str, bytes, bool]] = []
        self.stop_notify_calls: list[str] = []
        self.read_responses: dict[str, bytes] = {}
        self.read_call_count: int = 0

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    def simulate_unexpected_disconnect(self) -> None:
        """Simulate a device dropping the connection without an explicit disconnect call."""
        self.is_connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    async def start_notify(self, uuid: str, handler: Any) -> None:
        self.notifications[uuid] = handler

    async def stop_notify(self, uuid: str) -> None:
        self.stop_notify_calls.append(uuid)

    async def write_gatt_char(self, uuid: str, payload: bytearray, response: bool = True) -> None:
        self.writes.append((uuid, bytes(payload), bool(response)))

    async def read_gatt_char(self, uuid: str) -> bytearray:
        self.read_call_count += 1
        return bytearray(self.read_responses.get(uuid, b""))


def test_bleak_backend_scan_connect_and_subscribe_plumbing(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
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


def test_bleak_ftms_transport_subscribes_and_writes_control_point(monkeypatch, tmp_path):
    # Always pass a tmp_path store — omitting it writes fake device names to the real
    # user data file, which then reappear in the UI on subsequent app launches.
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
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


def test_bleak_backend_shutdown_stops_notifications_before_disconnect(monkeypatch, tmp_path):
    # Always pass a tmp_path store — omitting it writes fake device names to the real
    # user data file, which then reappear in the UI on subsequent app launches.
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    backend.scan().result(timeout=1.0)
    backend.pair_device("AA:BB:CC:02").result(timeout=1.0)
    backend.connect_device("AA:BB:CC:02").result(timeout=1.0)
    backend.subscribe_device_notifications("AA:BB:CC:02", lambda *_: None).result(timeout=1.0)

    client = backend._clients["AA:BB:CC:02"]
    backend.shutdown()

    assert not client.is_connected
    for uuid in NOTIFICATION_CHARACTERISTIC_UUIDS:
        assert uuid in client.stop_notify_calls


def test_bleak_backend_loads_paired_devices_from_store_on_init(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        paired = backend.get_paired_devices()
        assert len(paired) == 1
        assert paired[0].device_id == "AA:BB:CC:01"
        assert paired[0].paired is True
        assert paired[0].connected is False
        assert paired[0].device_type is DeviceType.TRAINER
    finally:
        backend.shutdown()


def test_bleak_backend_pair_saves_to_store(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:02").result(timeout=1.0)

        saved = store.load()
        assert any(d["device_id"] == "AA:BB:CC:02" for d in saved)
    finally:
        backend.shutdown()


def test_bleak_backend_unpair_removes_from_store(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:02").result(timeout=1.0)
        backend.unpair_device("AA:BB:CC:02").result(timeout=1.0)

        saved = store.load()
        assert not any(d["device_id"] == "AA:BB:CC:02" for d in saved)
    finally:
        backend.shutdown()


def test_bleak_backend_scan_marks_persisted_paired_device_as_paired(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        scanned = backend.scan().result(timeout=2.0)
        trainer = next(d for d in scanned if d.device_id == "AA:BB:CC:01")
        assert trainer.paired is True
    finally:
        backend.shutdown()


def test_bleak_backend_scan_auto_reconnects_paired_device(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=2.0)
        assert "AA:BB:CC:01" in backend._clients
        assert backend._clients["AA:BB:CC:01"].is_connected
    finally:
        backend.shutdown()


def test_bleak_backend_scan_does_not_reconnect_already_connected_device(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=2.0)
        first_client = backend._clients.get("AA:BB:CC:01")
        assert first_client is not None

        # Second scan should not replace an already-connected client
        backend.scan().result(timeout=2.0)
        assert backend._clients.get("AA:BB:CC:01") is first_client
    finally:
        backend.shutdown()


def test_bleak_ftms_transport_reads_resistance_level_range(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        client.read_responses[FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID] = bytes([0, 100, 1])

        transport = BleakFTMSControlTransport(backend, "AA:BB:CC:01")
        result = transport.read_resistance_level_range()

        assert result == ResistanceLevelRange(minimum=0.0, maximum=10.0, minimum_increment=0.1)
        assert result.step_count == 100
    finally:
        backend.shutdown()


def test_bleak_ftms_transport_resistance_range_returns_none_on_failure(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        # No read_responses entry → empty bytes → decode raises ValueError → returns None
        transport = BleakFTMSControlTransport(backend, "AA:BB:CC:01")
        result = transport.read_resistance_level_range()

        assert result is None
    finally:
        backend.shutdown()


def test_bleak_ftms_transport_resistance_range_cached_after_first_read(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        client.read_responses[FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID] = bytes([0, 100, 1])

        transport = BleakFTMSControlTransport(backend, "AA:BB:CC:01")
        transport.read_resistance_level_range()
        transport.read_resistance_level_range()

        # Only one actual BLE read should have occurred
        assert client.read_call_count == 1
    finally:
        backend.shutdown()


def test_bleak_backend_disconnect_stops_all_subscribed_characteristics(monkeypatch, tmp_path):
    """All start_notify'd UUIDs — including FTMS control point — must be unsubscribed on disconnect."""
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        backend.subscribe_device_notifications("AA:BB:CC:01", lambda *_: None).result(timeout=1.0)
        backend.subscribe_characteristic(
            "AA:BB:CC:01",
            FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
            lambda _: None,
        ).result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        started_uuids = set(client.notifications.keys())

        backend.disconnect_device("AA:BB:CC:01").result(timeout=1.0)

        assert not client.is_connected
        assert started_uuids.issubset(set(client.stop_notify_calls))
    finally:
        backend.shutdown()


def test_bleak_backend_shutdown_stops_ftms_control_point_subscription(monkeypatch, tmp_path):
    """Shutdown must unsubscribe FTMS control point indications before disconnecting."""
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    backend.scan().result(timeout=1.0)
    backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
    backend.connect_device("AA:BB:CC:01").result(timeout=1.0)
    backend.subscribe_characteristic(
        "AA:BB:CC:01",
        FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
        lambda _: None,
    ).result(timeout=1.0)

    client = backend._clients["AA:BB:CC:01"]
    backend.shutdown()

    assert FTMS_CONTROL_POINT_CHARACTERISTIC_UUID in client.stop_notify_calls
    assert not client.is_connected


def test_bleak_backend_unexpected_disconnect_updates_device_state(monkeypatch, tmp_path):
    """An unexpected BLE drop must clear the client entry and mark the device disconnected."""
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        assert client.is_connected

        client.simulate_unexpected_disconnect()

        assert "AA:BB:CC:01" not in backend._clients
        assert backend._devices["AA:BB:CC:01"].connected is False
    finally:
        backend.shutdown()


def test_bleak_backend_fires_connection_changed_callback_on_unexpected_disconnect(monkeypatch, tmp_path):
    """The device_connection_changed_callback must be called with (device_id, False) on an
    unexpected BLE drop."""
    import time

    store = PairedDeviceStore(path=tmp_path / "paired.json")
    callbacks: list[tuple[str, bool]] = []
    backend = BleakDeviceBackend(
        scan_timeout_seconds=0.1,
        paired_device_store=store,
        device_connection_changed_callback=lambda device_id, connected: callbacks.append((device_id, connected)),
    )
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        client.simulate_unexpected_disconnect()

        # Give asyncio thread a moment to process
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and ("AA:BB:CC:01", False) not in callbacks:
            time.sleep(0.01)

        assert ("AA:BB:CC:01", False) in callbacks
    finally:
        backend.shutdown()


def test_bleak_backend_does_not_auto_reconnect_on_intentional_disconnect(monkeypatch, tmp_path):
    """An explicit disconnect_device call must not trigger the auto-reconnect loop."""
    import time

    store = PairedDeviceStore(path=tmp_path / "paired.json")
    callbacks: list[tuple[str, bool]] = []
    backend = BleakDeviceBackend(
        scan_timeout_seconds=0.1,
        paired_device_store=store,
        reconnect_delay_seconds=0.05,
        device_connection_changed_callback=lambda device_id, connected: callbacks.append((device_id, connected)),
    )
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        backend.disconnect_device("AA:BB:CC:01").result(timeout=1.0)

        # Wait longer than one reconnect delay to verify no reconnect attempt occurs
        time.sleep(0.2)

        reconnected = [c for c in callbacks if c == ("AA:BB:CC:01", True)]
        assert reconnected == []
        assert "AA:BB:CC:01" not in backend._reconnecting_ids
    finally:
        backend.shutdown()


def test_bleak_backend_auto_reconnects_after_unexpected_disconnect_of_paired_device(monkeypatch, tmp_path):
    """A paired device that drops unexpectedly must be automatically reconnected, and the
    callback must be called with (device_id, True) once the reconnect succeeds."""
    import time

    store = PairedDeviceStore(path=tmp_path / "paired.json")
    callbacks: list[tuple[str, bool]] = []
    backend = BleakDeviceBackend(
        scan_timeout_seconds=0.1,
        paired_device_store=store,
        reconnect_delay_seconds=0.05,
        device_connection_changed_callback=lambda device_id, connected: callbacks.append((device_id, connected)),
    )
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        backend.pair_device("AA:BB:CC:01").result(timeout=1.0)
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        client.simulate_unexpected_disconnect()

        # Wait for the reconnect loop to fire and succeed
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and ("AA:BB:CC:01", True) not in callbacks:
            time.sleep(0.02)

        assert ("AA:BB:CC:01", True) in callbacks
        assert "AA:BB:CC:01" in backend._clients
        assert backend._clients["AA:BB:CC:01"].is_connected
        assert backend._devices["AA:BB:CC:01"].connected is True
    finally:
        backend.shutdown()


def test_bleak_backend_no_auto_reconnect_for_unpaired_device(monkeypatch, tmp_path):
    """An unpaired device that disconnects unexpectedly must not trigger auto-reconnect."""
    import time

    store = PairedDeviceStore(path=tmp_path / "paired.json")
    callbacks: list[tuple[str, bool]] = []
    backend = BleakDeviceBackend(
        scan_timeout_seconds=0.1,
        paired_device_store=store,
        reconnect_delay_seconds=0.05,
        device_connection_changed_callback=lambda device_id, connected: callbacks.append((device_id, connected)),
    )
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.scan().result(timeout=1.0)
        # Connect but do NOT pair
        backend.connect_device("AA:BB:CC:01").result(timeout=1.0)

        client = backend._clients["AA:BB:CC:01"]
        client.simulate_unexpected_disconnect()

        time.sleep(0.2)

        reconnected = [c for c in callbacks if c == ("AA:BB:CC:01", True)]
        assert reconnected == []
        assert "AA:BB:CC:01" not in backend._reconnecting_ids
    finally:
        backend.shutdown()
