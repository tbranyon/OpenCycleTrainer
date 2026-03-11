from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.workout_screen import WorkoutScreen


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _show_screen(settings: AppSettings | None = None) -> WorkoutScreen:
    app = _get_or_create_qapp()
    screen = WorkoutScreen(settings=settings or AppSettings())
    screen.show()
    screen.activateWindow()
    screen.setFocus(Qt.ActiveWindowFocusReason)
    app.processEvents()
    return screen


def test_hotkey_t_cycles_mode():
    app = _get_or_create_qapp()
    screen = _show_screen()

    QTest.keyClick(screen, Qt.Key_T)
    app.processEvents()
    assert screen.mode_selector.currentText() == "Resistance"

    QTest.keyClick(screen, Qt.Key_T)
    app.processEvents()
    assert screen.mode_selector.currentText() == "Hybrid"


def test_hotkeys_1_and_5_emit_time_extensions_in_workout_mode():
    app = _get_or_create_qapp()
    screen = _show_screen(settings=AppSettings(default_workout_behavior="workout_mode"))
    requested: list[tuple[int, bool]] = []
    screen.extend_interval_requested.connect(lambda value, is_kj: requested.append((value, is_kj)))

    QTest.keyClick(screen, Qt.Key_1)
    QTest.keyClick(screen, Qt.Key_5)
    app.processEvents()

    assert requested == [(60, False), (300, False)]


def test_hotkeys_1_and_5_emit_kj_extensions_in_kj_mode():
    app = _get_or_create_qapp()
    screen = _show_screen(settings=AppSettings(default_workout_behavior="kj_mode"))
    requested: list[tuple[int, bool]] = []
    screen.extend_interval_requested.connect(lambda value, is_kj: requested.append((value, is_kj)))

    QTest.keyClick(screen, Qt.Key_1)
    QTest.keyClick(screen, Qt.Key_5)
    app.processEvents()

    assert requested == [(10, True), (50, True)]


def test_hotkeys_emit_skip_and_jog_commands():
    app = _get_or_create_qapp()
    screen = _show_screen()
    skip_count = 0
    jog_values: list[int] = []

    def _on_skip() -> None:
        nonlocal skip_count
        skip_count += 1

    screen.skip_interval_requested.connect(_on_skip)
    screen.jog_requested.connect(lambda delta: jog_values.append(int(delta)))

    QTest.keyClick(screen, Qt.Key_Tab)
    QTest.keyClick(screen, Qt.Key_Up)
    QTest.keyClick(screen, Qt.Key_Down)
    QTest.keyClick(screen, Qt.Key_Right)
    QTest.keyClick(screen, Qt.Key_Left)
    app.processEvents()

    assert skip_count == 1
    assert jog_values == [1, -1, 5, -5]


def test_hotkey_space_toggles_pause_then_resume():
    app = _get_or_create_qapp()
    screen = _show_screen()
    pause_clicks = 0
    resume_clicks = 0
    pause_resume_count = 0

    def _on_pause() -> None:
        nonlocal pause_clicks
        pause_clicks += 1

    def _on_resume() -> None:
        nonlocal resume_clicks
        resume_clicks += 1

    def _on_pause_resume() -> None:
        nonlocal pause_resume_count
        pause_resume_count += 1

    screen.pause_button.clicked.connect(_on_pause)
    screen.resume_button.clicked.connect(_on_resume)
    screen.pause_resume_requested.connect(_on_pause_resume)

    QTest.keyClick(screen, Qt.Key_Space)
    QTest.keyClick(screen, Qt.Key_Space)
    app.processEvents()

    assert pause_clicks == 1
    assert resume_clicks == 1
    assert pause_resume_count == 2


def test_hotkeys_do_not_trigger_when_text_input_has_focus():
    app = _get_or_create_qapp()
    screen = _show_screen()
    requested_extensions: list[tuple[int, bool]] = []
    screen.extend_interval_requested.connect(
        lambda value, is_kj: requested_extensions.append((value, is_kj)),
    )
    prior_mode = screen.mode_selector.currentText()

    editor = QLineEdit(screen)
    editor.show()
    editor.setFocus(Qt.ActiveWindowFocusReason)
    app.processEvents()

    QTest.keyClick(editor, Qt.Key_T)
    QTest.keyClick(editor, Qt.Key_1)
    app.processEvents()

    assert screen.mode_selector.currentText() == prior_mode
    assert requested_extensions == []
    assert editor.text().lower() == "t1"
