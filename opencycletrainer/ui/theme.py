from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from opencycletrainer.storage.settings import (
    DEFAULT_THEME_MODE,
    SUPPORTED_THEME_MODES,
    THEME_MODE_DARK,
    THEME_MODE_LIGHT,
    THEME_MODE_SYSTEM,
)


def normalize_theme_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in SUPPORTED_THEME_MODES:
        return DEFAULT_THEME_MODE
    return normalized


def resolve_effective_theme_mode(theme_mode: str, app: QApplication) -> str:
    normalized = normalize_theme_mode(theme_mode)
    if normalized == THEME_MODE_SYSTEM:
        return _system_color_scheme(app)
    return normalized


def apply_application_theme(theme_mode: str, app: QApplication) -> str:
    effective_mode = resolve_effective_theme_mode(theme_mode, app)
    if effective_mode == THEME_MODE_DARK:
        app.setPalette(_build_dark_palette())
        app.setStyleSheet(
            "QToolTip {"
            "color: #f1f5f9;"
            "background-color: #1f2937;"
            "border: 1px solid #334155;"
            "}"
        )
    else:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")
    return effective_mode


def _system_color_scheme(app: QApplication) -> str:
    style_hints = app.styleHints()
    if style_hints.colorScheme() == Qt.ColorScheme.Dark:
        return THEME_MODE_DARK
    return THEME_MODE_LIGHT


def _build_dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.Base, QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(31, 41, 55))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(241, 245, 249))
    palette.setColor(QPalette.ColorRole.Text, QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.Button, QColor(30, 41, 59))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(248, 113, 113))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(37, 99, 235))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    return palette
