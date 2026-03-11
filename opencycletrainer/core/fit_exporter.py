from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from opencycletrainer.storage.paths import ensure_dir


@dataclass(frozen=True)
class FitExportSample:
    timestamp_utc: datetime
    power_watts: int | None = None
    heart_rate_bpm: int | None = None
    cadence_rpm: float | None = None
    speed_mps: float | None = None


class FitWriterBackend(Protocol):
    def write_activity(
        self,
        *,
        workout_name: str,
        started_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> None: ...


class FitExporter:
    """Exports recorder samples to FIT files."""

    def __init__(self, *, writer_backend: FitWriterBackend | None = None) -> None:
        self._writer_backend = writer_backend if writer_backend is not None else _FitToolWriterBackend()

    def export_activity(
        self,
        *,
        workout_name: str,
        started_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> Path:
        ensure_dir(fit_file_path.parent)
        normalized_start = _normalize_utc(started_at_utc)
        normalized_samples = [
            FitExportSample(
                timestamp_utc=_normalize_utc(sample.timestamp_utc),
                power_watts=sample.power_watts,
                heart_rate_bpm=sample.heart_rate_bpm,
                cadence_rpm=sample.cadence_rpm,
                speed_mps=sample.speed_mps,
            )
            for sample in samples
        ]
        self._writer_backend.write_activity(
            workout_name=workout_name,
            started_at_utc=normalized_start,
            fit_file_path=fit_file_path,
            samples=normalized_samples,
        )
        return fit_file_path


class _FitToolWriterBackend:
    def write_activity(
        self,
        *,
        workout_name: str,
        started_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> None:
        try:
            from fit_tool.fit_file_builder import FitFileBuilder
            from fit_tool.profile.messages.file_id_message import FileIdMessage
            from fit_tool.profile.messages.record_message import RecordMessage
            from fit_tool.profile.profile_type import FileType, Manufacturer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "fit-tool is required for FIT export. Install it with `pip install fit-tool`.",
            ) from exc

        builder = FitFileBuilder(auto_define=True, min_string_size=50)

        file_id = FileIdMessage()
        _set_field(file_id, ("type",), getattr(FileType, "ACTIVITY", FileType.COURSE))
        _set_field(file_id, ("manufacturer",), _enum_value(getattr(Manufacturer, "DEVELOPMENT", 0)))
        _set_field(file_id, ("product",), 0)
        _set_field(file_id, ("serial_number", "serialNumber"), 0x0C0FFEE)
        _set_field(file_id, ("time_created", "timeCreated"), _to_fit_timestamp_ms(started_at_utc))
        builder.add(file_id)

        for sample in samples:
            record = RecordMessage()
            _set_field(record, ("timestamp",), _to_fit_timestamp_ms(sample.timestamp_utc))
            if sample.power_watts is not None:
                _set_field(record, ("power",), int(sample.power_watts))
            if sample.heart_rate_bpm is not None:
                _set_field(record, ("heart_rate", "heartRate"), int(sample.heart_rate_bpm))
            if sample.cadence_rpm is not None:
                _set_field(record, ("cadence",), int(round(sample.cadence_rpm)))
            if sample.speed_mps is not None:
                _set_field(record, ("speed",), float(sample.speed_mps))
            builder.add(record)

        fit_file = builder.build()
        fit_file.to_file(str(fit_file_path))


class JsonFitWriterBackend:
    """
    Test backend that writes a JSON payload at a .fit path.

    This backend is intended for deterministic tests when fit-tool is unavailable.
    """

    def write_activity(
        self,
        *,
        workout_name: str,
        started_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> None:
        payload = {
            "workout_name": workout_name,
            "started_at_utc": _normalize_utc(started_at_utc).isoformat().replace("+00:00", "Z"),
            "records": [
                {
                    "timestamp_utc": _normalize_utc(sample.timestamp_utc).isoformat().replace("+00:00", "Z"),
                    "power_watts": sample.power_watts,
                    "heart_rate_bpm": sample.heart_rate_bpm,
                    "cadence_rpm": sample.cadence_rpm,
                    "speed_mps": sample.speed_mps,
                }
                for sample in samples
            ],
        }
        fit_file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _set_field(target: object, candidate_names: tuple[str, ...], value: object) -> None:
    for field_name in candidate_names:
        try:
            setattr(target, field_name, value)
            return
        except (AttributeError, TypeError):
            continue


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _to_fit_timestamp_ms(value: datetime) -> int:
    return int(round(_normalize_utc(value).timestamp() * 1000))
