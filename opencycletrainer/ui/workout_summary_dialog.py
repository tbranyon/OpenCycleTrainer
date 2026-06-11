from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.power_history import compute_power_duration_curve

from .workout_chart import PowerDurationChartWidget

INTERVAL_PERCENT_COLOR_GREEN = QColor(76, 175, 80)
INTERVAL_PERCENT_COLOR_YELLOW = QColor(255, 193, 7)
INTERVAL_PERCENT_COLOR_RED = QColor(244, 67, 54)

DIALOG_MIN_WIDTH = 760
DIALOG_MIN_HEIGHT = 760


@dataclass(frozen=True)
class IntervalResult:
    """Per-interval performance snapshot captured when an interval completes."""

    interval_number: int
    duration_seconds: int
    target_watts: int | None
    target_percent_ftp: float | None
    avg_watts: int | None
    avg_hr: int | None
    skipped: bool = False


@dataclass(frozen=True)
class WorkoutSummary:
    """Snapshot of metrics collected over a completed workout."""

    elapsed_seconds: float
    kj: float
    normalized_power: int | None
    tss: float | None
    avg_hr: int | None
    interval_results: tuple[IntervalResult, ...] = ()
    workout_name: str = ""
    power_samples: tuple[tuple[float, int], ...] = ()


def compute_tss(
    np_watts: int | None,
    ftp_watts: int,
    elapsed_seconds: float,
) -> float | None:
    """Compute Training Stress Score (TSS).

    TSS = (duration_s × NP × IF) / (FTP × 3600) × 100, where IF = NP / FTP.
    Returns None when inputs are insufficient to compute a meaningful score.
    """
    if np_watts is None or ftp_watts <= 0 or elapsed_seconds <= 0:
        return None
    intensity_factor = np_watts / ftp_watts
    return (elapsed_seconds * np_watts * intensity_factor) / (ftp_watts * 3600.0) * 100.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _format_time(elapsed_seconds: float) -> str:
    secs = int(elapsed_seconds)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_kj(kj: float) -> str:
    return f"{int(kj)} kJ"


def _format_power(watts: int | None) -> str:
    return f"{watts} W" if watts is not None else "--"


def _format_tss(tss: float | None) -> str:
    return f"{int(tss)}" if tss is not None else "--"


def _format_hr(hr: int | None) -> str:
    return f"{hr} bpm" if hr is not None else "--"


def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _interval_percent_color(pct: int) -> QColor | None:
    if pct >= 95:
        return INTERVAL_PERCENT_COLOR_GREEN
    if pct >= 85:
        return INTERVAL_PERCENT_COLOR_YELLOW
    return INTERVAL_PERCENT_COLOR_RED


def _build_interval_table(results: tuple[IntervalResult, ...]) -> QTableWidget:
    headers = ["#", "Duration", "Target (W)", "Actual Avg (W)", "% of Target", "Avg HR"]
    table = QTableWidget(len(results), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    for row, result in enumerate(results):
        number_text = f"{result.interval_number} (Skipped)" if result.skipped else str(result.interval_number)
        table.setItem(row, 0, QTableWidgetItem(number_text))
        table.setItem(row, 1, QTableWidgetItem(_format_duration(result.duration_seconds)))

        if result.target_watts is None:
            table.setItem(row, 2, QTableWidgetItem("-"))
            pct_item = QTableWidgetItem("-")
            table.setItem(row, 4, pct_item)
        else:
            table.setItem(row, 2, QTableWidgetItem(str(result.target_watts)))
            if result.avg_watts is not None and result.target_watts > 0:
                pct = round(result.avg_watts / result.target_watts * 100)
                pct_item = QTableWidgetItem(f"{pct}%")
                color = _interval_percent_color(pct)
                pct_item.setBackground(color)
            else:
                pct_item = QTableWidgetItem("-")
            table.setItem(row, 4, pct_item)

        avg_w_text = str(result.avg_watts) if result.avg_watts is not None else "-"
        table.setItem(row, 3, QTableWidgetItem(avg_w_text))

        avg_hr_text = str(result.avg_hr) if result.avg_hr is not None else "-"
        table.setItem(row, 5, QTableWidgetItem(avg_hr_text))

        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                item.setTextAlignment(Qt.AlignCenter)

    return table


def _sans_font(base: QFont, *, bold: bool = False, size_delta: int = 0) -> QFont:
    font = QFont(base)
    font.setFamily("Arial")
    font.setBold(bold)
    if size_delta:
        font.setPointSize(max(6, font.pointSize() + size_delta))
    return font


class _SummaryTile(QWidget):
    """Borderless two-line tile: small title above a bold value."""

    def __init__(self, *, title: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        title_label = QLabel(title, self)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setFont(_sans_font(title_label.font()))
        layout.addWidget(title_label)

        self.value_label = QLabel(value, self)
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFont(_sans_font(self.value_label.font(), bold=True, size_delta=4))
        layout.addWidget(self.value_label)


# ---------------------------------------------------------------------------
# Public dialog
# ---------------------------------------------------------------------------


class WorkoutSummaryDialog(QDialog):
    """Modal summary screen displayed after a workout finishes or is stopped."""

    def __init__(self, summary: WorkoutSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workout Complete")
        self.setModal(True)
        self.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
        self.resize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)

        # Header
        header = QLabel("Great Job!", self)
        header.setAlignment(Qt.AlignCenter)
        header.setFont(_sans_font(header.font(), bold=True, size_delta=8))
        root.addWidget(header)

        # Activity name field
        name_row = QHBoxLayout()
        name_label = QLabel("Activity Name:", self)
        name_label.setFont(_sans_font(name_label.font()))
        self._name_field = QLineEdit(summary.workout_name, self)
        name_row.addWidget(name_label)
        name_row.addWidget(self._name_field)
        root.addLayout(name_row)

        # Metric tiles in a 3-column grid (row 0: Time, kJ, NP; row 1: TSS, Avg HR)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        tiles = [
            ("Time", _format_time(summary.elapsed_seconds)),
            ("kJ", _format_kj(summary.kj)),
            ("Normalized Power", _format_power(summary.normalized_power)),
            ("TSS", _format_tss(summary.tss)),
            ("Avg Heart Rate", _format_hr(summary.avg_hr)),
        ]
        for i, (title, value) in enumerate(tiles):
            tile = _SummaryTile(title=title, value=value, parent=self)
            grid.addWidget(tile, i // 3, i % 3)

        root.addLayout(grid)

        # Interval breakdown table (only shown when per-interval data is available)
        if summary.interval_results:
            breakdown_label = QLabel("Interval Breakdown", self)
            breakdown_label.setAlignment(Qt.AlignCenter)
            breakdown_label.setFont(_sans_font(breakdown_label.font(), bold=True))
            root.addWidget(breakdown_label)

            table = _build_interval_table(summary.interval_results)
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setWidget(table)
            scroll.setMaximumHeight(220)
            root.addWidget(scroll)

        # Power-duration curve (only shown when raw power samples are available)
        if summary.power_samples:
            curve_label = QLabel("Power Curve", self)
            curve_label.setAlignment(Qt.AlignCenter)
            curve_label.setFont(_sans_font(curve_label.font(), bold=True))
            root.addWidget(curve_label)

            chart = PowerDurationChartWidget(self)
            chart.setMinimumHeight(180)
            chart.set_curve(compute_power_duration_curve(list(summary.power_samples)))
            root.addWidget(chart, 1)

        # Action buttons
        finish_btn = QPushButton("Finish", self)
        finish_btn.clicked.connect(self.accept)
        discard_btn = QPushButton("Discard", self)
        discard_btn.clicked.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(discard_btn)
        btn_row.addWidget(finish_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def activity_name(self) -> str:
        return self._name_field.text().strip()
