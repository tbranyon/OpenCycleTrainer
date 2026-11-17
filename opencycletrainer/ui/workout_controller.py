from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time

_logger = logging.getLogger(__name__)

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QFileDialog

from opencycletrainer.core.control.ftms_control import FTMSControlTransport, should_jog_persist_into_interval
from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.devices.ble_backend import BleakDeviceBackend, BleakFTMSControlTransport
from opencycletrainer.core.mrc_parser import MRCParseError, parse_mrc_file
from opencycletrainer.core.cadence_history import CadenceHistory
from opencycletrainer.core.course_model import Course
from opencycletrainer.core.course_ride import CourseRide
from opencycletrainer.core.dfa.pipeline import DFA_WINDOW_SECONDS, DfaPipeline, DfaRecord
from opencycletrainer.core.energy_tracker import ExternalEnergyTracker
from opencycletrainer.core.fit_exporter import FitExporter, FitExportSample
from opencycletrainer.core.gpx_parser import GPXParseError, parse_gpx_file
from opencycletrainer.core.interval_stats import IntervalStats
from opencycletrainer.core.pedaling_detector import PedalingDetector
from opencycletrainer.core.power_history import PowerHistory
from opencycletrainer.core.recorder import WorkoutRecorder, to_fit_export_sample
from opencycletrainer.core.sensors import CadenceSource, PowerSource
from opencycletrainer.core.workout_engine import EngineState, WorkoutEngine, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.core.zwo_parser import ZWOParseError, parse_zwo_file
from opencycletrainer.storage.filenames import build_activity_filename
from opencycletrainer.storage.paths import get_workout_data_root, get_workout_fit_dir
from opencycletrainer.storage.settings import AppSettings, save_settings

from .chart_history import ChartHistory
from .ftms_bridge_manager import FTMSBridgeManager
from .opentrueup_state import OpenTrueUpState
from .mode_state import (
    DEFAULT_FREE_RIDE_ERG_TARGET_WATTS,
    DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT,
    MODE_SIMULATION,
    ModeState,
)
from .pause_state import PauseState
from .recorder_integration import RecorderIntegration, SensorSnapshot
from .ride_format import format_distance, format_grade_percent
from .tile_computation import TileComputation
from .tile_config import DFA_TILE_KEY
from .trainer_connection import TrainerConnection
from .workout_screen import MODE_OPTIONS, PauseDialog, WorkoutScreen
from .workout_summary_dialog import IntervalResult, WorkoutSummary, WorkoutSummaryDialog, compute_tss


_SENSOR_STALE_SECONDS = 3.0
_PEDALING_STOPPED_PAUSE_SECONDS = 3.0
_AUTO_START_PEDALING_SECONDS = 3.0
_RIDING_STATES = frozenset({EngineState.RUNNING, EngineState.RAMP_IN})

_COURSE_FILE_SUFFIX = ".gpx"
_ZWO_FILE_SUFFIX = ".zwo"
_LOAD_FILE_FILTER = (
    "Workouts and Courses (*.mrc *.zwo *.gpx);;Workout Files (*.mrc *.zwo);;GPX Courses (*.gpx)"
)
_OPEN_ENDED_RIDE_SECONDS = 86400
"""Nominal length of a ride with no planned end (a free ride or a course)."""

# A rider who stops pedaling on a descent is coasting, not stopping, so the ride is not
# auto-paused while the road drops at least this steeply and the bike is still rolling.
_COASTING_MAX_GRADE_PERCENT = -1.0
_COASTING_MIN_SPEED_MPS = 1.0


class WorkoutSessionController(QObject):
    """Connects WorkoutScreen controls/hotkeys to the workout engine runtime loop."""
    _bridge_alert_signal = Signal(str)
    _opentrueup_offset_signal = Signal(object)
    _strava_alert_signal = Signal(str, str)

    def __init__(
        self,
        *,
        screen: WorkoutScreen,
        settings: AppSettings,
        settings_path: Path | None = None,
        recorder: WorkoutRecorder | None = None,
        opentrueup: OpenTrueUpController | None = None,
        ftms_transport_factory: Callable[[object, str], FTMSControlTransport | None] | None = None,
        summary_dialog_factory: Callable[[WorkoutSummary, object], object] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        strava_upload_fn: Callable[[Path, Path | None], None] | None = None,
        intervals_icu_upload_fn: Callable[[Path, Path | None], None] | None = None,
        fit_exporter: FitExporter | None = None,
        tick_interval_ms: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._screen = screen
        self._settings = settings
        self._settings_path = settings_path
        self._monotonic_clock = monotonic_clock
        self._utc_now = utc_now if utc_now is not None else lambda: datetime.now(timezone.utc)
        self._recorder = recorder if recorder is not None else WorkoutRecorder()
        self._manual_save_fit_exporter = fit_exporter if fit_exporter is not None else FitExporter()
        self._completed_recording: dict | None = None
        self._workout_started_at_utc: datetime | None = None
        self._ftms_transport_factory = (
            ftms_transport_factory
            if ftms_transport_factory is not None
            else self._default_ftms_transport_factory
        )
        self._summary_dialog_factory = (
            summary_dialog_factory
            if summary_dialog_factory is not None
            else lambda summary, parent: WorkoutSummaryDialog(summary, parent)
        )
        self._opentrueup_state = (
            OpenTrueUpState(opentrueup, self._opentrueup_offset_signal.emit)
            if opentrueup is not None
            else OpenTrueUpState.from_settings(settings, self._opentrueup_offset_signal.emit)
        )
        self._engine = WorkoutEngine(
            kj_mode=self._settings.default_workout_behavior == "kj_mode",
        )
        self._workout: Workout | None = None
        self._mode_state = ModeState(self._screen.mode_selector.currentText())
        self._mode_state.set_simulation_difficulty_percent(
            self._settings.simulation_difficulty_percent
        )
        self._course_ride: CourseRide | None = None
        self._last_course_tick_monotonic: float | None = None
        self._mode_before_course: str | None = None
        self._interval_extra_seconds: dict[int, int] = {}
        self._last_snapshot: WorkoutEngineSnapshot | None = None

        self._power_history = PowerHistory()
        self._dfa_was_active = False
        self._dfa_pipeline = DfaPipeline(
            power_source=lambda now: self._power_history.windowed_avg(now, DFA_WINDOW_SECONDS)
        )
        self._pm_energy_tracker = ExternalEnergyTracker()
        self._ftms_energy_tracker = ExternalEnergyTracker()
        self._cadence_hist = CadenceHistory()
        self._pedaling = PedalingDetector()
        self._interval_stats = IntervalStats()
        self._active_interval_index: int | None = None
        self._interval_results: list[IntervalResult] = []
        self._current_interval_is_skipped: bool = False
        self._last_power_watts: int | None = None
        self._last_bike_power_watts: int | None = None
        self._last_hr_bpm: int | None = None
        self._last_rr_intervals_ms: tuple[float, ...] | None = None
        self._last_speed_mps: float | None = None
        self._last_pedal_balance_left_pct: float | None = None
        self._last_trainer_power_received_at: float | None = None
        self._last_bike_power_received_at: float | None = None
        self._last_hr_received_at: float | None = None
        self._last_speed_received_at: float | None = None

        self._pause_state = PauseState(self._screen, self._resume_workout)
        self._chart_history = ChartHistory(
            self._screen,
            self._monotonic_clock,
            self._power_history,
            self._pause_state,
        )
        self._recorder_integration = RecorderIntegration(
            recorder=self._recorder,
            screen=self._screen,
            settings=self._settings,
            utc_now=self._utc_now,
            strava_upload_fn=strava_upload_fn,
            intervals_icu_upload_fn=intervals_icu_upload_fn,
            alert_signal=self._strava_alert_signal.emit,
            mode_state=self._mode_state,
            monotonic_now=self._monotonic_clock,
        )
        self._ftms_bridge_manager = FTMSBridgeManager(
            transport_factory=self._ftms_transport_factory,
            screen=self._screen,
            alert_signal=self._bridge_alert_signal.emit,
            opentrueup_state=self._opentrueup_state,
            mode_state=self._mode_state,
            settings=self._settings,
            engine=self._engine,
        )

        self._tile_computation = TileComputation(
            self._power_history,
            self._cadence_hist,
            self._interval_stats,
            self._monotonic_clock,
            lambda: self._last_hr_bpm,
            self._pm_energy_tracker,
            self._ftms_energy_tracker,
            balance_source=lambda: self._last_pedal_balance_left_pct,
            dfa_source=self.latest_dfa_record,
            speed_source=self._current_speed_mps,
            distance_source=self._course_distance_m,
        )

        self._timer = QTimer(self)
        self._timer.setInterval(max(100, int(tick_interval_ms)))
        self._timer.timeout.connect(self.process_tick)

        self._trainer_connection = TrainerConnection(
            screen=self._screen,
            is_workout_active=self._timer.isActive,
        )
        self._power_source_trainer_id: str | None = None
        self._power_source_meter_id: str | None = None

        self._chart_history.chart_timer.timeout.connect(self._on_chart_tick)

        self._wire_screen_actions()
        self._set_no_workout_state()
        self._bridge_alert_signal.connect(self._screen.show_alert)
        self._opentrueup_offset_signal.connect(self._screen.set_opentrueup_offset_watts)
        self._strava_alert_signal.connect(self._screen.show_alert)

    @property
    def last_snapshot(self) -> WorkoutEngineSnapshot | None:
        return self._last_snapshot

    @property
    def course_ride(self) -> CourseRide | None:
        """The course being ridden (or loaded and ready), or None outside a course ride."""
        return self._course_ride

    def set_trainer_control_target(
        self,
        *,
        backend: object,
        trainer_device_id: str | None,
    ) -> None:
        self._trainer_connection.set_target(backend, trainer_device_id)
        self._ftms_bridge_manager.configure(
            backend, trainer_device_id, self._workout, self._last_snapshot
        )

    def set_power_source_pair(
        self,
        trainer_device_id: str | None,
        power_meter_device_id: str | None,
    ) -> None:
        """Update the active trainer + power meter pairing used for persistence."""
        self._power_source_trainer_id = trainer_device_id
        self._power_source_meter_id = power_meter_device_id
        self._opentrueup_state.configure_pair(
            self._settings,
            trainer_device_id,
            power_meter_device_id,
        )
        self._ftms_bridge_manager.set_opentrueup(self._opentrueup_state.controller)

    def apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._engine.kj_mode = settings.default_workout_behavior == "kj_mode"
        self._recorder_integration.configure_data_dir(settings)
        was_enabled = self._opentrueup_state.enabled
        now_enabled = settings.opentrueup_enabled
        if not was_enabled and now_enabled:
            self._opentrueup_state.enable(
                settings,
                self._power_source_trainer_id,
                self._power_source_meter_id,
            )
        elif was_enabled and not now_enabled:
            self._opentrueup_state.disable()
        self._ftms_bridge_manager.apply_settings(settings)
        self._mode_state.set_simulation_difficulty_percent(settings.simulation_difficulty_percent)
        if self._course_ride is not None:
            self._course_ride.set_total_mass_kg(settings.total_mass_kg)
        if was_enabled != now_enabled:
            self._ftms_bridge_manager.set_opentrueup(self._opentrueup_state.controller)

    def shutdown(self) -> None:
        self._timer.stop()
        self._chart_history.stop()
        self._ftms_bridge_manager.teardown()
        self._recorder_integration.shutdown()

    def process_tick(self, now_monotonic: float | None = None) -> WorkoutEngineSnapshot | None:
        if self._engine.workout is None:
            return None
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        self._update_pedaling(now)
        if self._engine.state in _RIDING_STATES:
            stopped_for = self._pedaling.seconds_since_pedaling(now)
            if (
                stopped_for is not None
                and stopped_for > _PEDALING_STOPPED_PAUSE_SECONDS
                and not self._is_coasting()
            ):
                self._pause_workout()
                return self._last_snapshot
        dfa_record = self._update_dfa(now)
        if dfa_record is not None and self._recorder_integration.recorder_active:
            self._chart_history.record_dfa_alpha1(dfa_record.alpha1, now)
        snapshot = self._engine.tick(now, pedaling=self._pedaling.is_pedaling)
        self._advance_course(snapshot, now)
        self._handle_snapshot(snapshot, now_monotonic=now)
        if snapshot.state == EngineState.FINISHED:
            self._timer.stop()
            recorder_summary = self._recorder_integration.prepare_summary()
            self._show_workout_summary(recorder_summary)
        elif self._course_ride is not None and self._course_ride.finished:
            self._stop_workout()
            return self._last_snapshot
        return snapshot

    def _advance_course(self, snapshot: WorkoutEngineSnapshot, now: float) -> None:
        """Move the rider along the course for the time since the last tick.

        The bike only moves while the engine is running; paused or ramping back in, it
        stands still.
        """
        ride = self._course_ride
        if ride is None:
            return
        last_tick = self._last_course_tick_monotonic
        self._last_course_tick_monotonic = now
        if snapshot.state != EngineState.RUNNING:
            ride.halt()
            return
        if last_tick is None:
            return
        sample = self._effective_power_sample(now)
        ride.advance(now - last_tick, sample[0] if sample is not None else 0)
        self._mode_state.set_course_grade(ride.grade_percent)

    def _is_coasting(self) -> bool:
        """True while a course rider is rolling down a descent without pedaling."""
        ride = self._course_ride
        return (
            ride is not None
            and ride.grade_percent <= _COASTING_MAX_GRADE_PERCENT
            and ride.speed_mps >= _COASTING_MIN_SPEED_MPS
        )

    def _current_speed_mps(self) -> float | None:
        """Speed to show and record: the virtual speed on a course, else the sensor's."""
        if self._course_ride is not None:
            return self._course_ride.speed_mps
        return self._fresh_value(
            self._last_speed_mps, self._last_speed_received_at, float(self._monotonic_clock())
        )

    def _course_readings(self) -> dict[str, float | None]:
        """Return the rider's place on the course for the recorder; empty outside a course."""
        ride = self._course_ride
        if ride is None:
            return {}
        latitude, longitude = ride.position or (None, None)
        return {
            "distance_m": ride.distance_m,
            "altitude_m": ride.elevation_m,
            "grade_percent": ride.grade_percent,
            "latitude_deg": latitude,
            "longitude_deg": longitude,
        }

    def _course_distance_m(self) -> float | None:
        """Distance ridden along the course, or None outside a course ride."""
        return self._course_ride.distance_m if self._course_ride is not None else None

    def _wire_screen_actions(self) -> None:
        self._screen.start_button.clicked.connect(self._start_workout)
        self._screen.pause_button.clicked.connect(self._pause_workout)
        self._screen.resume_button.clicked.connect(self._resume_workout)
        self._screen.end_button.clicked.connect(self._stop_workout)
        self._screen.save_button.clicked.connect(self._manual_save_completed_workout)
        self._screen.extend_interval_requested.connect(self._extend_interval)
        self._screen.skip_interval_requested.connect(self._skip_interval)
        self._screen.jog_requested.connect(self._jog_target)
        self._screen.mode_selector.currentTextChanged.connect(self._mode_selected)
        self._screen.load_workout_requested.connect(self._request_load_workout_from_file)
        self._screen.free_ride_requested.connect(self._start_free_ride)
        self._screen.erg_target_entered.connect(self._on_erg_target_entered)
        self._screen.kj_source_selected.connect(self._on_kj_source_selected)

    def _set_no_workout_state(self) -> None:
        self._workout = None
        self._leave_open_ended_ride()
        self._screen.set_workout_name(None)
        self._screen.set_session_state("idle")
        self._screen.set_mandatory_metrics(
            elapsed_text="--:--:--",
            remaining_text="--:--:--",
            interval_remaining_text="--:--:--",
            target_power_text="-- W",
        )

    def load_workout(self, path: Path) -> None:
        """Load a workout from *path* without opening a file dialog."""
        self._load_workout_from_file(path)

    def _request_load_workout_from_file(self) -> None:
        start_dir = str(self._settings.last_workout_dir or Path.home())
        file_path_str, _ = QFileDialog.getOpenFileName(
            self._screen,
            "Load Workout or Course File",
            start_dir,
            _LOAD_FILE_FILTER,
        )
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        self._load_workout_from_file(file_path)

    def _load_workout_from_file(self, path: Path) -> None:
        """Load a workout (.mrc, .zwo) or a course (.gpx), chosen by the file's extension."""
        self._screen.clear_alert()
        if path.suffix.lower() == _COURSE_FILE_SUFFIX:
            self._load_course_from_file(path)
            return
        ftp = max(1, int(self._settings.ftp))
        try:
            if path.suffix.lower() == _ZWO_FILE_SUFFIX:
                workout = parse_zwo_file(path, ftp_watts=ftp)
            else:
                workout = parse_mrc_file(path, ftp_watts=ftp)
        except (MRCParseError, ZWOParseError) as exc:
            self._screen.show_alert(f"Could not load '{path.name}' — file format may be invalid")
            return
        except (IOError, OSError) as exc:
            self._screen.show_alert(f"Could not read '{path.name}' — check the file exists and is accessible")
            return

        self._clear_completed_recording()
        self._leave_open_ended_ride()
        self._workout = workout
        self._interval_extra_seconds = {}
        self._mode_state._manual_resistance_offset_percent = DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT
        self._mode_state.reset_jog()
        self._mode_state.reset_grade_offset()
        self._chart_history.stop()
        # Loading arms auto-start, so any pedaling before the load does not count.
        self._pedaling.reset()
        self._screen.load_workout_chart(workout, ftp)
        snapshot = self._engine.load_workout(self._workout)
        self._screen.set_workout_name(self._workout.name)
        self._handle_snapshot(snapshot, now_monotonic=None)
        self._settings.last_workout_dir = path.parent
        save_settings(self._settings, self._settings_path)

    def _load_course_from_file(self, path: Path) -> None:
        """Parse a GPX file and ready a ride along it."""
        try:
            course = parse_gpx_file(path)
        except GPXParseError as exc:
            self._screen.show_alert(f"Could not load '{path.name}' — {exc}")
            return
        except (OSError, UnicodeDecodeError):
            self._screen.show_alert(f"Could not read '{path.name}' — check the file exists and is accessible")
            return

        self._clear_completed_recording()
        self._load_course(course)
        self._settings.last_workout_dir = path.parent
        save_settings(self._settings, self._settings_path)

    def _load_course(self, course: Course) -> None:
        """Ready an open-ended ride along *course*, with the trainer simulating its grade.

        The ride reuses free-ride behaviour (no planned targets, optional ERG target) and
        ends when the rider reaches the end of the course.
        """
        self._leave_open_ended_ride()
        self._course_ride = CourseRide(course, total_mass_kg=self._settings.total_mass_kg)
        self._last_course_tick_monotonic = None
        self._interval_extra_seconds = {}
        self._mode_state.set_free_ride(True, DEFAULT_FREE_RIDE_ERG_TARGET_WATTS)
        self._mode_state.reset_jog()
        self._mode_state.reset_grade_offset()
        self._mode_state.set_course_grade(self._course_ride.grade_percent)
        self._chart_history.stop()
        # Loading arms auto-start, so any pedaling before the load does not count.
        self._pedaling.reset()

        self._workout = _open_ended_workout(course.name, max(1, int(self._settings.ftp)))
        snapshot = self._engine.load_workout(self._workout)
        self._mode_before_course = self._mode_state.selected_mode
        self._mode_state.select_mode(MODE_SIMULATION)
        self._screen.set_mode_state(MODE_SIMULATION)
        self._screen.set_free_ride_mode(True)
        self._screen.set_course_mode(True)
        self._screen.load_course_chart(course)
        self._screen.set_workout_name(course.name)
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _leave_open_ended_ride(self) -> None:
        """Return mode state and screen from a free ride or course ride to planned-workout use."""
        was_course = self._course_ride is not None
        was_free_ride = self._mode_state.is_free_ride
        self._course_ride = None
        self._last_course_tick_monotonic = None
        if was_free_ride:
            self._mode_state.set_free_ride(False, None)
            self._screen.set_free_ride_mode(False)
        if not was_course:
            if was_free_ride:
                self._screen.set_interval_plot_visible(True)
            return
        self._mode_state.set_course_grade(None)
        self._mode_state.reset_grade_offset()
        self._screen.set_course_mode(False)
        previous_mode, self._mode_before_course = self._mode_before_course, None
        if previous_mode is not None and self._mode_state.selected_mode == MODE_SIMULATION:
            self._mode_state.select_mode(previous_mode)
            self._screen.set_mode_state(previous_mode)

    def _start_workout(self) -> None:
        if self._engine.workout is None:
            return 

        if self._engine.state in {EngineState.RUNNING, EngineState.RAMP_IN}:
            return
        if self._engine.state == EngineState.PAUSED:
            self._resume_workout()
            return

        self._interval_extra_seconds = {}
        self._mode_state.reset_jog()
        self._power_history.reset()
        self._interval_stats.reset_workout()
        self._active_interval_index = None
        self._interval_results = []
        self._current_interval_is_skipped = False
        self._last_power_watts = None
        self._last_bike_power_watts = None
        self._last_hr_bpm = None
        self._last_pedal_balance_left_pct = None
        self._last_trainer_power_received_at = None
        self._last_bike_power_received_at = None
        self._last_hr_received_at = None
        self._last_speed_received_at = None
        self._chart_history.reset()
        self._dfa_pipeline.reset()
        self._pedaling.reset()
        self._pause_state.reset()
        self._clear_completed_recording()
        now = float(self._monotonic_clock())
        started_at_utc = self._utc_now()
        self._workout_started_at_utc = started_at_utc
        self._recorder_integration.start(self._workout, started_at_utc, now)

        self._engine.start()
        self._chart_history.start(now)
        if self._course_ride is not None:
            self._course_ride.reset()
            self._last_course_tick_monotonic = None
            self._mode_state.set_course_grade(self._course_ride.grade_percent)
            self._screen.load_course_chart(self._course_ride.course)
        elif self._workout is not None:
            self._screen.load_workout_chart(self._workout, int(self._settings.ftp))
        snapshot = self._engine.tick(now)
        self._timer.start()
        self._handle_snapshot(snapshot, now_monotonic=now)

    def _start_free_ride(self) -> None:
        if self._engine.state in {EngineState.RUNNING, EngineState.RAMP_IN, EngineState.PAUSED}:
            return

        self._mode_state.set_free_ride(True, DEFAULT_FREE_RIDE_ERG_TARGET_WATTS)
        self._mode_state.reset_jog()
        self._interval_extra_seconds = {}
        self._power_history.reset()
        self._interval_stats.reset_workout()
        self._active_interval_index = None
        self._last_power_watts = None
        self._last_bike_power_watts = None
        self._last_hr_bpm = None
        self._last_pedal_balance_left_pct = None
        self._last_trainer_power_received_at = None
        self._last_bike_power_received_at = None
        self._last_hr_received_at = None
        self._last_speed_received_at = None
        self._chart_history.reset()
        self._dfa_pipeline.reset()
        self._pedaling.reset()
        self._pause_state.reset()

        synthetic = _open_ended_workout("Free Ride", max(1, int(self._settings.ftp)))
        self._workout = synthetic
        self._engine.load_workout(synthetic)

        self._mode_state.select_mode("Resistance")
        self._screen.set_mode_state("Resistance")
        self._screen.set_free_ride_mode(True)
        self._screen.set_interval_plot_visible(False)
        self._screen.load_free_ride_chart()
        self._screen.set_workout_name("Free Ride")

        self._clear_completed_recording()
        now = float(self._monotonic_clock())
        started_at_utc = self._utc_now()
        self._workout_started_at_utc = started_at_utc
        self._recorder_integration.start(self._workout, started_at_utc, now)
        self._engine.start()
        self._chart_history.start(now)
        snapshot = self._engine.tick(now)
        self._timer.start()
        self._handle_snapshot(snapshot, now_monotonic=now)

    def _on_erg_target_entered(self, watts: int) -> None:
        """Switch to ERG mode with the given watt target entered by the user in free ride."""
        self._mode_state.set_erg_target(watts)
        self._screen.set_mode_state("ERG")
        jog_offset = 0.0
        self._ftms_bridge_manager.submit_action(
            lambda bridge: bridge.set_erg_jog_offset_watts(jog_offset)
        )
        if self._last_snapshot:
            self._handle_snapshot(self._last_snapshot, now_monotonic=None)

    def _effective_power_sample(self, now: float) -> tuple[int, float] | None:
        """Return the freshest usable (watts, received_at) power pair: bike preferred, trainer fallback."""
        for watts, received_at in (
            (self._last_bike_power_watts, self._last_bike_power_received_at),
            (self._last_power_watts, self._last_trainer_power_received_at),
        ):
            if self._fresh_value(watts, received_at, now) is not None:
                return int(watts), float(received_at)
        return None

    def _update_pedaling(self, now: float) -> None:
        """Record a pedaling observation and act on any auto start/resume it triggers.

        Cadence is only consulted while a cadence source is reporting, so trainers
        that publish power alone can still drive auto start, pause and resume.
        """
        sample = self._effective_power_sample(now)
        cadence = self._cadence_hist.fresh_rpm(now)
        pedaling = sample is not None and sample[0] > 0 and (cadence is None or cadence > 0)
        # Pedaling is timestamped with the reading it came from, not with *now*:
        # a held reading must not keep pushing the stopped-pedaling clock forward
        # between sensor updates.
        self._pedaling.update(sample[1] if pedaling else now, pedaling=pedaling)
        self._maybe_auto_start_or_resume(now)

    def _maybe_auto_start_or_resume(self, now: float) -> None:
        """Start a loaded workout, or leave a pause, on the strength of the rider pedaling."""
        state = self._engine.state
        if state == EngineState.READY:
            if self._pedaling.pedaling_duration(now) >= _AUTO_START_PEDALING_SECONDS:
                self._start_workout()
            return
        if state != EngineState.PAUSED:
            return
        # Only a pedaling run that began after the pause resumes the workout, so a
        # deliberate pause is not undone while the rider is still turning the cranks.
        pause_start = self._pause_state.pause_start_monotonic
        pedaling_since = self._pedaling.pedaling_since
        if pause_start is None or pedaling_since is None or pedaling_since < pause_start:
            return
        self._auto_resume()

    def _auto_resume(self) -> None:
        """Resume as though the pause dialog's Resume button had been pressed."""
        dialog = self._pause_state.pause_dialog
        if dialog is None:
            self._resume_workout()
            return
        dialog.begin_resume()

    def _pause_workout(self) -> None:
        """Pause the workout; ignored unless the engine is running or ramping in."""
        if self._engine.state not in _RIDING_STATES:
            return
        now = self._monotonic_clock()
        snapshot = self._engine.pause()
        self._handle_snapshot(snapshot, now_monotonic=None)
        self._pause_state.pause(now)

    def _resume_workout(self) -> None:
        # _pause_start_monotonic remains set intentionally: the cursor stays frozen
        # through RAMP_IN. It is accumulated and cleared when RAMP_IN → RUNNING
        # is detected in _handle_snapshot.
        snapshot = self._engine.resume()
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _stop_workout(self) -> None:
        self._pause_state.close_dialog()
        snapshot = self._engine.stop()
        self._timer.stop()
        self._chart_history.stop()
        self._leave_open_ended_ride()
        self._handle_snapshot(snapshot, now_monotonic=None)
        recorder_summary = self._recorder_integration.prepare_summary()
        self._show_workout_summary(recorder_summary)

    def _extend_interval(self, seconds_or_kj: int, is_kj_mode: bool) -> None:
        if bool(is_kj_mode) != self._engine.kj_mode:
            return
        snapshot = self._engine.extend_interval(int(seconds_or_kj))
        if not is_kj_mode and snapshot.current_interval_index is not None:
            current_index = int(snapshot.current_interval_index)
            current_extra = self._interval_extra_seconds.get(current_index, 0)
            self._interval_extra_seconds[current_index] = current_extra + int(seconds_or_kj)
            self._screen.rebuild_target_series(self._engine.interval_durations)
        self._handle_snapshot(snapshot, now_monotonic=None)

    def _skip_interval(self) -> None:
        elapsed_before = self._last_snapshot.elapsed_seconds if self._last_snapshot else 0.0
        mono_now = float(self._monotonic_clock())
        self._current_interval_is_skipped = True
        snapshot = self._engine.skip_interval()
        elapsed_after = snapshot.elapsed_seconds
        if elapsed_after > elapsed_before and self._chart_history.chart_start_monotonic is not None:
            self._chart_history.record_skip(mono_now, elapsed_before, elapsed_after)
            self._screen.add_skip_marker(elapsed_before, elapsed_after)
        self._handle_snapshot(snapshot, now_monotonic=None)
        if snapshot.state == EngineState.FINISHED:
            self._timer.stop()
            self._chart_history.stop()
            recorder_summary = self._recorder_integration.prepare_summary()
            self._show_workout_summary(recorder_summary)

    def _jog_target(self, delta_percent: int) -> None:
        snapshot = self._last_snapshot or self._engine.snapshot()
        self._mode_state.jog(delta_percent, max(1, self._settings.ftp), snapshot, self._workout)

        active_mode = self._mode_state.active_control_mode(snapshot, self._workout)
        if active_mode == "ERG":
            jog_watts = self._mode_state.erg_jog_watts
            self._ftms_bridge_manager.submit_action(
                lambda bridge: bridge.set_erg_jog_offset_watts(jog_watts)
            )
        elif active_mode == "Resistance" and snapshot.state in _RIDING_STATES:
            # Interval-driven updates only send resistance at interval changes, so push the
            # jogged level now. While paused the trainer keeps its pause setpoint and the
            # new level is applied on resume.
            level = self._mode_state.resistance_target_percent()
            self._ftms_bridge_manager.submit_action(
                lambda bridge: bridge.apply_manual_resistance_level(level)
            )

        # Force an immediate update of the trainer target
        if self._last_snapshot:
            self._handle_snapshot(self._last_snapshot, now_monotonic=None)

    def _mode_selected(self, mode: str) -> None:
        if mode not in MODE_OPTIONS:
            return
        self._mode_state.select_mode(mode)
        self._handle_snapshot(self._engine.snapshot(), now_monotonic=None)

    def _handle_snapshot(
        self,
        snapshot: WorkoutEngineSnapshot,
        *,
        now_monotonic: float | None,
    ) -> None:
        prev_state = self._last_snapshot.state if self._last_snapshot is not None else None
        if prev_state == EngineState.RAMP_IN and snapshot.state == EngineState.RUNNING:
            now = self._monotonic_clock()
            pause_start = self._pause_state.pause_start_monotonic
            if pause_start is not None:
                self._chart_history.record_pause(now, now - pause_start)
            self._pause_state.on_ramp_in_to_running(now)
            self._pause_state.close_dialog()
        self._last_snapshot = snapshot
        self._screen.set_session_state(snapshot.state.value)
        self._screen.set_mode_state(self._mode_state.selected_mode)

        active_mode = self._mode_state.active_control_mode(snapshot, self._workout)
        if active_mode == "Resistance":
            value, show_percent = self._mode_state.resistance_display()
            self._screen.set_resistance_level(value, show_percent=show_percent)
            self._screen.set_jog_offset(None)
            self._screen.set_simulation_grade(None)
        elif active_mode == MODE_SIMULATION:
            self._screen.set_resistance_level(None)
            self._screen.set_jog_offset(None)
            self._screen.set_simulation_grade(self._mode_state.simulation_grade_percent())
        else:
            self._screen.set_resistance_level(None)
            self._screen.set_jog_offset(int(round(self._mode_state.erg_jog_watts)))
            self._screen.set_simulation_grade(None)

        current_index = snapshot.current_interval_index
        if current_index != self._active_interval_index:
            if self._active_interval_index is not None:
                self._capture_interval_result(
                    self._active_interval_index, skipped=self._current_interval_is_skipped
                )
            self._current_interval_is_skipped = False
            self._active_interval_index = current_index
            self._reset_interval_accumulators()
            if not self._should_jog_persist_into_current_interval(current_index):
                self._mode_state.reset_jog()

        elapsed_seconds = int(round(snapshot.riding_elapsed_seconds))
        window = max(1, int(self._settings.windowed_power_window_seconds))
        windowed_avg = self._windowed_avg_power(self._monotonic_clock(), window)
        current_str = str(windowed_avg) if windowed_avg is not None else "--"

        if self._mode_state.is_free_ride:
            remaining_text = "\u2014"
            interval_remaining_text = "\u2014"
            if self._course_ride is not None:
                remaining_text = format_distance(
                    self._course_ride.remaining_m, self._settings.display_units
                )
                interval_remaining_text = format_grade_percent(self._course_ride.grade_percent)
                self._screen.update_course_position(self._course_ride.distance_m)
            if self._mode_state.active_control_mode(snapshot, self._workout) == "ERG" and self._mode_state.free_ride_erg_target is not None:
                target_watts = self._mode_state.free_ride_erg_target + int(round(self._mode_state.erg_jog_watts))
                target_str = str(target_watts)
            else:
                target_str = "\u2014"
        else:
            remaining_seconds = max(int(snapshot.total_duration_seconds) - int(round(snapshot.elapsed_seconds)), 0)
            interval_remaining_seconds = self._interval_remaining_seconds(snapshot)
            target_watts = self._mode_state.resolve_target_watts(snapshot, self._workout) or self._mode_state.workout_target_watts(snapshot, self._workout)
            remaining_text = _format_hh_mm_ss(remaining_seconds)
            interval_remaining_text = _format_hh_mm_ss(interval_remaining_seconds)
            target_str = str(target_watts) if target_watts is not None else "--"

        self._screen.set_mandatory_metrics(
            elapsed_text=_format_hh_mm_ss(elapsed_seconds),
            remaining_text=remaining_text,
            interval_remaining_text=interval_remaining_text,
            target_power_text=f"{current_str} / {target_str} W",
        )

        self._update_tiles(snapshot)
        self._ftms_bridge_manager.submit_snapshot(snapshot, self._workout)

        if self._recorder_integration.recorder_active:
            dfa_record = self.latest_dfa_record()
            now = float(self._monotonic_clock())
            self._recorder_integration.sync(
                snapshot,
                now_monotonic,
                SensorSnapshot(
                    last_power_watts=self._fresh_value(
                        self._last_power_watts, self._last_trainer_power_received_at, now
                    ),
                    last_bike_power_watts=self._fresh_value(
                        self._last_bike_power_watts, self._last_bike_power_received_at, now
                    ),
                    last_hr_bpm=self._fresh_value(self._last_hr_bpm, self._last_hr_received_at, now),
                    last_cadence_rpm=self._cadence_hist.fresh_rpm(now),
                    last_speed_mps=self._current_speed_mps(),
                    dfa_alpha1=dfa_record.alpha1 if dfa_record is not None else None,
                    dfa_quality=dfa_record.quality.value if dfa_record is not None else None,
                    **self._course_readings(),
                ),
            )

    def _interval_remaining_seconds(self, snapshot: WorkoutEngineSnapshot) -> int:
        index = snapshot.current_interval_index
        if index is None or self._workout is None:
            return 0
        if index < 0 or index >= len(self._workout.intervals):
            return 0
        base_duration = int(self._workout.intervals[index].duration_seconds)
        interval_duration = base_duration + self._interval_extra_seconds.get(index, 0)
        elapsed = int(round(snapshot.current_interval_elapsed_seconds or 0.0))
        return max(interval_duration - elapsed, 0)

    def _workout_target_watts(self, snapshot: WorkoutEngineSnapshot) -> int | None:
        """Return the raw workout target power regardless of control mode."""
        return self._mode_state.workout_target_watts(snapshot, self._workout)

    def _resolve_target_watts(self, snapshot: WorkoutEngineSnapshot) -> int | None:
        return self._mode_state.resolve_target_watts(snapshot, self._workout)

    def _resistance_display(self) -> tuple[int, bool]:
        return self._mode_state.resistance_display()

    def _active_control_mode(self, snapshot: WorkoutEngineSnapshot) -> str:
        return self._mode_state.active_control_mode(snapshot, self._workout)

    def _show_workout_summary(self, recorder_summary: object = None) -> None:
        """Build a WorkoutSummary from recorder-derived metrics and display the modal."""
        # Capture the in-progress interval for workouts stopped before natural completion.
        if self._active_interval_index is not None:
            self._capture_interval_result(self._active_interval_index, skipped=False)
            self._active_interval_index = None

        elapsed = self._last_snapshot.elapsed_seconds if self._last_snapshot else 0.0
        ftp = max(1, int(self._settings.ftp))

        if recorder_summary is not None:
            np_watts = getattr(recorder_summary, "normalized_power", None)
            kj = float(getattr(recorder_summary, "kj", 0.0))
            avg_hr = getattr(recorder_summary, "avg_hr", None)
        else:
            np_watts = self._compute_normalized_power()
            kj = self._power_history.workout_actual_kj()
            avg_hr = self._interval_stats.workout_avg_hr()

        tss = compute_tss(np_watts, ftp, elapsed)
        summary = WorkoutSummary(
            elapsed_seconds=elapsed,
            kj=kj,
            normalized_power=np_watts,
            tss=tss,
            avg_hr=avg_hr,
            interval_results=tuple(self._interval_results),
            workout_name=self._workout.name if self._workout else "",
            power_samples=tuple(self._power_history.as_series()),
        )
        dialog = self._summary_dialog_factory(summary, self._screen)
        if dialog is not None:
            dialog.accepted.connect(lambda: self._on_summary_finish(dialog.activity_name()))
            dialog.rejected.connect(self._on_summary_discard)
            dialog.open()
        else:
            self._on_summary_finish(None)

    def _on_summary_finish(self, activity_name: str | None = None) -> None:
        completed = self._capture_completed_recording(activity_name)
        self._recorder_integration.commit(activity_name=activity_name or None)
        self._set_no_workout_state()
        if completed is not None:
            self._completed_recording = completed
            self._screen.set_save_available(True)

    def _on_summary_discard(self) -> None:
        self._recorder_integration.discard()
        self._set_no_workout_state()

    def _capture_completed_recording(self, activity_name: str | None) -> dict | None:
        """Snapshot the just-finished recording for manual FIT save. Called before commit()."""
        if self._workout is None or self._workout_started_at_utc is None:
            return None
        get_samples = getattr(self._recorder, "get_recorded_samples", None)
        samples = list(get_samples()) if callable(get_samples) else []
        name = activity_name.strip() if isinstance(activity_name, str) and activity_name.strip() else self._workout.name
        return {
            "samples": samples,
            "workout_name": name,
            "started_at_utc": self._workout_started_at_utc,
            "finished_at_utc": self._utc_now(),
        }

    def _clear_completed_recording(self) -> None:
        self._completed_recording = None
        self._screen.set_save_available(False)

    def _manual_save_completed_workout(self) -> None:
        """Prompt for a directory and write a FIT file from the last completed recording."""
        snapshot = self._completed_recording
        if snapshot is None:
            return
        default_dir = str(get_workout_fit_dir(get_workout_data_root(self._settings.workout_data_dir)))
        directory = QFileDialog.getExistingDirectory(
            self._screen,
            "Save Workout FIT to Directory",
            default_dir,
        )
        if not directory:
            return
        filename = build_activity_filename(
            snapshot["workout_name"],
            snapshot["started_at_utc"],
            "fit",
        )
        dest_path = Path(directory) / filename
        fit_samples = [to_fit_export_sample(sample) for sample in snapshot["samples"]]
        self._screen.show_alert(f"Saving {dest_path.name}…", "info")
        # Encoding a long ride takes seconds, so it runs off the UI thread; the result is
        # reported back through a queued signal.
        threading.Thread(
            target=self._export_manual_save,
            args=(snapshot, dest_path, fit_samples),
            name="manual-fit-save",
        ).start()

    def _export_manual_save(self, snapshot: dict, dest_path: Path, fit_samples: list[FitExportSample]) -> None:
        try:
            self._manual_save_fit_exporter.export_activity(
                workout_name=snapshot["workout_name"],
                started_at_utc=snapshot["started_at_utc"],
                finished_at_utc=snapshot["finished_at_utc"],
                fit_file_path=dest_path,
                samples=fit_samples,
            )
        except Exception as exc:
            _logger.warning("Manual FIT save failed: %s", exc)
            self._strava_alert_signal.emit("Failed to save FIT file", "error")
            return
        self._strava_alert_signal.emit(f"Saved: {dest_path.name}", "success")

    @staticmethod
    def _fresh_value(value: object, received_at: float | None, now: float) -> object | None:
        """Return *value* unless it is older than the sensor staleness window."""
        if value is None or received_at is None:
            return None
        if now - received_at > _SENSOR_STALE_SECONDS:
            return None
        return value

    @staticmethod
    def _resolve_effective_power(
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> int | None:
        """Return the effective power for metrics: bike preferred, trainer fallback."""
        if bike_watts is not None:
            return bike_watts
        return trainer_watts

    def receive_power_watts(self, watts: int | None, now_monotonic: float | None = None) -> None:
        """Feed a live trainer power reading (W) into the metric computation pipeline."""
        self._last_power_watts = watts
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        if watts is None:
            self._power_history.record(
                None,
                now,
                False,
                source=PowerSource.TRAINER,
            )
            return
        self._last_trainer_power_received_at = now
        recording_active = self._last_snapshot is not None and self._last_snapshot.recording_active
        if recording_active:
            accepted = self._power_history.record(
                int(watts),
                now,
                recording_active,
                source=PowerSource.TRAINER,
            )
            if accepted:
                self._interval_stats.record_power(int(watts), now, recording_active)
            if self._recorder_integration.recorder_active:
                self._recorder_integration.ingest_power(now, trainer_watts=int(watts))
        else:
            # While paused (or ramping back in), feed only the live trailing-window
            # display so windowed tiles stay current without recording onto the plot,
            # workout averages, or the FIT file.
            self._power_history.record_live(int(watts), now, source=PowerSource.TRAINER)
        self._dispatch_power_sample(
            timestamp=now,
            trainer_watts=watts,
            bike_watts=None,
        )
        self._update_pedaling(now)

    def receive_bike_power_watts(self, watts: int | None, now_monotonic: float | None = None) -> None:
        """Feed a live bike power meter reading (W).

        CPS power is treated as the primary metrics stream while fresh, with FTMS
        trainer power used as fallback.
        """
        self._last_bike_power_watts = watts
        now = float(now_monotonic if now_monotonic is not None else self._monotonic_clock())
        if watts is None:
            self._power_history.record(
                None,
                now,
                False,
                source=PowerSource.POWER_METER,
            )
            return
        self._last_bike_power_received_at = now
        recording_active = self._last_snapshot is not None and self._last_snapshot.recording_active
        if recording_active:
            accepted = self._power_history.record(
                int(watts),
                now,
                recording_active,
                source=PowerSource.POWER_METER,
            )
            if accepted:
                self._interval_stats.record_power(int(watts), now, recording_active)
            if self._recorder_integration.recorder_active:
                self._recorder_integration.ingest_power(now, bike_watts=int(watts))
        else:
            # While paused (or ramping back in), feed only the live trailing-window
            # display so windowed tiles stay current without recording onto the plot,
            # workout averages, or the FIT file.
            self._power_history.record_live(int(watts), now, source=PowerSource.POWER_METER)
        self._dispatch_power_sample(
            timestamp=now,
            trainer_watts=None,
            bike_watts=watts,
        )
        self._update_pedaling(now)

    def receive_hr_bpm(self, bpm: int | None) -> None:
        """Feed a live heart rate reading (bpm) into the metric computation pipeline."""
        self._last_hr_bpm = bpm
        if bpm is None:
            return
        self._last_hr_received_at = float(self._monotonic_clock())
        recording_active = self._last_snapshot is not None and self._last_snapshot.recording_active
        # While paused (or ramping back in), HR is not recorded into the
        # interval/plot history so the trace freezes instead of capturing pause data.
        if not recording_active:
            return
        self._interval_stats.record_hr(int(bpm))
        if self._recorder_integration.recorder_active:
            self._chart_history.record_hr(int(bpm), float(self._monotonic_clock()))

    def receive_rr_intervals_ms(self, rr_intervals_ms: tuple[float, ...]) -> None:
        """Feed RR-interval readings (ms) from a connected chest strap into the DFA pipeline."""
        self._last_rr_intervals_ms = rr_intervals_ms
        self._dfa_pipeline.ingest_rr(rr_intervals_ms, float(self._monotonic_clock()))

    def latest_dfa_record(self) -> DfaRecord | None:
        """Return the most recently computed DFA α1 record, or None while DFA is off.

        DFA is on only while its tile is selected (DFA spec [0e]); returning None when
        it is off keeps a stale α1 out of the tile, the chart and the recorded FIT file.
        """
        if not self._dfa_active():
            return None
        return self._dfa_pipeline.latest_record

    def _dfa_active(self) -> bool:
        return DFA_TILE_KEY in self._settings.tile_selections

    def _update_dfa(self, now: float) -> DfaRecord | None:
        """Recompute DFA α1 on its 5 s cadence while the tile is selected; else skip it.

        RR beats keep flowing into the pipeline's 120 s buffer either way (that is only an
        append), so selecting the tile mid-ride shows a value at once, without waiting for
        the window to refill. The pipeline enforces its own cadence, so driving it from
        this tick avoids an extra Qt timer (DFA spec [0d]).
        """
        if not self._dfa_active():
            self._dfa_was_active = False
            return None
        just_enabled = not self._dfa_was_active
        self._dfa_was_active = True
        return self._dfa_pipeline.maybe_recompute(now, force=just_enabled)

    def receive_cadence_rpm(
        self, rpm: float | None, source: CadenceSource = CadenceSource.TRAINER
    ) -> None:
        """Feed a live cadence reading (rpm), respecting source priority.

        Sources are accepted in priority order: dedicated sensor > power meter > trainer.
        A lower-priority source is only used when no higher-priority source has been heard
        from within the last staleness window.
        """
        now = float(self._monotonic_clock())
        self._cadence_hist.record(rpm, source, now)
        self._update_pedaling(now)

    def receive_speed_mps(self, mps: float | None) -> None:
        """Feed a live speed reading (m/s) for inclusion in recorder samples."""
        self._last_speed_mps = mps
        if mps is None:
            return
        self._last_speed_received_at = float(self._monotonic_clock())

    def receive_pedal_balance(self, left_pct: float | None) -> None:
        """Feed a live left-pedal power balance reading (%) from a CPS power meter."""
        self._last_pedal_balance_left_pct = left_pct

    def receive_bike_energy_kj(self, kj: float | None) -> None:
        """Feed a cumulative energy reading (kJ) from a CPS power meter."""
        if kj is not None:
            self._pm_energy_tracker.update(float(kj))

    def receive_trainer_energy_kj(self, kj: float | None) -> None:
        """Feed a cumulative energy reading (kJ) from an FTMS trainer."""
        if kj is not None:
            self._ftms_energy_tracker.update(float(kj))

    def _on_kj_source_selected(self, source_key: str) -> None:
        self._tile_computation.kj_workout_source = source_key

    def _dispatch_power_sample(
        self,
        *,
        timestamp: float,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> None:
        if self._ftms_bridge_manager.active:
            self._ftms_bridge_manager.submit_power_sample(timestamp, trainer_watts, bike_watts)
            return
        self._feed_opentrueup(
            timestamp,
            trainer_watts=trainer_watts,
            bike_watts=bike_watts,
        )

    @staticmethod
    def _default_ftms_transport_factory(
        backend: object,
        trainer_device_id: str,
    ) -> FTMSControlTransport | None:
        if not isinstance(backend, BleakDeviceBackend):
            return None
        return BleakFTMSControlTransport(backend, trainer_device_id)

    def _feed_opentrueup(
        self,
        now: float,
        *,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> None:
        self._opentrueup_state.feed(now, trainer_watts=trainer_watts, bike_watts=bike_watts)

    def _capture_interval_result(self, index: int, *, skipped: bool) -> None:
        if self._workout is None or index < 0 or index >= len(self._workout.intervals):
            return
        interval = self._workout.intervals[index]
        if interval.free_ride:
            target_watts = None
            target_percent_ftp = None
        else:
            target_watts = (interval.start_target_watts + interval.end_target_watts) // 2
            target_percent_ftp = (interval.start_percent_ftp + interval.end_percent_ftp) / 2.0
        duration = interval.duration_seconds + self._interval_extra_seconds.get(index, 0)
        self._interval_results.append(IntervalResult(
            interval_number=index + 1,
            duration_seconds=duration,
            target_watts=target_watts,
            target_percent_ftp=target_percent_ftp,
            avg_watts=self._interval_stats.interval_avg_watts(),
            avg_hr=self._interval_stats.interval_avg_hr(),
            skipped=skipped,
        ))

    def _reset_interval_accumulators(self) -> None:
        self._interval_stats.reset_interval()

    def _should_jog_persist_into_current_interval(self, interval_index: int | None) -> bool:
        """Return whether the manual ERG jog offset should carry into *interval_index*."""
        if self._workout is None or interval_index is None:
            return False
        if interval_index < 0 or interval_index >= len(self._workout.intervals):
            return False
        return should_jog_persist_into_interval(
            self._settings.erg_jog_persistence_mode,
            self._workout.intervals[interval_index],
        )

    def _update_tiles(self, snapshot: WorkoutEngineSnapshot) -> None:
        self._screen.update_kj_tile_sources(self._tile_computation.available_kj_sources())
        self._tile_computation.update_screen(self._screen, snapshot, self._settings)

    def _compute_tile_value(self, key: str, snapshot: WorkoutEngineSnapshot) -> str:
        return self._tile_computation.compute(key, snapshot, self._settings)

    def _windowed_avg_power(self, now: float, window_seconds: int) -> int | None:
        return self._power_history.windowed_avg(now, window_seconds)

    def _windowed_avg_cadence(self, now: float) -> int | None:
        return self._cadence_hist.windowed_avg(now)

    def _on_chart_tick(self) -> None:
        erg_target_watts: int | None = None
        if (
            self._mode_state.is_free_ride
            and self._mode_state.active_control_mode(self._last_snapshot, self._workout) == "ERG"
            and self._mode_state.free_ride_erg_target is not None
        ):
            erg_target_watts = self._mode_state.free_ride_erg_target + int(round(self._mode_state.erg_jog_watts))
        self._chart_history.on_tick(
            self._last_snapshot,
            self._workout,
            self._mode_state.is_free_ride,
            erg_target_watts,
        )

    def _compute_normalized_power(self) -> int | None:
        return self._power_history.compute_normalized_power()


def _format_hh_mm_ss(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02}"


def _open_ended_workout(name: str, ftp_watts: int) -> Workout:
    """Build the single target-free interval that backs a free ride or a course ride."""
    interval = WorkoutInterval(
        start_offset_seconds=0,
        duration_seconds=_OPEN_ENDED_RIDE_SECONDS,
        start_percent_ftp=0.0,
        end_percent_ftp=0.0,
        start_target_watts=0,
        end_target_watts=0,
    )
    return Workout(name=name, ftp_watts=ftp_watts, intervals=(interval,))
