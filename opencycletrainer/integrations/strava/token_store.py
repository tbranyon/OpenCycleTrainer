from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import keyring
from keyring.errors import PasswordDeleteError

from opencycletrainer.storage.paths import get_data_dir

_SERVICE = "OpenCycleTrainer/Strava"
_USERNAME = "default"
_FALLBACK_FILENAME = "strava_tokens.json"


@dataclass(frozen=True)
class StravaTokenBundle:
    """Per-user Strava OAuth token payload stored in the OS keychain or file fallback."""

    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp


def _has_working_keyring() -> bool:
    """Return True if the system keyring backend can perform operations."""
    try:
        backend = keyring.get_keyring()
        backend.get_password(_SERVICE, "__probe__")
        return True
    except Exception:
        return False


def _fallback_path() -> Path:
    """Return the path to the file-based token fallback."""
    return get_data_dir() / _FALLBACK_FILENAME


def _decode(raw: str) -> StravaTokenBundle:
    data = json.loads(raw)
    return StravaTokenBundle(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=int(data["expires_at"]),
    )


def is_available() -> bool:
    """Return True — either the system keyring or file-based fallback is always usable."""
    return True


def get_tokens() -> StravaTokenBundle | None:
    """Return the stored token bundle, or None if no tokens have been saved."""
    if _has_working_keyring():
        try:
            raw = keyring.get_password(_SERVICE, _USERNAME)
            if raw is not None:
                return _decode(raw)
        except Exception:
            pass
    # Fall back to file-based storage.
    path = _fallback_path()
    if not path.exists():
        return None
    return _decode(path.read_text(encoding="utf-8"))


def save_tokens(bundle: StravaTokenBundle) -> None:
    """Persist the token bundle to the OS keychain, or a restricted file if unavailable."""
    payload = json.dumps({
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
    })
    if _has_working_keyring():
        keyring.set_password(_SERVICE, _USERNAME, payload)
        # Remove any stale fallback file left from a prior session without keyring.
        path = _fallback_path()
        if path.exists():
            path.unlink()
    else:
        path = _fallback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def clear_tokens() -> None:
    """Remove any stored token bundle from the OS keychain and file fallback."""
    if _has_working_keyring():
        try:
            keyring.delete_password(_SERVICE, _USERNAME)
        except PasswordDeleteError:
            pass
    path = _fallback_path()
    if path.exists():
        path.unlink()
