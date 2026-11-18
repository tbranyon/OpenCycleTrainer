"""Opening library workouts in the builder for editing."""

from __future__ import annotations

from pathlib import Path

from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.ui.workout_builder_screen import WorkoutBuilderScreen

_DATA_DIR = Path(__file__).parent / "data"


def test_an_erg_workout_opens_for_editing(qapp, tmp_path):
    library = WorkoutLibrary(user_dir=tmp_path / "user", prepackaged_dir=tmp_path / "prepackaged")
    screen = WorkoutBuilderScreen(library=library, ftp_getter=lambda: 250)
    try:
        screen.load_for_edit(_DATA_DIR / "steady.erg")

        assert screen._name_edit.text() == "Steady Watts"
        assert screen._text_edit.toPlainText().strip() == "- 5m 80%"
        assert screen._editing_path == _DATA_DIR / "steady.erg"
    finally:
        screen.deleteLater()
        qapp.processEvents()
