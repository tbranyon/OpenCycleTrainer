"""Tests for NiceGUI library screen logic (Phase 5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.core.workout_library import WorkoutLibraryEntry


# ---------------------------------------------------------------------------
# Import helpers under test (pure functions, no NiceGUI dependency)
# ---------------------------------------------------------------------------

from opencycletrainer.ui.library_screen_ng import (
    filter_library_entries,
    format_duration,
    sort_library_entries,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _entry(name: str, duration_seconds: int) -> WorkoutLibraryEntry:
    return WorkoutLibraryEntry(name=name, path=Path(f"/workouts/{name}.mrc"), duration_seconds=duration_seconds)


@pytest.fixture()
def entries() -> list[WorkoutLibraryEntry]:
    return [
        _entry("Vo2Max Intervals", 3900),
        _entry("Sweet Spot Base", 3300),
        _entry("Recovery Ride", 2700),
        _entry("Tempo Efforts", 4200),
    ]


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------


def test_format_duration_zero() -> None:
    assert format_duration(0) == "0:00:00"


def test_format_duration_under_one_hour() -> None:
    assert format_duration(3600 - 1) == "0:59:59"


def test_format_duration_exactly_one_hour() -> None:
    assert format_duration(3600) == "1:00:00"


def test_format_duration_over_one_hour() -> None:
    assert format_duration(3900) == "1:05:00"


def test_format_duration_negative_treated_as_zero() -> None:
    assert format_duration(-10) == "0:00:00"


# ---------------------------------------------------------------------------
# filter_library_entries
# ---------------------------------------------------------------------------


def test_filter_empty_text_returns_all(entries: list[WorkoutLibraryEntry]) -> None:
    result = filter_library_entries(entries, "")
    assert len(result) == len(entries)


def test_filter_matches_substring(entries: list[WorkoutLibraryEntry]) -> None:
    result = filter_library_entries(entries, "vo2")
    assert len(result) == 1
    assert result[0].name == "Vo2Max Intervals"


def test_filter_case_insensitive(entries: list[WorkoutLibraryEntry]) -> None:
    result = filter_library_entries(entries, "BASE")
    assert len(result) == 1
    assert result[0].name == "Sweet Spot Base"


def test_filter_no_match_returns_empty(entries: list[WorkoutLibraryEntry]) -> None:
    result = filter_library_entries(entries, "zzznomatch")
    assert result == []


def test_filter_matches_multiple(entries: list[WorkoutLibraryEntry]) -> None:
    result = filter_library_entries(entries, "e")  # appears in many names
    assert all("e" in e.name.lower() for e in result)


# ---------------------------------------------------------------------------
# sort_library_entries
# ---------------------------------------------------------------------------


def test_sort_by_name_ascending(entries: list[WorkoutLibraryEntry]) -> None:
    result = sort_library_entries(entries, column="name", descending=False)
    names = [e.name for e in result]
    assert names == sorted(names, key=str.lower)


def test_sort_by_name_descending(entries: list[WorkoutLibraryEntry]) -> None:
    result = sort_library_entries(entries, column="name", descending=True)
    names = [e.name for e in result]
    assert names == sorted(names, key=str.lower, reverse=True)


def test_sort_by_duration_ascending(entries: list[WorkoutLibraryEntry]) -> None:
    result = sort_library_entries(entries, column="duration", descending=False)
    durations = [e.duration_seconds for e in result]
    assert durations == sorted(durations)


def test_sort_by_duration_descending(entries: list[WorkoutLibraryEntry]) -> None:
    result = sort_library_entries(entries, column="duration", descending=True)
    durations = [e.duration_seconds for e in result]
    assert durations == sorted(durations, reverse=True)


def test_sort_unknown_column_sorts_by_name(entries: list[WorkoutLibraryEntry]) -> None:
    """Unknown column falls back to name sort."""
    result = sort_library_entries(entries, column="unknown", descending=False)
    names = [e.name for e in result]
    assert names == sorted(names, key=str.lower)


def test_sort_preserves_all_entries(entries: list[WorkoutLibraryEntry]) -> None:
    result = sort_library_entries(entries, column="name", descending=False)
    assert len(result) == len(entries)
    assert set(e.name for e in result) == set(e.name for e in entries)
