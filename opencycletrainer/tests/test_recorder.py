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


def _sample(ts: datetime, *, trainer: int | None = None, bike: int | None = None) -> RecorderSample:
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
