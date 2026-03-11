# Windows MSI Packaging

This directory contains the Windows packaging toolchain for Task 15.

## Toolchain

- PyInstaller (builds distributable app folder)
- WiX Toolset 3.x (`heat`, `candle`, `light`) for MSI creation

## Files

- `opencycletrainer.spec`: PyInstaller build definition
- `OpenCycleTrainer.wxs`: WiX MSI definition
- `../../scripts/build_windows_msi.ps1`: end-to-end build script

## Prerequisites

1. Windows 10/11
2. Python 3.11+
3. WiX Toolset 3.x installed and added to `PATH`
   - Required commands: `heat`, `candle`, `light`

## Build MSI

Run from repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_msi.ps1
```

Optional flags:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_msi.ps1 -SkipTests
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_msi.ps1 -AppVersion 0.1.0
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_msi.ps1 -PythonExe .\.venv\Scripts\python.exe
```

If `-PythonExe` is omitted, the script automatically prefers `.\.venv\Scripts\python.exe` when present.

Output MSI:

- `dist\installer\OpenCycleTrainer-<version>-x64.msi`

## Install / Verify Checklist

1. Install MSI and launch OpenCycleTrainer from Start menu shortcut.
2. Confirm app starts and window title is `OpenCycleTrainer`.
3. Confirm settings path is `%APPDATA%\OpenCycleTrainer\settings.json`.
4. In Devices tab, run BLE scan and confirm relevant sensors/trainers can be discovered.
5. Confirm uninstall removes app files and shortcuts.
