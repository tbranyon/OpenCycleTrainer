from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget

from opencycletrainer.devices.mock_backend import DeviceType, MockDevice, MockDeviceBackend
from opencycletrainer.ui.devices_screen import DevicesScreen


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
    action_widget = table.cellWidget(row, 4)
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
