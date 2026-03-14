from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.ui.workout_library_screen import WorkoutLibraryScreen, _format_duration

_DATA_DIR = Path(__file__).parent / "data"
_STEP_MRC = _DATA_DIR / "step_only.mrc"
_RAMP_MRC = _DATA_DIR / "ramp.mrc"


def _get_qapp() -> QApplication:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_screen(tmp_path, *, user_files=(), prepackaged_files=()):
    user_dir = tmp_path / "user"
    prepackaged_dir = tmp_path / "prepackaged"
    user_dir.mkdir()
    prepackaged_dir.mkdir()
    for src in user_files:
        shutil.copy2(src, user_dir / src.name)
    for src in prepackaged_files:
        shutil.copy2(src, prepackaged_dir / src.name)
    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=prepackaged_dir)
    _get_qapp()
    return WorkoutLibraryScreen(library=lib), lib, user_dir


# ── Table population ──────────────────────────────────────────────────────────

def test_rows_populated_from_library(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])

    assert screen.table.rowCount() == 2


def test_row_shows_name_and_formatted_duration(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC])

    assert screen.table.item(0, 0).text() == "step_only"
    assert screen.table.item(0, 1).text() == "0:15:00"


def test_empty_library_shows_no_rows(tmp_path):
    screen, _, _ = _make_screen(tmp_path)

    assert screen.table.rowCount() == 0


# ── Sorting ───────────────────────────────────────────────────────────────────

def test_default_sort_is_name_ascending(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    names = [screen.table.item(r, 0).text() for r in range(screen.table.rowCount())]
    assert names == sorted(names)


def test_click_name_header_toggles_to_descending(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    screen.table.horizontalHeader().sectionClicked.emit(0)

    names = [screen.table.item(r, 0).text() for r in range(screen.table.rowCount())]
    assert names == sorted(names, reverse=True)


def test_click_name_header_twice_returns_to_ascending(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    screen.table.horizontalHeader().sectionClicked.emit(0)
    screen.table.horizontalHeader().sectionClicked.emit(0)

    names = [screen.table.item(r, 0).text() for r in range(screen.table.rowCount())]
    assert names == sorted(names)


def test_click_duration_header_sorts_by_duration(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    screen.table.horizontalHeader().sectionClicked.emit(1)

    durations = [
        screen.table.item(r, 1).data(Qt.UserRole + 1)
        for r in range(screen.table.rowCount())
    ]
    assert durations == sorted(durations)


# ── Search / filter ───────────────────────────────────────────────────────────

def test_search_filters_rows_by_name(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])

    screen.search_input.setText("step")

    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 0).text() == "step_only"


def test_search_is_case_insensitive(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC])

    screen.search_input.setText("STEP")

    assert screen.table.rowCount() == 1


def test_search_cleared_shows_all_rows(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])

    screen.search_input.setText("step")
    screen.search_input.setText("")

    assert screen.table.rowCount() == 2


# ── Double-click emits signal ─────────────────────────────────────────────────

def test_double_click_emits_workout_selected(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC])
    received: list[Path] = []
    screen.workout_selected.connect(received.append)

    screen.table.cellDoubleClicked.emit(0, 0)

    assert len(received) == 1
    assert received[0].name == "step_only.mrc"


def test_double_click_emits_correct_path_for_each_row(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])
    received: list[Path] = []
    screen.workout_selected.connect(received.append)

    for row in range(screen.table.rowCount()):
        screen.table.cellDoubleClicked.emit(row, 0)

    names = {p.stem for p in received}
    assert names == {"step_only", "ramp"}


# ── Duration formatting ───────────────────────────────────────────────────────

def test_format_duration_minutes_and_seconds():
    assert _format_duration(900) == "0:15:00"


def test_format_duration_over_one_hour():
    assert _format_duration(3661) == "1:01:01"


def test_format_duration_zero():
    assert _format_duration(0) == "0:00:00"
