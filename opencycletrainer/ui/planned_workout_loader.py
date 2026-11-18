"""Fetches today's planned workout from intervals.icu for the workout tab."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import logging

from PySide6.QtCore import QObject, Signal

from opencycletrainer.integrations.intervalsicu.planned_workouts import (
    PlannedWorkout,
    download_planned_workout,
    fetch_planned_workouts,
)

_logger = logging.getLogger(__name__)

_NOTHING_PLANNED_MESSAGE = "No ride planned on intervals.icu for today"
_FAILURE_MESSAGE = "Couldn't load today's workout from intervals.icu: {error}"


class PlannedWorkoutLoader(QObject):
    """Finds the rides planned for today and loads the one the rider picks.

    Network calls run off the UI thread and their results come back through signals,
    so choosing, loading and notifying all happen on the UI thread. Requests made while
    one is still in flight are ignored.
    """

    _fetched = Signal(object)       # list[PlannedWorkout] | Exception
    _downloaded = Signal(str, object)  # workout name, ZWO text | Exception

    def __init__(
        self,
        *,
        api_key_getter: Callable[[], str | None],
        choose: Callable[[list[PlannedWorkout]], PlannedWorkout | None],
        load: Callable[[str, str], None],
        notify: Callable[[str], None],
        today: Callable[[], date] = date.today,
        fetch_fn: Callable[[str, date], list[PlannedWorkout]] = fetch_planned_workouts,
        download_fn: Callable[[str, int | str], str] = download_planned_workout,
        run_async: Callable[[Callable[[], None]], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api_key_getter = api_key_getter
        self._choose = choose
        self._load = load
        self._notify = notify
        self._today = today
        self._fetch_fn = fetch_fn
        self._download_fn = download_fn
        self._executor: ThreadPoolExecutor | None = None
        self._run_async = run_async if run_async is not None else self._submit
        self._busy = False

        self._fetched.connect(self._on_fetched)
        self._downloaded.connect(self._on_downloaded)

    def request(self) -> None:
        """Look up today's planned rides. No-op when not connected or already looking."""
        api_key = self._api_key_getter()
        if not api_key or self._busy:
            return
        self._busy = True
        day = self._today()
        self._run_async(lambda: self._fetched.emit(self._attempt(self._fetch_fn, api_key, day)))

    def shutdown(self) -> None:
        """Stop accepting background work; requests in flight are abandoned."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _on_fetched(self, result: object) -> None:
        if isinstance(result, Exception):
            self._fail(result)
            return
        planned = list(result) if isinstance(result, list) else []
        if not planned:
            self._busy = False
            self._notify(_NOTHING_PLANNED_MESSAGE)
            return
        chosen = planned[0] if len(planned) == 1 else self._choose(planned)
        api_key = self._api_key_getter()
        if chosen is None or not api_key:
            self._busy = False
            return
        self._run_async(
            lambda: self._downloaded.emit(
                chosen.name, self._attempt(self._download_fn, api_key, chosen.event_id)
            )
        )

    def _on_downloaded(self, name: str, result: object) -> None:
        if isinstance(result, Exception):
            self._fail(result)
            return
        self._busy = False
        self._load(str(result), name)

    def _fail(self, error: Exception) -> None:
        self._busy = False
        self._notify(_FAILURE_MESSAGE.format(error=error))

    @staticmethod
    def _attempt(fn: Callable[..., object], *args: object) -> object:
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("intervals.icu planned workout request failed: %s", exc)
            return exc

    def _submit(self, job: Callable[[], None]) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intervals-icu-plan")
        self._executor.submit(job)
