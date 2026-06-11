"""ToastOverlay — non-blocking, auto-dismissing notifications stacked over a window."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget

_DEFAULT_DURATION_MS = 4000
_EDGE_MARGIN_PX = 16
_TOAST_SPACING_PX = 8

_TOAST_STYLE = (
    "QLabel#toastLabel {"
    "background-color: rgba(40, 40, 40, 220);"
    "color: white;"
    "border-radius: 6px;"
    "padding: 8px 14px;"
    "font-size: 13px;"
    "}"
)


class ToastOverlay(QWidget):
    """Transparent overlay that shows transient toast messages in the lower-right corner.

    The overlay covers its parent but passes mouse events through, so it never blocks the
    underlying UI. Each message auto-dismisses after the configured duration.
    """

    def __init__(self, parent: QWidget, *, duration_ms: int = _DEFAULT_DURATION_MS) -> None:
        super().__init__(parent)
        self._duration_ms = duration_ms
        self._toasts: list[QLabel] = []
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    def show_message(self, text: str) -> None:
        """Display a toast that fades away after the configured duration."""
        message = text.strip()
        if not message:
            return
        label = QLabel(message, self)
        label.setObjectName("toastLabel")
        label.setStyleSheet(_TOAST_STYLE)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.adjustSize()
        label.show()
        self._toasts.append(label)
        self._reposition()
        self.raise_()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(self._duration_ms)
        timer.timeout.connect(lambda: self._remove(label))
        timer.start()

    def _remove(self, label: QLabel) -> None:
        if label in self._toasts:
            self._toasts.remove(label)
            label.deleteLater()
            self._reposition()

    def _reposition(self) -> None:
        """Stack toasts from the bottom-right corner upward, newest at the bottom."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        y = self.height() - _EDGE_MARGIN_PX
        for label in reversed(self._toasts):
            label.adjustSize()
            y -= label.height()
            label.move(self.width() - label.width() - _EDGE_MARGIN_PX, y)
            y -= _TOAST_SPACING_PX

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._reposition()
        return super().eventFilter(watched, event)
