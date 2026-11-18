# Building installers

Each platform builds with one command, run from the repository root. The script fetches
the tools it needs, brings the locked dependencies up to date, runs the tests and writes
the installer to `dist/`.

| Platform | Command | Output |
|---|---|---|
| Windows | `scripts\build_windows.cmd` | `dist\OpenCycleTrainer-<version>-x64.msi` |
| Linux | `scripts/build_linux.sh` | `dist/OpenCycleTrainer-<version>-<arch>.flatpak` |

Options:

| Windows | Linux | Effect |
|---|---|---|
| `-Upgrade` | `--upgrade` | Upgrade every dependency to the newest version `pyproject.toml` allows (rewrites `uv.lock`; on Linux also updates the Flatpak runtime, SDK and base app) |
| `-SkipTests` | `--skip-tests` | Skip the test suite |
| | `--install` | Install the built bundle for the current user |

`build_windows.cmd` only runs `build_windows.ps1` with `-ExecutionPolicy Bypass`; calling
the `.ps1` directly works too where scripts are allowed.

## Prerequisites

**Windows:** Windows 10 or 11 (x64) and an internet connection. Everything else goes into
`build\tools` the first time: uv (unless it is already on `PATH`), Python 3.13 (through uv),
PyInstaller (locked in `uv.lock`) and WiX 3.14 (from NuGet). Downloads are pinned and
checked against SHA-256 hashes.

**Linux:** `flatpak`, and `curl` if uv is not installed. The KDE runtime and SDK, the
PySide base app and, if `flatpak-builder` is not installed, `org.flatpak.Builder` are
installed from Flathub for the current user, so no root access is needed.

## Dependencies

`uv.lock` is the single record of dependency versions for both builds. Each build runs
`uv lock` first, so a dependency added to `pyproject.toml` is picked up without extra
steps; `--upgrade` moves everything to the newest allowed versions. Commit `uv.lock`
when it changes.

The Flatpak build has no network access, so `build_linux.sh` asks the Flatpak SDK which
wheels its Python accepts and runs `packaging/linux/flatpak_deps.py` to write
`build/linux/python-deps.json`: the exact locked wheels (URL and SHA-256) for that
interpreter. PySide6 is left out because `io.qt.PySide.BaseApp` already provides it.

To move to a newer Flatpak runtime, change `runtime-version` and `base-version` in the
manifest. To move to a newer uv or WiX, change the version, URL and SHA-256 constants at
the top of the build scripts (from the PyPI or NuGet file pages).

## Layout

- `windows/opencycletrainer.spec`: PyInstaller build of the app folder
- `windows/launcher.py`: entry point for the frozen app
- `windows/OpenCycleTrainer.wxs`: WiX installer definition
- `linux/org.opencycletrainer.OpenCycleTrainer.yaml`: Flatpak manifest
- `linux/org.opencycletrainer.OpenCycleTrainer.desktop`: desktop entry
- `linux/flatpak_deps.py`: turns `uv.lock` into the Flatpak's Python module

Both installers bundle the prepackaged workouts (`workouts/*.mrc`) and the app icon
(`res/icon_nobg.png`). Working files go under `build/` (cached tools, the build
environments, PyInstaller and flatpak-builder state); it is safe to delete.

## Checking an installer

Windows:

1. Install the MSI and launch OpenCycleTrainer from the Start menu shortcut.
2. Confirm the window title is `OpenCycleTrainer` and settings are saved to
   `%APPDATA%\OpenCycleTrainer\settings.json`.
3. In the Devices tab, run a BLE scan and confirm sensors and trainers are found.
4. Uninstall and confirm the app files and shortcuts are removed.

Linux:

1. Install the bundle (`--install`, or `flatpak install --user <bundle>`) and run
   `flatpak run org.opencycletrainer.OpenCycleTrainer`.
2. In the Devices tab, run a BLE scan and confirm sensors and trainers are found
   (the manifest grants Bluetooth and BlueZ access).
3. Finish or simulate a ride and confirm its files can be saved to Documents.
