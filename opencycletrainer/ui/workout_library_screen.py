from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.workout_library import WorkoutLibrary


class WorkoutLibraryScreen(QWidget):
    """Tab displaying the workout library with search, sort, and load capabilities."""

    workout_selected = Signal(Path)

    def __init__(
        self,
        library: WorkoutLibrary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._sort_column = 0
        self._sort_order = Qt.AscendingOrder

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        self._build_toolbar(root_layout)
        self._build_table(root_layout)
        self._populate_table()

    def _build_toolbar(self, root_layout: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search by name…")
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_input, stretch=1)

        self.add_button = QPushButton("Add to Library", self)
        self.add_button.clicked.connect(self._on_add_clicked)
        toolbar.addWidget(self.add_button)

        root_layout.addLayout(toolbar)

    def _build_table(self, root_layout: QVBoxLayout) -> None:
        self.table = QTableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Name", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(False)  # Manual sort to preserve row data
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        root_layout.addWidget(self.table, stretch=1)

    def _populate_table(self) -> None:
        """Rebuild table rows from library entries, applying current sort and filter."""
        filter_text = self.search_input.text().lower() if hasattr(self, "search_input") else ""
        entries = [e for e in self._library.entries if filter_text in e.name.lower()]

        reverse = self._sort_order == Qt.DescendingOrder
        if self._sort_column == 0:
            entries.sort(key=lambda e: e.name.lower(), reverse=reverse)
        else:
            entries.sort(key=lambda e: e.duration_seconds, reverse=reverse)

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            name_item = QTableWidgetItem(entry.name)
            name_item.setData(Qt.UserRole, entry.path)
            duration_item = QTableWidgetItem(_format_duration(entry.duration_seconds))
            duration_item.setData(Qt.UserRole + 1, entry.duration_seconds)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, duration_item)

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

    def _on_add_clicked(self) -> None:
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Add Workout to Library",
            str(Path.home()),
            "MRC Files (*.mrc)",
        )
        if not file_path_str:
            return
        self._library.add_workout(Path(file_path_str))
        self._populate_table()

    def _on_row_double_clicked(self, row: int, column: int) -> None:  # noqa: ARG002
        item = self.table.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if isinstance(path, Path):
            self.workout_selected.emit(path)

    def refresh(self) -> None:
        """Rescan library directories and repopulate the table."""
        self._library.refresh()
        self._populate_table()


def _format_duration(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02}:{secs:02}"
