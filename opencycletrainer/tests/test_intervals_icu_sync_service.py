from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.integrations.intervalsicu.sync_service import (
    DuplicateUploadError,
    upload_fit_to_intervals_icu,
)

# Common injectable no-ops that isolate tests from real history/keyring.
_NO_HISTORY = lambda _: False  # noqa: E731
_NO_RECORD = lambda _: None  # noqa: E731


# ── happy path ────────────────────────────────────────────────────────────────

def test_upload_happy_path_calls_upload_impl(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    calls: list[tuple[Path, str]] = []

    def fake_upload(path: Path, api_key: str, activity_name: str | None = None) -> None:  # noqa: ARG001
        calls.append((path, api_key))

    upload_fit_to_intervals_icu(
        fit_file,
        _key_getter=lambda: "KEY123",
        _upload_impl=fake_upload,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert calls == [(fit_file, "KEY123")]


def test_upload_forwards_activity_name_to_upload_impl(tmp_path: Path) -> None:
    fit_file = tmp_path / "Threshold_20260309_1842.fit"
    fit_file.write_bytes(b"FIT")
    names: list[str | None] = []

    upload_fit_to_intervals_icu(
        fit_file,
        "Tuesday Threshold",
        _key_getter=lambda: "KEY123",
        _upload_impl=lambda _p, _k, n=None: names.append(n),
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert names == ["Tuesday Threshold"]


def test_upload_passes_none_activity_name_when_not_provided(tmp_path: Path) -> None:
    fit_file = tmp_path / "Threshold_20260309_1842.fit"
    fit_file.write_bytes(b"FIT")
    names: list[str | None] = []

    upload_fit_to_intervals_icu(
        fit_file,
        _key_getter=lambda: "KEY123",
        _upload_impl=lambda _p, _k, n=None: names.append(n),
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert names == [None]


# ── no key ────────────────────────────────────────────────────────────────────

def test_upload_raises_when_no_api_key(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    with pytest.raises(RuntimeError, match="No intervals.icu API key"):
        upload_fit_to_intervals_icu(
            fit_file,
            _key_getter=lambda: None,
            _history_checker=_NO_HISTORY,
        )


# ── retries ───────────────────────────────────────────────────────────────────

def test_upload_retries_on_transient_failure(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    attempt = [0]

    def flaky_upload(path: Path, api_key: str, activity_name: str | None = None) -> None:  # noqa: ARG001
        attempt[0] += 1
        if attempt[0] < 2:
            raise OSError("network blip")

    upload_fit_to_intervals_icu(
        fit_file,
        _key_getter=lambda: "KEY123",
        _upload_impl=flaky_upload,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert attempt[0] == 2


def test_upload_raises_after_max_retries(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    def always_fails(_path: Path, _key: str, _name: str | None = None) -> None:
        raise OSError("server down")

    with pytest.raises(RuntimeError, match="failed after"):
        upload_fit_to_intervals_icu(
            fit_file,
            _key_getter=lambda: "KEY123",
            _upload_impl=always_fails,
            _history_checker=_NO_HISTORY,
            _history_recorder=_NO_RECORD,
        )


# ── duplicate upload prevention ───────────────────────────────────────────────

def test_upload_raises_duplicate_error_when_already_uploaded(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    with pytest.raises(DuplicateUploadError):
        upload_fit_to_intervals_icu(
            fit_file,
            _key_getter=lambda: "KEY123",
            _history_checker=lambda _: True,  # already uploaded
        )


def test_upload_does_not_attempt_when_duplicate(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    calls: list[Path] = []

    with pytest.raises(DuplicateUploadError):
        upload_fit_to_intervals_icu(
            fit_file,
            _key_getter=lambda: "KEY123",
            _upload_impl=lambda _p, _k, _n=None: calls.append(_p),
            _history_checker=lambda _: True,
        )

    assert calls == []


def test_upload_raises_duplicate_when_server_reports_duplicate(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    def dup_upload(_path: Path, _key: str, _name: str | None = None) -> None:
        raise DuplicateUploadError("intervals.icu reported a duplicate activity")

    with pytest.raises(DuplicateUploadError):
        upload_fit_to_intervals_icu(
            fit_file,
            _key_getter=lambda: "KEY123",
            _upload_impl=dup_upload,
            _history_checker=_NO_HISTORY,
            _history_recorder=_NO_RECORD,
        )


def test_upload_records_success_in_history(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    recorded: list[Path] = []

    upload_fit_to_intervals_icu(
        fit_file,
        _key_getter=lambda: "KEY123",
        _upload_impl=lambda _p, _k, _n=None: None,
        _history_checker=_NO_HISTORY,
        _history_recorder=recorded.append,
    )

    assert recorded == [fit_file]


def test_upload_does_not_record_history_on_failure(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    recorded: list[Path] = []

    with pytest.raises(RuntimeError):
        upload_fit_to_intervals_icu(
            fit_file,
            _key_getter=lambda: "KEY123",
            _upload_impl=lambda _p, _k, _n=None: (_ for _ in ()).throw(OSError("fail")),
            _history_checker=_NO_HISTORY,
            _history_recorder=recorded.append,
        )

    assert recorded == []
