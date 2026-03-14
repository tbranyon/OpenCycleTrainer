from __future__ import annotations

import os
import platform
from pathlib import Path


APP_NAME_WINDOWS = "OpenCycleTrainer"
APP_NAME_UNIX = "opencycletrainer"


def _system_name() -> str:
    return platform.system().lower()


def _home_dir() -> Path:
    return Path.home()


def get_config_dir() -> Path:
    system_name = _system_name()
    if system_name == "windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME_WINDOWS
        return _home_dir() / "AppData" / "Roaming" / APP_NAME_WINDOWS
    return _home_dir() / ".config" / APP_NAME_UNIX


def get_data_dir() -> Path:
    system_name = _system_name()
    if system_name == "windows":
        # Windows spec currently defines %APPDATA% as the storage root.
        return get_config_dir()
    return _home_dir() / ".local" / "share" / APP_NAME_UNIX


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_settings_file_path() -> Path:
    return get_config_dir() / "settings.json"


def get_log_file_path() -> Path:
    return get_data_dir() / "opencycletrainer.log"


def get_opentrueup_offsets_file_path() -> Path:
    return get_config_dir() / "opentrueup_offsets.json"


def get_paired_devices_file_path() -> Path:
    return get_config_dir() / "paired_devices.json"


def get_user_workouts_dir() -> Path:
    """Return (and create) the platform-specific user workouts directory."""
    return ensure_dir(get_data_dir() / "workouts")


def get_prepackaged_workouts_dir() -> Path:
    """Return the bundled workouts directory shipped alongside the application."""
    return Path(__file__).parent.parent.parent / "workouts"
