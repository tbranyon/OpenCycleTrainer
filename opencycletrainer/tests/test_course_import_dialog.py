from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from opencycletrainer.core.course_model import Course, CoursePoint
from opencycletrainer.storage.settings import DISPLAY_UNITS_IMPERIAL, DISPLAY_UNITS_METRIC
from opencycletrainer.ui.course_import_dialog import (
    CourseImportDialog,
    CourseLapDialog,
    CourseSplitDialog,
)

_METERS_PER_MILE = 1609.344


def _qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _course() -> Course:
    """A 10 mile loop that climbs 100 m over its first 5 miles, then descends back."""
    return Course(
        name="River Road",
        points=(
            CoursePoint(distance_m=0.0, elevation_m=100.0),
            CoursePoint(distance_m=5 * _METERS_PER_MILE, elevation_m=200.0),
            CoursePoint(distance_m=10 * _METERS_PER_MILE, elevation_m=100.0),
        ),
    )


class _SubDialogDriver:
    """Stands in for exec() on the Split/Lap dialogs: fills them in, then clicks a button."""

    def __init__(self, fill=None, button: str = "ride_button") -> None:
        self.fill = fill
        self.button = button
        self.shown: list[QDialog] = []

    def __call__(self, dialog: QDialog) -> int:
        self.shown.append(dialog)
        if self.fill is not None:
            self.fill(dialog)
        getattr(dialog, self.button).click()
        return dialog.result()


def _dialog(units: str = DISPLAY_UNITS_IMPERIAL, driver=None) -> CourseImportDialog:
    _qapp()
    return CourseImportDialog(
        _course(),
        units=units,
        exec_sub_dialog=driver if driver is not None else _SubDialogDriver(),
    )


# ── Import dialog ─────────────────────────────────────────────────────────────

def test_import_dialog_shows_the_route_title_centred():
    dialog = _dialog()

    assert dialog.title_label.text() == "River Road"
    assert dialog.title_label.alignment() & Qt.AlignHCenter


def test_import_dialog_shows_distance_and_elevation_gain_in_display_units():
    dialog = _dialog(units=DISPLAY_UNITS_IMPERIAL)

    assert "10.00 mi" in dialog.distance_label.text()
    assert "328 ft" in dialog.elevation_gain_label.text()


def test_import_dialog_shows_metric_stats_with_metric_units():
    dialog = _dialog(units=DISPLAY_UNITS_METRIC)

    assert "16.09 km" in dialog.distance_label.text()
    assert "100 m" in dialog.elevation_gain_label.text()


def test_import_dialog_offers_ride_split_and_lap():
    dialog = _dialog()

    assert dialog.ride_button.text() == "Ride"
    assert dialog.split_button.text() == "Split"
    assert dialog.lap_button.text() == "Lap"


def test_ride_accepts_the_full_course():
    dialog = _dialog()

    dialog.ride_button.click()

    assert dialog.result() == QDialog.Accepted
    assert dialog.chosen_course == _course()


def test_closing_the_import_dialog_chooses_nothing():
    dialog = _dialog()

    dialog.reject()

    assert dialog.chosen_course is None


# ── Split ─────────────────────────────────────────────────────────────────────

def _fill_split(start: str, end: str):
    def fill(dialog: CourseSplitDialog) -> None:
        dialog.start_edit.setText(start)
        dialog.end_edit.setText(end)

    return fill


def test_split_opens_a_dialog_with_ride_and_cancel():
    driver = _SubDialogDriver(button="cancel_button")
    dialog = _dialog(driver=driver)

    dialog.split_button.click()

    split = driver.shown[0]
    assert isinstance(split, CourseSplitDialog)
    assert split.ride_button.text() == "Ride"
    assert split.cancel_button.text() == "Cancel"


def test_split_ride_trims_the_course_to_the_chosen_miles():
    dialog = _dialog(driver=_SubDialogDriver(fill=_fill_split("2", "7.5")))

    dialog.split_button.click()

    assert dialog.result() == QDialog.Accepted
    trimmed = dialog.chosen_course
    assert trimmed.total_distance_m == pytest.approx(5.5 * _METERS_PER_MILE)
    assert trimmed.elevation_at(0.0) == pytest.approx(_course().elevation_at(2 * _METERS_PER_MILE))


def test_split_with_blank_start_begins_at_the_start_of_the_route():
    dialog = _dialog(driver=_SubDialogDriver(fill=_fill_split("", "4")))

    dialog.split_button.click()

    assert dialog.chosen_course.total_distance_m == pytest.approx(4 * _METERS_PER_MILE)
    assert dialog.chosen_course.elevation_at(0.0) == pytest.approx(100.0)


def test_split_with_blank_end_runs_to_the_end_of_the_route():
    dialog = _dialog(driver=_SubDialogDriver(fill=_fill_split("6", "")))

    dialog.split_button.click()

    assert dialog.chosen_course.total_distance_m == pytest.approx(4 * _METERS_PER_MILE)


def test_split_uses_kilometres_with_metric_units():
    dialog = _dialog(units=DISPLAY_UNITS_METRIC, driver=_SubDialogDriver(fill=_fill_split("1", "3")))

    dialog.split_button.click()

    assert dialog.chosen_course.total_distance_m == pytest.approx(2000.0)


def test_split_cancel_returns_to_the_import_dialog_without_choosing():
    dialog = _dialog(driver=_SubDialogDriver(fill=_fill_split("2", "4"), button="cancel_button"))

    dialog.split_button.click()

    assert dialog.chosen_course is None
    assert dialog.result() != QDialog.Accepted


def test_split_names_the_course_after_the_chosen_stretch():
    dialog = _dialog(driver=_SubDialogDriver(fill=_fill_split("2", "7.5")))

    dialog.split_button.click()

    assert dialog.chosen_course.name.startswith("River Road")
    assert "2" in dialog.chosen_course.name
    assert "7.5" in dialog.chosen_course.name


@pytest.mark.parametrize("start, end", [("5", "3"), ("4", "4"), ("12", ""), ("", "11")])
def test_split_cannot_ride_an_invalid_range(start, end):
    _qapp()
    split = CourseSplitDialog(_course(), units=DISPLAY_UNITS_IMPERIAL)

    split.start_edit.setText(start)
    split.end_edit.setText(end)

    assert not split.ride_button.isEnabled()
    assert split.error_label.text()


def test_split_with_both_fields_blank_can_ride_the_whole_route():
    _qapp()
    split = CourseSplitDialog(_course(), units=DISPLAY_UNITS_IMPERIAL)

    assert split.ride_button.isEnabled()
    assert not split.error_label.text()


# ── Lap ───────────────────────────────────────────────────────────────────────

def _set_laps(count: int):
    def fill(dialog: CourseLapDialog) -> None:
        dialog.lap_count_spin.setValue(count)

    return fill


def test_lap_opens_a_dialog_with_ride_and_cancel():
    driver = _SubDialogDriver(button="cancel_button")
    dialog = _dialog(driver=driver)

    dialog.lap_button.click()

    lap = driver.shown[0]
    assert isinstance(lap, CourseLapDialog)
    assert lap.ride_button.text() == "Ride"
    assert lap.cancel_button.text() == "Cancel"


def test_lap_ride_repeats_the_course():
    dialog = _dialog(driver=_SubDialogDriver(fill=_set_laps(3)))

    dialog.lap_button.click()

    assert dialog.result() == QDialog.Accepted
    assert dialog.chosen_course.total_ascent_m == pytest.approx(3 * _course().total_ascent_m)
    assert "3 laps" in dialog.chosen_course.name


def test_lap_cancel_returns_to_the_import_dialog_without_choosing():
    dialog = _dialog(driver=_SubDialogDriver(fill=_set_laps(3), button="cancel_button"))

    dialog.lap_button.click()

    assert dialog.chosen_course is None
    assert dialog.result() != QDialog.Accepted


def test_lap_count_is_at_least_one():
    _qapp()
    lap = CourseLapDialog(_course(), units=DISPLAY_UNITS_IMPERIAL)

    lap.lap_count_spin.setValue(0)

    assert lap.lap_count_spin.value() == 1
