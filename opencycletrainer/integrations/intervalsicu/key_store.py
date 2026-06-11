from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import keyring
from keyring.errors import PasswordDeleteError

from opencycletrainer.storage.paths import get_data_dir

_SERVICE = "OpenCycleTrainer/IntervalsICU"
_USERNAME = "default"
_FALLBACK_FILENAME = "intervals_icu_key.json"


def _has_working_keyring() -> bool:
    """Return True if the system keyring backend can perform operations."""
    try:
        backend = keyring.get_keyring()
        backend.get_password(_SERVICE, "__probe__")
        return True
    except Exception:
        return False


def _fallback_path() -> Path:
    """Return the path to the file-based key fallback."""
    return get_data_dir() / _FALLBACK_FILENAME


def is_available() -> bool:
    """Return True — either the system keyring or file-based fallback is always usable."""
    return True


def get_api_key() -> str | None:
    """Return the stored intervals.icu API key, or None if none has been saved."""
    if _has_working_keyring():
        try:
            value = keyring.get_password(_SERVICE, _USERNAME)
            if value is not None:
                return value
        except Exception:
            pass
    # Fall back to file-based storage.
    path = _fallback_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("api_key")
    except Exception:  # noqa: BLE001
        return None


def save_api_key(api_key: str) -> None:
    """Persist the API key to the OS keychain, or a restricted file if unavailable."""
    if _has_working_keyring():
        keyring.set_password(_SERVICE, _USERNAME, api_key)
        # Remove any stale fallback file left from a prior session without keyring.
        path = _fallback_path()
        if path.exists():
            path.unlink()
    else:
        path = _fallback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"api_key": api_key}), encoding="utf-8")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def clear_api_key() -> None:
    """Remove any stored API key from the OS keychain and file fallback."""
    if _has_working_keyring():
        try:
            keyring.delete_password(_SERVICE, _USERNAME)
        except PasswordDeleteError:
            pass
    path = _fallback_path()
    if path.exists():
        path.unlink()
