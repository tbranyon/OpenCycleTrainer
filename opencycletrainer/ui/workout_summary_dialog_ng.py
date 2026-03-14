"""NiceGUI workout summary dialog — Phase 3."""
from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from .workout_summary_dialog import WorkoutSummary


def _fmt_time(elapsed: float) -> str:
    secs = int(elapsed)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def show_workout_summary(
    summary: WorkoutSummary,
    on_done: Callable[[], None],
) -> None:
    """Open a NiceGUI modal summarising the completed workout session.

    *on_done* is called when the user dismisses the dialog.
    """
    np_text = f"{summary.normalized_power} W" if summary.normalized_power is not None else "--"
    tss_text = f"{int(summary.tss)}" if summary.tss is not None else "--"
    hr_text = f"{summary.avg_hr} bpm" if summary.avg_hr is not None else "--"

    tiles = [
        ("Time", _fmt_time(summary.elapsed_seconds)),
        ("Work", f"{int(summary.kj)} kJ"),
        ("Normalized Power", np_text),
        ("TSS", tss_text),
        ("Avg Heart Rate", hr_text),
    ]

    with ui.dialog() as dialog, ui.card().classes("summary-card"):
        ui.label("Great Job!").classes("summary-heading")

        with ui.element("div").classes("summary-grid"):
            for title, value in tiles:
                with ui.element("div").classes("summary-tile"):
                    ui.label(title).classes("summary-tile-label")
                    ui.label(value).classes("summary-tile-value")

        def _dismiss() -> None:
            dialog.close()
            on_done()

        ui.button("Done", on_click=_dismiss).classes("btn btn-primary").props("no-caps")

    dialog.open()
