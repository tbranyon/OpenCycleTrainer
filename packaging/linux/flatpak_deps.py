"""Turn uv.lock into a flatpak-builder module that installs the app's Python dependencies.

The module lists the exact wheels uv locked (URL and sha256), chosen for the Flatpak
SDK's interpreter and platform, so the sandboxed build installs them without network.

    python flatpak_deps.py --lock uv.lock --target target.json --exclude pyside6 \
        --output python-deps.json

``target.json`` describes the SDK's interpreter, as printed inside the SDK by:
``{"environment": packaging.markers.default_environment(),
"tags": [str(tag) for tag in packaging.tags.sys_tags()]}``.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import tomllib
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import canonicalize_name, parse_wheel_filename

MODULE_NAME = "python-dependencies"
PROJECT_SOURCE_KINDS = ("editable", "virtual")
PROJECT_SOURCE_PATH = "."
SHA256_PREFIX = "sha256:"
PIP_INSTALL_COMMAND = (
    'python3 -m pip install --no-index --no-deps --no-build-isolation --prefix="${FLATPAK_DEST}"'
)


class DependencyError(Exception):
    """The lock cannot be turned into an offline module for the given target."""


def build_module(
    lock: Mapping, target: Mapping, *, exclude: Iterable[str] = ()
) -> dict:
    """Return a flatpak-builder module installing the project's runtime dependencies.

    ``exclude`` names packages the Flatpak base already provides; their own
    dependencies are left out too unless something else needs them.
    """
    packages = _resolve_runtime_packages(
        lock, target["environment"], {canonicalize_name(name) for name in exclude}
    )
    tag_priority = {tag: rank for rank, tag in enumerate(target["tags"])}
    wheels = [_select_wheel(package, tag_priority) for package in packages]
    filenames = [_wheel_filename(wheel) for wheel in wheels]
    return {
        "name": MODULE_NAME,
        "buildsystem": "simple",
        "build-commands": [
            " ".join([PIP_INSTALL_COMMAND, *(shlex.quote(name) for name in filenames)])
        ],
        "sources": [
            {"type": "file", "url": wheel["url"], "sha256": _sha256(package, wheel)}
            for package, wheel in zip(packages, wheels)
        ],
    }


def _resolve_runtime_packages(
    lock: Mapping, environment: Mapping[str, str], excluded: set[str]
) -> list[Mapping]:
    """Walk the project's runtime dependencies whose markers match the environment."""
    index: dict[str, list[Mapping]] = {}
    for package in lock.get("package", []):
        index.setdefault(package["name"], []).append(package)

    project = _find_project(lock)
    included: dict[tuple[str, str], Mapping] = {}
    expanded_extras: dict[tuple[str, str], set[str]] = {}
    pending: deque[Mapping] = deque(project.get("dependencies", []))
    while pending:
        dependency = pending.popleft()
        if canonicalize_name(dependency["name"]) in excluded:
            continue
        marker = dependency.get("marker")
        if marker and not Marker(marker).evaluate(dict(environment)):
            continue
        package = _lookup(index, dependency)
        key = (package["name"], package["version"])
        done = expanded_extras.setdefault(key, set())
        if key not in included:
            included[key] = package
            pending.extend(package.get("dependencies", []))
        for extra in set(dependency.get("extra", [])) - done:
            done.add(extra)
            pending.extend(package.get("optional-dependencies", {}).get(extra, []))
    return sorted(included.values(), key=lambda package: package["name"])


def _find_project(lock: Mapping) -> Mapping:
    for package in lock.get("package", []):
        source = package.get("source", {})
        if any(source.get(kind) == PROJECT_SOURCE_PATH for kind in PROJECT_SOURCE_KINDS):
            return package
    raise DependencyError("The lock has no project package (a source of editable or virtual '.').")


def _lookup(index: Mapping[str, list[Mapping]], dependency: Mapping) -> Mapping:
    candidates = index.get(dependency["name"], [])
    for field in ("version", "source"):
        if field in dependency:
            candidates = [package for package in candidates if package.get(field) == dependency[field]]
    if len(candidates) != 1:
        raise DependencyError(
            f"Cannot pick a single locked package for dependency {dict(dependency)!r} "
            f"({len(candidates)} candidates)."
        )
    return candidates[0]


def _select_wheel(package: Mapping, tag_priority: Mapping[str, int]) -> Mapping:
    """Return the package's wheel whose best tag ranks highest for the target."""
    best_rank = None
    best_wheel = None
    for wheel in package.get("wheels", []):
        _, _, _, tags = parse_wheel_filename(_wheel_filename(wheel))
        ranks = [tag_priority[str(tag)] for tag in tags if str(tag) in tag_priority]
        if ranks and (best_rank is None or min(ranks) < best_rank):
            best_rank, best_wheel = min(ranks), wheel
    if best_wheel is None:
        raise DependencyError(
            f"{package['name']} {package['version']} has no wheel for the Flatpak target; "
            "pin a version that publishes one or build it from source in its own module."
        )
    return best_wheel


def _wheel_filename(wheel: Mapping) -> str:
    return wheel["url"].rsplit("/", 1)[-1]


def _sha256(package: Mapping, wheel: Mapping) -> str:
    digest = wheel.get("hash", "")
    if not digest.startswith(SHA256_PREFIX):
        raise DependencyError(f"{package['name']} wheel has no sha256 hash in the lock.")
    return digest.removeprefix(SHA256_PREFIX)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", type=Path, required=True, help="path to uv.lock")
    parser.add_argument("--target", type=Path, required=True, help="SDK interpreter JSON")
    parser.add_argument(
        "--exclude", action="append", default=[], help="package the Flatpak base provides"
    )
    parser.add_argument("--output", type=Path, required=True, help="module JSON to write")
    args = parser.parse_args(argv)

    lock = tomllib.loads(args.lock.read_text(encoding="utf-8"))
    target = json.loads(args.target.read_text(encoding="utf-8"))
    try:
        module = build_module(lock, target, exclude=args.exclude)
    except DependencyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(module, indent=4) + "\n", encoding="utf-8")
    print(f"Wrote {len(module['sources'])} wheels to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
