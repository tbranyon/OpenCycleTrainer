from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
import pyqtgraph as pg

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.builder_parser import parse_builder_text
from opencycletrainer.core.mrc_exporter import workout_to_mrc_text
from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.core.zwo_exporter import workout_to_zwo_text
from opencycletrainer.ui.workout_chart import (
    _TimeAxisItem,
    _configure_y_axis,
    _make_target_item,
    build_target_series,
    compute_y_max,
)

_INSTRUCTIONS = """\
  - 10m 50%              steady state (% FTP)          - 5m free          free ride
  - 5m ramp 60-90%       ramp between two % values     - 3x(4m 110%, 2m 55%)  repeat
  - 2m 300W              absolute watts                 # this line is a comment
  Duration: Nm = minutes, Ns = seconds\
"""

_DEBOUNCE_MS = 300


def _fixed_font() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(10)
    return font


def _sanitize_filename(name: str) -> str:
    """Replace characters that are invalid in filenames with underscores."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")


class WorkoutBuilderScreen(QWidget):
    """Builder tab: compose a workout from text, preview it, then save/load."""

    workout_saved = Signal()
    workout_load_requested = Signal(Path)

    def __init__(
        self,
        library: WorkoutLibrary,
        ftp_getter: Callable[[], int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._ftp_getter = ftp_getter
        self._export_auto_checked = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._update_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self._build_header(root)
        self._build_instructions(root)
        self._build_text_area(root)
        self._build_error_label(root)
        self._build_graph(root)
        self._build_action_row(root)

    # ── Layout builders ───────────────────────────────────────────────────────

    def _build_header(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("Workout name…")
        row.addWidget(self._name_edit, stretch=2)
        row.addSpacing(16)
        row.addWidget(QLabel("Category:"))
        self._category_edit = QLineEdit(self)
        self._category_edit.setPlaceholderText("Optional…")
        row.addWidget(self._category_edit, stretch=1)
        layout.addLayout(row)

    def _build_instructions(self, layout: QVBoxLayout) -> None:
        label = QLabel(_INSTRUCTIONS, self)
        label.setFont(_fixed_font())
        label.setWordWrap(False)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setStyleSheet(
            "background: rgba(128,128,128,20); padding: 6px 8px;"
            " border-radius: 4px;"
        )
        layout.addWidget(label)

    def _build_text_area(self, layout: QVBoxLayout) -> None:
        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setFont(_fixed_font())
        self._text_edit.setPlaceholderText(
            "- 10m 50%\n- 20m 95%\n- 5m 50%"
        )
        self._text_edit.setMinimumHeight(150)
        self._text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._text_edit, stretch=2)

    def _build_error_label(self, layout: QVBoxLayout) -> None:
        self._error_label = QLabel(self)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #dc2626;")
        self._error_label.hide()
        layout.addWidget(self._error_label)

    def _build_graph(self, layout: QVBoxLayout) -> None:
        self._plot = pg.PlotWidget(
            axisItems={"bottom": _TimeAxisItem("bottom")},
            parent=self,
        )
        self._plot.setMinimumHeight(180)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.getViewBox().disableAutoRange()
        self._plot.getAxis("left").setLabel("W")
        self._plot.showGrid(x=False, y=True, alpha=0.2)
        self._target_item = _make_target_item()
        self._plot.addItem(self._target_item)
        layout.addWidget(self._plot, stretch=3)

    def _build_action_row(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()

        self._cb_export = QCheckBox("Export to File", self)
        self._cb_library = QCheckBox("Add to Library", self)
        self._cb_load = QCheckBox("Load Workout", self)
        self._finish_btn = QPushButton("Finish", self)
        self._finish_btn.setEnabled(False)

        for cb in (self._cb_export, self._cb_library, self._cb_load):
            cb.toggled.connect(self._on_any_checkbox_toggled)
            row.addWidget(cb)

        self._cb_library.toggled.connect(self._on_library_toggled)

        row.addStretch()
        row.addWidget(self._finish_btn)
        layout.addLayout(row)

        self._finish_btn.clicked.connect(self._on_finish)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        self._debounce.start()

    def _on_any_checkbox_toggled(self, _checked: bool) -> None:
        self._finish_btn.setEnabled(
            any(cb.isChecked() for cb in (self._cb_export, self._cb_library, self._cb_load))
        )

    def _on_library_toggled(self, checked: bool) -> None:
        if checked:
            self._export_auto_checked = not self._cb_export.isChecked()
            self._cb_export.setChecked(True)
            self._cb_export.setEnabled(False)
        else:
            self._cb_export.setEnabled(True)
            if self._export_auto_checked:
                self._cb_export.setChecked(False)
                self._export_auto_checked = False

    def _update_preview(self) -> None:
        name = self._name_edit.text().strip() or "Untitled"
        ftp = self._ftp_getter()
        workout, errors = parse_builder_text(self._text_edit.toPlainText(), ftp, name)

        if errors:
            shown = errors[:5]
            if len(errors) > 5:
                shown.append(f"… and {len(errors) - 5} more error(s)")
            self._error_label.setText("\n".join(shown))
            self._error_label.show()
        else:
            self._error_label.hide()

        if not workout.intervals:
            self._target_item.setData([], [])
            return

        t, w = build_target_series(workout)
        self._target_item.setData(t, w)
        y_max = compute_y_max(workout, ftp)
        _configure_y_axis(self._plot, y_max)
        self._plot.setXRange(0.0, float(workout.total_duration_seconds), padding=0)

    def _on_finish(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Required", "Please enter a workout name.")
            return

        ftp = self._ftp_getter()
        workout, _ = parse_builder_text(self._text_edit.toPlainText(), ftp, name)

        if not workout.intervals:
            QMessageBox.warning(self, "No Steps", "Enter at least one valid step before saving.")
            return

        category = self._category_edit.text().strip()
        has_free = any(iv.free_ride for iv in workout.intervals)
        ext = ".zwo" if has_free else ".mrc"
        file_text = (
            workout_to_zwo_text(workout, category)
            if has_free
            else workout_to_mrc_text(workout, category)
        )
        safe_name = _sanitize_filename(name) or "workout"
        filename = safe_name + ext

        saved_path: Path | None = None

        if self._cb_library.isChecked():
            try:
                entry = self._library.add_workout_from_text(file_text, filename)
                saved_path = entry.path
                self.workout_saved.emit()
            except Exception as exc:
                QMessageBox.critical(self, "Save Error", f"Could not add to library:\n{exc}")
                return

        elif self._cb_export.isChecked():
            filter_str = "ZWO Files (*.zwo)" if has_free else "MRC Files (*.mrc)"
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Export Workout", str(Path.home() / filename), filter_str
            )
            if not chosen:
                return
            chosen_path = Path(chosen)
            try:
                chosen_path.write_text(file_text, encoding="utf-8")
                saved_path = chosen_path
            except OSError as exc:
                QMessageBox.critical(self, "Save Error", f"Could not write file:\n{exc}")
                return

        elif self._cb_load.isChecked():
            # Load Workout checked alone: auto-save to user workouts dir so the
            # workout controller has a file path to load from.
            try:
                entry = self._library.add_workout_from_text(file_text, filename)
                saved_path = entry.path
                self.workout_saved.emit()
            except Exception as exc:
                QMessageBox.critical(self, "Save Error", f"Could not save workout:\n{exc}")
                return

        if self._cb_load.isChecked() and saved_path is not None:
            self.workout_load_requested.emit(saved_path)
