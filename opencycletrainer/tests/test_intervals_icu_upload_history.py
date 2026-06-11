from __future__ import annotations

from pathlib import Path

from opencycletrainer.integrations.intervalsicu.upload_history import (
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
    import json

    history_path = tmp_path / "history.json"
    fit_file = _make_fit(tmp_path)
    record_upload(fit_file, history_path=history_path)
    record_upload(fit_file, history_path=history_path)
    data = json.loads(history_path.read_text())
    assert len(data["uploads"]) == 1
