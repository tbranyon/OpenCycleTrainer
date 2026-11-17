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
    def __init__(
        self,
        mode: str = "ERG",
        resistance_percent: float = 33.0,
        grade_percent: float = 0.0,
    ) -> None:
        self._mode = mode
        self._resistance_percent = resistance_percent
        self.grade_percent = grade_percent
        self.resistance_step_count: int | None = None

    def simulation_grade_percent(self) -> float:
        return self.grade_percent

    def active_control_mode(self, snapshot, workout) -> str:
        return self._mode

    def resistance_target_percent(self) -> float:
        return self._resistance_percent

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
    lead_time_increasing_only: bool = False


def _make_manager(
    transport_factory=None,
    mode: str = "ERG",
    resistance_range=None,
    resistance_percent: float = 33.0,
    grade_percent: float = 0.0,
) -> tuple[FTMSBridgeManager, _FakeScreen, _FakeModeState, _FakeTransport]:
    transport = _FakeTransport(resistance_range=resistance_range)
    screen = _FakeScreen()
    mode_state = _FakeModeState(
        mode=mode, resistance_percent=resistance_percent, grade_percent=grade_percent
    )
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


def test_workout_resistance_mode_uses_manual_level_not_interval_ftp_percent():
    """Resistance mode in a workout must send the user's manual resistance, not the interval's FTP%."""
    from opencycletrainer.core.workout_engine import WorkoutEngine, EngineState
    from opencycletrainer.core.workout_model import Workout, WorkoutInterval

    # Interval at 100% FTP — in ERG mode this is the power target, but in
    # resistance mode the user's 45% setting must be sent, not 100%.
    interval = WorkoutInterval(
        start_offset_seconds=0,
        duration_seconds=60,
        start_target_watts=300,
        end_target_watts=300,
        start_percent_ftp=100.0,
        end_percent_ftp=100.0,
    )
    workout = Workout(name="Test", ftp_watts=300, intervals=[interval])

    manager, _, _, transport = _configured_manager(mode="Resistance", resistance_percent=45.0)

    engine = WorkoutEngine()
    engine.load_workout(workout)
    engine.start()
    snapshot = engine.snapshot()
    assert snapshot.state == EngineState.RUNNING

    manager.submit_snapshot(snapshot, workout)
    manager._ftms_bridge_executor.shutdown(wait=True)

    # FTMS opcode 0x04 = SET_TARGET_RESISTANCE; the value at byte index 1 is the
    # resistance level (0–100 mapped via _normalize_resistance with no range → raw int).
    resistance_writes = [w for w in transport.writes if w[0] == 0x04]
    assert resistance_writes, "No SET_TARGET_RESISTANCE command sent"
    sent_level = resistance_writes[-1][1]
    assert sent_level == 45, (
        f"Expected manual resistance 45%, got {sent_level}% "
        f"(interval FTP% is 100%, which would be wrong)"
    )


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


# ── Tests: apply_settings (live update, no rebuild) ────────────────────────────

_SET_TARGET_POWER_OPCODE = 0x05


def _two_interval_workout():
    from opencycletrainer.core.workout_model import Workout, WorkoutInterval

    intervals = (
        WorkoutInterval(
            start_offset_seconds=0, duration_seconds=10,
            start_percent_ftp=50.0, end_percent_ftp=50.0,
            start_target_watts=150, end_target_watts=150,
        ),
        WorkoutInterval(
            start_offset_seconds=10, duration_seconds=20,
            start_percent_ftp=75.0, end_percent_ftp=75.0,
            start_target_watts=225, end_target_watts=225,
        ),
    )
    return Workout(name="Lead Time", ftp_watts=300, intervals=intervals)


def _erg_targets_sent_reaching_lead_time_window(manager: FTMSBridgeManager, transport) -> list[int]:
    """Ride to 3 s before the 150 W -> 225 W change and return every ERG target written."""
    from opencycletrainer.core.workout_engine import WorkoutEngine

    workout = _two_interval_workout()
    engine = WorkoutEngine()
    engine.load_workout(workout)
    engine.start()
    for elapsed in (0, 7):
        engine.tick(elapsed)
        manager.submit_snapshot(engine.snapshot(), workout)
    manager._ftms_bridge_executor.shutdown(wait=True)
    return [
        int.from_bytes(w[1:3], "little", signed=True)
        for w in transport.writes
        if w[0] == _SET_TARGET_POWER_OPCODE
    ]


def _counting_factory(resistance_range=None):
    """Transport factory that builds a fresh transport per call and records each one."""
    created: list[_FakeTransport] = []

    def factory(backend, device_id):
        transport = _FakeTransport(resistance_range=resistance_range)
        transport.read_count = 0
        original_read = transport.read_resistance_level_range

        def counted_read():
            transport.read_count += 1
            return original_read()

        transport.read_resistance_level_range = counted_read
        created.append(transport)
        return transport

    return factory, created


def test_apply_settings_keeps_the_live_bridge_and_transport():
    factory, created = _counting_factory()
    manager, *_ = _make_manager(transport_factory=factory)
    manager.configure("bleak", "trainer-1")

    manager.apply_settings(SimpleNamespace(lead_time=5, lead_time_increasing_only=False,
                                           erg_jog_persistence_mode="always"))

    assert manager.active
    assert len(created) == 1


def test_apply_settings_pushes_lead_time_to_live_bridge():
    factory, created = _counting_factory()
    manager, *_ = _make_manager(transport_factory=factory)
    manager.configure("bleak", "trainer-1")

    manager.apply_settings(SimpleNamespace(lead_time=3, lead_time_increasing_only=False,
                                           erg_jog_persistence_mode="always"))

    assert _erg_targets_sent_reaching_lead_time_window(manager, created[-1]) == [150, 225]


def test_apply_settings_before_configure_is_used_by_next_bridge():
    factory, created = _counting_factory()
    manager, *_ = _make_manager(transport_factory=factory)

    manager.apply_settings(SimpleNamespace(lead_time=3, lead_time_increasing_only=False,
                                           erg_jog_persistence_mode="always"))
    manager.configure("bleak", "trainer-1")

    assert _erg_targets_sent_reaching_lead_time_window(manager, created[-1]) == [150, 225]


def test_set_opentrueup_routes_power_samples_to_new_controller():
    manager, *_ = _configured_manager()
    received: list[dict] = []

    class _Controller:
        def record_power_sample(self, **kwargs):
            received.append(kwargs)
            return SimpleNamespace(requires_erg_reapply=False, last_computed_offset_watts=None)

    manager.set_opentrueup(_Controller())
    manager.submit_power_sample(timestamp=1.0, trainer_watts=200, bike_watts=210)
    manager._ftms_bridge_executor.shutdown(wait=True)

    assert received == [{"timestamp": 1.0, "trainer_power_watts": 200, "bike_power_watts": 210}]


# ── Tests: resistance range cache ──────────────────────────────────────────────


def test_resistance_range_is_read_once_per_trainer_across_reconfigures():
    factory, created = _counting_factory(resistance_range=SimpleNamespace(step_count=10))
    manager, _, mode_state, _ = _make_manager(transport_factory=factory)

    manager.configure("bleak", "trainer-1")
    manager.configure("bleak", "trainer-1")

    assert sum(t.read_count for t in created) == 1
    assert mode_state.resistance_step_count == 10


def test_resistance_range_is_read_again_for_a_different_trainer():
    factory, created = _counting_factory(resistance_range=SimpleNamespace(step_count=10))
    manager, *_ = _make_manager(transport_factory=factory)

    manager.configure("bleak", "trainer-1")
    manager.configure("bleak", "trainer-2")

    assert sum(t.read_count for t in created) == 2


def test_failed_resistance_range_read_is_retried_on_next_configure():
    factory, created = _counting_factory(resistance_range=None)
    manager, *_ = _make_manager(transport_factory=factory)

    manager.configure("bleak", "trainer-1")
    manager.configure("bleak", "trainer-1")

    assert sum(t.read_count for t in created) == 2


# ── Tests: simulation mode ─────────────────────────────────────────────────────

_SIMULATION_OPCODE = 0x11


def _simulation_grades(transport: _FakeTransport) -> list[float]:
    """Return the grades (%) of every simulation command written to *transport*."""
    import struct

    return [
        struct.unpack("<BhhBB", write)[2] / 100.0
        for write in transport.writes
        if write[0] == _SIMULATION_OPCODE
    ]


def _running_snapshot_and_workout():
    from opencycletrainer.core.workout_engine import WorkoutEngine
    from opencycletrainer.core.workout_model import Workout, WorkoutInterval

    interval = WorkoutInterval(
        start_offset_seconds=0,
        duration_seconds=600,
        start_target_watts=200,
        end_target_watts=200,
        start_percent_ftp=80.0,
        end_percent_ftp=80.0,
    )
    workout = Workout(name="Sim", ftp_watts=250, intervals=(interval,))
    engine = WorkoutEngine()
    engine.load_workout(workout)
    engine.start()
    return engine, engine.tick(0.0), workout


def test_simulation_mode_sends_the_grade_while_riding():
    manager, _, _, transport = _configured_manager(mode="Simulation", grade_percent=4.5)
    _, snapshot, workout = _running_snapshot_and_workout()

    manager.submit_snapshot(snapshot, workout)
    manager._ftms_bridge_executor.shutdown(wait=True)

    assert _simulation_grades(transport)[-1] == 4.5
    assert not [w for w in transport.writes if w[0] in (0x04, 0x05)]


def test_simulation_mode_follows_grade_changes():
    manager, _, mode_state, transport = _configured_manager(mode="Simulation", grade_percent=2.0)
    _, snapshot, workout = _running_snapshot_and_workout()

    manager.submit_snapshot(snapshot, workout)
    mode_state.grade_percent = -3.0
    manager.submit_snapshot(snapshot, workout)
    manager.submit_snapshot(snapshot, workout)
    manager._ftms_bridge_executor.shutdown(wait=True)

    assert _simulation_grades(transport)[-2:] == [2.0, -3.0]


def test_simulation_mode_flattens_the_road_when_paused():
    manager, _, _, transport = _configured_manager(mode="Simulation", grade_percent=6.0)
    engine, snapshot, workout = _running_snapshot_and_workout()

    manager.submit_snapshot(snapshot, workout)
    manager.submit_snapshot(engine.pause(), workout)
    manager._ftms_bridge_executor.shutdown(wait=True)

    assert _simulation_grades(transport)[-2:] == [6.0, 0.0]


def test_simulation_mode_applies_in_free_ride():
    manager, _, mode_state, transport = _configured_manager(mode="Simulation", grade_percent=3.0)
    mode_state.is_free_ride = True
    _, snapshot, workout = _running_snapshot_and_workout()

    manager.submit_snapshot(snapshot, workout)
    manager._ftms_bridge_executor.shutdown(wait=True)

    assert _simulation_grades(transport)[-1] == 3.0
    assert not [w for w in transport.writes if w[0] in (0x04, 0x05)]


def test_configure_starts_the_bridge_in_simulation_mode_when_selected():
    from opencycletrainer.core.control.ftms_control import ControlMode

    manager, _, _, _ = _configured_manager(mode="Simulation")

    assert manager._ftms_bridge.mode is ControlMode.SIMULATION
