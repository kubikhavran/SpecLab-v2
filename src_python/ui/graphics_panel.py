"""Appearance controls with the complete spectrum and peak styling options."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFormLayout, QGroupBox,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from app.state import AppState


_PALETTE_OPTIONS = [
    ('Auto', 'auto'), ('Publication Bold', 'pubBold'),
    ('Publication Colorblind', 'pubColorblind'), ('Tol Bright', 'tolBright'),
    ('Tol Muted', 'tolMuted'), ('Deep Rainbow', 'deepRainbow'),
    ('Viridis dark', 'viridisDark'), ('Plasma dark', 'plasmaDark'),
    ('Cividis dark', 'cividisDark'), ('Tableau 10', 'tableau10'),
    ('Dark2', 'dark2'), ('Paired', 'paired'), ('Okabe–Ito', 'colorblind'),
    ('Viridis', 'viridis'), ('Plasma', 'plasma'), ('Magma', 'magma'),
    ('Cividis', 'cividis'), ('Electrochem', 'electrochem'),
    ('Monochrome', 'mono'), ('Neon', 'neon'),
]
_FONT_FAMILIES = ['Arial', 'Inter', 'Times New Roman', 'Courier New']


class GraphicsPanel(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self._state = state
        self._graphics_controls = {}
        self._peak_controls = {}
        self._build_ui()
        state.graphics_changed.connect(self._sync_graphics)
        state.peaks_changed.connect(self._sync_peaks)
        self._sync_graphics()
        self._sync_peaks()

    def _section(self, layout, title):
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setContentsMargins(10, 12, 10, 10)
        form.setSpacing(8)
        layout.addWidget(group)
        return form

    def _register(self, key, widget, owner):
        controls = self._graphics_controls if owner == 'graphics' else self._peak_controls
        controls[key] = widget
        setter = self._state.set_graphics if owner == 'graphics' else self._state.set_peaks
        if isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda value, k=key: setter(**{k: value}))
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(lambda value, k=key: setter(**{k: value}))
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda _, k=key, w=widget: setter(**{k: w.currentData()}))
        elif isinstance(widget, QLineEdit):
            widget.editingFinished.connect(lambda k=key, w=widget: setter(**{k: w.text()}))
        return widget

    def _check(self, form, key, text, owner='graphics'):
        widget = self._register(key, QCheckBox(text), owner)
        form.addRow(widget)
        return widget

    def _spin(self, form, key, label, low, high, owner='graphics', step=1):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setSingleStep(step)
        self._register(key, widget, owner)
        form.addRow(label, widget)
        return widget

    def _combo(self, form, key, label, options, owner='graphics'):
        widget = QComboBox()
        for text, value in options:
            widget.addItem(text, value)
        self._register(key, widget, owner)
        form.addRow(label, widget)
        return widget

    def _color(self, form, key, label, owner='graphics'):
        widget = QPushButton()
        widget.setToolTip('Choose a color')
        self._register(key, widget, owner)
        def choose():
            settings = self._state.graphics if owner == 'graphics' else self._state.peaks_settings
            selected = QColorDialog.getColor(QColor(getattr(settings, key)), self, label)
            if selected.isValid():
                setter = self._state.set_graphics if owner == 'graphics' else self._state.set_peaks
                setter(**{key: selected.name()})
        widget.clicked.connect(choose)
        form.addRow(label, widget)
        return widget

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        form = self._section(layout, 'Axis labels')
        for key, label, placeholder in (
            ('x_label', 'X label', 'Raman shift (cm^{-1})'),
            ('y_label', 'Y label', 'Intensity (a.u.)'),
        ):
            widget = QLineEdit()
            widget.setPlaceholderText(placeholder)
            widget.setToolTip('Use ^{…} for superscripts and _{…} for subscripts.')
            self._register(key, widget, 'graphics')
            form.addRow(label, widget)
        self._check(form, 'axis_label_bold', 'Bold labels')
        self._check(form, 'axis_label_italic', 'Italic labels')

        form = self._section(layout, 'Fonts and ticks')
        self._combo(form, 'font_family', 'Font', [(f, f) for f in _FONT_FAMILIES])
        self._spin(form, 'base_font_size', 'Label size', 8, 72)
        self._spin(form, 'tick_font_size', 'Tick size', 8, 48)
        self._check(form, 'tick_label_bold', 'Bold tick labels')
        self._check(form, 'tick_label_italic', 'Italic tick labels')
        self._check(form, 'show_x_tick_labels', 'Show X numbers')
        self._check(form, 'show_y_tick_labels', 'Show Y numbers')
        self._check(form, 'show_x_tick_marks', 'Show X tick marks')
        self._check(form, 'show_y_tick_marks', 'Show Y tick marks')

        form = self._section(layout, 'Lines and canvas')
        self._spin(form, 'trace_line_width', 'Spectrum width', 1, 10)
        self._spin(form, 'axis_line_width', 'Axis width', 1, 10)
        self._color(form, 'axis_line_color', 'Axis color')
        self._combo(form, 'frame_mode', 'Frame', [('Open', 'open'), ('Box', 'box')])
        self._combo(form, 'plot_canvas', 'Canvas', [('Follow theme', 'auto'), ('White', 'white'), ('Dark', 'dark')])
        self._check(form, 'show_grid', 'Show grid')
        self._color(form, 'grid_color', 'Grid color')
        self._spin(form, 'grid_width', 'Grid width', 1, 3)
        self._combo(form, 'palette', 'Palette', _PALETTE_OPTIONS)
        self._check(form, 'inline_spectrum_labels', 'Names beside spectra')
        for key, label in [('spectrum_label_bold', 'Bold spectrum names'),
                           ('spectrum_label_italic', 'Italic spectrum names')]:
            if hasattr(self._state.graphics, key):
                self._check(form, key, label)

        form = self._section(layout, 'Peak labels')
        self._check(form, 'show_markers', 'Show markers', 'peaks')
        self._check(form, 'show_labels', 'Show labels', 'peaks')
        self._check(form, 'show_leader_lines', 'Show leader lines', 'peaks')
        self._spin(form, 'label_angle_deg', 'Angle (degrees)', -180, 180, 'peaks')
        self._spin(form, 'label_font_size', 'Label size', 8, 72, 'peaks')
        self._check(form, 'label_bold', 'Bold peak labels', 'peaks')
        self._check(form, 'label_italic', 'Italic peak labels', 'peaks')
        colors = [('Match spectrum', 'trace'), ('Custom color', 'custom')]
        self._combo(form, 'label_color_mode', 'Label color', colors, 'peaks')
        self._color(form, 'label_color', 'Custom label color', 'peaks')
        self._combo(form, 'leader_color_mode', 'Leader color', colors, 'peaks')
        self._color(form, 'leader_color', 'Custom leader color', 'peaks')
        self._spin(form, 'leader_line_width', 'Leader width', 1, 6, 'peaks')

        form = self._section(layout, 'Export canvas')
        self._spin(form, 'export_width', 'Width (px)', 300, 8000, step=100)
        self._spin(form, 'export_height', 'Height (px)', 300, 8000, step=100)
        if hasattr(self._state.graphics, 'preview_canvas_size'):
            self._check(form, 'preview_canvas_size', 'Preview export dimensions')

    @staticmethod
    def _sync_controls(settings, controls):
        for key, widget in controls.items():
            value = getattr(settings, key)
            widget.blockSignals(True)
            try:
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(round(value))
                elif isinstance(widget, QComboBox):
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                elif isinstance(widget, QPushButton):
                    color = QColor(str(value))
                    widget.setText(str(value))
                    text = '#111827' if color.lightness() >= 128 else '#ffffff'
                    widget.setStyleSheet(f'background-color: {color.name()}; color: {text};')
            finally:
                widget.blockSignals(False)

    def _sync_graphics(self):
        self._sync_controls(self._state.graphics, self._graphics_controls)

    def _sync_peaks(self):
        self._sync_controls(self._state.peaks_settings, self._peak_controls)
        ps = self._state.peaks_settings
        self._peak_controls['label_color'].setEnabled(ps.label_color_mode == 'custom')
        self._peak_controls['leader_color'].setEnabled(ps.leader_color_mode == 'custom')
