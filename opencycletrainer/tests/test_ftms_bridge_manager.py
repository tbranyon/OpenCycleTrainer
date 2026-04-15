from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

from opencycletrainer.ui.ftms_bridge_manager import FTMSBridgeManager


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeTransport:
    def __init__(self, resistance_range=None) -> None:
        self.writes: list[bytes] = []
        self._handler = lambda _: None
        self._resistance_range = resistance_range

    def write_control_point(self, payload: bytes) -> Future[None]:
        self.writes.append(payload)
        future: Future[None] = Future()
        future.set_result(None)
        self._handler(bytes([0x80, payload[0], 0x01]))
        return future

    def set_indication_handler(self, handler) -> None:
        self._handler = handler

    def read_resistance_level_range(self):
        return self._resistance_range


class _FakeScreen:
    def __init__(self) -> None:
        self.trainer_controls_visible: bool | None = None

    def set_trainer_controls_visible(self, visible: bool) -> None:
        self.trainer_controls_visible = visible


class _FakeModeState:
    def __init__(self, mode: str = "ERG") -> None:
        self._mode = mode
        self.resistance_step_count: int | None = None

    def active_control_mode(self, snapshot, workout) -> str:
        return self._mode

    def set_trainer_resistance_step_count(self, count: int | None) -> None:
        self.resistance_step_count = count


class _FakeEngine:
    def __init__(self) -> None:
        self.kj_mode = False

    def snapshot(self):
        from opencycletrainer.core.workout_engine import WorkoutEngine
        return WorkoutEngine().snapshot()


class _FakeOpenTrueUpState:
    def __init__(self) -> None:
        self.controller = None
        self.bridge_statuses: list[object] = []

    def handle_bridge_status(self, status: object) -> None:
        self.bridge_statuses.append(status)


class _FakeSettings:
    lead_time: float = 0.0


def _make_manager(
    transport_factory=None,
    mode: str = "ERG",
    resistance_range=None,
) -> tuple[FTMSBridgeManager, _FakeScreen, _FakeModeState, _FakeTransport]:
    transport = _FakeTransport(resistance_range=resistance_range)
    screen = _FakeScreen()
    mode_state = _FakeModeState(mode=mode)
    opentrueup_state = _FakeOpenTrueUpState()
    engine = _FakeEngine()
    settings = _FakeSettings()
    alerts: list[str] = []

    if transport_factory is None:
        transport_factory = lambda backend, device_id: transport  # noqa: E731

    manager = FTMSBridgeManager(
        transport_factory=transport_factory,
        screen=screen,
        alert_signal=alerts.append,
        opentrueup_state=opentrueup_state,
        mode_state=mode_state,
        settings=settings,
        engine=engine,
    )
    return manager, screen, mode_state, transport


def _configured_manager(**kwargs) -> tuple[FTMSBridgeManager, _FakeScreen, _FakeModeState, _FakeTransport]:
    manager, screen, mode_state, transport = _make_manager(**kwargs)
    manager.configure("bleak", "trainer-1")
    return manager, screen, mode_state, transport


# ── Tests: active property ─────────────────────────────────────────────────────


def test_inactive_initially():
    manager, _, _, _ = _make_manager()
    assert not manager.active


def test_active_after_configure_with_valid_transport():
    manager, _, _, _ = _configured_manager()
    assert manager.active


def test_inactive_after_teardown():
    manager, _, _, _ = _configured_manager()
    manager.teardown()
    assert not manager.active


# ── Tests: configure ───────────────────────────────────────────────────────────


def test_configure_with_none_device_id_stays_inactive():
    manager, screen, _, _ = _make_manager()
    manager.configure("bleak", None)
    assert not manager.active
    assert screen.trainer_controls_visible is False


def test_configure_with_none_backend_stays_inactive():
    manager, screen, _, _ = _make_manager()
    manager.configure(None, "trainer-1")
    assert not manager.active
    assert screen.trainer_controls_visible is False


def test_configure_when_transport_factory_returns_none_stays_inactive():
    manager, screen, _, _ = _make_manager(transport_factory=lambda b, d: None)
    manager.configure("bleak", "trainer-1")
    assert not manager.active
    assert screen.trainer_controls_visible is False


def test_configure_shows_trainer_controls_when_valid_transport():
    manager, screen, _, _ = _configured_manager()
    assert screen.trainer_controls_visible is True


def test_configure_hides_trainer_controls_when_no_device():
    manager, screen, _, _ = _make_manager()
    manager.configure("bleak", None)
    assert screen.trainer_controls_visible is False


def test_configure_resets_previous_bridge_before_creating_new():
    """Calling configure twice cleanly tears down the first bridge."""
    manager, _, _, _ = _configured_manager()
    assert manager.active
    manager.configure("bleak", "trainer-2")
    assert manager.active  # second bridge is up


def test_configure_sets_resistance_step_count_when_range_available():
    resistance_range = SimpleNamespace(step_count=10)
    manager, _, mode_state, _ = _configured_manager(resistance_range=resistance_range)
    assert mode_state.resistance_step_count == 10


def test_configure_clears_resistance_step_count_when_no_range():
    manager, _, mode_state, _ = _configured_manager()
    assert mode_state.resistance_step_count is None


def test_configure_ignores_zero_step_count():
    resistance_range = SimpleNamespace(step_count=0)
    manager, _, mode_state, _ = _configured_manager(resistance_range=resistance_range)
    assert mode_state.resistance_step_count is None


# ── Tests: teardown ────────────────────────────────────────────────────────────


def test_teardown_hides_trainer_controls_via_mode_state():
    """teardown resets resistance step count to None."""
    manager, _, mode_state, _ = _configured_manager(
        resistance_range=SimpleNamespace(step_count=5)
    )
    assert mode_state.resistance_step_count == 5
    manager.teardown()
    assert mode_state.resistance_step_count is None


def test_teardown_when_already_inactive_is_safe():
    manager, _, _, _ = _make_manager()
    manager.teardown()  # must not raise


# ── Tests: submit_action ───────────────────────────────────────────────────────


def test_submit_action_noop_when_inactive():
    manager, _, _, _ = _make_manager()
    called = []
    manager.submit_action(lambda bridge: called.append(True))
    time.sleep(0.05)
    assert not called


def test_submit_action_dispatches_when_active():
    manager, _, _, _ = _configured_manager()
    called = []

    def action(bridge):
        called.append(True)

    manager.submit_action(action)
    manager._ftms_bridge_executor.shutdown(wait=True)
    assert called


def test_submit_action_race_guard_skips_stale_action():
    """If _ftms_bridge is replaced between submission and execution, action is skipped."""
    manager, _, _, _ = _configured_manager()

    block = threading.Event()
    worker_started = threading.Event()

    # Occupy the single worker thread
    manager.submit_action(lambda b: (worker_started.set() or block.wait()))
    worker_started.wait(timeout=2.0)

    # Queue a second action while the worker is busy
    called = []
    manager.submit_action(lambda b: called.append(True))

    # Simulate bridge replacement (as teardown does) without shutting down executor
    manager._ftms_bridge = None

    # Release the blocking first action and drain
    block.set()
    manager._ftms_bridge_executor.shutdown(wait=True)
    manager._ftms_bridge_executor = None

    assert not called


# ── Tests: submit_snapshot ─────────────────────────────────────────────────────


def test_submit_snapshot_applies_erg_mode():
    manager, _, _, _ = _configured_manager(mode="ERG")
    from opencycletrainer.core.workout_engine import WorkoutEngine
    snapshot = WorkoutEngine().snapshot()

    erg_calls = []
    manager._ftms_bridge.set_mode_erg = lambda: erg_calls.append(True)

    manager.submit_snapshot(snapshot, None)
    manager._ftms_bridge_executor.shutdown(wait=True)
    assert erg_calls


def test_submit_snapshot_applies_resistance_mode():
    manager, _, _, _ = _configured_manager(mode="Resistance")
    from opencycletrainer.core.workout_engine import WorkoutEngine
    snapshot = WorkoutEngine().snapshot()

    resistance_calls = []
    manager._ftms_bridge.set_mode_resistance = lambda: resistance_calls.append(True)

    manager.submit_snapshot(snapshot, None)
    manager._ftms_bridge_executor.shutdown(wait=True)
    assert resistance_calls


# ── Tests: submit_power_sample ─────────────────────────────────────────────────


def test_submit_power_sample_calls_on_power_sample():
    manager, _, _, _ = _configured_manager()
    samples: list[dict] = []

    def fake_on_power_sample(*, timestamp, trainer_power_watts, bike_power_watts):
        samples.append({
            "timestamp": timestamp,
            "trainer": trainer_power_watts,
            "bike": bike_power_watts,
        })

    manager._ftms_bridge.on_power_sample = fake_on_power_sample

    manager.submit_power_sample(timestamp=1.0, trainer_watts=200, bike_watts=None)
    manager._ftms_bridge_executor.shutdown(wait=True)

    assert len(samples) == 1
    assert samples[0] == {"timestamp": 1.0, "trainer": 200, "bike": None}


def test_submit_power_sample_noop_when_inactive():
    manager, _, _, _ = _make_manager()
    # Should not raise
    manager.submit_power_sample(timestamp=1.0, trainer_watts=200, bike_watts=None)
