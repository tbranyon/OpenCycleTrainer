from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class WorkoutSummary:
    """Snapshot of metrics collected over a completed workout."""

    elapsed_seconds: float
    kj: float
    normalized_power: int | None
    tss: float | None
    avg_hr: int | None


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

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)

        # Header
        header = QLabel("Great Job!", self)
        header.setAlignment(Qt.AlignCenter)
        header.setFont(_sans_font(header.font(), bold=True, size_delta=8))
        root.addWidget(header)

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

        # Done button
        done_btn = QPushButton("Done", self)
        done_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(done_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)
