from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .paths import ensure_dir, get_settings_file_path

DISPLAY_UNITS_METRIC = "metric"
DISPLAY_UNITS_IMPERIAL = "imperial"
SUPPORTED_DISPLAY_UNITS = {DISPLAY_UNITS_METRIC, DISPLAY_UNITS_IMPERIAL}

DEFAULT_WORKOUT_BEHAVIOR = "workout_mode"
SUPPORTED_WORKOUT_BEHAVIORS = {
    DEFAULT_WORKOUT_BEHAVIOR,
    "free_ride_mode",
    "kj_mode",
}

class JogPersistenceMode(str, Enum):
    """Controls whether a manual ERG power jog survives interval boundaries."""

    ALWAYS = "always"
    WORK_INTERVALS_ONLY = "work_only"
    NEVER = "never"


DEFAULT_JOG_PERSISTENCE_MODE = JogPersistenceMode.NEVER

ROAD_SURFACE_SMOOTH_ROAD = "smooth_road"
ROAD_SURFACE_AGED_ASPHALT = "aged_asphalt"
ROAD_SURFACE_CHIPSEAL = "chipseal"
ROAD_SURFACE_HARDPACK_GRAVEL = "hardpack_gravel"
ROAD_SURFACE_GRAVEL = "gravel"
ROAD_SURFACE_LOOSE_GRAVEL = "loose_gravel"
DEFAULT_ROAD_SURFACE = ROAD_SURFACE_SMOOTH_ROAD
SUPPORTED_ROAD_SURFACES = {
    ROAD_SURFACE_SMOOTH_ROAD,
    ROAD_SURFACE_AGED_ASPHALT,
    ROAD_SURFACE_CHIPSEAL,
    ROAD_SURFACE_HARDPACK_GRAVEL,
    ROAD_SURFACE_GRAVEL,
    ROAD_SURFACE_LOOSE_GRAVEL,
}

THEME_MODE_SYSTEM = "system"
THEME_MODE_LIGHT = "light"
THEME_MODE_DARK = "dark"
DEFAULT_THEME_MODE = THEME_MODE_SYSTEM
SUPPORTED_THEME_MODES = {
    THEME_MODE_SYSTEM,
    THEME_MODE_LIGHT,
    THEME_MODE_DARK,
}


def _restore_dir(value: str | None) -> Path | None:
    """Return a Path only if the stored value is non-empty and the directory exists."""
    if not value:
        return None
    path = Path(value)
    return path if path.exists() else None


def _restore_optional_int(value: object) -> int | None:
    """Return the stored value as an int, or None when it is missing or not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


DEFAULT_RIDER_WEIGHT_KG = 75.0
MIN_RIDER_WEIGHT_KG = 30.0
MAX_RIDER_WEIGHT_KG = 200.0
DEFAULT_BIKE_WEIGHT_KG = 9.0
MIN_BIKE_WEIGHT_KG = 3.0
MAX_BIKE_WEIGHT_KG = 30.0
DEFAULT_SIMULATION_DIFFICULTY_PERCENT = 100
MIN_SIMULATION_DIFFICULTY_PERCENT = 0
MAX_SIMULATION_DIFFICULTY_PERCENT = 100

DEFAULT_COURSE_ZOOM_SPAN = 1.0
"""Default width of the zoomed course view, in display distance units (km or mi)."""
MIN_COURSE_ZOOM_SPAN = 0.1
MAX_COURSE_ZOOM_SPAN = 50.0

MAP_TILE_SOURCE_OPENSTREETMAP = "openstreetmap"
MAP_TILE_SOURCE_CYCLOSM = "cyclosm"
MAP_TILE_SOURCE_OPENTOPOMAP = "opentopomap"
MAP_TILE_SOURCE_THUNDERFOREST_CYCLE = "thunderforest_cycle"
DEFAULT_MAP_TILE_SOURCE = MAP_TILE_SOURCE_OPENSTREETMAP
SUPPORTED_MAP_TILE_SOURCES = (
    MAP_TILE_SOURCE_OPENSTREETMAP,
    MAP_TILE_SOURCE_CYCLOSM,
    MAP_TILE_SOURCE_OPENTOPOMAP,
    MAP_TILE_SOURCE_THUNDERFOREST_CYCLE,
)


def _clamped_float(raw: Any, default: float, minimum: float, maximum: float) -> float:
    """Return *raw* as a float within [minimum, maximum], or *default* if it is not a number."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _restore_width_px(value: object) -> int | None:
    """Return a stored pixel width, or None if it is missing or not a positive whole number."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _resolve_jog_persistence_mode(data: dict[str, Any]) -> JogPersistenceMode:
    """Resolve the jog persistence mode, migrating the legacy boolean if needed.

    Prefers the current ``erg_jog_persistence_mode`` key. If absent, falls back to
    the legacy ``erg_jog_persistent`` bool (``True`` -> ALWAYS, ``False`` -> NEVER).
    Unknown or missing values fall back to the default (NEVER).
    """
    raw_mode = data.get("erg_jog_persistence_mode")
    if raw_mode is None:
        if "erg_jog_persistent" in data:
            return JogPersistenceMode.ALWAYS if bool(data["erg_jog_persistent"]) else JogPersistenceMode.NEVER
        return DEFAULT_JOG_PERSISTENCE_MODE
    try:
        return JogPersistenceMode(str(raw_mode))
    except ValueError:
        return DEFAULT_JOG_PERSISTENCE_MODE


@dataclass
class AppSettings:
    ftp: int = 250
    lead_time: int = 0
    lead_time_increasing_only: bool = True
    opentrueup_enabled: bool = False
    tile_selections: list[str] = field(default_factory=list)
    theme_mode: str = DEFAULT_THEME_MODE
    display_units: str = DISPLAY_UNITS_METRIC
    default_workout_behavior: str = DEFAULT_WORKOUT_BEHAVIOR
    windowed_power_window_seconds: int = 3
    last_workout_dir: Path | None = None
    workout_data_dir: Path | None = None
    strava_auto_sync_enabled: bool = False
    strava_athlete_name: str = ""
    intervals_icu_auto_sync_enabled: bool = False
    intervals_icu_athlete_name: str = ""
    # intervals.icu FTP the rider chose not to adopt; not offered again until it changes.
    intervals_icu_declined_ftp: int | None = None
    show_interval_plot: bool = True
    erg_jog_persistence_mode: JogPersistenceMode = DEFAULT_JOG_PERSISTENCE_MODE
    rider_weight_kg: float = DEFAULT_RIDER_WEIGHT_KG
    bike_weight_kg: float = DEFAULT_BIKE_WEIGHT_KG
    # Share of a course's real grade the trainer is asked to simulate.
    simulation_difficulty_percent: int = DEFAULT_SIMULATION_DIFFICULTY_PERCENT
    # Surface being ridden, which sets the rolling resistance of a simulated ride.
    road_surface: str = DEFAULT_ROAD_SURFACE
    # Width of the zoomed course view, in display distance units (km or mi).
    course_zoom_span: float = DEFAULT_COURSE_ZOOM_SPAN
    # Colour climbs on the course profile by how steep they are.
    course_grade_colors: bool = True
    # Show the map beside the plots on course rides, drawn over tiles from this source.
    course_map_enabled: bool = True
    map_tile_source: str = DEFAULT_MAP_TILE_SOURCE
    # The rider's own key for Thunderforest tiles, which need one.
    thunderforest_api_key: str = ""
    # Map panel width the rider last dragged it to; None leaves it at its default share.
    course_map_width_px: int | None = None
    course_map_collapsed: bool = False

    @property
    def total_mass_kg(self) -> float:
        """Rider plus bike, the mass moved when simulating a ride."""
        return self.rider_weight_kg + self.bike_weight_kg

    def to_dict(self) -> dict[str, Any]:
        return {
            "ftp": self.ftp,
            "lead_time": self.lead_time,
            "lead_time_increasing_only": self.lead_time_increasing_only,
            "opentrueup_enabled": self.opentrueup_enabled,
            "tile_selections": self.tile_selections,
            "theme_mode": self.theme_mode,
            "display_units": self.display_units,
            "default_workout_behavior": self.default_workout_behavior,
            "windowed_power_window_seconds": self.windowed_power_window_seconds,
            "last_workout_dir": str(self.last_workout_dir) if self.last_workout_dir else None,
            "workout_data_dir": str(self.workout_data_dir) if self.workout_data_dir else None,
            "strava_auto_sync_enabled": self.strava_auto_sync_enabled,
            "strava_athlete_name": self.strava_athlete_name,
            "intervals_icu_auto_sync_enabled": self.intervals_icu_auto_sync_enabled,
            "intervals_icu_athlete_name": self.intervals_icu_athlete_name,
            "intervals_icu_declined_ftp": self.intervals_icu_declined_ftp,
            "show_interval_plot": self.show_interval_plot,
            "erg_jog_persistence_mode": self.erg_jog_persistence_mode.value,
            "rider_weight_kg": self.rider_weight_kg,
            "bike_weight_kg": self.bike_weight_kg,
            "simulation_difficulty_percent": self.simulation_difficulty_percent,
            "road_surface": self.road_surface,
            "course_zoom_span": self.course_zoom_span,
            "course_grade_colors": self.course_grade_colors,
            "course_map_enabled": self.course_map_enabled,
            "map_tile_source": self.map_tile_source,
            "thunderforest_api_key": self.thunderforest_api_key,
            "course_map_width_px": self.course_map_width_px,
            "course_map_collapsed": self.course_map_collapsed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        display_units = str(data.get("display_units", DISPLAY_UNITS_METRIC)).lower()
        if display_units not in SUPPORTED_DISPLAY_UNITS:
            display_units = DISPLAY_UNITS_METRIC

        theme_mode = str(data.get("theme_mode", DEFAULT_THEME_MODE)).lower()
        if theme_mode not in SUPPORTED_THEME_MODES:
            theme_mode = DEFAULT_THEME_MODE

        default_workout_behavior = str(
            data.get("default_workout_behavior", DEFAULT_WORKOUT_BEHAVIOR),
        )
        if default_workout_behavior not in SUPPORTED_WORKOUT_BEHAVIORS:
            default_workout_behavior = DEFAULT_WORKOUT_BEHAVIOR

        erg_jog_persistence_mode = _resolve_jog_persistence_mode(data)

        road_surface = str(data.get("road_surface", DEFAULT_ROAD_SURFACE))
        if road_surface not in SUPPORTED_ROAD_SURFACES:
            road_surface = DEFAULT_ROAD_SURFACE

        map_tile_source = str(data.get("map_tile_source", DEFAULT_MAP_TILE_SOURCE))
        if map_tile_source not in SUPPORTED_MAP_TILE_SOURCES:
            map_tile_source = DEFAULT_MAP_TILE_SOURCE

        return cls(
            ftp=int(data.get("ftp", 250)),
            lead_time=int(data.get("lead_time", 0)),
            lead_time_increasing_only=bool(data.get("lead_time_increasing_only", True)),
            opentrueup_enabled=bool(data.get("opentrueup_enabled", False)),
            tile_selections=list(data.get("tile_selections", [])),
            theme_mode=theme_mode,
            display_units=display_units,
            default_workout_behavior=default_workout_behavior,
            windowed_power_window_seconds=max(1, min(10, int(data.get("windowed_power_window_seconds", 3)))),
            last_workout_dir=_restore_dir(data.get("last_workout_dir")),
            workout_data_dir=_restore_dir(data.get("workout_data_dir")),
            strava_auto_sync_enabled=bool(data.get("strava_auto_sync_enabled", False)),
            strava_athlete_name=str(data.get("strava_athlete_name", "")),
            intervals_icu_auto_sync_enabled=bool(data.get("intervals_icu_auto_sync_enabled", False)),
            intervals_icu_athlete_name=str(data.get("intervals_icu_athlete_name", "")),
            intervals_icu_declined_ftp=_restore_optional_int(data.get("intervals_icu_declined_ftp")),
            show_interval_plot=bool(data.get("show_interval_plot", True)),
            erg_jog_persistence_mode=erg_jog_persistence_mode,
            rider_weight_kg=_clamped_float(
                data.get("rider_weight_kg"),
                DEFAULT_RIDER_WEIGHT_KG,
                MIN_RIDER_WEIGHT_KG,
                MAX_RIDER_WEIGHT_KG,
            ),
            bike_weight_kg=_clamped_float(
                data.get("bike_weight_kg"),
                DEFAULT_BIKE_WEIGHT_KG,
                MIN_BIKE_WEIGHT_KG,
                MAX_BIKE_WEIGHT_KG,
            ),
            simulation_difficulty_percent=int(
                round(
                    _clamped_float(
                        data.get("simulation_difficulty_percent"),
                        DEFAULT_SIMULATION_DIFFICULTY_PERCENT,
                        MIN_SIMULATION_DIFFICULTY_PERCENT,
                        MAX_SIMULATION_DIFFICULTY_PERCENT,
                    )
                )
            ),
            road_surface=road_surface,
            course_zoom_span=_clamped_float(
                data.get("course_zoom_span"),
                DEFAULT_COURSE_ZOOM_SPAN,
                MIN_COURSE_ZOOM_SPAN,
                MAX_COURSE_ZOOM_SPAN,
            ),
            course_grade_colors=bool(data.get("course_grade_colors", True)),
            course_map_enabled=bool(data.get("course_map_enabled", True)),
            map_tile_source=map_tile_source,
            thunderforest_api_key=str(data.get("thunderforest_api_key", "")).strip(),
            course_map_width_px=_restore_width_px(data.get("course_map_width_px")),
            course_map_collapsed=bool(data.get("course_map_collapsed", False)),
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
