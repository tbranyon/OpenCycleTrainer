from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import ensure_dir, get_settings_file_path

DISPLAY_UNITS_METRIC = "metric"
DISPLAY_UNITS_IMPERIAL = "imperial"
SUPPORTED_DISPLAY_UNITS = {DISPLAY_UNITS_METRIC, DISPLAY_UNITS_IMPERIAL}

THEME_DARK = "dark"
THEME_LIGHT = "light"
SUPPORTED_THEMES = {THEME_DARK, THEME_LIGHT}

DEFAULT_WORKOUT_BEHAVIOR = "workout_mode"
SUPPORTED_WORKOUT_BEHAVIORS = {
    DEFAULT_WORKOUT_BEHAVIOR,
    "free_ride_mode",
    "kj_mode",
}


@dataclass
class AppSettings:
    ftp: int = 250
    lead_time: int = 0
    opentrueup_enabled: bool = False
    tile_selections: list[str] = field(default_factory=list)
    display_units: str = DISPLAY_UNITS_METRIC
    default_workout_behavior: str = DEFAULT_WORKOUT_BEHAVIOR
    windowed_power_window_seconds: int = 3
    last_workout_dir: Path | None = None
    strava_auto_sync_enabled: bool = False
    strava_athlete_name: str = ""
    theme: str = THEME_DARK

    def to_dict(self) -> dict[str, Any]:
        return {
            "ftp": self.ftp,
            "lead_time": self.lead_time,
            "opentrueup_enabled": self.opentrueup_enabled,
            "tile_selections": self.tile_selections,
            "display_units": self.display_units,
            "default_workout_behavior": self.default_workout_behavior,
            "windowed_power_window_seconds": self.windowed_power_window_seconds,
            "last_workout_dir": str(self.last_workout_dir) if self.last_workout_dir else None,
            "strava_auto_sync_enabled": self.strava_auto_sync_enabled,
            "strava_athlete_name": self.strava_athlete_name,
            "theme": self.theme,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        display_units = str(data.get("display_units", DISPLAY_UNITS_METRIC)).lower()
        if display_units not in SUPPORTED_DISPLAY_UNITS:
            display_units = DISPLAY_UNITS_METRIC

        default_workout_behavior = str(
            data.get("default_workout_behavior", DEFAULT_WORKOUT_BEHAVIOR),
        )
        if default_workout_behavior not in SUPPORTED_WORKOUT_BEHAVIORS:
            default_workout_behavior = DEFAULT_WORKOUT_BEHAVIOR

        return cls(
            ftp=int(data.get("ftp", 250)),
            lead_time=int(data.get("lead_time", 0)),
            opentrueup_enabled=bool(data.get("opentrueup_enabled", False)),
            tile_selections=list(data.get("tile_selections", [])),
            display_units=display_units,
            default_workout_behavior=default_workout_behavior,
            windowed_power_window_seconds=max(1, min(10, int(data.get("windowed_power_window_seconds", 3)))),
            last_workout_dir=Path(data["last_workout_dir"]) if data.get("last_workout_dir") else None,
            strava_auto_sync_enabled=bool(data.get("strava_auto_sync_enabled", False)),
            strava_athlete_name=str(data.get("strava_athlete_name", "")),
            theme=str(data.get("theme", THEME_DARK)) if data.get("theme") in SUPPORTED_THEMES else THEME_DARK,
        )


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    settings_path = path or get_settings_file_path()
    ensure_dir(settings_path.parent)
    settings_path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    return settings_path


def load_settings(path: Path | None = None) -> AppSettings:
    settings_path = path or get_settings_file_path()
    if not settings_path.exists():
        defaults = AppSettings()
        save_settings(defaults, settings_path)
        return defaults

    raw_data = settings_path.read_text(encoding="utf-8")
    if not raw_data.strip():
        defaults = AppSettings()
        save_settings(defaults, settings_path)
        return defaults

    return AppSettings.from_dict(json.loads(raw_data))
