"""NiceGUI workout screen — Phase 2 static layout."""
from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from opencycletrainer.storage.settings import AppSettings
from .components import AlertBanner, MetricTile
from .tile_config import TILE_LABEL_BY_KEY, normalize_tile_selections

MODE_OPTIONS: tuple[str, ...] = ("ERG", "Resistance", "Hybrid")


class WorkoutScreen:
    """Full workout screen widget for NiceGUI.

    Instantiate inside a ``@ui.page`` handler; all ``ui.*`` calls attach to
    the active NiceGUI rendering context.  Callbacks (on_start, etc.) are
    wired by ``WorkoutSessionController`` in Phase 3; they default to no-ops
    so the static layout renders independently.
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        on_start: Callable[[], None] | None = None,
        on_pause: Callable[[], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_load_file: Callable[[], None] | None = None,
        on_load_library: Callable[[], None] | None = None,
        on_mode_changed: Callable[[str], None] | None = None,
        on_jog: Callable[[int], None] | None = None,
        on_extend: Callable[[int, bool], None] | None = None,
        on_skip: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._selected_tiles = normalize_tile_selections(settings.tile_selections)
        self._kj_mode = settings.default_workout_behavior == "kj_mode"

        self._on_start = on_start or (lambda: None)
        self._on_pause = on_pause or (lambda: None)
        self._on_resume = on_resume or (lambda: None)
        self._on_stop = on_stop or (lambda: None)
        self._on_load_file = on_load_file or (lambda: None)
        self._on_load_library = on_load_library or (lambda: None)
        self._on_mode_changed = on_mode_changed or (lambda _m: None)
        self._on_jog = on_jog or (lambda _d: None)
        self._on_extend = on_extend or (lambda _s, _k: None)
        self._on_skip = on_skip or (lambda: None)

        self._tile_by_key: dict[str, MetricTile] = {}
        self._build()

    # ── Layout construction ───────────────────────────────────────────────

    def _build(self) -> None:
        self._build_header()
        with ui.element("div").classes("workout-body"):
            self._build_mandatory_tiles()
            self._build_configurable_tiles()
            self._build_chart_area()
            self._build_controls()
        self._build_trainer_footer()
        self._build_pause_overlay()

    def _build_header(self) -> None:
        """Screen header: toggles between workout name and load-file buttons."""
        with ui.element("div").classes("screen-header"):
            with ui.element("div") as self._header_name_area:
                self._workout_name_label = ui.label("Workout").classes("screen-header-title")
            self._header_name_area.set_visibility(False)

            with ui.element("div").classes("workout-load-buttons") as self._header_load_area:
                ui.button(
                    "Load from Library",
                    icon="menu_book",
                    on_click=self._on_load_library,
                ).classes("btn btn-secondary").props("no-caps flat")
                ui.button(
                    "Load from File",
                    icon="file_open",
                    on_click=self._on_load_file,
                ).classes("btn btn-primary").props("no-caps")

    def _build_mandatory_tiles(self) -> None:
        """Four always-visible metric tiles."""
        with ui.element("div").classes("tiles-mandatory"):
            self._elapsed_tile = MetricTile("TIME ELAPSED", "0:00")
            self._target_tile = MetricTile("TARGET POWER", "---")
            self._interval_tile = MetricTile("INTERVAL REMAINING", "0:00")
            self._remaining_tile = MetricTile("TIME REMAINING", "0:00")

    def _build_configurable_tiles(self) -> None:
        """User-selected metric tile grid (up to 8, 4 per row)."""
        if not self._selected_tiles:
            ui.label("No tiles selected — configure in Settings.").classes(
                "text-small color-muted"
            ).style("padding: var(--space-1) 0")
            return
        with ui.element("div").classes("tiles-configurable"):
            for key in self._selected_tiles:
                tile = MetricTile(TILE_LABEL_BY_KEY[key].upper(), "---")
                self._tile_by_key[key] = tile

    def _build_chart_area(self) -> None:
        """Chart area — placeholder divs replaced by ECharts in Phase 4."""
        with ui.element("div").classes("chart-area"):
            with ui.element("div").classes("chart-placeholder").style("flex: 3"):
                ui.icon("show_chart").style(
                    "font-size: 32px; color: var(--text-muted); opacity: 0.3"
                )
                ui.label("Interval chart  ·  Phase 4").classes("text-small color-muted")
            with ui.element("div").classes("chart-placeholder").style("flex: 2"):
                ui.icon("bar_chart").style(
                    "font-size: 32px; color: var(--text-muted); opacity: 0.3"
                )
                ui.label("Overview chart  ·  Phase 4").classes("text-small color-muted")

    def _build_controls(self) -> None:
        """Start / Pause / Resume / Stop buttons plus the alert banner."""
        with ui.element("div").classes("controls-row"):
            self._start_btn = (
                ui.button("Start", icon="play_arrow", on_click=self._on_start)
                .classes("btn btn-primary btn-lg")
                .props("no-caps")
            )
            self._pause_btn = (
                ui.button("Pause", icon="pause", on_click=self._on_pause)
                .classes("btn btn-secondary btn-lg")
                .props("no-caps")
            )
            self._resume_btn = (
                ui.button("Resume", icon="play_arrow", on_click=self._on_resume)
                .classes("btn btn-primary btn-lg")
                .props("no-caps")
            )
            self._stop_btn = (
                ui.button("Stop", icon="stop", on_click=self._on_stop)
                .classes("btn btn-destructive btn-lg")
                .props("no-caps")
            )
        with ui.element("div").classes("alert-area"):
            self._alert = AlertBanner(timeout_s=5.0)

        # Initial idle state: only Start is active
        self.set_session_state("idle")

    def _build_trainer_footer(self) -> None:
        """Mode selector + resistance + OpenTrueUp footer (hidden until trainer connected)."""
        with ui.element("div").classes("trainer-footer") as self._trainer_footer:
            ui.label("MODE").classes("text-label color-muted")
            self._mode_select = (
                ui.select(
                    options=list(MODE_OPTIONS),
                    value="ERG",
                    on_change=lambda e: self._on_mode_changed(e.value),
                )
                .props("dense outlined")
                .classes("mode-select")
            )

            with ui.element("div").classes("resistance-display") as self._resistance_area:
                ui.label("RESISTANCE").classes("text-label color-muted")
                self._resistance_label = ui.label("-- %").classes("text-body color-secondary")
            self._resistance_area.set_visibility(False)

            ui.element("div").style("width: 16px")  # spacer

            ui.label("OPENTRUEUP").classes("text-label color-muted")
            self._opentrueup_label = ui.label("-- W").classes("text-body color-secondary")

        self._trainer_footer.set_visibility(False)

    def _build_pause_overlay(self) -> None:
        """Full-viewport pause overlay with elapsed time and action buttons."""
        with ui.element("div").classes("pause-overlay") as self._pause_overlay:
            ui.label("PAUSED").classes("pause-heading")

            with ui.element("div").classes("pause-elapsed-group"):
                self._pause_elapsed = ui.label("0:00").classes("pause-elapsed")
                ui.label("elapsed so far").classes("pause-elapsed-label")

            # Reserved for countdown digits supplied by controller in Phase 3
            self._pause_countdown = ui.label("").classes("pause-countdown")

            with ui.element("div").classes("pause-actions"):
                ui.button(
                    "Resume Now",
                    icon="play_arrow",
                    on_click=self._on_resume,
                ).classes("btn btn-primary btn-lg").props("no-caps")
                ui.button(
                    "Stop Workout",
                    icon="stop",
                    on_click=self._on_stop,
                ).classes("btn btn-destructive btn-lg").props("no-caps")

        self._pause_overlay.set_visibility(False)

    # ── Public interface ──────────────────────────────────────────────────

    def set_workout_name(self, name: str | None) -> None:
        """Show workout name in header, or revert to load buttons when *name* is falsy."""
        if name:
            self._workout_name_label.set_text(str(name).strip())
            self._header_name_area.set_visibility(True)
            self._header_load_area.set_visibility(False)
        else:
            self._header_name_area.set_visibility(False)
            self._header_load_area.set_visibility(True)

    def set_mandatory_metrics(
        self,
        *,
        elapsed_text: str,
        remaining_text: str,
        interval_remaining_text: str,
        target_power_text: str,
    ) -> None:
        self._elapsed_tile.set_value(elapsed_text)
        self._target_tile.set_value(target_power_text)
        self._interval_tile.set_value(interval_remaining_text)
        self._remaining_tile.set_value(remaining_text)

    def set_session_state(self, state: str) -> None:
        """Enable/disable control buttons to match engine *state* string."""
        s = str(state).strip().lower()
        can_start = s in {"idle", "ready", "stopped", "finished"}
        can_pause = s in {"running", "ramp_in"}
        can_resume = s == "paused"
        can_stop = s in {"running", "ramp_in", "paused"}

        _set_enabled(self._start_btn, can_start)
        _set_enabled(self._pause_btn, can_pause)
        _set_enabled(self._resume_btn, can_resume)
        _set_enabled(self._stop_btn, can_stop)

        self._pause_overlay.set_visibility(can_resume)

    def set_mode_state(self, mode: str) -> None:
        if mode in MODE_OPTIONS and self._mode_select.value != mode:
            self._mode_select.set_value(mode)

    def set_resistance_level(self, level: int | None) -> None:
        if level is None:
            self._resistance_area.set_visibility(False)
        else:
            self._resistance_label.set_text(f"{level} %")
            self._resistance_area.set_visibility(True)

    def set_opentrueup_offset_watts(self, offset_watts: int | None) -> None:
        text = f"{int(offset_watts)} W" if offset_watts is not None else "-- W"
        self._opentrueup_label.set_text(text)

    def set_trainer_controls_visible(self, visible: bool) -> None:
        self._trainer_footer.set_visibility(visible)
        if not visible:
            self._resistance_area.set_visibility(False)

    def set_tile_value(self, key: str, text: str) -> None:
        tile = self._tile_by_key.get(key)
        if tile is not None:
            tile.set_value(text)

    def show_alert(self, message: str, alert_type: str = "error") -> None:
        kind = alert_type if alert_type in {"error", "success", "warning"} else "error"
        self._alert.show(message.strip(), kind)

    def clear_alert(self) -> None:
        self._alert.hide()

    def set_pause_elapsed(self, elapsed_text: str) -> None:
        """Update elapsed time shown on the pause overlay."""
        self._pause_elapsed.set_text(elapsed_text)

    def set_pause_countdown(self, n: int | None) -> None:
        """Show countdown digits (3→2→1); pass None to clear."""
        self._pause_countdown.set_text(str(n) if n is not None else "")

    def get_selected_tile_keys(self) -> list[str]:
        return list(self._selected_tiles)

    def apply_settings(self, settings: AppSettings) -> None:
        """Apply updated settings. Tile grid changes take effect on next page load."""
        self._settings = settings
        self._selected_tiles = normalize_tile_selections(settings.tile_selections)
        self._kj_mode = settings.default_workout_behavior == "kj_mode"

    def handle_hotkey(self, key: str) -> None:
        """Route a JS keyboard event key name to the appropriate workout action."""
        if key == "T":
            self._cycle_mode()
        elif key == "1":
            self._on_extend(10 if self._kj_mode else 60, self._kj_mode)
        elif key == "5":
            self._on_extend(50 if self._kj_mode else 300, self._kj_mode)
        elif key == "Tab":
            self._on_skip()
        elif key == "ArrowUp":
            self._on_jog(1)
        elif key == "ArrowDown":
            self._on_jog(-1)
        elif key == "ArrowRight":
            self._on_jog(5)
        elif key == "ArrowLeft":
            self._on_jog(-5)
        elif key == " ":
            if self._pause_overlay.visible:
                self._on_resume()
            else:
                self._on_pause()

    def _cycle_mode(self) -> None:
        try:
            idx = list(MODE_OPTIONS).index(self._mode_select.value or "ERG")
        except ValueError:
            idx = 0
        next_mode = MODE_OPTIONS[(idx + 1) % len(MODE_OPTIONS)]
        self.set_mode_state(next_mode)
        self._on_mode_changed(next_mode)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_enabled(btn: ui.button, enabled: bool) -> None:
    """Toggle the Quasar disabled prop on a button."""
    if enabled:
        btn.props(remove="disabled")
    else:
        btn.props(add="disabled")
