"""Asynchronous AI plan editor: request → review → preview → explicit apply."""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.ai_client import (
    DEFAULT_BASE_URL,
    PREFERRED_MODEL,
    EInfraClient,
    chat_models,
    parse_plan,
    spectrum_context,
    stored_api_key,
)
from ui.busy import with_busy_cursor


class _RequestThread(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            result = self.function()
            if not self.isInterruptionRequested():
                self.result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class AIPanel(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._thread = None
        self._active_client = None
        self._proposal_revision = None
        self._proposal_signature = None
        self._proposal_ids = None
        self._proposal_source = "manual"
        self._own_preview_id = None
        self._plan = None
        self._build()
        state.preview_changed.connect(self._sync_apply)
        state.spectra_changed.connect(self._sync_apply)
        state.active_spectrum_changed.connect(self._sync_apply)

    def _target_ids(self):
        return (
            self.get_ids()
            if hasattr(self, "get_ids")
            else (
                [self.state.active_spectrum_id] if self.state.active_spectrum_id else []
            )
        )

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(
            "Popiš úpravu. AI navrhne kroky, jejich výsledek si prohlédneš v grafu."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)
        connection = QWidget()
        connection_layout = QVBoxLayout(connection)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_toggle = QPushButton("Nastavení připojení e-INFRA…")
        connection_toggle.setCheckable(True)
        connection_toggle.toggled.connect(connection.setVisible)
        layout.addWidget(connection_toggle)
        layout.addWidget(connection)
        connection.hide()
        form = QFormLayout()
        # Endpoint and model are remembered between sessions; the key never is.
        self._settings = QSettings("SpecLab", "SpecLab Studio")
        self.url = QLineEdit(str(self._settings.value("ai/base_url", DEFAULT_BASE_URL)))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Prázdné = Klíčenka / E_INFRA_API_TOKEN")
        self.key.setToolTip(
            "Zadaný klíč zůstává jen v paměti. Prázdné pole použije klíč uložený "
            "v Klíčence macOS (služba e-infra-api) nebo proměnnou E_INFRA_API_TOKEN."
        )
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setPlaceholderText("Načti nebo zadej ID modelu")
        saved_model = str(self._settings.value("ai/model", ""))
        if saved_model:
            self.model.addItem(saved_model)
            self.model.setCurrentText(saved_model)
        form.addRow("API", self.url)
        form.addRow("Klíč", self.key)
        form.addRow("Model", self.model)
        connection_layout.addLayout(form)
        self.models_button = QPushButton("Načíst dostupné modely")
        self.models_button.clicked.connect(self._models)
        connection_layout.addWidget(self.models_button)
        self.samples = QCheckBox("Odeslat redukovaný náhled spektra")
        self.samples.setChecked(True)
        self.samples.setToolTip(
            "Nejvýše 258 bodů na každé vybrané spektrum; cesty se neodesílají. Názvy zapni samostatně níže."
        )
        connection_layout.addWidget(self.samples)
        self.send_names = QCheckBox("Odeslat názvy spekter (pro přejmenování a pořadí)")
        connection_layout.addWidget(self.send_names)
        context_button = QPushButton("Zobrazit odesílaná data")
        context_button.clicked.connect(self._show_context)
        connection_layout.addWidget(context_button)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Např. jemně odstraň baseline a šum, zachovej úzké Ramanovy pásy…"
        )
        self.prompt.setFixedHeight(88)
        layout.addWidget(self.prompt)
        row = QHBoxLayout()
        self.request_button = QPushButton("Navrhnout úpravy")
        self.request_button.setObjectName("primary")
        self.request_button.clicked.connect(self._propose)
        self.cancel_button = QPushButton("Zrušit")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        row.addWidget(self.request_button, 1)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.status = QLabel("AI není připojena. Ruční nástroje jsou dostupné offline.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        self.plan_summary = QLabel("Zde se zobrazí navržené kroky.")
        self.plan_summary.setWordWrap(True)
        layout.addWidget(self.plan_summary)
        advanced = QPushButton("Pokročilé: upravit plán JSON")
        advanced.setCheckable(True)
        layout.addWidget(advanced)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            '{"explanation":"…","warnings":[],"operations":[…]}'
        )
        self.editor.setMinimumHeight(160)
        self.editor.textChanged.connect(self._edited)
        layout.addWidget(self.editor)
        self.editor.hide()
        advanced.toggled.connect(self.editor.setVisible)
        self.use_data = QCheckBox("Použít zpracování dat")
        self.use_style = QCheckBox("Použít grafiku a detekci píků")
        self.use_collection = QCheckBox("Použít názvy, pořadí a individuální čáry")
        for check in (self.use_data, self.use_style, self.use_collection):
            check.setChecked(True)
            check.toggled.connect(self._edited)
            layout.addWidget(check)
        example = QPushButton("Vložit ukázkový plán (bez AI)")
        example.clicked.connect(self._example)
        layout.addWidget(example)
        self.preview_button = QPushButton("Spočítat náhled")
        self.preview_button.clicked.connect(self._preview)
        layout.addWidget(self.preview_button)
        full_preview = QPushButton("Prohlédnout celý návrh grafu…")
        full_preview.clicked.connect(self._view_preview)
        layout.addWidget(full_preview)
        row = QHBoxLayout()
        self.apply_button = QPushButton("Použít návrh")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        discard = QPushButton("Zahodit náhled")
        discard.clicked.connect(self.state.clear_preview)
        row.addWidget(self.apply_button, 1)
        row.addWidget(discard)
        layout.addLayout(row)
        layout.addStretch()

    def _client(self):
        return EInfraClient(self.key.text() or stored_api_key(), self.url.text())

    def _context(self):
        spec = self.state.active_spectrum
        if spec is None:
            raise ValueError("Nejprve vyber spektrum.")
        context = spectrum_context(
            spec, self.state.displayed_y(spec.id), self.samples.isChecked()
        )
        # Current figure state lets the model improve rather than replace it.
        graphics, peaks = self.state.graphics, self.state.peaks_settings
        context["figure"] = {
            "x_label": graphics.x_label,
            "y_label": graphics.y_label,
            "font_family": graphics.font_family,
            "palette": graphics.palette,
            "peak_polarity": peaks.polarity,
            "peak_min_prominence": peaks.min_prominence,
            "peaks_shown": len(self.state.peaks_auto.get(spec.id, []))
            + len(self.state.peaks_manual.get(spec.id, [])),
        }
        ids = self._target_ids()
        if not ids:
            raise ValueError("Vyber alespoň jedno spektrum pro AI návrh.")
        context["target_ids"] = ids
        context["collection"] = [
            dict(id=s.id, **({"name": s.name} if self.send_names.isChecked() else {}))
            for s in self.state.spectra
        ]
        context["targets"] = [
            dict(
                id=s.id,
                **spectrum_context(
                    s, self.state.displayed_y(s.id), self.samples.isChecked()
                ),
            )
            for s in self.state.spectra
            if s.id in ids
        ]
        if len(context["targets"]) > 30:
            raise ValueError(
                "Pro jeden AI návrh vyber nejvýše 30 spekter; další lze zpracovat uloženým presetem."
            )
        return context

    def _show_context(self):
        try:
            context = self._context()
            message = QMessageBox(self)
            message.setWindowTitle("Data pro AI")
            message.setText(
                "Odešle se tvoje zadání, níže uvedené parametry spektra a popis dostupných operací."
            )
            message.setDetailedText(json.dumps(context, indent=2, ensure_ascii=False))
            message.exec()
        except ValueError as exc:
            self.status.setText(str(exc))

    def _start(self, function, callback, client=None):
        if self._thread is not None and self._thread.isRunning():
            return
        self._active_client = client
        self._thread = _RequestThread(function, self)
        self.request_button.setEnabled(False)
        self.models_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._thread.result.connect(callback)
        self._thread.failed.connect(self.status.setText)
        self._thread.finished.connect(self._finished)
        self._thread.start()

    def _finished(self):
        self._active_client = None
        self.request_button.setEnabled(True)
        self.models_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self._thread and self._thread.isInterruptionRequested():
            self.status.setText("Požadavek byl zrušen.")

    def _cancel(self):
        if self._thread:
            self._thread.requestInterruption()
        if self._active_client is not None:
            self._active_client.cancel()
        self.status.setText("Ruším požadavek…")

    def _models(self):
        try:
            client = self._client()
            self.status.setText("Načítám seznam modelů…")
            self._start(client.list_models, self._models_ready, client)
        except ValueError as exc:
            self.status.setText(str(exc))

    def _models_ready(self, models):
        current = self.model.currentText().strip()
        usable = chat_models(models)
        self.model.clear()
        self.model.addItems(usable)
        for choice in (current, PREFERRED_MODEL):
            if choice and choice in usable:
                self.model.setCurrentText(choice)
                break
        hidden = len(models) - len(usable)
        self.status.setText(
            f"Dostupné modely: {len(usable)}"
            + (f" (skryto {hidden} embedding/řečových)" if hidden else "")
            + ". Vyber model pro návrh."
        )

    def _propose(self):
        if self._thread is not None and self._thread.isRunning():
            return
        try:
            client = self._client()
            context = self._context()
            model, prompt = (
                self.model.currentText().strip(),
                self.prompt.toPlainText().strip(),
            )
            if not model or not prompt:
                raise ValueError("Vyber model a napiš požadovanou úpravu.")
            self._settings.setValue("ai/model", model)
            self._settings.setValue("ai/base_url", self.url.text().strip())
            self._proposal_revision = self.state.revision
            self._proposal_ids = self._target_ids()
            request_signature = self.state._workflow_signature()
            request_revision = self._proposal_revision
            request_ids = list(self._proposal_ids)
            self.state.clear_preview()
            self.status.setText("AI připravuje návrh… data se zatím nemění.")
            self._start(
                lambda: client.propose(
                    model,
                    prompt,
                    context,
                    cancel=lambda: self._thread.isInterruptionRequested(),
                ),
                lambda plan: self._proposal_ready(
                    plan, request_revision, request_ids, request_signature
                ),
                client,
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def _proposal_ready(self, plan, revision, spectrum_ids, signature=None):
        self._proposal_signature = signature
        # Bind to the immutable target captured by this request's callback.
        self._proposal_revision = revision
        self._proposal_ids = list(spectrum_ids)
        self._proposal_source = "ai"
        # textChanged invalidates preview but must not change the captured input revision.
        self.editor.setPlainText(json.dumps(plan, indent=2, ensure_ascii=False))
        text = plan["explanation"] + (
            "\n" + "\n".join(plan["warnings"]) if plan["warnings"] else ""
        )
        if self.state.revision != self._proposal_revision:
            text = "Spektrum se mezitím změnilo. Vyžádej nový návrh.\n" + text
        self.status.setText(text)

    def _edited(self):
        self._own_preview_id = None
        self.state.clear_preview()
        try:
            from ui.workflow import TOOLS, PARAMETERS, SECTIONS

            plan = parse_plan(self.editor.toPlainText())
            names = {key: values[0] for key, values in PARAMETERS.items()}
            titles = {
                key: title
                for section in SECTIONS.values()
                for owner, key, title in section
            }
            titles.update(
                {
                    "detect_peaks": "Najít píky",
                    "polarity": "Polarita",
                    "min_prominence": "Prominence",
                    "min_distance": "Min. vzdálenost",
                    "max_peaks": "Počet píků",
                    "relative_prominence": "Relativní prominence",
                }
            )

            def display(value):
                return (
                    "ano" if value is True else "ne" if value is False else str(value)
                )

            lines = [
                f"{i + 1}. {TOOLS.get(op['op'], (op['op'],))[0]}: "
                + ", ".join(
                    f"{names.get(k, k)} = {display(v)}"
                    for k, v in op.get("params", {}).items()
                )
                for i, op in enumerate(plan["operations"])
            ]
            for section, values in plan.get("presentation", {}).items():
                if isinstance(values, dict):
                    lines.extend(
                        f"{titles.get(k, k)}: {display(v)}" for k, v in values.items()
                    )
                else:
                    lines.append(f"{titles.get(section, section)}: {display(values)}")
            collection = plan.get("collection", {})
            loaded = {s.id: s.name for s in self.state.spectra}
            lines.extend(
                f"Název: {loaded.get(sid, sid)} → {name}"
                for sid, name in collection.get("rename", {}).items()
            )
            if "order" in collection:
                lines.append(
                    "Pořadí: "
                    + " → ".join(
                        collection.get("rename", {}).get(sid, loaded.get(sid, sid))
                        for sid in collection["order"]
                    )
                )
            for sid, style in collection.get("styles", {}).items():
                lines.append(
                    f"Čára {loaded.get(sid, sid)}: "
                    + ", ".join(f"{k} = {v}" for k, v in style.items())
                )
            self.plan_summary.setText("\n".join(lines) or plan["explanation"])
        except ValueError:
            self.plan_summary.setText("Nejprve vytvoř nebo vlož platný návrh.")

    def _example(self):
        self._proposal_source = "manual"
        self._proposal_revision = self.state.revision
        self._proposal_signature = self.state._workflow_signature()
        self._proposal_ids = self._target_ids()
        self.editor.setPlainText(
            json.dumps(
                {
                    "explanation": "Ukázka jemného vyhlazení. Nevytvořila ji AI.",
                    "warnings": ["Ověř zachování úzkých pásů v náhledu."],
                    "operations": [
                        {"op": "smooth", "params": {"window": 11, "poly_order": 3}}
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    @with_busy_cursor
    def _preview(self):
        try:
            if (
                self._proposal_signature is not None
                and self._proposal_signature != self.state._workflow_signature()
            ):
                raise ValueError("Nastavení se od návrhu změnilo. Vyžádej nový návrh.")
            if (
                self._proposal_revision is not None
                and self.state.revision != self._proposal_revision
            ):
                raise ValueError(
                    "Vstup se od vytvoření návrhu změnil. Vyžádej nový návrh."
                )
            if self._proposal_ids and self._proposal_ids != self._target_ids():
                raise ValueError(
                    "Návrh patří jinému výběru. Vrať původní rozsah nebo vytvoř nový návrh."
                )
            plan = parse_plan(self.editor.toPlainText())
            self._plan = plan
            preview = self.state.preview_workflow(
                operations=plan["operations"] if self.use_data.isChecked() else [],
                presentation=plan.get("presentation")
                if self.use_style.isChecked()
                else None,
                collection=plan.get("collection")
                if self.use_collection.isChecked()
                else None,
                spectrum_ids=self._proposal_ids or self._target_ids(),
                source=self._proposal_source,
                label="AI návrh"
                if self._proposal_source == "ai"
                else "Ručně vložený plán",
            )
            self._own_preview_id = preview["id"]
            self._sync_apply()
            self.status.setText(
                "Náhled je v grafu. Plná data zůstávají beze změny do použití návrhu."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def _view_preview(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        from ui.plot_widget import SpectrumPlotWidget

        staged = self.state.preview_state()
        if staged is None:
            self.status.setText("Nejprve spočítej náhled návrhu.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Náhled AI · data, grafika a názvy před použitím")
        dialog.resize(1000, 700)
        layout = QVBoxLayout(dialog)
        graph = SpectrumPlotWidget(staged)
        layout.addWidget(graph)
        layout.addWidget(
            QLabel(
                "Zavřením náhledu se nic nepoužije. Potvrď návrh tlačítkem Použít návrh."
            )
        )
        dialog.exec()

    def _sync_apply(self):
        preview = self.state.preview_summary
        valid = bool(
            preview
            and preview.get("id") == self._own_preview_id
            and preview.get("revision") == self.state.revision
            and self._target_ids() == preview.get("spectrum_ids", [])
        )
        self.apply_button.setEnabled(valid)

    @with_busy_cursor
    def _apply(self):
        try:
            summary = self.state.preview_summary
            if (
                not summary
                or summary.get("id") != self._own_preview_id
                or summary["spectrum_ids"] != self._target_ids()
            ):
                raise ValueError(
                    "Nejprve vytvoř náhled tohoto návrhu pro aktuální výběr."
                )
            self.state.apply_preview()
            found = 0
            self._plan = None
            self._proposal_revision = None
            self._proposal_signature = None
            self._proposal_ids = None
            self._own_preview_id = None
            self.status.setText(
                "Návrh byl použit"
                + (f" · nalezeno píků: {found}" if found else "")
                + ". Pokračuj ručními nástroji nebo vrať kroky přes Zpět."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def shutdown(self, wait_ms: int = 3000) -> bool:
        """Cancel a running request; True once no network thread remains."""
        if self._thread and self._thread.isRunning():
            self._cancel()
            return self._thread.wait(wait_ms)
        return True

    def quit_when_idle(self) -> None:
        """Quit the application once a still-connecting request gives up.

        A connection that has not delivered a response yet cannot be interrupted;
        the thread ends at the latest after the client timeout.
        """
        from PySide6.QtWidgets import QApplication

        if self._thread and self._thread.isRunning():
            self._thread.finished.connect(QApplication.quit)
        else:
            QApplication.quit()
