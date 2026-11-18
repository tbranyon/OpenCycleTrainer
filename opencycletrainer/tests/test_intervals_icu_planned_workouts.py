"""Reading the rider's planned workouts from the intervals.icu calendar."""

from __future__ import annotations

from datetime import date

import pytest

from opencycletrainer.integrations.intervalsicu.planned_workouts import (
    PlannedWorkout,
    download_planned_workout,
    fetch_planned_workouts,
)

_TODAY = date(2026, 11, 18)


class _Response:
    def __init__(self, status_code: int = 200, payload: object = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Http:
    """Records GET requests and answers them with a canned response."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return self.response


def _event(event_id: int, name: str, *, start: str, activity_type: str = "Ride") -> dict:
    return {
        "id": event_id,
        "name": name,
        "category": "WORKOUT",
        "type": activity_type,
        "start_date_local": start,
    }


def test_fetch_returns_todays_rides_in_start_order():
    events = [
        _event(1, "Evening VO2", start="2026-11-18T18:00:00"),
        _event(2, "Easy Run", start="2026-11-18T07:00:00", activity_type="Run"),
        _event(3, "Morning Spin", start="2026-11-18T06:30:00", activity_type="VirtualRide"),
        _event(4, "Tomorrow's Ride", start="2026-11-19T00:00:00"),
    ]
    http = _Http(_Response(payload=events))

    planned = fetch_planned_workouts("secret", _TODAY, _http=http)

    assert planned == [
        PlannedWorkout(event_id=3, name="Morning Spin"),
        PlannedWorkout(event_id=1, name="Evening VO2"),
    ]
    url, kwargs = http.calls[0]
    assert url == "https://intervals.icu/api/v1/athlete/0/events"
    assert kwargs["auth"] == ("API_KEY", "secret")
    assert kwargs["params"]["category"] == "WORKOUT"
    assert kwargs["params"]["oldest"].startswith("2026-11-18")
    assert kwargs["params"]["newest"].startswith("2026-11-18")


def test_fetch_ignores_a_malformed_reply():
    http = _Http(_Response(payload={"unexpected": "shape"}))

    assert fetch_planned_workouts("secret", _TODAY, _http=http) == []


def test_download_returns_the_workout_as_zwo_text():
    http = _Http(_Response(text="<workout_file/>"))

    text = download_planned_workout("secret", 42, _http=http)

    assert text == "<workout_file/>"
    url, kwargs = http.calls[0]
    assert url == "https://intervals.icu/api/v1/athlete/0/events/42/download.zwo"
    assert kwargs["auth"] == ("API_KEY", "secret")


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize(
    "call",
    [
        lambda http: fetch_planned_workouts("bad", _TODAY, _http=http),
        lambda http: download_planned_workout("bad", 42, _http=http),
    ],
    ids=["fetch", "download"],
)
def test_requests_report_a_rejected_key(call, status):
    with pytest.raises(RuntimeError, match="rejected the API key"):
        call(_Http(_Response(status_code=status)))
