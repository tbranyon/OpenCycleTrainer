from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.ui.workout_library_screen import WorkoutLibraryScreen, _format_duration

_DATA_DIR = Path(__file__).parent / "data"
_STEP_MRC = _DATA_DIR / "step_only.mrc"
_RAMP_MRC = _DATA_DIR / "ramp.mrc"

_MRC_SST = (
    "[COURSE HEADER]\n"
    "VERSION = 2\n"
    "CATEGORY = SST\n"
    "[END COURSE HEADER]\n"
    "[COURSE DATA]\n"
    "0.0\t50.0\n"
    "5.0\t50.0\n"
    "[END COURSE DATA]\n"
)

_MRC_THRESHOLD = (
    "[COURSE HEADER]\n"
    "VERSION = 2\n"
    "CATEGORY = Threshold\n"
    "[END COURSE HEADER]\n"
    "[COURSE DATA]\n"
    "0.0\t50.0\n"
    "10.0\t50.0\n"
    "[END COURSE DATA]\n"
)


def _get_qapp() -> QApplication:
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
    return WorkoutLibraryScreen(library=lib, ftp_getter=lambda: 250), lib, user_dir


def _make_screen_with_mrc_text(tmp_path, mrc_texts: dict[str, str]):
    """Create a screen with custom MRC text content keyed by filename."""
    user_dir = tmp_path / "user"
    prepackaged_dir = tmp_path / "prepackaged"
    user_dir.mkdir()
    prepackaged_dir.mkdir()
    for filename, text in mrc_texts.items():
        (user_dir / filename).write_text(text, encoding="utf-8")
    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=prepackaged_dir)
    _get_qapp()
    return WorkoutLibraryScreen(library=lib, ftp_getter=lambda: 250), lib, user_dir


# ── Table population ──────────────────────────────────────────────────────────

def test_rows_populated_from_library(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])

    assert screen.table.rowCount() == 2


def test_row_shows_name_and_formatted_duration(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC])

    assert screen.table.item(0, 1).text() == "step_only"
    assert screen.table.item(0, 2).text() == "0:15:00"


def test_empty_library_shows_no_rows(tmp_path):
    screen, _, _ = _make_screen(tmp_path)

    assert screen.table.rowCount() == 0


# ── Table structure (3 columns) ────────────────────────────────────────────────

def test_table_has_three_columns(tmp_path):
    screen, _, _ = _make_screen(tmp_path)

    assert screen.table.columnCount() == 3


def test_column_headers_are_category_name_duration(tmp_path):
    screen, _, _ = _make_screen(tmp_path)

    assert screen.table.horizontalHeaderItem(0).text() == "Category"
    assert screen.table.horizontalHeaderItem(1).text() == "Name"
    assert screen.table.horizontalHeaderItem(2).text() == "Duration"


def test_category_column_shows_entry_category(tmp_path):
    screen, _, _ = _make_screen_with_mrc_text(tmp_path, {"sst.mrc": _MRC_SST})

    assert screen.table.item(0, 0).text() == "SST"


def test_category_column_empty_when_no_category(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC])

    assert screen.table.item(0, 0).text() == ""


def test_sort_by_category_column(tmp_path):
    screen, _, _ = _make_screen_with_mrc_text(
        tmp_path, {"threshold.mrc": _MRC_THRESHOLD, "sst.mrc": _MRC_SST}
    )

    screen.table.horizontalHeader().sectionClicked.emit(0)

    cats = [screen.table.item(r, 0).text() for r in range(screen.table.rowCount())]
    assert cats == sorted(cats)


# ── Category filter combo ─────────────────────────────────────────────────────

def test_category_filter_combo_initialized_with_all_categories(tmp_path):
    screen, _, _ = _make_screen_with_mrc_text(
        tmp_path, {"sst.mrc": _MRC_SST, "threshold.mrc": _MRC_THRESHOLD}
    )

    items = [screen.category_combo.itemText(i) for i in range(screen.category_combo.count())]
    assert "All" in items
    assert "SST" in items
    assert "Threshold" in items


def test_category_filter_filters_table(tmp_path):
    screen, _, _ = _make_screen_with_mrc_text(
        tmp_path, {"sst.mrc": _MRC_SST, "threshold.mrc": _MRC_THRESHOLD}
    )

    idx = screen.category_combo.findText("SST")
    screen.category_combo.setCurrentIndex(idx)

    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 0).text() == "SST"


def test_category_filter_all_shows_all_rows(tmp_path):
    screen, _, _ = _make_screen_with_mrc_text(
        tmp_path, {"sst.mrc": _MRC_SST, "threshold.mrc": _MRC_THRESHOLD}
    )

    idx = screen.category_combo.findText("SST")
    screen.category_combo.setCurrentIndex(idx)
    assert screen.table.rowCount() == 1

    all_idx = screen.category_combo.findText("All")
    screen.category_combo.setCurrentIndex(all_idx)
    assert screen.table.rowCount() == 2


# ── Sorting (updated column indices) ──────────────────────────────────────────

def test_default_sort_is_name_ascending(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    names = [screen.table.item(r, 1).text() for r in range(screen.table.rowCount())]
    assert names == sorted(names)


def test_click_name_header_toggles_to_descending(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    screen.table.horizontalHeader().sectionClicked.emit(1)

    names = [screen.table.item(r, 1).text() for r in range(screen.table.rowCount())]
    assert names == sorted(names, reverse=True)


def test_click_name_header_twice_returns_to_ascending(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    screen.table.horizontalHeader().sectionClicked.emit(1)
    screen.table.horizontalHeader().sectionClicked.emit(1)

    names = [screen.table.item(r, 1).text() for r in range(screen.table.rowCount())]
    assert names == sorted(names)


def test_click_duration_header_sorts_by_duration(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_RAMP_MRC, _STEP_MRC])

    screen.table.horizontalHeader().sectionClicked.emit(2)

    durations = [
        screen.table.item(r, 2).data(Qt.UserRole + 1)
        for r in range(screen.table.rowCount())
    ]
    assert durations == sorted(durations)


# ── Search / filter ───────────────────────────────────────────────────────────

def test_search_filters_rows_by_name(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])

    screen.search_input.setText("step")

    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 1).text() == "step_only"


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

    screen.table.cellDoubleClicked.emit(0, 1)

    assert len(received) == 1
    assert received[0].name == "step_only.mrc"


def test_double_click_emits_correct_path_for_each_row(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC, _RAMP_MRC])
    received: list[Path] = []
    screen.workout_selected.connect(received.append)

    for row in range(screen.table.rowCount()):
        screen.table.cellDoubleClicked.emit(row, 1)

    names = {p.stem for p in received}
    assert names == {"step_only", "ramp"}


# ── Duration formatting ───────────────────────────────────────────────────────

def test_format_duration_minutes_and_seconds():
    assert _format_duration(900) == "0:15:00"


def test_format_duration_over_one_hour():
    assert _format_duration(3661) == "1:01:01"


def test_format_duration_zero():
    assert _format_duration(0) == "0:00:00"


# ── _CategoryDialog ───────────────────────────────────────────────────────────

def test_category_dialog_shows_existing_categories_and_add_new():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import _CategoryDialog

    dialog = _CategoryDialog(["SST", "Threshold"])
    items = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]
    assert "SST" in items
    assert "Threshold" in items
    assert "Add new..." in items


def test_category_dialog_text_field_hidden_initially():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import _CategoryDialog

    dialog = _CategoryDialog(["SST"])
    assert dialog.line_edit.isHidden()


def test_category_dialog_reveals_text_field_on_add_new():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import _CategoryDialog

    dialog = _CategoryDialog(["SST"])
    idx = dialog.combo.findText("Add new...")
    dialog.combo.setCurrentIndex(idx)
    assert not dialog.line_edit.isHidden()


def test_category_dialog_selected_category_returns_combo_text():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import _CategoryDialog

    dialog = _CategoryDialog(["SST", "Threshold"])
    idx = dialog.combo.findText("SST")
    dialog.combo.setCurrentIndex(idx)
    assert dialog.selected_category() == "SST"


def test_category_dialog_selected_category_returns_typed_text_on_add_new():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import _CategoryDialog

    dialog = _CategoryDialog(["SST"])
    idx = dialog.combo.findText("Add new...")
    dialog.combo.setCurrentIndex(idx)
    dialog.line_edit.setText("MyCategory")
    assert dialog.selected_category() == "MyCategory"


def test_category_dialog_selected_category_empty_on_blank_selection():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import _CategoryDialog

    dialog = _CategoryDialog(["SST"])
    dialog.combo.setCurrentIndex(0)  # blank/no-category item
    assert dialog.selected_category() == ""


# ── WorkoutPreviewPane ────────────────────────────────────────────────────────

def test_preview_pane_initial_state_shows_placeholder():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    assert pane._name_label.text() != ""


def test_preview_pane_stats_are_dashes_initially():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    for label in (pane._duration_label, pane._np_label, pane._kj_label, pane._tss_label):
        assert label.text() == "—"


def test_preview_pane_load_populates_name_label():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    pane.load(_STEP_MRC)
    assert pane._name_label.text() == "Step Session"


def test_preview_pane_load_populates_chart_data():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    pane.load(_STEP_MRC)
    x, y = pane._target_item.getData()
    assert x is not None and len(x) > 0


def test_preview_pane_load_populates_duration_stat():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    pane.load(_STEP_MRC)
    # step_only.mrc is 15 minutes = 900 seconds → "0:15:00"
    assert "15" in pane._duration_label.text()


def test_preview_pane_load_populates_np_kj_tss_stats():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    pane.load(_STEP_MRC)
    assert pane._np_label.text() != "—"
    assert pane._kj_label.text() != "—"
    assert pane._tss_label.text() != "—"


def test_preview_pane_clear_resets_all_labels():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    pane.load(_STEP_MRC)
    pane.clear()
    for label in (pane._duration_label, pane._np_label, pane._kj_label, pane._tss_label):
        assert label.text() == "—"


def test_preview_pane_invalid_path_clears_gracefully():
    _get_qapp()
    from opencycletrainer.ui.workout_library_screen import WorkoutPreviewPane

    pane = WorkoutPreviewPane(ftp_getter=lambda: 250)
    pane.load(_STEP_MRC)
    pane.load(Path("/nonexistent/path.mrc"))
    for label in (pane._duration_label, pane._np_label, pane._kj_label, pane._tss_label):
        assert label.text() == "—"


def test_single_click_row_triggers_preview_load(tmp_path):
    screen, _, _ = _make_screen(tmp_path, user_files=[_STEP_MRC])

    screen.table.cellClicked.emit(0, 1)

    assert screen._preview_pane._name_label.text() == "Step Session"


# ── Stat functions ────────────────────────────────────────────────────────────

def _make_flat_workout(watts: int = 200, duration_s: int = 300) -> Workout:
    return Workout(
        name="Flat",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=duration_s,
                start_percent_ftp=100.0,
                end_percent_ftp=100.0,
                start_target_watts=watts,
                end_target_watts=watts,
            ),
        ),
    )


def _make_ramp_workout(start_w: int = 100, end_w: int = 200, duration_s: int = 300) -> Workout:
    return Workout(
        name="Ramp",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=duration_s,
                start_percent_ftp=50.0,
                end_percent_ftp=100.0,
                start_target_watts=start_w,
                end_target_watts=end_w,
            ),
        ),
    )


def test_compute_target_kj_flat_interval():
    from opencycletrainer.ui.workout_library_screen import _compute_target_kj

    workout = _make_flat_workout(watts=200, duration_s=300)
    # (200 + 200) / 2 * 300 / 1000 = 60 kJ
    assert _compute_target_kj(workout) == pytest.approx(60.0)


def test_compute_target_kj_ramp_interval():
    from opencycletrainer.ui.workout_library_screen import _compute_target_kj

    workout = _make_ramp_workout(start_w=100, end_w=200, duration_s=300)
    # (100 + 200) / 2 * 300 / 1000 = 45 kJ
    assert _compute_target_kj(workout) == pytest.approx(45.0)


def test_compute_target_kj_zero_intervals():
    from opencycletrainer.ui.workout_library_screen import _compute_target_kj

    workout = Workout(name="Empty", ftp_watts=200, intervals=())
    assert _compute_target_kj(workout) == pytest.approx(0.0)


def test_compute_target_np_flat_workout_approximates_power():
    from opencycletrainer.ui.workout_library_screen import _compute_target_np

    # Flat 200W for 600s — NP should be very close to 200
    workout = _make_flat_workout(watts=200, duration_s=600)
    np_val = _compute_target_np(workout)
    assert abs(np_val - 200) <= 5


def test_compute_target_np_returns_int():
    from opencycletrainer.ui.workout_library_screen import _compute_target_np

    workout = _make_flat_workout(watts=200, duration_s=600)
    assert isinstance(_compute_target_np(workout), int)
