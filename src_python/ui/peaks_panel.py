"""
Peak detection panel.
Equivalent of PeaksPanel.tsx.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState


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
        self._chk_enabled = QCheckBox("Enable peaks")
        layout.addWidget(self._chk_enabled)

        # Mode: active / all
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._combo_mode = QComboBox()
        self._combo_mode.addItems(["active", "all"])
        mode_row.addWidget(self._combo_mode)
        layout.addLayout(mode_row)

        # Polarity: max / min / both
        pol_row = QHBoxLayout()
        pol_row.addWidget(QLabel("Polarity:"))
        self._combo_polarity = QComboBox()
        self._combo_polarity.addItems(["max", "min", "both"])
        self._combo_polarity.setToolTip(
            "max = peaks (Raman, UV-Vis)\n"
            "min = dips (IR transmittance)\n"
            "both = peaks and dips"
        )
        pol_row.addWidget(self._combo_polarity)
        layout.addLayout(pol_row)

        # Min prominence
        prom_row = QHBoxLayout()
        prom_row.addWidget(QLabel("Min prominence:"))
        self._prom_spin = QDoubleSpinBox()
        self._prom_spin.setDecimals(8)
        self._prom_spin.setRange(0, 1e12)
        self._prom_spin.setValue(20)
        self._prom_spin.setSingleStep(0.01)
        prom_row.addWidget(self._prom_spin)
        layout.addLayout(prom_row)

        self._chk_mixed = QCheckBox('Automatic settings for mixed Y types')
        self._chk_mixed.setToolTip(
            'For a mixed batch, use absorbance prominence 0.01, fractional transmittance 0.05, '
            'percent transmittance 5, and intensity 20 with matching polarity. '
            'Disable to use your prominence and polarity for every spectrum. Both stays both.'
        )
        layout.addWidget(self._chk_mixed)

        # Min distance (X units)
        dist_row = QHBoxLayout()
        dist_row.addWidget(QLabel("Min distance:"))
        self._dist_spin = QDoubleSpinBox()
        self._dist_spin.setDecimals(6)
        self._dist_spin.setRange(0, 1e12)
        self._dist_spin.setValue(10)
        dist_row.addWidget(self._dist_spin)
        layout.addLayout(dist_row)

        self._chk_region = QCheckBox('Limit detection to X range')
        self._chk_region.setToolTip('Enable to seed the range from current plot bounds, then edit the limits.')
        layout.addWidget(self._chk_region)
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel('X min:'))
        self._region_min = QDoubleSpinBox()
        self._region_min.setDecimals(6)
        self._region_min.setRange(-1e12, 1e12)
        region_row.addWidget(self._region_min)
        region_row.addWidget(QLabel('X max:'))
        self._region_max = QDoubleSpinBox()
        self._region_max.setDecimals(6)
        self._region_max.setRange(-1e12, 1e12)
        region_row.addWidget(self._region_max)
        layout.addLayout(region_row)

        # Max peaks
        mp_row = QHBoxLayout()
        mp_row.addWidget(QLabel("Max peaks:"))
        self._mp_spin = QSpinBox()
        self._mp_spin.setRange(1, 200)
        self._mp_spin.setValue(20)
        mp_row.addWidget(self._mp_spin)
        layout.addLayout(mp_row)

        # Decimals for labels
        dec_row = QHBoxLayout()
        dec_row.addWidget(QLabel("Decimals:"))
        self._dec_spin = QSpinBox()
        self._dec_spin.setRange(0, 4)
        self._dec_spin.setValue(0)
        dec_row.addWidget(self._dec_spin)
        layout.addLayout(dec_row)

        # Show markers / labels
        self._chk_markers = QCheckBox("Show markers")
        self._chk_markers.setChecked(True)
        layout.addWidget(self._chk_markers)

        self._chk_labels = QCheckBox("Show labels")
        self._chk_labels.setChecked(True)
        layout.addWidget(self._chk_labels)

        # Manual pick toggle
        self._chk_manual = QCheckBox("Manual pick (click on plot)")
        self._chk_manual.setToolTip(
            "Ctrl+click on the plot to add a peak.\n"
            "Shift+click near a peak label to remove it.\n"
            "Plain click selects the nearest spectrum."
        )
        layout.addWidget(self._chk_manual)

        # Buttons
        btn1 = QHBoxLayout()
        self._btn_detect = QPushButton("Detect peaks")
        self._btn_clear = QPushButton("Clear peaks")
        btn1.addWidget(self._btn_detect)
        btn1.addWidget(self._btn_clear)
        layout.addLayout(btn1)

        btn2 = QHBoxLayout()
        self._btn_detect_all = QPushButton("Detect ALL")
        self._btn_detect_all.setToolTip(
            'Mixed ordinate types use per-spectrum defaults: absorbance maxima / 0.01, '
            'fractional transmittance minima / 0.05, percent transmittance minima / 5, '
            'intensity maxima / 20. Both polarity remains both. Homogeneous scope uses your settings.'
        )
        self._btn_clear_all = QPushButton("Clear ALL")
        btn2.addWidget(self._btn_detect_all)
        btn2.addWidget(self._btn_clear_all)
        layout.addLayout(btn2)

        # Info
        self._info = QLabel("")
        self._info.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self._info)

    def _connect_signals(self) -> None:
        self._chk_enabled.toggled.connect(lambda c: self._state.set_peaks(enabled=c))
        self._combo_mode.currentTextChanged.connect(lambda t: self._state.set_peaks(mode=t))
        self._combo_polarity.currentTextChanged.connect(
            lambda t: self._state.set_peaks(polarity=t)
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
            self._combo_mode.setCurrentText(p.mode)
            self._combo_polarity.setCurrentText(p.polarity)
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
            self._info.setText('X minimum must be smaller than maximum.')
            return
        self._state.set_peaks(x_min=lower, x_max=upper)

    def _detect(self, ids: list[str]) -> None:
        if not ids:
            return
        try:
            count = self._state.detect_spectrum_peaks(ids)
            kinds = {spec.meta.get('y_kind', 'intensity') for spec in self._state.spectra if spec.id in ids}
            suffix = (' · mixed Y types: per-spectrum defaults' if len(kinds) > 1
                      and self._state.peaks_settings.mixed_defaults else '')
            self._info.setText(f"Detected: {count} peaks{suffix}")
        except ValueError as error:
            QMessageBox.warning(self, "Peak detection could not run", str(error))

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
            self._info.setText(f"Manual peak added at x={x:.1f}")

    def remove_nearest_peak(self, x: float) -> None:
        """Remove the peak nearest to X on the active spectrum (Shift+click)."""
        spec = self._state.active_spectrum
        if spec is None:
            return

        # Search both auto and manual peaks
        best_dist = float("inf")
        best_id = None
        best_source = None

        for source_name, store in [("auto", self._state.peaks_auto), ("manual", self._state.peaks_manual)]:
            peaks = store.get(spec.id, [])
            for peak in peaks:
                d = abs(peak.x - x)
                if d < best_dist:
                    best_dist = d
                    best_id = peak.id
                    best_source = source_name

        if best_id is None:
            return

        self._state.remove_peak(spec.id, best_id)

        self._info.setText(f"Peak removed near x={x:.1f}")
