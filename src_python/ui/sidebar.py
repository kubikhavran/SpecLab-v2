"""
Sidebar — collapsible accordion sections for all SpecLab panels.
Currently only the 'Data' section is wired; others are placeholders.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from ui.baseline_panel import BaselinePanel
from ui.cosmic_panel import CosmicPanel
from ui.export_panel import ExportPanel
from ui.graphics_panel import GraphicsPanel
from ui.peaks_panel import PeaksPanel
from ui.presets_panel import PresetsPanel
from ui.smoothing_panel import SmoothingPanel
from .import_panel import ImportPanel


# Section names matching the React sidebar order
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
        self, title: str, content: QWidget, expanded: bool = False, parent: QWidget | None = None
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
        self._toggle.setSizePolicy(
            self._toggle.sizePolicy().horizontalPolicy(),
            self._toggle.sizePolicy().verticalPolicy(),
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
    """Return a simple placeholder widget for sections not yet implemented."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    lbl = QLabel(f"{label} — coming soon")
    lbl.setStyleSheet("color: #94a3b8; font-style: italic;")
    lay.addWidget(lbl)
    return w


class Sidebar(QWidget):
    """Main sidebar containing all accordion sections."""

    def __init__(self, state: AppState, get_plot_widget=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._get_plot_widget = get_plot_widget
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.peaks_panel: Optional[PeaksPanel] = None

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
                self.peaks_panel = content  # expose for plot widget
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
