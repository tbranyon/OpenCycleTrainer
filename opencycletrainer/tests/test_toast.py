from __future__ import annotations

import os
import time

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from opencycletrainer.ui.toast import ToastOverlay


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _toast_texts(overlay: ToastOverlay) -> list[str]:
    # Use isHidden() rather than isVisible(): in tests the parent window is never shown,
    # so isVisible() is always False even for live toast labels. isHidden() reflects only
    # whether the label itself was hidden/removed.
    return [label.text() for label in overlay.findChildren(QLabel) if not label.isHidden()]


def test_toast_overlay_shows_message_label():
    _get_or_create_qapp()
    parent = QWidget()
    parent.resize(400, 300)
    overlay = ToastOverlay(parent, duration_ms=10000)

    overlay.show_message("Connected to Trainer One")

    assert "Connected to Trainer One" in _toast_texts(overlay)


def test_toast_overlay_stacks_multiple_messages():
    _get_or_create_qapp()
    parent = QWidget()
    parent.resize(400, 300)
    overlay = ToastOverlay(parent, duration_ms=10000)

    overlay.show_message("First")
    overlay.show_message("Second")

    texts = _toast_texts(overlay)
    assert "First" in texts
    assert "Second" in texts


def test_toast_overlay_auto_dismisses_after_duration():
    app = _get_or_create_qapp()
    parent = QWidget()
    parent.resize(400, 300)
    overlay = ToastOverlay(parent, duration_ms=50)

    overlay.show_message("Temporary")

    deadline = time.time() + 2.0
    while _toast_texts(overlay) and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert _toast_texts(overlay) == []


def test_toast_overlay_is_transparent_for_mouse_events():
    _get_or_create_qapp()
    from PySide6.QtCore import Qt

    parent = QWidget()
    parent.resize(400, 300)
    overlay = ToastOverlay(parent)

    assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
