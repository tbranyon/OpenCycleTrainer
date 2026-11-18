"""Fetching today's planned workout from intervals.icu and handing it to the workout tab."""

from __future__ import annotations

from datetime import date

import pytest

from opencycletrainer.integrations.intervalsicu.planned_workouts import PlannedWorkout
from opencycletrainer.ui.planned_workout_loader import PlannedWorkoutLoader

_TODAY = date(2026, 11, 18)
_MORNING = PlannedWorkout(event_id=1, name="Morning Spin")
_EVENING = PlannedWorkout(event_id=2, name="Evening VO2")


class _Rider:
    """Fakes intervals.icu and the rider's answers, and records what reached the app."""

    def __init__(self, planned: list[PlannedWorkout] | Exception, *, pick: int | None = 0) -> None:
        self.planned = planned
        self.pick = pick
        self.download_error: Exception | None = None
        self.choices_offered: list[list[PlannedWorkout]] = []
        self.fetch_days: list[date] = []
        self.loaded: list[tuple[str, str]] = []
        self.notices: list[str] = []

    def fetch(self, api_key: str, day: date) -> list[PlannedWorkout]:
        assert api_key == "secret"
        self.fetch_days.append(day)
        if isinstance(self.planned, Exception):
            raise self.planned
        return self.planned

    def download(self, api_key: str, event_id: int) -> str:
        assert api_key == "secret"
        if self.download_error is not None:
            raise self.download_error
        return f"<zwo {event_id}>"

    def choose(self, options: list[PlannedWorkout]) -> PlannedWorkout | None:
        self.choices_offered.append(options)
        return None if self.pick is None else options[self.pick]

    def loader(self, *, api_key: str | None = "secret", run_async=None) -> PlannedWorkoutLoader:
        return PlannedWorkoutLoader(
            api_key_getter=lambda: api_key,
            today=lambda: _TODAY,
            choose=self.choose,
            load=lambda text, name: self.loaded.append((text, name)),
            notify=self.notices.append,
            fetch_fn=self.fetch,
            download_fn=self.download,
            run_async=run_async or (lambda job: job()),
        )


def test_a_single_planned_workout_loads_without_asking(qapp):
    rider = _Rider([_MORNING])

    rider.loader().request()

    assert rider.fetch_days == [_TODAY]
    assert rider.choices_offered == []
    assert rider.loaded == [("<zwo 1>", "Morning Spin")]


def test_several_planned_workouts_let_the_rider_choose(qapp):
    rider = _Rider([_MORNING, _EVENING], pick=1)

    rider.loader().request()

    assert rider.choices_offered == [[_MORNING, _EVENING]]
    assert rider.loaded == [("<zwo 2>", "Evening VO2")]


def test_cancelling_the_choice_loads_nothing(qapp):
    rider = _Rider([_MORNING, _EVENING], pick=None)

    rider.loader().request()

    assert rider.loaded == []
    assert rider.notices == []


def test_no_planned_workout_tells_the_rider(qapp):
    rider = _Rider([])

    rider.loader().request()

    assert rider.loaded == []
    assert len(rider.notices) == 1
    assert "no ride planned" in rider.notices[0].lower()


@pytest.mark.parametrize("failing_step", ["fetch", "download"])
def test_a_failed_request_tells_the_rider(qapp, failing_step):
    error = RuntimeError("intervals.icu rejected the API key")
    rider = _Rider(error if failing_step == "fetch" else [_MORNING])
    if failing_step == "download":
        rider.download_error = error

    rider.loader().request()

    assert rider.loaded == []
    assert len(rider.notices) == 1
    assert "rejected the API key" in rider.notices[0]


def test_nothing_is_fetched_when_intervals_icu_is_not_connected(qapp):
    rider = _Rider([_MORNING])

    rider.loader(api_key=None).request()

    assert rider.fetch_days == []
    assert rider.loaded == []


def test_a_second_request_is_ignored_while_one_is_in_flight(qapp):
    rider = _Rider([_MORNING])
    pending: list = []
    loader = rider.loader(run_async=pending.append)

    loader.request()
    loader.request()
    while pending:
        pending.pop(0)()

    assert rider.fetch_days == [_TODAY]
    assert rider.loaded == [("<zwo 1>", "Morning Spin")]
