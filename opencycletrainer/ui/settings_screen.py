from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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


class SettingsScreen(QWidget):
    settings_applied = Signal(object)

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        settings_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_path = settings_path
        self._settings = settings if settings is not None else load_settings(settings_path)
        self._selected_tiles = normalize_tile_selections(self._settings.tile_selections)
        self._tile_checkboxes: dict[str, QCheckBox] = {}

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
