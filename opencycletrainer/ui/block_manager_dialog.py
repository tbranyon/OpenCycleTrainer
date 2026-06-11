from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.builder_parser import is_valid_block_name, parse_builder_text
from opencycletrainer.storage.blocks import save_blocks

_BLOCK_HINT = (
    "Define a block with the same builder syntax (steps, ramps, repeats).\n"
    "Blocks cannot reference other blocks."
)


def _fixed_font() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(10)
    return font


class BlockManagerDialog(QDialog):
    """Create, edit, and delete reusable workout blocks (name -> builder text)."""

    def __init__(
        self,
        blocks: dict[str, str],
        ftp_getter: Callable[[], int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Blocks")
        self._blocks = dict(blocks)
        self._ftp_getter = ftp_getter
        self._current: str | None = None

        root = QHBoxLayout(self)

        # Left: block list + add/delete
        left = QVBoxLayout()
        self._list = QListWidget(self)
        self._list.currentTextChanged.connect(self._on_selection_changed)
        left.addWidget(self._list)
        list_btns = QHBoxLayout()
        new_btn = QPushButton("New", self)
        new_btn.clicked.connect(self._on_new)
        self._delete_btn = QPushButton("Delete", self)
        self._delete_btn.clicked.connect(self._on_delete)
        list_btns.addWidget(new_btn)
        list_btns.addWidget(self._delete_btn)
        left.addLayout(list_btns)
        root.addLayout(left, stretch=1)

        # Right: editor
        right = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("e.g. warmup")
        name_row.addWidget(self._name_edit)
        right.addLayout(name_row)

        hint = QLabel(_BLOCK_HINT, self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        right.addWidget(hint)

        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setFont(_fixed_font())
        self._text_edit.setPlaceholderText("- 5m ramp 40-65%\n- 1m 50%")
        right.addWidget(self._text_edit, stretch=1)

        self._error_label = QLabel(self)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #dc2626;")
        self._error_label.hide()
        right.addWidget(self._error_label)

        action_row = QHBoxLayout()
        save_btn = QPushButton("Save Block", self)
        save_btn.clicked.connect(self._on_save_block)
        action_row.addWidget(save_btn)
        action_row.addStretch()
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        action_row.addWidget(close_btn)
        right.addLayout(action_row)
        root.addLayout(right, stretch=2)

        self._refresh_list()
        self._update_editor_enabled()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_blocks(self) -> dict[str, str]:
        return dict(self._blocks)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for name in sorted(self._blocks):
            self._list.addItem(name)
        self._list.blockSignals(False)

    def _update_editor_enabled(self) -> None:
        self._delete_btn.setEnabled(self._current is not None)

    def _on_selection_changed(self, name: str) -> None:
        if not name:
            return
        self._current = name
        self._name_edit.setText(name)
        self._text_edit.setPlainText(self._blocks.get(name, ""))
        self._error_label.hide()
        self._update_editor_enabled()

    def _on_new(self) -> None:
        self._current = None
        self._list.clearSelection()
        self._name_edit.clear()
        self._text_edit.clear()
        self._error_label.hide()
        self._name_edit.setFocus()
        self._update_editor_enabled()

    def _on_delete(self) -> None:
        if self._current is None:
            return
        self._blocks.pop(self._current, None)
        save_blocks(self._blocks)
        self._current = None
        self._refresh_list()
        self._on_new()

    def _on_save_block(self) -> None:
        name = self._name_edit.text().strip()
        if not is_valid_block_name(name):
            QMessageBox.warning(
                self,
                "Invalid Name",
                "Block names must start with a letter or digit and contain only "
                "letters, digits, spaces, hyphens, or underscores.",
            )
            return

        if name != self._current and name in self._blocks:
            QMessageBox.warning(
                self, "Duplicate Name", f"A block named {name!r} already exists."
            )
            return

        text = self._text_edit.toPlainText()
        _, errors = parse_builder_text(text, self._ftp_getter(), name)
        if errors:
            shown = errors[:5]
            self._error_label.setText(
                "Saved with warnings:\n" + "\n".join(shown)
            )
            self._error_label.show()
        else:
            self._error_label.hide()

        # Renaming: drop the old key.
        if self._current is not None and name != self._current:
            self._blocks.pop(self._current, None)

        self._blocks[name] = text
        save_blocks(self._blocks)
        self._current = name
        self._refresh_list()
        items = self._list.findItems(name, Qt.MatchExactly)
        if items:
            self._list.setCurrentItem(items[0])
        self._update_editor_enabled()
