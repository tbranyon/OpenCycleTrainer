from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


APP_NAME_WINDOWS = "OpenCycleTrainer"
APP_NAME_UNIX = "opencycletrainer"
APP_ICON_FILE_NAME = "icon_nobg.png"
WORKOUT_FIT_SUBDIR = "FIT"
WORKOUT_JSON_SUBDIR = "JSON"
WORKOUT_PNG_SUBDIR = "png"


def _system_name() -> str:
    return platform.system().lower()


def _home_dir() -> Path:
    return Path.home()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _frozen_bundle_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(sys.executable).resolve().parent


def _iter_bundled_roots() -> list[Path]:
    roots: list[Path] = []
    frozen_root = _frozen_bundle_root()
    if frozen_root is not None:
        roots.append(frozen_root)
    roots.append(Path(sys.prefix) / "share" / APP_NAME_UNIX)
    roots.append(_repo_root())
    return roots


def _resolve_existing_bundled_path(relative_path: Path, *, directory: bool) -> Path | None:
    for root in _iter_bundled_roots():
        candidate = root / relative_path
        if directory and candidate.is_dir():
            return candidate
        if not directory and candidate.is_file():
            return candidate
    return None


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


def get_workout_data_root(custom_root: Path | None = None) -> Path:
    return custom_root if custom_root is not None else get_data_dir()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_workout_fit_dir(custom_root: Path | None = None) -> Path:
    return ensure_dir(get_workout_data_root(custom_root) / WORKOUT_FIT_SUBDIR)


def get_workout_json_dir(custom_root: Path | None = None) -> Path:
    return ensure_dir(get_workout_data_root(custom_root) / WORKOUT_JSON_SUBDIR)


def get_workout_png_dir(custom_root: Path | None = None) -> Path:
    return ensure_dir(get_workout_data_root(custom_root) / WORKOUT_PNG_SUBDIR)


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
    relative_path = Path("workouts")
    resolved = _resolve_existing_bundled_path(relative_path, directory=True)
    if resolved is not None:
        return resolved
    return _repo_root() / relative_path


def get_app_icon_path() -> Path:
    """Return the packaged application icon path."""
    relative_path = Path("res") / APP_ICON_FILE_NAME
    resolved = _resolve_existing_bundled_path(relative_path, directory=False)
    if resolved is not None:
        return resolved
    return _repo_root() / relative_path
