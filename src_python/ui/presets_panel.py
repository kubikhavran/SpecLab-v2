"""
Presets panel - save, load, rename, delete, import/export setting presets.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from core.presets import (
    Preset,
    apply_preset_payload,
    capture_preset_payload,
    export_presets_to_file,
    import_presets_from_file,
    load_presets,
    save_presets,
)


class PresetsPanel(QWidget):
    """Panel for managing configuration presets."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._presets = load_presets()
        self._build_ui()
        self._connect_signals()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row1 = QHBoxLayout()
        self._btn_save_new = QPushButton("Save current as...")
        self._btn_save_new.setToolTip("Save current settings as a new preset")
        row1.addWidget(self._btn_save_new)

        self._btn_update = QPushButton("Update selected")
        self._btn_update.setToolTip("Overwrite the selected preset with current settings")
        self._btn_update.setEnabled(False)
        row1.addWidget(self._btn_update)
        layout.addLayout(row1)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setMinimumHeight(60)
        layout.addWidget(self._list)

        row2 = QHBoxLayout()
        self._btn_apply = QPushButton("Apply")
        self._btn_apply.setToolTip("Apply the selected preset's settings")
        self._btn_apply.setEnabled(False)
        row2.addWidget(self._btn_apply)

        self._btn_rename = QPushButton("Rename")
        self._btn_rename.setEnabled(False)
        row2.addWidget(self._btn_rename)

        self._btn_delete = QPushButton("Delete")
        self._btn_delete.setEnabled(False)
        row2.addWidget(self._btn_delete)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self._btn_export = QPushButton("Export presets...")
        self._btn_export.setToolTip("Export all presets to a JSON file")
        row3.addWidget(self._btn_export)

        self._btn_import = QPushButton("Import presets...")
        self._btn_import.setToolTip("Import presets from a JSON file")
        row3.addWidget(self._btn_import)
        layout.addLayout(row3)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self._info)

    def _connect_signals(self) -> None:
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._on_apply)
        self._btn_save_new.clicked.connect(self._on_save_new)
        self._btn_update.clicked.connect(self._on_update)
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_rename.clicked.connect(self._on_rename)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_export.clicked.connect(self._on_export)
        self._btn_import.clicked.connect(self._on_import)

    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for preset in self._presets:
            item = QListWidgetItem(preset.name)
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._on_selection_changed(-1)

    def _selected_preset(self) -> Preset | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._presets):
            return self._presets[row]
        return None

    def _on_selection_changed(self, row: int) -> None:
        has_sel = 0 <= row < len(self._presets)
        self._btn_apply.setEnabled(has_sel)
        self._btn_update.setEnabled(has_sel)
        self._btn_rename.setEnabled(has_sel)
        self._btn_delete.setEnabled(has_sel)

    def _persist(self) -> None:
        save_presets(self._presets)

    def _on_save_new(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        payload = capture_preset_payload(self._state)
        preset = Preset(name=name.strip(), payload=payload)
        self._presets.append(preset)
        self._persist()
        self._refresh_list()
        self._list.setCurrentRow(len(self._presets) - 1)
        self._info.setText(f"Saved: {preset.name}")

    def _on_update(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        preset.payload = capture_preset_payload(self._state)
        from datetime import datetime

        preset.updated_at = datetime.now().isoformat()
        self._persist()
        self._info.setText(f"Updated: {preset.name}")

    def _on_apply(self, *_args) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        apply_preset_payload(self._state, preset.payload)
        self._info.setText(f"Applied: {preset.name}")

    def _on_rename(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename preset", "New name:", text=preset.name
        )
        if not ok or not name.strip():
            return
        preset.name = name.strip()
        self._persist()
        self._refresh_list()
        self._info.setText(f"Renamed to: {preset.name}")

    def _on_delete(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete preset",
            f"Delete preset '{preset.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._presets = [p for p in self._presets if p.id != preset.id]
        self._persist()
        self._refresh_list()
        self._info.setText(f"Deleted: {preset.name}")

    def _on_export(self) -> None:
        if not self._presets:
            self._info.setText("No presets to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export presets",
            "speclab_presets.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            export_presets_to_file(self._presets, path)
            self._info.setText(f"Exported {len(self._presets)} presets")
        except OSError as e:
            self._info.setText(f"Error: {e}")

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import presets",
            "",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            imported = import_presets_from_file(path)
            if not imported:
                self._info.setText("No valid presets found in file")
                return
            self._presets.extend(imported)
            self._persist()
            self._refresh_list()
            self._info.setText(f"Imported {len(imported)} presets")
        except (json.JSONDecodeError, OSError) as e:
            self._info.setText(f"Error: {e}")

