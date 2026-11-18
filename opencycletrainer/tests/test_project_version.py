from __future__ import annotations

import tomllib
from pathlib import Path

import opencycletrainer

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_package_version_matches_pyproject():
    """Installers are named from pyproject.toml; the app shows __version__. They must agree."""
    pyproject = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))

    assert opencycletrainer.__version__ == pyproject["project"]["version"]
