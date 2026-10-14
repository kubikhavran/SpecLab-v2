"""Asynchronous AI plan editor: request → review → preview → explicit apply."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QThread, Signal
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

from core.ai_client import DEFAULT_BASE_URL, EInfraClient, parse_plan, spectrum_context


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
        self._proposal_revision = None
        self._proposal_ids = None
        self._proposal_source = "manual"
        self._own_preview_id = None
        self._build()
        state.preview_changed.connect(self._sync_apply)
        state.spectra_changed.connect(self._sync_apply)
        state.active_spectrum_changed.connect(self._sync_apply)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(
            "Popiš úpravu. AI navrhne kroky, jejich výsledek si prohlédneš v grafu."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)
        form = QFormLayout()
        self.url = QLineEdit(DEFAULT_BASE_URL)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("API klíč / E_INFRA_API_TOKEN")
        self.key.setToolTip("Klíč zůstává pouze v paměti po dobu běhu aplikace.")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setPlaceholderText("Načti nebo zadej ID modelu")
        form.addRow("API", self.url)
        form.addRow("Klíč", self.key)
        form.addRow("Model", self.model)
        layout.addLayout(form)
        self.models_button = QPushButton("Načíst dostupné modely")
        self.models_button.clicked.connect(self._models)
        layout.addWidget(self.models_button)
        self.samples = QCheckBox("Odeslat redukovaný náhled spektra")
        self.samples.setChecked(True)
        self.samples.setToolTip(
            "Nejvýše 258 bodů min/max obálky; bez názvu a cesty souboru. Jinak jen rozsahy a jednotky."
        )
        layout.addWidget(self.samples)
        context_button = QPushButton("Zobrazit odesílaná data")
        context_button.clicked.connect(self._show_context)
        layout.addWidget(context_button)
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
        layout.addWidget(QLabel("Návrh kroků · editovatelný JSON"))
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            '{"explanation":"…","warnings":[],"operations":[…]}'
        )
        self.editor.setMinimumHeight(160)
        self.editor.textChanged.connect(self._edited)
        layout.addWidget(self.editor)
        example = QPushButton("Vložit ukázkový plán (bez AI)")
        example.clicked.connect(self._example)
        layout.addWidget(example)
        self.preview_button = QPushButton("Spočítat náhled")
        self.preview_button.clicked.connect(self._preview)
        layout.addWidget(self.preview_button)
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
        return EInfraClient(
            self.key.text() or os.getenv("E_INFRA_API_TOKEN", ""), self.url.text()
        )

    def _context(self):
        spec = self.state.active_spectrum
        if spec is None:
            raise ValueError("Nejprve vyber spektrum.")
        return spectrum_context(
            spec, self.state.displayed_y(spec.id), self.samples.isChecked()
        )

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

    def _start(self, function, callback):
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = _RequestThread(function, self)
        self.request_button.setEnabled(False)
        self.models_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._thread.result.connect(callback)
        self._thread.failed.connect(self.status.setText)
        self._thread.finished.connect(self._finished)
        self._thread.start()

    def _finished(self):
        self.request_button.setEnabled(True)
        self.models_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self._thread and self._thread.isInterruptionRequested():
            self.status.setText("Požadavek byl zrušen.")

    def _cancel(self):
        if self._thread:
            self._thread.requestInterruption()
        self.status.setText(
            "Rušení požadavku… probíhající síťové čtení má omezený timeout."
        )

    def _models(self):
        try:
            client = self._client()
            self.status.setText("Načítám seznam modelů…")
            self._start(client.list_models, self._models_ready)
        except ValueError as exc:
            self.status.setText(str(exc))

    def _models_ready(self, models):
        self.model.clear()
        self.model.addItems(models)
        self.status.setText(f"Dostupné modely: {len(models)}. Vyber model pro návrh.")

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
            self._proposal_revision = self.state.revision
            self._proposal_ids = [self.state.active_spectrum_id]
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
                lambda plan: self._proposal_ready(plan, request_revision, request_ids),
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def _proposal_ready(self, plan, revision, spectrum_ids):
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

    def _example(self):
        self._proposal_source = "manual"
        self._proposal_revision = self.state.revision
        self._proposal_ids = (
            [self.state.active_spectrum_id] if self.state.active_spectrum_id else []
        )
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

    def _preview(self):
        try:
            if (
                self._proposal_revision is not None
                and self.state.revision != self._proposal_revision
            ):
                raise ValueError(
                    "Vstup se od vytvoření návrhu změnil. Vyžádej nový návrh."
                )
            if self._proposal_ids and self._proposal_ids != [
                self.state.active_spectrum_id
            ]:
                raise ValueError(
                    "Návrh patří jinému spektru. Vyber původní spektrum nebo vytvoř nový návrh."
                )
            plan = parse_plan(self.editor.toPlainText())
            if not plan["operations"]:
                raise ValueError(
                    plan["explanation"] or "Návrh neobsahuje žádné úpravy."
                )
            preview = self.state.preview_operations(
                plan["operations"],
                self._proposal_ids or None,
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

    def _sync_apply(self):
        preview = self.state.preview
        valid = bool(
            preview
            and preview.get("id") == self._own_preview_id
            and preview.get("revision") == self.state.revision
            and self.state.active_spectrum_id in preview.get("spectrum_ids", [])
        )
        self.apply_button.setEnabled(valid)

    def _apply(self):
        try:
            if (
                not self.state.preview
                or self.state.preview.get("id") != self._own_preview_id
            ):
                raise ValueError("Nejprve vytvoř náhled tohoto návrhu.")
            self.state.apply_preview(self.state.preview)
            self._proposal_revision = None
            self._proposal_ids = None
            self._own_preview_id = None
            self.status.setText(
                "Návrh byl použit. Pokračuj ručními nástroji nebo vrať celý krok přes Zpět."
            )
        except ValueError as exc:
            self.status.setText(str(exc))

    def shutdown(self) -> bool:
        if self._thread and self._thread.isRunning():
            self._thread.requestInterruption()
            return False
        return True
