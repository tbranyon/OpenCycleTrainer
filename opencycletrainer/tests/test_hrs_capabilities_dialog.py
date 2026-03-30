from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from opencycletrainer.devices.decoders.hrs import HRSBodySensorLocation, HRSCapabilities
from opencycletrainer.ui.hrs_capabilities_dialog import HRSCapabilitiesDialog


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _collect_label_text(widget: QApplication) -> str:
    return " | ".join(label.text() for label in widget.findChildren(QLabel))


def test_dialog_title_contains_device_name():
    _get_or_create_qapp()
    capabilities = HRSCapabilities(body_sensor_location=None)
    dialog = HRSCapabilitiesDialog("Polar H10", capabilities)
    assert "Polar H10" in dialog.windowTitle()


def test_dialog_shows_body_sensor_location_chest():
    _get_or_create_qapp()
    capabilities = HRSCapabilities(body_sensor_location=HRSBodySensorLocation.CHEST)
    dialog = HRSCapabilitiesDialog("Polar H10", capabilities)
    text = _collect_label_text(dialog)
    assert "Chest" in text


def test_dialog_shows_body_sensor_location_wrist():
    _get_or_create_qapp()
    capabilities = HRSCapabilities(body_sensor_location=HRSBodySensorLocation.WRIST)
    dialog = HRSCapabilitiesDialog("Apple Watch", capabilities)
    text = _collect_label_text(dialog)
    assert "Wrist" in text


def test_dialog_shows_na_when_body_sensor_location_unavailable():
    _get_or_create_qapp()
    capabilities = HRSCapabilities(body_sensor_location=None)
    dialog = HRSCapabilitiesDialog("Generic HRM", capabilities)
    text = _collect_label_text(dialog)
    assert "N/A" in text
