from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)


class WorkoutHotkeys(QObject):
    """Registers workout hotkeys and guards against key capture while typing."""

    def __init__(
        self,
        widget: QWidget,
        *,
        on_toggle_mode: Callable[[], None],
        on_extend_short: Callable[[], None],
        on_extend_long: Callable[[], None],
        on_skip_interval: Callable[[], None],
        on_jog_small_up: Callable[[], None],
        on_jog_small_down: Callable[[], None],
        on_jog_large_up: Callable[[], None],
        on_jog_large_down: Callable[[], None],
        on_pause_resume: Callable[[], None],
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._app = QApplication.instance()
        self._callbacks_by_key: dict[int, Callable[[], None]] = {
            Qt.Key_T: on_toggle_mode,
            Qt.Key_1: on_extend_short,
            Qt.Key_5: on_extend_long,
            Qt.Key_Tab: on_skip_interval,
            Qt.Key_Up: on_jog_small_up,
            Qt.Key_Down: on_jog_small_down,
            Qt.Key_Right: on_jog_large_up,
            Qt.Key_Left: on_jog_large_down,
            Qt.Key_Space: on_pause_resume,
        }
        if self._app is not None:
            self._app.installEventFilter(self)
        self._widget.destroyed.connect(self._remove_event_filter)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.KeyPress:
            return False
        try:
            if not self._widget.isVisible():
                return False
        except RuntimeError:
            self._remove_event_filter()
            return False

        focused = QApplication.focusWidget()
        if focused is None:
            return False
        if focused is not self._widget and not self._widget.isAncestorOf(focused):
            return False

        key = int(event.key())
        callback = self._callbacks_by_key.get(key)
        if callback is None:
            return False
        if event.modifiers() != Qt.NoModifier:
            return False
        if _focused_widget_is_text_input():
            return False
        callback()
        return True

    def _remove_event_filter(self, *_args: object) -> None:
        if self._app is None:
            return
        try:
            self._app.removeEventFilter(self)
        except RuntimeError:
            pass
        self._app = None


def _focused_widget_is_text_input() -> bool:
    focused = QApplication.focusWidget()
    if focused is None:
        return False
    if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
        return True
    if isinstance(focused, QComboBox):
        return focused.isEditable()
    return False
