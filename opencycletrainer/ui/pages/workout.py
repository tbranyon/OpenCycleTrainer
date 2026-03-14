"""Workout page — Phase 2 placeholder."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..components import screen_header


@ui.page("/workout")
def workout_page() -> None:
    """Main workout screen (stub — full implementation in Phase 2)."""
    content = shell.build("/workout")
    with content:
        screen_header("Ride")
        with ui.element("div").classes("placeholder-page"):
            ui.icon("directions_bike").classes("placeholder-icon")
            ui.label("Workout Screen").classes("placeholder-label")
            ui.label("Full implementation coming in Phase 2").classes("placeholder-sub")
