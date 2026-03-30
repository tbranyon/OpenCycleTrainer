from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QTabWidget

from opencycletrainer.core.sensors import CadenceSource, SensorSample
from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
)

_CADENCE_SOURCE_BY_UUID: dict[str, CadenceSource] = {
    CSC_MEASUREMENT_CHARACTERISTIC_UUID: CadenceSource.DEDICATED,
    CPS_MEASUREMENT_CHARACTERISTIC_UUID: CadenceSource.POWER_METER,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID: CadenceSource.TRAINER,
}
from opencycletrainer.integrations.strava.sync_service import upload_fit_to_strava
from opencycletrainer.integrations.strava.token_store import get_tokens
from opencycletrainer.storage.settings import AppSettings, save_settings
from opencycletrainer.devices.device_manager import DeviceManager
from .devices_screen import DevicesScreen
from .settings_screen import SettingsScreen
from .theme import apply_application_theme
from .workout_controller import WorkoutSessionController
from .workout_library_screen import WorkoutLibraryScreen
from .workout_screen import WorkoutScreen


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        settings_path: Path | None = None,
        backend: DeviceManager | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings or AppSettings()
        self._effective_theme_mode = "light"
        self.setWindowTitle("OpenCycleTrainer")
        self.resize(1024, 720)
        self._settings_path = settings_path

        self.tabs = QTabWidget(self)
        self.workout_screen = WorkoutScreen(
            settings=self._settings,
            settings_path=settings_path,
            parent=self,
        )
        self.devices_screen = DevicesScreen(backend=backend, parent=self)
        self.settings_screen = SettingsScreen(
            settings=self._settings,
            settings_path=settings_path,
            strava_connected=get_tokens() is not None,
            strava_sync_fn=upload_fit_to_strava,
            opentrueup_devices_available=self.devices_screen.has_opentrueup_devices(),
            parent=self,
        )
        self.workout_controller = WorkoutSessionController(
            screen=self.workout_screen,
            settings=self._settings,
            settings_path=settings_path,
            strava_upload_fn=upload_fit_to_strava,
            parent=self,
        )
        self.settings_screen.settings_applied.connect(self._on_settings_applied)
        self.workout_screen.tile_order_changed.connect(self._on_tile_order_changed)
        self.devices_screen.sensor_sample_received.connect(self._on_sensor_sample)
        self.devices_screen.trainer_device_changed.connect(self._on_trainer_device_changed)
        self.devices_screen.opentrueup_availability_changed.connect(
            self.settings_screen.set_opentrueup_devices_available
        )
        self._workout_library = WorkoutLibrary()
        self.workout_library_screen = WorkoutLibraryScreen(
            library=self._workout_library,
            ftp_getter=lambda: self._settings.ftp,
            parent=self,
        )
        self.tabs.addTab(self.workout_screen, "Workout")
        self.tabs.addTab(self.workout_library_screen, "Library")
        self.tabs.addTab(self.devices_screen, "Devices")
        self.tabs.addTab(self.settings_screen, "Settings")
        self.setCentralWidget(self.tabs)

        self._library_tab_index = self.tabs.indexOf(self.workout_library_screen)
        self._workout_tab_index = self.tabs.indexOf(self.workout_screen)
        self.workout_screen.load_from_library_requested.connect(self._navigate_to_library)
        self.workout_library_screen.workout_selected.connect(self._on_library_workout_selected)
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_color_scheme_changed
        )
        self._apply_theme(self._settings)

        self.workout_controller.set_trainer_control_target(
            backend=self.devices_screen.backend,
            trainer_device_id=self.devices_screen.connected_trainer_device_id(),
        )

    def _on_sensor_sample(self, sample: object) -> None:
        if not isinstance(sample, SensorSample):
            return
        if sample.power_watts is not None:
            if sample.source_characteristic_uuid == CPS_MEASUREMENT_CHARACTERISTIC_UUID:
                self.workout_controller.receive_bike_power_watts(sample.power_watts)
            else:
                self.workout_controller.receive_power_watts(sample.power_watts)
        if sample.heart_rate_bpm is not None:
            self.workout_controller.receive_hr_bpm(sample.heart_rate_bpm)
        if sample.cadence_rpm is not None:
            source = _CADENCE_SOURCE_BY_UUID.get(
                sample.source_characteristic_uuid, CadenceSource.TRAINER
            )
            self.workout_controller.receive_cadence_rpm(sample.cadence_rpm, source)
        if sample.speed_mps is not None:
            self.workout_controller.receive_speed_mps(sample.speed_mps)

    def _on_settings_applied(self, settings: object) -> None:
        if not isinstance(settings, AppSettings):
            return
        self._settings = settings
        self._apply_theme(settings)
        self.workout_screen.apply_settings(settings)
        self.workout_controller.apply_settings(settings)

    def _on_tile_order_changed(self, new_order: object) -> None:
        """Persist the drag-reordered tile list to the settings file."""
        if not isinstance(new_order, list):
            return
        save_settings(self.workout_screen._settings, self._settings_path)

    def _navigate_to_library(self) -> None:
        self.tabs.setCurrentIndex(self._library_tab_index)

    def _on_library_workout_selected(self, path: Path) -> None:
        self.workout_controller.load_workout(path)
        self.tabs.setCurrentIndex(self._workout_tab_index)

    def _on_trainer_device_changed(self, backend: object, trainer_device_id: object) -> None:
        trainer_id = trainer_device_id if isinstance(trainer_device_id, str) else None
        self.workout_controller.set_trainer_control_target(
            backend=backend,
            trainer_device_id=trainer_id,
        )

    def _on_system_color_scheme_changed(self, _scheme: object) -> None:
        self._apply_theme(self._settings)

    def _apply_theme(self, settings: AppSettings) -> None:
        app = QApplication.instance()
        if app is None:
            return
        self._effective_theme_mode = apply_application_theme(settings.theme_mode, app)
        self.workout_screen.apply_color_theme(self._effective_theme_mode)

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.workout_controller.shutdown()
        self.devices_screen.backend.shutdown()
        super().closeEvent(event)
