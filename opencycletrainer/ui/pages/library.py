"""Library page — Phase 5: full workout library screen."""
from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from .. import shell
from ..library_screen_ng import LibraryScreen
from ... import singletons


@ui.page("/library")
def library_page() -> None:
    """Workout library screen with search, sort, and load capabilities."""
    content = shell.build("/library")
    library = singletons.get_library()

    def _on_load(path: Path) -> None:
        """Queue the selected workout and navigate to the workout screen."""
        app.storage.user["pending_workout_path"] = str(path)
        ui.navigate.to("/workout")

    with content:
        LibraryScreen(library=library, on_load_workout=_on_load)
