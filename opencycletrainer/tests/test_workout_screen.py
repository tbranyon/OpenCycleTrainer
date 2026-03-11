from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.tile_config import TILE_LABEL_BY_KEY
from opencycletrainer.ui.workout_screen import WorkoutScreen


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_workout_screen_displays_mandatory_fields_controls_and_mode():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    label_texts = {label.text() for label in screen.findChildren(QLabel)}
    button_texts = {button.text() for button in screen.findChildren(QPushButton)}

    assert "Time Elapsed" in label_texts
    assert "Time Remaining" in label_texts
    assert "Interval Time/Work Remaining" in label_texts
    assert {"Start", "Pause", "Resume", "Stop"}.issubset(button_texts)
    assert screen.mode_state_value.text() == "ERG"


def test_workout_screen_uses_settings_tile_selection_without_selector_controls():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "workout_avg_power"]),
    )

    assert screen.get_selected_tile_keys() == ["heart_rate", "workout_avg_power"]
    assert screen.findChildren(QCheckBox) == []
    label_texts = {label.text() for label in screen.findChildren(QLabel)}
    assert TILE_LABEL_BY_KEY["heart_rate"] in label_texts
    assert TILE_LABEL_BY_KEY["workout_avg_power"] in label_texts


def test_workout_screen_includes_chart_scaffolding():
    _get_or_create_qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    screen = WorkoutScreen(settings=AppSettings())

    assert isinstance(screen.chart_widget, WorkoutChartWidget)


def test_workout_screen_alert_channel_visibility():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    assert screen.alert_label.isHidden() is True
    screen.show_alert("Trainer disconnected")
    assert screen.alert_label.isHidden() is False
    assert screen.alert_label.text() == "Trainer disconnected"
    screen.clear_alert()
    assert screen.alert_label.isHidden() is True


def test_workout_screen_can_render_opentrueup_offset_value():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    assert screen.opentrueup_offset_value.text() == "-- W"
    screen.set_opentrueup_offset_watts(14)
    assert screen.opentrueup_offset_value.text() == "14 W"
    screen.set_opentrueup_offset_watts(None)
    assert screen.opentrueup_offset_value.text() == "-- W"
