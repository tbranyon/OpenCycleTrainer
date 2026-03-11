from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.storage.settings import AppSettings, load_settings
from .hotkeys import WorkoutHotkeys
from .tile_config import TILE_LABEL_BY_KEY, normalize_tile_selections

MODE_OPTIONS = ("ERG", "Resistance", "Hybrid")


class MetricTile(QFrame):
    def __init__(
        self,
        *,
        title: str,
        key: str,
        prominent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.title_label = QLabel(title, self)
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.value_label = QLabel("--", self)
        self.value_label.setObjectName(f"value_{key}")
        self.value_label.setAlignment(Qt.AlignCenter)
        font = self.value_label.font()
        font.setBold(prominent)
        font.setPointSize(font.pointSize() + (4 if prominent else 1))
        self.value_label.setFont(font)
        layout.addWidget(self.value_label)


class WorkoutScreen(QWidget):
    toggle_mode_requested = Signal(str)
    extend_interval_requested = Signal(int, bool)
    skip_interval_requested = Signal()
    jog_requested = Signal(int)
    pause_resume_requested = Signal()

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        settings_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings if settings is not None else load_settings(settings_path)
        self._selected_tiles = normalize_tile_selections(self._settings.tile_selections)
        self._kj_mode_active = self._settings.default_workout_behavior == "kj_mode"
        self._paused_for_resume_hotkey = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.title_label = QLabel("Workout", self)
        self.title_label.setObjectName("workoutScreenTitle")
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 4)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(self.title_label)

        self._build_control_buttons(root_layout)
        self._build_alert_banner(root_layout)
        self._build_metrics_section(root_layout)
        self._build_chart_scaffolding(root_layout)
        self._build_mode_footer(root_layout)
        self._render_selected_tiles()
        self._wire_button_state_tracking()
        self.hotkeys = WorkoutHotkeys(
            self,
            on_toggle_mode=self._handle_toggle_mode_hotkey,
            on_extend_short=self._handle_extend_short_hotkey,
            on_extend_long=self._handle_extend_long_hotkey,
            on_skip_interval=self._handle_skip_interval_hotkey,
            on_jog_small_up=lambda: self._handle_jog_hotkey(1),
            on_jog_small_down=lambda: self._handle_jog_hotkey(-1),
            on_jog_large_up=lambda: self._handle_jog_hotkey(5),
            on_jog_large_down=lambda: self._handle_jog_hotkey(-5),
            on_pause_resume=self._handle_pause_resume_hotkey,
        )

    def get_selected_tile_keys(self) -> list[str]:
        return list(self._selected_tiles)

    def apply_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._selected_tiles = normalize_tile_selections(settings.tile_selections)
        self._kj_mode_active = settings.default_workout_behavior == "kj_mode"
        self._render_selected_tiles()

    def set_mode_state(self, mode: str) -> None:
        if mode not in MODE_OPTIONS:
            return
        self.mode_state_value.setText(mode)
        if self.mode_selector.currentText() != mode:
            self.mode_selector.setCurrentText(mode)

    def set_opentrueup_offset_watts(self, offset_watts: int | None) -> None:
        if offset_watts is None:
            self.opentrueup_offset_value.setText("-- W")
            return
        self.opentrueup_offset_value.setText(f"{int(offset_watts)} W")

    def show_alert(self, message: str) -> None:
        message_clean = message.strip()
        if not message_clean:
            self.clear_alert()
            return
        self.alert_label.setText(message_clean)
        self.alert_label.setVisible(True)

    def clear_alert(self) -> None:
        self.alert_label.clear()
        self.alert_label.setVisible(False)

    def _build_metrics_section(self, root_layout: QVBoxLayout) -> None:
        self.metrics_widget = QWidget(self)
        metrics_layout = QVBoxLayout(self.metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(8)

        mandatory_row = QHBoxLayout()
        mandatory_row.setSpacing(8)
        self.elapsed_time_tile = MetricTile(title="Time Elapsed", key="time_elapsed", parent=self)
        self.remaining_tile = MetricTile(title="Time Remaining", key="time_remaining", parent=self)
        self.interval_remaining_tile = MetricTile(
            title="Interval Time/Work Remaining",
            key="interval_remaining",
            prominent=True,
            parent=self,
        )

        mandatory_row.addWidget(self.elapsed_time_tile, 2)
        mandatory_row.addWidget(self.interval_remaining_tile, 3)
        mandatory_row.addWidget(self.remaining_tile, 2)
        metrics_layout.addLayout(mandatory_row)

        info_label = QLabel("Configure visible tiles in Settings.", self.metrics_widget)
        info_label.setObjectName("configuredTilesHint")
        info_label.setAlignment(Qt.AlignCenter)
        metrics_layout.addWidget(info_label)

        self.tile_display_widget = QWidget(self.metrics_widget)
        self.tile_display_layout = QGridLayout(self.tile_display_widget)
        self.tile_display_layout.setContentsMargins(0, 0, 0, 0)
        self.tile_display_layout.setHorizontalSpacing(8)
        self.tile_display_layout.setVerticalSpacing(8)
        metrics_layout.addWidget(self.tile_display_widget)

        root_layout.addWidget(self.metrics_widget)

    def _build_control_buttons(self, root_layout: QVBoxLayout) -> None:
        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        controls_row.addStretch(1)

        self.start_button = QPushButton("Start", self)
        self.pause_button = QPushButton("Pause", self)
        self.resume_button = QPushButton("Resume", self)
        self.end_button = QPushButton("Stop", self)

        controls_row.addWidget(self.start_button)
        controls_row.addWidget(self.pause_button)
        controls_row.addWidget(self.resume_button)
        controls_row.addWidget(self.end_button)
        controls_row.addStretch(1)
        root_layout.addLayout(controls_row)

    def _wire_button_state_tracking(self) -> None:
        self.pause_button.clicked.connect(lambda: self._set_paused(True))
        self.resume_button.clicked.connect(lambda: self._set_paused(False))
        self.start_button.clicked.connect(lambda: self._set_paused(False))
        self.end_button.clicked.connect(lambda: self._set_paused(False))

    def _build_alert_banner(self, root_layout: QVBoxLayout) -> None:
        self.alert_label = QLabel("", self)
        self.alert_label.setObjectName("workoutAlertLabel")
        self.alert_label.setVisible(False)
        self.alert_label.setStyleSheet(
            "QLabel#workoutAlertLabel {"
            "color: #9f1d1d;"
            "background-color: #ffe8e8;"
            "border: 1px solid #d33;"
            "border-radius: 4px;"
            "padding: 6px;"
            "}",
        )
        root_layout.addWidget(self.alert_label)

    def _build_chart_scaffolding(self, root_layout: QVBoxLayout) -> None:
        self.interval_chart_group = QGroupBox("Interval Chart", self)
        interval_layout = QVBoxLayout(self.interval_chart_group)
        interval_layout.addWidget(
            QLabel("TODO: Plot 1s power, target power, and HR for the current interval.", self),
        )
        root_layout.addWidget(self.interval_chart_group)

        self.workout_chart_group = QGroupBox("Workout Chart", self)
        workout_layout = QVBoxLayout(self.workout_chart_group)
        workout_layout.addWidget(
            QLabel("TODO: Plot 1s power, target power, and HR for the full workout.", self),
        )
        root_layout.addWidget(self.workout_chart_group)

    def _build_mode_footer(self, root_layout: QVBoxLayout) -> None:
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addStretch(1)

        mode_row.addWidget(QLabel("Trainer Mode:", self))
        self.mode_state_value = QLabel("ERG", self)
        self.mode_state_value.setObjectName("modeStateValue")
        mode_row.addWidget(self.mode_state_value)

        self.mode_selector = QComboBox(self)
        self.mode_selector.addItems(list(MODE_OPTIONS))
        self.mode_selector.currentTextChanged.connect(self.set_mode_state)
        mode_row.addWidget(self.mode_selector)

        mode_row.addSpacing(16)
        mode_row.addWidget(QLabel("OpenTrueUp Offset:", self))
        self.opentrueup_offset_value = QLabel("-- W", self)
        self.opentrueup_offset_value.setObjectName("openTrueUpOffsetValue")
        mode_row.addWidget(self.opentrueup_offset_value)
        mode_row.addStretch(1)
        root_layout.addLayout(mode_row)

    def _render_selected_tiles(self) -> None:
        while self.tile_display_layout.count():
            item = self.tile_display_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._selected_tiles:
            self.tile_display_layout.addWidget(
                QLabel("No configurable tiles selected. Configure them in Settings.", self.tile_display_widget),
                0,
                0,
            )
            return

        for index, key in enumerate(self._selected_tiles):
            row = index // 4
            column = index % 4
            tile = MetricTile(title=TILE_LABEL_BY_KEY[key], key=key, parent=self.tile_display_widget)
            self.tile_display_layout.addWidget(tile, row, column)

    def _set_paused(self, paused: bool) -> None:
        self._paused_for_resume_hotkey = bool(paused)

    def _handle_toggle_mode_hotkey(self) -> None:
        current_mode = self.mode_selector.currentText()
        try:
            current_index = MODE_OPTIONS.index(current_mode)
        except ValueError:
            current_index = 0
        next_mode = MODE_OPTIONS[(current_index + 1) % len(MODE_OPTIONS)]
        self.set_mode_state(next_mode)
        self.toggle_mode_requested.emit(next_mode)

    def _handle_extend_short_hotkey(self) -> None:
        self._emit_extension_request(1)

    def _handle_extend_long_hotkey(self) -> None:
        self._emit_extension_request(5)

    def _emit_extension_request(self, base_value: int) -> None:
        if self._kj_mode_active:
            requested = 10 if base_value == 1 else 50
        else:
            requested = 60 if base_value == 1 else 300
        self.extend_interval_requested.emit(requested, self._kj_mode_active)

    def _handle_skip_interval_hotkey(self) -> None:
        self.skip_interval_requested.emit()

    def _handle_jog_hotkey(self, delta_percent: int) -> None:
        self.jog_requested.emit(int(delta_percent))

    def _handle_pause_resume_hotkey(self) -> None:
        if self._paused_for_resume_hotkey:
            self.resume_button.click()
        else:
            self.pause_button.click()
        self.pause_resume_requested.emit()
