from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.tags import compatible_tags, cpython_tags

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "packaging" / "linux" / "flatpak_deps.py"


def _load_flatpak_deps():
    spec = importlib.util.spec_from_file_location("flatpak_deps", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flatpak_deps = _load_flatpak_deps()

_PLATFORMS = [f"manylinux_2_{minor}_x86_64" for minor in range(40, 16, -1)] + ["linux_x86_64"]
_TARGET = {
    "environment": {
        "implementation_name": "cpython",
        "implementation_version": "3.13.5",
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "platform_release": "6.12.0",
        "platform_system": "Linux",
        "platform_version": "#1 SMP",
        "python_full_version": "3.13.5",
        "python_version": "3.13",
        "sys_platform": "linux",
    },
    "tags": [
        str(tag)
        for tags in (
            cpython_tags((3, 13), abis=["cp313"], platforms=_PLATFORMS),
            compatible_tags((3, 13), interpreter="cp313", platforms=_PLATFORMS),
        )
        for tag in tags
    ],
}

_LOCK = tomllib.loads(
    """
version = 1
revision = 3
requires-python = ">=3.11"

[[package]]
name = "app"
version = "1.0.0"
source = { editable = "." }
dependencies = [
    { name = "pure" },
    { name = "native" },
    { name = "linux-only", marker = "sys_platform == 'linux'" },
    { name = "windows-only", marker = "sys_platform == 'win32'" },
    { name = "old-python-only", marker = "python_full_version < '3.12'" },
    { name = "qt" },
]

[package.optional-dependencies]
dev = [{ name = "test-tool" }]

[package.dev-dependencies]
build = [{ name = "freezer" }]

[[package]]
name = "pure"
version = "2.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "shared" }]
wheels = [{ url = "https://files.example/pure-2.0-py3-none-any.whl", hash = "sha256:a1", size = 1 }]

[[package]]
name = "shared"
version = "1.1"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/shared-1.1-py3-none-any.whl", hash = "sha256:b2", size = 1 }]

[[package]]
name = "native"
version = "3.0"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "https://files.example/native-3.0-cp311-abi3-manylinux_2_17_x86_64.whl", hash = "sha256:c0", size = 1 },
    { url = "https://files.example/native-3.0-cp312-cp312-manylinux_2_28_x86_64.whl", hash = "sha256:c1", size = 1 },
    { url = "https://files.example/native-3.0-cp313-cp313-manylinux_2_28_aarch64.whl", hash = "sha256:c2", size = 1 },
    { url = "https://files.example/native-3.0-cp313-cp313-manylinux_2_28_x86_64.whl", hash = "sha256:c3", size = 1 },
    { url = "https://files.example/native-3.0-cp313-cp313-musllinux_1_2_x86_64.whl", hash = "sha256:c4", size = 1 },
    { url = "https://files.example/native-3.0-cp313-cp313-win_amd64.whl", hash = "sha256:c5", size = 1 },
]

[[package]]
name = "linux-only"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/linux_only-1.0-py3-none-any.whl", hash = "sha256:d1", size = 1 }]

[[package]]
name = "windows-only"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/windows_only-1.0-py3-none-any.whl", hash = "sha256:e1", size = 1 }]

[[package]]
name = "old-python-only"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/old_python_only-1.0-py3-none-any.whl", hash = "sha256:e2", size = 1 }]

[[package]]
name = "qt"
version = "6.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "qt-core" }]
wheels = [{ url = "https://files.example/qt-6.0-cp313-abi3-manylinux_2_28_x86_64.whl", hash = "sha256:f1", size = 1 }]

[[package]]
name = "qt-core"
version = "6.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/qt_core-6.0-cp313-abi3-manylinux_2_28_x86_64.whl", hash = "sha256:f2", size = 1 }]

[[package]]
name = "test-tool"
version = "8.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/test_tool-8.0-py3-none-any.whl", hash = "sha256:g1", size = 1 }]

[[package]]
name = "freezer"
version = "6.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/freezer-6.0-py3-none-any.whl", hash = "sha256:h1", size = 1 }]
"""
)


def _bundled_wheels(module: dict) -> list[str]:
    return [source["url"].rsplit("/", 1)[-1] for source in module["sources"]]


def _bundled_projects(module: dict) -> set[str]:
    return {wheel.split("-", 1)[0] for wheel in _bundled_wheels(module)}


def _with_package(lock: dict, package_toml: str, *, depended_on_as: str | None = None) -> dict:
    extra = tomllib.loads(package_toml)["package"]
    lock = {**lock, "package": [dict(package) for package in lock["package"]] + extra}
    root = lock["package"][0]
    root["dependencies"] = root["dependencies"] + [{"name": depended_on_as or extra[0]["name"]}]
    return lock


def test_bundles_runtime_dependencies_for_the_target_only():
    module = flatpak_deps.build_module(_LOCK, _TARGET, exclude=["qt"])

    assert _bundled_projects(module) == {"pure", "shared", "native", "linux_only"}


def test_excluded_package_takes_its_own_dependencies_with_it():
    bundled = flatpak_deps.build_module(_LOCK, _TARGET)
    excluded = flatpak_deps.build_module(_LOCK, _TARGET, exclude=["Qt"])

    assert {"qt", "qt_core"} <= _bundled_projects(bundled)
    assert not {"qt", "qt_core"} & _bundled_projects(excluded)


def test_picks_the_wheel_built_for_the_target_interpreter_and_platform():
    module = flatpak_deps.build_module(_LOCK, _TARGET, exclude=["qt"])

    native_sources = [source for source in module["sources"] if "/native-" in source["url"]]
    assert native_sources == [
        {
            "type": "file",
            "url": "https://files.example/native-3.0-cp313-cp313-manylinux_2_28_x86_64.whl",
            "sha256": "c3",
        }
    ]


def test_install_command_installs_every_bundled_wheel_without_an_index():
    module = flatpak_deps.build_module(_LOCK, _TARGET, exclude=["qt"])

    (command,) = module["build-commands"]
    assert "--no-index" in command
    assert "${FLATPAK_DEST}" in command
    for wheel in _bundled_wheels(module):
        assert wheel in command


def test_dependency_extra_pulls_in_that_extras_dependencies():
    lock = _with_package(
        _LOCK,
        """
[[package]]
name = "client"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/client-1.0-py3-none-any.whl", hash = "sha256:i1", size = 1 }]

[package.optional-dependencies]
socks = [{ name = "socks-lib" }]
unused = [{ name = "windows-only" }]

[[package]]
name = "socks-lib"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://files.example/socks_lib-1.0-py3-none-any.whl", hash = "sha256:i2", size = 1 }]
""",
    )
    lock["package"][0]["dependencies"][-1]["extra"] = ["socks"]

    module = flatpak_deps.build_module(lock, _TARGET, exclude=["qt"])

    assert {"client", "socks_lib"} <= _bundled_projects(module)
    assert "windows_only" not in _bundled_projects(module)


def test_dependency_without_a_wheel_for_the_target_is_an_error():
    lock = _with_package(
        _LOCK,
        """
[[package]]
name = "windows-native"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.example/windows_native-1.0.tar.gz", hash = "sha256:j0", size = 1 }
wheels = [{ url = "https://files.example/windows_native-1.0-cp313-cp313-win_amd64.whl", hash = "sha256:j1", size = 1 }]
""",
    )

    with pytest.raises(flatpak_deps.DependencyError, match="windows-native"):
        flatpak_deps.build_module(lock, _TARGET, exclude=["qt"])


def test_cli_writes_a_module_for_the_repository_lock(tmp_path):
    target_path = tmp_path / "target.json"
    target_path.write_text(json.dumps(_TARGET), encoding="utf-8")
    output_path = tmp_path / "out" / "python-deps.json"

    exit_code = flatpak_deps.main(
        [
            "--lock", str(_REPO_ROOT / "uv.lock"),
            "--target", str(target_path),
            "--exclude", "pyside6",
            "--output", str(output_path),
        ]
    )

    assert exit_code == 0
    projects = _bundled_projects(json.loads(output_path.read_text(encoding="utf-8")))
    assert {"bleak", "dbus_fast", "numpy", "pyqtgraph"} <= projects
    assert not {"pyside6", "shiboken6", "pytest", "winrt_runtime"} & projects
