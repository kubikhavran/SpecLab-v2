"""
Peak detection panel.
Equivalent of PeaksPanel.tsx.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from ui.busy import with_busy_cursor


class PeaksPanel(QWidget):
    """Controls for automatic peak detection and display settings."""

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

        # Enable peaks checkbox
        self._chk_enabled = QCheckBox("Zapnout detekci píků")
        layout.addWidget(self._chk_enabled)

        # Mode: active / all
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Režim:"))
        self._combo_mode = QComboBox()
        self._combo_mode.addItem("Aktivní spektrum", "active")
        self._combo_mode.addItem("Všechna spektra", "all")
        mode_row.addWidget(self._combo_mode)
        layout.addLayout(mode_row)

        # Polarity: max / min / both
        pol_row = QHBoxLayout()
        pol_row.addWidget(QLabel("Polarita:"))
        self._combo_polarity = QComboBox()
        self._combo_polarity.addItem("Maxima", "max")
        self._combo_polarity.addItem("Minima", "min")
        self._combo_polarity.addItem("Maxima i minima", "both")
        self._combo_polarity.setToolTip(
            "Maxima = píky (Raman, UV–Vis)\n"
            "Minima = poklesy (IR – transmitance)\n"
            "Obojí = píky i poklesy"
        )
        pol_row.addWidget(self._combo_polarity)
        layout.addLayout(pol_row)

        # Min prominence
        prom_row = QHBoxLayout()
        prom_row.addWidget(QLabel("Min. prominence:"))
        self._prom_spin = QDoubleSpinBox()
        self._prom_spin.setDecimals(8)
        self._prom_spin.setRange(0, 1e12)
        self._prom_spin.setValue(20)
        self._prom_spin.setSingleStep(0.01)
        prom_row.addWidget(self._prom_spin)
        layout.addLayout(prom_row)

        self._chk_mixed = QCheckBox('Automatické nastavení pro různé typy Y')
        self._chk_mixed.setToolTip(
            'U smíšené dávky použije prominence 0,01 pro absorbanci, 0,05 pro transmitanci (0–1), '
            '5 pro transmitanci v procentech a 20 pro intenzitu, vždy s odpovídající polaritou. '
            'Vypnutím použijete zadanou prominence a polaritu pro všechna spektra. Volba obojí zůstává obojí.'
        )
        layout.addWidget(self._chk_mixed)

        # Min distance (X units)
        dist_row = QHBoxLayout()
        dist_row.addWidget(QLabel("Min. vzdálenost:"))
        self._dist_spin = QDoubleSpinBox()
        self._dist_spin.setDecimals(6)
        self._dist_spin.setRange(0, 1e12)
        self._dist_spin.setValue(10)
        dist_row.addWidget(self._dist_spin)
        layout.addLayout(dist_row)

        self._chk_region = QCheckBox('Omezit hledání na rozsah X')
        self._chk_region.setToolTip('Zapnutím předvyplníte rozsah podle aktuálních mezí grafu, které pak můžete upravit.')
        layout.addWidget(self._chk_region)
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel('Min. X:'))
        self._region_min = QDoubleSpinBox()
        self._region_min.setDecimals(4)
        self._region_min.setRange(-1e12, 1e12)
        region_row.addWidget(self._region_min)
        region_row.addWidget(QLabel('Max. X:'))
        self._region_max = QDoubleSpinBox()
        self._region_max.setDecimals(4)
        self._region_max.setRange(-1e12, 1e12)
        region_row.addWidget(self._region_max)
        layout.addLayout(region_row)

        # Max peaks
        mp_row = QHBoxLayout()
        mp_row.addWidget(QLabel("Max. počet píků:"))
        self._mp_spin = QSpinBox()
        self._mp_spin.setRange(1, 200)
        self._mp_spin.setValue(20)
        mp_row.addWidget(self._mp_spin)
        layout.addLayout(mp_row)

        # Decimals for labels
        dec_row = QHBoxLayout()
        dec_row.addWidget(QLabel("Desetinná místa:"))
        self._dec_spin = QSpinBox()
        self._dec_spin.setRange(0, 4)
        self._dec_spin.setValue(0)
        dec_row.addWidget(self._dec_spin)
        layout.addLayout(dec_row)

        # Show markers / labels
        self._chk_markers = QCheckBox("Zobrazit značky")
        self._chk_markers.setChecked(True)
        layout.addWidget(self._chk_markers)

        self._chk_labels = QCheckBox("Zobrazit popisky")
        self._chk_labels.setChecked(True)
        layout.addWidget(self._chk_labels)

        # Manual pick toggle
        self._chk_manual = QCheckBox("Ruční výběr (kliknutím do grafu)")
        self._chk_manual.setToolTip(
            "Ctrl+kliknutím do grafu přidáte pík.\n"
            "Shift+kliknutím poblíž popisku pík odstraníte.\n"
            "Běžným kliknutím vyberete nejbližší spektrum."
        )
        layout.addWidget(self._chk_manual)

        # Buttons
        btn1 = QHBoxLayout()
        self._btn_detect = QPushButton("Najít píky")
        self._btn_clear = QPushButton("Vymazat píky")
        btn1.addWidget(self._btn_detect)
        btn1.addWidget(self._btn_clear)
        layout.addLayout(btn1)

        btn2 = QHBoxLayout()
        self._btn_detect_all = QPushButton("Najít píky ve všech")
        self._btn_detect_all.setToolTip(
            'Pro různé typy Y se použije výchozí nastavení pro každé spektrum: maxima absorbance / 0,01, '
            'minima transmitance (0–1) / 0,05, minima transmitance v procentech / 5, '
            'maxima intenzity / 20. Polarita obojí zůstává obojí. U stejného typu se použije vaše nastavení.'
        )
        self._btn_clear_all = QPushButton("Vymazat všechny")
        btn2.addWidget(self._btn_detect_all)
        btn2.addWidget(self._btn_clear_all)
        layout.addLayout(btn2)

        # Info
        self._info = QLabel("")
        self._info.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self._info)

    def _connect_signals(self) -> None:
        self._chk_enabled.toggled.connect(lambda c: self._state.set_peaks(enabled=c))
        self._combo_mode.currentIndexChanged.connect(
            lambda: self._state.set_peaks(mode=self._combo_mode.currentData())
        )
        self._combo_polarity.currentIndexChanged.connect(
            lambda: self._state.set_peaks(polarity=self._combo_polarity.currentData())
        )
        self._prom_spin.valueChanged.connect(lambda v: self._state.set_peaks(min_prominence=v))
        self._chk_mixed.toggled.connect(lambda checked: self._state.set_peaks(mixed_defaults=checked))
        self._dist_spin.valueChanged.connect(lambda v: self._state.set_peaks(min_distance=v))
        self._chk_region.toggled.connect(self._on_region_toggled)
        self._region_min.editingFinished.connect(self._on_region_limits)
        self._region_max.editingFinished.connect(self._on_region_limits)
        self._mp_spin.valueChanged.connect(lambda v: self._state.set_peaks(max_peaks=v))
        self._dec_spin.valueChanged.connect(lambda v: self._state.set_peaks(decimals=v))
        self._chk_markers.toggled.connect(lambda c: self._state.set_peaks(show_markers=c))
        self._chk_labels.toggled.connect(lambda c: self._state.set_peaks(show_labels=c))
        self._chk_manual.toggled.connect(
            lambda c: self._state.set_peaks(manual_pick_enabled=c)
        )

        self._btn_detect.clicked.connect(self._on_detect)
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_detect_all.clicked.connect(self._on_detect_all)
        self._btn_clear_all.clicked.connect(self._on_clear_all)

        # Keep controls synced after external state updates (e.g. presets).
        self._state.peaks_changed.connect(self._sync_from_state)
        self._state.active_spectrum_changed.connect(self._sync_from_state)

    def _sync_from_state(self) -> None:
        p = self._state.peaks_settings
        widgets = [
            self._chk_enabled,
            self._combo_mode,
            self._combo_polarity,
            self._prom_spin,
            self._chk_mixed,
            self._dist_spin,
            self._chk_region, self._region_min, self._region_max,
            self._mp_spin,
            self._dec_spin,
            self._chk_markers,
            self._chk_labels,
            self._chk_manual,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self._chk_enabled.setChecked(p.enabled)
            self._combo_mode.setCurrentIndex(self._combo_mode.findData(p.mode))
            self._combo_polarity.setCurrentIndex(self._combo_polarity.findData(p.polarity))
            self._prom_spin.setValue(p.min_prominence)
            self._chk_mixed.setChecked(p.mixed_defaults)
            self._dist_spin.setValue(p.min_distance)
            lower, upper = self._region_defaults()
            self._chk_region.setChecked(p.region_enabled)
            self._region_min.setValue(p.x_min if p.x_min is not None else lower)
            self._region_max.setValue(p.x_max if p.x_max is not None else upper)
            self._region_min.setEnabled(p.region_enabled)
            self._region_max.setEnabled(p.region_enabled)
            self._mp_spin.setValue(p.max_peaks)
            self._dec_spin.setValue(p.decimals)
            self._chk_markers.setChecked(p.show_markers)
            self._chk_labels.setChecked(p.show_labels)
            self._chk_manual.setChecked(p.manual_pick_enabled)
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _region_defaults(self) -> tuple[float, float]:
        spec = self._state.active_spectrum
        lower, upper = (min(spec.x), max(spec.x)) if spec is not None else (0.0, 1.0)
        plot = self._state.plot
        lower = plot.x_min if plot.x_min is not None else lower
        upper = plot.x_max if plot.x_max is not None else upper
        return float(min(lower, upper)), float(max(lower, upper))

    def _on_region_toggled(self, checked: bool) -> None:
        if checked:
            lower, upper = self._region_defaults()
            self._state.set_peaks(region_enabled=True, x_min=lower, x_max=upper)
        else:
            self._state.set_peaks(region_enabled=False)

    def _on_region_limits(self) -> None:
        lower, upper = self._region_min.value(), self._region_max.value()
        if lower >= upper:
            self._info.setText('Minimální hodnota X musí být menší než maximální.')
            return
        self._state.set_peaks(x_min=lower, x_max=upper)

    @with_busy_cursor
    def _detect(self, ids: list[str]) -> None:
        if not ids:
            return
        try:
            count = self._state.detect_spectrum_peaks(ids)
            kinds = {spec.meta.get('y_kind', 'intensity') for spec in self._state.spectra if spec.id in ids}
            suffix = (' · různé typy Y: výchozí nastavení pro každé spektrum' if len(kinds) > 1
                      and self._state.peaks_settings.mixed_defaults else '')
            self._info.setText(f"Nalezeno píků: {count}{suffix}")
        except ValueError as error:
            QMessageBox.warning(self, "Detekci píků nelze spustit", str(error))

    def _on_detect(self) -> None:
        spec = self._state.active_spectrum
        if spec is not None:
            self._detect([spec.id])

    def _on_clear(self) -> None:
        spec = self._state.active_spectrum
        if spec is not None:
            self._state.clear_peaks([spec.id])
            self._info.setText("")

    def _on_detect_all(self) -> None:
        self._detect([spec.id for spec in self._state.spectra])

    def _on_clear_all(self) -> None:
        ids = [spec.id for spec in self._state.spectra]
        if ids:
            self._state.clear_peaks(ids)
            self._info.setText("")

    def add_manual_peak(self, x: float) -> None:
        spec = self._state.active_spectrum
        if spec is not None:
            self._state.add_manual_peak(spec.id, x)
            self._info.setText(f"Ruční pík přidán na x={x:.1f}")

    def remove_nearest_peak(self, x: float, tolerance: float | None = None) -> bool:
        """Remove the active spectrum's peak nearest to X (Shift+click).

        Only a peak within ``tolerance`` (X units) is removed, so a stray click
        far from any peak never deletes one.
        """
        spec = self._state.active_spectrum
        if spec is None:
            return False
        peaks = self._state.peaks_auto.get(spec.id, []) + self._state.peaks_manual.get(spec.id, [])
        if not peaks:
            return False
        nearest = min(peaks, key=lambda peak: abs(peak.x - x))
        if tolerance is not None and abs(nearest.x - x) > tolerance:
            self._info.setText("V místě kliknutí není žádný pík.")
            return False
        self._state.remove_peak(spec.id, nearest.id)
        self._info.setText(f"Pík odstraněn poblíž x={x:.1f}")
        return True
