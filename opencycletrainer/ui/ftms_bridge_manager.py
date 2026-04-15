from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import logging

from opencycletrainer.core.control.ftms_control import (
    ControlMode,
    FTMSControl,
    FTMSControlTransport,
    WorkoutEngineFTMSBridge,
)
from opencycletrainer.core.workout_engine import WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout

_logger = logging.getLogger(__name__)


class FTMSBridgeManager:
    """Owns the WorkoutEngineFTMSBridge and its single-threaded executor."""

    def __init__(
        self,
        transport_factory: Callable[[object, str], FTMSControlTransport | None],
        screen: object,
        alert_signal: Callable[[str], None],
        opentrueup_state: object,
        mode_state: object,
        settings: object,
        engine: object,
    ) -> None:
        self._transport_factory = transport_factory
        self._screen = screen
        self._alert_signal = alert_signal
        self._opentrueup_state = opentrueup_state
        self._mode_state = mode_state
        self._settings = settings
        self._engine = engine

        self._ftms_bridge: WorkoutEngineFTMSBridge | None = None
        self._ftms_bridge_executor: ThreadPoolExecutor | None = None

    @property
    def active(self) -> bool:
        """True when a bridge and executor are running."""
        return self._ftms_bridge is not None

    def configure(
        self,
        backend: object,
        device_id: str | None,
        workout: Workout | None = None,
        initial_snapshot: WorkoutEngineSnapshot | None = None,
    ) -> None:
        """Tear down any existing bridge and configure a new one for the given trainer."""
        self.teardown()
        if device_id is None or backend is None:
            self._screen.set_trainer_controls_visible(False)
            return

        transport = self._create_transport(backend, device_id)
        if transport is None:
            self._screen.set_trainer_controls_visible(False)
            return

        resistance_range = transport.read_resistance_level_range()
        if resistance_range is not None:
            step_count = resistance_range.step_count
            self._mode_state.set_trainer_resistance_step_count(step_count if step_count > 0 else None)
        else:
            self._mode_state.set_trainer_resistance_step_count(None)

        snapshot = initial_snapshot if initial_snapshot is not None else self._engine.snapshot()
        initial_mode = (
            ControlMode.RESISTANCE
            if self._mode_state.active_control_mode(snapshot, workout) == "Resistance"
            else ControlMode.ERG
        )

        try:
            control = FTMSControl(transport)
        except Exception as exc:
            _logger.error("Failed to initialise FTMSControl: %s", exc)
            self._alert_signal("Could not connect to trainer")
            self._screen.set_trainer_controls_visible(False)
            return

        self._ftms_bridge = WorkoutEngineFTMSBridge(
            control,
            mode=initial_mode,
            alert_callback=self._alert_signal,
            opentrueup=self._opentrueup_state.controller,
            opentrueup_status_callback=self._opentrueup_state.handle_bridge_status,
            lead_time_seconds=max(0, int(self._settings.lead_time)),
            kj_mode=self._engine.kj_mode,
        )
        self._ftms_bridge_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ftms-bridge",
        )
        self.submit_snapshot(snapshot, workout)
        self._screen.set_trainer_controls_visible(True)

    def teardown(self) -> None:
        """Shut down the bridge and executor; clear resistance step count."""
        executor = self._ftms_bridge_executor
        self._ftms_bridge_executor = None
        self._ftms_bridge = None
        self._mode_state.set_trainer_resistance_step_count(None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def submit_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> None:
        """Submit a snapshot to the bridge to update trainer targets."""
        self.submit_action(
            lambda bridge: self._apply_snapshot(bridge, snapshot, workout)
        )

    def submit_power_sample(
        self,
        timestamp: float,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> None:
        """Submit a power sample to the bridge for OpenTrueUp processing."""
        self.submit_action(
            lambda bridge: bridge.on_power_sample(
                timestamp=timestamp,
                trainer_power_watts=trainer_watts,
                bike_power_watts=bike_watts,
            )
        )

    def submit_action(
        self,
        action: Callable[[WorkoutEngineFTMSBridge], None],
    ) -> None:
        """Enqueue an action on the bridge executor; no-op if inactive."""
        bridge = self._ftms_bridge
        executor = self._ftms_bridge_executor
        if bridge is None or executor is None:
            return

        def _run() -> None:
            current_bridge = self._ftms_bridge
            if current_bridge is not bridge:
                return
            action(current_bridge)

        executor.submit(_run)

    def _apply_snapshot(
        self,
        bridge: WorkoutEngineFTMSBridge,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> None:
        active_mode = self._mode_state.active_control_mode(snapshot, workout)
        if active_mode == "Resistance":
            bridge.set_mode_resistance()
        else:
            bridge.set_mode_erg()
        bridge.on_engine_snapshot(snapshot, workout)

    def _create_transport(
        self,
        backend: object,
        device_id: str,
    ) -> FTMSControlTransport | None:
        try:
            return self._transport_factory(backend, device_id)
        except Exception as exc:
            _logger.error("Failed to create FTMS transport: %s", exc)
            self._alert_signal("Could not connect to trainer")
            return None
