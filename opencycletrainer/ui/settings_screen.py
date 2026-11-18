from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer import __version__
from opencycletrainer.core.control.ftms_control import WORK_INTERVAL_MIN_PERCENT_FTP
from opencycletrainer.integrations.strava.app_credentials import (
    has_app_credentials,
    load_app_credentials,
)
from opencycletrainer.integrations.strava.oauth_flow import OAuthResult, run_oauth_flow
from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError
from opencycletrainer.integrations.strava.token_store import clear_tokens, is_available, save_tokens
from opencycletrainer.integrations.intervalsicu.sync_service import (
    DuplicateUploadError as IntervalsIcuDuplicateUploadError,
    validate_api_key,
)
from opencycletrainer.integrations.intervalsicu.key_store import (
    clear_api_key,
    get_api_key,
    save_api_key,
)
from opencycletrainer.storage.paths import get_workout_fit_dir
from opencycletrainer.storage.settings import (
    AppSettings,
    DISPLAY_UNITS_IMPERIAL,
    DISPLAY_UNITS_METRIC,
    JogPersistenceMode,
    MAP_TILE_SOURCE_CYCLOSM,
    MAP_TILE_SOURCE_OPENSTREETMAP,
    MAP_TILE_SOURCE_OPENTOPOMAP,
    MAP_TILE_SOURCE_THUNDERFOREST_CYCLE,
    MAX_BIKE_WEIGHT_KG,
    MAX_COURSE_ZOOM_SPAN,
    MAX_RIDER_WEIGHT_KG,
    MAX_SIMULATION_DIFFICULTY_PERCENT,
    MIN_BIKE_WEIGHT_KG,
    MIN_COURSE_ZOOM_SPAN,
    MIN_RIDER_WEIGHT_KG,
    MIN_SIMULATION_DIFFICULTY_PERCENT,
    ROAD_SURFACE_AGED_ASPHALT,
    ROAD_SURFACE_CHIPSEAL,
    ROAD_SURFACE_GRAVEL,
    ROAD_SURFACE_HARDPACK_GRAVEL,
    ROAD_SURFACE_LOOSE_GRAVEL,
    ROAD_SURFACE_SMOOTH_ROAD,
    THEME_MODE_DARK,
    THEME_MODE_LIGHT,
    THEME_MODE_SYSTEM,
    load_settings,
    save_settings,
)
from .ride_format import distance_unit_label, kilograms_per_weight_unit, weight_unit_label
from .tile_config import MAX_CONFIGURABLE_TILES, TILE_OPTIONS, normalize_tile_selections
from .toggle_switch import ToggleSwitch

OPENTRUEUP_TOOLTIP = (
    "OpenTrueUp computes the offset between your on-bike power meter and your trainer "
    "and adjusts the ERG target accordingly so that ERG holds the desired power target "
    "according to your on-bike PM"
)

SIMULATION_DIFFICULTY_TOOLTIP = (
    "How much of a course's real grade the trainer simulates. At 50% a 10% climb feels "
    "like 5%; your speed on the course is still calculated from the real grade"
)
COURSE_UNITS_TOOLTIP = (
    "Show speed, distance and elevation in miles, mph and feet instead of kilometres, "
    "km/h and metres, and enter weights in pounds instead of kilograms. Recorded ride "
    "files are always metric"
)
WEIGHT_DECIMALS = 1
WEIGHT_STEP_KG = 0.5
WEIGHT_STEP_LB = 1.0
# Weights are kept in kilograms to this precision, finer than the weight fields show, so
# a weight entered in pounds reads back as the same number of pounds.
STORED_WEIGHT_DECIMALS = 2
SIMULATION_DIFFICULTY_STEP_PERCENT = 5
COURSE_ZOOM_SPAN_DECIMALS = 1
COURSE_ZOOM_SPAN_STEP = 0.5
COURSE_ZOOM_SPAN_TOOLTIP = (
    "How much road the zoomed-in course view shows ahead of you, in kilometres or miles"
)
COURSE_GRADE_COLORS_TOOLTIP = (
    "Colour climbs on the course profile: yellow from 3% to 6%, red above 6% to 10%, "
    "dark red above 10%"
)

COURSE_MAP_TOOLTIP = (
    "Show a map of the route beside the plots on course rides. Map tiles are downloaded "
    "as you ride; the route itself is drawn without internet"
)
MAP_TILE_SOURCE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("OpenStreetMap", MAP_TILE_SOURCE_OPENSTREETMAP),
    ("CyclOSM (cycling)", MAP_TILE_SOURCE_CYCLOSM),
    ("OpenTopoMap (terrain)", MAP_TILE_SOURCE_OPENTOPOMAP),
    ("Thunderforest OpenCycleMap", MAP_TILE_SOURCE_THUNDERFOREST_CYCLE),
)
MAP_TILE_SOURCE_TOOLTIP = "Which map the route is drawn over"
THUNDERFOREST_API_KEY_TOOLTIP = (
    "Thunderforest maps need your own API key, free for hobby use from "
    "thunderforest.com. Without one the map uses OpenStreetMap"
)

SPINBOX_MAX_WIDTH = 100
COMBO_MAX_WIDTH = 180
TEXT_FIELD_MAX_WIDTH = 360

# Listed from the fastest-rolling surface to the slowest.
ROAD_SURFACE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Smooth road", ROAD_SURFACE_SMOOTH_ROAD),
    ("Aged asphalt", ROAD_SURFACE_AGED_ASPHALT),
    ("Chipseal", ROAD_SURFACE_CHIPSEAL),
    ("Hardpack gravel", ROAD_SURFACE_HARDPACK_GRAVEL),
    ("Gravel", ROAD_SURFACE_GRAVEL),
    ("Loose gravel", ROAD_SURFACE_LOOSE_GRAVEL),
)
ROAD_SURFACE_TOOLTIP = (
    "The surface being ridden, which sets rolling resistance. A rougher surface lowers "
    "your speed on a course and is also sent to the trainer in Simulation mode"
)

THEME_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Use System Theme", THEME_MODE_SYSTEM),
    ("Light", THEME_MODE_LIGHT),
    ("Dark", THEME_MODE_DARK),
)

JOG_PERSISTENCE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Always", JogPersistenceMode.ALWAYS.value),
    ("Work Intervals Only", JogPersistenceMode.WORK_INTERVALS_ONLY.value),
    ("Never", JogPersistenceMode.NEVER.value),
)

JOG_PERSISTENCE_TOOLTIP = (
    "Controls whether manual ERG power jogs carry over across interval boundaries.\n"
    "Always: jogs persist for the whole workout.\n"
    f"Work Intervals Only: jogs persist into intervals at or above {WORK_INTERVAL_MIN_PERCENT_FTP:g}% FTP.\n"
    "Never: jogs reset at every interval boundary."
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


_READ_API_KEY_FROM_STORE = object()

class SettingsScreen(QWidget):
    settings_applied = Signal(object)
    ftp_edited = Signal(int)  # the rider finished typing a new FTP
    _sync_now_signal = Signal(str)  # "success" | "duplicate" | "error:{msg}"
    _intervals_icu_sync_now_signal = Signal(str)  # "success" | "duplicate" | "error:{msg}"
    _intervals_icu_connect_signal = Signal(str)  # "ok:{name}" | "error:{msg}"

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        settings_path: Path | None = None,
        strava_connected: bool = False,
        strava_sync_fn: object = None,
        intervals_icu_connected: bool = False,
        intervals_icu_sync_fn: object = None,
        opentrueup_devices_available: bool = False,
        parent: QWidget | None = None,
        intervals_icu_api_key: str | None | object = _READ_API_KEY_FROM_STORE,
    ) -> None:
        super().__init__(parent)
        self._settings_path = settings_path
        self._settings = settings if settings is not None else load_settings(settings_path)
        self._strava_sync_fn = strava_sync_fn
        self._intervals_icu_sync_fn = intervals_icu_sync_fn
        self._selected_tiles = normalize_tile_selections(self._settings.tile_selections)
        self._tile_checkboxes: dict[str, QCheckBox] = {}
        self._strava_connected = strava_connected
        self._intervals_icu_connected = intervals_icu_connected
        self._intervals_icu_api_key: str | None = None
        self._oauth_thread: QThread | None = None
        self._sync_now_signal.connect(self._on_sync_now_result)
        self._intervals_icu_sync_now_signal.connect(self._on_intervals_icu_sync_now_result)
        self._intervals_icu_connect_signal.connect(self._on_intervals_icu_connect_result)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        _scroll = QScrollArea(self)
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(_scroll)
        _content = QWidget()
        root_layout = QVBoxLayout(_content)
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
        self.ftp_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        general_layout.addRow("FTP (W)", self.ftp_spinbox)

        self.lead_time_spinbox = QSpinBox(general_group)
        self.lead_time_spinbox.setRange(0, 30)
        self.lead_time_spinbox.setValue(self._settings.lead_time)
        self.lead_time_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        general_layout.addRow("Lead Time (s)", self.lead_time_spinbox)

        self.lead_time_increasing_only_checkbox = ToggleSwitch("Increasing power only", general_group)
        self.lead_time_increasing_only_checkbox.setChecked(self._settings.lead_time_increasing_only)
        general_layout.addRow("Lead Time Direction", self.lead_time_increasing_only_checkbox)

        self.windowed_power_window_spinbox = QSpinBox(general_group)
        self.windowed_power_window_spinbox.setRange(1, 10)
        self.windowed_power_window_spinbox.setValue(self._settings.windowed_power_window_seconds)
        self.windowed_power_window_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        general_layout.addRow("Power Averaging Time (s)", self.windowed_power_window_spinbox)

        self.erg_jog_persistence_mode_combo = QComboBox(general_group)
        for label, value in JOG_PERSISTENCE_OPTIONS:
            self.erg_jog_persistence_mode_combo.addItem(label, value)
        selected_jog_index = self.erg_jog_persistence_mode_combo.findData(
            self._settings.erg_jog_persistence_mode.value
        )
        if selected_jog_index < 0:
            selected_jog_index = self.erg_jog_persistence_mode_combo.findData(JogPersistenceMode.NEVER.value)
        self.erg_jog_persistence_mode_combo.setCurrentIndex(selected_jog_index)
        self.erg_jog_persistence_mode_combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self.erg_jog_persistence_mode_combo.setToolTip(JOG_PERSISTENCE_TOOLTIP)
        general_layout.addRow("Power Jog", self.erg_jog_persistence_mode_combo)

        self.theme_mode_combo = QComboBox(general_group)
        for label, value in THEME_OPTIONS:
            self.theme_mode_combo.addItem(label, value)
        selected_theme_index = self.theme_mode_combo.findData(self._settings.theme_mode)
        if selected_theme_index < 0:
            selected_theme_index = self.theme_mode_combo.findData(THEME_MODE_SYSTEM)
        self.theme_mode_combo.setCurrentIndex(selected_theme_index)
        self.theme_mode_combo.setMaximumWidth(COMBO_MAX_WIDTH)
        general_layout.addRow("Theme", self.theme_mode_combo)

        self.workout_data_dir_edit = QLineEdit(general_group)
        self.workout_data_dir_edit.setMaximumWidth(TEXT_FIELD_MAX_WIDTH)
        if self._settings.workout_data_dir is not None:
            self.workout_data_dir_edit.setText(str(self._settings.workout_data_dir))
        self.workout_data_dir_button = QPushButton("Browse...", general_group)
        self.workout_data_dir_button.clicked.connect(self._browse_workout_data_dir)
        workout_dir_row = QHBoxLayout()
        workout_dir_row.setContentsMargins(0, 0, 0, 0)
        workout_dir_row.addWidget(self.workout_data_dir_edit, 1)
        workout_dir_row.addWidget(self.workout_data_dir_button, 0)
        workout_dir_widget = QWidget(general_group)
        workout_dir_widget.setLayout(workout_dir_row)
        general_layout.addRow("Workout Data Folder", workout_dir_widget)

        self.opentrueup_label = QLabel("OpenTrueUp", general_group)
        self.opentrueup_label.setToolTip(OPENTRUEUP_TOOLTIP)
        self.opentrueup_checkbox = ToggleSwitch("Enable OpenTrueUp", general_group)
        self.opentrueup_checkbox.setChecked(self._settings.opentrueup_enabled)
        self.opentrueup_checkbox.setToolTip(OPENTRUEUP_TOOLTIP)
        general_layout.addRow(self.opentrueup_label, self.opentrueup_checkbox)

        root_layout.addWidget(general_group)

        tiles_group = QGroupBox("Visible Workout Tiles (max 8)", self)
        tiles_layout = QVBoxLayout(tiles_group)
        selector_layout = QGridLayout()
        for index, (key, label) in enumerate(TILE_OPTIONS):
            checkbox = ToggleSwitch(label, tiles_group)
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

        simulation_group = QGroupBox("Grade Simulation", self)
        simulation_layout = QFormLayout(simulation_group)

        # The weight fields show kilograms or pounds; these hold what is saved, in kilograms.
        self._rider_weight_kg = self._settings.rider_weight_kg
        self._bike_weight_kg = self._settings.bike_weight_kg

        self.rider_weight_label = QLabel("", simulation_group)
        self.rider_weight_spinbox = QDoubleSpinBox(simulation_group)
        self.rider_weight_spinbox.setDecimals(WEIGHT_DECIMALS)
        self.rider_weight_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        simulation_layout.addRow(self.rider_weight_label, self.rider_weight_spinbox)

        self.bike_weight_label = QLabel("", simulation_group)
        self.bike_weight_spinbox = QDoubleSpinBox(simulation_group)
        self.bike_weight_spinbox.setDecimals(WEIGHT_DECIMALS)
        self.bike_weight_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        simulation_layout.addRow(self.bike_weight_label, self.bike_weight_spinbox)

        self.simulation_difficulty_spinbox = QSpinBox(simulation_group)
        self.simulation_difficulty_spinbox.setRange(
            MIN_SIMULATION_DIFFICULTY_PERCENT, MAX_SIMULATION_DIFFICULTY_PERCENT
        )
        self.simulation_difficulty_spinbox.setSingleStep(SIMULATION_DIFFICULTY_STEP_PERCENT)
        self.simulation_difficulty_spinbox.setValue(self._settings.simulation_difficulty_percent)
        self.simulation_difficulty_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        self.simulation_difficulty_spinbox.setToolTip(SIMULATION_DIFFICULTY_TOOLTIP)
        simulation_layout.addRow("Trainer Difficulty (%)", self.simulation_difficulty_spinbox)

        self.road_surface_combo = QComboBox(simulation_group)
        for label, value in ROAD_SURFACE_OPTIONS:
            self.road_surface_combo.addItem(label, value)
        selected_surface_index = self.road_surface_combo.findData(self._settings.road_surface)
        if selected_surface_index < 0:
            selected_surface_index = self.road_surface_combo.findData(ROAD_SURFACE_SMOOTH_ROAD)
        self.road_surface_combo.setCurrentIndex(selected_surface_index)
        self.road_surface_combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self.road_surface_combo.setToolTip(ROAD_SURFACE_TOOLTIP)
        simulation_layout.addRow("Road Surface", self.road_surface_combo)

        self.imperial_units_checkbox = ToggleSwitch("Imperial (mi, mph, ft, lb)", simulation_group)
        self.imperial_units_checkbox.setChecked(
            self._settings.display_units == DISPLAY_UNITS_IMPERIAL
        )
        self.imperial_units_checkbox.setToolTip(COURSE_UNITS_TOOLTIP)
        simulation_layout.addRow("Units", self.imperial_units_checkbox)
        self._show_weights_in_display_units()

        root_layout.addWidget(simulation_group)

        charts_group = QGroupBox("Charts", self)
        charts_layout = QFormLayout(charts_group)
        self.show_interval_plot_checkbox = ToggleSwitch("Show interval plot", charts_group)
        self.show_interval_plot_checkbox.setChecked(self._settings.show_interval_plot)
        charts_layout.addRow(self.show_interval_plot_checkbox)
        self.course_grade_colors_checkbox = ToggleSwitch("Colour climbs by grade", charts_group)
        self.course_grade_colors_checkbox.setChecked(self._settings.course_grade_colors)
        self.course_grade_colors_checkbox.setToolTip(COURSE_GRADE_COLORS_TOOLTIP)
        charts_layout.addRow(self.course_grade_colors_checkbox)
        self.course_zoom_span_label = QLabel("", charts_group)
        self.course_zoom_span_spinbox = QDoubleSpinBox(charts_group)
        self.course_zoom_span_spinbox.setDecimals(COURSE_ZOOM_SPAN_DECIMALS)
        self.course_zoom_span_spinbox.setRange(MIN_COURSE_ZOOM_SPAN, MAX_COURSE_ZOOM_SPAN)
        self.course_zoom_span_spinbox.setSingleStep(COURSE_ZOOM_SPAN_STEP)
        self.course_zoom_span_spinbox.setValue(self._settings.course_zoom_span)
        self.course_zoom_span_spinbox.setMaximumWidth(SPINBOX_MAX_WIDTH)
        self.course_zoom_span_spinbox.setToolTip(COURSE_ZOOM_SPAN_TOOLTIP)
        charts_layout.addRow(self.course_zoom_span_label, self.course_zoom_span_spinbox)
        self._label_course_zoom_span()

        self.course_map_checkbox = ToggleSwitch("Show map on course rides", charts_group)
        self.course_map_checkbox.setChecked(self._settings.course_map_enabled)
        self.course_map_checkbox.setToolTip(COURSE_MAP_TOOLTIP)
        charts_layout.addRow(self.course_map_checkbox)
        self.map_tile_source_combo = QComboBox(charts_group)
        for label, value in MAP_TILE_SOURCE_OPTIONS:
            self.map_tile_source_combo.addItem(label, value)
        self.map_tile_source_combo.setCurrentIndex(
            max(self.map_tile_source_combo.findData(self._settings.map_tile_source), 0)
        )
        self.map_tile_source_combo.setMaximumWidth(COMBO_MAX_WIDTH)
        self.map_tile_source_combo.setToolTip(MAP_TILE_SOURCE_TOOLTIP)
        charts_layout.addRow("Map Tiles", self.map_tile_source_combo)
        self.thunderforest_api_key_edit = QLineEdit(charts_group)
        self.thunderforest_api_key_edit.setMaximumWidth(TEXT_FIELD_MAX_WIDTH)
        self.thunderforest_api_key_edit.setEchoMode(QLineEdit.Password)
        self.thunderforest_api_key_edit.setPlaceholderText("Paste your Thunderforest API key")
        self.thunderforest_api_key_edit.setText(self._settings.thunderforest_api_key)
        self.thunderforest_api_key_edit.setToolTip(THUNDERFOREST_API_KEY_TOOLTIP)
        charts_layout.addRow("Thunderforest API Key", self.thunderforest_api_key_edit)
        self._update_map_source_controls()
        root_layout.addWidget(charts_group)

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

        self.strava_auto_sync_checkbox = ToggleSwitch("Automatically sync rides with Strava", strava_group)
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

        intervals_icu_group = QGroupBox("intervals.icu", self)
        intervals_icu_layout = QFormLayout(intervals_icu_group)

        self.intervals_icu_status_label = QLabel("", intervals_icu_group)
        self.intervals_icu_status_label.setObjectName("intervalsIcuStatusLabel")
        intervals_icu_layout.addRow("Status", self.intervals_icu_status_label)

        self.intervals_icu_api_key_edit = QLineEdit(intervals_icu_group)
        self.intervals_icu_api_key_edit.setMaximumWidth(TEXT_FIELD_MAX_WIDTH)
        self.intervals_icu_api_key_edit.setEchoMode(QLineEdit.Password)
        self.intervals_icu_api_key_edit.setPlaceholderText(
            "Paste your API key (intervals.icu → Settings → Developer Settings)"
        )
        # The main window passes the key it already read, sparing a second keyring lookup.
        existing_key = (
            get_api_key()
            if intervals_icu_api_key is _READ_API_KEY_FROM_STORE
            else intervals_icu_api_key
        )
        if existing_key:
            self.intervals_icu_api_key_edit.setText(existing_key)
            self._intervals_icu_api_key = existing_key
        intervals_icu_layout.addRow("API Key", self.intervals_icu_api_key_edit)

        self.intervals_icu_connect_button = QPushButton("Connect", intervals_icu_group)
        self.intervals_icu_connect_button.clicked.connect(self._on_intervals_icu_connect)
        intervals_icu_layout.addRow(self.intervals_icu_connect_button)

        self.intervals_icu_disconnect_button = QPushButton("Disconnect", intervals_icu_group)
        self.intervals_icu_disconnect_button.clicked.connect(self.disconnect_intervals_icu)
        intervals_icu_layout.addRow(self.intervals_icu_disconnect_button)

        self.intervals_icu_auto_sync_checkbox = ToggleSwitch(
            "Automatically sync rides with intervals.icu", intervals_icu_group
        )
        self.intervals_icu_auto_sync_checkbox.setChecked(
            self._settings.intervals_icu_auto_sync_enabled
        )
        intervals_icu_layout.addRow(self.intervals_icu_auto_sync_checkbox)

        self.intervals_icu_sync_now_button = QPushButton("Sync now", intervals_icu_group)
        self.intervals_icu_sync_now_button.clicked.connect(self._on_intervals_icu_sync_now)
        intervals_icu_layout.addRow(self.intervals_icu_sync_now_button)

        root_layout.addWidget(intervals_icu_group)
        self._apply_intervals_icu_connected_state(
            self._intervals_icu_connected,
            self._settings.intervals_icu_athlete_name,
        )

        self.status_label = QLabel("Ready.", self)
        self.status_label.setObjectName("settingsStatusLabel")
        root_layout.addWidget(self.status_label)
        root_layout.addStretch(1)

        self.version_label = QLabel(f"Version {__version__}", self)
        self.version_label.setObjectName("settingsVersionLabel")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        version_font = self.version_label.font()
        version_font.setPointSize(max(version_font.pointSize() - 1, 1))
        self.version_label.setFont(version_font)
        root_layout.addWidget(self.version_label)

        _scroll.setWidget(_content)
        self._apply_opentrueup_state(opentrueup_devices_available)
        self._connect_autosave_signals()

    def current_settings(self) -> AppSettings:
        workout_data_dir_text = self.workout_data_dir_edit.text().strip()
        return replace(
            self._settings,
            ftp=self.ftp_spinbox.value(),
            lead_time=self.lead_time_spinbox.value(),
            lead_time_increasing_only=self.lead_time_increasing_only_checkbox.isChecked(),
            opentrueup_enabled=self.opentrueup_checkbox.isChecked(),
            tile_selections=list(self._selected_tiles),
            theme_mode=str(self.theme_mode_combo.currentData()),
            windowed_power_window_seconds=self.windowed_power_window_spinbox.value(),
            workout_data_dir=Path(workout_data_dir_text) if workout_data_dir_text else None,
            strava_auto_sync_enabled=self.strava_auto_sync_checkbox.isChecked(),
            intervals_icu_auto_sync_enabled=self.intervals_icu_auto_sync_checkbox.isChecked(),
            show_interval_plot=self.show_interval_plot_checkbox.isChecked(),
            erg_jog_persistence_mode=JogPersistenceMode(str(self.erg_jog_persistence_mode_combo.currentData())),
            rider_weight_kg=self._rider_weight_kg,
            bike_weight_kg=self._bike_weight_kg,
            simulation_difficulty_percent=self.simulation_difficulty_spinbox.value(),
            display_units=self._selected_display_units(),
            road_surface=str(self.road_surface_combo.currentData()),
            course_zoom_span=self.course_zoom_span_spinbox.value(),
            course_grade_colors=self.course_grade_colors_checkbox.isChecked(),
            course_map_enabled=self.course_map_checkbox.isChecked(),
            map_tile_source=str(self.map_tile_source_combo.currentData()),
            thunderforest_api_key=self.thunderforest_api_key_edit.text().strip(),
        )

    def _selected_display_units(self) -> str:
        """Return the display units the units toggle currently selects."""
        if self.imperial_units_checkbox.isChecked():
            return DISPLAY_UNITS_IMPERIAL
        return DISPLAY_UNITS_METRIC

    def _show_weights_in_display_units(self) -> None:
        """Label, limit and fill the weight fields in the selected units.

        Only what is shown changes; the saved weights are left exactly as they were.
        """
        units = self._selected_display_units()
        kg_per_unit = kilograms_per_weight_unit(units)
        step = WEIGHT_STEP_LB if units == DISPLAY_UNITS_IMPERIAL else WEIGHT_STEP_KG
        shown_steps = 10 ** WEIGHT_DECIMALS
        fields = (
            (self.rider_weight_label, self.rider_weight_spinbox, "Rider Weight",
             self._rider_weight_kg, MIN_RIDER_WEIGHT_KG, MAX_RIDER_WEIGHT_KG),
            (self.bike_weight_label, self.bike_weight_spinbox, "Bike Weight",
             self._bike_weight_kg, MIN_BIKE_WEIGHT_KG, MAX_BIKE_WEIGHT_KG),
        )
        for label, spinbox, title, weight_kg, min_kg, max_kg in fields:
            label.setText(f"{title} ({weight_unit_label(units)})")
            # Limits are rounded inward so the largest and smallest entries stay within
            # the allowed weights once converted back to kilograms.
            minimum = math.ceil(min_kg / kg_per_unit * shown_steps) / shown_steps
            maximum = math.floor(max_kg / kg_per_unit * shown_steps) / shown_steps
            was_blocked = spinbox.blockSignals(True)
            spinbox.setRange(minimum, maximum)
            spinbox.setSingleStep(step)
            spinbox.setValue(weight_kg / kg_per_unit)
            spinbox.blockSignals(was_blocked)

    def _weight_kg_shown_in(self, spinbox: QDoubleSpinBox) -> float:
        """Return the weight a field shows, converted to kilograms."""
        kg_per_unit = kilograms_per_weight_unit(self._selected_display_units())
        return round(spinbox.value() * kg_per_unit, STORED_WEIGHT_DECIMALS)

    def _on_rider_weight_edited(self) -> None:
        self._rider_weight_kg = self._weight_kg_shown_in(self.rider_weight_spinbox)
        self._autosave()

    def _on_bike_weight_edited(self) -> None:
        self._bike_weight_kg = self._weight_kg_shown_in(self.bike_weight_spinbox)
        self._autosave()

    def _on_units_toggled(self) -> None:
        self._show_weights_in_display_units()
        self._label_course_zoom_span()
        self._autosave()

    def _label_course_zoom_span(self) -> None:
        """Name the zoomed course span's unit; the number keeps its value in either unit."""
        unit = distance_unit_label(self._selected_display_units())
        self.course_zoom_span_label.setText(f"Zoomed Course Span ({unit})")

    def set_ftp(self, watts: int) -> None:
        """Set FTP from code (not typed by the rider); saved and applied like any edit."""
        self.ftp_spinbox.setValue(int(watts))

    def set_intervals_icu_declined_ftp(self, watts: int | None) -> None:
        """Remember the intervals.icu FTP the rider chose not to adopt."""
        self._settings = replace(self._settings, intervals_icu_declined_ftp=watts)
        self._autosave()

    def set_course_map_layout(self, *, width_px: int | None, collapsed: bool) -> None:
        """Remember the map panel's width and whether it is collapsed, for the next course ride."""
        if (width_px, collapsed) == (
            self._settings.course_map_width_px,
            self._settings.course_map_collapsed,
        ):
            return
        self._settings = replace(
            self._settings, course_map_width_px=width_px, course_map_collapsed=collapsed
        )
        save_settings(self._settings, self._settings_path)

    def _update_map_source_controls(self) -> None:
        """Offer the map options only while the map is on, and the API key only for Thunderforest."""
        map_on = self.course_map_checkbox.isChecked()
        self.map_tile_source_combo.setEnabled(map_on)
        self.thunderforest_api_key_edit.setEnabled(
            map_on and self.map_tile_source_combo.currentData() == MAP_TILE_SOURCE_THUNDERFOREST_CYCLE
        )

    def _on_map_setting_changed(self) -> None:
        self._update_map_source_controls()
        self._autosave()

    def connected_intervals_icu_api_key(self) -> str | None:
        """Return the validated intervals.icu API key, or None when not connected."""
        return self._intervals_icu_api_key if self._intervals_icu_connected else None

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
        self.ftp_spinbox.editingFinished.connect(
            lambda: self.ftp_edited.emit(self.ftp_spinbox.value())
        )
        self.lead_time_spinbox.valueChanged.connect(self._autosave)
        self.lead_time_increasing_only_checkbox.toggled.connect(self._autosave)
        self.windowed_power_window_spinbox.valueChanged.connect(self._autosave)
        self.erg_jog_persistence_mode_combo.currentIndexChanged.connect(self._autosave)
        self.theme_mode_combo.currentIndexChanged.connect(self._autosave)
        self.workout_data_dir_edit.editingFinished.connect(self._autosave)
        self.opentrueup_checkbox.toggled.connect(self._autosave)
        self.strava_auto_sync_checkbox.toggled.connect(self._autosave)
        self.intervals_icu_auto_sync_checkbox.toggled.connect(self._autosave)
        self.show_interval_plot_checkbox.toggled.connect(self._autosave)
        self.course_grade_colors_checkbox.toggled.connect(self._autosave)
        self.course_zoom_span_spinbox.valueChanged.connect(self._autosave)
        self.course_map_checkbox.toggled.connect(self._on_map_setting_changed)
        self.map_tile_source_combo.currentIndexChanged.connect(self._on_map_setting_changed)
        self.thunderforest_api_key_edit.editingFinished.connect(self._autosave)
        self.rider_weight_spinbox.valueChanged.connect(self._on_rider_weight_edited)
        self.bike_weight_spinbox.valueChanged.connect(self._on_bike_weight_edited)
        self.simulation_difficulty_spinbox.valueChanged.connect(self._autosave)
        self.imperial_units_checkbox.toggled.connect(self._on_units_toggled)
        self.road_surface_combo.currentIndexChanged.connect(self._autosave)

    def _browse_workout_data_dir(self) -> None:
        start_dir_text = self.workout_data_dir_edit.text().strip()
        start_dir = start_dir_text if start_dir_text else str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Workout Data Folder",
            start_dir,
        )
        if not selected:
            return
        self.workout_data_dir_edit.setText(selected)
        self._autosave()

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
        default_dir = str(get_workout_fit_dir(self.current_settings().workout_data_dir))
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

    def _apply_intervals_icu_connected_state(self, connected: bool, athlete_name: str) -> None:
        self._intervals_icu_connected = connected
        if connected:
            label = f"Connected as {athlete_name}" if athlete_name else "Connected"
        else:
            label = "Not connected"
        self.intervals_icu_status_label.setText(label)
        self.intervals_icu_connect_button.setEnabled(True)
        self.intervals_icu_disconnect_button.setVisible(connected)
        self.intervals_icu_auto_sync_checkbox.setEnabled(connected)
        self.intervals_icu_sync_now_button.setEnabled(connected)

    def _on_intervals_icu_connect(self) -> None:
        """Validate the entered API key off-thread and store it on success."""
        api_key = self.intervals_icu_api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self,
                "intervals.icu — API Key Required",
                "Enter your intervals.icu API key first.\n\n"
                "Find it at intervals.icu → Settings → Developer Settings.",
            )
            return
        self.intervals_icu_connect_button.setEnabled(False)
        self.status_label.setText("Connecting to intervals.icu…")

        signal = self._intervals_icu_connect_signal

        def _run() -> None:
            try:
                name = validate_api_key(api_key)
                signal.emit(f"ok:{name}")
            except Exception as exc:  # noqa: BLE001
                signal.emit(f"error:{exc}")

        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intervals_icu_connect")
        executor.submit(_run)
        executor.shutdown(wait=False)

    def _on_intervals_icu_connect_result(self, result: str) -> None:
        if result.startswith("ok:"):
            athlete_name = result[len("ok:"):]
            self._intervals_icu_api_key = self.intervals_icu_api_key_edit.text().strip()
            save_api_key(self._intervals_icu_api_key)
            self._settings = replace(self._settings, intervals_icu_athlete_name=athlete_name)
            save_settings(self._settings, self._settings_path)
            self._apply_intervals_icu_connected_state(True, athlete_name)
            self.status_label.setText("intervals.icu connected.")
        else:
            self.intervals_icu_connect_button.setEnabled(True)
            msg = result[len("error:"):] if result.startswith("error:") else result
            self.status_label.setText("intervals.icu connection failed.")
            QMessageBox.warning(self, "intervals.icu — Connection Failed", msg)

    def disconnect_intervals_icu(self) -> None:
        """Clear the stored API key and update the UI to the disconnected state."""
        clear_api_key()
        self._intervals_icu_api_key = None
        self.intervals_icu_api_key_edit.clear()
        self._settings = replace(
            self._settings,
            intervals_icu_athlete_name="",
            intervals_icu_auto_sync_enabled=False,
            intervals_icu_declined_ftp=None,
        )
        save_settings(self._settings, self._settings_path)
        self._apply_intervals_icu_connected_state(False, "")

    def _on_intervals_icu_sync_now(self) -> None:
        """Open a FIT file picker and enqueue the selected file for intervals.icu upload."""
        default_dir = str(get_workout_fit_dir(self.current_settings().workout_data_dir))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select FIT File to Sync",
            default_dir,
            "FIT Files (*.fit)",
        )
        if not path or self._intervals_icu_sync_fn is None:
            return
        self.intervals_icu_sync_now_button.setEnabled(False)
        self.status_label.setText("Syncing to intervals.icu…")

        fit_path = Path(path)
        sync_fn = self._intervals_icu_sync_fn
        signal = self._intervals_icu_sync_now_signal

        def _run() -> None:
            try:
                sync_fn(fit_path)  # type: ignore[operator]
                signal.emit("success")
            except IntervalsIcuDuplicateUploadError:
                signal.emit("duplicate")
            except Exception as exc:  # noqa: BLE001
                signal.emit(f"error:{exc}")

        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intervals_icu_sync_now")
        executor.submit(_run)
        executor.shutdown(wait=False)

    def _on_intervals_icu_sync_now_result(self, result: str) -> None:
        self.intervals_icu_sync_now_button.setEnabled(True)
        if result == "success":
            self.status_label.setText("Ride synced to intervals.icu.")
        elif result == "duplicate":
            self.status_label.setText("Ride already synced to intervals.icu.")
        else:
            msg = result[len("error:"):] if result.startswith("error:") else result
            self.status_label.setText(f"intervals.icu sync failed: {msg}")

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

