"""Tests for NiceGUI workout summary dialog helpers (Phase 8)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from opencycletrainer.ui.workout_summary_dialog import WorkoutSummary
from opencycletrainer.ui.workout_summary_dialog_ng import fmt_time


# ---------------------------------------------------------------------------
# fmt_time
# ---------------------------------------------------------------------------


def test_fmt_time_zero() -> None:
    assert fmt_time(0) == "00:00:00"


def test_fmt_time_seconds_only() -> None:
    assert fmt_time(45) == "00:00:45"


def test_fmt_time_minutes_and_seconds() -> None:
    assert fmt_time(125) == "00:02:05"


def test_fmt_time_one_hour() -> None:
    assert fmt_time(3600) == "01:00:00"


def test_fmt_time_mixed() -> None:
    """1h 2m 3s = 3723 seconds."""
    assert fmt_time(3723) == "01:02:03"


def test_fmt_time_multi_hour() -> None:
    """2h 1m 1s = 7261 seconds."""
    assert fmt_time(7261) == "02:01:01"


def test_fmt_time_truncates_sub_second() -> None:
    assert fmt_time(3661.9) == "01:01:01"


# ---------------------------------------------------------------------------
# show_workout_summary — smoke tests using mocked NiceGUI
# ---------------------------------------------------------------------------


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


def _mock_nicegui():
    """Return a context manager that patches nicegui.ui with MagicMocks."""
    card_ctx = MagicMock()
    card_ctx.__enter__ = MagicMock(return_value=card_ctx)
    card_ctx.__exit__ = MagicMock(return_value=False)

    dialog_ctx = MagicMock()
    dialog_ctx.__enter__ = MagicMock(return_value=dialog_ctx)
    dialog_ctx.__exit__ = MagicMock(return_value=False)
    dialog_ctx.open = MagicMock()

    element_ctx = MagicMock()
    element_ctx.__enter__ = MagicMock(return_value=element_ctx)
    element_ctx.__exit__ = MagicMock(return_value=False)
    element_ctx.classes = MagicMock(return_value=element_ctx)

    mock_ui = MagicMock()
    mock_ui.dialog.return_value = dialog_ctx
    mock_ui.card.return_value = card_ctx
    mock_ui.element.return_value = element_ctx
    mock_ui.label.return_value = MagicMock()
    mock_ui.button.return_value = MagicMock()
    mock_ui.icon.return_value = MagicMock()

    return patch("opencycletrainer.ui.workout_summary_dialog_ng.ui", mock_ui), mock_ui, dialog_ctx


def test_show_summary_opens_dialog() -> None:
    """show_workout_summary must open a dialog."""
    ctx, mock_ui, dialog = _mock_nicegui()
    with ctx:
        # Also patch MetricTile to avoid NiceGUI element creation
        with patch("opencycletrainer.ui.workout_summary_dialog_ng.MetricTile"):
            from opencycletrainer.ui.workout_summary_dialog_ng import show_workout_summary
            on_done = MagicMock()
            show_workout_summary(_make_summary(), on_done)
            dialog.open.assert_called_once()


def test_show_summary_without_strava_fn_no_upload_button() -> None:
    """When no strava_upload_fn is given, no upload button is rendered."""
    ctx, mock_ui, dialog = _mock_nicegui()
    with ctx:
        with patch("opencycletrainer.ui.workout_summary_dialog_ng.MetricTile"):
            from opencycletrainer.ui.workout_summary_dialog_ng import show_workout_summary
            show_workout_summary(_make_summary(), MagicMock(), strava_upload_fn=None)
    # ui.button called only once (Done button)
    assert mock_ui.button.call_count == 1
    call_args = mock_ui.button.call_args_list[0]
    assert call_args[0][0] == "Done"


def test_show_summary_with_strava_fn_renders_upload_button() -> None:
    """When strava_upload_fn is provided, an upload button is also rendered."""
    ctx, mock_ui, dialog = _mock_nicegui()
    with ctx:
        with patch("opencycletrainer.ui.workout_summary_dialog_ng.MetricTile"):
            from opencycletrainer.ui.workout_summary_dialog_ng import show_workout_summary
            strava_fn = MagicMock()
            show_workout_summary(_make_summary(), MagicMock(), strava_upload_fn=strava_fn)
    # Two buttons: Done + Upload to Strava
    assert mock_ui.button.call_count == 2
    button_labels = [c[0][0] for c in mock_ui.button.call_args_list]
    assert "Upload to Strava" in button_labels
    assert "Done" in button_labels


def test_show_summary_with_none_np_and_hr() -> None:
    """Dialog with None normalized_power and avg_hr must not raise."""
    ctx, mock_ui, dialog = _mock_nicegui()
    with ctx:
        with patch("opencycletrainer.ui.workout_summary_dialog_ng.MetricTile"):
            from opencycletrainer.ui.workout_summary_dialog_ng import show_workout_summary
            show_workout_summary(
                _make_summary(normalized_power=None, tss=None, avg_hr=None),
                MagicMock(),
            )
    dialog.open.assert_called_once()
