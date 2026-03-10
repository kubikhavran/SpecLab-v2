"""
Cosmic Rays removal panel.
Equivalent of CosmicRaysPanel.tsx.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from core.cosmic import remove_cosmic_rays


class CosmicPanel(QWidget):
    """Controls for cosmic ray spike removal."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._last_removed: dict[str, int] = {}
        self._build_ui()
        self._connect_signals()
        self._sync_from_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Window slider (odd, 5–51)
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
        layout.addWidget(self._win_slider)

        # Threshold slider (3.0–10.0, step 0.5)
        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel("Threshold:"))
        self._thr_label = QLabel("6.0")
        thr_row.addStretch()
        thr_row.addWidget(self._thr_label)
        layout.addLayout(thr_row)

        self._thr_slider = QSlider(Qt.Orientation.Horizontal)
        self._thr_slider.setRange(6, 20)   # maps to 3.0–10.0 (value / 2)
        self._thr_slider.setValue(12)       # 6.0
        layout.addWidget(self._thr_slider)

        # Max width slider (1–7)
        mw_row = QHBoxLayout()
        mw_row.addWidget(QLabel("Max width:"))
        self._mw_label = QLabel("3")
        mw_row.addStretch()
        mw_row.addWidget(self._mw_label)
        layout.addLayout(mw_row)

        self._mw_slider = QSlider(Qt.Orientation.Horizontal)
        self._mw_slider.setRange(1, 7)
        self._mw_slider.setValue(3)
        layout.addWidget(self._mw_slider)

        # Positive only checkbox
        self._chk_positive = QCheckBox("Positive only")
        self._chk_positive.setChecked(True)
        layout.addWidget(self._chk_positive)

        # Iterations slider (1–3)
        iter_row = QHBoxLayout()
        iter_row.addWidget(QLabel("Iterations:"))
        self._iter_label = QLabel("1")
        iter_row.addStretch()
        iter_row.addWidget(self._iter_label)
        layout.addLayout(iter_row)

        self._iter_slider = QSlider(Qt.Orientation.Horizontal)
        self._iter_slider.setRange(1, 3)
        self._iter_slider.setValue(1)
        layout.addWidget(self._iter_slider)

        # Buttons
        btn1 = QHBoxLayout()
        self._btn_apply = QPushButton("Apply cosmic")
        self._btn_reset = QPushButton("Reset cosmic")
        btn1.addWidget(self._btn_apply)
        btn1.addWidget(self._btn_reset)
        layout.addLayout(btn1)

        btn2 = QHBoxLayout()
        self._btn_apply_all = QPushButton("Apply ALL")
        self._btn_reset_all = QPushButton("Reset ALL")
        btn2.addWidget(self._btn_apply_all)
        btn2.addWidget(self._btn_reset_all)
        layout.addLayout(btn2)

        # Info label
        self._info = QLabel("")
        self._info.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self._info)

    def _connect_signals(self) -> None:
        self._win_slider.valueChanged.connect(self._on_win)
        self._thr_slider.valueChanged.connect(self._on_thr)
        self._mw_slider.valueChanged.connect(self._on_mw)
        self._iter_slider.valueChanged.connect(self._on_iter)
        self._chk_positive.toggled.connect(self._on_positive)

        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_reset.clicked.connect(self._on_reset)
        self._btn_apply_all.clicked.connect(self._on_apply_all)
        self._btn_reset_all.clicked.connect(self._on_reset_all)

        # Keep controls synced after external state updates (e.g. presets).
        self._state.cosmic_changed.connect(self._sync_from_state)

    def _sync_from_state(self) -> None:
        c = self._state.cosmic
        w = c.window if c.window % 2 == 1 else c.window + 1
        self._win_slider.blockSignals(True)
        self._thr_slider.blockSignals(True)
        self._mw_slider.blockSignals(True)
        self._iter_slider.blockSignals(True)
        self._chk_positive.blockSignals(True)
        try:
            self._win_slider.setValue(w)
            self._win_label.setText(str(w))

            self._thr_slider.setValue(int(c.threshold * 2))
            self._thr_label.setText(f"{c.threshold:.1f}")

            self._mw_slider.setValue(c.max_width)
            self._mw_label.setText(str(c.max_width))

            self._iter_slider.setValue(c.iterations)
            self._iter_label.setText(str(c.iterations))

            self._chk_positive.setChecked(c.positive_only)
        finally:
            self._win_slider.blockSignals(False)
            self._thr_slider.blockSignals(False)
            self._mw_slider.blockSignals(False)
            self._iter_slider.blockSignals(False)
            self._chk_positive.blockSignals(False)

    def _on_win(self, val: int) -> None:
        if val % 2 == 0:
            val += 1
            self._win_slider.blockSignals(True)
            self._win_slider.setValue(val)
            self._win_slider.blockSignals(False)
        self._win_label.setText(str(val))
        self._state.set_cosmic(window=val)

    def _on_thr(self, val: int) -> None:
        thr = val / 2.0
        self._thr_label.setText(f"{thr:.1f}")
        self._state.set_cosmic(threshold=thr)

    def _on_mw(self, val: int) -> None:
        self._mw_label.setText(str(val))
        self._state.set_cosmic(max_width=val)

    def _on_iter(self, val: int) -> None:
        self._iter_label.setText(str(val))
        self._state.set_cosmic(iterations=val)

    def _on_positive(self, checked: bool) -> None:
        self._state.set_cosmic(positive_only=checked)

    def _apply_to(self, spectrum_id: str, y_raw: list) -> int:
        c = self._state.cosmic
        result = remove_cosmic_rays(
            y_raw,
            window=c.window,
            threshold=c.threshold,
            max_width=c.max_width,
            positive_only=c.positive_only,
            iterations=c.iterations,
        )
        self._state.cosmic_clean_y[spectrum_id] = result.y_clean
        # Clear downstream
        self._state.processed_y.pop(spectrum_id, None)
        self._state.baseline_y.pop(spectrum_id, None)
        self._state.smoothed_y.pop(spectrum_id, None)
        return result.removed_count

    def _on_apply(self) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            return
        y_in = self._state.cosmic_clean_y.get(spec.id, spec.y)
        removed = self._apply_to(spec.id, y_in)
        self._last_removed[spec.id] = removed
        self._info.setText(f"Removed: {removed} spikes")
        self._state.spectra_changed.emit()

    def _on_reset(self) -> None:
        spec = self._state.active_spectrum
        if spec is None:
            return
        self._state.cosmic_clean_y.pop(spec.id, None)
        self._state.processed_y.pop(spec.id, None)
        self._state.baseline_y.pop(spec.id, None)
        self._state.smoothed_y.pop(spec.id, None)
        self._last_removed.pop(spec.id, None)
        self._info.setText("")
        self._state.spectra_changed.emit()

    def _on_apply_all(self) -> None:
        total = 0
        for spec in self._state.spectra:
            y_in = self._state.cosmic_clean_y.get(spec.id, spec.y)
            removed = self._apply_to(spec.id, y_in)
            self._last_removed[spec.id] = removed
            total += removed
        self._info.setText(f"Removed total: {total} spikes")
        self._state.spectra_changed.emit()

    def _on_reset_all(self) -> None:
        self._state.cosmic_clean_y.clear()
        self._state.processed_y.clear()
        self._state.baseline_y.clear()
        self._state.smoothed_y.clear()
        self._last_removed.clear()
        self._info.setText("")
        self._state.spectra_changed.emit()
