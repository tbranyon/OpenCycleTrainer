from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import numpy as np

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
import pyqtgraph as pg

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.mrc_parser import inject_category_into_mrc_text, parse_mrc_file
from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.core.workout_model import Workout
from opencycletrainer.ui.workout_chart import (
    _TimeAxisItem,
    _configure_y_axis,
    build_target_series,
    compute_y_max,
    _make_target_item,
)
from opencycletrainer.ui.workout_summary_dialog import compute_tss


# ── Module-level stat functions ───────────────────────────────────────────────

def _compute_target_kj(workout: Workout) -> float:
    """Total work from target profile.

    kJ = sum((start_w + end_w) / 2 * duration_s / 1000) per interval.
    """
    total = 0.0
    for iv in workout.intervals:
        avg_w = (iv.start_target_watts + iv.end_target_watts) / 2.0
        total += avg_w * iv.duration_seconds / 1000.0
    return total


def _compute_target_np(workout: Workout) -> int:
    """Coggan NP from the target power profile.

    1. Expand intervals to 1-second samples (np.linspace for ramps).
    2. 30-second rolling mean.
    3. mean(rolling^4)^0.25, rounded to int.
    """
    segments = []
    for iv in workout.intervals:
        powers = np.linspace(
            iv.start_target_watts, iv.end_target_watts, iv.duration_seconds
        )
        segments.append(powers)
    if not segments:
        return 0
    power_array = np.concatenate(segments)
    kernel_size = 30
    if len(power_array) < kernel_size:
        return int(round(float(np.mean(power_array))))
    rolling = np.convolve(
        power_array, np.ones(kernel_size) / kernel_size, mode="valid"
    )
    return int(round(float(np.mean(rolling**4) ** 0.25)))


# ── WorkoutPreviewPane ────────────────────────────────────────────────────────

class WorkoutPreviewPane(QWidget):
    """Right-side preview pane showing a mini chart and estimated stats for the selected workout."""

    def __init__(self, ftp_getter: Callable[[], int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ftp_getter = ftp_getter

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._name_label = QLabel("Select a workout to preview", self)
        self._name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._name_label)

        self._plot = pg.PlotWidget(axisItems={"bottom": _TimeAxisItem("bottom")}, parent=self)
        self._plot.setFixedHeight(200)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.getViewBox().disableAutoRange()
        self._target_item = _make_target_item()
        self._plot.addItem(self._target_item)
        layout.addWidget(self._plot)

        stats_layout = QGridLayout()
        stats_layout.addWidget(QLabel("Duration"), 0, 0, Qt.AlignCenter)
        stats_layout.addWidget(QLabel("Target NP"), 0, 1, Qt.AlignCenter)
        stats_layout.addWidget(QLabel("kJ"), 0, 2, Qt.AlignCenter)
        stats_layout.addWidget(QLabel("TSS"), 0, 3, Qt.AlignCenter)

        self._duration_label = QLabel("—", self)
        self._np_label = QLabel("—", self)
        self._kj_label = QLabel("—", self)
        self._tss_label = QLabel("—", self)

        for col, label in enumerate(
            (self._duration_label, self._np_label, self._kj_label, self._tss_label)
        ):
            label.setAlignment(Qt.AlignCenter)
            stats_layout.addWidget(label, 1, col)

        layout.addLayout(stats_layout)
        layout.addStretch()

    def clear(self) -> None:
        """Reset to placeholder state."""
        self._name_label.setText("Select a workout to preview")
        self._target_item.setData([], [])
        self._duration_label.setText("—")
        self._np_label.setText("—")
        self._kj_label.setText("—")
        self._tss_label.setText("—")

    def load(self, path: Path) -> None:
        """Parse MRC at path using current FTP, populate chart and stats."""
        try:
            ftp = self._ftp_getter()
            workout = parse_mrc_file(path, ftp_watts=ftp)
        except Exception:
            self.clear()
            return

        self._name_label.setText(workout.name)

        t, w = build_target_series(workout)
        self._target_item.setData(t, w)

        y_max = compute_y_max(workout, ftp)
        _configure_y_axis(self._plot, y_max)
        self._plot.setXRange(0.0, float(workout.total_duration_seconds), padding=0)

        self._duration_label.setText(_format_duration(workout.total_duration_seconds))

        np_w = _compute_target_np(workout)
        self._np_label.setText(f"{np_w} W")

        kj = _compute_target_kj(workout)
        self._kj_label.setText(f"{int(kj)} kJ")

        tss = compute_tss(np_w, ftp, float(workout.total_duration_seconds))
        self._tss_label.setText(f"{int(tss)}" if tss is not None else "—")


# ── _CategoryDialog ───────────────────────────────────────────────────────────

class _CategoryDialog(QDialog):
    """QComboBox listing known categories plus an 'Add new...' option.

    Selecting 'Add new...' reveals a QLineEdit for custom text.
    """

    _ADD_NEW = "Add new..."

    def __init__(
        self,
        existing_categories: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose Category")

        layout = QVBoxLayout(self)

        self.combo = QComboBox(self)
        self.combo.addItem("")  # blank = no category
        for cat in existing_categories:
            self.combo.addItem(cat)
        self.combo.addItem(self._ADD_NEW)
        self.combo.currentTextChanged.connect(self._on_combo_changed)
        layout.addWidget(self.combo)

        self.line_edit = QLineEdit(self)
        self.line_edit.setPlaceholderText("Enter new category…")
        self.line_edit.hide()
        layout.addWidget(self.line_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_combo_changed(self, text: str) -> None:
        self.line_edit.setVisible(text == self._ADD_NEW)

    def selected_category(self) -> str:
        """Returns chosen category string, or '' if none selected."""
        if self.combo.currentText() == self._ADD_NEW:
            return self.line_edit.text().strip()
        return self.combo.currentText()


# ── WorkoutLibraryScreen ──────────────────────────────────────────────────────

class WorkoutLibraryScreen(QWidget):
    """Tab displaying the workout library with search, sort, category filter, and preview pane."""

    workout_selected = Signal(Path)

    def __init__(
        self,
        library: WorkoutLibrary,
        ftp_getter: Callable[[], int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._ftp_getter = ftp_getter
        self._sort_column = 1  # default: sort by name (col 1)
        self._sort_order = Qt.AscendingOrder

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        self._build_toolbar(root_layout)
        self._build_content(root_layout)
        self._refresh_category_combo()
        self._populate_table()

    def _build_toolbar(self, root_layout: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search by name…")
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_input, stretch=1)

        self.category_combo = QComboBox(self)
        self.category_combo.currentIndexChanged.connect(self._on_category_filter_changed)
        toolbar.addWidget(self.category_combo)

        self.add_button = QPushButton("Add to Library", self)
        self.add_button.clicked.connect(self._on_add_clicked)
        toolbar.addWidget(self.add_button)

        root_layout.addLayout(toolbar)

    def _build_content(self, root_layout: QVBoxLayout) -> None:
        splitter = QSplitter(Qt.Horizontal, self)

        # Left: table
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._build_table(left_layout)
        splitter.addWidget(left)

        # Right: preview pane
        self._preview_pane = WorkoutPreviewPane(ftp_getter=self._ftp_getter, parent=splitter)
        splitter.addWidget(self._preview_pane)
        splitter.setSizes([600, 400])

        root_layout.addWidget(splitter, stretch=1)

    def _build_table(self, layout: QVBoxLayout) -> None:
        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Category", "Name", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.cellClicked.connect(self._on_row_single_clicked)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

    def _refresh_category_combo(self) -> None:
        """Rebuild category combo from unique non-empty categories in library."""
        cats = sorted({e.category for e in self._library.entries if e.category})
        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All")
        for cat in cats:
            self.category_combo.addItem(cat)
        # Restore previous selection if still present
        idx = self.category_combo.findText(current)
        self.category_combo.setCurrentIndex(max(0, idx))
        self.category_combo.blockSignals(False)

    def _populate_table(self) -> None:
        """Rebuild table rows from library entries, applying current sort and filters."""
        filter_text = self.search_input.text().lower() if hasattr(self, "search_input") else ""
        cat_filter = (
            self.category_combo.currentText()
            if hasattr(self, "category_combo")
            else "All"
        )

        entries = [
            e for e in self._library.entries
            if filter_text in e.name.lower()
            and (cat_filter == "All" or e.category == cat_filter)
        ]

        reverse = self._sort_order == Qt.DescendingOrder
        if self._sort_column == 0:
            entries.sort(key=lambda e: e.category.lower(), reverse=reverse)
        elif self._sort_column == 2:
            entries.sort(key=lambda e: e.duration_seconds, reverse=reverse)
        else:  # column 1 = name
            entries.sort(key=lambda e: e.name.lower(), reverse=reverse)

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            cat_item = QTableWidgetItem(entry.category)
            name_item = QTableWidgetItem(entry.name)
            name_item.setData(Qt.UserRole, entry.path)
            duration_item = QTableWidgetItem(_format_duration(entry.duration_seconds))
            duration_item.setData(Qt.UserRole + 1, entry.duration_seconds)
            self.table.setItem(row, 0, cat_item)
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, duration_item)

    def _on_header_clicked(self, logical_index: int) -> None:
        if self._sort_column == logical_index:
            self._sort_order = (
                Qt.DescendingOrder
                if self._sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
        else:
            self._sort_column = logical_index
            self._sort_order = Qt.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(self._sort_column, self._sort_order)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self._populate_table()

    def _on_search_changed(self, text: str) -> None:  # noqa: ARG002
        self._populate_table()

    def _on_category_filter_changed(self, index: int) -> None:  # noqa: ARG002
        self._populate_table()

    def _on_add_clicked(self) -> None:
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Add Workout to Library",
            str(Path.home()),
            "MRC Files (*.mrc)",
        )
        if not file_path_str:
            return
        source_path = Path(file_path_str)

        existing_cats = [
            self.category_combo.itemText(i)
            for i in range(self.category_combo.count())
            if self.category_combo.itemText(i) not in ("All",)
        ]
        dialog = _CategoryDialog(existing_cats, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return

        cat = dialog.selected_category()
        if cat:
            text = source_path.read_text(encoding="utf-8")
            text = inject_category_into_mrc_text(text, cat)
            self._library.add_workout_from_text(text, source_path.name)
        else:
            self._library.add_workout(source_path)

        self._refresh_category_combo()
        self._populate_table()

    def _on_row_single_clicked(self, row: int, column: int) -> None:  # noqa: ARG002
        item = self.table.item(row, 1)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if isinstance(path, Path):
            self._preview_pane.load(path)

    def _on_row_double_clicked(self, row: int, column: int) -> None:  # noqa: ARG002
        item = self.table.item(row, 1)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if isinstance(path, Path):
            self.workout_selected.emit(path)

    def refresh(self) -> None:
        """Rescan library directories and repopulate the table."""
        self._library.refresh()
        self._refresh_category_combo()
        self._populate_table()


def _format_duration(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02}:{secs:02}"
