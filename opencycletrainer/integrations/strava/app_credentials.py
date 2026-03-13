from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StravaAppCredentials:
    """App-wide Strava OAuth credentials."""

    client_id: str
    client_secret: str


def _load_from_secrets_module() -> tuple[str, str]:
    """Return (client_id, client_secret) from the gitignored _app_secrets module, or empty strings."""
    try:
        from . import _app_secrets  # noqa: PLC0415
        return (
            str(getattr(_app_secrets, "STRAVA_CLIENT_ID", "")).strip(),
            str(getattr(_app_secrets, "STRAVA_CLIENT_SECRET", "")).strip(),
        )
    except ImportError:
        return "", ""


def load_app_credentials() -> StravaAppCredentials:
    """Return Strava OAuth credentials.

    Resolution order:
    1. ``_app_secrets.py`` (gitignored bundled secrets file)
    2. ``OCT_STRAVA_CLIENT_ID`` / ``OCT_STRAVA_CLIENT_SECRET`` environment variables

    Raises EnvironmentError if credentials are not found in either source.
    """
    client_id, client_secret = _load_from_secrets_module()
    if not client_id or not client_secret:
        client_id = os.environ.get("OCT_STRAVA_CLIENT_ID", "").strip()
        client_secret = os.environ.get("OCT_STRAVA_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise EnvironmentError(
            "Strava OAuth credentials not configured. "
            "Populate _app_secrets.py or set OCT_STRAVA_CLIENT_ID and OCT_STRAVA_CLIENT_SECRET."
        )
    return StravaAppCredentials(client_id=client_id, client_secret=client_secret)


def has_app_credentials() -> bool:
    """Return True if Strava app credentials are available from any source."""
    client_id, client_secret = _load_from_secrets_module()
    if client_id and client_secret:
        return True
    return bool(
        os.environ.get("OCT_STRAVA_CLIENT_ID", "").strip()
        and os.environ.get("OCT_STRAVA_CLIENT_SECRET", "").strip()
    )
