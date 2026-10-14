"""Native spectrum-first workspace with explicit, reversible AI processing."""

from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)
from app.models import AXIS_Y_LABELS, Peak, Spectrum
from app.state import AppState
from core.project_io import load_project, save_project
from core.spectrum_parser import (
    SpectrumParseError,
    extract_label_from_filename,
    parse_spectrum_files,
)
from ui.ai_panel import AIPanel
from ui.baseline_panel import BaselinePanel
from ui.cosmic_panel import CosmicPanel
from ui.export_panel import ExportPanel
from ui.graphics_panel import GraphicsPanel
from ui.peaks_panel import PeaksPanel
from ui.plot_widget import SpectrumPlotWidget
from ui.presets_panel import PresetsPanel
from ui.processing_panel import ProcessingPanel
from ui.smoothing_panel import SmoothingPanel
from ui.theme import STYLESHEET
from ui.busy import with_busy_cursor

ACCEPTED_EXTENSIONS = {
    ".txt",
    ".csv",
    ".tsv",
    ".dat",
    ".asc",
    ".xy",
    ".spc",
    ".spa",
    ".wdf",
    ".jdx",
    ".dx",
}
FILE_FILTER = "Spektra (*.txt *.csv *.tsv *.dat *.asc *.xy *.spc *.spa *.wdf *.jdx *.dx);;Všechny soubory (*)"
TECHNIQUES = {
    "raman": "Raman",
    "infrared": "IR",
    "uv_vis": "UV–Vis",
    "custom": "Vlastní",
}
# Provenance records stay in English inside project files; the UI shows Czech.
HISTORY_LABELS = {
    "Import spectra": "Import spekter",
    "Remove spectra": "Odebrání spekter",
    "Clear spectra": "Vymazání všech spekter",
    "Rename spectra": "Přejmenování",
    "Reorder spectra": "Změna pořadí",
    "Change spectrum metadata": "Změna typu měření",
    "Restore original data": "Návrat k původním datům",
    "Remove baseline": "Odebrání baseline",
    "Remove smooth": "Odebrání vyhlazení",
    "Remove despike": "Odebrání úpravy spiků",
    "Apply preset from original data": "Preset z původních dat",
    "Apply preset settings": "Nastavení z presetu",
    "Edit peak label": "Úprava popisku píku",
    "Move peak label": "Posun popisku píku",
    "Reset peak label positions": "Výchozí pozice popisků",
    "Add manual peak": "Ruční pík",
    "Detect peaks": "Detekce píků",
    "Clear peaks": "Smazání píků",
    "Remove peak": "Odebrání píku",
}
OPERATION_LABELS = {
    "baseline": "Baseline",
    "smooth": "Vyhlazení",
    "despike": "Odstranění spiků",
    "normalize": "Normalizace",
    "derivative": "Derivace",
    "convert_y": "Převod Y",
    "crop": "Ořez",
    "resample": "Převzorkování",
    "shift": "Posun",
    "interpolate": "Interpolace",
}
SOURCE_LABELS = {"manual": "ručně", "ai": "AI", "preset": "preset"}
PEAK_SOURCES = {"auto": "auto", "manual": "ruční"}


def spectrum_display_name(path, metadata: dict, index: int, count: int) -> str:
    """Library name for an imported curve.

    Text tables name curves by file (a header such as "Intensity" repeats in
    every file); several Y columns add the column title. Vendor formats keep
    their measurement title.
    """
    stem = extract_label_from_filename(path)
    title = metadata.get("name")
    if "column_index" in metadata:
        return stem if count == 1 else f"{stem} · {title or index + 1}"
    name = title or stem
    # Renishaw titles already carry the spectrum number, e.g. "Map [3]".
    if count > 1 and not name.endswith(f"[{index + 1}]"):
        return f"{name} · {index + 1}"
    return name


def history_text(record: dict) -> str:
    label = str(record.get("label", "Úprava"))
    label = HISTORY_LABELS.get(
        label, " → ".join(OPERATION_LABELS.get(part, part) for part in label.split(" → "))
    )
    prefix = {"undo": "↶ Zpět: ", "redo": "↷ Znovu: "}.get(record.get("action"), "")
    source = record.get("source", "manual")
    return f"{prefix}{label} · {SOURCE_LABELS.get(source, source)}"


Y_KINDS = {
    "intensity": "Intenzita (a.u.)",
    "absorbance": "Absorbance",
    "transmittance_percent": "Transmitance (%)",
    "transmittance_fraction": "Transmitance (0–1)",
}


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if primary:
        widget.setObjectName("primary")
    return widget


def scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    container = QWidget()
    container.setObjectName("panelContents")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(2, 4, 2, 8)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    # Wide numeric ranges make Qt request very wide inputs; let the inspector width win.
    for field in widget.findChildren(QAbstractSpinBox) + widget.findChildren(QComboBox):
        field.setMinimumWidth(64)
        field.setSizePolicy(QSizePolicy.Policy.Ignored, field.sizePolicy().verticalPolicy())
    layout.addWidget(widget)
    layout.addStretch()
    area.setWidget(container)
    return area


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpecLab Studio · Spectroscopy workspace")
        self.resize(1500, 940)
        self.setMinimumSize(1080, 720)
        self.setStyleSheet(STYLESHEET)
        self.setAcceptDrops(True)
        self._state = AppState(self)
        self._state.set_graphics(
            show_y_tick_labels=True,
            inline_spectrum_labels=False,
            axis_line_width=2,
            trace_line_width=3,
        )
        self._project_path = None
        self._dirty = False
        self._syncing = False
        self._peak_ids = []
        self._axis_context = None
        self._suspend_auto_axes = False
        self._auto_syncing = False
        self._build()
        self._connect()
        self._refresh()

    def _build(self):
        workspace = QWidget()
        workspace.setObjectName("workspace")
        root = QVBoxLayout(workspace)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(22, 14, 22, 14)
        row.setSpacing(10)
        row.addWidget(label("SpecLab", "brand"))
        row.addWidget(label("STUDIO", "muted"))
        row.addSpacing(20)
        self.project_label = label("Nový projekt", "muted")
        row.addWidget(self.project_label, 1)
        row.addWidget(button("Otevřít projekt", self._open_project))
        row.addWidget(button("Uložit", self._save_project))
        self.undo_button = button("↶ Zpět", self._state.undo)
        self.redo_button = button("↷ Znovu", self._state.redo)
        row.addWidget(self.undo_button)
        row.addWidget(self.redo_button)
        row.addWidget(button("Importovat", self._open_files, True))
        root.addWidget(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._library())
        splitter.addWidget(self._center())
        splitter.addWidget(self._inspector())
        splitter.setSizes([255, 860, 385])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        self.setCentralWidget(workspace)
        self.statusBar().showMessage(
            "Připraveno · přetáhni spektra do okna nebo je importuj"
        )
        for name, key, callback in [
            ("Importovat", QKeySequence.StandardKey.Open, self._open_files),
            ("Uložit projekt", QKeySequence.StandardKey.Save, self._save_project),
            (
                "Uložit jako",
                QKeySequence.StandardKey.SaveAs,
                lambda: self._save_project(True),
            ),
            ("Zpět", QKeySequence.StandardKey.Undo, self._state.undo),
            ("Znovu", QKeySequence.StandardKey.Redo, self._state.redo),
            ("Smazat vybraný pík", QKeySequence.StandardKey.Delete, self._delete_peak),
        ]:
            action = QAction(name, self)
            action.setShortcut(QKeySequence(key))
            if callback == self._delete_peak:
                # The Mac "delete" key sends Backspace.
                action.setShortcuts([QKeySequence(key), QKeySequence(Qt.Key.Key_Backspace)])
            action.triggered.connect(callback)
            self.addAction(action)

    def _library(self):
        panel = QFrame()
        panel.setObjectName("library")
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(label("Spektra", "section"))
        self.count = label("0", "muted")
        row.addWidget(self.count)
        row.addStretch()
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(160)
        self.list.currentRowChanged.connect(self._select_spectrum)
        self.list.itemDoubleClicked.connect(self._rename)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, callback in [
            ("↑", lambda: self._move("up")),
            ("↓", lambda: self._move("down")),
            ("Přejmenovat", self._rename),
        ]:
            row.addWidget(button(text, callback))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button("Odebrat", self._remove))
        row.addWidget(button("Vymazat", self._clear))
        layout.addLayout(row)
        layout.addWidget(button("Hromadné názvy…", self._batch_names))
        layout.addSpacing(8)
        layout.addWidget(label("Měření", "section"))
        form = QFormLayout()
        form.setSpacing(10)
        self.technique = QComboBox()
        self.y_kind = QComboBox()
        for key, value in TECHNIQUES.items():
            self.technique.addItem(value, key)
        for key, value in Y_KINDS.items():
            self.y_kind.addItem(value, key)
        self.x_unit = QComboBox()
        self.x_unit.addItems(["cm⁻¹", "nm", "µm", "eV", "s", "a.u."])
        self.x_unit.setEditable(True)
        form.addRow("Technika", self.technique)
        form.addRow("Typ Y", self.y_kind)
        form.addRow("Jednotka X", self.x_unit)
        layout.addLayout(form)
        self.technique.currentIndexChanged.connect(self._measurement_changed)
        self.y_kind.currentIndexChanged.connect(self._measurement_changed)
        self.x_unit.currentTextChanged.connect(self._measurement_changed)
        note = label(
            "Typ měření a jednotky patří aktivnímu spektru. Nastavení typu samo nepřevádí data.",
            "muted",
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(8)
        layout.addWidget(button("Načíst demonstrační spektra", self.load_demo))
        layout.addWidget(label("TXT · CSV · WDF · SPA · SPC · JCAMP", "muted"))
        return panel

    def _center(self):
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(22, 20, 22, 12)
        layout.setSpacing(12)
        row = QHBoxLayout()
        self.plot_title = label("Spektrální pracovní prostor", "plotTitle")
        row.addWidget(self.plot_title, 1)
        self.preview_label = label("", "muted")
        row.addWidget(self.preview_label)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.overlay = QCheckBox("Porovnat spektra")
        self.raw = QCheckBox("Původní data")
        self.grid = QCheckBox("Mřížka")
        self.invert = QCheckBox("Obrátit X")
        self.overlay.toggled.connect(lambda v: self._state.set_plot(show_all_spectra=v))
        self.grid.toggled.connect(lambda v: self._state.set_plot(show_grid=v))
        self.invert.toggled.connect(lambda v: self._state.set_plot(invert_x=v))
        for widget in [self.overlay, self.raw, self.grid, self.invert]:
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(label("Rozestup křivek", "muted"))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-1e9, 1e9)
        self.offset.setDecimals(4)
        self.offset.setFixedWidth(105)
        self.offset.valueChanged.connect(lambda v: self._state.set_plot(stack_offset=v))
        row.addWidget(self.offset)
        auto_offset = button("Auto", self._auto_offset)
        auto_offset.setToolTip("Rozestoupit křivky tak, aby se v překryvu nepřekrývaly")
        row.addWidget(auto_offset)
        self.reverse = QCheckBox("Obrátit pořadí")
        self.reverse.toggled.connect(
            lambda v: self._state.set_plot(reverse_overlay_order=v)
        )
        row.addWidget(self.reverse)
        row.addStretch()
        row.addWidget(button("Rozsahy os", self._axis_limits))
        row.addWidget(button("Fit Y", self._plot_fit_y))
        row.addWidget(button("Přizpůsobit graf", self._fit))
        layout.addLayout(row)
        vertical = QSplitter(Qt.Orientation.Vertical)
        self._plot = SpectrumPlotWidget(self._state)
        self.raw.toggled.connect(self._plot.set_show_original)
        vertical.addWidget(self._plot)
        self.details = QTabWidget()
        self.peaks_table = QTableWidget(0, 6)
        self.peaks_table.setHorizontalHeaderLabels(
            ["Pozice X", "Hodnota Y", "Popisek", "Původ", "Prominence", "Šířka"]
        )
        self.peaks_table.setAlternatingRowColors(True)
        self.peaks_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.peaks_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.peaks_table.itemChanged.connect(self._edit_peak)
        peaks = QWidget()
        pk_layout = QVBoxLayout(peaks)
        pk_layout.setContentsMargins(0, 0, 0, 0)
        pk_layout.addWidget(self.peaks_table)
        pk_row = QHBoxLayout()
        pk_row.addWidget(
            label(
                "S ručním výběrem píků: Ctrl / ⌘ + klik přidá, Shift + klik odebere · popisky lze táhnout",
                "muted",
            )
        )
        pk_row.addStretch()
        pk_row.addWidget(button("Smazat pík", self._delete_peak))
        pk_row.addWidget(button("Kopírovat TSV", self._copy_peaks))
        pk_row.addWidget(
            button("Reset popisků", lambda: self._plot.reset_label_positions())
        )
        pk_layout.addLayout(pk_row)
        self.details.addTab(peaks, "Píky")
        self.history_list = QListWidget()
        self.details.addTab(self.history_list, "Historie úprav")
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.details.addTab(self.metadata, "Metadata")
        analysis = QWidget()
        analysis_layout = QVBoxLayout(analysis)
        area_row = QHBoxLayout()
        self.area_low = QDoubleSpinBox()
        self.area_high = QDoubleSpinBox()
        for spin in [self.area_low, self.area_high]:
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(4)
        self.area_high.setValue(1000)
        area_row.addWidget(QLabel("Od"))
        area_row.addWidget(self.area_low)
        area_row.addWidget(QLabel("Do"))
        area_row.addWidget(self.area_high)
        area_row.addWidget(button("Integrovat pás", self._integrate))
        analysis_layout.addLayout(area_row)
        self.area_result = label(
            "Integrace metodou lichoběžníků s interpolací hranic. Výsledek vychází z aktuálních dat.",
            "muted",
        )
        self.area_result.setWordWrap(True)
        analysis_layout.addWidget(self.area_result)
        analysis_layout.addStretch()
        self.details.addTab(analysis, "Plocha pásu")
        vertical.addWidget(self.details)
        vertical.setSizes([600, 200])
        vertical.setStretchFactor(0, 1)
        layout.addWidget(vertical, 1)
        return center

    def _inspector(self):
        panel = QFrame()
        panel.setObjectName("inspector")
        panel.setMinimumWidth(335)
        panel.setMaximumWidth(520)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 18, 14, 14)
        tabs = QTabWidget()
        self.inspector_tabs = tabs
        processing = QWidget()
        processing_layout = QVBoxLayout(processing)
        processing_layout.setContentsMargins(4, 8, 4, 6)
        self.tool_tabs = QTabWidget()
        self.peaks_panel = PeaksPanel(self._state)
        for title, widget in [
            ("Baseline", BaselinePanel(self._state)),
            ("Šum", SmoothingPanel(self._state)),
            ("Spikes", CosmicPanel(self._state)),
            ("Píky", self.peaks_panel),
            ("Další", ProcessingPanel(self._state)),
        ]:
            self.tool_tabs.addTab(scroll(widget), title)
        processing_layout.addWidget(self.tool_tabs)
        tabs.addTab(processing, "Úpravy")
        self.ai_panel = AIPanel(self._state)
        tabs.addTab(scroll(self.ai_panel), "AI")
        tabs.addTab(scroll(GraphicsPanel(self._state)), "Vzhled")
        self.export_panel = ExportPanel(self._state, get_plot_widget=lambda: self._plot)
        tabs.addTab(scroll(self.export_panel), "Export")
        tabs.addTab(scroll(PresetsPanel(self._state)), "Presety")
        layout.addWidget(tabs)
        self._plot.set_peaks_panel(self.peaks_panel)
        return panel

    def _connect(self):
        for signal in [
            self._state.spectra_changed,
            self._state.active_spectrum_changed,
            self._state.peaks_changed,
            self._state.history_changed,
            self._state.plot_changed,
            self._state.preview_changed,
        ]:
            signal.connect(self._refresh)
        for signal in [
            self._state.spectra_changed,
            self._state.history_changed,
            self._state.graphics_changed,
            self._state.plot_changed,
            self._state.peaks_changed,
            self._state.baseline_changed,
            self._state.smoothing_changed,
            self._state.cosmic_changed,
        ]:
            signal.connect(self._mark_dirty)

    def _mark_dirty(self):
        if self._auto_syncing:
            return
        self._dirty = True
        self.project_label.setText(
            (Path(self._project_path).stem if self._project_path else "Nový projekt")
            + " · neuloženo"
        )

    def _refresh(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            state = self._state
            spec = state.active_spectrum
            # Selecting another spectrum of the same kind must keep user-edited
            # axis and detection settings; only a different measurement type syncs.
            # Runs first so the controls below show the synchronized settings.
            context = (
                None
                if spec is None
                else (
                    spec.meta.get("technique"),
                    spec.meta.get("y_kind"),
                    spec.meta.get("x_unit"),
                )
            )
            if context != self._axis_context:
                self._axis_context = context
                if not self._suspend_auto_axes and context is not None:
                    self._sync_axes_to_measurement()
            self.list.blockSignals(True)
            self.list.clear()
            for spec in state.spectra:
                item = QListWidgetItem(
                    f"{spec.name}\n{TECHNIQUES.get(spec.meta.get('technique'), 'Vlastní')} · {len(spec.x):,} bodů"
                )
                item.setData(Qt.ItemDataRole.UserRole, spec.id)
                self.list.addItem(item)
                if spec.id == state.active_spectrum_id:
                    self.list.setCurrentItem(item)
            self.list.blockSignals(False)
            self.count.setText(str(len(state.spectra)))
            self.undo_button.setEnabled(state.can_undo)
            self.redo_button.setEnabled(state.can_redo)
            for widget, value in [
                (self.overlay, state.plot.show_all_spectra),
                (self.grid, state.plot.show_grid),
                (self.invert, state.plot.invert_x),
                (self.reverse, state.plot.reverse_overlay_order),
            ]:
                widget.blockSignals(True)
                widget.setChecked(value)
                widget.blockSignals(False)
            self.offset.blockSignals(True)
            self.offset.setValue(state.plot.stack_offset)
            self.offset.blockSignals(False)
            for widget in [self.technique, self.y_kind, self.x_unit]:
                widget.setEnabled(spec is not None)
                widget.blockSignals(True)
            if spec:
                self.technique.setCurrentIndex(
                    max(
                        0, self.technique.findData(spec.meta.get("technique", "custom"))
                    )
                )
                self.y_kind.setCurrentIndex(
                    max(0, self.y_kind.findData(spec.meta.get("y_kind", "intensity")))
                )
                self.x_unit.setCurrentText(
                    spec.meta.get("x_unit", spec.meta.get("x_units") or "a.u.")
                )
                self.plot_title.setText(spec.name)
                self.metadata.setPlainText(
                    json.dumps(spec.meta, indent=2, ensure_ascii=False, default=str)
                )
            else:
                self.plot_title.setText("Spektrální pracovní prostor")
                self.metadata.clear()
            for widget in [self.technique, self.y_kind, self.x_unit]:
                widget.blockSignals(False)
            self.preview_label.setText(
                "NÁHLED · dosud nepoužito" if state.preview_summary else ""
            )
            self._refresh_peaks()
            self.history_list.clear()
            for record in reversed(state.history):
                item = QListWidgetItem(history_text(record))
                item.setToolTip(
                    json.dumps(record, indent=2, ensure_ascii=False, default=str)
                )
                self.history_list.addItem(item)
        finally:
            self._syncing = False

    def _refresh_peaks(self):
        table = self.peaks_table
        table.blockSignals(True)
        table.setRowCount(0)
        self._peak_ids = []
        spec = self._state.active_spectrum
        if spec:
            y = self._state.displayed_y(spec.id)
            peaks = self._state.peaks_auto.get(
                spec.id, []
            ) + self._state.peaks_manual.get(spec.id, [])
            for peak in sorted(peaks, key=lambda p: p.x):
                row = table.rowCount()
                table.insertRow(row)
                self._peak_ids.append(peak.id)
                x = np.asarray(spec.x)
                ordinate = (
                    np.interp(peak.x, x, y)
                    if x[-1] > x[0]
                    else np.interp(peak.x, x[::-1], y[::-1])
                )
                values = [
                    f"{peak.x:.6g}",
                    f"{ordinate:.8g}",
                    peak.label or "",
                    PEAK_SOURCES.get(peak.source, peak.source),
                    "" if peak.prominence is None else f"{peak.prominence:.6g}",
                    "" if peak.width is None else f"{peak.width:.6g}",
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col != 2:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row, col, item)
        table.blockSignals(False)

    def _select_spectrum(self, row):
        if not self._syncing and 0 <= row < len(self._state.spectra):
            self._state.set_active_spectrum(self._state.spectra[row].id)

    def _measurement_changed(self, *_):
        if self._syncing or self._state.active_spectrum is None:
            return
        self._state.update_spectrum_metadata(
            self._state.active_spectrum_id,
            technique=self.technique.currentData(),
            y_kind=self.y_kind.currentData(),
            x_unit=self.x_unit.currentText(),
        )

    def _sync_axes_to_measurement(self):
        spec = self._state.active_spectrum
        if not spec:
            return
        # Derived display defaults follow the selection; they are not user edits.
        self._auto_syncing = True
        try:
            self._apply_measurement_defaults(spec)
        finally:
            self._auto_syncing = False

    def _apply_measurement_defaults(self, spec):
        meta = spec.meta
        technique = meta.get("technique", "custom")
        kind = meta.get("y_kind", "intensity")
        unit = meta.get("x_unit", meta.get("x_units") or "a.u.")
        name = {
            "raman": "Raman shift",
            "infrared": "Wavenumber",
            "uv_vis": "Wavelength",
        }.get(technique, "X")
        self._state.set_graphics(
            x_label=f"{name} ({unit})", y_label=AXIS_Y_LABELS.get(kind, "Intensity (a.u.)")
        )
        self._state.set_plot(invert_x=technique == "infrared")
        self._state.set_peaks(
            polarity="min" if kind.startswith("transmittance") else "max",
            min_prominence=0.01
            if kind == "absorbance"
            else 0.05
            if kind == "transmittance_fraction"
            else 5
            if kind.startswith("transmittance")
            else 20,
        )
        self._state.set_baseline(p=0.999 if kind.startswith("transmittance") else 0.01)

    def _rename(self, *_):
        spec = self._state.active_spectrum
        if spec:
            name, ok = QInputDialog.getText(
                self, "Přejmenovat spektrum", "Název:", text=spec.name
            )
            if ok:
                self._state.rename_spectrum(spec.id, name)

    def _batch_names(self):
        from ui.naming_dialog import NamingDialog

        if not self._state.spectra:
            return
        dialog = NamingDialog(self._state, self)
        if dialog.exec():
            self._state.rename_spectra(dialog.mapping)

    def _copy_peaks(self):
        import csv
        import io
        from PySide6.QtWidgets import QApplication

        output = io.StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        table = self.peaks_table
        writer.writerow(
            [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        )
        for row in range(table.rowCount()):
            writer.writerow(
                [table.item(row, col).text() for col in range(table.columnCount())]
            )
        QApplication.clipboard().setText(output.getvalue())
        self.statusBar().showMessage("Tabulka píků zkopírována jako TSV")

    def _auto_offset(self):
        self._state.set_plot(show_all_spectra=True, stack_offset=self._plot.auto_stack_offset())
        self._fit()

    def _plot_fit_y(self):
        self._plot.fit_y_visible()

    def _move(self, direction):
        if self._state.active_spectrum_id:
            self._state.move_spectrum(self._state.active_spectrum_id, direction)

    def _remove(self):
        if self._state.active_spectrum_id:
            self._state.remove_spectrum(self._state.active_spectrum_id)

    def _clear(self):
        if (
            self._state.spectra
            and QMessageBox.question(
                self, "Vymazat spektra", "Odebrat všechna spektra z projektu?"
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._state.clear_spectra()

    def _open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importovat spektra", self._state.last_folder("import"), FILE_FILTER
        )
        if paths:
            self._load_files(paths)

    @with_busy_cursor
    def _load_files(self, paths):
        errors = []
        count = 0
        for path in paths:
            try:
                curves = parse_spectrum_files(path)
                batch = []
                for index, parsed in enumerate(curves):
                    name = spectrum_display_name(path, parsed.metadata, index, len(curves))
                    meta = {
                        "sourcePath": str(path),
                        "sourceName": Path(path).name,
                        **parsed.metadata,
                    }
                    peaks = [
                        Peak(x=p.x, source="manual", label=p.label or None)
                        for p in parsed.imported_peaks
                    ]
                    batch.append(
                        (Spectrum(name=name, x=parsed.x, y=parsed.y, meta=meta), peaks)
                    )
                # One signal round per file keeps large WDF maps responsive.
                self._state.add_spectra(batch)
                count += len(batch)
            except (SpectrumParseError, ValueError, OSError) as exc:
                errors.append(f"{Path(path).name}: {exc}")
        if paths:
            self._state.set_last_folder(str(Path(paths[0]).parent), "import")
        self._fit()
        self.statusBar().showMessage(
            f"Načteno {count} spekter" + (f" · chyb: {len(errors)}" if errors else "")
        )
        if errors:
            QMessageBox.warning(self, "Import souborů", "\n".join(errors[:12]))

    def _fit(self):
        self._state.set_plot(x_min=None, x_max=None, y_min=None, y_max=None)
        self._plot.fit()

    def _axis_limits(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Rozsahy os")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        fields = {}
        view = self._plot._plot_item.getViewBox().viewRange()
        for key, text, value in [
            ("x_min", "X od", view[0][0]),
            ("x_max", "X do", view[0][1]),
            ("y_min", "Y od", view[1][0]),
            ("y_max", "Y do", view[1][1]),
        ]:
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(-1e12, 1e12)
            spin.setValue(value)
            form.addRow(text, spin)
            fields[key] = spin
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            values = {key: widget.value() for key, widget in fields.items()}
            if values["x_min"] >= values["x_max"] or values["y_min"] >= values["y_max"]:
                QMessageBox.warning(
                    self, "Rozsahy", "Dolní hranice musí být menší než horní."
                )
            else:
                self._state.set_plot(**values)

    @with_busy_cursor
    def _open_project(self):
        if not self._confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Otevřít projekt", "", "SpecLab project (*.speclab.json *.json)"
        )
        if not path:
            return
        try:
            self._suspend_auto_axes = True
            load_project(self._state, path)
            self._project_path = path
            self._fit()
            self._dirty = False
            self.project_label.setText(Path(path).stem)
            self.statusBar().showMessage("Projekt byl načten")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
        finally:
            self._suspend_auto_axes = False

    @with_busy_cursor
    def _save_project(self, save_as=False):
        path = None if save_as is True else self._project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Uložit projekt",
                "experiment.speclab.json",
                "SpecLab project (*.speclab.json)",
            )
            if not path:
                return False
            if not path.endswith(".json"):
                path += ".speclab.json"
        try:
            save_project(self._state, path)
            self._project_path = path
            self._dirty = False
            self.project_label.setText(Path(path).stem)
            self.statusBar().showMessage("Projekt uložen · původní data jsou zachována")
            return True
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return False

    def _confirm_unsaved(self):
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Neuložený projekt",
            "Uložit aktuální projekt?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self._save_project()
        return reply == QMessageBox.StandardButton.Discard

    def _edit_peak(self, item):
        if not self._syncing and item.column() == 2 and self._state.active_spectrum:
            self._state.edit_peak_label(
                self._state.active_spectrum_id, self._peak_ids[item.row()], item.text()
            )

    def _delete_peak(self):
        # Require an explicit row selection; a stale current row must not be deleted
        # by a Delete/Backspace press elsewhere in the window.
        if not self.peaks_table.selectionModel().hasSelection():
            self.statusBar().showMessage("Nejprve vyber pík v tabulce")
            return
        row = self.peaks_table.currentRow()
        if self._state.active_spectrum and 0 <= row < len(self._peak_ids):
            self._state.remove_peak(self._state.active_spectrum_id, self._peak_ids[row])

    def _integrate(self):
        from core.analysis import integrate_band

        spec = self._state.active_spectrum
        if not spec:
            return
        try:
            area = integrate_band(
                spec.x,
                self._state.displayed_y(spec.id),
                self.area_low.value(),
                self.area_high.value(),
            )
            self.area_result.setText(
                f"Plocha pásu = {area:.8g} · jednotky Y × {spec.meta.get('x_unit', 'X')}. Bez odečtení lokální baseline."
            )
        except ValueError as exc:
            self.area_result.setText(str(exc))

    def load_demo(self):
        x = np.linspace(200, 2000, 1801)
        rng = np.random.default_rng(7)
        batch = []
        for i, name in enumerate(
            ["Reference · syntetický Raman", "Vzorek · syntetický Raman"]
        ):
            y = (
                40
                + 0.018 * x
                + sum(
                    a * np.exp(-0.5 * ((x - c - i * 3) / w) ** 2)
                    for a, c, w in [
                        (145, 520, 12),
                        (100, 1003, 19),
                        (210, 1330, 30),
                        (175, 1580, 23),
                    ]
                )
                + rng.normal(0, 2, len(x))
            )
            batch.append((
                Spectrum(
                    name=name,
                    x=x.tolist(),
                    y=y.tolist(),
                    meta={
                        "technique": "raman",
                        "y_kind": "intensity",
                        "x_unit": "cm⁻¹",
                        "source_format": "synthetic",
                        "synthetic": True,
                    },
                ),
                None,
            ))
        self._state.add_spectra(batch)
        self._state.set_plot(show_all_spectra=True, show_grid=True)
        self._fit()
        self.statusBar().showMessage(
            "Demonstrační data jsou syntetická · nejsou laboratorním měřením"
        )

    def dragEnterEvent(self, event):
        if any(
            url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in ACCEPTED_EXTENSIONS
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in ACCEPTED_EXTENSIONS
        ]
        if paths:
            self._load_files(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def closeEvent(self, event):
        if not self._confirm_unsaved():
            event.ignore()
            return
        if not self.ai_panel.shutdown():
            # Never destroy a running QThread: hide now, quit when it finishes.
            self.hide()
            self.ai_panel.quit_when_idle()
            event.ignore()
            return
        event.accept()
