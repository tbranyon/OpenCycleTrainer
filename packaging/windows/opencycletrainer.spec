# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build of the app folder that the MSI installs (run by scripts/build_windows.ps1)."""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PACKAGING_DIR = Path(SPECPATH).resolve()
REPO_ROOT = PACKAGING_DIR.parents[1]
APP_NAME = "OpenCycleTrainer"

hiddenimports = collect_submodules("bleak.backends.winrt") if sys.platform == "win32" else []

a = Analysis(
    [str(PACKAGING_DIR / "launcher.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[
        (str(REPO_ROOT / "res" / "icon_nobg.png"), "res"),
        (str(REPO_ROOT / "workouts" / "*.mrc"), "workouts"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
