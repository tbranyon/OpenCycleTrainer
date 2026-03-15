"""NiceGUI Settings Screen — Phase 7.

Ports SettingsScreen from PySide6 to NiceGUI with collapsible sections,
custom number inputs, tile selector with count enforcement, and Strava OAuth.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from nicegui import ui

from opencycletrainer.integrations.strava.app_credentials import has_app_credentials, load_app_credentials
from opencycletrainer.integrations.strava.oauth_flow import OAuthResult, run_oauth_flow
from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError
from opencycletrainer.integrations.strava.token_store import clear_tokens, is_available, save_tokens
from opencycletrainer.storage.paths import get_data_dir
from opencycletrainer.storage.settings import AppSettings, save_settings
from .components import screen_header
from .tile_config import MAX_CONFIGURABLE_TILES, TILE_OPTIONS, normalize_tile_selections

_logger = logging.getLogger(__name__)

DISPLAY_UNITS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("metric", "Metric"),
    ("imperial", "Imperial"),
)
DEFAULT_BEHAVIOR_OPTIONS: tuple[tuple[str, str], ...] = (
    ("workout_mode", "Workout Mode"),
    ("free_ride_mode", "Free Ride Mode"),
    ("kj_mode", "kJ Mode"),
)


# ---------------------------------------------------------------------------
# SettingsController — pure logic layer (no NiceGUI)
# ---------------------------------------------------------------------------


class SettingsController:
    """Holds mutable settings state and enforces tile selection limits.

    No NiceGUI imports — fully unit-testable.
    """

    def __init__(
        self,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
    ) -> None:
        self._initial = settings
        self._on_save = on_save

        self.ftp: int = settings.ftp
        self.lead_time: int = settings.lead_time
        self.windowed_power_window_seconds: int = settings.windowed_power_window_seconds
        self.opentrueup_enabled: bool = settings.opentrueup_enabled
        self.display_units: str = settings.display_units
        self.default_workout_behavior: str = settings.default_workout_behavior
        self.strava_auto_sync_enabled: bool = settings.strava_auto_sync_enabled
        self.theme: str = settings.theme
        self.selected_tiles: list[str] = normalize_tile_selections(settings.tile_selections)

    @property
    def tile_count(self) -> int:
        return len(self.selected_tiles)

    @property
    def tile_count_label(self) -> str:
        return f"{self.tile_count} of {MAX_CONFIGURABLE_TILES} selected"

    def is_tile_selected(self, key: str) -> bool:
        return key in self.selected_tiles

    def toggle_tile(self, key: str, checked: bool) -> bool:
        """Toggle *key* in selected tiles.  Returns False if the max limit prevented adding."""
        if checked:
            if key in self.selected_tiles:
                return True
            if len(self.selected_tiles) >= MAX_CONFIGURABLE_TILES:
                return False
            self.selected_tiles.append(key)
        else:
            if key in self.selected_tiles:
                self.selected_tiles.remove(key)
        return True

    def save(self) -> AppSettings:
        """Build an AppSettings from current field values and call on_save."""
        updated = replace(
            self._initial,
            ftp=int(self.ftp),
            lead_time=int(self.lead_time),
            windowed_power_window_seconds=int(self.windowed_power_window_seconds),
            opentrueup_enabled=bool(self.opentrueup_enabled),
            display_units=self.display_units,
            default_workout_behavior=self.default_workout_behavior,
            strava_auto_sync_enabled=self.strava_auto_sync_enabled,
            theme=self.theme,
            tile_selections=list(self.selected_tiles),
        )
        self._initial = updated
        self._on_save(updated)
        return updated


# ---------------------------------------------------------------------------
# SettingsScreenNg — NiceGUI view layer
# ---------------------------------------------------------------------------


class SettingsScreenNg:
    """NiceGUI settings screen with collapsible sections."""

    def __init__(
        self,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
        settings_path: Path | None = None,
        strava_connected: bool = False,
        strava_sync_fn: Callable[[Path, Path | None], None] | None = None,
    ) -> None:
        self._ctrl = SettingsController(settings, on_save)
        self._settings_path = settings_path
        self._strava_connected = strava_connected
        self._strava_sync_fn = strava_sync_fn

        actions = screen_header("Settings")
        with actions:
            self._save_btn = (
                ui.button("Save Changes", icon="save", on_click=self._on_save_clicked)
                .classes("btn btn-primary btn-sm")
                .props("no-caps")
            )

        self._status_label = ui.label("").classes("settings-status text-small")

        with ui.element("div").classes("settings-content"):
            self._build_general_section()
            self._build_tiles_section()
            self._build_strava_section(strava_connected, settings.strava_athlete_name)
            self._build_display_section()

    # ── Section builders ──────────────────────────────────────────────────

    def _build_general_section(self) -> None:
        with self._collapsible_section("General"):
            with ui.element("div").classes("settings-form"):
                self._ftp_input = self._number_row(
                    "FTP (W)", self._ctrl.ftp, min_val=50, max_val=2000,
                    on_change=lambda v: setattr(self._ctrl, "ftp", v),
                )
                self._lead_time_input = self._number_row(
                    "Lead Time (s)", self._ctrl.lead_time, min_val=0, max_val=30,
                    on_change=lambda v: setattr(self._ctrl, "lead_time", v),
                )
                self._power_window_input = self._number_row(
                    "Power Window (s)", self._ctrl.windowed_power_window_seconds, min_val=1, max_val=10,
                    on_change=lambda v: setattr(self._ctrl, "windowed_power_window_seconds", v),
                )
                self._build_toggle_row(
                    "OpenTrueUp",
                    self._ctrl.opentrueup_enabled,
                    on_change=lambda v: setattr(self._ctrl, "opentrueup_enabled", v),
                )
                self._build_select_row(
                    "Display Units",
                    DISPLAY_UNITS_OPTIONS,
                    self._ctrl.display_units,
                    on_change=lambda v: setattr(self._ctrl, "display_units", v),
                )
                self._build_select_row(
                    "Default Behavior",
                    DEFAULT_BEHAVIOR_OPTIONS,
                    self._ctrl.default_workout_behavior,
                    on_change=lambda v: setattr(self._ctrl, "default_workout_behavior", v),
                )

    def _build_tiles_section(self) -> None:
        with self._collapsible_section("Metric Tiles"):
            with ui.element("div").classes("settings-tile-header"):
                self._tile_count_label = ui.label(self._ctrl.tile_count_label).classes(
                    "text-small color-secondary"
                )
            with ui.element("div").classes("settings-tile-grid"):
                self._tile_checkboxes: dict[str, ui.checkbox] = {}
                for key, label in TILE_OPTIONS:
                    cb = ui.checkbox(
                        label,
                        value=self._ctrl.is_tile_selected(key),
                        on_change=lambda e, k=key: self._on_tile_toggled(k, e.value),
                    ).classes("settings-tile-checkbox")
                    self._tile_checkboxes[key] = cb

    def _build_strava_section(self, connected: bool, athlete_name: str) -> None:
        with self._collapsible_section("Strava"):
            with ui.element("div").classes("settings-form"):
                with ui.element("div").classes("settings-row"):
                    ui.label("Status").classes("settings-row-label text-label color-secondary")
                    self._strava_status_label = ui.label(
                        self._strava_status_text(connected, athlete_name)
                    ).classes("text-body")

                with ui.element("div").classes("settings-row"):
                    ui.label("").classes("settings-row-label")
                    with ui.element("div").style("display:flex; gap:8px; flex-wrap:wrap"):
                        self._strava_connect_btn = (
                            ui.button(
                                "Connect with Strava",
                                icon="link",
                                on_click=lambda: asyncio.ensure_future(self._do_strava_connect()),
                            )
                            .classes("btn btn-secondary btn-sm")
                            .props("no-caps flat")
                        )
                        self._strava_disconnect_btn = (
                            ui.button(
                                "Disconnect",
                                icon="link_off",
                                on_click=self._on_strava_disconnect,
                            )
                            .classes("btn btn-destructive btn-sm")
                            .props("no-caps flat")
                        )
                        self._strava_sync_now_btn = (
                            ui.button(
                                "Sync Now",
                                icon="sync",
                                on_click=lambda: asyncio.ensure_future(self._do_sync_now()),
                            )
                            .classes("btn btn-secondary btn-sm")
                            .props("no-caps flat")
                        )

                with ui.element("div").classes("settings-row"):
                    ui.label("Auto-sync").classes("settings-row-label text-label color-secondary")
                    self._auto_sync_toggle = ui.switch(
                        value=self._ctrl.strava_auto_sync_enabled,
                        on_change=lambda e: setattr(
                            self._ctrl, "strava_auto_sync_enabled", e.value
                        ),
                    )

        self._apply_strava_state(connected, athlete_name)

    def _build_display_section(self) -> None:
        with self._collapsible_section("Display"):
            with ui.element("div").classes("settings-form"):
                self._build_select_row(
                    "Theme",
                    (("dark", "Dark"), ("light", "Light")),
                    self._ctrl.theme,
                    on_change=self._on_theme_changed,
                )

    # ── Form element helpers ──────────────────────────────────────────────

    @staticmethod
    def _collapsible_section(title: str):
        """Render a collapsible settings section card and return its body context."""
        expansion = ui.expansion(title, icon="expand_more").classes("settings-section")
        expansion.open()
        return expansion

    def _number_row(
        self,
        label: str,
        initial: int,
        min_val: int,
        max_val: int,
        on_change: Callable[[int], None],
    ) -> ui.number:
        with ui.element("div").classes("settings-row"):
            ui.label(label).classes("settings-row-label text-label color-secondary")
            num = ui.number(
                value=initial,
                min=min_val,
                max=max_val,
                step=1,
                on_change=lambda e: on_change(int(e.value)) if e.value is not None else None,
            ).classes("settings-number-input").props("dense outlined")
        return num

    def _build_toggle_row(
        self,
        label: str,
        initial: bool,
        on_change: Callable[[bool], None],
    ) -> ui.switch:
        with ui.element("div").classes("settings-row"):
            ui.label(label).classes("settings-row-label text-label color-secondary")
            toggle = ui.switch(value=initial, on_change=lambda e: on_change(bool(e.value)))
        return toggle

    def _build_select_row(
        self,
        label: str,
        options: tuple[tuple[str, str], ...],
        current_value: str,
        on_change: Callable[[str], None],
    ) -> ui.select:
        opt_map = {k: v for k, v in options}
        opt_list = list(opt_map.values())
        current_label = opt_map.get(current_value, opt_list[0] if opt_list else "")
        with ui.element("div").classes("settings-row"):
            ui.label(label).classes("settings-row-label text-label color-secondary")
            sel = ui.select(
                opt_list,
                value=current_label,
                on_change=lambda e: on_change(
                    next((k for k, v in options if v == e.value), options[0][0])
                ),
            ).classes("settings-select").props("dense outlined")
        return sel

    # ── Tile management ───────────────────────────────────────────────────

    def _on_tile_toggled(self, key: str, checked: bool) -> None:
        accepted = self._ctrl.toggle_tile(key, checked)
        if not accepted:
            # Revert checkbox
            cb = self._tile_checkboxes.get(key)
            if cb is not None:
                cb.set_value(False)
            self._status_label.set_text(f"Maximum {MAX_CONFIGURABLE_TILES} tiles can be selected.")
        self._tile_count_label.set_text(self._ctrl.tile_count_label)

    # ── Save ──────────────────────────────────────────────────────────────

    def _on_save_clicked(self) -> None:
        try:
            self._ctrl.save()
            if self._settings_path:
                save_settings(self._ctrl._initial, self._settings_path)
            self._status_label.set_text("Settings saved.")
        except Exception as exc:
            _logger.error("Save settings failed: %s", exc)
            self._status_label.set_text(f"Save failed: {exc}")

    # ── Theme ─────────────────────────────────────────────────────────────

    def _on_theme_changed(self, value: str) -> None:
        self._ctrl.theme = value
        ui.run_javascript(f'document.documentElement.className = "{value}";')
        try:
            from opencycletrainer import state  # noqa: PLC0415
            state.update(theme=value)
        except Exception:
            pass

    # ── Strava ────────────────────────────────────────────────────────────

    async def _do_strava_connect(self) -> None:
        if not is_available():
            self._status_label.set_text(
                "Secure credential storage is not available on this system."
            )
            return
        if not has_app_credentials():
            self._status_label.set_text("Strava app credentials are not configured.")
            return

        credentials = load_app_credentials()
        self._strava_connect_btn.props(add="disabled")
        self._status_label.set_text("Opening Strava authorization in browser…")
        try:
            result: OAuthResult = await asyncio.to_thread(run_oauth_flow, credentials)
            save_tokens(result.token_bundle)
            self._ctrl._initial = replace(
                self._ctrl._initial, strava_athlete_name=result.athlete_name
            )
            if self._settings_path:
                save_settings(self._ctrl._initial, self._settings_path)
            self._apply_strava_state(True, result.athlete_name)
            self._status_label.set_text("Strava connected.")
        except Exception as exc:
            self._status_label.set_text(f"Strava connection failed: {exc}")
        finally:
            self._strava_connect_btn.props(remove="disabled")

    def _on_strava_disconnect(self) -> None:
        clear_tokens()
        self._ctrl._initial = replace(
            self._ctrl._initial, strava_athlete_name="", strava_auto_sync_enabled=False
        )
        self._ctrl.strava_auto_sync_enabled = False
        if self._settings_path:
            save_settings(self._ctrl._initial, self._settings_path)
        self._apply_strava_state(False, "")

    async def _do_sync_now(self) -> None:
        if self._strava_sync_fn is None:
            self._status_label.set_text("Strava sync function not configured.")
            return

        path_str = await asyncio.to_thread(self._open_fit_dialog)
        if not path_str:
            return

        self._strava_sync_now_btn.props(add="disabled")
        self._status_label.set_text("Syncing to Strava…")
        fit_path = Path(path_str)
        sync_fn = self._strava_sync_fn
        try:
            await asyncio.to_thread(sync_fn, fit_path, None)
            self._status_label.set_text("Ride synced to Strava.")
        except DuplicateUploadError:
            self._status_label.set_text("Ride already synced to Strava.")
        except Exception as exc:
            self._status_label.set_text(f"Strava sync failed: {exc}")
        finally:
            self._strava_sync_now_btn.props(remove="disabled")

    def _apply_strava_state(self, connected: bool, athlete_name: str) -> None:
        self._strava_connected = connected
        self._strava_status_label.set_text(self._strava_status_text(connected, athlete_name))
        self._strava_connect_btn.set_visibility(not connected)
        self._strava_disconnect_btn.set_visibility(connected)
        self._strava_sync_now_btn.set_visibility(connected)
        self._auto_sync_toggle.set_visibility(connected)

    @staticmethod
    def _strava_status_text(connected: bool, athlete_name: str) -> str:
        if connected:
            return f"Connected as {athlete_name}" if athlete_name else "Connected"
        return "Not connected"

    @staticmethod
    def _open_fit_dialog() -> str:
        try:
            import tkinter as tk  # noqa: PLC0415
            from tkinter import filedialog  # noqa: PLC0415

            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Select FIT File to Sync",
                initialdir=str(get_data_dir()),
                filetypes=[("FIT Files", "*.fit"), ("All Files", "*.*")],
            )
            root.destroy()
            return path or ""
        except Exception as exc:
            _logger.warning("File dialog error: %s", exc)
            return ""
