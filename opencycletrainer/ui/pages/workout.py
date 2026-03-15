"""Workout page — wires WorkoutScreen with WorkoutSessionController."""
from __future__ import annotations

from nicegui import app, ui

from .. import shell
from ..workout_screen_ng import WorkoutScreen
from ..workout_controller_ng import WorkoutSessionController
from ... import state, singletons


@ui.page("/workout")
def workout_page() -> None:
    """Render the full workout screen with live controller wiring."""
    content = shell.build("/workout")
    settings = state.get()

    with content:
        screen = WorkoutScreen(settings=settings)

        controller = WorkoutSessionController(
            screen=screen,
            settings=settings,
            settings_path=state.get_settings_path(),
            strava_upload_fn=singletons.get_strava_upload_fn(),
        )

        # Wire trainer device changes from the devices screen
        def _on_trainer_changed(backend, trainer_device_id: str | None) -> None:
            controller.set_trainer_control_target(
                backend=backend,
                trainer_device_id=trainer_device_id,
            )

        singletons.register_trainer_changed_callback(_on_trainer_changed)

        def _on_hotkey(e: object) -> None:  # pragma: no cover
            key = (getattr(e, "args", {}) or {}).get("key", "")
            screen.handle_hotkey(key)

        ui.on("hotkey", _on_hotkey)

        # Load any workout path queued from the library page
        pending = app.storage.user.get("pending_workout_path")
        if pending:
            app.storage.user["pending_workout_path"] = None
            from pathlib import Path  # noqa: PLC0415
            controller.load_workout(Path(pending))
