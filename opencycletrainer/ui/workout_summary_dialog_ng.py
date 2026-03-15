"""NiceGUI workout summary dialog — Phase 8."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from nicegui import ui

from .components import MetricTile
from .workout_summary_dialog import WorkoutSummary


def fmt_time(elapsed: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    secs = int(elapsed)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def show_workout_summary(
    summary: WorkoutSummary,
    on_done: Callable[[], None],
    strava_upload_fn: Callable[[], None] | None = None,
) -> None:
    """Open a NiceGUI modal summarising the completed workout session.

    *on_done* is called when the user dismisses the dialog.
    *strava_upload_fn*, when provided, adds an upload-to-Strava button with
    inline progress feedback.
    """
    np_text = f"{summary.normalized_power} W" if summary.normalized_power is not None else "--"
    tss_text = f"{int(summary.tss)}" if summary.tss is not None else "--"
    hr_text = f"{summary.avg_hr} bpm" if summary.avg_hr is not None else "--"

    tiles = [
        ("Time", fmt_time(summary.elapsed_seconds)),
        ("Work", f"{int(summary.kj)} kJ"),
        ("Normalized Power", np_text),
        ("TSS", tss_text),
        ("Avg Heart Rate", hr_text),
    ]

    with ui.dialog() as dialog, ui.card().classes("summary-card"):
        ui.label("Great Job!").classes("summary-heading")

        with ui.element("div").classes("summary-grid"):
            for title, value in tiles:
                MetricTile(title, initial_value=value, compact=True)

        if strava_upload_fn is not None:
            _build_strava_section(strava_upload_fn)

        with ui.element("div").classes("summary-actions"):
            def _dismiss() -> None:
                dialog.close()
                on_done()

            ui.button("Done", on_click=_dismiss).classes("btn btn-primary").props("no-caps")

    dialog.open()


def _build_strava_section(upload_fn: Callable[[], None]) -> None:
    """Render the Strava upload button with inline progress and status feedback."""
    with ui.element("div").classes("strava-section"):
        status_label = ui.label("").classes("strava-status color-secondary")
        status_label.set_visibility(False)

        async def _on_upload_click() -> None:
            upload_btn.disable()
            upload_btn.props(add="loading")
            status_label.set_visibility(False)
            try:
                await asyncio.get_event_loop().run_in_executor(None, upload_fn)
                upload_btn.props(remove="loading")
                upload_btn.set_text("Uploaded ✓")
                status_label.set_text("Synced to Strava")
                status_label.classes(add="color-success", remove="color-secondary color-error")
            except Exception:
                upload_btn.props(remove="loading")
                upload_btn.set_text("Upload to Strava")
                upload_btn.enable()
                status_label.set_text("Upload failed — check connection")
                status_label.classes(add="color-error", remove="color-secondary color-success")
            finally:
                status_label.set_visibility(True)

        upload_btn = ui.button(
            "Upload to Strava",
            icon="upload",
            on_click=_on_upload_click,
        ).classes("btn btn-secondary").props("no-caps").props(
            'aria-label="Upload workout to Strava"'
        )
