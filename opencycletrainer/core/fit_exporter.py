from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

_logger = logging.getLogger(__name__)

from opencycletrainer.storage.paths import ensure_dir

# DFA alpha1 developer data field (spec [9]): there is no native FIT field for
# it, so it is embedded as a best-effort developer data field. These identify
# it consistently across the DeveloperDataIdMessage, FieldDescriptionMessage,
# and each RecordMessage's DeveloperField.
_DFA_DEVELOPER_DATA_INDEX = 0
_DFA_ALPHA1_FIELD_DEFINITION_NUMBER = 0
_DFA_ALPHA1_FIELD_NAME = "dfa_alpha1"
_DFA_ALPHA1_FIELD_UNITS = ""
_DFA_DEVELOPER_APP_ID = bytes(16)  # placeholder 16-byte OCT developer/application id

# Records are one per recorded second; a larger step between consecutive
# record timestamps means recording was paused in between.
_RECORD_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class FitExportSample:
    timestamp_utc: datetime
    power_watts: int | None = None
    heart_rate_bpm: int | None = None
    cadence_rpm: float | None = None
    speed_mps: float | None = None
    dfa_alpha1: float | None = None
    # Course ride fields; all None for a ride that did not follow a course.
    distance_m: float | None = None
    altitude_m: float | None = None
    grade_percent: float | None = None
    latitude_deg: float | None = None
    longitude_deg: float | None = None


class FitWriterBackend(Protocol):
    def write_activity(
        self,
        *,
        workout_name: str,
        started_at_utc: datetime,
        finished_at_utc: datetime,
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
        finished_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> Path:
        ensure_dir(fit_file_path.parent)
        normalized_start = _normalize_utc(started_at_utc)
        normalized_finish = _normalize_utc(finished_at_utc)
        normalized_samples = [
            replace(sample, timestamp_utc=_normalize_utc(sample.timestamp_utc))
            for sample in samples
        ]
        self._writer_backend.write_activity(
            workout_name=workout_name,
            started_at_utc=normalized_start,
            finished_at_utc=normalized_finish,
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
        finished_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> None:
        try:
            from fit_tool.fit_file_builder import FitFileBuilder
            from fit_tool.profile.messages.activity_message import ActivityMessage
            from fit_tool.profile.messages.event_message import EventMessage
            from fit_tool.profile.messages.file_id_message import FileIdMessage
            from fit_tool.profile.messages.lap_message import LapMessage
            from fit_tool.profile.messages.record_message import RecordMessage
            from fit_tool.profile.messages.session_message import SessionMessage
            from fit_tool.profile.profile_type import (
                Activity,
                Event,
                EventType,
                FileType,
                Manufacturer,
                Sport,
                SubSport,
            )
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

        include_dfa_alpha1 = False
        try:
            include_dfa_alpha1 = _add_dfa_developer_field_definitions(builder, samples)
        except Exception:
            _logger.debug(
                "Could not add DFA alpha1 developer-field definitions; "
                "continuing without it.",
                exc_info=True,
            )

        def add_timer_event(timestamp_ms: int, event_type: object) -> None:
            event = EventMessage()
            _set_field(event, ("timestamp",), timestamp_ms)
            _set_field(event, ("event",), _enum_value(Event.TIMER))
            _set_field(event, ("event_type", "eventType"), _enum_value(event_type))
            _set_field(event, ("event_group", "eventGroup"), 0)
            builder.add(event)

        # Timer start/stop events bracket the recording and every pause so
        # readers derive moving time from the timer, not from elapsed time.
        add_timer_event(_to_fit_timestamp_ms(started_at_utc), EventType.START)
        for pause_start, pause_end in _pause_intervals(samples):
            add_timer_event(_to_fit_timestamp_ms(pause_start), EventType.STOP_ALL)
            add_timer_event(_to_fit_timestamp_ms(pause_end), EventType.START)

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
            if sample.distance_m is not None:
                _set_field(record, ("distance",), float(sample.distance_m))
            if sample.altitude_m is not None:
                _set_field(record, ("altitude",), float(sample.altitude_m))
            if sample.grade_percent is not None:
                _set_field(record, ("grade",), float(sample.grade_percent))
            if sample.latitude_deg is not None and sample.longitude_deg is not None:
                _set_field(record, ("position_lat", "positionLat"), float(sample.latitude_deg))
                _set_field(record, ("position_long", "positionLong"), float(sample.longitude_deg))
            if include_dfa_alpha1 and sample.dfa_alpha1 is not None:
                _attach_dfa_developer_field(record, sample.dfa_alpha1)
            builder.add(record)

        elapsed_seconds = (finished_at_utc - started_at_utc).total_seconds()
        timer_seconds = float(len(samples)) * _RECORD_INTERVAL_SECONDS
        finish_ts_ms = _to_fit_timestamp_ms(finished_at_utc)
        start_ts_ms = _to_fit_timestamp_ms(started_at_utc)

        add_timer_event(finish_ts_ms, EventType.STOP_ALL)

        total_distance_m = _total_distance_m(samples)
        total_ascent_m, total_descent_m = _total_ascent_descent_m(samples)
        has_positions = any(sample.latitude_deg is not None for sample in samples)
        # A ride along a course is a virtual ride; anything else is plain indoor cycling.
        sub_sport = SubSport.VIRTUAL_ACTIVITY if has_positions else SubSport.INDOOR_CYCLING

        lap = LapMessage()
        _set_field(lap, ("timestamp",), finish_ts_ms)
        _set_field(lap, ("start_time", "startTime"), start_ts_ms)
        _set_field(lap, ("total_elapsed_time", "totalElapsedTime"), elapsed_seconds)
        _set_field(lap, ("total_timer_time", "totalTimerTime"), timer_seconds)
        if total_distance_m is not None:
            _set_field(lap, ("total_distance", "totalDistance"), total_distance_m)
        _set_field(lap, ("event",), _enum_value(Event.LAP))
        _set_field(lap, ("event_type", "eventType"), _enum_value(EventType.STOP))
        builder.add(lap)

        session = SessionMessage()
        _set_field(session, ("timestamp",), finish_ts_ms)
        _set_field(session, ("start_time", "startTime"), start_ts_ms)
        _set_field(session, ("total_elapsed_time", "totalElapsedTime"), elapsed_seconds)
        _set_field(session, ("total_timer_time", "totalTimerTime"), timer_seconds)
        _set_field(session, ("sport",), _enum_value(Sport.CYCLING))
        _set_field(session, ("sub_sport", "subSport"), _enum_value(sub_sport))
        if total_distance_m is not None:
            _set_field(session, ("total_distance", "totalDistance"), total_distance_m)
        if total_ascent_m is not None:
            _set_field(session, ("total_ascent", "totalAscent"), total_ascent_m)
            _set_field(session, ("total_descent", "totalDescent"), total_descent_m)
        _set_field(session, ("event",), _enum_value(Event.SESSION))
        _set_field(session, ("event_type", "eventType"), _enum_value(EventType.STOP_DISABLE_ALL))
        _set_field(session, ("num_laps", "numLaps"), 1)
        builder.add(session)

        activity = ActivityMessage()
        _set_field(activity, ("timestamp",), finish_ts_ms)
        _set_field(activity, ("local_timestamp", "localTimestamp"), _to_local_fit_timestamp(finished_at_utc))
        _set_field(activity, ("total_timer_time", "totalTimerTime"), timer_seconds)
        _set_field(activity, ("num_sessions", "numSessions"), 1)
        _set_field(activity, ("type",), _enum_value(Activity.MANUAL))
        _set_field(activity, ("event",), _enum_value(Event.ACTIVITY))
        _set_field(activity, ("event_type", "eventType"), _enum_value(EventType.STOP))
        builder.add(activity)

        fit_file = builder.build()
        fit_file.to_file(str(fit_file_path))


def _total_distance_m(samples: list[FitExportSample]) -> float | None:
    """Return the distance covered by the last sample that has one, or None if none do."""
    distances = [sample.distance_m for sample in samples if sample.distance_m is not None]
    return float(distances[-1]) if distances else None


def _total_ascent_descent_m(samples: list[FitExportSample]) -> tuple[int | None, int | None]:
    """Return whole metres climbed and descended across the samples' altitudes.

    Both are None when no sample carries an altitude.
    """
    altitudes = [sample.altitude_m for sample in samples if sample.altitude_m is not None]
    if not altitudes:
        return None, None
    changes = [later - earlier for earlier, later in zip(altitudes, altitudes[1:])]
    ascent = sum(change for change in changes if change > 0)
    descent = -sum(change for change in changes if change < 0)
    return int(round(ascent)), int(round(descent))


def _pause_intervals(samples: list[FitExportSample]) -> list[tuple[datetime, datetime]]:
    """Return (pause_start, pause_end) pairs implied by gaps in the record stream.

    Records are one per recorded second, so a pause begins one record interval
    after the last record before the gap and ends at the first record after it.
    """
    pauses: list[tuple[datetime, datetime]] = []
    for previous, current in zip(samples, samples[1:]):
        gap = (current.timestamp_utc - previous.timestamp_utc).total_seconds()
        if gap > _RECORD_INTERVAL_SECONDS:
            pause_start = previous.timestamp_utc + timedelta(seconds=_RECORD_INTERVAL_SECONDS)
            pauses.append((pause_start, current.timestamp_utc))
    return pauses


def _add_dfa_developer_field_definitions(
    builder: object,
    samples: list[FitExportSample],
) -> bool:
    """Best-effort: emit the DeveloperDataIdMessage + FieldDescriptionMessage
    describing the dfa_alpha1 developer field, when any sample carries a value.

    Returns True when per-record developer field values should be attached.
    Never raises; the caller treats any failure the same as "not present"
    (spec [9] — no native FIT field for α1, best-effort developer field).
    """
    if not any(sample.dfa_alpha1 is not None for sample in samples):
        return False

    from fit_tool.base_type import BaseType
    from fit_tool.profile.messages.developer_data_id_message import DeveloperDataIdMessage
    from fit_tool.profile.messages.field_description_message import FieldDescriptionMessage

    dev_id = DeveloperDataIdMessage()
    _set_field(dev_id, ("developer_id", "developerId"), _DFA_DEVELOPER_APP_ID)
    _set_field(dev_id, ("application_id", "applicationId"), _DFA_DEVELOPER_APP_ID)
    _set_field(dev_id, ("manufacturer_id", "manufacturerId"), 0)
    _set_field(dev_id, ("developer_data_index", "developerDataIndex"), _DFA_DEVELOPER_DATA_INDEX)
    builder.add(dev_id)

    field_description = FieldDescriptionMessage()
    _set_field(
        field_description, ("developer_data_index", "developerDataIndex"), _DFA_DEVELOPER_DATA_INDEX
    )
    _set_field(
        field_description,
        ("field_definition_number", "fieldDefinitionNumber"),
        _DFA_ALPHA1_FIELD_DEFINITION_NUMBER,
    )
    _set_field(field_description, ("fit_base_type_id", "fitBaseTypeId"), BaseType.FLOAT32.value)
    _set_field(field_description, ("field_name", "fieldName"), _DFA_ALPHA1_FIELD_NAME)
    _set_field(field_description, ("units",), _DFA_ALPHA1_FIELD_UNITS)
    builder.add(field_description)
    return True


def _attach_dfa_developer_field(record: object, alpha1: float) -> None:
    """Best-effort: attach the dfa_alpha1 developer field value to *record*.

    Swallows any failure so a single sample's developer field never aborts
    the export (spec [9]); the JSONL store still has the value regardless.
    """
    try:
        from fit_tool.base_type import BaseType
        from fit_tool.developer_field import DeveloperField

        field = DeveloperField(
            field_id=_DFA_ALPHA1_FIELD_DEFINITION_NUMBER,
            name=_DFA_ALPHA1_FIELD_NAME,
            base_type=BaseType.FLOAT32,
            units=_DFA_ALPHA1_FIELD_UNITS,
            developer_data_index=_DFA_DEVELOPER_DATA_INDEX,
            growable=True,
        )
        field.set_encoded_value(0, float(alpha1))
        record.developer_fields = [field]
    except Exception:
        _logger.debug("Could not attach dfa_alpha1 developer field to record.", exc_info=True)


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
        finished_at_utc: datetime,
        fit_file_path: Path,
        samples: list[FitExportSample],
    ) -> None:
        payload = {
            "workout_name": workout_name,
            "started_at_utc": _normalize_utc(started_at_utc).isoformat().replace("+00:00", "Z"),
            "finished_at_utc": _normalize_utc(finished_at_utc).isoformat().replace("+00:00", "Z"),
            "records": [
                {
                    "timestamp_utc": _normalize_utc(sample.timestamp_utc).isoformat().replace("+00:00", "Z"),
                    "power_watts": sample.power_watts,
                    "heart_rate_bpm": sample.heart_rate_bpm,
                    "cadence_rpm": sample.cadence_rpm,
                    "speed_mps": sample.speed_mps,
                    "dfa_alpha1": sample.dfa_alpha1,
                    "distance_m": sample.distance_m,
                    "altitude_m": sample.altitude_m,
                    "grade_percent": sample.grade_percent,
                    "latitude_deg": sample.latitude_deg,
                    "longitude_deg": sample.longitude_deg,
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
    _logger.debug("Could not set any of %s to %r on %s", candidate_names, value, type(target).__name__)


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc)


_FIT_EPOCH_OFFSET_SECONDS = 631065600  # seconds between Unix epoch (1970-01-01) and FIT epoch (1989-12-31)


def _to_fit_timestamp_ms(value: datetime) -> int:
    return int(round(_normalize_utc(value).timestamp() * 1000))


def _to_local_fit_timestamp(value: datetime) -> int:
    """Returns a FIT local_timestamp: seconds since FIT epoch (Dec 31 1989) expressed in local time."""
    utc_seconds = int(_normalize_utc(value).timestamp())
    utc_offset_seconds = int(value.astimezone().utcoffset().total_seconds())
    return utc_seconds + utc_offset_seconds - _FIT_EPOCH_OFFSET_SECONDS
