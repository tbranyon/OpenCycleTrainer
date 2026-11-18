"""Flat push buttons with a role colour and a small line icon, for the workout screen.

A button's role is primary (the main thing to do), secondary or danger. Its colours and
its icon, drawn from a small inline SVG, follow the light or dark colour theme.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QWidget

from opencycletrainer.storage.settings import THEME_MODE_DARK, THEME_MODE_LIGHT

ROLE_PRIMARY = "primary"
ROLE_SECONDARY = "secondary"
ROLE_DANGER = "danger"

BUTTON_HEIGHT_PX = 34
ICON_SIZE_PX = 16
_ICON_TEXT_GAP_PX = 6
"""Transparent space drawn after each icon, since a stylesheet cannot space it from the text."""
_ICON_CANVAS = QSize(ICON_SIZE_PX + _ICON_TEXT_GAP_PX, ICON_SIZE_PX)
_ICON_RENDER_SCALE = 3
"""Icons are drawn at this multiple of their size so they stay crisp on high-DPI screens."""
_CORNER_RADIUS_PX = 6
_HORIZONTAL_PADDING_PX = 14
_FONT_WEIGHT = 600

_STROKE = 'fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
_FILL = 'fill="{color}"'
_ICON_SVG = {
    "play": f'<path {_FILL} d="M4.5 3.1v9.8a.7.7 0 0 0 1.06.6l7.9-4.9a.7.7 0 0 0 0-1.2L5.56 2.5a.7.7 0 0 0-1.06.6z"/>',
    "pause": (
        f'<rect {_FILL} x="3.5" y="2.75" width="3.2" height="10.5" rx="0.9"/>'
        f'<rect {_FILL} x="9.3" y="2.75" width="3.2" height="10.5" rx="0.9"/>'
    ),
    "stop": f'<rect {_FILL} x="3" y="3" width="10" height="10" rx="1.8"/>',
    "save": f'<path {_STROKE} d="M8 2.25v8.25M4.5 7l3.5 3.5L11.5 7M2.75 13.5h10.5"/>',
    "workout": (
        f'<rect {_FILL} x="1.25" y="9" width="2.75" height="5.25" rx="0.6"/>'
        f'<rect {_FILL} x="4.9" y="2.25" width="2.75" height="12" rx="0.6"/>'
        f'<rect {_FILL} x="8.55" y="6" width="2.75" height="8.25" rx="0.6"/>'
        f'<rect {_FILL} x="12.2" y="10.5" width="2.75" height="3.75" rx="0.6"/>'
    ),
    "library": (
        f'<rect {_STROKE} x="1.5" y="2.25" width="2.8" height="11.5" rx="0.6"/>'
        f'<rect {_STROKE} x="5.6" y="4" width="2.8" height="9.75" rx="0.6"/>'
        f'<rect {_STROKE} x="10.2" y="3.25" width="2.6" height="10.5" rx="0.6" transform="rotate(10 12.8 13.75)"/>'
    ),
    "calendar": (
        f'<rect {_STROKE} x="1.75" y="3" width="12.5" height="11" rx="1.4"/>'
        f'<path {_STROKE} d="M1.75 6.5h12.5M5 1.5v3M11 1.5v3"/>'
        f'<rect {_FILL} x="9" y="9" width="3" height="3" rx="0.5"/>'
    ),
    "course": (
        f'<path {_STROKE} d="M1.5 13.25 5.6 5.5l3.1 4.6 1.9-2.6 3.9 5.75z"/>'
        f'<circle {_FILL} cx="5.6" cy="3.1" r="1.15"/>'
    ),
}


@dataclass(frozen=True)
class _RoleColors:
    background: str
    hover: str
    pressed: str
    border: str
    text: str


@dataclass(frozen=True)
class _ThemeColors:
    roles: dict[str, _RoleColors]
    focus_border: str
    disabled_background: str
    disabled_text: str


_THEME_COLORS = {
    THEME_MODE_LIGHT: _ThemeColors(
        roles={
            ROLE_PRIMARY: _RoleColors("#2563eb", "#1d4ed8", "#1e40af", "#2563eb", "#ffffff"),
            ROLE_SECONDARY: _RoleColors("#ffffff", "#f3f4f6", "#e5e7eb", "#d0d7de", "#1f2328"),
            ROLE_DANGER: _RoleColors("#ffffff", "#fef2f2", "#fee2e2", "#f0b4b4", "#b42318"),
        },
        focus_border="#1e40af",
        disabled_background="#f3f4f6",
        disabled_text="#8c959f",
    ),
    THEME_MODE_DARK: _ThemeColors(
        roles={
            ROLE_PRIMARY: _RoleColors("#2563eb", "#3b82f6", "#1d4ed8", "#2563eb", "#ffffff"),
            ROLE_SECONDARY: _RoleColors("#3b4759", "#465569", "#2a3444", "#4f5e75", "#f0f6fc"),
            ROLE_DANGER: _RoleColors("#3b4759", "#4a3039", "#3a2229", "#8a3a42", "#ff8a80"),
        },
        focus_border="#93c5fd",
        disabled_background="#2a3444",
        disabled_text="#6e7681",
    ),
}


class ActionButton(QPushButton):
    """A flat, rounded push button coloured by its role, with an optional icon before its text."""

    def __init__(
        self,
        text: str,
        *,
        role: str = ROLE_SECONDARY,
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._role = role
        self._icon_name = icon
        self.setFixedHeight(BUTTON_HEIGHT_PX)
        self.setIconSize(_ICON_CANVAS)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.apply_color_theme(THEME_MODE_LIGHT)

    def apply_color_theme(self, theme_mode: str) -> None:
        """Recolour the button and its icon for *theme_mode* ("light" or "dark")."""
        theme = _THEME_COLORS.get(theme_mode, _THEME_COLORS[THEME_MODE_LIGHT])
        colors = theme.roles[self._role]
        self.setStyleSheet(_style_sheet(colors, theme))
        if self._icon_name is not None:
            self.setIcon(_render_icon(self._icon_name, colors.text, theme.disabled_text))


def _style_sheet(colors: _RoleColors, theme: _ThemeColors) -> str:
    return (
        "QPushButton {"
        f"background-color: {colors.background}; color: {colors.text};"
        f"border: 1px solid {colors.border}; border-radius: {_CORNER_RADIUS_PX}px;"
        f"padding: 0px {_HORIZONTAL_PADDING_PX}px; font-weight: {_FONT_WEIGHT}; outline: none;"
        "}"
        f"QPushButton:hover {{ background-color: {colors.hover}; }}"
        f"QPushButton:pressed {{ background-color: {colors.pressed}; }}"
        f"QPushButton:focus {{ border-color: {theme.focus_border}; }}"
        "QPushButton:disabled {"
        f"background-color: {theme.disabled_background}; color: {theme.disabled_text};"
        f"border-color: {theme.disabled_background};"
        "}"
    )


def _render_icon(name: str, color: str, disabled_color: str) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_render_pixmap(name, color), QIcon.Mode.Normal)
    icon.addPixmap(_render_pixmap(name, disabled_color), QIcon.Mode.Disabled)
    return icon


def _render_pixmap(name: str, color: str) -> QPixmap:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        f"{_ICON_SVG[name].format(color=color)}</svg>"
    )
    pixmap = QPixmap(_ICON_CANVAS * _ICON_RENDER_SCALE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    glyph_px = ICON_SIZE_PX * _ICON_RENDER_SCALE
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, glyph_px, glyph_px))
    painter.end()
    pixmap.setDevicePixelRatio(_ICON_RENDER_SCALE)
    return pixmap
