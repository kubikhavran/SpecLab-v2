"""
Graphics settings panel — axis labels, fonts, palettes, line widths.
Equivalent of GraphicsPanel.tsx.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState


_PALETTE_OPTIONS = [
    ("Auto (default)", "auto"),
    ("Publication Bold", "pubBold"),
    ("Publication Colorblind", "pubColorblind"),
    ("Tol Bright", "tolBright"),
    ("Tol Muted", "tolMuted"),
    ("Deep Rainbow", "deepRainbow"),
    ("Viridis (dark)", "viridisDark"),
    ("Plasma (dark)", "plasmaDark"),
    ("Cividis (dark)", "cividisDark"),
    ("Tableau 10", "tableau10"),
    ("Dark2", "dark2"),
    ("Paired", "paired"),
    ("Okabe-Ito (Colorblind)", "colorblind"),
    ("Electrochem", "electrochem"),
    ("Monochrome", "mono"),
    ("Neon", "neon"),
]

_FONT_FAMILIES = ["Arial", "Inter", "Times New Roman", "Courier New"]


class GraphicsPanel(QWidget):
    """Controls for axis labels, fonts, palettes, line widths, frame mode."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._build_ui()
        self._connect_signals()
        self._sync_from_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Axis labels ──
        labels_group = QGroupBox("Axis labels")
        labels_form = QFormLayout(labels_group)
        labels_form.setContentsMargins(4, 6, 4, 6)

        self._x_label = QLineEdit()
        self._x_label.setPlaceholderText("e.g. Raman shift (cm^-1)")
        labels_form.addRow("X label:", self._x_label)

        self._y_label = QLineEdit()
        self._y_label.setPlaceholderText("e.g. Intensity (a.u.)")
        labels_form.addRow("Y label:", self._y_label)

        lbl_style = QHBoxLayout()
        self._chk_axis_bold = QCheckBox("Bold")
        self._chk_axis_italic = QCheckBox("Italic")
        lbl_style.addWidget(self._chk_axis_bold)
        lbl_style.addWidget(self._chk_axis_italic)
        labels_form.addRow("Label style:", lbl_style)

        layout.addWidget(labels_group)

        # ── Font & sizes ──
        font_group = QGroupBox("Font & sizes")
        font_form = QFormLayout(font_group)
        font_form.setContentsMargins(4, 6, 4, 6)

        self._combo_font = QComboBox()
        self._combo_font.addItems(_FONT_FAMILIES)
        font_form.addRow("Font:", self._combo_font)

        self._spin_base_font = QSpinBox()
        self._spin_base_font.setRange(8, 48)
        self._spin_base_font.setValue(32)
        font_form.addRow("Base font size:", self._spin_base_font)

        self._spin_tick_font = QSpinBox()
        self._spin_tick_font.setRange(8, 36)
        self._spin_tick_font.setValue(30)
        font_form.addRow("Tick font size:", self._spin_tick_font)

        tick_style = QHBoxLayout()
        self._chk_tick_bold = QCheckBox("Bold")
        self._chk_tick_italic = QCheckBox("Italic")
        tick_style.addWidget(self._chk_tick_bold)
        tick_style.addWidget(self._chk_tick_italic)
        font_form.addRow("Tick style:", tick_style)

        layout.addWidget(font_group)

        # ── Lines & frame ──
        lines_group = QGroupBox("Lines & frame")
        lines_form = QFormLayout(lines_group)
        lines_form.setContentsMargins(4, 6, 4, 6)

        self._spin_trace_width = QSpinBox()
        self._spin_trace_width.setRange(1, 10)
        self._spin_trace_width.setValue(4)
        lines_form.addRow("Trace width:", self._spin_trace_width)

        self._spin_axis_width = QSpinBox()
        self._spin_axis_width.setRange(1, 10)
        self._spin_axis_width.setValue(4)
        lines_form.addRow("Axis width:", self._spin_axis_width)

        self._combo_frame = QComboBox()
        self._combo_frame.addItems(["open", "box"])
        lines_form.addRow("Frame:", self._combo_frame)

        layout.addWidget(lines_group)

        # ── Palette ──
        self._combo_palette = QComboBox()
        for label, value in _PALETTE_OPTIONS:
            self._combo_palette.addItem(label, value)
        layout.addWidget(QLabel("Palette:"))
        layout.addWidget(self._combo_palette)

        # ── Tick visibility ──
        ticks_row = QHBoxLayout()
        self._chk_show_x_ticks = QCheckBox("X tick labels")
        self._chk_show_x_ticks.setChecked(True)
        self._chk_show_y_ticks = QCheckBox("Y tick labels")
        ticks_row.addWidget(self._chk_show_x_ticks)
        ticks_row.addWidget(self._chk_show_y_ticks)
        layout.addLayout(ticks_row)

        # ── Grid settings ──
        self._chk_grid = QCheckBox("Show grid")
        layout.addWidget(self._chk_grid)

        # ── Export canvas size ──
        size_group = QGroupBox("Export canvas size")
        size_form = QFormLayout(size_group)
        size_form.setContentsMargins(4, 6, 4, 6)

        self._spin_export_w = QSpinBox()
        self._spin_export_w.setRange(300, 8000)
        self._spin_export_w.setValue(1600)
        self._spin_export_w.setSingleStep(100)
        size_form.addRow("Width:", self._spin_export_w)

        self._spin_export_h = QSpinBox()
        self._spin_export_h.setRange(300, 8000)
        self._spin_export_h.setValue(900)
        self._spin_export_h.setSingleStep(100)
        size_form.addRow("Height:", self._spin_export_h)

        layout.addWidget(size_group)

    def _connect_signals(self) -> None:
        s = self._state

        self._x_label.editingFinished.connect(
            lambda: s.set_graphics(x_label=self._x_label.text())
        )
        self._y_label.editingFinished.connect(
            lambda: s.set_graphics(y_label=self._y_label.text())
        )
        self._chk_axis_bold.toggled.connect(lambda c: s.set_graphics(axis_label_bold=c))
        self._chk_axis_italic.toggled.connect(lambda c: s.set_graphics(axis_label_italic=c))

        self._combo_font.currentTextChanged.connect(lambda t: s.set_graphics(font_family=t))
        self._spin_base_font.valueChanged.connect(lambda v: s.set_graphics(base_font_size=v))
        self._spin_tick_font.valueChanged.connect(lambda v: s.set_graphics(tick_font_size=v))
        self._chk_tick_bold.toggled.connect(lambda c: s.set_graphics(tick_label_bold=c))
        self._chk_tick_italic.toggled.connect(lambda c: s.set_graphics(tick_label_italic=c))

        self._spin_trace_width.valueChanged.connect(lambda v: s.set_graphics(trace_line_width=v))
        self._spin_axis_width.valueChanged.connect(lambda v: s.set_graphics(axis_line_width=v))
        self._combo_frame.currentTextChanged.connect(lambda t: s.set_graphics(frame_mode=t))

        self._combo_palette.currentIndexChanged.connect(self._on_palette_changed)

        self._chk_show_x_ticks.toggled.connect(lambda c: s.set_graphics(show_x_tick_labels=c))
        self._chk_show_y_ticks.toggled.connect(lambda c: s.set_graphics(show_y_tick_labels=c))
        self._chk_grid.toggled.connect(lambda c: s.set_graphics(show_grid=c))

        self._spin_export_w.valueChanged.connect(lambda v: s.set_graphics(export_width=v))
        self._spin_export_h.valueChanged.connect(lambda v: s.set_graphics(export_height=v))

    def _on_palette_changed(self, index: int) -> None:
        value = self._combo_palette.itemData(index)
        if value:
            self._state.set_graphics(palette=value)

    def _sync_from_state(self) -> None:
        g = self._state.graphics

        self._x_label.setText(g.x_label)
        self._y_label.setText(g.y_label)
        self._chk_axis_bold.setChecked(g.axis_label_bold)
        self._chk_axis_italic.setChecked(g.axis_label_italic)

        idx = self._combo_font.findText(g.font_family)
        if idx >= 0:
            self._combo_font.setCurrentIndex(idx)
        self._spin_base_font.setValue(g.base_font_size)
        self._spin_tick_font.setValue(g.tick_font_size)
        self._chk_tick_bold.setChecked(g.tick_label_bold)
        self._chk_tick_italic.setChecked(g.tick_label_italic)

        self._spin_trace_width.setValue(g.trace_line_width)
        self._spin_axis_width.setValue(g.axis_line_width)
        idx_frame = self._combo_frame.findText(g.frame_mode)
        if idx_frame >= 0:
            self._combo_frame.setCurrentIndex(idx_frame)

        for i in range(self._combo_palette.count()):
            if self._combo_palette.itemData(i) == g.palette:
                self._combo_palette.setCurrentIndex(i)
                break

        self._chk_show_x_ticks.setChecked(g.show_x_tick_labels)
        self._chk_show_y_ticks.setChecked(g.show_y_tick_labels)
        self._chk_grid.setChecked(g.show_grid)

        self._spin_export_w.setValue(g.export_width)
        self._spin_export_h.setValue(g.export_height)
