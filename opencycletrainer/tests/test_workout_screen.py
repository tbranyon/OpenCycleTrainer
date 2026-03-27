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
    assert "Current / Target Power" in label_texts
    assert "Time Remaining" in label_texts
    assert "Interval Time/Work Remaining" in label_texts
    assert {"Start", "Pause", "Resume", "Stop"}.issubset(button_texts)


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


def test_workout_screen_alert_defaults_to_error_style():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    screen.show_alert("Something went wrong")
    assert "#d33" in screen.alert_label.styleSheet()


def test_workout_screen_alert_success_style():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    screen.show_alert("Workout saved: ride.fit", alert_type="success")
    style = screen.alert_label.styleSheet()
    assert "#1a7f37" in style or "green" in style.lower()


def test_workout_screen_can_render_opentrueup_offset_value():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    assert screen.opentrueup_offset_value.text() == "-- W"
    screen.set_opentrueup_offset_watts(14)
    assert screen.opentrueup_offset_value.text() == "14 W"
    screen.set_opentrueup_offset_watts(None)
    assert screen.opentrueup_offset_value.text() == "-- W"


def test_resistance_level_label_hidden_by_default():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    assert screen.resistance_level_label.isHidden() is True


def test_resistance_level_label_shown_with_value_when_in_resistance_mode():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    screen.set_resistance_level(50)

    assert screen.resistance_level_label.isHidden() is False
    assert screen.resistance_level_label.text() == "50 %"


def test_resistance_level_label_hidden_when_cleared():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    screen.set_resistance_level(25)
    screen.set_resistance_level(None)

    assert screen.resistance_level_label.isHidden() is True


def test_resistance_level_label_zero():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    screen.set_resistance_level(0)

    assert screen.resistance_level_label.isHidden() is False
    assert screen.resistance_level_label.text() == "0 %"


def test_pause_dialog_shows_paused_message():
    _get_or_create_qapp()
    from opencycletrainer.ui.workout_screen import PauseDialog

    dialog = PauseDialog()
    label_texts = {label.text() for label in dialog.findChildren(QLabel)}
    assert any("Paused" in t for t in label_texts)


def test_pause_dialog_has_resume_button():
    _get_or_create_qapp()
    from opencycletrainer.ui.workout_screen import PauseDialog

    dialog = PauseDialog()
    button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "Resume" in button_texts


def test_pause_dialog_resume_shows_countdown():
    _get_or_create_qapp()
    from opencycletrainer.ui.workout_screen import PauseDialog

    dialog = PauseDialog()
    dialog.resume_button.click()
    assert dialog.countdown_label.text() == "3"


def test_pause_dialog_emits_resume_confirmed_after_countdown():
    _get_or_create_qapp()
    from opencycletrainer.ui.workout_screen import PauseDialog

    confirmed = []
    dialog = PauseDialog()
    dialog.resume_confirmed.connect(lambda: confirmed.append(True))
    dialog.resume_button.click()
    dialog._tick_countdown()  # 2
    dialog._tick_countdown()  # 1
    dialog._tick_countdown()  # 0 → emits resume_confirmed
    assert confirmed == [True]


def test_workout_screen_has_free_ride_button():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    button_texts = {button.text() for button in screen.findChildren(QPushButton)}
    assert "Free Ride" in button_texts


def test_free_ride_button_emits_free_ride_requested():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    received = []
    screen.free_ride_requested.connect(lambda: received.append(True))
    screen.free_ride_button.click()

    assert received == [True]


def test_metric_tile_does_not_show_editor_when_editing_disabled():
    _get_or_create_qapp()
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    screen = WorkoutScreen(settings=AppSettings())
    tile = screen.target_power_tile

    assert tile.editing_enabled is False
    QTest.mouseDClick(tile, Qt.LeftButton)

    assert tile._edit_input is None


def test_metric_tile_shows_inline_editor_on_double_click_when_enabled():
    _get_or_create_qapp()
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit

    screen = WorkoutScreen(settings=AppSettings())
    screen.set_free_ride_mode(True)
    tile = screen.target_power_tile

    assert tile.editing_enabled is True
    QTest.mouseDClick(tile, Qt.LeftButton)

    assert tile._edit_input is not None
    assert isinstance(tile._edit_input, QLineEdit)
    assert tile.value_label.isHidden()


def test_erg_target_entered_emitted_on_valid_watt_input():
    _get_or_create_qapp()
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    screen = WorkoutScreen(settings=AppSettings())
    screen.set_free_ride_mode(True)

    received = []
    screen.erg_target_entered.connect(lambda w: received.append(w))

    tile = screen.target_power_tile
    QTest.mouseDClick(tile, Qt.LeftButton)
    tile._edit_input.setText("250")
    tile._edit_input.returnPressed.emit()

    assert received == [250]
    assert tile._edit_input is None  # editor closed


def test_erg_target_entered_not_emitted_on_non_integer_input():
    _get_or_create_qapp()
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    screen = WorkoutScreen(settings=AppSettings())
    screen.set_free_ride_mode(True)

    received = []
    screen.erg_target_entered.connect(lambda w: received.append(w))

    tile = screen.target_power_tile
    QTest.mouseDClick(tile, Qt.LeftButton)
    tile._edit_input.setText("abc")
    tile._edit_input.returnPressed.emit()

    assert received == []


def test_metric_tile_escape_cancels_editor():
    _get_or_create_qapp()
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    screen = WorkoutScreen(settings=AppSettings())
    screen.set_free_ride_mode(True)

    tile = screen.target_power_tile
    QTest.mouseDClick(tile, Qt.LeftButton)
    assert tile._edit_input is not None

    QTest.keyClick(tile._edit_input, Qt.Key_Escape)

    assert tile._edit_input is None
    assert tile.value_label.isHidden() is False


def test_set_free_ride_mode_false_disables_editing():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings())

    screen.set_free_ride_mode(True)
    assert screen.target_power_tile.editing_enabled is True

    screen.set_free_ride_mode(False)
    assert screen.target_power_tile.editing_enabled is False
