"""Read the rider's planned workouts from the intervals.icu calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .ftp_service import _raise_for_failure, _requests
from .sync_service import _API_BASE, _BASIC_AUTH_USERNAME, _SELF_ATHLETE_ID

_REQUEST_TIMEOUT_SECONDS = 15
_WORKOUT_CATEGORY = "WORKOUT"
_RIDE_TYPES = frozenset({"Ride", "VirtualRide"})
_DAY_START_TIME = "T00:00:00"
_DAY_END_TIME = "T23:59:59"
_ISO_DATE_LENGTH = len("yyyy-mm-dd")
_DEFAULT_WORKOUT_NAME = "Planned workout"


@dataclass(frozen=True)
class PlannedWorkout:
    """A ride planned on the intervals.icu calendar."""

    event_id: int | str
    name: str


def fetch_planned_workouts(api_key: str, day: date, *, _http: object = None) -> list[PlannedWorkout]:
    """Return the rides planned on *day*, earliest first.

    The day is bounded by full timestamps, and each event's local start date is checked
    again here, so the result does not depend on how the server widens a date-only
    range. Raises RuntimeError if the key is rejected or the request fails. ``_http``
    is an injection point for testing only.
    """
    http = _http if _http is not None else _requests()
    day_text = day.isoformat()
    resp = http.get(
        f"{_API_BASE}/athlete/{_SELF_ATHLETE_ID}/events",
        auth=(_BASIC_AUTH_USERNAME, api_key),
        params={
            "oldest": f"{day_text}{_DAY_START_TIME}",
            "newest": f"{day_text}{_DAY_END_TIME}",
            "category": _WORKOUT_CATEGORY,
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    _raise_for_failure(resp)
    events = resp.json()
    if not isinstance(events, list):
        return []
    rides = [
        event for event in events
        if isinstance(event, dict)
        and event.get("id") is not None
        and event.get("category", _WORKOUT_CATEGORY) == _WORKOUT_CATEGORY
        and event.get("type") in _RIDE_TYPES
        and str(event.get("start_date_local", ""))[:_ISO_DATE_LENGTH] == day_text
    ]
    rides.sort(key=lambda event: str(event.get("start_date_local", "")))
    return [
        PlannedWorkout(event_id=event["id"], name=str(event.get("name") or _DEFAULT_WORKOUT_NAME))
        for event in rides
    ]


def download_planned_workout(api_key: str, event_id: int | str, *, _http: object = None) -> str:
    """Return a planned workout as ZWO text, with targets as fractions of FTP.

    Raises RuntimeError if the key is rejected or the request fails. ``_http`` is an
    injection point for testing only.
    """
    http = _http if _http is not None else _requests()
    resp = http.get(
        f"{_API_BASE}/athlete/{_SELF_ATHLETE_ID}/events/{event_id}/download.zwo",
        auth=(_BASIC_AUTH_USERNAME, api_key),
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    _raise_for_failure(resp)
    return resp.text
