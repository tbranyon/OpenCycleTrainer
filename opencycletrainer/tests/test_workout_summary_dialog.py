from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QTableWidget

from opencycletrainer.core.recorder import RecorderSample
from opencycletrainer.core.workout_metrics import compute_workout_metrics
from opencycletrainer.ui.workout_chart import PowerDurationChartWidget
from opencycletrainer.ui.workout_summary_dialog import (
    INTERVAL_PERCENT_COLOR_GREEN,
    INTERVAL_PERCENT_COLOR_RED,
    INTERVAL_PERCENT_COLOR_YELLOW,
    IntervalResult,
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
    interval_results: tuple[IntervalResult, ...] = (),
    power_samples: tuple[tuple[float, int], ...] = (),
) -> WorkoutSummary:
    return WorkoutSummary(
        elapsed_seconds=elapsed_seconds,
        kj=kj,
        normalized_power=normalized_power,
        tss=tss,
        avg_hr=avg_hr,
        interval_results=interval_results,
        power_samples=power_samples,
    )


def _make_interval_result(
    interval_number: int = 1,
    duration_seconds: int = 300,
    target_watts: int | None = 200,
    target_percent_ftp: float | None = 80.0,
    avg_watts: int | None = 190,
    avg_hr: int | None = 145,
    skipped: bool = False,
) -> IntervalResult:
    return IntervalResult(
        interval_number=interval_number,
        duration_seconds=duration_seconds,
        target_watts=target_watts,
        target_percent_ftp=target_percent_ftp,
        avg_watts=avg_watts,
        avg_hr=avg_hr,
        skipped=skipped,
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


def test_summary_dialog_has_finish_button():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())
    button_texts = {btn.text() for btn in dialog.findChildren(QPushButton)}
    assert "Finish" in button_texts


def test_summary_dialog_has_discard_button():
    _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())
    button_texts = {btn.text() for btn in dialog.findChildren(QPushButton)}
    assert "Discard" in button_texts


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


def test_finish_button_accepts_dialog():
    app = _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())

    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))

    finish_button = next(
        btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Finish"
    )
    finish_button.click()
    app.processEvents()

    assert accepted == [True]


def test_discard_button_rejects_dialog():
    app = _get_or_create_qapp()
    dialog = WorkoutSummaryDialog(_make_summary())

    rejected: list[bool] = []
    dialog.rejected.connect(lambda: rejected.append(True))

    discard_button = next(
        btn for btn in dialog.findChildren(QPushButton) if btn.text() == "Discard"
    )
    discard_button.click()
    app.processEvents()

    assert rejected == [True]


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – values derived from metrics calculator
# ---------------------------------------------------------------------------

_METRICS_BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _metrics_sample(
    idx: int,
    *,
    trainer: int | None = None,
    hr: int | None = None,
) -> RecorderSample:
    return RecorderSample(
        timestamp_utc=_METRICS_BASE + timedelta(seconds=idx),
        trainer_power_watts=trainer,
        heart_rate_bpm=hr,
    )


def _metrics_steady(n: int, watts: int, hr: int | None = None) -> list[RecorderSample]:
    return [_metrics_sample(i, trainer=watts, hr=hr) for i in range(n)]


def test_dialog_np_reflects_metrics_calculator_output() -> None:
    """NP shown in dialog must match what compute_workout_metrics returns for the
    same sample stream — no separate recomputation in the controller."""
    _get_or_create_qapp()
    samples = _metrics_steady(60, watts=200)
    metrics = compute_workout_metrics(samples, ftp_watts=250)

    summary = WorkoutSummary(
        elapsed_seconds=float(len(samples)),
        kj=metrics.kj,
        normalized_power=metrics.normalized_power,
        tss=metrics.tss,
        avg_hr=metrics.avg_hr,
    )
    dialog = WorkoutSummaryDialog(summary)
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}

    assert metrics.normalized_power is not None
    assert f"{metrics.normalized_power} W" in label_texts


def test_dialog_kj_reflects_metrics_calculator_output() -> None:
    """kJ shown in dialog must equal sum(effective_power × 1 s) / 1000 from the
    sample stream, as computed by compute_workout_metrics."""
    _get_or_create_qapp()
    samples = _metrics_steady(60, watts=300)
    metrics = compute_workout_metrics(samples, ftp_watts=250)

    summary = WorkoutSummary(
        elapsed_seconds=float(len(samples)),
        kj=metrics.kj,
        normalized_power=metrics.normalized_power,
        tss=metrics.tss,
        avg_hr=metrics.avg_hr,
    )
    dialog = WorkoutSummaryDialog(summary)
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}

    # 60 × 300 W × 1 s / 1000 = 18 kJ
    assert metrics.kj == pytest.approx(18.0)
    assert f"{int(metrics.kj)} kJ" in label_texts


def test_dialog_avg_hr_reflects_metrics_calculator_output() -> None:
    """Avg HR shown in dialog must match compute_workout_metrics result."""
    _get_or_create_qapp()
    samples = _metrics_steady(60, watts=200, hr=155)
    metrics = compute_workout_metrics(samples, ftp_watts=250)

    summary = WorkoutSummary(
        elapsed_seconds=float(len(samples)),
        kj=metrics.kj,
        normalized_power=metrics.normalized_power,
        tss=metrics.tss,
        avg_hr=metrics.avg_hr,
    )
    dialog = WorkoutSummaryDialog(summary)
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}

    assert metrics.avg_hr == 155
    assert "155 bpm" in label_texts


def test_dialog_tss_reflects_metrics_calculator_output() -> None:
    """TSS shown in dialog must match compute_workout_metrics result."""
    _get_or_create_qapp()
    samples = _metrics_steady(60, watts=250)  # riding at FTP
    metrics = compute_workout_metrics(samples, ftp_watts=250)

    summary = WorkoutSummary(
        elapsed_seconds=float(len(samples)),
        kj=metrics.kj,
        normalized_power=metrics.normalized_power,
        tss=metrics.tss,
        avg_hr=metrics.avg_hr,
    )
    dialog = WorkoutSummaryDialog(summary)
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}

    assert metrics.tss is not None
    assert f"{int(metrics.tss)}" in label_texts


def test_dialog_shows_placeholder_when_metrics_has_no_hr() -> None:
    """When samples carry no HR, metrics.avg_hr is None and dialog shows '--'."""
    _get_or_create_qapp()
    samples = _metrics_steady(60, watts=200, hr=None)
    metrics = compute_workout_metrics(samples, ftp_watts=250)

    summary = WorkoutSummary(
        elapsed_seconds=float(len(samples)),
        kj=metrics.kj,
        normalized_power=metrics.normalized_power,
        tss=metrics.tss,
        avg_hr=metrics.avg_hr,
    )
    dialog = WorkoutSummaryDialog(summary)
    label_texts = {lbl.text() for lbl in dialog.findChildren(QLabel)}

    assert metrics.avg_hr is None
    assert "--" in label_texts


# ---------------------------------------------------------------------------
# IntervalResult dataclass
# ---------------------------------------------------------------------------


def test_interval_result_stores_all_fields():
    result = _make_interval_result()
    assert result.interval_number == 1
    assert result.duration_seconds == 300
    assert result.target_watts == 200
    assert result.target_percent_ftp == pytest.approx(80.0)
    assert result.avg_watts == 190
    assert result.avg_hr == 145
    assert result.skipped is False


def test_interval_result_skipped_defaults_to_false():
    result = IntervalResult(
        interval_number=1,
        duration_seconds=60,
        target_watts=200,
        target_percent_ftp=80.0,
        avg_watts=190,
        avg_hr=None,
    )
    assert result.skipped is False


def test_interval_result_supports_none_fields_for_free_ride():
    result = IntervalResult(
        interval_number=1,
        duration_seconds=300,
        target_watts=None,
        target_percent_ftp=None,
        avg_watts=None,
        avg_hr=None,
    )
    assert result.target_watts is None
    assert result.target_percent_ftp is None


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – interval breakdown table structure
# ---------------------------------------------------------------------------


def test_dialog_shows_interval_table_when_results_provided():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(),))
    dialog = WorkoutSummaryDialog(summary)
    tables = dialog.findChildren(QTableWidget)
    assert tables, "Expected a QTableWidget when interval results are present"


def test_dialog_has_no_interval_table_when_results_empty():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=())
    dialog = WorkoutSummaryDialog(summary)
    tables = dialog.findChildren(QTableWidget)
    assert not tables, "Expected no QTableWidget when interval_results is empty"


def test_dialog_interval_table_has_six_columns():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.columnCount() == 6


def test_dialog_interval_table_column_headers():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["#", "Duration", "Target (W)", "Actual Avg (W)", "% of Target", "Avg HR"]


def test_dialog_interval_table_row_count_matches_results():
    _get_or_create_qapp()
    results = (_make_interval_result(1), _make_interval_result(2), _make_interval_result(3))
    summary = _make_summary(interval_results=results)
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.rowCount() == 3


def test_dialog_interval_table_shows_interval_number():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(interval_number=3),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 0).text() == "3"


def test_dialog_interval_table_shows_duration_as_mss():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(duration_seconds=300),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 1).text() == "5:00"


def test_dialog_interval_table_shows_target_watts():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(target_watts=250),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 2).text() == "250"


def test_dialog_interval_table_shows_actual_avg_watts():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(avg_watts=195),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 3).text() == "195"


def test_dialog_interval_table_shows_avg_hr():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(avg_hr=152),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 5).text() == "152"


def test_dialog_interval_table_shows_dash_for_no_avg_hr():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(avg_hr=None),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 5).text() == "-"


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – % of Target display and color coding
# ---------------------------------------------------------------------------


def test_dialog_interval_table_shows_percent_of_target():
    """190 W actual vs 200 W target = 95%."""
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(target_watts=200, avg_watts=190),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 4).text() == "95%"


def test_dialog_interval_percent_cell_green_at_or_above_95_percent():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(target_watts=200, avg_watts=190),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    color = table.item(0, 4).background().color()
    assert color == INTERVAL_PERCENT_COLOR_GREEN


def test_dialog_interval_percent_cell_yellow_between_85_and_94_percent():
    """170 W actual vs 200 W target = 85%."""
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(target_watts=200, avg_watts=170),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    color = table.item(0, 4).background().color()
    assert color == INTERVAL_PERCENT_COLOR_YELLOW


def test_dialog_interval_percent_cell_red_below_85_percent():
    """160 W actual vs 200 W target = 80%."""
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(target_watts=200, avg_watts=160),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    color = table.item(0, 4).background().color()
    assert color == INTERVAL_PERCENT_COLOR_RED


def test_dialog_interval_percent_cell_uncolored_when_no_avg_watts():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(target_watts=200, avg_watts=None),))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    item = table.item(0, 4)
    assert item.text() == "-"
    color = item.background().color()
    assert color != INTERVAL_PERCENT_COLOR_GREEN
    assert color != INTERVAL_PERCENT_COLOR_YELLOW
    assert color != INTERVAL_PERCENT_COLOR_RED


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – free-ride and skipped intervals
# ---------------------------------------------------------------------------


def test_dialog_interval_table_shows_dash_for_free_ride_target():
    _get_or_create_qapp()
    result = _make_interval_result(target_watts=None, target_percent_ftp=None)
    summary = _make_summary(interval_results=(result,))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert table.item(0, 2).text() == "-"
    assert table.item(0, 4).text() == "-"


def test_dialog_interval_table_marks_skipped_interval():
    _get_or_create_qapp()
    result = _make_interval_result(skipped=True)
    summary = _make_summary(interval_results=(result,))
    dialog = WorkoutSummaryDialog(summary)
    table = dialog.findChildren(QTableWidget)[0]
    assert "Skipped" in table.item(0, 0).text()


# ---------------------------------------------------------------------------
# WorkoutSummaryDialog – power-duration curve chart
# ---------------------------------------------------------------------------


def _power_samples(seconds: int = 60, watts: int = 200) -> tuple[tuple[float, int], ...]:
    return tuple((float(i), watts) for i in range(seconds))


def test_dialog_shows_power_duration_chart_when_power_samples_present():
    _get_or_create_qapp()
    summary = _make_summary(power_samples=_power_samples())
    dialog = WorkoutSummaryDialog(summary)
    charts = dialog.findChildren(PowerDurationChartWidget)
    assert charts, "Expected a PowerDurationChartWidget when power samples are present"


def test_dialog_has_no_power_duration_chart_when_power_samples_empty():
    _get_or_create_qapp()
    summary = _make_summary(power_samples=())
    dialog = WorkoutSummaryDialog(summary)
    charts = dialog.findChildren(PowerDurationChartWidget)
    assert not charts


def test_power_duration_chart_placed_below_interval_table():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(),), power_samples=_power_samples())
    dialog = WorkoutSummaryDialog(summary)
    root = dialog.layout()

    table = dialog.findChildren(QTableWidget)[0]
    chart = dialog.findChildren(PowerDurationChartWidget)[0]

    scroll = table.parent()
    while scroll is not None and not isinstance(scroll, QScrollArea):
        scroll = scroll.parent()
    assert isinstance(scroll, QScrollArea)

    scroll_index = root.indexOf(scroll)
    chart_index = root.indexOf(chart)
    assert scroll_index != -1 and chart_index != -1
    assert chart_index > scroll_index


def test_power_duration_chart_not_inside_interval_table_scroll_area():
    _get_or_create_qapp()
    summary = _make_summary(interval_results=(_make_interval_result(),), power_samples=_power_samples())
    dialog = WorkoutSummaryDialog(summary)

    table = dialog.findChildren(QTableWidget)[0]
    chart = dialog.findChildren(PowerDurationChartWidget)[0]

    scroll = table.parent()
    while scroll is not None and not isinstance(scroll, QScrollArea):
        scroll = scroll.parent()
    assert isinstance(scroll, QScrollArea)
    assert chart not in scroll.findChildren(PowerDurationChartWidget)


def test_dialog_minimum_size_larger_than_default():
    _get_or_create_qapp()
    summary = _make_summary()
    dialog = WorkoutSummaryDialog(summary)
    assert dialog.minimumWidth() >= 700
    assert dialog.minimumHeight() >= 700
