from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from opencycletrainer.ui.workout_summary_dialog import (
    WorkoutSummary,
    WorkoutSummaryDialog,
    compute_tss,
)


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_summary(
    elapsed_seconds: float = 3600.0,
    kj: float = 900.0,
    normalized_power: int | None = 200,
    tss: float | None = 64.0,
    avg_hr: int | None = 145,
) -> WorkoutSummary:
    return WorkoutSummary(
        elapsed_seconds=elapsed_seconds,
        kj=kj,
        normalized_power=normalized_power,
        tss=tss,
        avg_hr=avg_hr,
    )


# ---------------------------------------------------------------------------
# compute_tss
# ---------------------------------------------------------------------------


def test_compute_tss_returns_100_for_one_hour_at_ftp():
    """One hour at exactly FTP should yield TSS of 100."""
    ftp = 250
    result = compute_tss(np_watts=250, ftp_watts=ftp, elapsed_seconds=3600.0)
    assert result is not None
    assert abs(result - 100.0) < 0.01


def test_compute_tss_returns_50_for_half_hour_at_ftp():
    ftp = 250
    result = compute_tss(np_watts=250, ftp_watts=ftp, elapsed_seconds=1800.0)
    assert result is not None
    assert abs(result - 50.0) < 0.01


def test_compute_tss_scales_with_intensity():
    """Riding at 2× FTP for 1 hour should give TSS of 400."""
    ftp = 200
    result = compute_tss(np_watts=400, ftp_watts=ftp, elapsed_seconds=3600.0)
    assert result is not None
    assert abs(result - 400.0) < 0.01


def test_compute_tss_returns_none_when_np_is_none():
    assert compute_tss(np_watts=None, ftp_watts=250, elapsed_seconds=3600.0) is None


def test_compute_tss_returns_none_when_ftp_is_zero():
    assert compute_tss(np_watts=200, ftp_watts=0, elapsed_seconds=3600.0) is None


def test_compute_tss_returns_none_when_elapsed_is_zero():
    assert compute_tss(np_watts=200, ftp_watts=250, elapsed_seconds=0.0) is None


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – structure
# ---------------------------------------------------------------------------


def test_summary_dialog_shows_all_five_tile_labels():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "Time" in label_texts
    assert "kJ" in label_texts
    assert "Normalized Power" in label_texts
    assert "TSS" in label_texts
    assert "Avg Heart Rate" in label_texts


def test_summary_dialog_has_done_button():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())
    button_texts = {btn.text() for btn in dialog.findChildren(QPushButton)}
    assert "Done" in button_texts


def test_summary_dialog_has_header_label():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "Great Job!" in label_texts


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – value formatting
# ---------------------------------------------------------------------------


def test_summary_dialog_formats_elapsed_time_as_hhmmss():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(elapsed_seconds=3723.0))  # 1h 2m 3s
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "01:02:03" in label_texts


def test_summary_dialog_formats_kj_as_integer_with_unit():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(kj=450.7))
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "450 kJ" in label_texts


def test_summary_dialog_formats_np_with_unit():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(normalized_power=215))
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "215 W" in label_texts


def test_summary_dialog_formats_tss_as_integer():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(tss=87.6))
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "87" in label_texts


def test_summary_dialog_formats_avg_hr_with_unit():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(avg_hr=152))
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "152 bpm" in label_texts


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – None handling
# ---------------------------------------------------------------------------


def test_summary_dialog_shows_placeholder_when_np_is_none():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(normalized_power=None, tss=None))
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "--" in label_texts


def test_summary_dialog_shows_placeholder_when_hr_is_none():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary(avg_hr=None))
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}
    assert "--" in label_texts


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – Done button behaviour
# ---------------------------------------------------------------------------


def test_done_button_accepts_dialog():
    app = _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())

    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))

    done_button = next(
        btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Done"
    )
    done_button.click()
    app.processEvents()

    assert accepted == [True]
