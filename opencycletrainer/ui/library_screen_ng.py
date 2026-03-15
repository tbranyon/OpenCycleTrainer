"""NiceGUI Library Screen — Phase 5.

Ports WorkoutLibraryScreen from PySide6 to NiceGUI.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from opencycletrainer.core.workout_library import WorkoutLibrary, WorkoutLibraryEntry
from .components import screen_header

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure logic helpers (tested independently)
# ---------------------------------------------------------------------------


def format_duration(total_seconds: int) -> str:
    """Format *total_seconds* as H:MM:SS."""
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02}:{secs:02}"


def filter_library_entries(
    entries: list[WorkoutLibraryEntry],
    search_text: str,
) -> list[WorkoutLibraryEntry]:
    """Return entries whose names contain *search_text* (case-insensitive)."""
    if not search_text:
        return list(entries)
    lower = search_text.lower()
    return [e for e in entries if lower in e.name.lower()]


def sort_library_entries(
    entries: list[WorkoutLibraryEntry],
    *,
    column: str,
    descending: bool,
) -> list[WorkoutLibraryEntry]:
    """Return *entries* sorted by *column* ('name' or 'duration')."""
    if column == "duration":
        key = lambda e: e.duration_seconds  # noqa: E731
    else:
        key = lambda e: e.name.lower()  # noqa: E731
    return sorted(entries, key=key, reverse=descending)


# ---------------------------------------------------------------------------
# LibraryScreen
# ---------------------------------------------------------------------------


class LibraryScreen:
    """NiceGUI workout library screen with search, sort, and load capabilities."""

    _COLUMNS = [
        {
            "name": "name",
            "label": "Name",
            "field": "name",
            "sortable": True,
            "align": "left",
            "classes": "library-col-name",
        },
        {
            "name": "duration",
            "label": "Duration",
            "field": "duration_str",
            "sortable": True,
            "align": "left",
            "style": "width: 120px",
        },
        {
            "name": "actions",
            "label": "",
            "field": "actions",
            "sortable": False,
            "align": "right",
            "style": "width: 80px",
        },
    ]

    def __init__(
        self,
        library: WorkoutLibrary,
        on_load_workout: Callable[[Path], None],
    ) -> None:
        self._library = library
        self._on_load_workout = on_load_workout
        self._search_text = ""

        actions = screen_header("Library")
        with actions:
            ui.button(
                "Add to Library",
                icon="add",
                on_click=lambda: asyncio.ensure_future(self._async_add()),
            ).classes("btn btn-secondary btn-sm").props("no-caps flat")

        with ui.element("div").classes("library-toolbar"):
            self._search_input = (
                ui.input(placeholder="Search workouts…", on_change=self._on_search_changed)
                .classes("library-search-input")
                .props("clearable outlined dense")
            )
            with self._search_input:
                ui.icon("search").props("slot=prepend")

        self._table = ui.table(
            columns=self._COLUMNS,
            rows=[],
            row_key="path_str",
        ).classes("library-table").props("flat dense")

        self._table.add_slot(
            "body-cell-actions",
            r"""
            <q-td :props="props">
              <button class="btn btn-secondary btn-sm"
                      style="cursor:pointer"
                      @click="$parent.$emit('load-row', props.row)">
                Load
              </button>
            </q-td>
            """,
        )
        self._table.on("load-row", self._handle_load_event)

        with ui.element("div").classes("placeholder-page") as self._empty_state:
            ui.icon("menu_book").classes("placeholder-icon")
            ui.label("No workouts yet").classes("placeholder-label")
            ui.label("Add workouts to your library using the button above").classes(
                "placeholder-sub"
            )

        self._refresh()

    # ── Callbacks ─────────────────────────────────────────────────────────

    def _on_search_changed(self, e: object) -> None:
        self._search_text = (getattr(e, "value", "") or "").strip()
        self._refresh()

    def _handle_load_event(self, e: object) -> None:
        row: dict = getattr(e, "args", {}) or {}
        path_str = row.get("path_str") if isinstance(row, dict) else None
        if path_str:
            self._on_load_workout(Path(path_str))

    async def _async_add(self) -> None:
        path_str = await asyncio.to_thread(self._open_add_dialog)
        if not path_str:
            return
        try:
            self._library.add_workout(Path(path_str))
        except Exception as exc:
            _logger.warning("Failed to add workout: %s", exc)
        self._refresh()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """Filter, sort, and rebuild table rows."""
        filtered = filter_library_entries(self._library.entries, self._search_text)
        sorted_entries = sort_library_entries(filtered, column="name", descending=False)
        rows = [
            {
                "name": e.name,
                "duration_str": format_duration(e.duration_seconds),
                "path_str": str(e.path),
            }
            for e in sorted_entries
        ]
        self._table.rows = rows
        self._table.update()
        self._empty_state.set_visibility(len(rows) == 0)

    def refresh_library(self) -> None:
        """Rescan library directories and repopulate the table."""
        self._library.refresh()
        self._refresh()

    @staticmethod
    def _open_add_dialog() -> str:
        try:
            import tkinter as tk  # noqa: PLC0415
            from tkinter import filedialog  # noqa: PLC0415

            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Add Workout to Library",
                initialdir=str(Path.home()),
                filetypes=[("MRC Files", "*.mrc"), ("All Files", "*.*")],
            )
            root.destroy()
            return path or ""
        except Exception as exc:
            _logger.warning("File dialog error: %s", exc)
            return ""
