from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import logging

from opencycletrainer.core.bike_physics import rolling_resistance_for_surface
from opencycletrainer.core.control.ftms_control import (
    ControlMode,
    FTMSControl,
    FTMSControlTransport,
    WorkoutEngineFTMSBridge,
)
from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.core.workout_engine import WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout
from opencycletrainer.devices.decoders.ftms import ResistanceLevelRange
from opencycletrainer.storage.settings import (
    DEFAULT_JOG_PERSISTENCE_MODE,
    DEFAULT_ROAD_SURFACE,
    JogPersistenceMode,
)

from .mode_state import MODE_SIMULATION

_logger = logging.getLogger(__name__)

_CONTROL_MODE_BY_NAME = {
    "ERG": ControlMode.ERG,
    "Resistance": ControlMode.RESISTANCE,
    MODE_SIMULATION: ControlMode.SIMULATION,
}


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
        self._erg_jog_persistence_mode = getattr(
            settings, "erg_jog_persistence_mode", DEFAULT_JOG_PERSISTENCE_MODE
        )

        self._ftms_bridge: WorkoutEngineFTMSBridge | None = None
        self._ftms_bridge_executor: ThreadPoolExecutor | None = None
        self._resistance_ranges: dict[str, ResistanceLevelRange] = {}

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

        resistance_range = self._resistance_range_for(device_id, transport)
        if resistance_range is not None:
            step_count = resistance_range.step_count
            self._mode_state.set_trainer_resistance_step_count(step_count if step_count > 0 else None)
        else:
            self._mode_state.set_trainer_resistance_step_count(None)

        snapshot = initial_snapshot if initial_snapshot is not None else self._engine.snapshot()
        initial_mode = _CONTROL_MODE_BY_NAME.get(
            self._mode_state.active_control_mode(snapshot, workout), ControlMode.ERG
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
            lead_time_increasing_only=self._settings.lead_time_increasing_only,
            kj_mode=self._engine.kj_mode,
            erg_jog_persistence_mode=self._erg_jog_persistence_mode,
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

    def apply_settings(self, settings: object) -> None:
        """Use *settings* for future bridges and push the bridge-relevant values to the live one.

        The live bridge is updated in place rather than rebuilt, so a settings change never
        re-subscribes to the trainer or blocks on BLE reads.
        """
        self._settings = settings
        lead_time_seconds = max(0, int(settings.lead_time))
        increasing_only = settings.lead_time_increasing_only
        kj_mode = self._engine.kj_mode
        self.submit_action(
            lambda bridge: bridge.set_lead_time(lead_time_seconds, increasing_only=increasing_only)
        )
        self.submit_action(lambda bridge: bridge.set_kj_mode(kj_mode))
        self.set_erg_jog_persistence_mode(settings.erg_jog_persistence_mode)

    def set_opentrueup(self, controller: OpenTrueUpController | None) -> None:
        """Hand the live bridge a replacement OpenTrueUp controller (or None to disable it)."""
        self.submit_action(lambda bridge: bridge.set_opentrueup(controller))

    def set_erg_jog_persistence_mode(self, mode: JogPersistenceMode) -> None:
        """Update jog-persistence mode for the current and any future bridge."""
        self._erg_jog_persistence_mode = mode
        self.submit_action(
            lambda bridge: bridge.set_erg_jog_persistence_mode(self._erg_jog_persistence_mode)
        )

    def submit_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> None:
        """Submit a snapshot to the bridge to update trainer targets.

        Mode and targets are read now, on the caller's thread, rather than when the bridge
        thread gets to the snapshot: by then a ride that ended may have left Simulation
        mode or cleared its grade, and a queued snapshot would be applied with them.
        """
        self.submit_action(self._snapshot_action(snapshot, workout))

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

    def _snapshot_action(
        self,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> Callable[[WorkoutEngineFTMSBridge], None]:
        """Capture the current mode and targets for *snapshot* into a bridge action."""
        active_mode = self._mode_state.active_control_mode(snapshot, workout)
        if active_mode == MODE_SIMULATION:
            road_surface = getattr(self._settings, "road_surface", DEFAULT_ROAD_SURFACE)
            grade_percent = self._mode_state.simulation_grade_percent()
            rolling_resistance = rolling_resistance_for_surface(road_surface)

            def _apply_simulation(bridge: WorkoutEngineFTMSBridge) -> None:
                bridge.set_mode_simulation()
                bridge.apply_simulation_grade(snapshot, grade_percent, rolling_resistance)

            return _apply_simulation

        resistance_percent = self._mode_state.resistance_target_percent()
        if getattr(self._mode_state, "is_free_ride", False):
            if active_mode == "Resistance":

                def _apply_free_ride_resistance(bridge: WorkoutEngineFTMSBridge) -> None:
                    bridge.set_mode_resistance()
                    bridge.apply_manual_resistance_level(resistance_percent)

                return _apply_free_ride_resistance

            target_watts = getattr(self._mode_state, "free_ride_erg_target", None)

            def _apply_free_ride_erg(bridge: WorkoutEngineFTMSBridge) -> None:
                bridge.set_mode_erg()
                if target_watts is not None:
                    bridge.apply_manual_erg_target(target_watts)

            return _apply_free_ride_erg

        if active_mode == "Resistance":

            def _apply_resistance(bridge: WorkoutEngineFTMSBridge) -> None:
                bridge.set_mode_resistance()
                bridge.on_engine_snapshot(
                    snapshot, workout, manual_resistance_level=resistance_percent
                )

            return _apply_resistance

        def _apply_erg(bridge: WorkoutEngineFTMSBridge) -> None:
            bridge.set_mode_erg()
            bridge.on_engine_snapshot(snapshot, workout)

        return _apply_erg

    def _resistance_range_for(
        self,
        device_id: str,
        transport: FTMSControlTransport,
    ) -> ResistanceLevelRange | None:
        """Return the trainer's resistance range, reading it over BLE only once per device.

        Failed reads are not cached, so a later reconnect retries them.
        """
        cached = self._resistance_ranges.get(device_id)
        if cached is not None:
            return cached
        resistance_range = transport.read_resistance_level_range()
        if resistance_range is not None:
            self._resistance_ranges[device_id] = resistance_range
        return resistance_range

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
