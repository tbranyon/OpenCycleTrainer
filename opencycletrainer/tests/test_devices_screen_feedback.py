"""Devices screen feedback: in-progress states, plain-language errors, and safer actions."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import replace
import os
import threading
import time

from PySide6.QtWidgets import QApplication, QPushButton

from opencycletrainer.devices.mock_backend import DeviceType, MockDevice, MockDeviceBackend
from opencycletrainer.devices.types import DeviceInfo
from opencycletrainer.ui.devices_screen import DevicesScreen

_COL_STATUS = 2
_COL_BATTERY = 3
_COL_ACTIONS = 6


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _process(app: QApplication, predicate=lambda: False, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            break
        time.sleep(0.005)
    app.processEvents()


class _ControllableBackend(MockDeviceBackend):
    """Mock backend whose connect and scan futures complete only when the test says so."""

    def __init__(self, devices: list[MockDevice]) -> None:
        super().__init__(devices)
        self.calls: list[tuple[str, str]] = []
        self.pending_connects: dict[str, Future] = {}
        self.pending_scan: Future | None = None

    def connect_device(self, device_id: str) -> Future:
        self.calls.append(("connect", device_id))
        future: Future = Future()
        self.pending_connects[device_id] = future
        return future

    def finish_connect(self, device_id: str, error: BaseException | None = None) -> None:
        future = self.pending_connects.pop(device_id)
        if error is not None:
            future.set_exception(error)
            return
        super().connect_device(device_id)
        future.set_result(None)

    def disconnect_device(self, device_id: str) -> Future:
        self.calls.append(("disconnect", device_id))
        pending = self.pending_connects.pop(device_id, None)
        if pending is not None and not pending.done():
            pending.cancel()
        return super().disconnect_device(device_id)

    def unpair_device(self, device_id: str) -> Future:
        self.calls.append(("unpair", device_id))
        return super().unpair_device(device_id)

    def scan(self) -> Future:
        self.calls.append(("scan", ""))
        self.pending_scan = Future()
        return self.pending_scan

    def set_device(self, device: DeviceInfo) -> None:
        with self._lock:
            self._devices[device.device_id] = device


def _trainer(**overrides) -> MockDevice:
    fields = dict(device_id="AA:01", name="Trainer One", device_type=DeviceType.TRAINER, paired=True, connected=False)
    fields.update(overrides)
    return MockDevice(**fields)


def _row_buttons(screen: DevicesScreen, row: int = 0) -> dict[str, QPushButton]:
    widget = screen.paired_table.cellWidget(row, _COL_ACTIONS)
    return {button.text(): button for button in widget.findChildren(QPushButton)}


def _status(screen: DevicesScreen, row: int = 0) -> str:
    return screen.paired_table.item(row, _COL_STATUS).text()


# ── Immediate feedback for Connect ────────────────────────────────────────────


def test_connect_shows_connecting_and_offers_cancel_until_it_finishes():
    app = _app()
    backend = _ControllableBackend([_trainer()])
    screen = DevicesScreen(backend=backend)

    _row_buttons(screen)["Connect"].click()
    _process(app)

    assert _status(screen) == "Connecting…"
    assert "Cancel" in _row_buttons(screen)
    assert not screen.busy_indicator.isHidden()
    assert "Trainer One" in screen.status_label.text()

    backend.finish_connect("AA:01")
    _process(app, lambda: _status(screen) == "Connected")

    assert _status(screen) == "Connected"
    assert "Disconnect" in _row_buttons(screen)
    assert screen.busy_indicator.isHidden()
    assert screen.status_label.text() == "Connected to Trainer One."


def test_cancel_stops_the_pending_connect_without_an_error_message():
    app = _app()
    backend = _ControllableBackend([_trainer()])
    screen = DevicesScreen(backend=backend)
    _row_buttons(screen)["Connect"].click()
    _process(app)

    _row_buttons(screen)["Cancel"].click()
    _process(app, lambda: _status(screen) == "Disconnected")

    assert ("disconnect", "AA:01") in backend.calls
    assert _status(screen) == "Disconnected"
    assert "Connect" in _row_buttons(screen)
    assert screen.status_label.text() == "Stopped connecting to Trainer One."


def test_backend_reported_connecting_state_is_shown():
    app = _app()
    backend = _ControllableBackend([_trainer(connecting=True)])
    screen = DevicesScreen(backend=backend)
    _process(app)

    assert _status(screen) == "Connecting…"
    assert "Cancel" in _row_buttons(screen)


def test_reconnecting_device_is_labelled_and_can_be_stopped():
    app = _app()
    backend = _ControllableBackend([_trainer(reconnecting=True)])
    screen = DevicesScreen(backend=backend)
    _process(app)

    assert _status(screen) == "Reconnecting…"
    assert "Cancel" in _row_buttons(screen)


# ── Plain-language errors with device names ───────────────────────────────────


def test_failed_connect_explains_the_problem_using_the_device_name():
    app = _app()
    backend = _ControllableBackend([_trainer()])
    screen = DevicesScreen(backend=backend)
    _row_buttons(screen)["Connect"].click()
    _process(app)

    backend.finish_connect("AA:01", error=asyncio.TimeoutError())
    _process(app, lambda: "didn't respond" in screen.status_label.text())

    message = screen.status_label.text()
    assert message.startswith("Trainer One didn't respond")
    assert "AA:01" not in message
    assert _status(screen) == "Disconnected"
    assert "Connect" in _row_buttons(screen)


# ── Scan ──────────────────────────────────────────────────────────────────────


def test_scan_button_shows_progress_and_ignores_repeat_presses():
    app = _app()
    backend = _ControllableBackend([_trainer()])
    screen = DevicesScreen(backend=backend)

    screen.scan_button.click()
    _process(app)
    assert screen.scan_button.text() == "Scanning…"
    assert not screen.scan_button.isEnabled()
    assert not screen.busy_indicator.isHidden()

    screen.scan_button.click()
    assert [call for call in backend.calls if call[0] == "scan"] == [("scan", "")]

    backend.pending_scan.set_result([])
    _process(app, lambda: screen.scan_button.isEnabled())
    assert screen.scan_button.text() == "Scan"
    assert screen.busy_indicator.isHidden()


def test_devices_found_during_a_scan_appear_without_waiting_for_it_to_finish():
    app = _app()
    backend = _ControllableBackend([_trainer()])
    screen = DevicesScreen(backend=backend)
    screen.scan_button.click()
    _process(app)

    backend.set_device(MockDevice(device_id="HR:01", name="Strap", device_type=DeviceType.HEART_RATE))
    threading.Thread(target=backend.devices_changed_callback).start()
    _process(app, lambda: screen.available_table.rowCount() == 1)

    assert screen.available_table.rowCount() == 1
    assert screen.available_table.item(0, 0).text() == "Strap"


# ── Safer actions ─────────────────────────────────────────────────────────────


def test_unpair_asks_for_confirmation_first():
    app = _app()
    backend = _ControllableBackend([_trainer()])
    screen = DevicesScreen(backend=backend)
    asked: list[str] = []
    screen.confirm_unpair = lambda device: asked.append(device.name) or False

    _row_buttons(screen)["Unpair"].click()
    _process(app)

    assert asked == ["Trainer One"]
    assert ("unpair", "AA:01") not in backend.calls

    screen.confirm_unpair = lambda device: True
    _row_buttons(screen)["Unpair"].click()
    _process(app, lambda: screen.paired_table.rowCount() == 0)
    assert ("unpair", "AA:01") in backend.calls


def test_pairing_a_device_connects_it_straight_away():
    app = _app()
    backend = _ControllableBackend([_trainer(paired=False)])
    screen = DevicesScreen(backend=backend)
    widget = screen.available_table.cellWidget(0, _COL_ACTIONS)
    next(b for b in widget.findChildren(QPushButton) if b.text() == "Pair").click()
    _process(app, lambda: ("connect", "AA:01") in backend.calls)

    assert ("connect", "AA:01") in backend.calls
    assert _status(screen) == "Connecting…"


# ── Empty states and battery ──────────────────────────────────────────────────


def test_empty_paired_list_explains_what_to_do():
    app = _app()
    screen = DevicesScreen(backend=_ControllableBackend([]))
    _process(app)
    assert not screen.paired_empty_label.isHidden()
    assert "Scan" in screen.paired_empty_label.text()

    screen_with_device = DevicesScreen(backend=_ControllableBackend([_trainer()]))
    assert screen_with_device.paired_empty_label.isHidden()


def test_battery_level_is_shown_when_known_and_a_dash_otherwise():
    app = _app()
    backend = _ControllableBackend([
        _trainer(connected=True),
        MockDevice(device_id="HR:01", name="Strap", device_type=DeviceType.HEART_RATE,
                   paired=True, connected=True, battery_percent=76),
    ])
    screen = DevicesScreen(backend=backend)
    _process(app)
    by_name = {
        screen.paired_table.item(row, 0).text(): screen.paired_table.item(row, _COL_BATTERY).text()
        for row in range(screen.paired_table.rowCount())
    }
    assert by_name == {"Strap": "76%", "Trainer One": "—"}


def test_backend_updates_from_another_thread_refresh_the_table():
    app = _app()
    backend = _ControllableBackend([_trainer(connected=True)])
    screen = DevicesScreen(backend=backend)
    _process(app)

    backend.set_device(_trainer(connected=True, battery_percent=41))
    threading.Thread(target=backend.devices_changed_callback).start()
    _process(app, lambda: screen.paired_table.item(0, _COL_BATTERY).text() == "41%")

    assert screen.paired_table.item(0, _COL_BATTERY).text() == "41%"
