"""
Import/Data panel: load spectrum files and manage the spectrum list.
Equivalent of ImportSpectrum.tsx + SpectrumList.tsx.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models import Peak, Spectrum
from app.state import AppState
from core.spectrum_parser import (
    SpectrumParseError,
    extract_label_from_filename,
    parse_spectrum_file,
)


_FILE_FILTER = (
    "Spectrum files (*.txt *.csv *.tsv *.dat *.asc *.xy *.spc *.spa);;All files (*)"
)


class ImportPanel(QWidget):
    """Panel for loading spectrum files and managing the list."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._build_ui()
        self._connect_signals()
        self._refresh_list()
        self._sync_plot_controls_from_state()

    # UI construction
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._btn_open = QPushButton("Open files...")
        self._btn_open.setToolTip("Load one or more spectrum files")
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

        # Spectrum list
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(80)
        layout.addWidget(self._list)

        # Quick plot controls
        from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox

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

        # Stack offset: slider + spinbox
        offset_label = QLabel("Stack offset:")
        plot_form.addRow(offset_label)

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
        self._offset_spin.setToolTip("Type any value, or use slider range 0-10000")
        self._offset_spin.setFixedWidth(90)
        offset_inner.addWidget(self._offset_spin)

        plot_form.addRow(offset_inner)
        layout.addWidget(plot_group)

    # Signal wiring
    def _connect_signals(self) -> None:
        self._btn_open.clicked.connect(self._on_open_files)
        self._btn_remove.clicked.connect(self._on_remove)
        self._btn_clear.clicked.connect(self._on_clear)
        self._list.currentRowChanged.connect(self._on_row_changed)

        # React to state changes
        self._state.spectra_changed.connect(self._refresh_list)
        self._state.active_spectrum_changed.connect(self._sync_selection)
        self._state.plot_changed.connect(self._sync_plot_controls_from_state)

        # Plot controls -> state
        self._chk_overlay.toggled.connect(
            lambda checked: self._state.set_plot(show_all_spectra=checked)
        )
        self._chk_grid.toggled.connect(
            lambda checked: self._state.set_plot(show_grid=checked)
        )
        self._chk_invert_x.toggled.connect(
            lambda checked: self._state.set_plot(invert_x=checked)
        )

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

    def _sync_plot_controls_from_state(self) -> None:
        """Sync quick plot controls from current PlotSettings."""
        p = self._state.plot
        offset_val = max(0, int(round(float(p.stack_offset))))

        self._chk_overlay.blockSignals(True)
        self._chk_grid.blockSignals(True)
        self._chk_invert_x.blockSignals(True)
        self._offset_slider.blockSignals(True)
        self._offset_spin.blockSignals(True)
        try:
            self._chk_overlay.setChecked(bool(p.show_all_spectra))
            self._chk_grid.setChecked(bool(p.show_grid))
            self._chk_invert_x.setChecked(bool(p.invert_x))
            self._offset_spin.setValue(offset_val)
            self._offset_slider.setValue(min(offset_val, self._offset_slider.maximum()))
        finally:
            self._chk_overlay.blockSignals(False)
            self._chk_grid.blockSignals(False)
            self._chk_invert_x.blockSignals(False)
            self._offset_slider.blockSignals(False)
            self._offset_spin.blockSignals(False)

    # Slots
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

        self._state.set_last_folder(paths[0], "import")

        errors: list[str] = []
        for path in paths:
            try:
                parsed = parse_spectrum_file(path)
            except SpectrumParseError as exc:
                errors.append(f"{Path(path).name}: {exc}")
                continue

            if parsed is None:
                continue

            name = extract_label_from_filename(path)
            meta = {"sourcePath": path, "sourceName": name}
            meta.update(parsed.metadata)

            imported_peaks = [
                Peak(x=peak.x, source="manual", label=peak.label or None)
                for peak in parsed.imported_peaks
            ]

            spectrum = Spectrum(name=name, x=parsed.x, y=parsed.y, meta=meta)
            self._state.add_spectrum(spectrum, imported_peaks=imported_peaks)

        if errors:
            details = "\n".join(errors[:8])
            if len(errors) > 8:
                details += f"\n... and {len(errors) - 8} more"
            QMessageBox.warning(self, "Some files could not be imported", details)

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

    # List refresh
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
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif item:
                font = item.font()
                font.setBold(False)
                item.setFont(font)
        self._list.blockSignals(False)

