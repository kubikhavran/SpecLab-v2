"""Step-oriented controls; processing and appearance have separate commit paths."""

from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QPushButton,
    QColorDialog,
)
from core.project_io import SETTINGS
from ui.controls import NumberField
from ui.graphics_panel import _PALETTE_OPTIONS, _FONT_FAMILIES
from ui.busy import with_busy_cursor


def action_row(layout, apply, reset, preview=None):
    row = QHBoxLayout()
    if preview:
        button = QPushButton("Náhled")
        button.clicked.connect(preview)
        row.addWidget(button)
    use = QPushButton("Použít")
    use.setObjectName("primary")
    use.clicked.connect(apply)
    row.addWidget(use)
    clear = QPushButton("Reset")
    clear.setObjectName("reset")
    clear.clicked.connect(reset)
    row.addWidget(clear)
    layout.addLayout(row)
    return use, clear


def note(text):
    widget = QLabel(text)
    widget.setObjectName("muted")
    widget.setWordWrap(True)
    return widget


# All numerical limits follow the processing validator, not arbitrary UI limits.
PARAMETERS = {
    "lam": ("Lambda", 1.0, 1e12, 1e6, {"log": True}),
    "p": ("Asymetrie p", 0.000001, 0.999999, 0.01, {"log": True}),
    "iterations": ("Iterace", 1, 100, 10, {"integer": True}),
    "window": ("Okno (body)", 3, 1001, 11, {"integer": True, "odd": True}),
    "poly_order": ("Řád polynomu", 0, 9, 3, {"integer": True}),
    "threshold": ("Práh", 0.1, 100.0, 6.0, {"log": True}),
    "max_width": ("Max. šířka (body)", 1, 100, 5, {"integer": True}),
    "min": ("Minimum X", -1e12, 1e12, 0.0, {}),
    "max": ("Maximum X", -1e12, 1e12, 4000.0, {}),
    "step": ("Krok X", 1e-9, 1e12, 1.0, {"log": True}),
    "x": ("Posun X", -1e12, 1e12, 0.0, {}),
    "y": ("Posun Y", -1e12, 1e12, 0.0, {}),
    "factor": ("Násobek Y", -1e12, 1e12, 1.0, {}),
    "order": ("Řád derivace", 1, 2, 1, {"integer": True}),
}
CHOICES = {
    "method": [
        ("Maximum = 1", "max"),
        ("Vektorová norma", "vector"),
        ("Plocha = 1", "area"),
        ("Min–max (0–1)", "minmax"),
    ],
    "target": [
        ("Absorbance", "absorbance"),
        ("Transmitance (%)", "transmittance_percent"),
        ("Transmitance (0–1)", "transmittance_fraction"),
    ],
}
TOOLS = {
    "crop": (
        "Ořez dat",
        ["min", "max"],
        "Zachová zadaný interval v datech. Rozsahy samotného obrázku jsou v kroku Osy.",
    ),
    "convert_y": (
        "Absorbance / transmitance",
        ["target"],
        "Převádí hodnoty podle typu Y nastaveného u spektra. A = −log₁₀(T).",
    ),
    "resample": (
        "Převzorkování",
        ["step"],
        "Lineární interpolace na rovnoměrnou osu X. Nevytváří nové měření.",
    ),
    "despike": (
        "Cosmic ray removal",
        ["window", "threshold", "max_width", "positive_only", "iterations"],
        "Odstraní úzké odlehlé špičky. Pro série lze porovnat sousední spektra v pořadí seznamu.",
    ),
    "interpolate": (
        "Ruční interpolace",
        ["min", "max"],
        "Nahradí interval přímkou mezi sousedními platnými body. Zkontroluj, zda jde o artefakt.",
    ),
    "baseline": (
        "AsLS baseline",
        ["lam", "p", "iterations"],
        "Vyšší lambda dává hladší baseline. Před použitím lze spočítat náhled.",
    ),
    "smooth": (
        "Savitzky–Golay",
        ["window", "poly_order"],
        "Vol malé liché okno vůči šířce pásů. Silné vyhlazení mění skutečné pásy.",
    ),
    "derivative": (
        "Derivace",
        ["order", "window", "poly_order"],
        "1. nebo 2. derivace; vyžaduje rovnoměrné vzorkování X.",
    ),
    "normalize": (
        "Normalizace",
        ["method"],
        "Mění exportované hodnoty Y na relativní intenzitu. Full / Common scale jsou samostatně v Rozložení.",
    ),
    "scale": (
        "Násobení intenzity",
        ["factor"],
        "Výsledná intenzita je relativní; násobek se ukládá do receptu.",
    ),
    "shift": (
        "Posun dat X / Y",
        ["x", "y"],
        "Mění souřadnice dat. Rozestup křivek pro obrázek se nastavuje v Rozložení.",
    ),
}


class DataStep(QWidget):
    def __init__(self, state, tools, get_ids, parent=None):
        super().__init__(parent)
        self.state, self.get_ids = state, get_ids
        self._preview_id = None
        self._preview_scope = None
        self._preview_mode = "normal"
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.tool = QComboBox()
        for op in tools:
            self.tool.addItem(TOOLS[op][0], op)
        layout.addWidget(self.tool)
        self.explanation = note("")
        layout.addWidget(self.explanation)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setSpacing(10)
        layout.addLayout(self.form)
        for key in dict.fromkeys(k for op in tools for k in TOOLS[op][1]):
            if key in CHOICES:
                field = QComboBox()
                for text, value in CHOICES[key]:
                    field.addItem(text, value)
                name = "Metoda" if key == "method" else "Cílový typ Y"
                field.currentIndexChanged.connect(self._changed)
            elif key == "positive_only":
                name, field = "", QCheckBox("Pouze kladné spiky")
                field.setChecked(True)
                field.toggled.connect(self._changed)
            else:
                name, low, high, value, options = PARAMETERS[key]
                if key == "window" and "despike" in tools:
                    low = 5
                if key == "iterations" and "despike" in tools:
                    value = 2
                field = NumberField(low, high, value, **options)
                field.valueChanged.connect(self._changed)
            self.form.addRow(name, field)
            self.fields[key] = field
        if tools == ["baseline"]:
            overlay = QCheckBox("Zobrazit odhad baseline")
            overlay.setChecked(state.baseline.show_overlay)
            overlay.toggled.connect(lambda v: state.set_baseline(show_overlay=v))
            layout.addWidget(overlay)
        self.apply_button, self.reset_button = action_row(
            layout, self._apply, self._reset, self._preview
        )
        if "despike" in tools:
            series = QPushButton("Náhled podle sousedů v sérii")
            series.clicked.connect(self._series)
            layout.addWidget(series)
        self.status = note("Náhled nemění data. Použít zapíše krok do historie.")
        layout.addWidget(self.status)
        layout.addStretch()
        self.tool.currentIndexChanged.connect(self._show_tool)
        state.active_spectrum_changed.connect(self._input_range)
        self._show_tool()
        for signal in (
            state.baseline_changed,
            state.smoothing_changed,
            state.cosmic_changed,
        ):
            signal.connect(self._sync_parameters)
        self._sync_parameters()

    def _sync_parameters(self):
        self._loading = True
        group = {
            "baseline": self.state.baseline,
            "smooth": self.state.smoothing,
            "despike": self.state.cosmic,
        }.get(self.tool.currentData())
        if group:
            for key, field in self.fields.items():
                name = "lambda_" if key == "lam" else key
                if hasattr(group, name):
                    value = getattr(group, name)
                    if isinstance(field, QCheckBox):
                        field.setChecked(value)
                    else:
                        field.setValue(value)

        self._loading = False

    def _input_range(self):
        spec = self.state.active_spectrum
        if spec and "min" in self.fields:
            self.fields["min"].setValue(min(spec.x))
            self.fields["max"].setValue(max(spec.x))

    def _show_tool(self):
        op = self.tool.currentData()
        self.explanation.setText(TOOLS[op][2])
        for key, field in self.fields.items():
            visible = key in TOOLS[op][1]
            field.setVisible(visible)
            if self.form.labelForField(field):
                self.form.labelForField(field).setVisible(visible)
        self._changed()

    def _changed(self, *_):
        if getattr(self, "_loading", False):
            return
        if (
            self._preview_id
            and (self.state.preview_summary or {}).get("id") == self._preview_id
        ):
            self.state.clear_preview()
        self._preview_id = None
        self._preview_scope = None
        self._preview_mode = "normal"

    def _operation(self):
        op = self.tool.currentData()
        params = {}
        for key in TOOLS[op][1]:
            field = self.fields[key]
            params[key] = (
                field.currentData()
                if isinstance(field, QComboBox)
                else field.isChecked()
                if isinstance(field, QCheckBox)
                else field.value()
            )
        return {"op": op, "params": params}

    @with_busy_cursor
    def _preview(self):
        try:
            proposal = self.state.preview_operations(
                [self._operation()], self.get_ids(), label=self.tool.currentText()
            )
            self._preview_id = proposal["id"]
            self._preview_scope = list(self.get_ids())
            self._preview_mode = "normal"
            self.status.setText(
                "Tečkovaná křivka = náhled. Použít potvrdí tento výsledek."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    @with_busy_cursor
    def _apply(self):
        try:
            preview = self.state.preview_summary
            if (
                not preview
                or preview["id"] != self._preview_id
                or self._preview_scope != self.get_ids()
            ):
                if self._preview_mode == "series":
                    self._series()
                else:
                    self._preview()
                preview = self.state.preview_summary
            if preview and preview["id"] == self._preview_id:
                self.state.apply_preview()
                self.status.setText("Použito. Změnu lze vrátit pomocí Zpět.")
        except ValueError as exc:
            self.status.setText(str(exc))

    @with_busy_cursor
    def _reset(self):
        try:
            self.state.reset_operation(self.tool.currentData(), self.get_ids())
            self.status.setText(
                "Tento nástroj byl odebrán z receptu; další kroky byly přepočítány."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    @with_busy_cursor
    def _series(self):
        self._preview_mode = "series"
        try:
            proposal = self.state.preview_series_despike(self.get_ids())
            self._preview_id = proposal["id"] if proposal else None
            self._preview_scope = list(self.get_ids())
            self.status.setText(
                "Náhled série připraven."
                if proposal
                else "V sérii nebyly nalezeny spiky."
            )
        except ValueError as exc:
            self.status.setText(str(exc))


# Each property appears once in the workflow. Font sizes are shown in legacy
# SpecLab units, explicitly explained; old presets therefore retain their size.
SECTIONS = {
    "lines": [
        ("graphics", "palette", "Paleta"),
        ("graphics", "trace_line_width", "Šířka všech křivek"),
    ],
    "axes": [
        ("graphics", key, title)
        for key, title in [
            ("x_label", "Název X"),
            ("y_label", "Název Y"),
            ("font_family", "Písmo"),
            ("base_font_size", "Velikost názvů os"),
            ("tick_font_size", "Velikost hodnot os"),
            ("axis_label_bold", "Tučné názvy os"),
            ("axis_label_italic", "Názvy os kurzívou"),
            ("tick_label_bold", "Tučné hodnoty os"),
            ("tick_label_italic", "Hodnoty os kurzívou"),
            ("show_x_tick_labels", "Hodnoty X"),
            ("show_y_tick_labels", "Hodnoty Y"),
            ("show_x_tick_marks", "Značky X"),
            ("show_y_tick_marks", "Značky Y"),
            ("axis_line_width", "Šířka os"),
            ("axis_line_color", "Barva os"),
            ("frame_mode", "Rámeček"),
            ("show_grid", "Mřížka v exportu"),
            ("grid_color", "Barva mřížky"),
            ("grid_width", "Šířka mřížky"),
        ]
    ]
    + [("plot", "invert_x", "Obrátit osu X")],
    "layout": [
        ("plot", "scale_mode", "Měřítko zobrazení"),
        ("plot", "stack_offset", "Rozestup série"),
        ("plot", "reverse_overlay_order", "Obrátit pořadí v grafu"),
        ("graphics", "inline_spectrum_labels", "Názvy u křivek"),
        ("graphics", "spectrum_label_bold", "Tučné názvy křivek"),
        ("graphics", "spectrum_label_italic", "Názvy křivek kurzívou"),
        ("graphics", "plot_canvas", "Plátno"),
        ("graphics", "preview_canvas_size", "Náhled rozměrů exportu"),
    ]
    + [
        ("peaks", key, title)
        for key, title in [
            ("show_markers", "Značky píků"),
            ("show_labels", "Popisky píků"),
            ("show_leader_lines", "Vodicí čáry"),
            ("label_angle_deg", "Úhel popisků"),
            ("label_font_size", "Velikost popisků"),
            ("label_bold", "Tučné popisky"),
            ("label_italic", "Popisky kurzívou"),
            ("decimals", "Desetinná místa"),
            ("label_color_mode", "Barva popisků"),
            ("label_color", "Vlastní barva popisků"),
            ("leader_color_mode", "Barva vodicích čar"),
            ("leader_color", "Vlastní barva čar"),
            ("leader_line_width", "Šířka vodicích čar"),
        ]
    ],
}
OPTIONS = {
    "palette": _PALETTE_OPTIONS,
    "font_family": [(f, f) for f in _FONT_FAMILIES],
    "frame_mode": [("Otevřený", "open"), ("Uzavřený", "box")],
    "plot_canvas": [("Světlé", "auto"), ("Bílé", "white"), ("Tmavé", "dark")],
    "scale_mode": [
        ("Common scale · společné Y", "common"),
        ("Full scale · každá křivka 0–1", "full"),
    ],
    "label_color_mode": [("Podle křivky", "trace"), ("Vlastní", "custom")],
    "leader_color_mode": [("Podle křivky", "trace"), ("Vlastní", "custom")],
}


class AppearanceStep(QWidget):
    def __init__(self, state, kind, get_ids, parent=None):
        super().__init__(parent)
        self.state, self.kind, self.get_ids = state, kind, get_ids
        self.controls = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        if kind in ("axes", "layout"):
            layout.addWidget(
                note(
                    "Velikost písma: jednotky SpecLabu = 3 × body (30 = 10 pt v exportu)."
                )
            )
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(10)
        layout.addLayout(form)
        for owner, key, title in SECTIONS[kind]:
            default = getattr(SETTINGS[owner][1](), key)
            if key in OPTIONS:
                field = QComboBox()
                for text, value in OPTIONS[key]:
                    field.addItem(text, value)
            elif isinstance(default, bool):
                field = QCheckBox(title)
                title = ""
            elif isinstance(default, (float, int)):
                low, high = (
                    (1, 300)
                    if "font_size" in key
                    else (0, 10)
                    if key == "decimals"
                    else (-180, 180)
                    if key == "label_angle_deg"
                    else (-1e12, 1e12)
                    if key == "stack_offset"
                    else (1, 100)
                )
                field = NumberField(
                    low, high, default, integer=isinstance(default, int)
                )
            else:
                field = QLineEdit()
                if key.endswith("_color"):
                    field.setPlaceholderText("#RRGGBB")
                    pick = QAction("Vybrat barvu", field)
                    field.addAction(pick, QLineEdit.ActionPosition.TrailingPosition)
                    pick.triggered.connect(
                        lambda checked=False, w=field: self._choose_color(w)
                    )
            self.controls[owner, key] = field
            form.addRow(title, field)
        action_row(layout, self._apply, self._reset)
        if kind == "lines":
            layout.addWidget(QLabel("Individuální vzhled · podle rozsahu nahoře"))
            self.trace_visible = QCheckBox("Zobrazit v porovnání")
            self.trace_visible.setChecked(True)
            layout.addWidget(self.trace_visible)
            self.trace_color = QLineEdit()
            self.trace_color.setPlaceholderText("Prázdné = automatická paleta")
            pick_color = QPushButton("Vybrat barvu…")
            pick_color.clicked.connect(lambda: self._choose_color(self.trace_color))
            layout.addWidget(pick_color)
            self.trace_width = NumberField(0.1, 100.0, 3.0)
            self.trace_line = QComboBox()
            for name, value in [
                ("Plná", "solid"),
                ("Čárkovaná", "dash"),
                ("Tečkovaná", "dot"),
                ("Čerchovaná", "dashdot"),
            ]:
                self.trace_line.addItem(name, value)
            layout.addWidget(self.trace_color)
            layout.addWidget(self.trace_width)
            layout.addWidget(self.trace_line)
            action_row(layout, self._apply_trace, self._reset_trace)
            state.active_spectrum_changed.connect(self._sync_trace)
            state.spectra_changed.connect(self._sync_trace)
        self.status = note(
            "Nastav parametry a potvrď Použít. Reset obnoví nastavení tohoto kroku."
        )
        layout.addWidget(self.status)
        layout.addStretch()
        for signal in (state.graphics_changed, state.peaks_changed, state.plot_changed):
            signal.connect(self.sync)
        self.sync()

    def _choose_color(self, field):
        color = QColorDialog.getColor(QColor(field.text() or "#14756f"), self)
        if color.isValid():
            field.setText(color.name())

    @staticmethod
    def _value(field):
        return (
            field.currentData()
            if isinstance(field, QComboBox)
            else field.isChecked()
            if isinstance(field, QCheckBox)
            else field.text()
            if isinstance(field, QLineEdit)
            else field.value()
        )

    def sync(self):
        for (owner, key), field in self.controls.items():
            value = getattr(getattr(self.state, SETTINGS[owner][0]), key)
            field.blockSignals(True)
            if isinstance(field, QComboBox):
                field.setCurrentIndex(field.findData(value))
            elif isinstance(field, QCheckBox):
                field.setChecked(value)
            elif isinstance(field, QLineEdit):
                field.setText(value)
            else:
                field.setValue(value)
            field.blockSignals(False)
        if self.kind == "lines":
            self._sync_trace()

    def _settings(self, defaults=False):
        settings = {}
        for (owner, key), field in self.controls.items():
            settings.setdefault(owner, {})[key] = (
                getattr(SETTINGS[owner][1](), key) if defaults else self._value(field)
            )
        return settings

    def _apply(self):
        try:
            self.state.commit_settings(
                self._settings(),
                "Vzhled: "
                + {"lines": "čáry", "axes": "osy", "layout": "rozložení"}[self.kind],
            )
            self.status.setText("Vzhled použit. Zpět vrátí celý tento krok.")
        except ValueError as exc:
            self.status.setText(str(exc))

    def _reset(self):
        self.state.commit_settings(self._settings(True), "Reset vzhledu")

    def _sync_trace(self):
        spec = self.state.active_spectrum
        style = spec.meta.get("trace_style", {}) if spec else {}
        self.trace_visible.setChecked(style.get("visible", True))
        self.trace_color.setText(style.get("color", ""))
        self.trace_width.setValue(
            style.get("width", self.state.graphics.trace_line_width)
        )
        self.trace_line.setCurrentIndex(
            self.trace_line.findData(style.get("line", "solid"))
        )

    def _trace(self, reset=False):
        try:
            style = (
                {}
                if reset
                else {
                    "visible": self.trace_visible.isChecked(),
                    "width": self.trace_width.value(),
                    "line": self.trace_line.currentData(),
                }
            )
            if not reset and self.trace_color.text().strip():
                style["color"] = self.trace_color.text().strip()
            ids = self.get_ids()
            self.state.preview_workflow(
                collection={"styles": {sid: style for sid in ids}},
                spectrum_ids=ids,
                label="Vzhled vybraných křivek",
            )
            self.state.apply_preview()
            self.status.setText("Vzhled křivek použit.")
        except ValueError as exc:
            self.status.setText(str(exc))

    def _apply_trace(self):
        self._trace()

    def _reset_trace(self):
        self._trace(True)
