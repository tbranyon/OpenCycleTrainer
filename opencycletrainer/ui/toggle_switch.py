from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox

_TRACK_WIDTH = 40
_TRACK_HEIGHT = 20
_THUMB_MARGIN = 2
_THUMB_DIAMETER = _TRACK_HEIGHT - 2 * _THUMB_MARGIN
_LABEL_GAP = 8
_ANIMATION_DURATION_MS = 130


class ToggleSwitch(QCheckBox):
    """A QCheckBox rendered as an animated sliding toggle switch.

    Behaves identically to QCheckBox (checked state, ``toggled`` signal,
    enabled state) so it is a drop-in replacement; only the visual
    presentation and the sliding animation of the thumb differ.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._thumb_x = float(self._thumb_x_for(self.isChecked()))
        self._thumb_animation = QPropertyAnimation(self, b"thumbX", self)
        self._thumb_animation.setDuration(_ANIMATION_DURATION_MS)
        self._thumb_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_thumb)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _thumb_x_for(self, checked: bool) -> int:
        if checked:
            return _TRACK_WIDTH - _THUMB_DIAMETER - _THUMB_MARGIN
        return _THUMB_MARGIN

    def _animate_thumb(self, checked: bool) -> None:
        self._thumb_animation.stop()
        self._thumb_animation.setStartValue(self._thumb_x)
        self._thumb_animation.setEndValue(float(self._thumb_x_for(checked)))
        self._thumb_animation.start()

    def get_thumb_x(self) -> float:
        return self._thumb_x

    def set_thumb_x(self, value: float) -> None:
        self._thumb_x = value
        self.update()

    thumbX = Property(float, get_thumb_x, set_thumb_x)

    def sizeHint(self) -> QSize:
        width = _TRACK_WIDTH
        text = self.text()
        if text:
            width += _LABEL_GAP + self.fontMetrics().horizontalAdvance(text)
        height = max(_TRACK_HEIGHT, self.fontMetrics().height())
        return QSize(width, height)

    def hitButton(self, pos) -> bool:
        return self.contentsRect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        palette = self.palette()
        enabled = self.isEnabled()

        track_top = (self.height() - _TRACK_HEIGHT) // 2
        track_rect = QRectF(0, track_top, _TRACK_WIDTH, _TRACK_HEIGHT)

        on_color = palette.color(palette.ColorRole.Highlight)
        off_color = palette.color(palette.ColorRole.Mid)
        fraction = self._thumb_fraction()
        track_color = _blend(off_color, on_color, fraction)
        if not enabled:
            track_color.setAlpha(110)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, _TRACK_HEIGHT / 2, _TRACK_HEIGHT / 2)

        thumb_color = QColor(Qt.GlobalColor.white)
        if not enabled:
            thumb_color.setAlpha(160)
        painter.setBrush(thumb_color)
        thumb_rect = QRectF(
            self._thumb_x,
            track_top + _THUMB_MARGIN,
            _THUMB_DIAMETER,
            _THUMB_DIAMETER,
        )
        painter.drawEllipse(thumb_rect)

        text = self.text()
        if text:
            text_color = palette.color(palette.ColorRole.WindowText)
            if not enabled:
                text_color.setAlpha(130)
            painter.setPen(text_color)
            text_rect = self.rect().adjusted(_TRACK_WIDTH + _LABEL_GAP, 0, 0, 0)
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )

    def _thumb_fraction(self) -> float:
        span = self._thumb_x_for(True) - self._thumb_x_for(False)
        if span <= 0:
            return 1.0 if self.isChecked() else 0.0
        fraction = (self._thumb_x - self._thumb_x_for(False)) / span
        return min(1.0, max(0.0, fraction))


def _blend(start: QColor, end: QColor, fraction: float) -> QColor:
    fraction = min(1.0, max(0.0, fraction))
    return QColor(
        round(start.red() + (end.red() - start.red()) * fraction),
        round(start.green() + (end.green() - start.green()) * fraction),
        round(start.blue() + (end.blue() - start.blue()) * fraction),
    )
