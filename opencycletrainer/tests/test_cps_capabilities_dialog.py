from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QLabel

from opencycletrainer.devices.decoders.cps import (
    CPSCapabilities,
    CPSFeatures,
    CPSSensorLocation,
)
from opencycletrainer.ui.cps_capabilities_dialog import CPSCapabilitiesDialog


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
    capabilities = CPSCapabilities(features=None, sensor_location=None)
    dialog = CPSCapabilitiesDialog("Garmin Rally", capabilities)
    assert "Garmin Rally" in dialog.windowTitle()


def test_dialog_shows_sensor_location_left_crank():
    _get_or_create_qapp()
    capabilities = CPSCapabilities(
        features=None,
        sensor_location=CPSSensorLocation.LEFT_CRANK,
    )
    dialog = CPSCapabilitiesDialog("Garmin Rally", capabilities)
    text = _collect_label_text(dialog)
    assert "Left Crank" in text


def test_dialog_shows_sensor_location_right_pedal():
    _get_or_create_qapp()
    capabilities = CPSCapabilities(
        features=None,
        sensor_location=CPSSensorLocation.RIGHT_PEDAL,
    )
    dialog = CPSCapabilitiesDialog("Favero Assioma", capabilities)
    text = _collect_label_text(dialog)
    assert "Right Pedal" in text


def test_dialog_shows_na_when_sensor_location_unavailable():
    _get_or_create_qapp()
    capabilities = CPSCapabilities(features=None, sensor_location=None)
    dialog = CPSCapabilitiesDialog("Generic PM", capabilities)
    text = _collect_label_text(dialog)
    assert "N/A" in text


def test_dialog_shows_cps_features_when_available():
    _get_or_create_qapp()
    # Bit 3 = Crank Revolution Data supported
    features = CPSFeatures(feature_flags=1 << 3)
    capabilities = CPSCapabilities(features=features, sensor_location=None)
    dialog = CPSCapabilitiesDialog("Wahoo Powrlink", capabilities)
    text = _collect_label_text(dialog)
    assert "Yes" in text


def test_dialog_shows_measurement_context_force_based():
    _get_or_create_qapp()
    features = CPSFeatures(feature_flags=0)  # bit 16 = 0 -> Force-based
    capabilities = CPSCapabilities(features=features, sensor_location=None)
    dialog = CPSCapabilitiesDialog("PM", capabilities)
    text = _collect_label_text(dialog)
    assert "Force-based" in text


def test_dialog_shows_measurement_context_torque_based():
    _get_or_create_qapp()
    features = CPSFeatures(feature_flags=1 << 16)  # bit 16 = 1 -> Torque-based
    capabilities = CPSCapabilities(features=features, sensor_location=None)
    dialog = CPSCapabilitiesDialog("PM", capabilities)
    text = _collect_label_text(dialog)
    assert "Torque-based" in text


def test_dialog_shows_na_when_features_unavailable():
    _get_or_create_qapp()
    capabilities = CPSCapabilities(features=None, sensor_location=None)
    dialog = CPSCapabilitiesDialog("Generic PM", capabilities)
    text = _collect_label_text(dialog)
    assert "N/A" in text
