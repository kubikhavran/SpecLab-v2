from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from core.labels import spectrum_names


class NamingDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.mapping = {}
        self.setWindowTitle("Hromadné názvy spekter")
        self.resize(590, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.method = QComboBox()
        for title, key in [
            ("Číselná řada", "sequence"),
            ("Název souboru", "filename"),
            ("Potenciál mV", "mv"),
            ("První číslo", "first"),
            ("Poslední číslo", "last"),
            ("Regex · první skupina", "regex"),
            ("Výřez názvu", "slice"),
        ]:
            self.method.addItem(title, key)
        self.prefix = QLineEdit()
        self.suffix = QLineEdit()
        self.pattern = QLineEdit(r"(-?\d+)\s*mV")
        self.start = QDoubleSpinBox()
        self.step = QDoubleSpinBox()
        for spin in [self.start, self.step]:
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(6)
            spin.setValue(1)
        self.slice_start = QSpinBox()
        self.slice_end = QSpinBox()
        for spin in [self.slice_start, self.slice_end]:
            spin.setRange(-1000, 1000)
        self.slice_end.setValue(1000)
        self.reverse = QCheckBox("Obrátit pořadí číslování")
        self.trim = QCheckBox("Oříznout mezery výřezu")
        self.trim.setChecked(True)
        self.numbers = QCheckBox("Ve výřezu ponechat jen číslo")
        for name, widget in [
            ("Pravidlo", self.method),
            ("Prefix", self.prefix),
            ("Suffix", self.suffix),
            ("Začátek řady", self.start),
            ("Krok řady", self.step),
            ("Regex", self.pattern),
            ("Výřez od", self.slice_start),
            ("Výřez do", self.slice_end),
        ]:
            form.addRow(name, widget)
        layout.addLayout(form)
        for widget in [self.reverse, self.trim, self.numbers]:
            layout.addWidget(widget)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Původní název", "Nový název"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for widget in [
            self.method,
            self.prefix,
            self.suffix,
            self.pattern,
            self.start,
            self.step,
            self.slice_start,
            self.slice_end,
            self.reverse,
            self.trim,
            self.numbers,
        ]:
            signal = (
                widget.currentIndexChanged
                if isinstance(widget, QComboBox)
                else widget.textChanged
                if isinstance(widget, QLineEdit)
                else widget.toggled
                if isinstance(widget, QCheckBox)
                else widget.valueChanged
            )
            signal.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_):
        try:
            self.mapping = spectrum_names(
                self.state.spectra,
                self.method.currentData(),
                self.prefix.text(),
                self.suffix.text(),
                self.start.value(),
                self.step.value(),
                self.reverse.isChecked(),
                self.pattern.text(),
                self.slice_start.value(),
                self.slice_end.value(),
                self.trim.isChecked(),
                self.numbers.isChecked(),
            )
            self.table.setRowCount(len(self.state.spectra))
            for row, spec in enumerate(self.state.spectra):
                for col, text in enumerate([spec.name, self.mapping[spec.id]]):
                    self.table.setItem(row, col, QTableWidgetItem(text))
            self.status.setText("Pokud se pravidlo neshoduje, původní název zůstane.")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
                bool(self.mapping)
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
