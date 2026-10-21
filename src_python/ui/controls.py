"""Compact, linked slider and exact numeric entry for scientific parameters."""

import math
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QDoubleSpinBox, QSpinBox


class ScientificSpinBox(QDoubleSpinBox):
    """Readable small/large values; accepts decimal commas and exponents."""

    def textFromValue(self, value):
        return f"{value:.12g}"

    def valueFromText(self, text):
        return float(text.strip().replace(",", "."))

    def validate(self, text, position):
        normalized = text.strip().replace(",", ".")
        try:
            value = float(normalized)
            state = (
                QValidator.State.Acceptable
                if math.isfinite(value) and self.minimum() <= value <= self.maximum()
                else QValidator.State.Intermediate
            )
        except ValueError:
            state = (
                QValidator.State.Intermediate
                if re.fullmatch(r"[+-]?(?:\d*\.?\d*)?(?:[eE][+-]?\d*)?", normalized)
                else QValidator.State.Invalid
            )
        return state, text, position


class NumberField(QWidget):
    valueChanged = Signal(object)

    def __init__(
        self, low, high, value, *, integer=False, odd=False, log=False, parent=None
    ):
        super().__init__(parent)
        self.low, self.high, self.odd, self.log = low, high, odd, log
        self.integer = integer
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 2000)
        self.spin = QSpinBox() if integer else ScientificSpinBox()
        if not integer:
            self.spin.setDecimals(9)
        self.spin.setRange(low, high)
        self.spin.setSingleStep(2 if odd else 1 if integer else 0.1)
        self.spin.setFixedWidth(112)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.slider.valueChanged.connect(self._slide)
        self.spin.valueChanged.connect(self._typed)
        self.setValue(value)

    def _transform(self, value):
        if self.log and self.low > 0:
            return math.log(value)
        if self.high - self.low > 1e6:
            return math.asinh(value)
        return value

    def _inverse(self, value):
        if self.log and self.low > 0:
            return math.exp(value)
        return math.sinh(value) if self.high - self.low > 1e6 else value

    def _slide(self, position):
        low, high = self._transform(self.low), self._transform(self.high)
        value = self._inverse(low + (high - low) * position / 2000)
        self.spin.setValue(round(value) if self.integer else value)

    def _typed(self, value):
        if self.odd and value % 2 == 0:
            self.spin.setValue(min(self.high, value + 1))
            return
        low, high = self._transform(self.low), self._transform(self.high)
        self.slider.blockSignals(True)
        self.slider.setValue(
            round(2000 * (self._transform(value) - low) / (high - low))
        )
        self.slider.blockSignals(False)
        self.spin.setToolTip(
            f"Přesná hodnota: {value!r} · rozsah {self.low:g} až {self.high:g}"
        )
        self.valueChanged.emit(value)

    def value(self):
        return self.spin.value()

    def setValue(self, value):
        self.spin.setValue(value)
        self._typed(self.spin.value())

    def setRange(self, low, high):
        self.low, self.high = low, high
        self.spin.setRange(low, high)
        self._typed(self.value())

    def setDecimals(self, value):
        if isinstance(self.spin, QDoubleSpinBox):
            self.spin.setDecimals(value)

    def setSingleStep(self, value):
        self.spin.setSingleStep(value)
