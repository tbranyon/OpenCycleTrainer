"""Library page — Phase 5 placeholder."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..components import screen_header


@ui.page("/library")
def library_page() -> None:
    """Workout library screen (stub — full implementation in Phase 5)."""
    content = shell.build("/library")
    with content:
        screen_header("Library")
        with ui.element("div").classes("placeholder-page"):
            ui.icon("menu_book").classes("placeholder-icon")
            ui.label("Workout Library").classes("placeholder-label")
            ui.label("Full implementation coming in Phase 5").classes("placeholder-sub")
