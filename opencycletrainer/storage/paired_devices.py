from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from .paths import ensure_dir, get_paired_devices_file_path

_REQUIRED_KEYS = {"device_id", "name", "device_type"}
_VALID_DEVICE_TYPES = {"trainer", "power_meter", "heart_rate", "cadence", "other"}


class PairedDeviceStore:
    """Persists paired device identities across sessions."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            if "PYTEST_CURRENT_TEST" in os.environ:
                raise RuntimeError(
                    "PairedDeviceStore() was created without an explicit path during a test "
                    "run, which would write to the real user's production path. "
                    "Pass path=tmp_path / 'paired.json' in your test fixture."
                )
            self._path = get_paired_devices_file_path()
        else:
            self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[dict[str, str]]:
        """Return validated list of paired device dicts; returns [] if file missing or corrupt."""
        with self._lock:
            return self._read_locked()

    def save(self, devices: list[dict[str, str]]) -> None:
        """Persist the list of paired device dicts sorted by device_id."""
        with self._lock:
            self._write_locked(devices)

    def _read_locked(self) -> list[dict[str, str]]:
        if not self._path.exists():
            return []
        raw_text = self._path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return []
        loaded = json.loads(raw_text)
        if not isinstance(loaded, list):
            return []
        result: list[dict[str, str]] = []
        for entry in loaded:
            if not isinstance(entry, dict):
                continue
            if not _REQUIRED_KEYS.issubset(entry.keys()):
                continue
            if entry["device_type"] not in _VALID_DEVICE_TYPES:
                continue
            result.append({k: str(entry[k]) for k in _REQUIRED_KEYS})
        return result

    def _write_locked(self, devices: list[dict[str, str]]) -> None:
        ensure_dir(self._path.parent)
        payload = sorted(
            [{k: entry[k] for k in _REQUIRED_KEYS} for entry in devices],
            key=lambda d: d["device_id"],
        )
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
