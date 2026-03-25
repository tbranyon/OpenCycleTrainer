from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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

OPENTRUEUP_TOOLTIP = (
    "OpenTrueUp computes the offset between your on-bike power meter and your trainer "
    "and adjusts the ERG target accordingly so that ERG holds the desired power target "
    "according to your on-bike PM"
)


class _AuthUrlDialog(QDialog):
    """Displays the Strava authorization URL so the user can open or copy it."""

    def __init__(self, url: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Authorize Strava")
        self.setMinimumWidth(560)
        self._url = url

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Open this URL in a browser to authorize OpenCycleTrainer with Strava:"))

        url_field = QLineEdit(url, self)
        url_field.setReadOnly(True)
        layout.addWidget(url_field)

        btn_row = QHBoxLayout()

        open_btn = QPushButton("Open in Browser", self)
        open_btn.clicked.connect(self._open_in_browser)
        btn_row.addWidget(open_btn)

        self._copy_btn = QPushButton("Copy to Clipboard", self)
        self._copy_btn.clicked.connect(self._copy_url)
        btn_row.addWidget(self._copy_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def _open_in_browser(self) -> None:
        if not QDesktopServices.openUrl(QUrl(self._url)):
            QMessageBox.warning(
                self,
                "Could Not Open Browser",
                "No browser could be launched. Please copy the URL and open it manually.",
            )

    def _copy_url(self) -> None:
        QApplication.clipboard().setText(self._url)
        self._copy_btn.setText("Copied!")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("Copy to Clipboard"))


class _OAuthWorker(QObject):
    """Runs the blocking OAuth flow off the UI thread."""

    succeeded = Signal(object)  # OAuthResult
    failed = Signal(str)
    url_ready = Signal(str)  # authorization URL, for display if browser does not open

    def __init__(self, credentials: object) -> None:
        super().__init__()
        self._credentials = credentials

    def run(self) -> None:
        try:
            result = run_oauth_flow(  # type: ignore[arg-type]
                self._credentials,
                on_url_ready=self.url_ready.emit,
            )
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
        opentrueup_devices_available: bool = False,
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
        general_layout.addRow("Power Averaging Time (s)", self.windowed_power_window_spinbox)

        self.opentrueup_label = QLabel("OpenTrueUp", general_group)
        self.opentrueup_label.setToolTip(OPENTRUEUP_TOOLTIP)
        self.opentrueup_checkbox = QCheckBox("Enable OpenTrueUp", general_group)
        self.opentrueup_checkbox.setChecked(self._settings.opentrueup_enabled)
        self.opentrueup_checkbox.setToolTip(OPENTRUEUP_TOOLTIP)
        general_layout.addRow(self.opentrueup_label, self.opentrueup_checkbox)

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

        self.status_label = QLabel("Ready.", self)
        self.status_label.setObjectName("settingsStatusLabel")
        root_layout.addWidget(self.status_label)
        root_layout.addStretch(1)

        self._apply_opentrueup_state(opentrueup_devices_available)
        self._connect_autosave_signals()

    def current_settings(self) -> AppSettings:
        return replace(
            self._settings,
            ftp=self.ftp_spinbox.value(),
            lead_time=self.lead_time_spinbox.value(),
            opentrueup_enabled=self.opentrueup_checkbox.isChecked(),
            tile_selections=list(self._selected_tiles),
            windowed_power_window_seconds=self.windowed_power_window_spinbox.value(),
            strava_auto_sync_enabled=self.strava_auto_sync_checkbox.isChecked(),
        )

    def set_tile_selected(self, tile_key: str, selected: bool) -> None:
        checkbox = self._tile_checkboxes.get(tile_key)
        if checkbox is None:
            return
        checkbox.setChecked(selected)

    def set_opentrueup_devices_available(self, available: bool) -> None:
        """Enable or disable the OpenTrueUp checkbox based on connected device availability."""
        self._apply_opentrueup_state(available)

    def _apply_opentrueup_state(self, available: bool) -> None:
        self.opentrueup_checkbox.setEnabled(available)

    def save_current_settings(self) -> AppSettings:
        self._autosave()
        self.status_label.setText("Settings saved.")
        return self._settings

    def _autosave(self) -> None:
        """Persist current widget values immediately and notify listeners."""
        self._settings = self.current_settings()
        save_settings(self._settings, self._settings_path)
        self.settings_applied.emit(self._settings)

    def _connect_autosave_signals(self) -> None:
        """Wire every editable widget to _autosave so changes persist on the fly."""
        self.ftp_spinbox.valueChanged.connect(self._autosave)
        self.lead_time_spinbox.valueChanged.connect(self._autosave)
        self.windowed_power_window_spinbox.valueChanged.connect(self._autosave)
        self.opentrueup_checkbox.toggled.connect(self._autosave)
        self.strava_auto_sync_checkbox.toggled.connect(self._autosave)

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
            QMessageBox.warning(
                self,
                "Strava — Storage Unavailable",
                "Secure credential storage is not available on this system.\n"
                "Strava sync requires either a system keychain or a writable data directory.",
            )
            return
        if not has_app_credentials():
            QMessageBox.warning(
                self,
                "Strava — Credentials Not Configured",
                "Strava app credentials are not configured.\n\n"
                "Set the OCT_STRAVA_CLIENT_ID and OCT_STRAVA_CLIENT_SECRET environment "
                "variables, or create opencycletrainer/integrations/strava/_app_secrets.py "
                "with STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET.",
            )
            return

        credentials = load_app_credentials()
        self.strava_connect_button.setEnabled(False)
        self.status_label.setText("Preparing Strava authorization…")

        self._oauth_thread = QThread(self)
        self._oauth_worker = _OAuthWorker(credentials)
        self._oauth_worker.moveToThread(self._oauth_thread)
        self._oauth_thread.started.connect(self._oauth_worker.run)
        self._oauth_worker.url_ready.connect(self._on_oauth_url_ready)
        self._oauth_worker.succeeded.connect(self._on_oauth_succeeded)
        self._oauth_worker.failed.connect(self._on_oauth_failed)
        self._oauth_worker.succeeded.connect(self._oauth_thread.quit)
        self._oauth_worker.failed.connect(self._oauth_thread.quit)
        self._oauth_thread.start()

    def _on_oauth_url_ready(self, url: str) -> None:
        dialog = _AuthUrlDialog(url, self)
        self._oauth_worker.succeeded.connect(dialog.accept)
        if dialog.exec() == QDialog.DialogCode.Rejected and self._oauth_thread.isRunning():
            # User cancelled before the flow completed; suppress the eventual timeout error.
            self._oauth_cancelled = True

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
        if getattr(self, "_oauth_cancelled", False):
            self._oauth_cancelled = False
            self.status_label.setText("Strava authorization cancelled.")
            return
        self.status_label.setText("Strava connection failed.")
        QMessageBox.warning(self, "Strava — Connection Failed", error_message)

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
        self._autosave()

    def _update_selection_status(self) -> None:
        self.tile_selection_status_label.setText(
            f"Selected {len(self._selected_tiles)} of {MAX_CONFIGURABLE_TILES} tiles.",
        )

