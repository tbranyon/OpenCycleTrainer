from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opencycletrainer.core.fit_exporter import FitExporter, FitExportSample, JsonFitWriterBackend
from opencycletrainer.core.recorder import RecorderSample, WorkoutRecorder


class _FailingFitWriterBackend:
    """Writer backend that always raises, used to test graceful FIT failure handling."""

    def write_activity(
        self,
        *,
        workout_name: str,
        started_at_utc: object,
        fit_file_path: object,
        samples: list[FitExportSample],
    ) -> None:
        raise RuntimeError("simulated FIT write failure")


def _test_data_dir() -> Path:
    path = Path.cwd() / ".tmp_runtime" / "recorder_tests"
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sample(
    ts: datetime,
    *,
    trainer: int | None = None,
    bike: int | None = None,
    dfa_alpha1: float | None = None,
    dfa_quality: str | None = None,
) -> RecorderSample:
    return RecorderSample(
        timestamp_utc=ts,
        target_power_watts=200,
        trainer_power_watts=trainer,
        bike_power_watts=bike,
        heart_rate_bpm=150,
        cadence_rpm=90.0,
        speed_mps=10.2,
        mode="ERG",
        erg_setpoint_watts=210,
        total_kj=12.0,
        dfa_alpha1=dfa_alpha1,
        dfa_quality=dfa_quality,
    )


def test_recorder_logs_at_1hz_and_writes_summary_with_matching_fit_stem():
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=2,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)

    session = recorder.start("Threshold", started_at_utc=start_time)

    accepted_0 = recorder.record_sample(_sample(start_time, trainer=200))
    accepted_half = recorder.record_sample(_sample(start_time + timedelta(milliseconds=500), trainer=999))
    accepted_1 = recorder.record_sample(_sample(start_time + timedelta(seconds=1), trainer=220))
    accepted_2 = recorder.record_sample(_sample(start_time + timedelta(seconds=2, milliseconds=100), trainer=240))

    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=3))

    assert accepted_0 is True
    assert accepted_half is False
    assert accepted_1 is True
    assert accepted_2 is True

    assert summary.fit_file_path.stem == summary.summary_file_path.stem
    assert summary.fit_file_path.stem == session.fit_file_path.stem
    assert summary.fit_file_path.parent == data_dir / "FIT"
    assert summary.samples_file_path.parent == data_dir / "JSON"
    assert summary.summary_file_path.parent == data_dir / "JSON"
    assert (data_dir / "png").is_dir()
    assert summary.fit_file_path.exists()
    assert summary.sample_count == 3
    assert summary.duration_seconds == 3
    assert summary.avg_power_watts == pytest.approx(220.0)

    fit_payload = json.loads(summary.fit_file_path.read_text(encoding="utf-8"))
    assert fit_payload["workout_name"] == "Threshold"
    assert len(fit_payload["records"]) == 3
    assert fit_payload["records"][0]["timestamp_utc"] == "2026-03-10T18:42:00Z"
    assert fit_payload["records"][0]["power_watts"] == 200
    assert fit_payload["records"][0]["heart_rate_bpm"] == 150
    assert fit_payload["records"][0]["cadence_rpm"] == pytest.approx(90.0)

    summary_payload = json.loads(summary.summary_file_path.read_text(encoding="utf-8"))
    assert summary_payload["workout_name"] == "Threshold"
    assert summary_payload["start_time_utc"] == "2026-03-10T18:42:00Z"
    assert summary_payload["duration_seconds"] == 3
    assert summary_payload["avg_power_watts"] == pytest.approx(220.0)

    raw_lines = summary.samples_file_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw_lines) == 3
    first_row = json.loads(raw_lines[0])
    assert first_row["timestamp_utc"] == "2026-03-10T18:42:00Z"
    assert first_row["trainer_power_watts"] == 200


def test_recorder_uses_bike_power_when_available_for_avg_power():
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 3, 10, 19, 0, 0, tzinfo=timezone.utc)

    recorder.start("BikePM Priority", started_at_utc=start_time)
    recorder.record_sample(_sample(start_time, trainer=180, bike=200))
    recorder.record_sample(_sample(start_time + timedelta(seconds=1), trainer=200, bike=220))
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=2))

    assert summary.sample_count == 2
    assert summary.avg_power_watts == pytest.approx(210.0)


def test_recorder_can_pause_and_resume_sampling_via_recording_active_flag():
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 3, 10, 20, 0, 0, tzinfo=timezone.utc)

    recorder.start("Pause Resume", started_at_utc=start_time)
    assert recorder.recording_enabled is True

    accepted_running = recorder.record_sample(_sample(start_time, trainer=210))
    recorder.set_recording_active(False)
    accepted_paused = recorder.record_sample(_sample(start_time + timedelta(seconds=1), trainer=215))
    recorder.set_recording_active(True)
    accepted_resumed = recorder.record_sample(_sample(start_time + timedelta(seconds=2), trainer=220))
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=3))

    assert accepted_running is True
    assert accepted_paused is False
    assert accepted_resumed is True
    assert summary.sample_count == 2


def test_recorder_accepts_pre_aggregated_1s_stream_without_dropping_records():
    """Each pre-aggregated 1-second sample must be accepted; the recorder's <1s gate
    must not drop samples whose timestamps are exactly 1 second apart."""
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=10,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 4, 15, 8, 0, 0, tzinfo=timezone.utc)

    recorder.start("Pre-aggregated Stream", started_at_utc=start_time)
    # Feed exactly 1-second-apart samples as an aggregator would produce.
    results = [
        recorder.record_sample(_sample(start_time + timedelta(seconds=i), trainer=200 + i * 5))
        for i in range(5)
    ]
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=5))

    assert all(results), "Every pre-aggregated sample must be accepted"
    assert summary.sample_count == 5
    assert summary.avg_power_watts == pytest.approx(210.0)


def test_recorder_fit_power_uses_bike_first_with_trainer_fallback_on_dropout():
    """FIT power follows bike-first policy; when bike is absent a sample uses trainer."""
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 4, 15, 9, 0, 0, tzinfo=timezone.utc)

    recorder.start("Dropout Test", started_at_utc=start_time)
    # Sample 1: bike present → FIT uses bike (215)
    recorder.record_sample(_sample(start_time, trainer=200, bike=215))
    # Sample 2: bike absent (dropout) → FIT falls back to trainer (200)
    recorder.record_sample(_sample(start_time + timedelta(seconds=1), trainer=200, bike=None))
    # Sample 3: bike returns → FIT uses bike (215)
    recorder.record_sample(_sample(start_time + timedelta(seconds=2), trainer=200, bike=215))
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=3))

    fit_payload = json.loads(summary.fit_file_path.read_text(encoding="utf-8"))
    records = fit_payload["records"]
    assert records[0]["power_watts"] == 215  # bike present
    assert records[1]["power_watts"] == 200  # bike absent → trainer fallback
    assert records[2]["power_watts"] == 215  # bike back

    # avg = (215 + 200 + 215) / 3 = 210
    assert summary.avg_power_watts == pytest.approx(210.0)


def test_recorder_writes_dfa_alpha1_and_quality_into_jsonl_row():
    """A sample carrying dfa_alpha1/dfa_quality writes both into the JSONL row;
    a sample without them writes null for both (spec [9])."""
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    recorder.start("DFA Row", started_at_utc=start_time)
    recorder.record_sample(
        _sample(start_time, trainer=200, dfa_alpha1=0.81, dfa_quality="good")
    )
    recorder.record_sample(_sample(start_time + timedelta(seconds=1), trainer=200))
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=2))

    raw_lines = summary.samples_file_path.read_text(encoding="utf-8").strip().splitlines()
    rows = [json.loads(line) for line in raw_lines]
    assert rows[0]["dfa_alpha1"] == pytest.approx(0.81)
    assert rows[0]["dfa_quality"] == "good"
    assert rows[1]["dfa_alpha1"] is None
    assert rows[1]["dfa_quality"] is None


def test_recorder_sample_dfa_fields_round_trip_from_row():
    """A JSONL row's dfa_alpha1/dfa_quality map directly onto RecorderSample kwargs
    and preserve their value when reconstructed."""
    original = _sample(
        datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc),
        trainer=210,
        dfa_alpha1=0.77,
        dfa_quality="degraded",
    )
    row = WorkoutRecorder._sample_to_row(original)

    reconstructed = RecorderSample(
        timestamp_utc=original.timestamp_utc,
        target_power_watts=row["target_power_watts"],
        trainer_power_watts=row["trainer_power_watts"],
        bike_power_watts=row["bike_power_watts"],
        heart_rate_bpm=row["heart_rate_bpm"],
        cadence_rpm=row["cadence_rpm"],
        speed_mps=row["speed_mps"],
        mode=row["mode"],
        erg_setpoint_watts=row["erg_setpoint_watts"],
        total_kj=row["total_kj"],
        dfa_alpha1=row["dfa_alpha1"],
        dfa_quality=row["dfa_quality"],
    )

    assert reconstructed.dfa_alpha1 == pytest.approx(0.77)
    assert reconstructed.dfa_quality == "degraded"


def test_recorder_row_missing_dfa_alpha1_key_parses_as_none():
    """A row written by an older format (no dfa_alpha1/dfa_quality keys) still
    parses with None for both, so old .samples.jsonl files remain readable."""
    old_format_row = {
        "timestamp_utc": "2026-05-01T09:00:00Z",
        "target_power_watts": 200,
        "trainer_power_watts": 210,
        "bike_power_watts": None,
        "heart_rate_bpm": 150,
        "cadence_rpm": 90.0,
        "speed_mps": 10.2,
        "mode": "ERG",
        "erg_setpoint_watts": 210,
        "total_kj": 12.0,
    }

    reconstructed = RecorderSample(
        timestamp_utc=datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc),
        target_power_watts=old_format_row["target_power_watts"],
        trainer_power_watts=old_format_row["trainer_power_watts"],
        bike_power_watts=old_format_row["bike_power_watts"],
        heart_rate_bpm=old_format_row["heart_rate_bpm"],
        cadence_rpm=old_format_row["cadence_rpm"],
        speed_mps=old_format_row["speed_mps"],
        mode=old_format_row["mode"],
        erg_setpoint_watts=old_format_row["erg_setpoint_watts"],
        total_kj=old_format_row["total_kj"],
        dfa_alpha1=old_format_row.get("dfa_alpha1"),
        dfa_quality=old_format_row.get("dfa_quality"),
    )

    assert reconstructed.dfa_alpha1 is None
    assert reconstructed.dfa_quality is None


def test_recorder_forward_fills_dfa_alpha1_from_pull_model_across_1hz_samples():
    """WorkoutRecorder is a dumb sink: forward-fill is implicit when the caller
    pulls dfa_alpha1 from a source that itself holds the latest value between
    5 s pipeline emits (e.g. DfaPipeline.latest_record), the same way HR/cadence/
    power already reach RecorderSample. This exercises that pull-model pattern
    end to end through the JSONL row."""
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=10,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Simulates a pipeline emitting every ~3 ticks: None until the window fills,
    # then the latest emitted value is carried forward until the next emit.
    latest_alpha1_by_tick = [None, None, None, 0.81, 0.81, 0.81, 0.77, 0.77]

    recorder.start("DFA Forward Fill", started_at_utc=start_time)
    for i, alpha1 in enumerate(latest_alpha1_by_tick):
        quality = None if alpha1 is None else "good"
        recorder.record_sample(
            _sample(
                start_time + timedelta(seconds=i),
                trainer=200,
                dfa_alpha1=alpha1,
                dfa_quality=quality,
            )
        )
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=len(latest_alpha1_by_tick)))

    raw_lines = summary.samples_file_path.read_text(encoding="utf-8").strip().splitlines()
    rows = [json.loads(line) for line in raw_lines]
    assert [row["dfa_alpha1"] for row in rows] == latest_alpha1_by_tick
    assert [row["dfa_quality"] for row in rows] == [
        None if alpha1 is None else "good" for alpha1 in latest_alpha1_by_tick
    ]


def test_recorder_resume_cannot_emit_duplicate_utc_second():
    """set_recording_active(True) resets the <1s timestamp gate so the recorder
    can accept a sample immediately after resume. That reset must not let a
    UTC second already recorded pre-pause be recorded a second time."""
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)

    recorder.start("Resume Dedup", started_at_utc=start_time)
    accepted_first = recorder.record_sample(_sample(start_time, trainer=200))
    recorder.set_recording_active(False)
    recorder.set_recording_active(True)  # resets the <1s gate
    # Same UTC second as the sample already recorded pre-pause.
    duplicate_accepted = recorder.record_sample(_sample(start_time, trainer=999))
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=1))

    assert accepted_first is True
    assert duplicate_accepted is False
    assert summary.sample_count == 1


def test_recorder_resume_accepts_a_genuinely_new_second():
    """The duplicate-second guard must not block legitimate resume behaviour:
    a second after the last-recorded one is still accepted post-resume."""
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
    )
    start_time = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)

    recorder.start("Resume Ok", started_at_utc=start_time)
    recorder.record_sample(_sample(start_time, trainer=200))
    recorder.set_recording_active(False)
    recorder.set_recording_active(True)
    accepted = recorder.record_sample(
        _sample(start_time + timedelta(seconds=5), trainer=210)
    )
    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=6))

    assert accepted is True
    assert summary.sample_count == 2


def test_recorder_stop_completes_gracefully_when_fit_export_fails():
    data_dir = _test_data_dir()
    recorder = WorkoutRecorder(
        data_dir=data_dir,
        flush_batch_size=5,
        fit_exporter=FitExporter(writer_backend=_FailingFitWriterBackend()),
    )
    start_time = datetime(2026, 3, 10, 22, 0, 0, tzinfo=timezone.utc)

    recorder.start("FIT Fail Test", started_at_utc=start_time)
    recorder.record_sample(_sample(start_time, trainer=200))
    recorder.record_sample(_sample(start_time + timedelta(seconds=1), trainer=210))

    summary = recorder.stop(finished_at_utc=start_time + timedelta(seconds=2))

    assert summary.sample_count == 2
    assert not summary.fit_file_path.exists()
    assert summary.summary_file_path.exists()
    summary_payload = json.loads(summary.summary_file_path.read_text(encoding="utf-8"))
    assert summary_payload["sample_count"] == 2
