from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from opencycletrainer.core.fit_exporter import FitExporter, FitExportSample, JsonFitWriterBackend
from opencycletrainer.core.one_second_aggregator import OneSecondAggregator
from opencycletrainer.core.recorder import RecorderSample, WorkoutRecorder, to_fit_export_sample

_START = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
_FIT_SUB_SPORT_INDOOR_CYCLING = 6
_FIT_SUB_SPORT_VIRTUAL_ACTIVITY = 58


def _course_sample(second: float, **overrides) -> RecorderSample:
    """A recorder sample *second* seconds into a ride that climbs north at 10 m/s."""
    fields = dict(
        timestamp_utc=_START + timedelta(seconds=second),
        trainer_power_watts=200,
        speed_mps=10.0,
        distance_m=10.0 * second,
        altitude_m=100.0 + 0.5 * second,
        grade_percent=5.0,
        latitude_deg=45.0 + 0.0001 * second,
        longitude_deg=7.0,
    )
    fields.update(overrides)
    return RecorderSample(**fields)


# ── Aggregator ────────────────────────────────────────────────────────────────

def test_aggregator_keeps_the_last_course_reading_of_each_second():
    aggregator = OneSecondAggregator()
    aggregator.set_recording_active(True)

    aggregator.feed(_course_sample(0.1))
    aggregator.feed(_course_sample(0.6))
    completed = aggregator.feed(_course_sample(1.1))

    assert len(completed) == 1
    assert completed[0].distance_m == pytest.approx(6.0)
    assert completed[0].altitude_m == pytest.approx(100.3)
    assert completed[0].grade_percent == 5.0
    assert completed[0].latitude_deg == pytest.approx(45.00006)
    assert completed[0].longitude_deg == 7.0


def test_aggregator_leaves_course_fields_empty_outside_a_course():
    aggregator = OneSecondAggregator()
    aggregator.set_recording_active(True)

    aggregator.feed(RecorderSample(timestamp_utc=_START, heart_rate_bpm=140))
    completed = aggregator.feed(RecorderSample(timestamp_utc=_START + timedelta(seconds=1)))

    assert completed[0].distance_m is None
    assert completed[0].altitude_m is None
    assert completed[0].latitude_deg is None


def test_aggregator_does_not_carry_course_readings_into_the_next_second():
    aggregator = OneSecondAggregator()
    aggregator.set_recording_active(True)
    aggregator.feed(_course_sample(0.1))
    aggregator.feed(RecorderSample(timestamp_utc=_START + timedelta(seconds=1.1)))

    completed = aggregator.feed(RecorderSample(timestamp_utc=_START + timedelta(seconds=2.1)))

    assert completed[0].distance_m is None


# ── Recorder ──────────────────────────────────────────────────────────────────

def test_recorder_keeps_course_fields_in_samples_and_files(tmp_path):
    recorder = WorkoutRecorder(
        data_dir=tmp_path,
        flush_batch_size=1,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    recorder.start("Col", started_at_utc=_START)
    for second in range(3):
        recorder.record_sample(_course_sample(second))

    recorded = recorder.get_recorded_samples()
    summary = recorder.stop(finished_at_utc=_START + timedelta(seconds=3))

    assert recorded[2].distance_m == 20.0
    assert recorded[2].altitude_m == 101.0

    rows = [
        json.loads(line)
        for line in summary.samples_file_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[2]["distance_m"] == 20.0
    assert rows[2]["altitude_m"] == 101.0
    assert rows[2]["grade_percent"] == 5.0
    assert rows[2]["latitude_deg"] == pytest.approx(45.0002)
    assert rows[2]["longitude_deg"] == 7.0

    fit_records = json.loads(summary.fit_file_path.read_text(encoding="utf-8"))["records"]
    assert fit_records[2]["distance_m"] == 20.0
    assert fit_records[2]["altitude_m"] == 101.0
    assert fit_records[2]["latitude_deg"] == pytest.approx(45.0002)


def test_recorder_sample_converts_to_a_fit_sample_with_course_fields():
    fit_sample = to_fit_export_sample(_course_sample(4, bike_power_watts=210))

    assert fit_sample == FitExportSample(
        timestamp_utc=_START + timedelta(seconds=4),
        power_watts=210,
        speed_mps=10.0,
        distance_m=40.0,
        altitude_m=102.0,
        grade_percent=5.0,
        latitude_deg=pytest.approx(45.0004),
        longitude_deg=7.0,
    )


def test_fit_sample_conversion_falls_back_to_trainer_power():
    assert to_fit_export_sample(_course_sample(0)).power_watts == 200


# ── FIT export ────────────────────────────────────────────────────────────────

def _export(tmp_path, samples: list[FitExportSample]):
    """Write *samples* with the real FIT backend and return the decoded messages."""
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile

    fit_path = tmp_path / "course.fit"
    FitExporter().export_activity(
        workout_name="Col",
        started_at_utc=_START,
        finished_at_utc=_START + timedelta(seconds=len(samples)),
        fit_file_path=fit_path,
        samples=samples,
    )
    fit_file = FitFile.from_file(str(fit_path))
    return [record.message for record in fit_file.records if record.message is not None]


def test_fit_records_carry_course_position_distance_altitude_and_grade(tmp_path):
    from fit_tool.profile.messages.record_message import RecordMessage

    samples = [to_fit_export_sample(_course_sample(second)) for second in range(4)]

    messages = _export(tmp_path, samples)

    records = [message for message in messages if isinstance(message, RecordMessage)]
    assert len(records) == 4
    assert records[3].distance == pytest.approx(30.0, abs=0.01)
    assert records[3].altitude == pytest.approx(101.5, abs=0.2)
    assert records[3].grade == pytest.approx(5.0, abs=0.01)
    assert records[3].position_lat == pytest.approx(45.0003, abs=1e-6)
    assert records[3].position_long == pytest.approx(7.0, abs=1e-6)
    assert records[3].speed == pytest.approx(10.0, abs=0.001)


def test_fit_session_totals_cover_the_course_ridden(tmp_path):
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.session_message import SessionMessage

    samples = [
        to_fit_export_sample(_course_sample(second, altitude_m=altitude))
        for second, altitude in enumerate([100.0, 104.0, 102.0, 109.0])
    ]

    messages = _export(tmp_path, samples)

    session = next(message for message in messages if isinstance(message, SessionMessage))
    lap = next(message for message in messages if isinstance(message, LapMessage))
    assert session.total_distance == pytest.approx(30.0, abs=0.01)
    assert lap.total_distance == pytest.approx(30.0, abs=0.01)
    assert session.total_ascent == 11
    assert session.total_descent == 2


def test_fit_session_is_a_virtual_ride_when_it_has_positions(tmp_path):
    from fit_tool.profile.messages.session_message import SessionMessage

    samples = [to_fit_export_sample(_course_sample(second)) for second in range(3)]

    messages = _export(tmp_path, samples)

    session = next(message for message in messages if isinstance(message, SessionMessage))
    assert session.sub_sport == _FIT_SUB_SPORT_VIRTUAL_ACTIVITY


def test_fit_session_stays_indoor_cycling_without_a_course(tmp_path):
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.messages.session_message import SessionMessage

    samples = [
        FitExportSample(timestamp_utc=_START + timedelta(seconds=second), power_watts=200)
        for second in range(3)
    ]

    messages = _export(tmp_path, samples)

    session = next(message for message in messages if isinstance(message, SessionMessage))
    records = [message for message in messages if isinstance(message, RecordMessage)]
    assert session.sub_sport == _FIT_SUB_SPORT_INDOOR_CYCLING
    assert session.total_distance is None
    assert records[0].position_lat is None
    assert records[0].distance is None
