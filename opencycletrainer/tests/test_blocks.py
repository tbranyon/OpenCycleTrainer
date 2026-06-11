from __future__ import annotations

import shutil
from pathlib import Path

from opencycletrainer.storage.blocks import load_blocks, save_blocks


def _blocks_file() -> Path:
    folder = Path.cwd() / ".tmp_runtime" / "blocks_tests"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "blocks.json"


def test_load_blocks_returns_empty_when_file_missing():
    blocks_file = _blocks_file()
    assert load_blocks(blocks_file) == {}


def test_save_and_load_round_trip():
    blocks_file = _blocks_file()
    blocks = {
        "warmup": "- 5m ramp 40-65%\n- 1m 50%",
        "cooldown": "- 5m ramp 60-40%",
    }

    save_blocks(blocks, blocks_file)
    loaded = load_blocks(blocks_file)

    assert loaded == blocks


def test_load_blocks_empty_file_returns_empty():
    blocks_file = _blocks_file()
    blocks_file.write_text("", encoding="utf-8")
    assert load_blocks(blocks_file) == {}


def test_load_blocks_garbage_file_returns_empty():
    blocks_file = _blocks_file()
    blocks_file.write_text("not json {", encoding="utf-8")
    assert load_blocks(blocks_file) == {}


def test_save_blocks_returns_path():
    blocks_file = _blocks_file()
    result = save_blocks({"warmup": "- 5m 50%"}, blocks_file)
    assert result == blocks_file
    assert blocks_file.exists()
