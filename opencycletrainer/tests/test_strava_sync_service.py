from __future__ import annotations

import time
from pathlib import Path

import pytest

from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError, upload_fit_to_strava
from opencycletrainer.integrations.strava.token_store import StravaTokenBundle

# Common injectable no-ops that isolate tests from real history/keyring.
_NO_HISTORY = lambda _: False  # noqa: E731
_NO_RECORD = lambda _: None  # noqa: E731


def _make_tokens(*, expired: bool = False) -> StravaTokenBundle:
    expires_at = int(time.time()) + (-10 if expired else 3600)
    return StravaTokenBundle(
        access_token="acc_tok",
        refresh_token="ref_tok",
        expires_at=expires_at,
    )


def _make_refreshed_tokens() -> StravaTokenBundle:
    return StravaTokenBundle(
        access_token="new_acc",
        refresh_token="new_ref",
        expires_at=int(time.time()) + 3600,
    )


# ── happy path ────────────────────────────────────────────────────────────────

def test_upload_happy_path_calls_upload_impl(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    calls: list[tuple[Path, str]] = []

    def fake_upload(path: Path, access_token: str) -> None:
        calls.append((path, access_token))

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=fake_upload,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert calls == [(fit_file, "acc_tok")]


# ── no tokens ─────────────────────────────────────────────────────────────────

def test_upload_raises_when_no_tokens(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    with pytest.raises(RuntimeError, match="No Strava tokens"):
        upload_fit_to_strava(
            fit_file,
            _token_getter=lambda: None,
            _history_checker=_NO_HISTORY,
        )


# ── token refresh ─────────────────────────────────────────────────────────────

def test_upload_refreshes_expired_tokens(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    expired = _make_tokens(expired=True)
    refreshed = _make_refreshed_tokens()
    refresh_calls: list[StravaTokenBundle] = []

    def fake_refresh(t: StravaTokenBundle) -> StravaTokenBundle:
        refresh_calls.append(t)
        return refreshed

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: expired,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, _t: None,
        _refresh_impl=fake_refresh,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert len(refresh_calls) == 1
    assert refresh_calls[0] is expired


def test_upload_saves_refreshed_tokens(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    expired = _make_tokens(expired=True)
    refreshed = _make_refreshed_tokens()
    saved: list[StravaTokenBundle] = []

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: expired,
        _token_saver=saved.append,
        _upload_impl=lambda _p, _t: None,
        _refresh_impl=lambda _t: refreshed,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert saved == [refreshed]


def test_upload_uses_refreshed_access_token(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    expired = _make_tokens(expired=True)
    refreshed = _make_refreshed_tokens()
    used_tokens: list[str] = []

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: expired,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, t: used_tokens.append(t),
        _refresh_impl=lambda _t: refreshed,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert used_tokens == ["new_acc"]


# ── retries ───────────────────────────────────────────────────────────────────

def test_upload_retries_on_transient_failure(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    attempt = [0]

    def flaky_upload(path: Path, access_token: str) -> None:  # noqa: ARG001
        attempt[0] += 1
        if attempt[0] < 2:
            raise OSError("network blip")

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=flaky_upload,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert attempt[0] == 2


def test_upload_raises_after_max_retries(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()

    def always_fails(_path: Path, _token: str) -> None:
        raise OSError("server down")

    with pytest.raises(RuntimeError, match="failed after"):
        upload_fit_to_strava(
            fit_file,
            _token_getter=lambda: tokens,
            _token_saver=lambda _: None,
            _upload_impl=always_fails,
            _history_checker=_NO_HISTORY,
            _history_recorder=_NO_RECORD,
        )


def test_upload_no_refresh_when_token_valid(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens(expired=False)
    refresh_calls: list[object] = []

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, _t: None,
        _refresh_impl=lambda t: (refresh_calls.append(t), t)[1],
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
    )

    assert refresh_calls == []


# ── duplicate upload prevention ───────────────────────────────────────────────

def test_upload_raises_duplicate_error_when_already_uploaded(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()

    with pytest.raises(DuplicateUploadError):
        upload_fit_to_strava(
            fit_file,
            _token_getter=lambda: tokens,
            _history_checker=lambda _: True,  # already uploaded
        )


def test_upload_records_success_in_history(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    recorded: list[Path] = []

    upload_fit_to_strava(
        fit_file,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, _t: None,
        _history_checker=_NO_HISTORY,
        _history_recorder=recorded.append,
    )

    assert recorded == [fit_file]


def test_upload_does_not_record_history_on_failure(tmp_path: Path) -> None:
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    recorded: list[Path] = []

    with pytest.raises(RuntimeError):
        upload_fit_to_strava(
            fit_file,
            _token_getter=lambda: tokens,
            _token_saver=lambda _: None,
            _upload_impl=lambda _p, _t: (_ for _ in ()).throw(OSError("fail")),
            _history_checker=_NO_HISTORY,
            _history_recorder=recorded.append,
        )

    assert recorded == []


# ── chart image upload ────────────────────────────────────────────────────────

def test_image_upload_called_after_successful_fit_upload(tmp_path: Path) -> None:
    """Image uploader is called with the activity_id returned by the FIT upload."""
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    chart_image = tmp_path / "chart.png"
    chart_image.write_bytes(b"PNG")
    image_calls: list[tuple[str, Path, str]] = []

    def fake_upload(path: Path, access_token: str) -> str:  # noqa: ARG001
        return "activity_123"

    def fake_image_uploader(activity_id: str, image_path: Path, access_token: str) -> None:
        image_calls.append((activity_id, image_path, access_token))

    upload_fit_to_strava(
        fit_file,
        chart_image_path=chart_image,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=fake_upload,
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
        _image_uploader=fake_image_uploader,
    )

    assert len(image_calls) == 1
    assert image_calls[0][0] == "activity_123"
    assert image_calls[0][1] == chart_image
    assert image_calls[0][2] == "acc_tok"


def test_image_upload_failure_does_not_fail_fit_upload(tmp_path: Path) -> None:
    """An image upload exception does not surface as a FIT upload failure."""
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    chart_image = tmp_path / "chart.png"
    chart_image.write_bytes(b"PNG")

    def always_fails_image(_activity_id: str, _image_path: Path, _access_token: str) -> None:
        raise RuntimeError("image upload failed")

    # Must not raise
    upload_fit_to_strava(
        fit_file,
        chart_image_path=chart_image,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, _t: "activity_123",
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
        _image_uploader=always_fails_image,
    )


def test_image_upload_skipped_when_no_chart_image_path(tmp_path: Path) -> None:
    """Image upload is not attempted when chart_image_path is None."""
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    image_calls: list[object] = []

    upload_fit_to_strava(
        fit_file,
        chart_image_path=None,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, _t: "activity_123",
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
        _image_uploader=lambda _id, _p, _t: image_calls.append(None),
    )

    assert image_calls == []


def test_image_upload_skipped_when_fit_upload_returns_no_activity_id(tmp_path: Path) -> None:
    """Image upload is not attempted when the FIT upload returns no activity ID."""
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")
    tokens = _make_tokens()
    chart_image = tmp_path / "chart.png"
    chart_image.write_bytes(b"PNG")
    image_calls: list[object] = []

    upload_fit_to_strava(
        fit_file,
        chart_image_path=chart_image,
        _token_getter=lambda: tokens,
        _token_saver=lambda _: None,
        _upload_impl=lambda _p, _t: None,  # no activity id
        _history_checker=_NO_HISTORY,
        _history_recorder=_NO_RECORD,
        _image_uploader=lambda _id, _p, _t: image_calls.append(None),
    )

    assert image_calls == []
