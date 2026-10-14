"""
Baseline correction panel: AsLS baseline estimation and subtraction.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState


LAMBDA_EXP_MIN = 2
LAMBDA_EXP_MAX = 9


class BaselinePanel(QWidget):
    """Controls for AsLS baseline estimation and subtraction."""

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

        self._chk_overlay = QCheckBox("Zobrazit baseline v grafu")
        self._chk_overlay.setChecked(True)
        layout.addWidget(self._chk_overlay)

        lam_row = QHBoxLayout()
        lam_row.addWidget(QLabel("Lambda:"))
        self._lam_label = QLabel("1e6")
        lam_row.addStretch()
        lam_row.addWidget(self._lam_label)
        layout.addLayout(lam_row)

        self._lam_slider = QSlider(Qt.Orientation.Horizontal)
        self._lam_slider.setRange(LAMBDA_EXP_MIN, LAMBDA_EXP_MAX)
        self._lam_slider.setValue(6)
        self._lam_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._lam_slider.setTickInterval(1)
        layout.addWidget(self._lam_slider)

        p_row = QHBoxLayout()
        p_row.addWidget(QLabel("p:"))
        self._p_label = QLabel("0.010")
        p_row.addStretch()
        p_row.addWidget(self._p_label)
        layout.addLayout(p_row)

        self._p_slider = QSlider(Qt.Orientation.Horizontal)
        self._p_slider.setRange(1, 999)
        self._p_slider.setValue(10)
        layout.addWidget(self._p_slider)

        iter_row = QHBoxLayout()
        iter_row.addWidget(QLabel("Iterace:"))
        self._iter_label = QLabel("10")
        iter_row.addStretch()
        iter_row.addWidget(self._iter_label)
        layout.addLayout(iter_row)

        self._iter_slider = QSlider(Qt.Orientation.Horizontal)
        self._iter_slider.setRange(5, 30)
        self._iter_slider.setValue(10)
        layout.addWidget(self._iter_slider)

        btn_row1 = QHBoxLayout()
        self._btn_apply = QPushButton("Odečíst baseline")
        self._btn_reset = QPushButton("Vrátit baseline")
        btn_row1.addWidget(self._btn_apply)
        btn_row1.addWidget(self._btn_reset)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self._btn_apply_all = QPushButton("Použít na vše")
        self._btn_reset_all = QPushButton("Vrátit u všech")
        btn_row2.addWidget(self._btn_apply_all)
        btn_row2.addWidget(self._btn_reset_all)
        layout.addLayout(btn_row2)

    def _connect_signals(self) -> None:
        self._lam_slider.valueChanged.connect(self._on_lambda_changed)
        self._p_slider.valueChanged.connect(self._on_p_changed)
        self._iter_slider.valueChanged.connect(self._on_iter_changed)
        self._chk_overlay.toggled.connect(self._on_overlay_toggled)

        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_reset.clicked.connect(self._on_reset)
        self._btn_apply_all.clicked.connect(self._on_apply_all)
        self._btn_reset_all.clicked.connect(self._on_reset_all)

        self._state.baseline_changed.connect(self._sync_from_state)

    def _sync_from_state(self) -> None:
        b = self._state.baseline
        exp = max(
            LAMBDA_EXP_MIN,
            min(LAMBDA_EXP_MAX, round(np.log10(max(b.lambda_, 10**LAMBDA_EXP_MIN)))),
        )
        self._lam_slider.blockSignals(True)
        self._p_slider.blockSignals(True)
        self._iter_slider.blockSignals(True)
        self._chk_overlay.blockSignals(True)
        try:
            self._lam_slider.setValue(exp)
            self._lam_label.setText(f"1e{exp}")

            self._p_slider.setValue(round(b.p * 1000))
            self._p_label.setText(f"{b.p:.3f}")

            self._iter_slider.setValue(b.iterations)
            self._iter_label.setText(str(b.iterations))

            self._chk_overlay.setChecked(b.show_overlay)
        finally:
            self._lam_slider.blockSignals(False)
            self._p_slider.blockSignals(False)
            self._iter_slider.blockSignals(False)
            self._chk_overlay.blockSignals(False)

    def _on_lambda_changed(self, exp: int) -> None:
        lam = 10 ** exp
        self._lam_label.setText(f"1e{exp}")
        self._state.set_baseline(lambda_=lam)

    def _on_p_changed(self, val: int) -> None:
        p = val / 1000.0
        self._p_label.setText(f"{p:.3f}")
        self._state.set_baseline(p=p)

    def _on_iter_changed(self, val: int) -> None:
        self._iter_label.setText(str(val))
        self._state.set_baseline(iterations=val)

    def _on_overlay_toggled(self, checked: bool) -> None:
        self._state.set_baseline(show_overlay=checked)

    def _operation(self) -> dict:
        s = self._state.baseline
        return {'op': 'baseline', 'params': {'lam': s.lambda_, 'p': s.p, 'iterations': s.iterations}}

    def _apply(self, ids: list[str]) -> None:
        if not ids:
            return
        try:
            proposal = self._state.preview_operations([self._operation()], ids)
            self._state.apply_preview(proposal)
        except (ValueError, ArithmeticError) as error:
            QMessageBox.warning(self, "Zpracování nelze použít", str(error))

    def _reset(self, ids: list[str]) -> None:
        if not ids:
            return
        try:
            self._state.reset_operation('baseline', ids)
        except (ValueError, ArithmeticError) as error:
            QMessageBox.warning(self, "Zpracování nelze vrátit", str(error))

    def _on_apply(self) -> None:
        spec = self._state.active_spectrum
        if spec is not None:
            self._apply([spec.id])

    def _on_reset(self) -> None:
        spec = self._state.active_spectrum
        if spec is not None:
            self._reset([spec.id])

    def _on_apply_all(self) -> None:
        self._apply([spec.id for spec in self._state.spectra])

    def _on_reset_all(self) -> None:
        self._reset([spec.id for spec in self._state.spectra])
