from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.course_model import Course
from opencycletrainer.storage.settings import DISPLAY_UNITS_METRIC

from .ride_format import (
    distance_unit_label,
    format_distance,
    format_elevation,
    meters_per_distance_unit,
)

_TITLE_FONT_SIZE_DELTA = 6
_DIALOG_MIN_WIDTH = 360
_SUB_DIALOG_MIN_WIDTH = 260
_MIN_LAPS = 1
_MAX_LAPS = 99
_DEFAULT_LAPS = 2
_DISTANCE_DECIMALS = 2
_DISTANCE_TOLERANCE_UNITS = 0.5 * 10 ** -_DISTANCE_DECIMALS
"""An end typed as the route's displayed length is accepted even if the true length is a hair less."""
_DISTANCE_PATTERN = r"^\d*\.?\d*$"
_ERROR_STYLE = "color: #c62828;"

# Runs a Split or Lap dialog modally and returns its QDialog result code.
SubDialogRunner = Callable[[QDialog], int]


def choose_course_to_ride(
    course: Course, units: str, parent: QWidget | None = None
) -> Course | None:
    """Ask how to ride *course* (whole, part of it, or as laps); None if the rider backs out."""
    dialog = CourseImportDialog(course, units=units, parent=parent)
    dialog.exec()
    return dialog.chosen_course


class CourseImportDialog(QDialog):
    """Shows a course's title and stats and lets the rider ride it whole, split it, or lap it."""

    def __init__(
        self,
        course: Course,
        *,
        units: str = DISPLAY_UNITS_METRIC,
        exec_sub_dialog: SubDialogRunner | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._course = course
        self._units = units
        self._exec_sub_dialog = exec_sub_dialog if exec_sub_dialog is not None else QDialog.exec
        self._chosen_course: Course | None = None
        self.setWindowTitle("Load Course")
        self.setModal(True)
        self.setMinimumWidth(_DIALOG_MIN_WIDTH)

        self.title_label = QLabel(course.name)
        self.title_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.title_label.setWordWrap(True)
        title_font = QFont(self.title_label.font())
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + _TITLE_FONT_SIZE_DELTA)
        self.title_label.setFont(title_font)

        self.distance_label = QLabel(f"Distance: {format_distance(course.total_distance_m, units)}")
        self.elevation_gain_label = QLabel(
            f"Elevation gain: {format_elevation(course.total_ascent_m, units)}"
        )
        stats_column = QVBoxLayout()
        stats_column.addWidget(self.distance_label)
        stats_column.addWidget(self.elevation_gain_label)
        stats_column.addStretch(1)

        self.ride_button = QPushButton("Ride")
        self.split_button = QPushButton("Split")
        self.lap_button = QPushButton("Lap")
        self.ride_button.setDefault(True)
        self.ride_button.clicked.connect(lambda: self._choose(self._course))
        self.split_button.clicked.connect(self._on_split)
        self.lap_button.clicked.connect(self._on_lap)
        button_column = QVBoxLayout()
        for button in (self.ride_button, self.split_button, self.lap_button):
            button_column.addWidget(button)
        button_column.addStretch(1)

        columns = QHBoxLayout()
        columns.addLayout(stats_column, 1)
        columns.addLayout(button_column)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addLayout(columns)

    @property
    def chosen_course(self) -> Course | None:
        """The course to ride as the rider chose it, or None if nothing was chosen."""
        return self._chosen_course

    def _on_split(self) -> None:
        self._run_sub_dialog(CourseSplitDialog(self._course, units=self._units, parent=self))

    def _on_lap(self) -> None:
        self._run_sub_dialog(CourseLapDialog(self._course, units=self._units, parent=self))

    def _run_sub_dialog(self, dialog: CourseSplitDialog | CourseLapDialog) -> None:
        """Run a Split or Lap dialog; Ride there loads its course, Cancel returns here."""
        if self._exec_sub_dialog(dialog) == QDialog.Accepted:
            self._choose(dialog.result_course())

    def _choose(self, course: Course) -> None:
        self._chosen_course = course
        self.accept()


class CourseSplitDialog(QDialog):
    """Asks for the start and end distance of the stretch of a course to ride."""

    def __init__(
        self,
        course: Course,
        *,
        units: str = DISPLAY_UNITS_METRIC,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._course = course
        self._units = units
        self._unit_m = meters_per_distance_unit(units)
        unit_label = distance_unit_label(units)
        self.setWindowTitle("Split Course")
        self.setModal(True)
        self.setMinimumWidth(_SUB_DIALOG_MIN_WIDTH)

        validator = QRegularExpressionValidator(QRegularExpression(_DISTANCE_PATTERN), self)
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText(f"{0:.{_DISTANCE_DECIMALS}f}")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText(f"{self._course_length_units():.{_DISTANCE_DECIMALS}f}")
        for edit in (self.start_edit, self.end_edit):
            edit.setValidator(validator)
            edit.textChanged.connect(self._validate)

        form = QFormLayout()
        form.addRow(f"Start ({unit_label})", self.start_edit)
        form.addRow(f"End ({unit_label})", self.end_edit)

        hint = QLabel("Leave blank to start or finish at the end of the route.")
        hint.setWordWrap(True)
        self.error_label = QLabel()
        self.error_label.setStyleSheet(_ERROR_STYLE)
        self.error_label.setWordWrap(True)

        self.ride_button = QPushButton("Ride")
        self.ride_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.ride_button.clicked.connect(self._on_ride)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.ride_button)
        button_row.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.error_label)
        layout.addLayout(button_row)
        self._validate()

    def result_course(self) -> Course:
        """The chosen stretch of the course, named after the distances it spans."""
        start_units, end_units = self._entered_range()
        start_m = None if start_units is None else start_units * self._unit_m
        end_m = None if end_units is None else end_units * self._unit_m
        start_text = _format_mark(start_units if start_units is not None else 0.0)
        end_text = _format_mark(end_units if end_units is not None else self._course_length_units())
        name = f"{self._course.name} ({start_text}–{end_text} {distance_unit_label(self._units)})"
        return self._course.section(start_m, end_m, name=name)

    def _on_ride(self) -> None:
        if self._validate():
            self.accept()

    def _validate(self) -> bool:
        """Show why the entered range cannot be ridden, and enable Ride only when it can."""
        error = self._range_error()
        self.error_label.setText(error)
        self.ride_button.setEnabled(not error)
        return not error

    def _range_error(self) -> str:
        try:
            start, end = self._entered_range()
        except ValueError:
            return "Enter distances as numbers."
        length = self._course_length_units()
        limit = length + _DISTANCE_TOLERANCE_UNITS
        length_text = format_distance(self._course.total_distance_m, self._units)
        if start is not None and start >= limit:
            return f"Start is past the end of the route ({length_text})."
        if end is not None and end > limit:
            return f"End is past the end of the route ({length_text})."
        if (start or 0.0) >= (length if end is None else end):
            return "End must come after start."
        return ""

    def _entered_range(self) -> tuple[float | None, float | None]:
        """Return the typed start and end in display units; None where left blank."""
        return _parse_distance(self.start_edit.text()), _parse_distance(self.end_edit.text())

    def _course_length_units(self) -> float:
        return self._course.total_distance_m / self._unit_m


class CourseLapDialog(QDialog):
    """Asks how many times in a row to ride a course."""

    def __init__(
        self,
        course: Course,
        *,
        units: str = DISPLAY_UNITS_METRIC,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._course = course
        self._units = units
        self.setWindowTitle("Lap Course")
        self.setModal(True)
        self.setMinimumWidth(_SUB_DIALOG_MIN_WIDTH)

        self.lap_count_spin = QSpinBox()
        self.lap_count_spin.setRange(_MIN_LAPS, _MAX_LAPS)
        self.lap_count_spin.setValue(_DEFAULT_LAPS)
        self.total_label = QLabel()
        self.lap_count_spin.valueChanged.connect(self._update_total)

        form = QFormLayout()
        form.addRow("Laps", self.lap_count_spin)
        form.addRow("Total distance", self.total_label)

        self.ride_button = QPushButton("Ride")
        self.ride_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.ride_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.ride_button)
        button_row.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(button_row)
        self._update_total()

    def result_course(self) -> Course:
        """The course repeated for the chosen number of laps."""
        count = self.lap_count_spin.value()
        suffix = "lap" if count == 1 else "laps"
        return self._course.laps(count, name=f"{self._course.name} ({count} {suffix})")

    def _update_total(self) -> None:
        laps = self._course.laps(self.lap_count_spin.value())
        self.total_label.setText(format_distance(laps.total_distance_m, self._units))


def _parse_distance(text: str) -> float | None:
    """Return a typed distance as a number, or None if the field is blank."""
    stripped = text.strip()
    if not stripped or stripped == ".":
        return None
    return float(stripped)


def _format_mark(value: float) -> str:
    """Format a distance mark for a course name, without trailing zeros (e.g. ``7.5``)."""
    return f"{round(value, _DISTANCE_DECIMALS):g}"
