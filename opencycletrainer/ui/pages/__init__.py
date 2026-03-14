"""NiceGUI page registration for OpenCycleTrainer."""
from __future__ import annotations

from nicegui import ui


def register_all() -> None:
    """Import all page modules so their @ui.page decorators execute.

    Must be called before ``ui.run()``.
    """
    # Root redirect
    @ui.page("/")
    def _root() -> None:
        ui.navigate.to("/workout")

    # Import modules — the @ui.page decorators fire at import time
    from . import workout, library, devices, settings_page  # noqa: F401
