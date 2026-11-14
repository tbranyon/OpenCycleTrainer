"""Connection coordination, discovery-driven connects, and battery reads in BleakDeviceBackend.

A fake radio stands in for bleak: devices advertise (optionally after a delay), connects can
be held open, and the number of simultaneous connect attempts is recorded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import time
from typing import Any

import pytest

from opencycletrainer.devices.ble_backend import BleakDeviceBackend
from opencycletrainer.devices.types import (
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    FTMS_SERVICE_UUID,
    HRS_SERVICE_UUID,
)
from opencycletrainer.storage.paired_devices import PairedDeviceStore

_WAIT_SECONDS = 3.0


@dataclass
class _Device:
    name: str
    address: str
    details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Adv:
    service_uuids: list[str]
    rssi: int = -50


class _FakeRadio:
    """Shared state behind the fake bleak client and scanner classes."""

    def __init__(self) -> None:
        self.advertising: dict[str, tuple[_Device, _Adv, float]] = {}
        self.reachable: set[str] = set()
        self.connect_gate: threading.Event | None = None
        self.connect_delay_seconds = 0.0
        self.active_connects = 0
        self.max_active_connects = 0
        self.connect_calls: list[Any] = []
        self.clients: list[Any] = []
        self.battery: dict[str, int] = {}
        self.scans_started = 0
        self.lock = threading.Lock()

    def advertise(self, address: str, name: str, service: str, *, after: float = 0.0) -> None:
        device = _Device(name=name, address=address, details={"path": f"/org/bluez/hci0/dev_{address}"})
        self.advertising[address] = (device, _Adv(service_uuids=[service]), after)
        self.reachable.add(address)

    def classes(self) -> tuple[type, type]:
        radio = self

        class Client:
            def __init__(self, target: Any, disconnected_callback: Any = None, **kwargs: Any) -> None:
                self.target = target
                self.address = getattr(target, "address", target)
                self.disconnected_callback = disconnected_callback
                self.kwargs = kwargs
                self.is_connected = False
                radio.clients.append(self)

            async def connect(self, **kwargs: Any) -> None:
                with radio.lock:
                    radio.connect_calls.append(self.target)
                    radio.active_connects += 1
                    radio.max_active_connects = max(radio.max_active_connects, radio.active_connects)
                try:
                    if radio.connect_gate is not None:
                        while not radio.connect_gate.is_set():
                            await asyncio.sleep(0.01)
                    if radio.connect_delay_seconds:
                        await asyncio.sleep(radio.connect_delay_seconds)
                    if self.address not in radio.reachable:
                        raise asyncio.TimeoutError()
                    self.is_connected = True
                finally:
                    with radio.lock:
                        radio.active_connects -= 1

            async def disconnect(self) -> None:
                self.is_connected = False

            def drop(self) -> None:
                self.is_connected = False
                if self.disconnected_callback is not None:
                    self.disconnected_callback(self)

            async def start_notify(self, uuid: str, handler: Any) -> None:
                pass

            async def stop_notify(self, uuid: str) -> None:
                pass

            async def read_gatt_char(self, uuid: str) -> bytearray:
                if uuid == BATTERY_LEVEL_CHARACTERISTIC_UUID and self.address in radio.battery:
                    return bytearray([radio.battery[self.address]])
                raise RuntimeError(f"Characteristic {uuid} was not found!")

            async def write_gatt_char(self, uuid: str, payload: bytearray, response: bool = True) -> None:
                pass

        class Scanner:
            def __init__(self, detection_callback: Any = None, **kwargs: Any) -> None:
                self._callback = detection_callback
                self._handles: list[asyncio.TimerHandle] = []

            async def start(self) -> None:
                radio.scans_started += 1
                loop = asyncio.get_running_loop()
                for device, adv, after in list(radio.advertising.values()):
                    self._handles.append(loop.call_later(after, self._callback, device, adv))

            async def stop(self) -> None:
                for handle in self._handles:
                    handle.cancel()
                self._handles.clear()

        return Client, Scanner


def _backend(monkeypatch, tmp_path, radio: _FakeRadio, paired: list[tuple[str, str, str]] = (), **kwargs) -> BleakDeviceBackend:
    store = PairedDeviceStore(path=tmp_path / "paired.json")
    store.save([{"device_id": a, "name": n, "device_type": t} for a, n, t in paired])
    monkeypatch.setattr(BleakDeviceBackend, "_load_bleak_classes", staticmethod(radio.classes))
    defaults = dict(
        scan_timeout_seconds=0.3,
        autoconnect_discovery_seconds=0.6,
        reconnect_delay_seconds=0.02,
        reconnect_max_delay_seconds=0.05,
        battery_poll_seconds=60.0,
        bluez_battery_reader=None,
    )
    defaults.update(kwargs)
    return BleakDeviceBackend(paired_device_store=store, **defaults)


def _wait_for(predicate, timeout: float = _WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _paired(backend: BleakDeviceBackend, device_id: str):
    return next(d for d in backend.get_paired_devices() if d.device_id == device_id)


# ── Overlapping operations ────────────────────────────────────────────────────


def test_repeated_connect_joins_the_attempt_already_in_progress(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    radio.connect_gate = threading.Event()
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        first = backend.connect_device("T1")
        second = backend.connect_device("T1")
        assert _wait_for(lambda: len(radio.connect_calls) == 1)
        radio.connect_gate.set()
        first.result(timeout=_WAIT_SECONDS)
        second.result(timeout=_WAIT_SECONDS)
        assert len(radio.connect_calls) == 1
        assert _paired(backend, "T1").connected
    finally:
        backend.shutdown()


def test_connects_to_different_devices_never_overlap(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.update({"T1", "H1"})
    radio.connect_delay_seconds = 0.05
    backend = _backend(
        monkeypatch, tmp_path, radio,
        paired=[("T1", "Trainer", "trainer"), ("H1", "Strap", "heart_rate")],
    )
    try:
        futures = [backend.connect_device("T1"), backend.connect_device("H1")]
        for future in futures:
            future.result(timeout=_WAIT_SECONDS)
        assert radio.max_active_connects == 1
        assert _paired(backend, "T1").connected and _paired(backend, "H1").connected
    finally:
        backend.shutdown()


def test_device_reports_connecting_while_attempt_is_in_progress(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    radio.connect_gate = threading.Event()
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        future = backend.connect_device("T1")
        assert _wait_for(lambda: _paired(backend, "T1").connecting)
        assert _paired(backend, "T1").connection_status == "Connecting…"
        radio.connect_gate.set()
        future.result(timeout=_WAIT_SECONDS)
        device = _paired(backend, "T1")
        assert device.connected and not device.connecting
    finally:
        backend.shutdown()


def test_disconnect_cancels_a_pending_connect(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    radio.connect_gate = threading.Event()
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        connect_future = backend.connect_device("T1")
        assert _wait_for(lambda: _paired(backend, "T1").connecting)

        backend.disconnect_device("T1").result(timeout=_WAIT_SECONDS)

        with pytest.raises(BaseException):
            connect_future.result(timeout=_WAIT_SECONDS)
        device = _paired(backend, "T1")
        assert not device.connected and not device.connecting and not device.reconnecting
    finally:
        radio.connect_gate.set()
        backend.shutdown()


def test_state_changes_are_reported_through_devices_changed_callback(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    notifications: list[int] = []
    backend.devices_changed_callback = lambda: notifications.append(1)
    try:
        backend.connect_device("T1").result(timeout=_WAIT_SECONDS)
        assert len(notifications) >= 2  # connecting started, then connected
    finally:
        backend.shutdown()


# ── Discovery-driven connects ─────────────────────────────────────────────────


def test_connect_uses_the_discovered_device_object(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.advertise("T1", "Trainer", FTMS_SERVICE_UUID)
    backend = _backend(monkeypatch, tmp_path, radio)
    try:
        backend.scan().result(timeout=_WAIT_SECONDS)
        backend.pair_device("T1").result(timeout=_WAIT_SECONDS)
        backend.connect_device("T1").result(timeout=_WAIT_SECONDS)
        assert isinstance(radio.connect_calls[-1], _Device)
    finally:
        backend.shutdown()


def test_scan_lists_devices_while_it_is_still_running(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.advertise("T1", "Trainer", FTMS_SERVICE_UUID)
    backend = _backend(monkeypatch, tmp_path, radio, scan_timeout_seconds=1.0)
    try:
        future = backend.scan()
        assert _wait_for(lambda: any(d.device_id == "T1" for d in backend.get_available_devices()), timeout=0.8)
        assert not future.done()
        assert [d.device_id for d in future.result(timeout=_WAIT_SECONDS)] == ["T1"]
    finally:
        backend.shutdown()


def test_scan_returns_without_waiting_for_paired_reconnects(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.advertise("T1", "Trainer", FTMS_SERVICE_UUID)
    radio.connect_gate = threading.Event()
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        backend.scan().result(timeout=_WAIT_SECONDS)
        assert not _paired(backend, "T1").connected
        radio.connect_gate.set()
        assert _wait_for(lambda: _paired(backend, "T1").connected)
    finally:
        radio.connect_gate.set()
        backend.shutdown()


def test_autoconnect_connects_each_device_as_soon_as_it_advertises(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.advertise("T1", "Trainer", FTMS_SERVICE_UUID)
    radio.advertise("H1", "Strap", HRS_SERVICE_UUID, after=0.2)
    backend = _backend(
        monkeypatch, tmp_path, radio,
        paired=[("T1", "Trainer", "trainer"), ("H1", "Strap", "heart_rate")],
        autoconnect_discovery_seconds=2.0,
    )
    try:
        started = time.monotonic()
        connected = backend.autoconnect_paired_devices().result(timeout=_WAIT_SECONDS)
        assert sorted(connected) == ["H1", "T1"]
        assert time.monotonic() - started < 1.5  # finished once both were seen, not at the deadline
    finally:
        backend.shutdown()


def test_autoconnect_is_not_held_up_by_a_device_that_is_switched_off(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.advertise("T1", "Trainer", FTMS_SERVICE_UUID)
    radio.connect_delay_seconds = 0.0
    backend = _backend(
        monkeypatch, tmp_path, radio,
        paired=[("OFF", "Strap", "heart_rate"), ("T1", "Trainer", "trainer")],
        autoconnect_discovery_seconds=1.0,
    )
    try:
        future = backend.autoconnect_paired_devices()
        assert _wait_for(lambda: _paired(backend, "T1").connected, timeout=0.5)
        assert future.result(timeout=_WAIT_SECONDS) == ["T1"]
    finally:
        backend.shutdown()


def test_autoconnect_tries_devices_that_never_advertised_directly(monkeypatch, tmp_path):
    """A device the OS already holds connected does not advertise, but a direct connect works."""
    radio = _FakeRadio()
    radio.reachable.add("H1")
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("H1", "Strap", "heart_rate")],
                       autoconnect_discovery_seconds=0.2)
    try:
        assert backend.autoconnect_paired_devices().result(timeout=_WAIT_SECONDS) == ["H1"]
        assert radio.connect_calls[-1] == "H1"
    finally:
        backend.shutdown()


# ── Reconnect after a dropout ─────────────────────────────────────────────────


def test_dropped_device_shows_reconnecting_then_comes_back(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        backend.connect_device("T1").result(timeout=_WAIT_SECONDS)
        radio.reachable.discard("T1")
        backend._runner.submit(_call_soon(radio.clients[-1].drop)).result(timeout=_WAIT_SECONDS)

        assert _wait_for(lambda: _paired(backend, "T1").reconnecting)
        assert _paired(backend, "T1").connection_status == "Reconnecting…"
        radio.reachable.add("T1")
        assert _wait_for(lambda: _paired(backend, "T1").connected)
        assert not _paired(backend, "T1").reconnecting
    finally:
        backend.shutdown()


def test_reconnect_keeps_trying_beyond_a_short_outage(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        backend.connect_device("T1").result(timeout=_WAIT_SECONDS)
        radio.reachable.discard("T1")
        backend._runner.submit(_call_soon(radio.clients[-1].drop)).result(timeout=_WAIT_SECONDS)
        # Many more failed attempts than the old fixed limit of 10.
        assert _wait_for(lambda: len(radio.connect_calls) > 15)
        radio.reachable.add("T1")
        assert _wait_for(lambda: _paired(backend, "T1").connected)
    finally:
        backend.shutdown()


async def _call_soon(fn) -> None:
    fn()


# ── Battery ───────────────────────────────────────────────────────────────────


def test_battery_level_read_from_battery_service_after_connect(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("H1")
    radio.battery["H1"] = 76
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("H1", "Strap", "heart_rate")])
    try:
        backend.connect_device("H1").result(timeout=_WAIT_SECONDS)
        assert _wait_for(lambda: _paired(backend, "H1").battery_percent == 76)
    finally:
        backend.shutdown()


def test_battery_level_falls_back_to_bluez_when_service_is_hidden(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("H1")
    requested: list[str] = []

    async def bluez_reader(address: str) -> int | None:
        requested.append(address)
        return 58

    backend = _backend(monkeypatch, tmp_path, radio, paired=[("H1", "Strap", "heart_rate")],
                       bluez_battery_reader=bluez_reader)
    try:
        backend.connect_device("H1").result(timeout=_WAIT_SECONDS)
        assert _wait_for(lambda: _paired(backend, "H1").battery_percent == 58)
        assert requested[0] == "H1"
    finally:
        backend.shutdown()


def test_battery_level_is_refreshed_while_connected(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("H1")
    radio.battery["H1"] = 90
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("H1", "Strap", "heart_rate")],
                       battery_poll_seconds=0.05)
    try:
        backend.connect_device("H1").result(timeout=_WAIT_SECONDS)
        assert _wait_for(lambda: _paired(backend, "H1").battery_percent == 90)
        radio.battery["H1"] = 89
        assert _wait_for(lambda: _paired(backend, "H1").battery_percent == 89)
    finally:
        backend.shutdown()


def test_device_without_battery_reporting_leaves_level_unknown(monkeypatch, tmp_path):
    radio = _FakeRadio()
    radio.reachable.add("T1")
    backend = _backend(monkeypatch, tmp_path, radio, paired=[("T1", "Trainer", "trainer")])
    try:
        backend.connect_device("T1").result(timeout=_WAIT_SECONDS)
        time.sleep(0.1)
        assert _paired(backend, "T1").battery_percent is None
    finally:
        backend.shutdown()


# ── BlueZ battery reader (Linux) ──────────────────────────────────────────────


def _fake_bluez_bus(monkeypatch, managed_objects: dict) -> list[str]:
    """Replace dbus_fast's MessageBus with one that answers GetManagedObjects."""
    import dbus_fast.aio
    from dbus_fast import MessageType

    calls: list[str] = []

    class _Reply:
        message_type = MessageType.METHOD_RETURN
        body = [managed_objects]

    class _Bus:
        def __init__(self, bus_type=None) -> None:
            pass

        async def connect(self):
            return self

        async def call(self, message):
            calls.append(message.member)
            return _Reply()

        def disconnect(self) -> None:
            calls.append("disconnect")

    monkeypatch.setattr(dbus_fast.aio, "MessageBus", _Bus)
    return calls


def test_bluez_reader_returns_percentage_for_matching_address(monkeypatch):
    from dbus_fast import Variant

    from opencycletrainer.devices.ble_backend import read_bluez_battery_percent

    calls = _fake_bluez_bus(monkeypatch, {
        "/org/bluez/hci0/dev_11_22": {
            "org.bluez.Device1": {"Address": Variant("s", "11:22:33:44:55:66")},
        },
        "/org/bluez/hci0/dev_AA_BB": {
            "org.bluez.Device1": {"Address": Variant("s", "AA:BB:CC:DD:EE:FF")},
            "org.bluez.Battery1": {"Percentage": Variant("y", 63)},
        },
    })

    assert asyncio.run(read_bluez_battery_percent("aa:bb:cc:dd:ee:ff")) == 63
    assert calls == ["GetManagedObjects", "disconnect"]


def test_bluez_reader_returns_none_when_device_has_no_battery(monkeypatch):
    from dbus_fast import Variant

    from opencycletrainer.devices.ble_backend import read_bluez_battery_percent

    _fake_bluez_bus(monkeypatch, {
        "/org/bluez/hci0/dev_AA_BB": {"org.bluez.Device1": {"Address": Variant("s", "AA:BB:CC:DD:EE:FF")}},
    })

    assert asyncio.run(read_bluez_battery_percent("AA:BB:CC:DD:EE:FF")) is None
