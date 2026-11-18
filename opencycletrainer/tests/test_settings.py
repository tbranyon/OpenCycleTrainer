from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from opencycletrainer.storage.settings import (
    AppSettings,
    JogPersistenceMode,
    load_settings,
    save_settings,
)


def _settings_file() -> Path:
    folder = Path.cwd() / ".tmp_runtime" / "settings_tests"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def test_load_settings_creates_defaults_when_file_missing():
    settings_file = _settings_file()

    loaded = load_settings(settings_file)

    assert settings_file.exists()
    assert loaded == AppSettings()


def test_save_settings_writes_expected_keys():
    settings_file = _settings_file()
    settings = AppSettings(
        ftp=300,
        lead_time=5,
        opentrueup_enabled=True,
        tile_selections=["power", "cadence"],
        theme_mode="dark",
        display_units="imperial",
        default_workout_behavior="free_ride_mode",
    )

    save_settings(settings, settings_file)

    raw = json.loads(settings_file.read_text(encoding="utf-8"))
    assert raw["ftp"] == 300
    assert raw["lead_time"] == 5
    assert raw["opentrueup_enabled"] is True
    assert raw["tile_selections"] == ["power", "cadence"]
    assert raw["theme_mode"] == "dark"
    assert raw["display_units"] == "imperial"
    assert raw["default_workout_behavior"] == "free_ride_mode"


def test_strava_auto_sync_defaults_to_false():
    assert AppSettings().strava_auto_sync_enabled is False


def test_strava_auto_sync_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(strava_auto_sync_enabled=True)

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.strava_auto_sync_enabled is True


def test_strava_auto_sync_missing_key_defaults_to_false():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.strava_auto_sync_enabled is False


def test_strava_athlete_name_defaults_to_empty_string():
    assert AppSettings().strava_athlete_name == ""


def test_strava_athlete_name_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(strava_athlete_name="Jane Smith")

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.strava_athlete_name == "Jane Smith"


def test_strava_athlete_name_missing_key_defaults_to_empty_string():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.strava_athlete_name == ""


def test_intervals_icu_auto_sync_defaults_to_false():
    assert AppSettings().intervals_icu_auto_sync_enabled is False


def test_intervals_icu_auto_sync_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(intervals_icu_auto_sync_enabled=True)

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.intervals_icu_auto_sync_enabled is True


def test_intervals_icu_auto_sync_missing_key_defaults_to_false():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.intervals_icu_auto_sync_enabled is False


def test_intervals_icu_athlete_name_defaults_to_empty_string():
    assert AppSettings().intervals_icu_athlete_name == ""


def test_intervals_icu_athlete_name_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(intervals_icu_athlete_name="Jane Smith")

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.intervals_icu_athlete_name == "Jane Smith"


def test_intervals_icu_athlete_name_missing_key_defaults_to_empty_string():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.intervals_icu_athlete_name == ""


def test_erg_jog_persistence_mode_defaults_to_never():
    assert AppSettings().erg_jog_persistence_mode is JogPersistenceMode.NEVER


def test_erg_jog_persistence_mode_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(erg_jog_persistence_mode=JogPersistenceMode.ALWAYS)

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.erg_jog_persistence_mode is JogPersistenceMode.ALWAYS


def test_erg_jog_persistence_mode_missing_key_defaults_to_never():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.erg_jog_persistence_mode is JogPersistenceMode.NEVER


def test_erg_jog_persistence_mode_serializes_only_new_key():
    settings_file = _settings_file()
    settings = AppSettings(erg_jog_persistence_mode=JogPersistenceMode.WORK_INTERVALS_ONLY)

    save_settings(settings, settings_file)
    raw = json.loads(settings_file.read_text(encoding="utf-8"))

    assert raw["erg_jog_persistence_mode"] == "work_only"
    assert "erg_jog_persistent" not in raw


def test_erg_jog_persistence_mode_legacy_true_migrates_to_always():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250, "erg_jog_persistent": true}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.erg_jog_persistence_mode is JogPersistenceMode.ALWAYS


def test_erg_jog_persistence_mode_legacy_false_migrates_to_never():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250, "erg_jog_persistent": false}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.erg_jog_persistence_mode is JogPersistenceMode.NEVER


def test_erg_jog_persistence_mode_new_key_takes_precedence_over_legacy():
    settings_file = _settings_file()
    settings_file.write_text(
        '{"ftp": 250, "erg_jog_persistent": true, "erg_jog_persistence_mode": "work_only"}',
        encoding="utf-8",
    )

    loaded = load_settings(settings_file)

    assert loaded.erg_jog_persistence_mode is JogPersistenceMode.WORK_INTERVALS_ONLY


def test_erg_jog_persistence_mode_invalid_value_falls_back_to_never():
    settings_file = _settings_file()
    settings_file.write_text(
        '{"ftp": 250, "erg_jog_persistence_mode": "sometimes"}',
        encoding="utf-8",
    )

    loaded = load_settings(settings_file)

    assert loaded.erg_jog_persistence_mode is JogPersistenceMode.NEVER


def test_theme_mode_defaults_to_system():
    assert AppSettings().theme_mode == "system"


def test_theme_mode_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(theme_mode="dark")

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.theme_mode == "dark"


def test_theme_mode_missing_key_defaults_to_system():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.theme_mode == "system"


def test_lead_time_increasing_only_defaults_to_true():
    assert AppSettings().lead_time_increasing_only is True


def test_lead_time_increasing_only_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(lead_time_increasing_only=False)

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.lead_time_increasing_only is False


def test_lead_time_increasing_only_missing_key_defaults_to_true():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.lead_time_increasing_only is True


def test_theme_mode_invalid_value_defaults_to_system():
    settings_file = _settings_file()
    settings_file.write_text('{"theme_mode": "banana"}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.theme_mode == "system"


def test_workout_data_dir_defaults_to_none():
    assert AppSettings().workout_data_dir is None


def test_workout_data_dir_round_trips_through_serialization():
    settings_file = _settings_file()
    existing_dir = settings_file.parent
    settings = AppSettings(workout_data_dir=existing_dir)

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.workout_data_dir == existing_dir


def test_workout_data_dir_missing_key_defaults_to_none():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.workout_data_dir is None


def test_workout_data_dir_nonexistent_path_returns_none():
    settings_file = _settings_file()
    settings_file.write_text('{"workout_data_dir": "/nonexistent/path/xyz"}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.workout_data_dir is None


def test_last_workout_dir_defaults_to_none():
    assert AppSettings().last_workout_dir is None


def test_last_workout_dir_existing_path_round_trips():
    settings_file = _settings_file()
    existing_dir = settings_file.parent
    settings = AppSettings(last_workout_dir=existing_dir)

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.last_workout_dir == existing_dir


def test_last_workout_dir_nonexistent_path_returns_none():
    settings_file = _settings_file()
    settings_file.write_text('{"last_workout_dir": "/nonexistent/path/xyz"}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.last_workout_dir is None


def test_declined_intervals_icu_ftp_defaults_to_none_and_round_trips():
    settings_file = _settings_file()
    assert AppSettings().intervals_icu_declined_ftp is None

    save_settings(AppSettings(intervals_icu_declined_ftp=270), settings_file)

    assert load_settings(settings_file).intervals_icu_declined_ftp == 270


def test_declined_intervals_icu_ftp_missing_key_defaults_to_none():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    assert load_settings(settings_file).intervals_icu_declined_ftp is None


# ── Grade simulation settings ─────────────────────────────────────────────────


def test_simulation_settings_have_sensible_defaults():
    settings = AppSettings()

    assert settings.rider_weight_kg == 75.0
    assert settings.bike_weight_kg == 9.0
    assert settings.simulation_difficulty_percent == 100


def test_simulation_settings_round_trip_through_serialization():
    settings_file = _settings_file()
    save_settings(
        AppSettings(rider_weight_kg=68.5, bike_weight_kg=7.8, simulation_difficulty_percent=50),
        settings_file,
    )

    loaded = load_settings(settings_file)

    assert loaded.rider_weight_kg == 68.5
    assert loaded.bike_weight_kg == 7.8
    assert loaded.simulation_difficulty_percent == 50


def test_simulation_settings_missing_keys_use_defaults():
    loaded = AppSettings.from_dict({"ftp": 280})

    assert loaded.rider_weight_kg == 75.0
    assert loaded.bike_weight_kg == 9.0
    assert loaded.simulation_difficulty_percent == 100


def test_simulation_settings_out_of_range_values_are_clamped():
    loaded = AppSettings.from_dict(
        {"rider_weight_kg": 1.0, "bike_weight_kg": 900.0, "simulation_difficulty_percent": 250}
    )

    assert loaded.rider_weight_kg == 30.0
    assert loaded.bike_weight_kg == 30.0
    assert loaded.simulation_difficulty_percent == 100


def test_total_mass_combines_rider_and_bike():
    assert AppSettings(rider_weight_kg=70.0, bike_weight_kg=8.5).total_mass_kg == 78.5


# ── Road surface ──────────────────────────────────────────────────────────────


def test_road_surface_defaults_to_smooth_road():
    assert AppSettings().road_surface == "smooth_road"


def test_road_surface_round_trips_through_serialization():
    settings_file = _settings_file()
    save_settings(AppSettings(road_surface="gravel"), settings_file)

    assert load_settings(settings_file).road_surface == "gravel"


def test_road_surface_missing_key_defaults_to_smooth_road():
    assert AppSettings.from_dict({"ftp": 280}).road_surface == "smooth_road"


def test_road_surface_invalid_value_defaults_to_smooth_road():
    assert AppSettings.from_dict({"road_surface": "moon dust"}).road_surface == "smooth_road"


# ── Course chart ──────────────────────────────────────────────────────────────


def test_course_zoom_span_defaults_to_one_distance_unit():
    assert AppSettings().course_zoom_span == 1.0


def test_course_zoom_span_round_trips_through_serialization():
    settings_file = _settings_file()
    save_settings(AppSettings(course_zoom_span=2.5), settings_file)

    assert load_settings(settings_file).course_zoom_span == 2.5


@pytest.mark.parametrize("stored, expected", [(0.0, 0.1), (-3.0, 0.1), (500.0, 50.0), ("x", 1.0)])
def test_course_zoom_span_is_kept_within_limits(stored, expected):
    assert AppSettings.from_dict({"course_zoom_span": stored}).course_zoom_span == expected


def test_course_grade_colors_default_on_and_round_trip():
    settings_file = _settings_file()
    assert AppSettings().course_grade_colors is True

    save_settings(AppSettings(course_grade_colors=False), settings_file)

    assert load_settings(settings_file).course_grade_colors is False
