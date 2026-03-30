from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from opencycletrainer.devices.decoders.ftms import (
    FTMSCapabilities,
    FTMSFeatures,
    ResistanceLevelRange,
    SupportedPowerRange,
)
from opencycletrainer.ui.ftms_capabilities_dialog import FTMSCapabilitiesDialog


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
    capabilities = FTMSCapabilities(features=None, power_range=None, resistance_range=None)
    dialog = FTMSCapabilitiesDialog("Wahoo KICKR", capabilities)
    assert "Wahoo KICKR" in dialog.windowTitle()


def test_dialog_shows_supported_fitness_features():
    _get_or_create_qapp()
    fitness = (1 << 14) | (1 << 1)  # Power Measurement + Cadence
    target = 1 << 3                  # Power Target Setting
    features = FTMSFeatures(fitness_machine_features=fitness, target_setting_features=target)
    capabilities = FTMSCapabilities(features=features, power_range=None, resistance_range=None)
    dialog = FTMSCapabilitiesDialog("Test Trainer", capabilities)
    text = _collect_label_text(dialog)
    assert "Power Measurement" in text
    assert "Cadence" in text
    assert "Power Target Setting" in text


def test_dialog_shows_power_range():
    _get_or_create_qapp()
    power_range = SupportedPowerRange(minimum_watts=0, maximum_watts=2000, minimum_increment_watts=1)
    capabilities = FTMSCapabilities(features=None, power_range=power_range, resistance_range=None)
    dialog = FTMSCapabilitiesDialog("Test Trainer", capabilities)
    text = _collect_label_text(dialog)
    assert "2000" in text
    assert "0" in text


def test_dialog_shows_resistance_range():
    _get_or_create_qapp()
    resistance_range = ResistanceLevelRange(minimum=0.0, maximum=10.0, minimum_increment=0.1)
    capabilities = FTMSCapabilities(features=None, power_range=None, resistance_range=resistance_range)
    dialog = FTMSCapabilitiesDialog("Test Trainer", capabilities)
    text = _collect_label_text(dialog)
    assert "10.0" in text or "10" in text


def test_dialog_handles_all_none_capabilities_without_error():
    _get_or_create_qapp()
    capabilities = FTMSCapabilities(features=None, power_range=None, resistance_range=None)
    dialog = FTMSCapabilitiesDialog("Test Trainer", capabilities)
    text = _collect_label_text(dialog)
    assert "N/A" in text or "Unknown" in text or len(text) > 0
