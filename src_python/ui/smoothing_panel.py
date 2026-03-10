"""
Smoothing panel — Savitzky–Golay filter.
Equivalent of SmoothingPanel.tsx.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from core.smoothing import savgol_smooth


class SmoothingPanel(QWidget):
    """Controls for Savitzky–Golay smoothing."""

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

        # Window slider (odd values 5–51)
        win_row = QHBoxLayout()
        win_row.addWidget(QLabel("Window:"))
        self._win_label = QLabel("11")
        win_row.addStretch()
        win_row.addWidget(self._win_label)
        layout.addLayout(win_row)

        self._win_slider = QSlider(Qt.Orientation.Horizontal)
        self._win_slider.setRange(5, 51)
        self._win_slider.setValue(11)
        self._win_slider.setSingleStep(2)
        self._win_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._win_slider.setTickInterval(2)
        layout.addWidget(self._win_slider)

        # Poly order slider (1–5)
        poly_row = QHBoxLayout()
        poly_row.addWidget(QLabel("Poly order:"))
        self._poly_label = QLabel("3")
        poly_row.addStretch()
        poly_row.addWidget(self._poly_label)
        layout.addLayout(poly_row)

        self._poly_slider = QSlider(Qt.Orientation.Horizontal)
        self._poly_slider.setRange(1, 5)
        self._poly_slider.setValue(3)
        self._poly_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._poly_slider.setTickInterval(1)
        layout.addWidget(self._poly_slider)

        # Buttons
        btn_row1 = QHBoxLayout()
        self._btn_apply = QPushButton("Apply smoothing")
        self._btn_reset = QPushButton("Reset smoothing")
        btn_row1.addWidget(self._btn_apply)
        btn_row1.addWidget(self._btn_reset)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self._btn_apply_all = QPushButton("Apply ALL")
        self._btn_reset_all = QPushButton("Reset ALL")
        btn_row2.addWidget(self._btn_apply_all)
        btn_row2.addWidget(self._btn_reset_all)
        layout.addLayout(btn_row2)

    def _connect_signals(self) -> None:
        self._win_slider.valueChanged.connect(self._on_window_changed)
        self._poly_slider.valueChanged.connect(self._on_poly_changed)
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_reset.clicked.connect(self._on_reset)
        self._btn_apply_all.clicked.connect(self._on_apply_all)
        self._btn_reset_all.clicked.connect(self._on_reset_all)

        # Keep controls synced after external state updates (e.g. presets).
        self._state.smoothing_changed.connect(self._sync_from_state)

    def _sync_from_state(self) -> None:
        s = self._state.smoothing
        w = s.window
        if w % 2 == 0:
            w += 1
        self._win_slider.blockSignals(True)
        self._win_slider.setValue(w)
        self._win_slider.blockSignals(False)
        self._win_label.setText(str(w))

        self._poly_slider.blockSignals(True)
        self._poly_slider.setValue(s.poly_order)
        self._poly_slider.blockSignals(False)
        self._poly_label.setText(str(s.poly_order))

    def _on_window_changed(self, val: int) -> None:
        # Force odd
        if val % 2 == 0:
            val += 1
            self._win_slider.blockSignals(True)
            self._win_slider.setValue(val)
            self._win_slider.blockSignals(False)
        self._win_label.setText(str(val))
        self._state.set_smoothing(window=val)

    def _on_poly_changed(self, val: int) -> None:
        self._poly_label.setText(str(val))
        self._state.set_smoothing(poly_order=val)

    def _get_input_y(self, spectrum_id: str, raw_y: list) -> np.ndarray:
        """Get the Y data to smooth: processed (baseline-corrected) > cosmic > raw."""
        if spectrum_id in self._state.processed_y:
            return np.array(self._state.processed_y[spectrum_id], dtype=np.float64)
        if spectrum_id in self._state.cosmic_clean_y:
            return np.array(self._state.cosmic_clean_y[spectrum_id], dtype=np.float64)
        return np.array(raw_y, dtype=np.float64)

    def _on_apply(self) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            return
        s = self._state.smoothing
        y_in = self._get_input_y(spec.id, spec.y)
        y_smooth = savgol_smooth(y_in, window=s.window, poly_order=s.poly_order)
        self._state.smoothed_y[spec.id] = y_smooth.tolist()
        self._state.spectra_changed.emit()

    def _on_reset(self) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            return
        self._state.smoothed_y.pop(spec.id, None)
        self._state.spectra_changed.emit()

    def _on_apply_all(self) -> None:
        s = self._state.smoothing
        for spec in self._state.spectra:
            y_in = self._get_input_y(spec.id, spec.y)
            y_smooth = savgol_smooth(y_in, window=s.window, poly_order=s.poly_order)
            self._state.smoothed_y[spec.id] = y_smooth.tolist()
        self._state.spectra_changed.emit()

    def _on_reset_all(self) -> None:
        self._state.smoothed_y.clear()
        self._state.spectra_changed.emit()
