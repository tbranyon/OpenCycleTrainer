"""Settings page — Phase 7: full application settings screen."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..settings_screen_ng import SettingsScreenNg
from ... import state, singletons
from ...integrations.strava.token_store import get_tokens


@ui.page("/settings")
def settings_page() -> None:
    """Application settings: general options, metric tiles, Strava, and display."""
    content = shell.build("/settings")
    settings = state.get()

    strava_connected = get_tokens() is not None

    def _on_save(updated_settings) -> None:
        state.save(updated_settings)

    with content:
        SettingsScreenNg(
            settings=settings,
            on_save=_on_save,
            settings_path=state.get_settings_path(),
            strava_connected=strava_connected,
            strava_sync_fn=singletons.get_strava_upload_fn(),
        )
