from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.workout_model import Workout
from opencycletrainer.storage.settings import AppSettings, load_settings
from .hotkeys import WorkoutHotkeys
from .tile_config import TILE_LABEL_BY_KEY, normalize_tile_selections
from .workout_chart import WorkoutChartWidget

MODE_OPTIONS = ("ERG", "Resistance", "Hybrid")


class PauseDialog(QDialog):
    """Dialog shown when the workout is paused. Provides a 3-2-1 countdown before resuming."""

    resume_confirmed = Signal()
    resume_started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workout Paused")
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)
        layout.setContentsMargins(48, 32, 48, 32)

        paused_label = QLabel("Workout Paused", self)
        paused_label.setAlignment(Qt.AlignCenter)
        font = paused_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 6)
        paused_label.setFont(font)
        layout.addWidget(paused_label)

        self.countdown_label = QLabel("", self)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        font = self.countdown_label.font()
        font.setPointSize(font.pointSize() + 12)
        self.countdown_label.setFont(font)
        layout.addWidget(self.countdown_label)

        self.resume_button = QPushButton("Resume", self)
        self.resume_button.setDefault(True)
        self.resume_button.clicked.connect(self._on_resume_clicked)
        layout.addWidget(self.resume_button)

        self._countdown_value = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)

    def _on_resume_clicked(self) -> None:
        """Disable the resume button, signal resume start, and begin the 3-2-1 countdown."""
        self.resume_button.setEnabled(False)
        self.resume_started.emit()
        self._countdown_value = 3
        self.countdown_label.setText(str(self._countdown_value))
        self._countdown_timer.start()

    def _tick_countdown(self) -> None:
        """Decrement the countdown; emit resume_confirmed and close when it reaches zero."""
        self._countdown_value -= 1
        if self._countdown_value <= 0:
            self._countdown_timer.stop()
            self.resume_confirmed.emit()
            self.accept()
        else:
            self.countdown_label.setText(str(self._countdown_value))


class MetricTile(QFrame):
    """A single metric display tile showing a title and live value. Supports drag-to-reorder."""

    drag_requested = Signal(str)  # emits tile key when drag threshold is crossed

    _DRAG_THRESHOLD = 6

    def __init__(
        self,
        *,
        title: str,
        key: str,
        prominent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._drag_start_pos: QPoint | None = None
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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.position().toPoint() - self._drag_start_pos
            if delta.manhattanLength() >= self._DRAG_THRESHOLD:
                self._drag_start_pos = None
                self.drag_requested.emit(self.key)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class WorkoutScreen(QWidget):
    toggle_mode_requested = Signal(str)
    extend_interval_requested = Signal(int, bool)
    skip_interval_requested = Signal()
    jog_requested = Signal(int)
    pause_resume_requested = Signal()
    load_workout_requested = Signal()
    load_from_library_requested = Signal()
    tile_order_changed = Signal(list)  # emits new list[str] of tile keys after drag reorder

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
        self._drag_source_key: str | None = None
        self._drag_ghost: QLabel | None = None
        self._drag_target_key: str | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.title_widget = QStackedWidget(self)
        self.title_label = QLabel("Workout", self)
        self.title_label.setObjectName("workoutScreenTitle")
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 4)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignCenter)

        self.load_buttons_widget = QWidget(self)
        load_buttons_layout = QVBoxLayout(self.load_buttons_widget)
        load_buttons_layout.setContentsMargins(0, 0, 0, 0)
        load_buttons_layout.setSpacing(4)
        self.load_from_library_button = QPushButton("Load from Library", self)
        self.load_from_library_button.setObjectName("loadFromLibraryButton")
        font = self.load_from_library_button.font()
        font.setPointSize(font.pointSize() + 2)
        self.load_from_library_button.setFont(font)
        self.load_from_library_button.clicked.connect(self.load_from_library_requested)
        self.load_from_file_button = QPushButton("Load from File", self)
        self.load_from_file_button.setObjectName("loadFromFileButton")
        self.load_from_file_button.setFont(font)
        self.load_from_file_button.clicked.connect(self.load_workout_requested)
        load_buttons_layout.addWidget(self.load_from_library_button)
        load_buttons_layout.addWidget(self.load_from_file_button)

        self.title_widget.addWidget(self.title_label)
        self.title_widget.addWidget(self.load_buttons_widget)
        self.title_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        root_layout.addWidget(self.title_widget)

        self._tile_by_key: dict[str, MetricTile] = {}
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

    def set_workout_name(self, workout_name: str | None) -> None:
        name = str(workout_name or "").strip()
        if name:
            self.title_label.setText(name)
            self.title_widget.setCurrentWidget(self.title_label)
        else:
            self.title_widget.setCurrentWidget(self.load_buttons_widget)

    def set_mandatory_metrics(
        self,
        *,
        elapsed_text: str,
        remaining_text: str,
        interval_remaining_text: str,
        target_power_text: str,
    ) -> None:
        self.elapsed_time_tile.value_label.setText(elapsed_text)
        self.target_power_tile.value_label.setText(target_power_text)
        self.remaining_tile.value_label.setText(remaining_text)
        self.interval_remaining_tile.value_label.setText(interval_remaining_text)

    def set_session_state(self, state: str) -> None:
        state_key = str(state).strip().lower()
        can_start = state_key in {"idle", "ready", "stopped", "finished"}
        can_pause = state_key in {"running", "ramp_in"}
        can_resume = state_key == "paused"
        can_stop = state_key in {"running", "ramp_in", "paused"}

        self.start_button.setEnabled(can_start)
        self.pause_button.setEnabled(can_pause)
        self.resume_button.setEnabled(can_resume)
        self.end_button.setEnabled(can_stop)

    def set_mode_state(self, mode: str) -> None:
        if mode not in MODE_OPTIONS:
            return
        if self.mode_selector.currentText() != mode:
            self.mode_selector.setCurrentText(mode)

    def set_resistance_level(self, level: int | None) -> None:
        """Show the resistance level label with the given percentage, or hide it if None."""
        if level is None:
            self.resistance_level_label.setVisible(False)
            return
        self.resistance_level_label.setText(f"{level} %")
        self.resistance_level_label.setVisible(True)

    def set_opentrueup_offset_watts(self, offset_watts: int | None) -> None:
        if offset_watts is None:
            self.opentrueup_offset_value.setText("-- W")
            return
        self.opentrueup_offset_value.setText(f"{int(offset_watts)} W")

    _ALERT_STYLES = {
        "error": (
            "QLabel#workoutAlertLabel {"
            "color: #9f1d1d;"
            "background-color: #ffe8e8;"
            "border: 1px solid #d33;"
            "border-radius: 4px;"
            "padding: 6px;"
            "}"
        ),
        "success": (
            "QLabel#workoutAlertLabel {"
            "color: #1a7f37;"
            "background-color: #e6ffed;"
            "border: 1px solid #2da44e;"
            "border-radius: 4px;"
            "padding: 6px;"
            "}"
        ),
    }

    def show_alert(self, message: str, alert_type: str = "error") -> None:
        """Show a banner alert. alert_type is 'error' or 'success'. Auto-dismisses after 5s; click to dismiss early."""
        message_clean = message.strip()
        if not message_clean:
            self.clear_alert()
            return
        style = self._ALERT_STYLES.get(alert_type, self._ALERT_STYLES["error"])
        self.alert_label.setStyleSheet(style)
        self.alert_label.setText(message_clean)
        self.alert_label.setVisible(True)
        self._alert_timer.start()

    def clear_alert(self) -> None:
        self._alert_timer.stop()
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
        self.target_power_tile = MetricTile(title="Target Power", key="target_power", parent=self)
        self.interval_remaining_tile = MetricTile(
            title="Interval Time/Work Remaining",
            key="interval_remaining",
            prominent=True,
            parent=self,
        )
        self.remaining_tile = MetricTile(title="Time Remaining", key="time_remaining", parent=self)

        mandatory_row.addWidget(self.elapsed_time_tile, 2)
        mandatory_row.addWidget(self.target_power_tile, 2)
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
        self.alert_label.setCursor(Qt.PointingHandCursor)
        self.alert_label.mousePressEvent = lambda _: self.clear_alert()
        root_layout.addWidget(self.alert_label)

        self._alert_timer = QTimer(self)
        self._alert_timer.setSingleShot(True)
        self._alert_timer.setInterval(5000)
        self._alert_timer.timeout.connect(self.clear_alert)

    def load_workout_chart(self, workout: Workout, ftp_watts: int) -> None:
        self.chart_widget.load_workout(workout, ftp_watts)

    def update_charts(
        self,
        elapsed_seconds: float,
        current_interval_index: int | None,
        power_series: list[tuple[float, int]],
        hr_series: list[tuple[float, int]],
    ) -> None:
        self.chart_widget.update_charts(elapsed_seconds, current_interval_index, power_series, hr_series)

    def add_skip_marker(self, elapsed_before: float, elapsed_after: float) -> None:
        self.chart_widget.add_skip_marker(elapsed_before, elapsed_after)

    def export_chart_image(self, path: Path) -> Path:
        """Capture the workout overview chart as a PNG and save it to *path*."""
        return self.chart_widget.export_image(path)

    def clear_charts(self) -> None:
        self.chart_widget.clear()

    def _build_chart_scaffolding(self, root_layout: QVBoxLayout) -> None:
        self.chart_widget = WorkoutChartWidget(self)
        root_layout.addWidget(self.chart_widget, stretch=1)

    def set_trainer_controls_visible(self, visible: bool) -> None:
        """Show or hide the trainer mode and OpenTrueUp footer controls."""
        self.trainer_mode_label.setVisible(visible)
        self.mode_selector.setVisible(visible)
        self.opentrueup_label.setVisible(visible)
        self.opentrueup_offset_value.setVisible(visible)
        if not visible:
            self.resistance_level_label.setVisible(False)

    def _build_mode_footer(self, root_layout: QVBoxLayout) -> None:
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addStretch(1)

        self.trainer_mode_label = QLabel("Trainer Mode:", self)
        mode_row.addWidget(self.trainer_mode_label)
        self.mode_selector = QComboBox(self)
        self.mode_selector.addItems(list(MODE_OPTIONS))
        self.mode_selector.currentTextChanged.connect(self.set_mode_state)
        mode_row.addWidget(self.mode_selector)

        self.resistance_level_label = QLabel("-- %", self)
        self.resistance_level_label.setObjectName("resistanceLevelLabel")
        self.resistance_level_label.setVisible(False)
        mode_row.addWidget(self.resistance_level_label)

        mode_row.addSpacing(16)
        self.opentrueup_label = QLabel("OpenTrueUp Offset:", self)
        mode_row.addWidget(self.opentrueup_label)
        self.opentrueup_offset_value = QLabel("-- W", self)
        self.opentrueup_offset_value.setObjectName("openTrueUpOffsetValue")
        mode_row.addWidget(self.opentrueup_offset_value)
        mode_row.addStretch(1)
        root_layout.addLayout(mode_row)

        # Hidden until a controllable trainer is connected
        self.set_trainer_controls_visible(False)

    def set_tile_value(self, key: str, text: str) -> None:
        tile = self._tile_by_key.get(key)
        if tile is not None:
            tile.value_label.setText(text)

    def _render_selected_tiles(self) -> None:
        self._tile_by_key = {}
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
            tile.drag_requested.connect(self._on_drag_started)
            self._tile_by_key[key] = tile
            self.tile_display_layout.addWidget(tile, row, column)

    # --- Tile drag-to-reorder ---

    _DRAG_TARGET_STYLE = (
        "QFrame { border: 2px dashed #5b9bd5; background-color: rgba(91, 155, 213, 0.1); }"
    )
    _DRAG_FLASH_STYLE = "QFrame { background-color: rgba(91, 155, 213, 0.3); }"
    _DRAG_FLASH_MS = 300

    def reorder_tiles(self, from_key: str, to_key: str) -> None:
        """Swap two tiles by key and emit tile_order_changed. No-op if keys are identical or not both present."""
        if from_key == to_key:
            return
        if from_key not in self._selected_tiles or to_key not in self._selected_tiles:
            return
        src_idx = self._selected_tiles.index(from_key)
        tgt_idx = self._selected_tiles.index(to_key)
        self._selected_tiles[src_idx], self._selected_tiles[tgt_idx] = (
            self._selected_tiles[tgt_idx],
            self._selected_tiles[src_idx],
        )
        self._settings.tile_selections = list(self._selected_tiles)
        self._render_selected_tiles()
        self._flash_tile(from_key)
        self.tile_order_changed.emit(list(self._selected_tiles))

    def _on_drag_started(self, key: str) -> None:
        """Begin a tile drag: create a ghost overlay, dim the source tile, and grab mouse input."""
        if key not in self._tile_by_key:
            return
        self._drag_source_key = key
        source_tile = self._tile_by_key[key]

        pixmap = source_tile.grab()
        self._drag_ghost = QLabel(self)
        self._drag_ghost.setPixmap(pixmap)
        self._drag_ghost.resize(source_tile.size())
        self._drag_ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        effect = QGraphicsOpacityEffect(self._drag_ghost)
        effect.setOpacity(0.75)
        self._drag_ghost.setGraphicsEffect(effect)

        cursor_local = self.mapFromGlobal(QCursor.pos())
        self._drag_ghost.move(
            cursor_local - QPoint(self._drag_ghost.width() // 2, self._drag_ghost.height() // 2)
        )
        self._drag_ghost.raise_()
        self._drag_ghost.show()

        dim = QGraphicsOpacityEffect(source_tile)
        dim.setOpacity(0.35)
        source_tile.setGraphicsEffect(dim)

        self.grabMouse()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_ghost is not None:
            cursor_pos = event.position().toPoint()
            self._drag_ghost.move(
                cursor_pos - QPoint(self._drag_ghost.width() // 2, self._drag_ghost.height() // 2)
            )
            self._update_drag_target(cursor_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_ghost is not None and event.button() == Qt.LeftButton:
            self._complete_drag(self._drag_target_key)
        super().mouseReleaseEvent(event)

    def _update_drag_target(self, cursor_pos: QPoint) -> None:
        """Hit-test cursor against configurable tiles and update the drop-target highlight."""
        child = self.childAt(cursor_pos)
        new_target: str | None = None
        widget = child
        while widget is not None and not isinstance(widget, MetricTile):
            widget = widget.parent() if hasattr(widget, "parent") else None
        if isinstance(widget, MetricTile) and widget.key != self._drag_source_key:
            new_target = widget.key

        if new_target == self._drag_target_key:
            return

        if self._drag_target_key:
            old_tile = self._tile_by_key.get(self._drag_target_key)
            if old_tile:
                old_tile.setStyleSheet("")
        self._drag_target_key = new_target
        if new_target:
            new_tile = self._tile_by_key.get(new_target)
            if new_tile:
                new_tile.setStyleSheet(self._DRAG_TARGET_STYLE)

    def _complete_drag(self, target_key: str | None) -> None:
        """Finish the drag: clean up ghost, swap tiles if a valid target was found."""
        source_key = self._drag_source_key

        source_tile = self._tile_by_key.get(source_key) if source_key else None
        if source_tile:
            source_tile.setGraphicsEffect(None)

        if self._drag_target_key:
            target_tile = self._tile_by_key.get(self._drag_target_key)
            if target_tile:
                target_tile.setStyleSheet("")

        if self._drag_ghost is not None:
            self._drag_ghost.deleteLater()
            self._drag_ghost = None

        self._drag_source_key = None
        self._drag_target_key = None
        self.releaseMouse()

        if source_key and target_key:
            self.reorder_tiles(source_key, target_key)

    def _flash_tile(self, key: str) -> None:
        """Briefly highlight a tile to confirm a drop."""
        tile = self._tile_by_key.get(key)
        if tile is None:
            return
        tile.setStyleSheet(self._DRAG_FLASH_STYLE)
        QTimer.singleShot(self._DRAG_FLASH_MS, lambda: tile.setStyleSheet("") if tile else None)

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
