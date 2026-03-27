from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from opencycletrainer.storage.filenames import build_activity_filename
from opencycletrainer.storage import paths


def test_get_config_dir_windows_uses_appdata(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths, "_system_name", lambda: "windows")

    config_dir = paths.get_config_dir()

    assert config_dir == appdata / "OpenCycleTrainer"


def test_get_config_and_data_dirs_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_system_name", lambda: "linux")
    monkeypatch.setattr(paths, "_home_dir", lambda: tmp_path)

    assert paths.get_config_dir() == tmp_path / ".config" / "opencycletrainer"
    assert paths.get_data_dir() == tmp_path / ".local" / "share" / "opencycletrainer"


def test_ensure_dir_creates_path(tmp_path):
    missing_dir = tmp_path / "nested" / "folder"

    result = paths.ensure_dir(missing_dir)

    assert result == missing_dir
    assert missing_dir.exists()
    assert missing_dir.is_dir()


def test_settings_file_path_uses_config_dir(monkeypatch):
    fake_config = Path("C:/cfg/OpenCycleTrainer")
    monkeypatch.setattr(paths, "get_config_dir", lambda: fake_config)

    settings_path = paths.get_settings_file_path()

    assert settings_path == fake_config / "settings.json"


def test_opentrueup_offsets_path_uses_config_dir(monkeypatch):
    fake_config = Path("C:/cfg/OpenCycleTrainer")
    monkeypatch.setattr(paths, "get_config_dir", lambda: fake_config)

    offsets_path = paths.get_opentrueup_offsets_file_path()

    assert offsets_path == fake_config / "opentrueup_offsets.json"


def test_activity_filename_format():
    timestamp = datetime(2026, 3, 9, 18, 42)

    filename = build_activity_filename("Threshold", timestamp, "fit")

    assert filename == "Threshold_20260309_1842.fit"


def test_activity_filename_sanitizes_workout_name():
    timestamp = datetime(2026, 3, 9, 18, 42)

    filename = build_activity_filename("  VO2 Max:/Block 1  ", timestamp, ".fit")

    assert filename == "VO2_MaxBlock_1_20260309_1842.fit"


def test_activity_filename_requires_extension():
    timestamp = datetime(2026, 3, 9, 18, 42)

    with pytest.raises(ValueError):
        build_activity_filename("Threshold", timestamp, " ")


def test_get_user_workouts_dir_windows(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths, "_system_name", lambda: "windows")

    workouts_dir = paths.get_user_workouts_dir()

    assert workouts_dir == appdata / "OpenCycleTrainer" / "workouts"
    assert workouts_dir.exists()


def test_get_user_workouts_dir_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_system_name", lambda: "linux")
    monkeypatch.setattr(paths, "_home_dir", lambda: tmp_path)

    workouts_dir = paths.get_user_workouts_dir()

    assert workouts_dir == tmp_path / ".local" / "share" / "opencycletrainer" / "workouts"
    assert workouts_dir.exists()


def test_get_user_workouts_dir_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_system_name", lambda: "linux")
    monkeypatch.setattr(paths, "_home_dir", lambda: tmp_path)

    workouts_dir = paths.get_user_workouts_dir()

    assert workouts_dir.is_dir()


def test_get_prepackaged_workouts_dir_is_workouts_subdir():
    workouts_dir = paths.get_prepackaged_workouts_dir()

    assert workouts_dir.name == "workouts"
    assert (workouts_dir.parent / "opencycletrainer").is_dir()


def test_get_prepackaged_workouts_dir_prefers_frozen_bundle(monkeypatch, tmp_path):
    frozen_root = tmp_path / "bundle"
    frozen_workouts = frozen_root / "workouts"
    frozen_workouts.mkdir(parents=True)

    monkeypatch.setattr(paths, "_frozen_bundle_root", lambda: frozen_root)
    monkeypatch.setattr(paths, "_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(paths.sys, "prefix", str(tmp_path / "prefix"))

    assert paths.get_prepackaged_workouts_dir() == frozen_workouts


def test_get_prepackaged_workouts_dir_uses_shared_install_path(monkeypatch, tmp_path):
    prefix = tmp_path / "prefix"
    shared_workouts = prefix / "share" / "opencycletrainer" / "workouts"
    shared_workouts.mkdir(parents=True)

    monkeypatch.setattr(paths, "_frozen_bundle_root", lambda: None)
    monkeypatch.setattr(paths, "_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(paths.sys, "prefix", str(prefix))

    assert paths.get_prepackaged_workouts_dir() == shared_workouts


def test_get_app_icon_path_prefers_frozen_bundle(monkeypatch, tmp_path):
    frozen_root = tmp_path / "bundle"
    frozen_icon = frozen_root / "res" / paths.APP_ICON_FILE_NAME
    frozen_icon.parent.mkdir(parents=True)
    frozen_icon.write_bytes(b"png")

    monkeypatch.setattr(paths, "_frozen_bundle_root", lambda: frozen_root)
    monkeypatch.setattr(paths, "_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(paths.sys, "prefix", str(tmp_path / "prefix"))

    assert paths.get_app_icon_path() == frozen_icon


def test_get_app_icon_path_uses_shared_install_path(monkeypatch, tmp_path):
    prefix = tmp_path / "prefix"
    shared_icon = prefix / "share" / "opencycletrainer" / "res" / paths.APP_ICON_FILE_NAME
    shared_icon.parent.mkdir(parents=True)
    shared_icon.write_bytes(b"png")

    monkeypatch.setattr(paths, "_frozen_bundle_root", lambda: None)
    monkeypatch.setattr(paths, "_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(paths.sys, "prefix", str(prefix))

    assert paths.get_app_icon_path() == shared_icon


def test_get_workout_fit_json_png_dirs_use_default_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)

    fit_dir = paths.get_workout_fit_dir()
    json_dir = paths.get_workout_json_dir()
    png_dir = paths.get_workout_png_dir()

    assert fit_dir == tmp_path / "FIT"
    assert json_dir == tmp_path / "JSON"
    assert png_dir == tmp_path / "png"
    assert fit_dir.is_dir()
    assert json_dir.is_dir()
    assert png_dir.is_dir()


def test_get_workout_fit_json_png_dirs_use_custom_root(tmp_path):
    root = tmp_path / "rides"

    fit_dir = paths.get_workout_fit_dir(root)
    json_dir = paths.get_workout_json_dir(root)
    png_dir = paths.get_workout_png_dir(root)

    assert fit_dir == root / "FIT"
    assert json_dir == root / "JSON"
    assert png_dir == root / "png"
    assert fit_dir.is_dir()
    assert json_dir.is_dir()
    assert png_dir.is_dir()
