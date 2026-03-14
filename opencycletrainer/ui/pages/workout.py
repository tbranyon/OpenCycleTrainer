"""Workout page — Phase 2 static layout."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..workout_screen_ng import WorkoutScreen
from ... import state


@ui.page("/workout")
def workout_page() -> None:
    """Render the full workout screen with static layout."""
    content = shell.build("/workout")
    with content:
        screen = WorkoutScreen(
            settings=state.get(),
            # Callbacks wired in Phase 3 by WorkoutSessionController
        )

        # Forward JS keyboard events to screen.handle_hotkey().
        # Phase 3 will replace the stub with the real controller dispatch.
        def _on_hotkey(e: object) -> None:  # pragma: no cover
            pass  # Phase 3: screen.handle_hotkey(e.args['key'])

        ui.on("hotkey", _on_hotkey)
