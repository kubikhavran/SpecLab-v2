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
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models import Peak, _new_id
from app.state import AppState
from core.peak_detection import detect_peaks, detected_to_peaks


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

        # Min prominence
        prom_row = QHBoxLayout()
        prom_row.addWidget(QLabel("Min prominence:"))
        self._prom_spin = QSpinBox()
        self._prom_spin.setRange(0, 100000)
        self._prom_spin.setValue(20)
        self._prom_spin.setSingleStep(10)
        prom_row.addWidget(self._prom_spin)
        layout.addLayout(prom_row)

        # Min distance (X units)
        dist_row = QHBoxLayout()
        dist_row.addWidget(QLabel("Min distance:"))
        self._dist_spin = QSpinBox()
        self._dist_spin.setRange(0, 200)
        self._dist_spin.setValue(10)
        dist_row.addWidget(self._dist_spin)
        layout.addLayout(dist_row)

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
        self._prom_spin.valueChanged.connect(lambda v: self._state.set_peaks(min_prominence=v))
        self._dist_spin.valueChanged.connect(lambda v: self._state.set_peaks(min_distance=v))
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

    def _sync_from_state(self) -> None:
        p = self._state.peaks_settings
        self._chk_enabled.setChecked(p.enabled)
        self._combo_mode.setCurrentText(p.mode)
        self._prom_spin.setValue(int(p.min_prominence))
        self._dist_spin.setValue(p.min_distance)
        self._mp_spin.setValue(p.max_peaks)
        self._dec_spin.setValue(p.decimals)
        self._chk_markers.setChecked(p.show_markers)
        self._chk_labels.setChecked(p.show_labels)
        self._chk_manual.setChecked(p.manual_pick_enabled)

    def _get_display_y(self, spec) -> list:
        """Get the displayed Y for peak detection (follows processing chain)."""
        y = self._state.displayed_y(spec.id)
        return y if y is not None else spec.y

    def _detect_for(self, spec) -> int:
        """Run peak detection for one spectrum. Returns peak count."""
        p = self._state.peaks_settings
        y = self._get_display_y(spec)
        detected = detect_peaks(
            spec.x, y,
            min_prominence=p.min_prominence,
            min_distance_x=p.min_distance,
            max_peaks=p.max_peaks,
            polarity=p.polarity if hasattr(p, 'polarity') else "max",
        )
        peaks = detected_to_peaks(detected)
        self._state.peaks_auto[spec.id] = peaks
        return len(peaks)

    def _on_detect(self) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            return
        count = self._detect_for(spec)
        self._state.set_peaks(enabled=True)
        self._chk_enabled.setChecked(True)
        self._info.setText(f"Detected: {count} peaks")
        self._state.peaks_changed.emit()

    def _on_clear(self) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            return
        self._state.peaks_auto.pop(spec.id, None)
        self._state.peaks_manual.pop(spec.id, None)
        self._info.setText("")
        self._state.peaks_changed.emit()

    def _on_detect_all(self) -> None:
        total = 0
        for spec in self._state.spectra:
            total += self._detect_for(spec)
        self._state.set_peaks(enabled=True)
        self._chk_enabled.setChecked(True)
        self._info.setText(f"Detected total: {total} peaks")
        self._state.peaks_changed.emit()

    def _on_clear_all(self) -> None:
        self._state.peaks_auto.clear()
        self._state.peaks_manual.clear()
        self._info.setText("")
        self._state.peaks_changed.emit()

    def add_manual_peak(self, x: float) -> None:
        """Add a manual peak at the given X coordinate on the active spectrum."""
        spec = self._state.active_spectrum
        if spec is None:
            return
        peak = Peak(id=_new_id(), x=x, source="manual")
        manual = self._state.peaks_manual.get(spec.id, [])
        manual.append(peak)
        self._state.peaks_manual[spec.id] = manual
        self._state.set_peaks(enabled=True)
        self._chk_enabled.setChecked(True)
        self._info.setText(f"Manual peak added at x={x:.1f}")
        self._state.peaks_changed.emit()

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

        if best_source == "auto":
            self._state.peaks_auto[spec.id] = [
                p for p in self._state.peaks_auto.get(spec.id, []) if p.id != best_id
            ]
        else:
            self._state.peaks_manual[spec.id] = [
                p for p in self._state.peaks_manual.get(spec.id, []) if p.id != best_id
            ]

        self._info.setText(f"Peak removed near x={x:.1f}")
        self._state.peaks_changed.emit()
