from __future__ import annotations

import json
from dataclasses import dataclass

import keyring
from keyring.errors import PasswordDeleteError

_SERVICE = "OpenCycleTrainer/Strava"
_USERNAME = "default"


@dataclass(frozen=True)
class StravaTokenBundle:
    """Per-user Strava OAuth token payload stored in the OS keychain."""

    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp


def is_available() -> bool:
    """Return True if the active keyring backend can store and retrieve passwords."""
    try:
        backend = keyring.get_keyring()
        # The fail backend raises on every operation; treat it as unavailable.
        backend.get_password(_SERVICE, "__probe__")
        return True
    except Exception:
        return False


def get_tokens() -> StravaTokenBundle | None:
    """Return the stored token bundle, or None if no tokens have been saved or keyring is unavailable."""
    try:
        raw = keyring.get_password(_SERVICE, _USERNAME)
    except Exception:
        return None
    if raw is None:
        return None
    data = json.loads(raw)
    return StravaTokenBundle(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=int(data["expires_at"]),
    )


def save_tokens(bundle: StravaTokenBundle) -> None:
    """Persist the token bundle to the OS keychain."""
    payload = json.dumps({
        "access_token": bundle.access_token,
        "refresh_token": bundle.refresh_token,
        "expires_at": bundle.expires_at,
    })
    keyring.set_password(_SERVICE, _USERNAME, payload)


def clear_tokens() -> None:
    """Remove any stored token bundle from the OS keychain."""
    try:
        keyring.delete_password(_SERVICE, _USERNAME)
    except PasswordDeleteError:
        pass
