from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import struct
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from opencycletrainer.core.workout_engine import EngineState
from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.workout_controller import WorkoutSessionController
from opencycletrainer.ui.workout_screen import WorkoutScreen

DATA_DIR = Path(__file__).parent / "data"

_SESSION_START_UTC = datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
_TICK_SECONDS = 0.25
_POINT_SPACING_DEGREES = 0.001
_POINT_SPACING_METERS = 111.195
_SIMULATION_OPCODE = 0x11
_INTERVAL_TILE_TITLE = "Interval Time/Work Remaining"
_REMAINING_TILE_TITLE = "Time Remaining"


# ── Fakes and helpers ─────────────────────────────────────────────────────────

class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def utc(self) -> datetime:
        return _SESSION_START_UTC + timedelta(seconds=self.now)


class _FakeRecorder:
    def __init__(self) -> None:
        self.started = False
        self.samples: list[object] = []

    def start(self, workout_name: str, started_at_utc: object) -> object:  # noqa: ARG002
        self.started = True
        return SimpleNamespace(workout_name=workout_name)

    def set_recording_active(self, active: bool) -> None:  # noqa: ARG002
        if not self.started:
            raise RuntimeError("Recorder is not active.")

    def record_sample(self, sample: object) -> bool:
        self.samples.append(sample)
        return True

    def get_recorded_samples(self) -> list[object]:
        return list(self.samples)

    def stop(self, finished_at_utc: object, activity_name: str | None = None) -> object:  # noqa: ARG002
        self.started = False
        return SimpleNamespace(
            fit_file_path=Path("Course_20260311_1200.fit"),
            normalized_power=None,
            kj=0.0,
            avg_hr=None,
        )

    def discard(self) -> None:
        self.started = False


class _FakeFTMSTransport:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self._handler = lambda _: None

    def write_control_point(self, payload: bytes) -> Future[None]:
        self.writes.append(payload)
        future: Future[None] = Future()
        future.set_result(None)
        self._handler(bytes([0x80, payload[0], 0x01]))
        return future

    def set_indication_handler(self, handler) -> None:
        self._handler = handler

    def read_resistance_level_range(self):
        return None

    def simulation_grades(self) -> list[float]:
        """Grades (%) of every simulation command written so far."""
        return [
            struct.unpack("<BhhBB", write)[2] / 100.0
            for write in list(self.writes)
            if write[0] == _SIMULATION_OPCODE
        ]


def _qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _wait_until(app: QApplication, predicate, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        app.processEvents()
        time.sleep(0.01)
    return predicate()


def _write_gpx(folder: Path, elevations: list[float], name: str = "Test Course") -> Path:
    """Write a GPX track heading north with one point every ~111 m at the given elevations."""
    points = "".join(
        f'<trkpt lat="{45.0 + index * _POINT_SPACING_DEGREES:.6f}" lon="7.0"><ele>{elevation}</ele></trkpt>'
        for index, elevation in enumerate(elevations)
    )
    path = folder / "course.gpx"
    path.write_text(
        '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{name}</name><trkseg>{points}</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _constant_grade(grade_percent: float, point_count: int = 20) -> list[float]:
    rise_per_point = _POINT_SPACING_METERS * grade_percent / 100.0
    return [500.0 + index * rise_per_point for index in range(point_count)]


class _Session:
    """A controller, its screen and the fakes it was built with."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        settings: AppSettings | None = None,
        transport: _FakeFTMSTransport | None = None,
        course_chooser=None,
    ) -> None:
        self.app = _qapp()
        self.clock = _Clock()
        self.recorder = _FakeRecorder()
        self.summaries: list[object] = []
        self.transport = transport
        self.settings = settings if settings is not None else AppSettings()
        self.settings.workout_data_dir = tmp_path
        self.screen = WorkoutScreen(settings=self.settings)
        self.controller = WorkoutSessionController(
            screen=self.screen,
            settings=self.settings,
            settings_path=tmp_path / "settings.json",
            recorder=self.recorder,
            ftms_transport_factory=(lambda backend, trainer_id: transport),
            summary_dialog_factory=self._record_summary,
            monotonic_clock=self.clock,
            utc_now=self.clock.utc,
            course_chooser=(
                course_chooser
                if course_chooser is not None
                else (lambda course, units, parent: course)
            ),
        )
        if transport is not None:
            self.controller.set_trainer_control_target(
                backend="bleak", trainer_device_id="trainer-1"
            )

    def _record_summary(self, summary: object, parent: object) -> None:  # noqa: ARG002
        self.summaries.append(summary)
        return None

    def load(self, path: Path) -> None:
        self.controller._load_workout_from_file(path)
        self.app.processEvents()

    def start(self) -> None:
        self.screen.start_button.click()
        self.app.processEvents()

    def ride(self, seconds: float, watts: int) -> None:
        """Advance the clock in tick-sized steps while the rider holds *watts*."""
        for _ in range(int(round(seconds / _TICK_SECONDS))):
            self.clock.now += _TICK_SECONDS
            self.controller.receive_power_watts(watts, self.clock.now)
            self.controller.process_tick(self.clock.now)

    @property
    def state(self) -> EngineState:
        return self.controller.last_snapshot.state

    def dispose(self) -> None:
        """Shut the controller down and destroy the screen.

        Every live workout screen filters all application events for its hotkeys, so a
        screen left alive would slow down every test that runs afterwards.
        """
        self.controller.shutdown()
        self.screen.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def session(tmp_path):
    created: list[_Session] = []

    def _make(**kwargs) -> _Session:
        new_session = _Session(tmp_path, **kwargs)
        created.append(new_session)
        return new_session

    yield _make
    for made in created:
        made.dispose()


# ── Loading ───────────────────────────────────────────────────────────────────

def test_loading_a_gpx_file_readies_a_course_ride(session, tmp_path):
    s = session()

    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=5), name="River Road"))

    assert s.state == EngineState.READY
    assert s.screen.title_label.text() == "River Road"
    assert s.controller.course_ride is not None
    assert s.controller.course_ride.course.total_distance_m == pytest.approx(
        4 * _POINT_SPACING_METERS, rel=1e-3
    )


def _write_tcx(folder: Path, elevations: list[float]) -> Path:
    points = "".join(
        f"<Trackpoint><Position><LatitudeDegrees>{45.0 + index * _POINT_SPACING_DEGREES:.6f}</LatitudeDegrees>"
        f"<LongitudeDegrees>7.0</LongitudeDegrees></Position><AltitudeMeters>{elevation}</AltitudeMeters></Trackpoint>"
        for index, elevation in enumerate(elevations)
    )
    path = folder / "course.tcx"
    path.write_text(
        '<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f"<Courses><Course><Name>River Road</Name><Track>{points}</Track></Course></Courses></TrainingCenterDatabase>",
        encoding="utf-8",
    )
    return path


def _write_fit(folder: Path, elevations: list[float]) -> Path:
    from .test_fit_course_parser import write_fit_course

    return write_fit_course(folder / "course.fit", elevations, name="River Road")


@pytest.mark.parametrize("write_course", [_write_tcx, _write_fit], ids=["tcx", "fit"])
def test_tcx_and_fit_files_load_as_course_rides(session, tmp_path, write_course):
    s = session()

    s.load(write_course(tmp_path, _constant_grade(0.0, point_count=5)))

    assert s.state == EngineState.READY
    assert s.screen.title_label.text() == "River Road"
    assert s.controller.course_ride.course.total_distance_m == pytest.approx(
        4 * _POINT_SPACING_METERS, rel=1e-3
    )


@pytest.mark.parametrize("suffix", [".tcx", ".fit"])
def test_an_unreadable_tcx_or_fit_course_shows_an_alert_and_loads_nothing(session, tmp_path, suffix):
    s = session()
    path = tmp_path / f"broken{suffix}"
    path.write_text("not a course", encoding="utf-8")

    s.load(path)

    assert f"broken{suffix}" in s.screen.alert_label.text()
    assert s.controller.course_ride is None


def test_loading_a_gpx_file_asks_how_to_ride_it(session, tmp_path):
    asked: list[tuple[object, str]] = []

    def _chooser(course, units, parent):  # noqa: ARG001
        asked.append((course, units))
        return course

    s = session(settings=AppSettings(display_units="imperial"), course_chooser=_chooser)

    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=5), name="River Road"))

    assert len(asked) == 1
    assert asked[0][0].name == "River Road"
    assert asked[0][1] == "imperial"


def test_the_chosen_course_is_the_one_loaded(session, tmp_path):
    s = session(course_chooser=lambda course, units, parent: course.laps(3, name="River Road x3"))

    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=5), name="River Road"))

    assert s.state == EngineState.READY
    assert s.screen.title_label.text() == "River Road x3"
    assert s.controller.course_ride.course.total_distance_m == pytest.approx(
        12 * _POINT_SPACING_METERS, rel=1e-3
    )


def test_choosing_nothing_loads_nothing(session, tmp_path):
    s = session(course_chooser=lambda course, units, parent: None)

    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=5)))

    assert s.controller.course_ride is None
    assert s.controller.last_snapshot is None or s.state == EngineState.IDLE


def test_choosing_nothing_keeps_the_workout_already_loaded(session, tmp_path):
    s = session(course_chooser=lambda course, units, parent: None)
    s.load(DATA_DIR / "ramp.mrc")

    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=5)))

    assert s.controller.course_ride is None
    assert s.state == EngineState.READY
    assert s.screen.title_label.text() != "Test Course"


def test_course_ride_shows_grade_and_distance_remaining(session, tmp_path):
    s = session()

    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))

    assert s.screen.interval_remaining_tile.title_label.text() == "Grade"
    assert s.screen.interval_remaining_tile.value_label.text() == "+5.0 %"
    assert s.screen.remaining_tile.title_label.text() == "Distance Remaining"
    assert s.screen.remaining_tile.value_label.text() == "2.11 km"


def test_course_ride_selects_simulation_mode(session, tmp_path):
    s = session()

    s.load(_write_gpx(tmp_path, _constant_grade(2.0)))

    assert s.screen.mode_selector.currentText() == "Simulation"


def test_course_ride_shows_the_elevation_profile(session, tmp_path):
    s = session()

    s.load(_write_gpx(tmp_path, _constant_grade(2.0)))

    assert s.screen.chart_widget.course_plot_shown


def test_invalid_gpx_shows_an_alert_and_loads_nothing(session, tmp_path):
    s = session()
    path = tmp_path / "broken.gpx"
    path.write_text("<gpx><trk>", encoding="utf-8")

    s.load(path)

    assert "broken.gpx" in s.screen.alert_label.text()
    assert s.controller.course_ride is None
    assert s.controller.last_snapshot is None or s.state == EngineState.IDLE


def test_gpx_without_elevation_explains_why_it_cannot_be_ridden(session, tmp_path):
    s = session()
    path = tmp_path / "flat.gpx"
    path.write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="45.0" lon="7.0"/><trkpt lat="45.001" lon="7.0"/>'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )

    s.load(path)

    assert "elevation" in s.screen.alert_label.text()


def test_file_dialog_offers_workouts_and_courses(session, monkeypatch):
    s = session()
    offered: list[str] = []

    def _fake_dialog(parent, caption, directory, file_filter):  # noqa: ARG001
        offered.append(file_filter)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", _fake_dialog)

    s.screen.load_from_file_button.click()

    for pattern in ("*.gpx", "*.tcx", "*.fit", "*.mrc", "*.zwo"):
        assert pattern in offered[0]


def test_zwo_workout_loads_from_a_file(session):
    s = session()

    s.load(DATA_DIR / "steady.zwo")

    assert s.state == EngineState.READY
    assert s.controller.course_ride is None
    assert s.screen.title_widget.currentWidget() == s.screen.title_label


def test_loading_a_workout_after_a_course_leaves_course_mode(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(2.0)))

    s.load(DATA_DIR / "ramp.mrc")

    assert s.controller.course_ride is None
    assert s.screen.title_label.text() == "Ramp Session"
    assert s.screen.interval_remaining_tile.title_label.text() == _INTERVAL_TILE_TITLE
    assert s.screen.remaining_tile.title_label.text() == _REMAINING_TILE_TITLE
    assert s.screen.mode_selector.currentText() == "ERG"
    assert not s.screen.chart_widget.course_plot_shown
    assert s.screen.remaining_tile.value_label.text() != "—"


# ── Riding ────────────────────────────────────────────────────────────────────

def _pedal_without_ticks(s: _Session, seconds: float, watts: int = 180, rpm: float = 85.0) -> None:
    """Feed power and cadence readings at the tick rate, as the sensors would, with no ticks."""
    for _ in range(int(round(seconds / _TICK_SECONDS))):
        s.clock.now += _TICK_SECONDS
        s.controller.receive_cadence_rpm(rpm)
        s.controller.receive_power_watts(watts, s.clock.now)


def test_course_ride_starts_itself_after_three_seconds_of_pedaling(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))

    _pedal_without_ticks(s, 2.75)
    assert s.state == EngineState.READY

    _pedal_without_ticks(s, 0.5)
    assert s.state == EngineState.RUNNING


def test_pedaling_before_a_course_is_loaded_does_not_count_towards_starting_it(session, tmp_path):
    s = session()
    _pedal_without_ticks(s, 5.0)

    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    _pedal_without_ticks(s, 2.0)

    assert s.state == EngineState.READY


def test_pedaling_moves_the_rider_along_the_course(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()

    s.ride(20.0, 200)

    ride = s.controller.course_ride
    assert s.state == EngineState.RUNNING
    assert 50.0 < ride.distance_m < 250.0
    assert ride.speed_mps > 5.0
    expected_remaining_km = (ride.course.total_distance_m - ride.distance_m) / 1000.0
    assert s.screen.remaining_tile.value_label.text() == f"{expected_remaining_km:.2f} km"


def test_rider_and_bike_weight_slow_the_climb(session, tmp_path):
    gpx = _write_gpx(tmp_path, _constant_grade(8.0))
    light = session(settings=AppSettings(rider_weight_kg=60.0, bike_weight_kg=7.0))
    heavy = session(settings=AppSettings(rider_weight_kg=100.0, bike_weight_kg=12.0))
    for s in (light, heavy):
        s.load(gpx)
        s.start()
        s.ride(60.0, 250)

    assert heavy.controller.course_ride.distance_m < light.controller.course_ride.distance_m


def test_position_marker_follows_the_rider(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()

    s.ride(20.0, 200)

    assert s.screen.chart_widget.course_position_m == pytest.approx(
        s.controller.course_ride.distance_m
    )


def test_speed_and_distance_tiles_show_the_virtual_ride(session, tmp_path):
    s = session(settings=AppSettings(tile_selections=["speed", "distance"]))
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()

    s.ride(20.0, 200)

    ride = s.controller.course_ride
    assert s.screen._tile_by_key["speed"].value_label.text() == f"{ride.speed_mps * 3.6:.1f} km/h"
    assert s.screen._tile_by_key["distance"].value_label.text() == f"{ride.distance_m / 1000.0:.2f} km"


@pytest.mark.parametrize(("units", "metres_per_unit", "label"), [("metric", 1.0, "m"), ("imperial", 0.3048, "ft")])
def test_elevation_gain_tile_shows_the_climbing_done_and_still_to_come(session, tmp_path, units, metres_per_unit, label):
    import re

    s = session(settings=AppSettings(display_units=units, tile_selections=["elevation_gain"]))
    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))
    s.start()

    s.ride(60.0, 300)

    ride = s.controller.course_ride
    text = s.screen._tile_by_key["elevation_gain"].value_label.text()
    match = re.fullmatch(rf"(\d+) {label} · (\d+) {label} to go", text)
    assert match, text
    gained, to_go = (int(value) * metres_per_unit for value in match.groups())
    climbed_m = 0.05 * ride.distance_m
    assert climbed_m > 5.0
    assert gained == pytest.approx(climbed_m, abs=metres_per_unit)
    assert to_go == pytest.approx(0.05 * ride.course.total_distance_m - climbed_m, abs=metres_per_unit)


def test_recorded_speed_is_the_virtual_speed(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()

    s.ride(20.0, 200)

    recorded = [sample.speed_mps for sample in s.recorder.samples if sample.speed_mps is not None]
    assert recorded
    assert recorded[-1] == pytest.approx(s.controller.course_ride.speed_mps, rel=0.1)


def test_recorded_samples_place_the_rider_on_the_course(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))
    s.start()

    s.ride(20.0, 250)

    ride = s.controller.course_ride
    last = s.recorder.samples[-1]
    assert 0.0 < last.distance_m <= ride.distance_m
    assert last.altitude_m == pytest.approx(ride.course.elevation_at(last.distance_m), abs=0.01)
    assert last.grade_percent == pytest.approx(5.0, abs=0.01)
    assert 45.0 < last.latitude_deg < 45.019
    assert last.longitude_deg == pytest.approx(7.0)
    distances = [sample.distance_m for sample in s.recorder.samples]
    assert distances == sorted(distances)


def test_recorded_samples_number_the_course_lap_being_ridden(session, tmp_path):
    s = session(course_chooser=lambda course, units, parent: course.laps(3))
    # Laps of ~222 m: 45 s of riding crosses into the second lap but does not finish the course.
    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=3)))
    s.start()

    s.ride(45.0, 250)

    ride = s.controller.course_ride
    laps = [sample.lap_number for sample in s.recorder.samples]
    assert laps == sorted(laps)
    assert {1, 2} <= set(laps)
    assert laps[-1] == ride.course.lap_number_at(s.recorder.samples[-1].distance_m)


def test_recorded_samples_of_a_single_course_are_all_lap_one(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()

    s.ride(10.0, 250)

    assert {sample.lap_number for sample in s.recorder.samples} == {1}


def test_recorded_samples_have_no_course_fields_outside_a_course(session):
    s = session()
    s.load(DATA_DIR / "step_only.mrc")
    s.start()

    s.ride(5.0, 200)

    assert s.recorder.samples
    assert all(sample.distance_m is None for sample in s.recorder.samples)
    assert all(sample.latitude_deg is None for sample in s.recorder.samples)
    assert all(sample.lap_number is None for sample in s.recorder.samples)


def test_paused_course_ride_does_not_advance(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(20.0, 200)
    distance = s.controller.course_ride.distance_m

    s.screen.pause_button.click()
    for _ in range(40):
        s.clock.now += _TICK_SECONDS
        s.controller.process_tick(s.clock.now)

    assert s.state == EngineState.PAUSED
    assert s.controller.course_ride.distance_m == distance
    assert s.controller.course_ride.speed_mps == 0.0


def test_stopping_on_the_flat_auto_pauses(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(20.0, 200)

    s.ride(5.0, 0)

    assert s.state == EngineState.PAUSED


def test_coasting_down_a_descent_does_not_auto_pause(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(-8.0)))
    s.start()
    s.ride(10.0, 200)
    distance = s.controller.course_ride.distance_m

    s.ride(10.0, 0)

    assert s.state == EngineState.RUNNING
    assert s.controller.course_ride.distance_m > distance + 50.0


# ── Finishing ─────────────────────────────────────────────────────────────────

def test_reaching_the_end_of_the_course_finishes_the_ride(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0, point_count=2)))
    s.start()

    for _ in range(600):
        if s.summaries:
            break
        s.ride(_TICK_SECONDS, 250)

    assert len(s.summaries) == 1
    assert s.controller.course_ride is None
    assert s.screen.title_widget.currentWidget() == s.screen.load_buttons_widget
    assert not s.screen.chart_widget.course_plot_shown
    assert s.screen.interval_remaining_tile.title_label.text() == _INTERVAL_TILE_TITLE


def test_stopping_a_course_ride_early_leaves_course_mode(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(5.0, 200)

    s.screen.end_button.click()
    s.app.processEvents()

    assert len(s.summaries) == 1
    assert s.controller.course_ride is None
    assert s.screen.mode_selector.currentText() == "ERG"


def test_the_saved_ride_image_shows_the_course_map(monkeypatch, session, tmp_path):
    from opencycletrainer.storage.paths import get_workout_png_dir
    from opencycletrainer.ui import map_tiles

    from .test_chart_export import _TILE_MAGENTA, _Tiles, _columns_with, _pixels

    monkeypatch.setattr(map_tiles, "create_tile_provider", lambda source: _Tiles(source, hold_all=True))
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(5.0, 200)

    s.screen.end_button.click()
    s.app.processEvents()

    image = get_workout_png_dir(tmp_path) / "Course_20260311_1200.png"
    assert image.is_file()
    assert _columns_with(_pixels(image), _TILE_MAGENTA).size


def test_course_can_be_ridden_again_from_the_start(session, tmp_path):
    s = session()
    gpx = _write_gpx(tmp_path, _constant_grade(0.0))
    s.load(gpx)
    s.start()
    s.ride(10.0, 200)
    s.screen.end_button.click()
    s.app.processEvents()

    s.load(gpx)
    s.start()

    assert s.controller.course_ride.distance_m == 0.0
    assert s.state == EngineState.RUNNING


# ── Trainer control ───────────────────────────────────────────────────────────

def test_course_grade_is_sent_to_the_trainer(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)
    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))
    s.start()

    s.ride(2.0, 200)

    assert _wait_until(s.app, lambda: transport.simulation_grades()[-1:] == [5.0])


def test_road_is_flat_until_the_course_ride_starts(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)

    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))

    assert _wait_until(s.app, lambda: transport.simulation_grades()[-1:] == [0.0])


def test_trainer_difficulty_scales_the_grade_sent(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(settings=AppSettings(simulation_difficulty_percent=50), transport=transport)
    s.load(_write_gpx(tmp_path, _constant_grade(6.0)))
    s.start()

    s.ride(2.0, 200)

    assert _wait_until(s.app, lambda: transport.simulation_grades()[-1:] == [3.0])
    assert s.screen.interval_remaining_tile.value_label.text() == "+6.0 %"


def test_changing_trainer_difficulty_mid_ride_takes_effect(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)
    s.load(_write_gpx(tmp_path, _constant_grade(6.0)))
    s.start()
    s.ride(2.0, 200)

    s.controller.apply_settings(
        AppSettings(simulation_difficulty_percent=50, workout_data_dir=tmp_path)
    )
    s.ride(1.0, 200)

    assert _wait_until(s.app, lambda: transport.simulation_grades()[-1:] == [3.0])


def test_grade_follows_the_course_profile(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)
    climb_then_descent = [500.0, 500.0 + _POINT_SPACING_METERS * 0.06, 500.0]
    s.load(_write_gpx(tmp_path, climb_then_descent))
    s.start()

    for _ in range(2000):
        if s.summaries:
            break
        s.ride(_TICK_SECONDS, 250)

    assert _wait_until(s.app, lambda: min(transport.simulation_grades()) < -5.0)
    grades = transport.simulation_grades()
    assert max(grades) == pytest.approx(6.0, abs=0.1)
    assert min(grades) == pytest.approx(-6.0, abs=0.1)


def test_jog_adjusts_the_grade_in_simulation_mode(session):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)
    s.load(DATA_DIR / "step_only.mrc")
    s.screen.mode_selector.setCurrentText("Simulation")
    s.start()

    s.screen.jog_requested.emit(5)

    assert _wait_until(s.app, lambda: transport.simulation_grades()[-1:] == [2.5])
    assert s.screen.simulation_grade_label.text() == "Grade: +2.5 %"
    assert not s.screen.simulation_grade_label.isHidden()


def test_grade_label_is_hidden_outside_simulation_mode(session):
    s = session(transport=_FakeFTMSTransport())
    s.load(DATA_DIR / "step_only.mrc")

    assert s.screen.simulation_grade_label.isHidden()

    s.screen.mode_selector.setCurrentText("Simulation")

    assert not s.screen.simulation_grade_label.isHidden()
    assert s.screen.jog_offset_label.isHidden()

    s.screen.mode_selector.setCurrentText("ERG")

    assert s.screen.simulation_grade_label.isHidden()


def test_switching_a_course_ride_to_erg_holds_the_power_target(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)
    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))
    s.start()
    s.ride(2.0, 200)

    s.screen.mode_selector.setCurrentText("ERG")

    erg_100_watts = bytes([0x05]) + (100).to_bytes(2, "little", signed=True)
    assert _wait_until(s.app, lambda: transport.writes[-1:] == [erg_100_watts])


# ── Tiles outside a course ────────────────────────────────────────────────────

def test_speed_tile_shows_sensor_speed_outside_a_course(session):
    s = session(settings=AppSettings(tile_selections=["speed", "distance", "elevation_gain"]))
    s.load(DATA_DIR / "step_only.mrc")
    s.start()

    s.controller.receive_speed_mps(10.0)
    s.ride(1.0, 200)

    assert s.screen._tile_by_key["speed"].value_label.text() == "36.0 km/h"
    assert s.screen._tile_by_key["distance"].value_label.text() == "--"
    assert s.screen._tile_by_key["elevation_gain"].value_label.text() == "--"


def test_speed_tile_is_blank_without_a_speed_reading(session):
    s = session(settings=AppSettings(tile_selections=["speed"]))
    s.load(DATA_DIR / "step_only.mrc")
    s.start()

    s.ride(1.0, 200)

    assert s.screen._tile_by_key["speed"].value_label.text() == "--"


# ── Display units ─────────────────────────────────────────────────────────────

_METERS_PER_MILE = 1609.344
_MPH_PER_MPS = 3600.0 / _METERS_PER_MILE


def test_imperial_units_show_course_values_in_miles_and_mph(session, tmp_path):
    s = session(
        settings=AppSettings(display_units="imperial", tile_selections=["speed", "distance"])
    )
    s.load(_write_gpx(tmp_path, _constant_grade(5.0)))
    s.start()

    s.ride(20.0, 250)

    ride = s.controller.course_ride
    assert s.screen.remaining_tile.value_label.text() == f"{ride.remaining_m / _METERS_PER_MILE:.2f} mi"
    assert s.screen._tile_by_key["distance"].value_label.text() == f"{ride.distance_m / _METERS_PER_MILE:.2f} mi"
    assert s.screen._tile_by_key["speed"].value_label.text() == f"{ride.speed_mps * _MPH_PER_MPS:.1f} mph"
    assert s.screen.interval_remaining_tile.value_label.text() == "+5.0 %"


def test_imperial_units_label_the_elevation_profile_in_miles_and_feet(session, tmp_path):
    s = session(settings=AppSettings(display_units="imperial"))

    s.load(_write_gpx(tmp_path, _constant_grade(2.0)))

    course_plot = s.screen.chart_widget._course_plot
    assert course_plot.getAxis("bottom").labelText == "mi"
    assert course_plot.getAxis("left").labelText == "ft"


def test_switching_units_mid_ride_updates_the_course_values(session, tmp_path):
    s = session(settings=AppSettings(tile_selections=["speed"]))
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(10.0, 200)
    assert s.screen.remaining_tile.value_label.text().endswith(" km")

    imperial = AppSettings(
        display_units="imperial", tile_selections=["speed"], workout_data_dir=tmp_path
    )
    s.screen.apply_settings(imperial)
    s.controller.apply_settings(imperial)
    s.ride(1.0, 200)

    assert s.screen.remaining_tile.value_label.text().endswith(" mi")
    assert s.screen._tile_by_key["speed"].value_label.text().endswith(" mph")
    assert s.screen.chart_widget._course_plot.getAxis("bottom").labelText == "mi"


def test_switching_units_updates_a_loaded_course_before_it_starts(session, tmp_path):
    s = session(settings=AppSettings(tile_selections=["speed"]))
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    assert s.screen.remaining_tile.value_label.text().endswith(" km")

    imperial = AppSettings(
        display_units="imperial", tile_selections=["speed"], workout_data_dir=tmp_path
    )
    s.screen.apply_settings(imperial)
    s.controller.apply_settings(imperial)

    assert s.screen.remaining_tile.value_label.text().endswith(" mi")
    assert s.screen._tile_by_key["speed"].value_label.text().endswith(" mph")


def test_switching_units_mid_ride_updates_the_values_straight_away(session, tmp_path):
    s = session(settings=AppSettings(tile_selections=["speed"]))
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(10.0, 200)

    imperial = AppSettings(
        display_units="imperial", tile_selections=["speed"], workout_data_dir=tmp_path
    )
    s.screen.apply_settings(imperial)
    s.controller.apply_settings(imperial)

    assert s.screen.remaining_tile.value_label.text().endswith(" mi")
    assert s.screen._tile_by_key["speed"].value_label.text().endswith(" mph")


def test_switching_units_does_not_disturb_a_paused_course_ride(session, tmp_path):
    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(10.0, 200)
    s.screen.pause_button.click()
    distance = s.controller.course_ride.distance_m

    imperial = AppSettings(display_units="imperial", workout_data_dir=tmp_path)
    s.screen.apply_settings(imperial)
    s.controller.apply_settings(imperial)

    assert s.state == EngineState.PAUSED
    assert s.controller.course_ride.distance_m == distance
    assert s.screen.remaining_tile.value_label.text().endswith(" mi")


def test_recorded_course_values_stay_metric_with_imperial_units(session, tmp_path):
    s = session(settings=AppSettings(display_units="imperial"))
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()

    s.ride(20.0, 200)

    ride = s.controller.course_ride
    last = s.recorder.samples[-1]
    assert last.distance_m == pytest.approx(ride.distance_m, rel=0.1)
    assert last.speed_mps == pytest.approx(ride.speed_mps, rel=0.1)


def test_imperial_units_apply_to_sensor_speed_outside_a_course(session):
    s = session(settings=AppSettings(display_units="imperial", tile_selections=["speed"]))
    s.load(DATA_DIR / "step_only.mrc")
    s.start()

    s.controller.receive_speed_mps(10.0)
    s.ride(1.0, 200)

    assert s.screen._tile_by_key["speed"].value_label.text() == "22.4 mph"


# ── Road surface ──────────────────────────────────────────────────────────────

def _simulation_rolling_resistances(transport: _FakeFTMSTransport) -> list[float]:
    """Crr of every simulation command written so far."""
    return [
        struct.unpack("<BhhBB", write)[3] / 10000.0
        for write in list(transport.writes)
        if write[0] == _SIMULATION_OPCODE
    ]


def test_rougher_surface_slows_the_course_ride(session, tmp_path):
    gpx = _write_gpx(tmp_path, _constant_grade(0.0))
    smooth = session(settings=AppSettings(road_surface="smooth_road"))
    gravel = session(settings=AppSettings(road_surface="gravel"))
    for s in (smooth, gravel):
        s.load(gpx)
        s.start()
        s.ride(60.0, 200)

    assert gravel.controller.course_ride.distance_m < smooth.controller.course_ride.distance_m - 20.0


def test_selected_surface_is_sent_to_the_trainer(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(settings=AppSettings(road_surface="chipseal"), transport=transport)
    s.load(_write_gpx(tmp_path, _constant_grade(3.0)))
    s.start()

    s.ride(2.0, 200)

    assert _wait_until(s.app, lambda: transport.simulation_grades()[-1:] == [3.0])
    assert _simulation_rolling_resistances(transport)[-1] == 0.007


def test_changing_surface_mid_ride_takes_effect(session, tmp_path):
    transport = _FakeFTMSTransport()
    s = session(transport=transport)
    s.load(_write_gpx(tmp_path, _constant_grade(0.0)))
    s.start()
    s.ride(60.0, 200)
    smooth_speed = s.controller.course_ride.speed_mps

    s.controller.apply_settings(AppSettings(road_surface="gravel", workout_data_dir=tmp_path))
    s.ride(60.0, 200)

    assert s.state == EngineState.RUNNING
    assert s.controller.course_ride.speed_mps < smooth_speed - 0.5
    assert _wait_until(s.app, lambda: _simulation_rolling_resistances(transport)[-1:] == [0.012])


# ── Course chart settings ─────────────────────────────────────────────────────

def test_course_chart_uses_the_zoom_span_and_grade_colour_settings(session, tmp_path):
    s = session(settings=AppSettings(course_zoom_span=0.5, course_grade_colors=False))
    s.load(_write_gpx(tmp_path, _constant_grade(8.0)))
    chart = s.screen.chart_widget

    chart.course_zoom_button.click()

    (x_min, x_max), _ = chart._course_plot.getViewBox().viewRange()
    assert x_max - x_min == pytest.approx(500.0)
    steep, _ = chart._course_grade_items["steep"].getOriginalDataset()
    assert steep is None or len(steep) == 0


def test_changed_course_chart_settings_apply_to_the_course_shown(session, tmp_path):
    from dataclasses import replace

    s = session()
    s.load(_write_gpx(tmp_path, _constant_grade(8.0)))
    chart = s.screen.chart_widget
    chart.course_zoom_button.click()

    s.screen.apply_settings(replace(s.settings, course_zoom_span=2.0, course_grade_colors=False))

    (x_min, x_max), _ = chart._course_plot.getViewBox().viewRange()
    assert x_max - x_min == pytest.approx(2000.0)
    steep, _ = chart._course_grade_items["steep"].getOriginalDataset()
    assert steep is None or len(steep) == 0
