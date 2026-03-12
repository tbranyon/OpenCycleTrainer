from __future__ import annotations

import json
from pathlib import Path

import pytest

from opencycletrainer.storage.paired_devices import PairedDeviceStore


def test_paired_device_store_empty_when_file_missing(tmp_path):
    store = PairedDeviceStore(path=tmp_path / "paired_devices.json")

    result = store.load()

    assert result == []


def test_paired_device_store_roundtrip_save_and_load(tmp_path):
    path = tmp_path / "paired_devices.json"
    store = PairedDeviceStore(path=path)
    devices = [
        {"device_id": "AA:BB:CC:01", "name": "Trainer A", "device_type": "trainer"},
        {"device_id": "AA:BB:CC:02", "name": "Power Meter B", "device_type": "power_meter"},
    ]

    store.save(devices)
    loaded = PairedDeviceStore(path=path).load()

    assert loaded == sorted(devices, key=lambda d: d["device_id"])


def test_paired_device_store_skips_malformed_entries(tmp_path):
    path = tmp_path / "paired_devices.json"
    path.write_text(
        json.dumps([
            {"name": "No ID", "device_type": "trainer"},
            {"device_id": "AA:BB:CC:01", "name": "Valid", "device_type": "trainer"},
            {"device_id": "AA:BB:CC:02", "device_type": "power_meter"},
        ]),
        encoding="utf-8",
    )

    result = PairedDeviceStore(path=path).load()

    assert len(result) == 1
    assert result[0]["device_id"] == "AA:BB:CC:01"


def test_paired_device_store_skips_unknown_device_type(tmp_path):
    path = tmp_path / "paired_devices.json"
    path.write_text(
        json.dumps([
            {"device_id": "AA:BB:CC:01", "name": "Valid", "device_type": "trainer"},
            {"device_id": "AA:BB:CC:02", "name": "Bad", "device_type": "unknown_type"},
        ]),
        encoding="utf-8",
    )

    result = PairedDeviceStore(path=path).load()

    assert len(result) == 1
    assert result[0]["device_id"] == "AA:BB:CC:01"


def test_paired_device_store_path_property(tmp_path):
    path = tmp_path / "paired_devices.json"
    store = PairedDeviceStore(path=path)

    assert store.path == path


def test_paired_devices_path_uses_config_dir(monkeypatch):
    from pathlib import Path
    from opencycletrainer.storage import paths

    fake_config = Path("C:/cfg/OpenCycleTrainer")
    monkeypatch.setattr(paths, "get_config_dir", lambda: fake_config)

    from opencycletrainer.storage.paths import get_paired_devices_file_path
    assert get_paired_devices_file_path() == fake_config / "paired_devices.json"
