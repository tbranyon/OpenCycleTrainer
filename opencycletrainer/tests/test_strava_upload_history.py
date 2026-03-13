from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.integrations.strava.upload_history import (
    is_already_uploaded,
    record_upload,
)


def _make_fit(tmp_path: Path, name: str = "ride.fit", content: bytes = b"FIT") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_is_not_uploaded_when_history_missing(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    fit_file = _make_fit(tmp_path)
    assert not is_already_uploaded(fit_file, history_path=history_path)


def test_record_then_check_returns_true(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    fit_file = _make_fit(tmp_path)
    record_upload(fit_file, history_path=history_path)
    assert is_already_uploaded(fit_file, history_path=history_path)


def test_different_file_not_marked_as_uploaded(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    fit_a = _make_fit(tmp_path, "a.fit", b"FIT_A")
    fit_b = _make_fit(tmp_path, "b.fit", b"FIT_B")
    record_upload(fit_a, history_path=history_path)
    assert not is_already_uploaded(fit_b, history_path=history_path)


def test_record_is_idempotent(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    fit_file = _make_fit(tmp_path)
    record_upload(fit_file, history_path=history_path)
    record_upload(fit_file, history_path=history_path)
    # Load raw JSON and confirm no duplicates
    import json
    data = json.loads(history_path.read_text())
    assert len(data["uploads"]) == 1


def test_same_name_different_size_not_deduplicated(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    sub_a = tmp_path / "sub_a"
    sub_b = tmp_path / "sub_b"
    sub_a.mkdir()
    sub_b.mkdir()
    fit_small = sub_a / "ride.fit"
    fit_small.write_bytes(b"small")
    fit_large = sub_b / "ride.fit"
    fit_large.write_bytes(b"larger content")

    record_upload(fit_small, history_path=history_path)
    assert not is_already_uploaded(fit_large, history_path=history_path)


def test_multiple_files_tracked_independently(tmp_path: Path) -> None:
    history_path = tmp_path / "history.json"
    fit_a = _make_fit(tmp_path, "a.fit", b"A")
    fit_b = _make_fit(tmp_path, "b.fit", b"BB")
    fit_c = _make_fit(tmp_path, "c.fit", b"CCC")

    record_upload(fit_a, history_path=history_path)
    record_upload(fit_b, history_path=history_path)

    assert is_already_uploaded(fit_a, history_path=history_path)
    assert is_already_uploaded(fit_b, history_path=history_path)
    assert not is_already_uploaded(fit_c, history_path=history_path)
