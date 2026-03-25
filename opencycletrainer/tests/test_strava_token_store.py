from __future__ import annotations

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from opencycletrainer.integrations.strava.token_store import (
    StravaTokenBundle,
    clear_tokens,
    get_tokens,
    is_available,
    save_tokens,
)


class _InMemoryKeyring(KeyringBackend):
    """In-memory keyring backend for tests."""

    priority = 1

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise PasswordDeleteError("not found")
        del self._store[(service, username)]


class _FailKeyring(KeyringBackend):
    """Keyring backend that always raises to simulate no usable backend."""

    priority = 0

    def get_password(self, service: str, username: str) -> None:
        raise RuntimeError("no keyring")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("no keyring")

    def delete_password(self, service: str, username: str) -> None:
        raise RuntimeError("no keyring")


def _use_memory_keyring() -> _InMemoryKeyring:
    backend = _InMemoryKeyring()
    keyring.set_keyring(backend)
    return backend


def test_is_available_returns_true_with_working_keyring():
    _use_memory_keyring()
    assert is_available() is True


def test_is_available_is_true_even_with_fail_keyring():
    """File-based fallback means token storage is always available."""
    keyring.set_keyring(_FailKeyring())
    assert is_available() is True


def test_get_tokens_returns_none_when_no_tokens_stored():
    _use_memory_keyring()
    assert get_tokens() is None


def test_save_and_get_tokens_round_trips():
    _use_memory_keyring()
    bundle = StravaTokenBundle(
        access_token="acc_abc",
        refresh_token="ref_xyz",
        expires_at=9999999999,
    )

    save_tokens(bundle)
    loaded = get_tokens()

    assert loaded is not None
    assert loaded.access_token == "acc_abc"
    assert loaded.refresh_token == "ref_xyz"
    assert loaded.expires_at == 9999999999


def test_clear_tokens_removes_stored_tokens():
    _use_memory_keyring()
    save_tokens(StravaTokenBundle(access_token="a", refresh_token="r", expires_at=1))

    clear_tokens()

    assert get_tokens() is None


def test_clear_tokens_is_idempotent_when_no_tokens():
    _use_memory_keyring()
    # Should not raise when there is nothing to clear.
    clear_tokens()
    clear_tokens()


def test_save_tokens_overwrites_existing_tokens():
    _use_memory_keyring()
    save_tokens(StravaTokenBundle(access_token="old", refresh_token="r", expires_at=1))
    save_tokens(StravaTokenBundle(access_token="new", refresh_token="r2", expires_at=2))

    loaded = get_tokens()
    assert loaded is not None
    assert loaded.access_token == "new"
    assert loaded.expires_at == 2


def test_save_and_get_tokens_uses_file_fallback_when_keyring_unavailable(tmp_path, monkeypatch):
    keyring.set_keyring(_FailKeyring())
    monkeypatch.setattr(
        "opencycletrainer.integrations.strava.token_store.get_data_dir",
        lambda: tmp_path,
    )
    bundle = StravaTokenBundle(access_token="acc", refresh_token="ref", expires_at=12345)

    save_tokens(bundle)
    loaded = get_tokens()

    assert loaded is not None
    assert loaded.access_token == "acc"
    assert loaded.refresh_token == "ref"
    assert loaded.expires_at == 12345


def test_file_fallback_returns_none_when_no_file(tmp_path, monkeypatch):
    keyring.set_keyring(_FailKeyring())
    monkeypatch.setattr(
        "opencycletrainer.integrations.strava.token_store.get_data_dir",
        lambda: tmp_path,
    )
    assert get_tokens() is None


def test_clear_tokens_removes_file_fallback(tmp_path, monkeypatch):
    keyring.set_keyring(_FailKeyring())
    monkeypatch.setattr(
        "opencycletrainer.integrations.strava.token_store.get_data_dir",
        lambda: tmp_path,
    )
    save_tokens(StravaTokenBundle(access_token="a", refresh_token="r", expires_at=1))

    clear_tokens()

    assert get_tokens() is None


def test_clear_tokens_removes_stale_file_when_keyring_is_active(tmp_path, monkeypatch):
    """Ensures clear_tokens cleans up any leftover fallback file even when keyring is active."""
    _use_memory_keyring()
    monkeypatch.setattr(
        "opencycletrainer.integrations.strava.token_store.get_data_dir",
        lambda: tmp_path,
    )
    stale = tmp_path / "strava_tokens.json"
    stale.write_text('{"access_token":"stale","refresh_token":"r","expires_at":1}')

    clear_tokens()

    assert not stale.exists()


def test_save_tokens_with_keyring_removes_stale_fallback_file(tmp_path, monkeypatch):
    """Saving via keyring should clean up any pre-existing fallback file."""
    _use_memory_keyring()
    monkeypatch.setattr(
        "opencycletrainer.integrations.strava.token_store.get_data_dir",
        lambda: tmp_path,
    )
    stale = tmp_path / "strava_tokens.json"
    stale.write_text('{"access_token":"stale","refresh_token":"r","expires_at":1}')

    save_tokens(StravaTokenBundle(access_token="new", refresh_token="r2", expires_at=2))

    assert not stale.exists()
