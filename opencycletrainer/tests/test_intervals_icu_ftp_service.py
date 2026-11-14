"""Reading and writing the rider's FTP on intervals.icu."""

from __future__ import annotations

import pytest

from opencycletrainer.integrations.intervalsicu.ftp_service import (
    RemoteFtp,
    fetch_ftp,
    push_ftp,
    select_cycling_ftp,
)

_RUN = {"id": 11, "types": ["Run", "VirtualRun"], "ftp": 320, "indoor_ftp": None}
_RIDE = {"id": 22, "types": ["Ride", "GravelRide", "VirtualRide"], "ftp": 260, "indoor_ftp": None}


class _Response:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Http:
    """Records requests and answers them with a canned response."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append(("GET", url, kwargs))
        return self.response

    def put(self, url: str, **kwargs: object) -> _Response:
        self.calls.append(("PUT", url, kwargs))
        return self.response


def test_cycling_ftp_is_chosen_over_other_sports():
    assert select_cycling_ftp([_RUN, _RIDE]) == RemoteFtp(watts=260, settings_id=22, indoor=False)


def test_separate_indoor_ftp_is_preferred_when_set():
    ride = {**_RIDE, "indoor_ftp": 250}

    assert select_cycling_ftp([ride]) == RemoteFtp(watts=250, settings_id=22, indoor=True)


def test_indoor_ftp_of_zero_counts_as_unset():
    ride = {**_RIDE, "indoor_ftp": 0}

    assert select_cycling_ftp([ride]) == RemoteFtp(watts=260, settings_id=22, indoor=False)


def test_settings_covering_virtual_rides_win_over_outdoor_only_settings():
    outdoor = {"id": 1, "types": ["Ride"], "ftp": 270}
    virtual = {"id": 2, "types": ["VirtualRide"], "ftp": 255}

    assert select_cycling_ftp([outdoor, virtual]) == RemoteFtp(watts=255, settings_id=2, indoor=False)


@pytest.mark.parametrize(
    "sport_settings",
    [[], [_RUN], [{"id": 22, "types": ["Ride"], "ftp": None}], [{"id": 22, "types": ["Ride"]}], None, "oops"],
)
def test_no_ftp_is_reported_when_cycling_has_none(sport_settings):
    assert select_cycling_ftp(sport_settings) is None


def test_fetch_reads_the_key_owners_sport_settings():
    http = _Http(_Response(payload={"id": "i123", "sportSettings": [_RUN, _RIDE]}))

    remote = fetch_ftp("secret", _http=http)

    assert remote == RemoteFtp(watts=260, settings_id=22, indoor=False)
    method, url, kwargs = http.calls[0]
    assert (method, url) == ("GET", "https://intervals.icu/api/v1/athlete/0")
    assert kwargs["auth"] == ("API_KEY", "secret")
    assert kwargs["timeout"] > 0


@pytest.mark.parametrize("status", [401, 403])
def test_fetch_reports_a_rejected_key(status):
    http = _Http(_Response(status_code=status))

    with pytest.raises(RuntimeError, match="rejected the API key"):
        fetch_ftp("bad", _http=http)


def test_push_updates_only_the_field_that_was_read():
    http = _Http(_Response())

    push_ftp("secret", RemoteFtp(watts=250, settings_id=22, indoor=True), 265, _http=http)

    method, url, kwargs = http.calls[0]
    assert (method, url) == ("PUT", "https://intervals.icu/api/v1/athlete/0/sport-settings/22")
    assert kwargs["json"] == {"indoor_ftp": 265}
    assert kwargs["auth"] == ("API_KEY", "secret")


def test_push_updates_the_main_ftp_when_no_indoor_value_exists():
    http = _Http(_Response())

    push_ftp("secret", RemoteFtp(watts=260, settings_id=22, indoor=False), 265, _http=http)

    assert http.calls[0][2]["json"] == {"ftp": 265}


def test_push_failure_is_raised():
    http = _Http(_Response(status_code=500))

    with pytest.raises(RuntimeError):
        push_ftp("secret", RemoteFtp(watts=260, settings_id=22, indoor=False), 265, _http=http)
