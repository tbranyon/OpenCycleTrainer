"""App-level state singleton — initialised once at startup, read by UI pages."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .storage.settings import AppSettings, save_settings

_settings: AppSettings | None = None
_settings_path: Path | None = None


def init(settings: AppSettings, path: Path) -> None:
    """Initialise the singleton. Must be called before any page handler runs."""
    global _settings, _settings_path
    _settings = settings
    _settings_path = path


def get() -> AppSettings:
    """Return the current settings. Raises if not initialised."""
    if _settings is None:
        raise RuntimeError("state.init() has not been called")
    return _settings


def save(updated: AppSettings) -> None:
    """Persist updated settings and replace the in-memory copy."""
    global _settings
    _settings = updated
    save_settings(updated, _settings_path)


def update(**kwargs) -> AppSettings:
    """Convenience: apply field overrides, persist, and return the new settings."""
    updated = replace(get(), **kwargs)
    save(updated)
    return updated
