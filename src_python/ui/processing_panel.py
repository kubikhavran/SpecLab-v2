"""Extra spectroscopy tools, using the same preview/commit contract as AI."""

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ProcessingPanel(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.scope = QComboBox()
        self.scope.addItems(["Aktivní spektrum", "Všechna spektra"])
        layout.addWidget(self.scope)
        self.tool = QComboBox()
        self.tool.addItems(
            [
                "Normalizace",
                "Derivace",
                "Transmitance / absorbance",
                "Ořez rozsahu",
                "Převzorkování",
                "Posun os",
                "Ruční interpolace",
            ]
        )
        layout.addWidget(self.tool)
        form = QFormLayout()
        self.method = QComboBox()
        self.method.addItem("Maximum = 1", "max")
        self.method.addItem("Vektorová norma", "vector")
        self.method.addItem("Plocha = 1", "area")
        self.method.addItem("Min–max (0–1)", "minmax")
        self.target = QComboBox()
        self.target.addItem("Absorbance", "absorbance")
        self.target.addItem("Transmitance (%)", "transmittance_percent")
        self.target.addItem("Transmitance (0–1)", "transmittance_fraction")
        self.order = QSpinBox()
        self.order.setRange(1, 2)
        self.window = QSpinBox()
        self.window.setRange(5, 101)
        self.window.setSingleStep(2)
        self.window.setValue(11)
        self.low = self._number(-1e9, 1e9, 0)
        self.high = self._number(-1e9, 1e9, 1000)
        self.step = self._number(0.000001, 1e6, 1)
        self.x_shift = self._number(-1e9, 1e9, 0)
        self.y_shift = self._number(-1e9, 1e9, 0)
        self.rows = {}
        for name, widget in [
            ("Metoda", self.method),
            ("Cíl", self.target),
            ("Řád", self.order),
            ("Okno", self.window),
            ("Od", self.low),
            ("Do", self.high),
            ("Krok X", self.step),
            ("Posun X", self.x_shift),
            ("Posun Y", self.y_shift),
        ]:
            form.addRow(name, widget)
            self.rows[widget] = form.labelForField(widget)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        layout.addWidget(self.note)
        preview = QPushButton("Spočítat náhled")
        preview.clicked.connect(self._preview)
        layout.addWidget(preview)
        self.apply_button = QPushButton("Použít úpravu")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        layout.addWidget(self.apply_button)
        reset = QPushButton("Vrátit původní data")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        layout.addStretch()
        self.tool.currentIndexChanged.connect(self._tool_changed)
        for widget in self.rows:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(state.clear_preview)
            else:
                widget.valueChanged.connect(state.clear_preview)
        self.scope.currentIndexChanged.connect(state.clear_preview)
        state.preview_changed.connect(self._sync)
        state.active_spectrum_changed.connect(self._sync)
        self._tool_changed()

    @staticmethod
    def _number(low, high, value):
        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(low, high)
        spin.setValue(value)
        return spin

    def _tool_changed(self, *_):
        visible = [
            [self.method],
            [self.order, self.window],
            [self.target],
            [self.low, self.high],
            [self.step],
            [self.x_shift, self.y_shift],
            [self.low, self.high],
        ][self.tool.currentIndex()]
        for widget, label in self.rows.items():
            widget.setVisible(widget in visible)
            label.setVisible(widget in visible)
        notes = [
            "Změní měřítko intenzity. Výsledek je relativní.",
            "Derivace vyžaduje rovnoměrnou osu X. Zvol převzorkování, pokud je potřeba.",
            "Nejprve nastav typ Y u spektra vlevo. A = −log₁₀(T); procenta se dělí 100.",
            "Zachová jen zadaný interval.",
            "Lineární interpolace na rovnoměrnou osu; nepřidává nové měření.",
            "Explicitní posun X a Y. Parametry zůstanou v historii.",
            "Nahradí body v intervalu přímkou mezi sousedními platnými body.",
        ]
        self.note.setText(notes[self.tool.currentIndex()])
        self.state.clear_preview()

    def _ids(self):
        return (
            [s.id for s in self.state.spectra]
            if self.scope.currentIndex() == 1
            else None
        )

    def _operation(self):
        return [
            {"op": "normalize", "params": {"method": self.method.currentData()}},
            {
                "op": "derivative",
                "params": {
                    "order": self.order.value(),
                    "window": self.window.value(),
                    "poly_order": 3,
                },
            },
            {"op": "convert_y", "params": {"target": self.target.currentData()}},
            {
                "op": "crop",
                "params": {"min": self.low.value(), "max": self.high.value()},
            },
            {"op": "resample", "params": {"step": self.step.value()}},
            {
                "op": "shift",
                "params": {"x": self.x_shift.value(), "y": self.y_shift.value()},
            },
            {
                "op": "interpolate",
                "params": {"min": self.low.value(), "max": self.high.value()},
            },
        ][self.tool.currentIndex()]

    def _preview(self):
        try:
            self.state.preview_operations(
                [self._operation()],
                self._ids(),
                source="manual",
                label=self.tool.currentText(),
            )
            self.status.setText(
                "Tečkovaná křivka ukazuje náhled. Použij jej po kontrole."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def _sync(self):
        preview = self.state.preview_summary
        self.apply_button.setEnabled(
            bool(
                preview
                and preview.get("source") == "manual"
                and self.state.active_spectrum_id in preview.get("spectrum_ids", [])
            )
        )

    def _apply(self):
        try:
            self.state.apply_preview()
            self.status.setText("Úprava uložena do historie.")
        except ValueError as exc:
            self.status.setText(str(exc))

    def _reset(self):
        try:
            self.state.reset_processing(self._ids())
        except ValueError as exc:
            self.status.setText(str(exc))
