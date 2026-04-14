from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from opencycletrainer.core.fit_exporter import FitExportSample, FitExporter
from opencycletrainer.storage.filenames import build_activity_filename
from opencycletrainer.storage.paths import (
    ensure_dir,
    get_workout_data_root,
    get_workout_fit_dir,
    get_workout_json_dir,
    get_workout_png_dir,
)


@dataclass(frozen=True)
class RecorderSample:
    timestamp_utc: datetime
    target_power_watts: int | None = None
    trainer_power_watts: int | None = None
    bike_power_watts: int | None = None
    heart_rate_bpm: int | None = None
    cadence_rpm: float | None = None
    speed_mps: float | None = None
    mode: str | None = None
    erg_setpoint_watts: int | None = None
    total_kj: float | None = None


@dataclass(frozen=True)
class RecorderSession:
    workout_name: str
    started_at_utc: datetime
    fit_file_path: Path
    samples_file_path: Path
    summary_file_path: Path


@dataclass(frozen=True)
class RecorderSummary:
    workout_name: str
    start_time_utc: datetime
    duration_seconds: int
    avg_power_watts: float | None
    sample_count: int
    fit_file_path: Path
    samples_file_path: Path
    summary_file_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "workout_name": self.workout_name,
            "start_time_utc": _isoformat_utc(self.start_time_utc),
            "duration_seconds": self.duration_seconds,
            "avg_power_watts": self.avg_power_watts,
            "sample_count": self.sample_count,
        }


class WorkoutRecorder:
    """Records workout samples at 1 Hz and writes buffered sample data in the background."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        flush_batch_size: int = 10,
        fit_exporter: FitExporter | None = None,
    ) -> None:
        if flush_batch_size <= 0:
            raise ValueError("flush_batch_size must be greater than zero.")

        self._data_root = get_workout_data_root(data_dir)
        self._flush_batch_size = flush_batch_size
        self._fit_exporter = fit_exporter if fit_exporter is not None else FitExporter()

        self._session: RecorderSession | None = None
        self._recording_enabled = False
        self._recorded_samples: list[RecorderSample] = []
        self._pending_rows: list[dict[str, Any]] = []
        self._last_recorded_timestamp_utc: datetime | None = None
        self._effective_power_sum = 0.0
        self._effective_power_count = 0

        self._write_queue: queue.SimpleQueue[list[dict[str, Any]] | None] | None = None
        self._writer_thread: threading.Thread | None = None

    @property
    def is_recording(self) -> bool:
        return self._session is not None

    @property
    def recording_enabled(self) -> bool:
        return self._session is not None and self._recording_enabled

    @property
    def session(self) -> RecorderSession | None:
        return self._session

    def set_data_dir(self, data_dir: Path) -> None:
        if self._session is not None:
            raise RuntimeError("Cannot update recorder data directory while active.")
        self._data_root = data_dir

    def get_recorded_samples(self) -> list[RecorderSample]:
        return list(self._recorded_samples)

    def start(self, workout_name: str, started_at_utc: datetime | None = None) -> RecorderSession:
        if self._session is not None:
            raise RuntimeError("Recorder is already active.")

        start_time_utc = _normalize_utc(started_at_utc or datetime.now(timezone.utc))
        fit_dir = get_workout_fit_dir(self._data_root)
        json_dir = get_workout_json_dir(self._data_root)
        get_workout_png_dir(self._data_root)

        fit_filename = build_activity_filename(workout_name, start_time_utc, "fit")
        fit_file_path = fit_dir / fit_filename
        samples_file_path = json_dir / Path(fit_filename).with_suffix(".samples.jsonl")
        summary_file_path = json_dir / Path(fit_filename).with_suffix(".json")

        self._session = RecorderSession(
            workout_name=workout_name,
            started_at_utc=start_time_utc,
            fit_file_path=fit_file_path,
            samples_file_path=samples_file_path,
            summary_file_path=summary_file_path,
        )
        self._recorded_samples = []
        self._recording_enabled = True
        self._pending_rows = []
        self._last_recorded_timestamp_utc = None
        self._effective_power_sum = 0.0
        self._effective_power_count = 0

        self._write_queue = queue.SimpleQueue()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="WorkoutRecorderWriter",
            daemon=True,
        )
        self._writer_thread.start()
        return self._session

    def record_sample(self, sample: RecorderSample) -> bool:
        if self._session is None:
            raise RuntimeError("Recorder is not active.")
        if not self._recording_enabled:
            return False

        normalized_timestamp = _normalize_utc(sample.timestamp_utc)
        last_timestamp = self._last_recorded_timestamp_utc
        if last_timestamp is not None:
            delta_seconds = (normalized_timestamp - last_timestamp).total_seconds()
            if delta_seconds < 0:
                raise ValueError("Sample timestamps must be monotonic.")
            if delta_seconds < 1:
                return False

        normalized_sample = RecorderSample(
            timestamp_utc=normalized_timestamp,
            target_power_watts=sample.target_power_watts,
            trainer_power_watts=sample.trainer_power_watts,
            bike_power_watts=sample.bike_power_watts,
            heart_rate_bpm=sample.heart_rate_bpm,
            cadence_rpm=sample.cadence_rpm,
            speed_mps=sample.speed_mps,
            mode=sample.mode,
            erg_setpoint_watts=sample.erg_setpoint_watts,
            total_kj=sample.total_kj,
        )
        self._recorded_samples.append(normalized_sample)
        self._last_recorded_timestamp_utc = normalized_timestamp

        effective_power = normalized_sample.bike_power_watts
        if effective_power is None:
            effective_power = normalized_sample.trainer_power_watts
        if effective_power is not None:
            self._effective_power_sum += float(effective_power)
            self._effective_power_count += 1

        self._pending_rows.append(self._sample_to_row(normalized_sample))
        if len(self._pending_rows) >= self._flush_batch_size:
            self._flush_pending_rows()
        return True

    def stop(self, finished_at_utc: datetime | None = None) -> RecorderSummary:
        session = self._session
        if session is None:
            raise RuntimeError("Recorder is not active.")

        finish_time_utc = _normalize_utc(finished_at_utc or datetime.now(timezone.utc))
        if finish_time_utc < session.started_at_utc:
            raise ValueError("finish timestamp cannot be before start timestamp.")

        self._flush_pending_rows()
        if self._write_queue is not None:
            self._write_queue.put(None)
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5)
            if self._writer_thread.is_alive():
                raise RuntimeError("Timed out waiting for recorder writer thread.")

        duration_seconds = int((finish_time_utc - session.started_at_utc).total_seconds())
        avg_power_watts: float | None = None
        if self._effective_power_count > 0:
            avg_power_watts = round(self._effective_power_sum / self._effective_power_count, 2)

        fit_samples = [
            FitExportSample(
                timestamp_utc=sample.timestamp_utc,
                power_watts=(
                    sample.bike_power_watts
                    if sample.bike_power_watts is not None
                    else sample.trainer_power_watts
                ),
                heart_rate_bpm=sample.heart_rate_bpm,
                cadence_rpm=sample.cadence_rpm,
                speed_mps=sample.speed_mps,
            )
            for sample in self._recorded_samples
        ]
        try:
            self._fit_exporter.export_activity(
                workout_name=session.workout_name,
                started_at_utc=session.started_at_utc,
                finished_at_utc=finish_time_utc,
                fit_file_path=session.fit_file_path,
                samples=fit_samples,
            )
        except Exception:
            _logger.exception(
                "FIT export failed; workout data preserved in %s",
                session.samples_file_path,
            )
        else:
            size_kb = session.fit_file_path.stat().st_size / 1024
            _logger.info("FIT file written: %s (%.1f KB)", session.fit_file_path, size_kb)

        summary = RecorderSummary(
            workout_name=session.workout_name,
            start_time_utc=session.started_at_utc,
            duration_seconds=duration_seconds,
            avg_power_watts=avg_power_watts,
            sample_count=len(self._recorded_samples),
            fit_file_path=session.fit_file_path,
            samples_file_path=session.samples_file_path,
            summary_file_path=session.summary_file_path,
        )
        session.summary_file_path.write_text(
            json.dumps(summary.to_dict(), indent=2),
            encoding="utf-8",
        )

        self._session = None
        self._recording_enabled = False
        self._write_queue = None
        self._writer_thread = None
        self._pending_rows = []
        self._last_recorded_timestamp_utc = None
        return summary

    def set_recording_active(self, active: bool) -> None:
        if self._session is None:
            raise RuntimeError("Recorder is not active.")
        active_bool = bool(active)
        if self._recording_enabled == active_bool:
            return
        self._recording_enabled = active_bool
        if active_bool:
            # Allow immediate sample acceptance after pause/ramp-in transitions.
            self._last_recorded_timestamp_utc = None

    def _flush_pending_rows(self) -> None:
        if not self._pending_rows:
            return
        if self._write_queue is None:
            raise RuntimeError("Recorder writer queue is not initialized.")
        batch = list(self._pending_rows)
        self._pending_rows = []
        self._write_queue.put(batch)

    def _writer_loop(self) -> None:
        session = self._session
        write_queue = self._write_queue
        if session is None or write_queue is None:
            return

        ensure_dir(session.samples_file_path.parent)
        with session.samples_file_path.open("w", encoding="utf-8") as handle:
            while True:
                batch = write_queue.get()
                if batch is None:
                    break
                for row in batch:
                    handle.write(json.dumps(row, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()

    @staticmethod
    def _sample_to_row(sample: RecorderSample) -> dict[str, Any]:
        return {
            "timestamp_utc": _isoformat_utc(sample.timestamp_utc),
            "target_power_watts": sample.target_power_watts,
            "trainer_power_watts": sample.trainer_power_watts,
            "bike_power_watts": sample.bike_power_watts,
            "heart_rate_bpm": sample.heart_rate_bpm,
            "cadence_rpm": sample.cadence_rpm,
            "speed_mps": sample.speed_mps,
            "mode": sample.mode,
            "erg_setpoint_watts": sample.erg_setpoint_watts,
            "total_kj": sample.total_kj,
        }


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    return _normalize_utc(value).isoformat().replace("+00:00", "Z")
