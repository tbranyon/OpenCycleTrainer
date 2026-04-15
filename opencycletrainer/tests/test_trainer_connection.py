"""Unit tests for TrainerConnection."""
from __future__ import annotations

import pytest

from opencycletrainer.ui.trainer_connection import TrainerConnection


class _FakeScreen:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []

    def show_alert(self, message: str, kind: str = "info") -> None:
        self.alerts.append((message, kind))


def _make(is_active: bool = False) -> tuple[TrainerConnection, _FakeScreen]:
    screen = _FakeScreen()
    conn = TrainerConnection(
        screen=screen,
        is_workout_active=lambda: is_active,
    )
    return conn, screen


# ── Initial state ─────────────────────────────────────────────────────────────

def test_initial_properties_are_none():
    conn, _ = _make()
    assert conn.backend is None
    assert conn.device_id is None
    assert conn.last_known_id is None


# ── Property updates ──────────────────────────────────────────────────────────

def test_set_target_updates_backend_and_device_id():
    conn, _ = _make()
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    assert conn.backend == "bleak"
    assert conn.device_id == "trainer-1"


def test_set_target_with_none_device_id():
    conn, _ = _make()
    conn.set_target(backend="bleak", trainer_device_id=None)
    assert conn.backend == "bleak"
    assert conn.device_id is None


def test_last_known_id_updated_when_device_id_set():
    conn, _ = _make()
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    assert conn.last_known_id == "trainer-1"


def test_last_known_id_not_cleared_on_disconnect():
    """last_known_id retains the previous ID when the trainer disconnects."""
    conn, _ = _make()
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    conn.set_target(backend="bleak", trainer_device_id=None)
    assert conn.last_known_id == "trainer-1"


# ── Alert logic — workout not active ─────────────────────────────────────────

def test_no_alert_when_workout_not_active_on_disconnect():
    conn, screen = _make(is_active=False)
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    conn.set_target(backend="bleak", trainer_device_id=None)
    assert screen.alerts == []


def test_no_alert_when_workout_not_active_on_reconnect():
    conn, screen = _make(is_active=False)
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    conn.set_target(backend="bleak", trainer_device_id=None)
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    assert screen.alerts == []


# ── Alert logic — workout active ─────────────────────────────────────────────

def test_disconnect_during_active_workout_shows_reconnecting_alert():
    conn, screen = _make(is_active=True)
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    conn.set_target(backend="bleak", trainer_device_id=None)
    assert len(screen.alerts) == 1
    message, kind = screen.alerts[0]
    assert "Reconnecting" in message
    assert kind == "info"


def test_reconnect_during_active_workout_shows_reconnected_alert():
    conn, screen = _make(is_active=True)
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    conn.set_target(backend="bleak", trainer_device_id=None)
    screen.alerts.clear()
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    assert len(screen.alerts) == 1
    message, kind = screen.alerts[0]
    assert "reconnected" in message.lower()
    assert kind == "success"


def test_no_reconnect_alert_on_first_connection():
    """No reconnect alert when last_known_id is None (never connected before)."""
    conn, screen = _make(is_active=True)
    # First connect — last_known_id starts as None
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    # No alert should fire (this is not a reconnect)
    assert screen.alerts == []


def test_first_connect_sets_last_known_id():
    conn, _ = _make(is_active=True)
    conn.set_target(backend="bleak", trainer_device_id="trainer-1")
    assert conn.last_known_id == "trainer-1"
