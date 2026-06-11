from __future__ import annotations

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from opencycletrainer.integrations.intervalsicu.key_store import (
    clear_api_key,
    get_api_key,
    is_available,
    save_api_key,
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
    keyring.set_keyring(_FailKeyring())
    assert is_available() is True


def test_get_api_key_returns_none_when_no_key_stored():
    _use_memory_keyring()
    assert get_api_key() is None


def test_save_and_get_api_key_round_trips():
    _use_memory_keyring()
    save_api_key("abc123")
    assert get_api_key() == "abc123"


def test_clear_api_key_removes_stored_key():
    _use_memory_keyring()
    save_api_key("abc123")
    clear_api_key()
    assert get_api_key() is None


def test_clear_api_key_is_idempotent_when_no_key():
    _use_memory_keyring()
    clear_api_key()
    clear_api_key()


def test_save_api_key_overwrites_existing_key():
    _use_memory_keyring()
    save_api_key("old")
    save_api_key("new")
    assert get_api_key() == "new"


def test_save_and_get_api_key_uses_file_fallback_when_keyring_unavailable(tmp_path, monkeypatch):
    keyring.set_keyring(_FailKeyring())
    monkeypatch.setattr(
        "opencycletrainer.integrations.intervalsicu.key_store.get_data_dir",
        lambda: tmp_path,
    )
    save_api_key("fallback_key")
    assert get_api_key() == "fallback_key"


def test_file_fallback_returns_none_when_no_file(tmp_path, monkeypatch):
    keyring.set_keyring(_FailKeyring())
    monkeypatch.setattr(
        "opencycletrainer.integrations.intervalsicu.key_store.get_data_dir",
        lambda: tmp_path,
    )
    assert get_api_key() is None


def test_clear_api_key_removes_file_fallback(tmp_path, monkeypatch):
    keyring.set_keyring(_FailKeyring())
    monkeypatch.setattr(
        "opencycletrainer.integrations.intervalsicu.key_store.get_data_dir",
        lambda: tmp_path,
    )
    save_api_key("k")
    clear_api_key()
    assert get_api_key() is None


def test_save_api_key_with_keyring_removes_stale_fallback_file(tmp_path, monkeypatch):
    _use_memory_keyring()
    monkeypatch.setattr(
        "opencycletrainer.integrations.intervalsicu.key_store.get_data_dir",
        lambda: tmp_path,
    )
    stale = tmp_path / "intervals_icu_key.json"
    stale.write_text('{"api_key":"stale"}')

    save_api_key("fresh")

    assert not stale.exists()
