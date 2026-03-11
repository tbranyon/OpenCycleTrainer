from __future__ import annotations

import json
from pathlib import Path
import threading

from .paths import ensure_dir, get_opentrueup_offsets_file_path


def build_pair_key(trainer_id: str, power_meter_id: str) -> str:
    trainer = _normalize_device_id(trainer_id)
    power_meter = _normalize_device_id(power_meter_id)
    return f"{trainer}::{power_meter}"


class OpenTrueUpOffsetStore:
    """Persistence helper for OpenTrueUp offsets keyed by trainer + power meter pair."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else get_opentrueup_offsets_file_path()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def get_offset_watts(self, trainer_id: str, power_meter_id: str) -> int:
        pair_key = build_pair_key(trainer_id, power_meter_id)
        with self._lock:
            raw = self._read_offsets_locked()
            return int(raw.get(pair_key, 0))

    def set_offset_watts(self, trainer_id: str, power_meter_id: str, offset_watts: int) -> int:
        pair_key = build_pair_key(trainer_id, power_meter_id)
        normalized_offset = int(offset_watts)
        with self._lock:
            raw = self._read_offsets_locked()
            raw[pair_key] = normalized_offset
            self._write_offsets_locked(raw)
        return normalized_offset

    def read_all_offsets(self) -> dict[str, int]:
        with self._lock:
            raw = self._read_offsets_locked()
        return {key: int(value) for key, value in raw.items()}

    def _read_offsets_locked(self) -> dict[str, int]:
        if not self._path.exists():
            return {}
        raw_text = self._path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return {}

        loaded = json.loads(raw_text)
        if not isinstance(loaded, dict):
            return {}

        normalized: dict[str, int] = {}
        for key, value in loaded.items():
            if not isinstance(key, str):
                continue
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError):
                continue
        return normalized

    def _write_offsets_locked(self, offsets: dict[str, int]) -> None:
        ensure_dir(self._path.parent)
        payload = {key: int(value) for key, value in sorted(offsets.items())}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalize_device_id(device_id: str) -> str:
    normalized = str(device_id).strip().lower()
    if not normalized:
        raise ValueError("Device id must be a non-empty string.")
    return normalized
