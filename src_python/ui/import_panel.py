"""
Import / Data panel — load spectrum files and manage the spectrum list.
Equivalent of ImportSpectrum.tsx + SpectrumList.tsx.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models import Spectrum
from app.state import AppState
from core.spectrum_parser import extract_label_from_filename, parse_spectrum_text


_FILE_FILTER = "Spectrum files (*.txt *.csv *.tsv *.dat *.asc);;All files (*)"


class ImportPanel(QWidget):
    """Panel for loading spectrum files and managing the list."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._build_ui()
        self._connect_signals()
        self._refresh_list()

    # ── UI construction ────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Buttons row ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._btn_open = QPushButton("Open files…")
        self._btn_open.setToolTip("Load one or more spectrum text files")
        btn_row.addWidget(self._btn_open)

        self._btn_remove = QPushButton("Remove")
        self._btn_remove.setToolTip("Remove the selected spectrum")
        self._btn_remove.setEnabled(False)
        btn_row.addWidget(self._btn_remove)

        self._btn_clear = QPushButton("Clear all")
        self._btn_clear.setToolTip("Remove all loaded spectra")
        self._btn_clear.setEnabled(False)
        btn_row.addWidget(self._btn_clear)

        layout.addLayout(btn_row)

        # ── Spectrum list ──
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(80)
        layout.addWidget(self._list)

        # ── Quick plot controls ──
        from PySide6.QtWidgets import QCheckBox, QGroupBox, QFormLayout

        plot_group = QGroupBox("Plot view")
        plot_form = QFormLayout(plot_group)
        plot_form.setContentsMargins(4, 6, 4, 6)
        plot_form.setSpacing(3)

        self._chk_overlay = QCheckBox("Show all (overlay)")
        self._chk_overlay.setToolTip("Display all spectra together")
        plot_form.addRow(self._chk_overlay)

        self._chk_grid = QCheckBox("Grid")
        self._chk_grid.setChecked(True)
        plot_form.addRow(self._chk_grid)

        self._chk_invert_x = QCheckBox("Invert X axis")
        plot_form.addRow(self._chk_invert_x)

        # Stack offset — slider + spin box
        from PySide6.QtWidgets import QSpinBox
        offset_label = QLabel("Stack offset:")
        plot_form.addRow(offset_label)

        from PySide6.QtWidgets import QSlider
        offset_inner = QHBoxLayout()
        self._offset_slider = QSlider(Qt.Orientation.Horizontal)
        self._offset_slider.setRange(0, 10000)
        self._offset_slider.setSingleStep(100)
        self._offset_slider.setValue(0)
        offset_inner.addWidget(self._offset_slider, stretch=1)

        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(0, 999999)
        self._offset_spin.setSingleStep(100)
        self._offset_spin.setValue(0)
        self._offset_spin.setToolTip("Type any value, or use the slider (0–10 000)")
        self._offset_spin.setFixedWidth(80)
        offset_inner.addWidget(self._offset_spin)

        plot_form.addRow(offset_inner)

        layout.addWidget(plot_group)

    # ── Signal wiring ──────────────────────────────────────

    def _connect_signals(self) -> None:
        self._btn_open.clicked.connect(self._on_open_files)
        self._btn_remove.clicked.connect(self._on_remove)
        self._btn_clear.clicked.connect(self._on_clear)
        self._list.currentRowChanged.connect(self._on_row_changed)

        # React to state changes
        self._state.spectra_changed.connect(self._refresh_list)
        self._state.active_spectrum_changed.connect(self._sync_selection)

        # Plot controls → state
        self._chk_overlay.toggled.connect(
            lambda checked: self._state.set_plot(show_all_spectra=checked)
        )
        self._chk_grid.toggled.connect(
            lambda checked: self._state.set_plot(show_grid=checked)
        )
        self._chk_invert_x.toggled.connect(
            lambda checked: self._state.set_plot(invert_x=checked)
        )
        # Stack offset — keep slider, spin, and state in sync
        def _on_offset_slider(val: int) -> None:
            self._offset_spin.blockSignals(True)
            self._offset_spin.setValue(val)
            self._offset_spin.blockSignals(False)
            self._state.set_plot(stack_offset=float(val))

        def _on_offset_spin(val: int) -> None:
            self._offset_slider.blockSignals(True)
            self._offset_slider.setValue(min(val, self._offset_slider.maximum()))
            self._offset_slider.blockSignals(False)
            self._state.set_plot(stack_offset=float(val))

        self._offset_slider.valueChanged.connect(_on_offset_slider)
        self._offset_spin.valueChanged.connect(_on_offset_spin)

    # ── Slots ──────────────────────────────────────────────

    def _on_open_files(self) -> None:
        start_dir = self._state.last_folder("import")
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open spectrum files",
            start_dir,
            _FILE_FILTER,
        )
        if not paths:
            return
        if paths:
            self._state.set_last_folder(paths[0], "import")

        for path in paths:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue

            result = parse_spectrum_text(text)
            if result is None:
                continue

            xs, ys = result
            name = extract_label_from_filename(path)
            spectrum = Spectrum(name=name, x=xs, y=ys, meta={"sourcePath": path, "sourceName": name})
            self._state.add_spectrum(spectrum)

    def _on_remove(self) -> None:
        sid = self._state.active_spectrum_id
        if sid is not None:
            self._state.remove_spectrum(sid)

    def _on_clear(self) -> None:
        self._state.clear_spectra()

    def _on_row_changed(self, row: int) -> None:
        spectra = self._state.spectra
        if 0 <= row < len(spectra):
            self._state.set_active_spectrum(spectra[row].id)

    # ── List refresh ───────────────────────────────────────

    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()

        spectra = self._state.spectra
        active_id = self._state.active_spectrum_id

        for spec in spectra:
            item = QListWidgetItem(spec.name)
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            font = item.font()
            font.setBold(spec.id == active_id)
            item.setFont(font)
            self._list.addItem(item)

        self._list.blockSignals(False)

        self._sync_selection()
        self._btn_remove.setEnabled(len(spectra) > 0)
        self._btn_clear.setEnabled(len(spectra) > 0)

    def _sync_selection(self) -> None:
        """Highlight the row matching the active spectrum."""
        active_id = self._state.active_spectrum_id
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == active_id:
                self._list.setCurrentRow(i)
                # Update bold
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                if item:
                    font = item.font()
                    font.setBold(False)
                    item.setFont(font)
        self._list.blockSignals(False)
