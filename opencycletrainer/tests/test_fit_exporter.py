from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opencycletrainer.core.fit_exporter import FitExportSample, FitExporter, JsonFitWriterBackend


def _test_data_dir() -> Path:
    path = Path.cwd() / ".tmp_runtime" / "fit_exporter_tests"
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_fit_exporter_json_backend_writes_expected_records():
    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_20260310_1842.fit"
    exporter = FitExporter(writer_backend=JsonFitWriterBackend())
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    samples = [
        FitExportSample(
            timestamp_utc=start_time,
            power_watts=250,
            heart_rate_bpm=148,
            cadence_rpm=89.8,
            speed_mps=10.4,
        ),
        FitExportSample(
            timestamp_utc=start_time + timedelta(seconds=1),
            power_watts=252,
            heart_rate_bpm=149,
            cadence_rpm=90.2,
            speed_mps=10.5,
        ),
    ]

    output_path = exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=start_time + timedelta(seconds=2),
        fit_file_path=fit_path,
        samples=samples,
    )

    assert output_path == fit_path
    assert fit_path.exists()

    payload = json.loads(fit_path.read_text(encoding="utf-8"))
    assert payload["workout_name"] == "Threshold"
    assert payload["started_at_utc"] == "2026-03-10T18:42:00Z"
    assert len(payload["records"]) == 2
    assert payload["records"][0]["power_watts"] == 250
    assert payload["records"][0]["heart_rate_bpm"] == 148
    assert payload["records"][0]["cadence_rpm"] == pytest.approx(89.8)


def test_fit_exporter_real_backend_creates_fit_when_fit_tool_is_installed():
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.record_message import RecordMessage

    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_20260310_1842.fit"
    exporter = FitExporter()
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    finish_time = start_time + timedelta(seconds=2)
    samples = [
        FitExportSample(
            timestamp_utc=start_time,
            power_watts=250,
            heart_rate_bpm=148,
            cadence_rpm=90.0,
        ),
        FitExportSample(
            timestamp_utc=start_time + timedelta(seconds=1),
            power_watts=255,
            heart_rate_bpm=150,
            cadence_rpm=91.0,
        ),
    ]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=finish_time,
        fit_file_path=fit_path,
        samples=samples,
    )

    assert fit_path.exists()
    assert fit_path.stat().st_size > 0

    fit_file = FitFile.from_file(str(fit_path))
    record_messages = [
        rec.message
        for rec in fit_file.records
        if isinstance(getattr(rec, "message", None), RecordMessage)
    ]
    assert len(record_messages) == 2
    assert record_messages[0].power == 250
    assert record_messages[0].heart_rate == 148
    assert record_messages[0].cadence == 90
    assert record_messages[0].timestamp == int(start_time.timestamp() * 1000)
    assert record_messages[1].timestamp == int((start_time + timedelta(seconds=1)).timestamp() * 1000)


def test_fit_exporter_activity_message_has_local_timestamp():
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.activity_message import ActivityMessage

    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_localtimestamp_20260310_1842.fit"
    exporter = FitExporter()
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    finish_time = start_time + timedelta(seconds=3600)
    samples = [FitExportSample(timestamp_utc=start_time, power_watts=250)]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=finish_time,
        fit_file_path=fit_path,
        samples=samples,
    )

    fit_file = FitFile.from_file(str(fit_path))
    messages = [rec.message for rec in fit_file.records if rec.message is not None]
    activity_messages = [m for m in messages if isinstance(m, ActivityMessage)]
    assert len(activity_messages) == 1

    _FIT_EPOCH_OFFSET_SECONDS = 631065600
    utc_offset_s = int(finish_time.astimezone().utcoffset().total_seconds())
    expected_local_ts = int(finish_time.timestamp()) + utc_offset_s - _FIT_EPOCH_OFFSET_SECONDS
    assert activity_messages[0].local_timestamp == expected_local_ts


def test_fit_exporter_real_backend_includes_lap_session_activity_messages():
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.activity_message import ActivityMessage
    from fit_tool.profile.messages.lap_message import LapMessage
    from fit_tool.profile.messages.session_message import SessionMessage

    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_structure_20260310_1842.fit"
    exporter = FitExporter()
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    finish_time = start_time + timedelta(seconds=3600)
    samples = [
        FitExportSample(
            timestamp_utc=start_time + timedelta(seconds=i),
            power_watts=250,
        )
        for i in range(3)
    ]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=finish_time,
        fit_file_path=fit_path,
        samples=samples,
    )

    fit_file = FitFile.from_file(str(fit_path))
    messages = [rec.message for rec in fit_file.records if rec.message is not None]

    lap_messages = [m for m in messages if isinstance(m, LapMessage)]
    session_messages = [m for m in messages if isinstance(m, SessionMessage)]
    activity_messages = [m for m in messages if isinstance(m, ActivityMessage)]

    assert len(lap_messages) == 1, "Expected exactly one LapMessage"
    assert len(session_messages) == 1, "Expected exactly one SessionMessage"
    assert len(activity_messages) == 1, "Expected exactly one ActivityMessage"

    expected_elapsed = 3600.0
    assert lap_messages[0].total_elapsed_time == pytest.approx(expected_elapsed)
    assert session_messages[0].total_elapsed_time == pytest.approx(expected_elapsed)
    assert session_messages[0].num_laps == 1
    assert activity_messages[0].num_sessions == 1
