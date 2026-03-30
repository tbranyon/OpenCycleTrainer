from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from opencycletrainer.core.workout_library import WorkoutLibrary, WorkoutLibraryEntry

_DATA_DIR = Path(__file__).parent / "data"
_STEP_MRC = _DATA_DIR / "step_only.mrc"   # 15-minute workout → 900 seconds
_RAMP_MRC = _DATA_DIR / "ramp.mrc"


def _make_library(tmp_path, *, user_files=(), prepackaged_files=()):
    user_dir = tmp_path / "user"
    prepackaged_dir = tmp_path / "prepackaged"
    user_dir.mkdir()
    prepackaged_dir.mkdir()
    for src in user_files:
        shutil.copy2(src, user_dir / src.name)
    for src in prepackaged_files:
        shutil.copy2(src, prepackaged_dir / src.name)
    return WorkoutLibrary(user_dir=user_dir, prepackaged_dir=prepackaged_dir)


def test_entries_populated_from_user_dir(tmp_path):
    lib = _make_library(tmp_path, user_files=[_STEP_MRC])

    assert len(lib.entries) == 1
    entry = lib.entries[0]
    assert entry.name == "step_only"
    assert entry.duration_seconds == 900


def test_entries_populated_from_prepackaged_dir(tmp_path):
    lib = _make_library(tmp_path, prepackaged_files=[_RAMP_MRC])

    assert len(lib.entries) == 1
    assert lib.entries[0].name == "ramp"


def test_entries_combined_from_both_dirs(tmp_path):
    lib = _make_library(tmp_path, user_files=[_STEP_MRC], prepackaged_files=[_RAMP_MRC])

    names = {e.name for e in lib.entries}
    assert names == {"step_only", "ramp"}


def test_duplicate_filename_in_both_dirs_shows_both(tmp_path):
    lib = _make_library(tmp_path, user_files=[_STEP_MRC], prepackaged_files=[_STEP_MRC])

    assert len(lib.entries) == 2
    assert all(e.name == "step_only" for e in lib.entries)


def test_unparseable_file_is_skipped(tmp_path):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    bad_file = user_dir / "bad.mrc"
    bad_file.write_text("not a valid mrc file", encoding="utf-8")

    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=tmp_path / "empty")

    assert lib.entries == []


def test_add_workout_copies_file_and_appears_in_entries(tmp_path):
    lib = _make_library(tmp_path)
    assert lib.entries == []

    entry = lib.add_workout(_STEP_MRC)

    assert isinstance(entry, WorkoutLibraryEntry)
    assert entry.name == "step_only"
    assert entry.path.parent == (tmp_path / "user")
    assert entry.path.exists()
    assert len(lib.entries) == 1


def test_add_workout_refresh_updates_entries(tmp_path):
    lib = _make_library(tmp_path)
    lib.add_workout(_STEP_MRC)
    assert len(lib.entries) == 1

    lib.add_workout(_RAMP_MRC)
    assert len(lib.entries) == 2


def test_refresh_picks_up_new_files(tmp_path):
    lib = _make_library(tmp_path)
    assert lib.entries == []

    shutil.copy2(_STEP_MRC, tmp_path / "user" / _STEP_MRC.name)
    lib.refresh()

    assert len(lib.entries) == 1


def test_missing_prepackaged_dir_is_ignored(tmp_path):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    shutil.copy2(_STEP_MRC, user_dir / _STEP_MRC.name)
    missing_dir = tmp_path / "nonexistent"

    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=missing_dir)

    assert len(lib.entries) == 1


def test_entry_duration_matches_parsed_workout(tmp_path):
    lib = _make_library(tmp_path, user_files=[_STEP_MRC])

    entry = lib.entries[0]
    # step_only.mrc: 0-5 min, 5-10 min, 10-15 min → 3 × 300 = 900 seconds
    assert entry.duration_seconds == 900


# ── Category field ────────────────────────────────────────────────────────────

_MRC_WITH_CATEGORY = """[COURSE HEADER]
VERSION = 2
CATEGORY = SST
[END COURSE HEADER]
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]
"""

_MRC_WITHOUT_CATEGORY = """[COURSE HEADER]
VERSION = 2
[END COURSE HEADER]
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]
"""


def _write_mrc(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_entry_category_empty_when_no_category_header(tmp_path):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    _write_mrc(user_dir, "workout.mrc", _MRC_WITHOUT_CATEGORY)

    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=tmp_path / "empty")

    assert lib.entries[0].category == ""


def test_entry_category_populated_from_mrc_header(tmp_path):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    _write_mrc(user_dir, "workout.mrc", _MRC_WITH_CATEGORY)

    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=tmp_path / "empty")

    assert lib.entries[0].category == "SST"


def test_add_workout_from_text_writes_file_and_returns_entry(tmp_path):
    lib = _make_library(tmp_path)

    entry = lib.add_workout_from_text(_MRC_WITHOUT_CATEGORY, "my_workout.mrc")

    assert isinstance(entry, WorkoutLibraryEntry)
    assert entry.name == "my_workout"
    assert entry.path.name == "my_workout.mrc"
    assert entry.path.exists()
    assert len(lib.entries) == 1


def test_add_workout_from_text_category_preserved(tmp_path):
    lib = _make_library(tmp_path)

    entry = lib.add_workout_from_text(_MRC_WITH_CATEGORY, "sst_workout.mrc")

    assert entry.category == "SST"
