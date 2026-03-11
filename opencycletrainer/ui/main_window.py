from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QTabWidget

from opencycletrainer.storage.settings import AppSettings
from .devices_screen import DevicesScreen
from .settings_screen import SettingsScreen
from .workout_screen import WorkoutScreen


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("OpenCycleTrainer")
        self.resize(1024, 720)

        self.tabs = QTabWidget(self)
        self.workout_screen = WorkoutScreen(
            settings=settings,
            settings_path=settings_path,
            parent=self,
        )
        self.settings_screen = SettingsScreen(
            settings=settings,
            settings_path=settings_path,
            parent=self,
        )
        self.settings_screen.settings_applied.connect(self._on_settings_applied)
        self.devices_screen = DevicesScreen(parent=self)
        self.tabs.addTab(self.workout_screen, "Workout")
        self.tabs.addTab(self.devices_screen, "Devices")
        self.tabs.addTab(self.settings_screen, "Settings")
        self.setCentralWidget(self.tabs)

    def _on_settings_applied(self, settings: object) -> None:
        if not isinstance(settings, AppSettings):
            return
        self.workout_screen.apply_settings(settings)
