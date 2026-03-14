"""Devices page — Phase 6 placeholder."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..components import screen_header


@ui.page("/devices")
def devices_page() -> None:
    """Device management screen (stub — full implementation in Phase 6)."""
    content = shell.build("/devices")
    with content:
        screen_header("Devices")
        with ui.element("div").classes("placeholder-page"):
            ui.icon("bluetooth").classes("placeholder-icon")
            ui.label("Devices").classes("placeholder-label")
            ui.label("Full implementation coming in Phase 6").classes("placeholder-sub")
