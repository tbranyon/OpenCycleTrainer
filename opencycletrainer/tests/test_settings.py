from __future__ import annotations

import json
import shutil
from pathlib import Path

from opencycletrainer.storage.settings import AppSettings, load_settings, save_settings


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


def test_theme_mode_invalid_value_defaults_to_system():
    settings_file = _settings_file()
    settings_file.write_text('{"theme_mode": "banana"}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.theme_mode == "system"


def test_workout_data_dir_defaults_to_none():
    assert AppSettings().workout_data_dir is None


def test_workout_data_dir_round_trips_through_serialization():
    settings_file = _settings_file()
    settings = AppSettings(workout_data_dir=Path("C:/rides"))

    save_settings(settings, settings_file)
    loaded = load_settings(settings_file)

    assert loaded.workout_data_dir == Path("C:/rides")


def test_workout_data_dir_missing_key_defaults_to_none():
    settings_file = _settings_file()
    settings_file.write_text('{"ftp": 250}', encoding="utf-8")

    loaded = load_settings(settings_file)

    assert loaded.workout_data_dir is None
