"""Frozen-app entry point.

PyInstaller runs its entry script outside any package, so it cannot be
``opencycletrainer/__main__.py``, whose relative import would fail at launch.
"""

from opencycletrainer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
