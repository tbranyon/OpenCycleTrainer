from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.integrations.strava.app_credentials import (
    has_app_credentials,
    load_app_credentials,
)
from opencycletrainer.integrations.strava.oauth_flow import OAuthResult, run_oauth_flow
from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError
from opencycletrainer.integrations.strava.token_store import clear_tokens, is_available, save_tokens
from opencycletrainer.storage.paths import get_data_dir
from opencycletrainer.storage.settings import AppSettings, load_settings, save_settings
from .tile_config import MAX_CONFIGURABLE_TILES, TILE_OPTIONS, normalize_tile_selections

DISPLAY_UNITS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("metric", "Metric"),
    ("imperial", "Imperial"),
)
DEFAULT_BEHAVIOR_OPTIONS: tuple[tuple[str, str], ...] = (
    ("workout_mode", "Workout Mode"),
    ("free_ride_mode", "Free Ride Mode"),
    ("kj_mode", "kJ Mode"),
)


class _OAuthWorker(QObject):
    """Runs the blocking OAuth flow off the UI thread."""

    succeeded = Signal(object)  # OAuthResult
    failed = Signal(str)

    def __init__(self, credentials: object) -> None:
        super().__init__()
        self._credentials = credentials

    def run(self) -> None:
        try:
            result = run_oauth_flow(self._credentials)  # type: ignore[arg-type]
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SettingsScreen(QWidget):
    settings_applied = Signal(object)
    _sync_now_signal = Signal(str)  # "success" | "duplicate" | "error:{msg}"

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        settings_path: Path | None = None,
        strava_connected: bool = False,
        strava_sync_fn: object = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_path = settings_path
        self._settings = settings if settings is not None else load_settings(settings_path)
        self._strava_sync_fn = strava_sync_fn
        self._selected_tiles = normalize_tile_selections(self._settings.tile_selections)
        self._tile_checkboxes: dict[str, QCheckBox] = {}
        self._strava_connected = strava_connected
        self._oauth_thread: QThread | None = None
        self._sync_now_signal.connect(self._on_sync_now_result)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        title = QLabel("Settings", self)
        title.setObjectName("settingsScreenTitle")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 4)
        title.setFont(title_font)
        root_layout.addWidget(title)

        general_group = QGroupBox("General", self)
        general_layout = QFormLayout(general_group)

        self.ftp_spinbox = QSpinBox(general_group)
        self.ftp_spinbox.setRange(50, 2000)
        self.ftp_spinbox.setValue(self._settings.ftp)
        general_layout.addRow("FTP (W)", self.ftp_spinbox)

        self.lead_time_spinbox = QSpinBox(general_group)
        self.lead_time_spinbox.setRange(0, 30)
        self.lead_time_spinbox.setValue(self._settings.lead_time)
        general_layout.addRow("Lead Time (s)", self.lead_time_spinbox)

        self.windowed_power_window_spinbox = QSpinBox(general_group)
        self.windowed_power_window_spinbox.setRange(1, 10)
        self.windowed_power_window_spinbox.setValue(self._settings.windowed_power_window_seconds)
        general_layout.addRow("Power Window (s)", self.windowed_power_window_spinbox)

        self.opentrueup_checkbox = QCheckBox("Enable OpenTrueUp", general_group)
        self.opentrueup_checkbox.setChecked(self._settings.opentrueup_enabled)
        general_layout.addRow("OpenTrueUp", self.opentrueup_checkbox)

        self.display_units_combo = QComboBox(general_group)
        self.display_units_combo.addItems([label for _, label in DISPLAY_UNITS_OPTIONS])
        self._set_combo_value(
            self.display_units_combo,
            DISPLAY_UNITS_OPTIONS,
            self._settings.display_units,
        )
        general_layout.addRow("Display Units", self.display_units_combo)

        self.default_behavior_combo = QComboBox(general_group)
        self.default_behavior_combo.addItems([label for _, label in DEFAULT_BEHAVIOR_OPTIONS])
        self._set_combo_value(
            self.default_behavior_combo,
            DEFAULT_BEHAVIOR_OPTIONS,
            self._settings.default_workout_behavior,
        )
        general_layout.addRow("Default Workout Behavior", self.default_behavior_combo)
        root_layout.addWidget(general_group)

        tiles_group = QGroupBox("Visible Workout Tiles (max 8)", self)
        tiles_layout = QVBoxLayout(tiles_group)
        selector_layout = QGridLayout()
        for index, (key, label) in enumerate(TILE_OPTIONS):
            checkbox = QCheckBox(label, tiles_group)
            checkbox.toggled.connect(lambda checked, tile_key=key: self._on_tile_toggled(tile_key, checked))
            checkbox.setChecked(key in self._selected_tiles)
            row = index // 2
            column = index % 2
            selector_layout.addWidget(checkbox, row, column)
            self._tile_checkboxes[key] = checkbox
        tiles_layout.addLayout(selector_layout)

        self.tile_selection_status_label = QLabel("", tiles_group)
        self.tile_selection_status_label.setObjectName("settingsTileSelectionStatus")
        tiles_layout.addWidget(self.tile_selection_status_label)
        root_layout.addWidget(tiles_group)
        self._update_selection_status()

        strava_group = QGroupBox("Strava", self)
        strava_layout = QFormLayout(strava_group)

        self.strava_status_label = QLabel("", strava_group)
        self.strava_status_label.setObjectName("stravaStatusLabel")
        strava_layout.addRow("Status", self.strava_status_label)

        self.strava_connect_button = QPushButton("Connect with Strava", strava_group)
        self.strava_connect_button.clicked.connect(self._on_strava_connect)
        strava_layout.addRow(self.strava_connect_button)

        self.strava_disconnect_button = QPushButton("Disconnect Strava", strava_group)
        self.strava_disconnect_button.clicked.connect(self.disconnect_strava)
        strava_layout.addRow(self.strava_disconnect_button)

        self.strava_auto_sync_checkbox = QCheckBox("Automatically sync rides with Strava", strava_group)
        self.strava_auto_sync_checkbox.setChecked(self._settings.strava_auto_sync_enabled)
        strava_layout.addRow(self.strava_auto_sync_checkbox)

        self.strava_sync_now_button = QPushButton("Sync now", strava_group)
        self.strava_sync_now_button.clicked.connect(self._on_strava_sync_now)
        strava_layout.addRow(self.strava_sync_now_button)

        root_layout.addWidget(strava_group)
        self._apply_strava_connected_state(
            self._strava_connected,
            self._settings.strava_athlete_name,
        )

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        self.save_button = QPushButton("Save Settings", self)
        self.save_button.clicked.connect(self.save_current_settings)
        buttons_row.addWidget(self.save_button)
        root_layout.addLayout(buttons_row)

        self.status_label = QLabel("Ready.", self)
        self.status_label.setObjectName("settingsStatusLabel")
        root_layout.addWidget(self.status_label)
        root_layout.addStretch(1)

    def current_settings(self) -> AppSettings:
        return replace(
            self._settings,
            ftp=self.ftp_spinbox.value(),
            lead_time=self.lead_time_spinbox.value(),
            opentrueup_enabled=self.opentrueup_checkbox.isChecked(),
            tile_selections=list(self._selected_tiles),
            display_units=self._combo_value(self.display_units_combo, DISPLAY_UNITS_OPTIONS),
            default_workout_behavior=self._combo_value(
                self.default_behavior_combo,
                DEFAULT_BEHAVIOR_OPTIONS,
            ),
            windowed_power_window_seconds=self.windowed_power_window_spinbox.value(),
            strava_auto_sync_enabled=self.strava_auto_sync_checkbox.isChecked(),
        )

    def set_tile_selected(self, tile_key: str, selected: bool) -> None:
        checkbox = self._tile_checkboxes.get(tile_key)
        if checkbox is None:
            return
        checkbox.setChecked(selected)

    def save_current_settings(self) -> AppSettings:
        self._settings = self.current_settings()
        save_settings(self._settings, self._settings_path)
        self.status_label.setText("Settings saved.")
        self.settings_applied.emit(self._settings)
        return self._settings

    def disconnect_strava(self) -> None:
        """Clear stored tokens and update the UI to the disconnected state."""
        clear_tokens()
        self._settings = replace(
            self._settings,
            strava_athlete_name="",
            strava_auto_sync_enabled=False,
        )
        save_settings(self._settings, self._settings_path)
        self._apply_strava_connected_state(False, "")

    def _on_strava_connect(self) -> None:
        if not is_available():
            self.status_label.setText(
                "Strava sync requires a system keychain. "
                "Secure credential storage is not available on this system."
            )
            return
        if not has_app_credentials():
            self.status_label.setText("Strava app credentials are not configured.")
            return

        credentials = load_app_credentials()
        self.strava_connect_button.setEnabled(False)
        self.status_label.setText("Opening Strava authorization in browser…")

        self._oauth_thread = QThread(self)
        worker = _OAuthWorker(credentials)
        worker.moveToThread(self._oauth_thread)
        self._oauth_thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_oauth_succeeded)
        worker.failed.connect(self._on_oauth_failed)
        worker.succeeded.connect(self._oauth_thread.quit)
        worker.failed.connect(self._oauth_thread.quit)
        self._oauth_thread.start()

    def _on_oauth_succeeded(self, result: object) -> None:
        if not isinstance(result, OAuthResult):
            return
        save_tokens(result.token_bundle)
        self._settings = replace(self._settings, strava_athlete_name=result.athlete_name)
        save_settings(self._settings, self._settings_path)
        self._apply_strava_connected_state(True, result.athlete_name)
        self.status_label.setText("Strava connected.")

    def _on_oauth_failed(self, error_message: str) -> None:
        self.strava_connect_button.setEnabled(True)
        self.status_label.setText(f"Strava connection failed: {error_message}")

    def _apply_strava_connected_state(self, connected: bool, athlete_name: str) -> None:
        self._strava_connected = connected
        if connected:
            label = f"Connected as {athlete_name}" if athlete_name else "Connected"
        else:
            label = "Not connected"
        self.strava_status_label.setText(label)
        self.strava_connect_button.setVisible(not connected)
        self.strava_connect_button.setEnabled(True)
        self.strava_disconnect_button.setVisible(connected)
        self.strava_auto_sync_checkbox.setEnabled(connected)
        self.strava_sync_now_button.setEnabled(connected)

    def _on_strava_sync_now(self) -> None:
        """Open a FIT file picker and enqueue the selected file for Strava upload."""
        default_dir = str(get_data_dir())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select FIT File to Sync",
            default_dir,
            "FIT Files (*.fit)",
        )
        if not path or self._strava_sync_fn is None:
            return
        self.strava_sync_now_button.setEnabled(False)
        self.status_label.setText("Syncing to Strava…")

        fit_path = Path(path)
        sync_fn = self._strava_sync_fn
        signal = self._sync_now_signal

        def _run() -> None:
            try:
                sync_fn(fit_path)  # type: ignore[operator]
                signal.emit("success")
            except DuplicateUploadError:
                signal.emit("duplicate")
            except Exception as exc:  # noqa: BLE001
                signal.emit(f"error:{exc}")

        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strava_sync_now")
        executor.submit(_run)
        executor.shutdown(wait=False)

    def _on_sync_now_result(self, result: str) -> None:
        self.strava_sync_now_button.setEnabled(True)
        if result == "success":
            self.status_label.setText("Ride synced to Strava.")
        elif result == "duplicate":
            self.status_label.setText("Ride already synced to Strava.")
        else:
            msg = result[len("error:"):] if result.startswith("error:") else result
            self.status_label.setText(f"Strava sync failed: {msg}")

    def _on_tile_toggled(self, tile_key: str, checked: bool) -> None:
        if checked:
            if tile_key in self._selected_tiles:
                return
            if len(self._selected_tiles) >= MAX_CONFIGURABLE_TILES:
                checkbox = self._tile_checkboxes[tile_key]
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                self.status_label.setText("You can select up to 8 tiles.")
                self._update_selection_status()
                return
            self._selected_tiles.append(tile_key)
        else:
            if tile_key not in self._selected_tiles:
                return
            self._selected_tiles.remove(tile_key)
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        self.tile_selection_status_label.setText(
            f"Selected {len(self._selected_tiles)} of {MAX_CONFIGURABLE_TILES} tiles.",
        )

    @staticmethod
    def _set_combo_value(
        combo: QComboBox,
        options: tuple[tuple[str, str], ...],
        value: str,
    ) -> None:
        keys = [key for key, _ in options]
        try:
            index = keys.index(value)
        except ValueError:
            index = 0
        combo.setCurrentIndex(index)

    @staticmethod
    def _combo_value(
        combo: QComboBox,
        options: tuple[tuple[str, str], ...],
    ) -> str:
        index = combo.currentIndex()
        if index < 0 or index >= len(options):
            return options[0][0]
        return options[index][0]
