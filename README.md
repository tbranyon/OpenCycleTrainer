# OpenCycleTrainer

Task 00 scaffold for a PySide6 desktop application.

## Prerequisites

- Python 3.11+

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Run the app

```bash
python -m opencycletrainer
```

This launches a window titled `OpenCycleTrainer`.
Current tabs: `Workout`, `Devices`, and `Settings`.

Visible workout data tiles are configured from the `Settings` tab.
Current settings controls include FTP, lead time, OpenTrueUp enable, display units, default workout behavior, and visible workout tiles (up to 8).

## Run tests

```bash
pytest
```

## Flatpak packaging (Task 14)

Linux Flatpak manifest and build instructions are in:

- `flatpak/org.opencycletrainer.OpenCycleTrainer.yaml`
- `flatpak/README.md`

## Windows MSI packaging (Task 15)

Windows packaging files and build instructions are in:

- `packaging/windows/opencycletrainer.spec`
- `packaging/windows/OpenCycleTrainer.wxs`
- `packaging/windows/README.md`
- `scripts/build_windows_msi.ps1`

## Local files created on first run

- Settings JSON in platform config directory:
  - Windows: `%APPDATA%\OpenCycleTrainer\settings.json`
  - Linux: `~/.config/opencycletrainer/settings.json`
- Log file:
  - Windows: `%APPDATA%\OpenCycleTrainer\opencycletrainer.log`
  - Linux: `~/.local/share/opencycletrainer/opencycletrainer.log`

## Recorder outputs (Task 08)

When `WorkoutRecorder` is used, files are written to the app data directory with matching stems:

- FIT path placeholder: `[WorkoutName]_[YYYYMMDD]_[HHMM].fit`
- JSON summary: `[WorkoutName]_[YYYYMMDD]_[HHMM].json`
- Buffered sample log: `[WorkoutName]_[YYYYMMDD]_[HHMM].samples.jsonl`
