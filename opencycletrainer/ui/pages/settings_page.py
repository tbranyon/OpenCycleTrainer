"""Settings page — Phase 7 placeholder."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..components import screen_header


@ui.page("/settings")
def settings_page() -> None:
    """Settings screen (stub — full implementation in Phase 7)."""
    content = shell.build("/settings")
    with content:
        screen_header("Settings")
        with ui.element("div").classes("placeholder-page"):
            ui.icon("tune").classes("placeholder-icon")
            ui.label("Settings").classes("placeholder-label")
            ui.label("Full implementation coming in Phase 7").classes("placeholder-sub")
