"""
Sidebar: collapsible accordion sections for all SpecLab panels.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.models import SPECTRAL_MODE_LABELS, SPECTRAL_MODES
from app.state import AppState
from ui.baseline_panel import BaselinePanel
from ui.cosmic_panel import CosmicPanel
from ui.export_panel import ExportPanel
from ui.graphics_panel import GraphicsPanel
from ui.peaks_panel import PeaksPanel
from ui.presets_panel import PresetsPanel
from ui.smoothing_panel import SmoothingPanel
from .import_panel import ImportPanel


_SECTIONS = [
    "Data",
    "Cosmic rays",
    "Baseline",
    "Smoothing",
    "Peaks",
    "Graphics",
    "Export",
    "Presets",
]


class _CollapsibleSection(QWidget):
    """A single collapsible accordion section with a toggle button + content area."""

    def __init__(
        self,
        title: str,
        content: QWidget,
        expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._toggle.setStyleSheet(
            "QToolButton { font-weight: 600; padding: 6px 4px; border: none; "
            "border-bottom: 1px solid #cbd5e1; text-align: left; width: 100%; }"
        )
        self._toggle.setMinimumHeight(30)
        layout.addWidget(self._toggle)

        self._content = content
        self._content.setVisible(expanded)
        self._content.setContentsMargins(6, 4, 6, 8)
        layout.addWidget(self._content)

        self._toggle.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._content.setVisible(checked)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )


def _placeholder(label: str) -> QWidget:
    """Return a simple placeholder widget for unknown sections."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    lbl = QLabel(f"{label} - coming soon")
    lbl.setStyleSheet("color: #94a3b8; font-style: italic;")
    lay.addWidget(lbl)
    return w


class Sidebar(QWidget):
    """Main sidebar containing all accordion sections."""

    def __init__(
        self,
        state: AppState,
        get_plot_widget=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._get_plot_widget = get_plot_widget
        self.peaks_panel: Optional[PeaksPanel] = None
        self._mode_combo: Optional[QComboBox] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Top spectral mode selector bar
        mode_wrap = QWidget()
        mode_layout = QVBoxLayout(mode_wrap)
        mode_layout.setContentsMargins(8, 8, 8, 6)
        mode_layout.setSpacing(4)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(6)

        mode_label = QLabel("Mode:")
        mode_font = mode_label.font()
        mode_font.setBold(True)
        mode_label.setFont(mode_font)
        mode_row.addWidget(mode_label)

        self._mode_combo = QComboBox()
        for mode_id, label in SPECTRAL_MODE_LABELS.items():
            if mode_id in SPECTRAL_MODES:
                self._mode_combo.addItem(label, mode_id)
        self._mode_combo.setToolTip(
            "Switch spectral technique defaults for labels, axis direction, "
            "baseline parameters, and peak detection behavior."
        )
        mode_row.addWidget(self._mode_combo, 1)
        mode_layout.addLayout(mode_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setStyleSheet("color: #cbd5e1;")
        mode_layout.addWidget(separator)
        outer.addWidget(mode_wrap)

        if self._mode_combo.count() > 0:
            default_idx = self._mode_combo.findData("custom")
            if default_idx < 0:
                default_idx = self._mode_combo.count() - 1
            self._mode_combo.setCurrentIndex(default_idx)
            self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
            self._state.spectral_mode_changed.connect(self._sync_mode_from_state)
            self._sync_mode_from_state()

        # Scrollable container for sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        for section_name in _SECTIONS:
            if section_name == "Data":
                content = ImportPanel(self._state)
                expanded = True
            elif section_name == "Cosmic rays":
                content = CosmicPanel(self._state)
                expanded = False
            elif section_name == "Baseline":
                content = BaselinePanel(self._state)
                expanded = False
            elif section_name == "Smoothing":
                content = SmoothingPanel(self._state)
                expanded = False
            elif section_name == "Peaks":
                content = PeaksPanel(self._state)
                self.peaks_panel = content
                expanded = False
            elif section_name == "Graphics":
                content = GraphicsPanel(self._state)
                expanded = False
            elif section_name == "Export":
                content = ExportPanel(self._state, get_plot_widget=self._get_plot_widget)
                expanded = False
            elif section_name == "Presets":
                content = PresetsPanel(self._state)
                expanded = False
            else:
                content = _placeholder(section_name)
                expanded = False

            section = _CollapsibleSection(section_name, content, expanded=expanded)
            container_layout.addWidget(section)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _on_mode_changed(self, index: int) -> None:
        if self._mode_combo is None:
            return
        mode_id = self._mode_combo.itemData(index)
        if mode_id and mode_id != self._state.spectral_mode:
            self._state.set_spectral_mode(mode_id)

    def _sync_mode_from_state(self) -> None:
        if self._mode_combo is None:
            return
        current = self._state.spectral_mode
        self._mode_combo.blockSignals(True)
        for i in range(self._mode_combo.count()):
            if self._mode_combo.itemData(i) == current:
                self._mode_combo.setCurrentIndex(i)
                break
        self._mode_combo.blockSignals(False)

