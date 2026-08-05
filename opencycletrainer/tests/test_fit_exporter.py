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


def test_fit_exporter_json_backend_writes_dfa_alpha1_per_record():
    """JsonFitWriterBackend records carry dfa_alpha1 (null when absent), keeping
    FIT-export tests deterministic without needing the real fit_tool developer
    field path (spec [9])."""
    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_dfa_20260310_1842.fit"
    exporter = FitExporter(writer_backend=JsonFitWriterBackend())
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    samples = [
        FitExportSample(timestamp_utc=start_time, power_watts=250, dfa_alpha1=0.81),
        FitExportSample(timestamp_utc=start_time + timedelta(seconds=1), power_watts=252),
    ]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=start_time + timedelta(seconds=2),
        fit_file_path=fit_path,
        samples=samples,
    )

    payload = json.loads(fit_path.read_text(encoding="utf-8"))
    assert payload["records"][0]["dfa_alpha1"] == pytest.approx(0.81)
    assert payload["records"][1]["dfa_alpha1"] is None


def test_fit_exporter_real_backend_writes_dfa_alpha1_developer_field_when_present():
    """When any sample carries dfa_alpha1, the real backend writes a developer
    data field (DeveloperDataIdMessage + FieldDescriptionMessage) and each
    RecordMessage with a value round-trips it (spec [9])."""
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.developer_data_id_message import DeveloperDataIdMessage
    from fit_tool.profile.messages.field_description_message import FieldDescriptionMessage
    from fit_tool.profile.messages.record_message import RecordMessage

    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_devfield_20260310_1842.fit"
    exporter = FitExporter()
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    samples = [
        FitExportSample(timestamp_utc=start_time, power_watts=250, dfa_alpha1=0.81),
        FitExportSample(
            timestamp_utc=start_time + timedelta(seconds=1),
            power_watts=252,
            dfa_alpha1=None,
        ),
        FitExportSample(
            timestamp_utc=start_time + timedelta(seconds=2),
            power_watts=255,
            dfa_alpha1=0.77,
        ),
    ]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=start_time + timedelta(seconds=3),
        fit_file_path=fit_path,
        samples=samples,
    )

    fit_file = FitFile.from_file(str(fit_path))
    messages = [rec.message for rec in fit_file.records if rec.message is not None]

    dev_id_messages = [m for m in messages if isinstance(m, DeveloperDataIdMessage)]
    field_desc_messages = [m for m in messages if isinstance(m, FieldDescriptionMessage)]
    assert len(dev_id_messages) == 1
    assert len(field_desc_messages) == 1
    assert field_desc_messages[0].field_name == "dfa_alpha1"

    record_messages = [m for m in messages if isinstance(m, RecordMessage)]
    assert len(record_messages) == 3

    dev_field_0 = record_messages[0].get_developer_field_by_name("dfa_alpha1")
    assert dev_field_0 is not None
    assert dev_field_0.get_values()[0] == pytest.approx(0.81, abs=1e-4)

    dev_field_1 = record_messages[1].get_developer_field_by_name("dfa_alpha1")
    assert dev_field_1 is None

    dev_field_2 = record_messages[2].get_developer_field_by_name("dfa_alpha1")
    assert dev_field_2 is not None
    assert dev_field_2.get_values()[0] == pytest.approx(0.77, abs=1e-4)


def test_fit_exporter_real_backend_skips_dfa_developer_field_when_all_none():
    """No DeveloperDataIdMessage/FieldDescriptionMessage is emitted when every
    sample's dfa_alpha1 is None — an empty field description must not be
    written (spec [9])."""
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.developer_data_id_message import DeveloperDataIdMessage
    from fit_tool.profile.messages.field_description_message import FieldDescriptionMessage

    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_nodev_20260310_1842.fit"
    exporter = FitExporter()
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    samples = [
        FitExportSample(timestamp_utc=start_time, power_watts=250),
        FitExportSample(timestamp_utc=start_time + timedelta(seconds=1), power_watts=252),
    ]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=start_time + timedelta(seconds=2),
        fit_file_path=fit_path,
        samples=samples,
    )

    fit_file = FitFile.from_file(str(fit_path))
    messages = [rec.message for rec in fit_file.records if rec.message is not None]
    assert not [m for m in messages if isinstance(m, DeveloperDataIdMessage)]
    assert not [m for m in messages if isinstance(m, FieldDescriptionMessage)]


def test_fit_exporter_real_backend_survives_dfa_developer_field_failure(monkeypatch):
    """Best-effort: if the developer-field setup raises for any reason, the FIT
    export must still succeed with all standard fields intact (spec [9])."""
    pytest.importorskip("fit_tool")
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.record_message import RecordMessage

    import opencycletrainer.core.fit_exporter as fit_exporter_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated developer-field setup failure")

    monkeypatch.setattr(fit_exporter_module, "_add_dfa_developer_field_definitions", _boom)

    data_dir = _test_data_dir()
    fit_path = data_dir / "Threshold_devfail_20260310_1842.fit"
    exporter = FitExporter()
    start_time = datetime(2026, 3, 10, 18, 42, 0, tzinfo=timezone.utc)
    samples = [
        FitExportSample(
            timestamp_utc=start_time,
            power_watts=250,
            heart_rate_bpm=148,
            dfa_alpha1=0.81,
        ),
    ]

    exporter.export_activity(
        workout_name="Threshold",
        started_at_utc=start_time,
        finished_at_utc=start_time + timedelta(seconds=1),
        fit_file_path=fit_path,
        samples=samples,
    )

    assert fit_path.exists()
    fit_file = FitFile.from_file(str(fit_path))
    record_messages = [
        rec.message for rec in fit_file.records if isinstance(rec.message, RecordMessage)
    ]
    assert len(record_messages) == 1
    assert record_messages[0].power == 250
    assert record_messages[0].heart_rate == 148


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
