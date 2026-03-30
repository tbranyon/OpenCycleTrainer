from __future__ import annotations

import os
import time
from concurrent.futures import Future
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget

from opencycletrainer.core.sensors import SensorSample
from opencycletrainer.devices.device_manager import completed_future
from opencycletrainer.devices.decoders.ftms import FTMSCapabilities
from opencycletrainer.devices.decoders.hrs import HRSCapabilities
from opencycletrainer.devices.mock_backend import DeviceType, MockDevice, MockDeviceBackend
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    FTMS_FITNESS_MACHINE_FEATURE_CHARACTERISTIC_UUID,
    FTMS_SUPPORTED_POWER_RANGE_CHARACTERISTIC_UUID,
    FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
)
from opencycletrainer.ui.devices_screen import DevicesScreen

# Reuse payloads from sensor decoder tests
_CPS_SAMPLE_1 = bytes.fromhex("2000fa00e8030008")
_CPS_SAMPLE_2 = bytes.fromhex("2000ff00ea03000c")
_HRS_SAMPLE_8BIT = bytes.fromhex("0048")
_CSC_SAMPLE_1 = bytes.fromhex("03102700000008c8000008")
_CSC_SAMPLE_2 = bytes.fromhex("031a270000000cca00000c")
_FTMS_SAMPLE = bytes.fromhex("4402100eb400fa0096")


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _table_names(table: QTableWidget) -> list[str]:
    names: list[str] = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        names.append(item.text() if item is not None else "")
    return names


def _action_button_texts(table: QTableWidget, row: int) -> set[str]:
    action_widget = table.cellWidget(row, 6)
    if action_widget is None:
        return set()
    buttons = action_widget.findChildren(QPushButton)
    return {button.text() for button in buttons}


def test_mock_backend_available_devices_are_filtered_to_relevant_types():
    backend = MockDeviceBackend()
    available = backend.get_available_devices()

    assert available
    assert all(device.device_type in {
        DeviceType.TRAINER,
        DeviceType.POWER_METER,
        DeviceType.HEART_RATE,
        DeviceType.CADENCE,
    } for device in available)
    assert all(device.name != "Generic Watch" for device in available)


def test_devices_screen_shows_distinct_paired_and_available_sections():
    _get_or_create_qapp()
    screen = DevicesScreen(backend=MockDeviceBackend())

    paired_names = _table_names(screen.paired_table)
    available_names = _table_names(screen.available_table)

    assert paired_names == ["Favero Assioma", "Polar H10", "Wahoo KICKR"]
    assert available_names == ["Magene CAD", "Rotor INspider"]


def test_calibrate_button_only_shown_for_supported_power_meter():
    _get_or_create_qapp()
    backend = MockDeviceBackend(
        devices=[
            MockDevice(
                device_id="pm-cal",
                name="PM Cal",
                device_type=DeviceType.POWER_METER,
                paired=True,
                connected=True,
                battery_percent=80,
                supports_calibration=True,
            ),
            MockDevice(
                device_id="trainer-no",
                name="Trainer",
                device_type=DeviceType.TRAINER,
                paired=True,
                connected=True,
                battery_percent=None,
                supports_calibration=True,
            ),
            MockDevice(
                device_id="pm-no-cal",
                name="PM No Cal",
                device_type=DeviceType.POWER_METER,
                paired=True,
                connected=True,
                battery_percent=70,
                supports_calibration=False,
            ),
        ],
    )
    screen = DevicesScreen(backend=backend)

    row_buttons = {
        screen.paired_table.item(row, 0).text(): _action_button_texts(screen.paired_table, row)
        for row in range(screen.paired_table.rowCount())
    }

    assert "Calibrate" in row_buttons["PM Cal"]
    assert "Calibrate" not in row_buttons["Trainer"]
    assert "Calibrate" not in row_buttons["PM No Cal"]


def _now_utc() -> datetime:
    return datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)


def test_decode_notification_cps_returns_power_and_reading_text():
    _get_or_create_qapp()
    screen = DevicesScreen(backend=MockDeviceBackend())
    now = _now_utc()

    # First sample — no prior revolution data, cadence is None
    sample, text = screen._decode_notification("dev-1", CPS_MEASUREMENT_CHARACTERISTIC_UUID, _CPS_SAMPLE_1, now)
    assert sample is not None
    assert sample.power_watts == 250
    assert sample.cadence_rpm is None
    assert text == "250 W"

    # Second sample — cadence can now be computed
    sample2, text2 = screen._decode_notification("dev-1", CPS_MEASUREMENT_CHARACTERISTIC_UUID, _CPS_SAMPLE_2, now)
    assert sample2 is not None
    assert sample2.power_watts == 255
    assert sample2.cadence_rpm == pytest.approx(120.0)
    assert text2 == "255 W"


def test_decode_notification_hrs_returns_heart_rate_and_reading_text():
    _get_or_create_qapp()
    screen = DevicesScreen(backend=MockDeviceBackend())
    now = _now_utc()

    sample, text = screen._decode_notification("dev-hr", HRS_MEASUREMENT_CHARACTERISTIC_UUID, _HRS_SAMPLE_8BIT, now)
    assert sample is not None
    assert sample.heart_rate_bpm == 72
    assert sample.power_watts is None
    assert text == "72 bpm"


def test_decode_notification_csc_returns_cadence_after_two_samples():
    _get_or_create_qapp()
    screen = DevicesScreen(backend=MockDeviceBackend())
    now = _now_utc()

    sample1, _ = screen._decode_notification("dev-csc", CSC_MEASUREMENT_CHARACTERISTIC_UUID, _CSC_SAMPLE_1, now)
    assert sample1 is not None
    assert sample1.cadence_rpm is None  # needs two samples

    sample2, text2 = screen._decode_notification("dev-csc", CSC_MEASUREMENT_CHARACTERISTIC_UUID, _CSC_SAMPLE_2, now)
    assert sample2 is not None
    assert sample2.cadence_rpm == pytest.approx(120.0)
    assert text2 == "120 rpm"


def test_decode_notification_ftms_returns_power_cadence_speed():
    _get_or_create_qapp()
    screen = DevicesScreen(backend=MockDeviceBackend())
    now = _now_utc()

    sample, text = screen._decode_notification(
        "dev-trainer", FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID, _FTMS_SAMPLE, now
    )
    assert sample is not None
    assert sample.power_watts == 250
    assert sample.cadence_rpm == pytest.approx(90.0)
    assert sample.speed_mps == pytest.approx(10.0)
    assert text == "250 W"


def test_on_notification_emits_sensor_sample_received_signal():
    app = _get_or_create_qapp()
    screen = DevicesScreen(backend=MockDeviceBackend())
    received: list[SensorSample] = []
    screen.sensor_sample_received.connect(lambda s: received.append(s))

    screen._on_notification("dev-hr", HRS_MEASUREMENT_CHARACTERISTIC_UUID, _HRS_SAMPLE_8BIT)
    app.processEvents()

    assert len(received) == 1
    assert received[0].heart_rate_bpm == 72


def test_devices_screen_emits_trainer_device_changed_when_connected_state_changes():
    _get_or_create_qapp()
    backend = MockDeviceBackend(
        devices=[
            MockDevice(
                device_id="trainer-1",
                name="Trainer One",
                device_type=DeviceType.TRAINER,
                paired=True,
                connected=False,
                battery_percent=None,
            ),
        ],
    )
    screen = DevicesScreen(backend=backend)
    changes: list[tuple[object, object]] = []
    screen.trainer_device_changed.connect(lambda b, trainer_id: changes.append((b, trainer_id)))

    backend.connect_device("trainer-1").result(timeout=0.5)
    screen.refresh()
    assert changes[-1] == (backend, "trainer-1")

    backend.disconnect_device("trainer-1").result(timeout=0.5)
    screen.refresh()
    assert changes[-1] == (backend, None)


# --- Double-click capabilities tests ---

class _CapabilitiesMockBackend(MockDeviceBackend):
    """MockDeviceBackend that captures read_gatt_characteristic calls."""

    def __init__(self, devices: list[MockDevice]) -> None:
        super().__init__(devices)
        self.read_calls: list[tuple[str, str]] = []

    def read_gatt_characteristic(self, device_id: str, characteristic_uuid: str) -> Future[bytes]:
        self.read_calls.append((device_id, characteristic_uuid))
        return completed_future(bytes(8))


def _wait_for_signal(app: QApplication, received: list, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while not received and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def _detach_dialog_slot(screen: DevicesScreen) -> list[tuple[str, object]]:
    """Disconnect the dialog-showing slot and return a list that will collect signal emissions."""
    received: list[tuple[str, object]] = []
    screen._capabilities_ready.disconnect(screen._show_ftms_capabilities_dialog)
    screen._capabilities_ready.connect(lambda name, caps: received.append((name, caps)))
    return received


def test_double_click_connected_trainer_emits_capabilities_ready_signal():
    app = _get_or_create_qapp()
    backend = _CapabilitiesMockBackend(devices=[
        MockDevice(
            device_id="trainer-dbl",
            name="Double Click Trainer",
            device_type=DeviceType.TRAINER,
            paired=True,
            connected=True,
            battery_percent=None,
        ),
    ])
    screen = DevicesScreen(backend=backend)
    received = _detach_dialog_slot(screen)

    screen.paired_table.cellDoubleClicked.emit(0, 0)

    _wait_for_signal(app, received)

    assert received, "Expected _capabilities_ready signal to be emitted"
    name, caps = received[0]
    assert name == "Double Click Trainer"
    assert isinstance(caps, FTMSCapabilities)


def test_double_click_disconnected_trainer_does_not_emit_signal():
    app = _get_or_create_qapp()
    backend = _CapabilitiesMockBackend(devices=[
        MockDevice(
            device_id="trainer-disc",
            name="Disconnected Trainer",
            device_type=DeviceType.TRAINER,
            paired=True,
            connected=False,
            battery_percent=None,
        ),
    ])
    screen = DevicesScreen(backend=backend)
    received = _detach_dialog_slot(screen)

    screen.paired_table.cellDoubleClicked.emit(0, 0)

    app.processEvents()
    time.sleep(0.05)
    app.processEvents()

    assert not received, "Expected no signal for disconnected trainer"


def test_double_click_non_trainer_device_does_not_emit_signal():
    app = _get_or_create_qapp()
    backend = _CapabilitiesMockBackend(devices=[
        MockDevice(
            device_id="pm-1",
            name="Power Meter",
            device_type=DeviceType.POWER_METER,
            paired=True,
            connected=True,
            battery_percent=80,
            supports_calibration=True,
        ),
    ])
    screen = DevicesScreen(backend=backend)
    received = _detach_dialog_slot(screen)

    screen.paired_table.cellDoubleClicked.emit(0, 0)

    app.processEvents()
    time.sleep(0.05)
    app.processEvents()

    assert not received, "Expected no signal for non-trainer device"


def _detach_hrs_dialog_slot(screen: DevicesScreen) -> list[tuple[str, object]]:
    """Disconnect the HRS dialog slot and return a list that will collect signal emissions."""
    received: list[tuple[str, object]] = []
    screen._hrs_capabilities_ready.disconnect(screen._show_hrs_capabilities_dialog)
    screen._hrs_capabilities_ready.connect(lambda name, caps: received.append((name, caps)))
    return received


def test_double_click_connected_hrm_emits_hrs_capabilities_ready_signal():
    app = _get_or_create_qapp()
    backend = _CapabilitiesMockBackend(devices=[
        MockDevice(
            device_id="hrm-1",
            name="Polar H10",
            device_type=DeviceType.HEART_RATE,
            paired=True,
            connected=True,
            battery_percent=80,
        ),
    ])
    screen = DevicesScreen(backend=backend)
    received = _detach_hrs_dialog_slot(screen)

    screen.paired_table.cellDoubleClicked.emit(0, 0)

    _wait_for_signal(app, received)

    assert received, "Expected _hrs_capabilities_ready signal to be emitted"
    name, caps = received[0]
    assert name == "Polar H10"
    assert isinstance(caps, HRSCapabilities)


def test_double_click_disconnected_hrm_does_not_emit_hrs_signal():
    app = _get_or_create_qapp()
    backend = _CapabilitiesMockBackend(devices=[
        MockDevice(
            device_id="hrm-disc",
            name="Disconnected HRM",
            device_type=DeviceType.HEART_RATE,
            paired=True,
            connected=False,
            battery_percent=None,
        ),
    ])
    screen = DevicesScreen(backend=backend)
    received = _detach_hrs_dialog_slot(screen)

    screen.paired_table.cellDoubleClicked.emit(0, 0)

    app.processEvents()
    time.sleep(0.05)
    app.processEvents()

    assert not received, "Expected no signal for disconnected HRM"
