"""FTP is kept in step with intervals.icu, always asking the rider first."""

from __future__ import annotations

from collections.abc import Callable

from opencycletrainer.integrations.intervalsicu.ftp_service import RemoteFtp
from opencycletrainer.ui.ftp_sync import IntervalsIcuFtpSync

_REMOTE = RemoteFtp(watts=270, settings_id=22, indoor=False)


class _Rider:
    """Stands in for the app: holds the local FTP and answers prompts."""

    def __init__(self, *, ftp: int = 250, api_key: str | None = "secret", answer: bool = True) -> None:
        self.ftp = ftp
        self.api_key = api_key
        self.answer = answer
        self.declined_ftp: int | None = None
        self.prompts: list[tuple[str, str]] = []
        self.notices: list[str] = []
        self.remote: RemoteFtp | None | Exception = _REMOTE
        self.fetches = 0
        self.pushes: list[tuple[str, RemoteFtp, int]] = []
        self.push_error: Exception | None = None
        self.deferred: list[Callable[[], None]] | None = None

    def confirm(self, title: str, text: str) -> bool:
        self.prompts.append((title, text))
        return self.answer

    def fetch(self, api_key: str) -> RemoteFtp | None:  # noqa: ARG002
        self.fetches += 1
        if isinstance(self.remote, Exception):
            raise self.remote
        return self.remote

    def push(self, api_key: str, remote: RemoteFtp, watts: int) -> None:
        if self.push_error is not None:
            raise self.push_error
        self.pushes.append((api_key, remote, watts))

    def run(self, job: Callable[[], None]) -> None:
        if self.deferred is None:
            job()
        else:
            self.deferred.append(job)

    def set_ftp(self, watts: int) -> None:
        self.ftp = watts

    def remember_declined(self, watts: int | None) -> None:
        self.declined_ftp = watts


def _sync(rider: _Rider) -> IntervalsIcuFtpSync:
    return IntervalsIcuFtpSync(
        api_key_getter=lambda: rider.api_key,
        local_ftp_getter=lambda: rider.ftp,
        apply_local_ftp=rider.set_ftp,
        confirm=rider.confirm,
        notify=rider.notices.append,
        declined_ftp_getter=lambda: rider.declined_ftp,
        remember_declined_ftp=rider.remember_declined,
        fetch_fn=rider.fetch,
        push_fn=rider.push,
        run_async=rider.run,
    )


# ── Startup: offer to pull ────────────────────────────────────────────────────


def test_startup_does_nothing_when_intervals_icu_is_not_connected(qapp):
    rider = _Rider(api_key=None)

    _sync(rider).check_on_startup()

    assert rider.fetches == 0 and rider.prompts == []


def test_startup_is_silent_when_ftp_already_matches(qapp):
    rider = _Rider(ftp=270)

    _sync(rider).check_on_startup()

    assert rider.prompts == [] and rider.ftp == 270


def test_startup_offers_the_intervals_icu_ftp_and_applies_it_on_yes(qapp):
    rider = _Rider(ftp=250, answer=True)

    _sync(rider).check_on_startup()

    assert len(rider.prompts) == 1
    assert "270" in rider.prompts[0][1] and "250" in rider.prompts[0][1]
    assert rider.ftp == 270
    assert rider.pushes == []


def test_startup_keeps_the_local_ftp_on_no_and_does_not_ask_again_for_that_value(qapp):
    rider = _Rider(ftp=250, answer=False)

    _sync(rider).check_on_startup()
    _sync(rider).check_on_startup()  # next launch, intervals.icu unchanged

    assert rider.ftp == 250
    assert len(rider.prompts) == 1


def test_startup_asks_again_once_intervals_icu_has_a_new_value(qapp):
    rider = _Rider(ftp=250, answer=False)
    _sync(rider).check_on_startup()
    rider.remote = RemoteFtp(watts=280, settings_id=22, indoor=False)

    _sync(rider).check_on_startup()

    assert len(rider.prompts) == 2 and "280" in rider.prompts[1][1]


def test_startup_stays_quiet_when_intervals_icu_cannot_be_reached(qapp):
    rider = _Rider()
    rider.remote = RuntimeError("offline")

    _sync(rider).check_on_startup()

    assert rider.prompts == [] and rider.notices == [] and rider.ftp == 250


def test_startup_stays_quiet_when_intervals_icu_has_no_cycling_ftp(qapp):
    rider = _Rider()
    rider.remote = None

    _sync(rider).check_on_startup()

    assert rider.prompts == [] and rider.ftp == 250


def test_startup_prompt_names_the_indoor_ftp_when_that_is_what_was_read(qapp):
    rider = _Rider()
    rider.remote = RemoteFtp(watts=270, settings_id=22, indoor=True)

    _sync(rider).check_on_startup()

    assert "indoor FTP" in rider.prompts[0][1]


# ── Editing FTP: offer to push ────────────────────────────────────────────────


def test_new_ftp_is_offered_to_intervals_icu_and_pushed_on_yes(qapp):
    rider = _Rider(ftp=250, answer=True)
    sync = _sync(rider)
    rider.ftp = 265

    sync.on_local_ftp_edited(265)

    assert len(rider.prompts) == 1
    assert "270" in rider.prompts[0][1] and "265" in rider.prompts[0][1]
    assert rider.pushes == [("secret", _REMOTE, 265)]
    assert any("265" in notice for notice in rider.notices)


def test_new_ftp_is_not_pushed_on_no_and_the_same_value_is_not_offered_twice(qapp):
    rider = _Rider(ftp=250, answer=False)
    sync = _sync(rider)
    rider.ftp = 265

    sync.on_local_ftp_edited(265)
    sync.on_local_ftp_edited(265)  # e.g. Enter followed by the field losing focus

    assert rider.pushes == []
    assert len(rider.prompts) == 1 and rider.fetches == 1


def test_no_push_is_offered_when_intervals_icu_already_has_the_new_ftp(qapp):
    rider = _Rider(ftp=250)
    sync = _sync(rider)
    rider.ftp = 270

    sync.on_local_ftp_edited(270)

    assert rider.prompts == [] and rider.pushes == []


def test_leaving_the_ftp_field_unchanged_checks_nothing(qapp):
    rider = _Rider(ftp=250)

    _sync(rider).on_local_ftp_edited(250)

    assert rider.fetches == 0


def test_editing_ftp_does_nothing_when_intervals_icu_is_not_connected(qapp):
    rider = _Rider(ftp=250, api_key=None)
    sync = _sync(rider)

    sync.on_local_ftp_edited(265)

    assert rider.fetches == 0 and rider.prompts == []


def test_failed_push_tells_the_rider(qapp):
    rider = _Rider(ftp=250, answer=True)
    rider.push_error = RuntimeError("HTTP 500")
    sync = _sync(rider)
    rider.ftp = 265

    sync.on_local_ftp_edited(265)

    assert len(rider.notices) == 1
    assert rider.notices[0].startswith("Couldn't update FTP on intervals.icu")


def test_accepting_the_intervals_icu_ftp_does_not_offer_to_push_it_back(qapp):
    rider = _Rider(ftp=250, answer=True)
    sync = _sync(rider)
    sync.check_on_startup()

    sync.on_local_ftp_edited(270)

    assert rider.fetches == 1 and len(rider.prompts) == 1 and rider.pushes == []


def test_push_offer_is_dropped_if_ftp_changed_again_before_the_answer_arrived(qapp):
    rider = _Rider(ftp=250, answer=True)
    rider.deferred = []
    sync = _sync(rider)
    rider.ftp = 265
    sync.on_local_ftp_edited(265)
    rider.ftp = 266  # still typing while intervals.icu is being asked

    for job in rider.deferred:
        job()

    assert rider.prompts == [] and rider.pushes == []
