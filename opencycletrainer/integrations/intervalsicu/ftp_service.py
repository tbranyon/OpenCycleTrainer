"""Read and update the rider's cycling FTP on intervals.icu."""

from __future__ import annotations

from dataclasses import dataclass

from .sync_service import _API_BASE, _BASIC_AUTH_USERNAME, _SELF_ATHLETE_ID

_REQUEST_TIMEOUT_SECONDS = 15
_REJECTED_KEY_STATUSES = (401, 403)
# Sport settings are matched by activity type. Settings that cover indoor rides are
# preferred, since those are the rides this app records.
_CYCLING_TYPES = ("VirtualRide", "Ride")
_FTP_FIELD = "ftp"
_INDOOR_FTP_FIELD = "indoor_ftp"


@dataclass(frozen=True)
class RemoteFtp:
    """The FTP intervals.icu holds for cycling, and where it was read from."""

    watts: int
    settings_id: int | str
    indoor: bool  # True when the value is the sport's separate indoor FTP

    @property
    def field(self) -> str:
        """Name of the sport-settings field this value lives in."""
        return _INDOOR_FTP_FIELD if self.indoor else _FTP_FIELD


def select_cycling_ftp(sport_settings: object) -> RemoteFtp | None:
    """Pick the cycling FTP from an athlete's sport settings, or None if there is none.

    A separate indoor FTP is used when one is set; otherwise the sport's main FTP.
    """
    if not isinstance(sport_settings, list):
        return None
    for activity_type in _CYCLING_TYPES:
        for entry in sport_settings:
            if not isinstance(entry, dict) or activity_type not in (entry.get("types") or ()):
                continue
            settings_id = entry.get("id")
            if settings_id is None:
                continue
            for field, indoor in ((_INDOOR_FTP_FIELD, True), (_FTP_FIELD, False)):
                watts = entry.get(field)
                if isinstance(watts, (int, float)) and watts > 0:
                    return RemoteFtp(watts=int(round(watts)), settings_id=settings_id, indoor=indoor)
    return None


def fetch_ftp(api_key: str, *, _http: object = None) -> RemoteFtp | None:
    """Return the cycling FTP stored on intervals.icu, or None if none is set.

    Raises RuntimeError if the key is rejected or the request fails. ``_http`` is an
    injection point for testing only.
    """
    http = _http if _http is not None else _requests()
    resp = http.get(
        f"{_API_BASE}/athlete/{_SELF_ATHLETE_ID}",
        auth=(_BASIC_AUTH_USERNAME, api_key),
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    _raise_for_failure(resp)
    data = resp.json()
    athlete = data.get("athlete", data) if isinstance(data, dict) else {}
    return select_cycling_ftp(athlete.get("sportSettings") if isinstance(athlete, dict) else None)


def push_ftp(api_key: str, remote: RemoteFtp, watts: int, *, _http: object = None) -> None:
    """Set the FTP on intervals.icu, writing the same field *remote* was read from.

    Raises RuntimeError if the key is rejected or the request fails. ``_http`` is an
    injection point for testing only.
    """
    http = _http if _http is not None else _requests()
    resp = http.put(
        f"{_API_BASE}/athlete/{_SELF_ATHLETE_ID}/sport-settings/{remote.settings_id}",
        auth=(_BASIC_AUTH_USERNAME, api_key),
        json={remote.field: int(watts)},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    _raise_for_failure(resp)


def _requests() -> object:
    import requests  # noqa: PLC0415

    return requests


def _raise_for_failure(resp: object) -> None:
    if getattr(resp, "status_code", None) in _REJECTED_KEY_STATUSES:
        raise RuntimeError("intervals.icu rejected the API key")
    try:
        resp.raise_for_status()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"intervals.icu request failed: {exc}") from exc
