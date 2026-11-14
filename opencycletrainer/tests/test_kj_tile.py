from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from opencycletrainer.ui.workout_screen import KJMetricTile


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _combo_keys(tile: KJMetricTile) -> list[str]:
    combo = tile._source_combo
    return [combo.itemData(i) for i in range(combo.count())]


def test_unchanged_sources_do_not_rebuild_the_combo():
    _get_or_create_qapp()
    tile = KJMetricTile(title="kJ", key="kj_work_completed")
    tile.set_available_sources(["calculated", "pm"])
    removals: list[int] = []
    tile._source_combo.model().rowsRemoved.connect(lambda *args: removals.append(1))

    for _ in range(5):
        tile.set_available_sources(["calculated", "pm"])

    assert removals == []
    assert _combo_keys(tile) == ["calculated", "pm"]


def test_changed_sources_rebuild_and_keep_selection():
    _get_or_create_qapp()
    tile = KJMetricTile(title="kJ", key="kj_work_completed")
    tile.set_available_sources(["calculated", "pm"])
    tile._source_combo.setCurrentIndex(1)

    tile.set_available_sources(["calculated", "pm", "ftms"])

    assert _combo_keys(tile) == ["calculated", "pm", "ftms"]
    assert tile._source_combo.currentData() == "pm"


def test_removed_selected_source_falls_back_to_calculated_and_notifies():
    _get_or_create_qapp()
    tile = KJMetricTile(title="kJ", key="kj_work_completed")
    tile.set_available_sources(["calculated", "pm"])
    tile._source_combo.setCurrentIndex(1)
    emitted: list[str] = []
    tile.kj_source_changed.connect(emitted.append)

    tile.set_available_sources(["calculated"])

    assert tile._source_combo.currentData() == "calculated"
    assert emitted == ["calculated"]
