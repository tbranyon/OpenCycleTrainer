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
