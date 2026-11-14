from __future__ import annotations

import os
import time

from PySide6.QtWidgets import QApplication

from opencycletrainer.devices.ble_backend import BleakDeviceBackend
from opencycletrainer.devices.mock_backend import MockDevice, MockDeviceBackend
from opencycletrainer.devices.types import DeviceType
from opencycletrainer.storage.paired_devices import PairedDeviceStore
from opencycletrainer.ui.devices_screen import DevicesScreen
from .test_device_backends import (
    _FakeAdvertisement,
    _FakeBLEDevice,
    _FakeClient,
    _FakeScanner,
)


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# --- Backend: autoconnect_paired_devices ---


def test_mock_backend_autoconnect_connects_only_disconnected_paired_devices():
    backend = MockDeviceBackend(
        devices=[
            MockDevice(
                device_id="t1",
                name="Trainer",
                device_type=DeviceType.TRAINER,
                paired=True,
                connected=False,
            ),
            MockDevice(
                device_id="hr1",
                name="HRM",
                device_type=DeviceType.HEART_RATE,
                paired=True,
                connected=True,
            ),
            MockDevice(
                device_id="a1",
                name="Available",
                device_type=DeviceType.POWER_METER,
                paired=False,
                connected=False,
            ),
        ],
    )

    connected = backend.autoconnect_paired_devices().result(timeout=0.5)

    assert connected == ["t1"]
    paired = {d.device_id: d for d in backend.get_paired_devices()}
    assert paired["t1"].connected is True


def test_bleak_backend_autoconnect_connects_stored_paired_devices(monkeypatch, tmp_path):
    """Autoconnect must reach paired devices loaded from the store, with no manual scan first."""
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        connected = backend.autoconnect_paired_devices().result(timeout=2.0)
        assert connected == ["AA:BB:CC:01"]
        assert "AA:BB:CC:01" in backend._clients
        assert backend._clients["AA:BB:CC:01"].is_connected
    finally:
        backend.shutdown()


def test_bleak_backend_autoconnect_reaches_device_only_reachable_after_discovery(monkeypatch, tmp_path):
    """On Linux/macOS a paired device may be unreachable by address until it has been
    discovered. Autoconnect discovers first, so it still connects."""
    from opencycletrainer.devices.types import FTMS_SERVICE_UUID

    discovered: set[str] = set()

    class _CacheGatedClient(_FakeClient):
        async def connect(self, **kwargs) -> None:
            if self.address not in discovered:
                raise RuntimeError(f"Device with address {self.address} was not found")
            self.is_connected = True

    class _CachePopulatingScanner:
        def __init__(self, detection_callback=None, **kwargs) -> None:
            self._callback = detection_callback

        async def start(self) -> None:
            discovered.add("AA:BB:CC:01")
            self._callback(
                _FakeBLEDevice(name="Trainer A", address="AA:BB:CC:01", metadata={}),
                _FakeAdvertisement(service_uuids=[FTMS_SERVICE_UUID], rssi=-52),
            )

        async def stop(self) -> None:
            pass

    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_CacheGatedClient, _CachePopulatingScanner)),
    )

    try:
        connected = backend.autoconnect_paired_devices().result(timeout=2.0)
        assert connected == ["AA:BB:CC:01"]
        assert backend._clients["AA:BB:CC:01"].is_connected
    finally:
        backend.shutdown()


def test_bleak_backend_autoconnect_skips_already_connected_devices(monkeypatch, tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"}])

    backend = BleakDeviceBackend(scan_timeout_seconds=0.1, paired_device_store=store)
    monkeypatch.setattr(
        BleakDeviceBackend,
        "_load_bleak_classes",
        staticmethod(lambda: (_FakeClient, _FakeScanner)),
    )

    try:
        backend.autoconnect_paired_devices().result(timeout=2.0)
        first_client = backend._clients["AA:BB:CC:01"]

        connected = backend.autoconnect_paired_devices().result(timeout=2.0)
        assert connected == []
        assert backend._clients["AA:BB:CC:01"] is first_client
    finally:
        backend.shutdown()


# --- DevicesScreen.start_autoconnect ---


def _process(app: QApplication, predicate, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_devices_screen_start_autoconnect_connects_and_emits_device_connected():
    app = _get_or_create_qapp()
    backend = MockDeviceBackend(
        devices=[
            MockDevice(
                device_id="trainer-1",
                name="Trainer One",
                device_type=DeviceType.TRAINER,
                paired=True,
                connected=False,
            ),
        ],
    )
    screen = DevicesScreen(backend=backend)
    names: list[str] = []
    screen.device_connected.connect(lambda name: names.append(name))

    screen.start_autoconnect()
    _process(app, lambda: bool(names))

    assert names == ["Trainer One"]
    assert screen.connected_trainer_device_id() == "trainer-1"


def test_devices_screen_start_autoconnect_emits_nothing_when_no_paired_devices():
    app = _get_or_create_qapp()
    backend = MockDeviceBackend(
        devices=[
            MockDevice(
                device_id="a1",
                name="Available",
                device_type=DeviceType.POWER_METER,
                paired=False,
                connected=False,
            ),
        ],
    )
    screen = DevicesScreen(backend=backend)
    names: list[str] = []
    screen.device_connected.connect(lambda name: names.append(name))

    screen.start_autoconnect()
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()

    assert names == []
