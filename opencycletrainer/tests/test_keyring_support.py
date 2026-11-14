"""Keyring access is kept to the minimum: one lookup per stored secret at startup."""

from __future__ import annotations

import os

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from opencycletrainer.integrations.intervalsicu import key_store
from opencycletrainer.integrations.strava import token_store
from opencycletrainer.integrations.strava.token_store import StravaTokenBundle

_PROBE_USERNAME = "__probe__"


class _CountingKeyring(KeyringBackend):
    """In-memory backend that records every lookup (slow D-Bus calls on Linux)."""

    priority = 1

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.lookups: list[tuple[str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.lookups.append((service, username))
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


class _FailKeyring(KeyringBackend):
    priority = 0

    def get_password(self, service: str, username: str) -> None:
        raise RuntimeError("no keyring")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("no keyring")

    def delete_password(self, service: str, username: str) -> None:
        raise RuntimeError("no keyring")


def _counting_keyring(monkeypatch, tmp_path) -> _CountingKeyring:
    backend = _CountingKeyring()
    keyring.set_keyring(backend)
    monkeypatch.setattr(token_store, "_fallback_path", lambda: tmp_path / "strava_tokens.json")
    monkeypatch.setattr(key_store, "_fallback_path", lambda: tmp_path / "intervals_icu_key.json")
    return backend


def test_reading_stored_secrets_does_not_probe_the_keyring_first(monkeypatch, tmp_path):
    backend = _counting_keyring(monkeypatch, tmp_path)

    token_store.get_tokens()
    key_store.get_api_key()

    assert [username for _, username in backend.lookups] == ["default", "default"]


def test_keyring_is_probed_once_for_repeated_saves(monkeypatch, tmp_path):
    backend = _counting_keyring(monkeypatch, tmp_path)

    token_store.save_tokens(StravaTokenBundle("a", "r", 1))
    token_store.save_tokens(StravaTokenBundle("b", "r", 2))
    key_store.save_api_key("k1")
    token_store.clear_tokens()

    probes = [entry for entry in backend.lookups if entry[1] == _PROBE_USERNAME]
    assert len(probes) <= 1
    assert key_store.get_api_key() == "k1"


def test_changing_the_keyring_backend_probes_again(monkeypatch, tmp_path):
    _counting_keyring(monkeypatch, tmp_path)
    token_store.save_tokens(StravaTokenBundle("a", "r", 1))

    keyring.set_keyring(_FailKeyring())
    token_store.save_tokens(StravaTokenBundle("b", "r", 2))

    assert (tmp_path / "strava_tokens.json").exists()
    assert token_store.get_tokens() == StravaTokenBundle("b", "r", 2)


def test_main_window_reads_each_secret_once_at_startup(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from opencycletrainer.devices.mock_backend import MockDeviceBackend
    from opencycletrainer.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    backend = _counting_keyring(monkeypatch, tmp_path)
    backend.store[("OpenCycleTrainer/IntervalsICU", "default")] = "saved-key"

    window = MainWindow(backend=MockDeviceBackend())
    try:
        assert sorted(backend.lookups) == [
            ("OpenCycleTrainer/IntervalsICU", "default"),
            ("OpenCycleTrainer/Strava", "default"),
        ]
        assert window.settings_screen.intervals_icu_api_key_edit.text() == "saved-key"
    finally:
        window.close()
