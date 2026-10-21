"""Chat interface for the sandboxed SpecLab AI assistant."""

from __future__ import annotations

import html
import json
import time

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.ai_agent import AgentSession
from core.ai_attachments import image_attachment, load_attachment
from core.ai_client import (
    DEFAULT_BASE_URL,
    PREFERRED_MODEL,
    AIError,
    EInfraClient,
    chat_models,
    stored_api_key,
    supports_vision,
)
from core.ai_tools import Attachment


class _TurnThread(QThread):
    agent_event = Signal(str, object)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, session, text, attachments, note, parent=None):
        super().__init__(parent)
        self.session = session
        self.text = text
        self.attachments = attachments
        self.note = note

    def run(self):
        try:
            result = self.session.run_turn(
                self.text,
                self.attachments,
                cancel=self.isInterruptionRequested,
                note=self.note,
            )
            self.result.emit(result)
        except (AIError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - report instead of crashing the worker
            import traceback

            traceback.print_exc()
            self.failed.emit(f"Požadavek se nepodařilo dokončit ({type(exc).__name__}: {exc}).")


class _ModelsThread(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        try:
            self.result.emit(self.client.list_models())
        except AIError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Seznam modelů se nepodařilo načíst.")


class _ChatInput(QPlainTextEdit):
    pasted_image = Signal(bytes)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            image = self.parentWidget()._clipboard_image()
            if image:
                self.pasted_image.emit(image)
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        ):
            self.parentWidget()._send()
            return
        super().keyPressEvent(event)


class AIPanel(QWidget):
    """Dockable conversational assistant; changes remain staged until accepted."""

    _agent_event = Signal(str, object)
    preview_ready = Signal()     # a staged AI result can be shown in the main graph
    preview_closed = Signal()    # applied, discarded or invalidated

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setMinimumWidth(420)
        self.setAcceptDrops(True)
        self._settings = QSettings("SpecLab", "SpecLab Studio")
        self._thread = None
        self._models_thread = None
        self._active_client = None
        self._session = None
        self._pending: list[Attachment] = []
        self._note = ""
        self._preview_valid = False
        self._stream_text = ""
        self._started_at = 0.0
        self._title = ""
        self._own_preview_change = False   # our own staging/apply also emits preview_changed
        self._images: list[str] = []      # chat image resources, oldest first
        self._build()
        self._agent_event.connect(self._on_agent_event)
        state.preview_changed.connect(self._preview_changed)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._update_elapsed)
        self._new_session()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        header = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumContentsLength(24)
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if not self._settings.value("ai/agent_default_v2", False, type=bool):
            # The agent needs a tool-calling, vision-capable model; models chosen for
            # the former plan-only assistant are replaced once.
            self._settings.setValue("ai/model", PREFERRED_MODEL)
            self._settings.setValue("ai/agent_default_v2", True)
        saved_model = str(self._settings.value("ai/model", PREFERRED_MODEL))
        self.model.addItem(saved_model or PREFERRED_MODEL)
        self.model.setCurrentText(saved_model or PREFERRED_MODEL)
        self.model.setToolTip(
            "kimi-k3: nejschopnější model e-INFRA (nástroje + obrázky), důkladný, ale pomalejší – "
            "jedna zpráva obvykle 3–15 min.\n"
            "deepseek-v4.1-flash-thinking: v testech podobná kvalita, 3–5× rychlejší (1–7 min).\n"
            "Modely bez obrazového vstupu (glm-5.3, gpt-oss-120b) kontrolují obrázek jen textově."
        )
        for alternative in ("deepseek-v4.1-flash-thinking", "glm-5.3", "qwen3.8-flash-next"):
            if self.model.findText(alternative) < 0:
                self.model.addItem(alternative)
        self.models_button = QPushButton("Načíst modely")
        self.models_button.clicked.connect(self._load_models)
        self.new_button = QPushButton("Nová konverzace")
        self.new_button.clicked.connect(self._new_conversation)
        header.addWidget(self.model, 1)
        header.addWidget(self.models_button)
        header.addWidget(self.new_button)
        root.addLayout(header)

        self.model.currentTextChanged.connect(self._model_changed)
        self.connection_toggle = QPushButton("Připojení a soukromí")
        self.connection_toggle.setCheckable(True)
        root.addWidget(self.connection_toggle)
        self.connection = QWidget()
        self.connection.setObjectName("panelContents")
        connection_layout = QVBoxLayout(self.connection)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.url = QLineEdit(str(self._settings.value("ai/base_url", DEFAULT_BASE_URL)))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Prázdné = Klíčenka / E_INFRA_API_TOKEN")
        self.key.setToolTip("Zadaný klíč zůstává pouze v paměti.")
        form.addRow("API URL", self.url)
        form.addRow("API klíč", self.key)
        connection_layout.addLayout(form)
        self.send_names = QCheckBox("Posílat názvy spekter a souborů (AI z nich pozná laser a podmínky)")
        self.send_names.setChecked(self._settings.value("ai/send_names", True, type=bool))
        connection_layout.addWidget(self.send_names)
        self.data_button = QPushButton("Zobrazit odesílaná data")
        self.data_button.clicked.connect(self._show_data)
        connection_layout.addWidget(self.data_button)
        self.connection.hide()
        root.addWidget(self.connection)
        self.connection_toggle.toggled.connect(self.connection.setVisible)
        self.send_names.toggled.connect(self._names_changed)

        self.chat = QTextBrowser()
        self.chat.setOpenLinks(False)
        self.chat.setOpenExternalLinks(False)
        self.chat.anchorClicked.connect(self._open_image)
        self.chat.setStyleSheet(
            "QTextBrowser { background: #ffffff; border: 1px solid #dce4e5; "
            "border-radius: 8px; padding: 7px; }"
        )
        root.addWidget(self.chat, 1)
        self._append_html(
            '<div style="color:#697d84;padding:8px 4px;">Popiš, co chceš změnit. '
            "Např. „Dej spektra do offsetu a označ hlavní píky.“ "
            "„Obarvi křivky podle laseru a zkrať názvy.“</div>"
        )
        self.stream = QLabel()
        self.stream.setWordWrap(True)
        self.stream.setObjectName("muted")
        root.addWidget(self.stream)

        self.attachment_row = QWidget()
        self.attachment_layout = QHBoxLayout(self.attachment_row)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_layout.setSpacing(5)
        self.attachment_row.hide()
        root.addWidget(self.attachment_row)

        attach_row = QHBoxLayout()
        self.attach_button = QPushButton("Přiložit vzor…")
        self.attach_button.clicked.connect(self._choose_files)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        attach_row.addWidget(self.attach_button)
        attach_row.addWidget(self.status, 1)
        root.addLayout(attach_row)

        self.prompt = _ChatInput()
        self.prompt.setPlaceholderText(
            "Napiš požadavek…\n"
            "Např. „Srovnej baseline a zachovej ostré Ramanovy pásy.“\n"
            "„Označ 5 hlavních píků u každého spektra.“"
        )
        self.prompt.setMinimumHeight(90)
        self.prompt.pasted_image.connect(self._paste_image)
        root.addWidget(self.prompt)
        send_row = QHBoxLayout()
        send_row.addStretch(1)
        self.send_button = QPushButton("Odeslat")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self._send)
        self.stop_button = QPushButton("Zastavit")
        self.stop_button.clicked.connect(self._cancel)
        self.stop_button.hide()
        send_row.addWidget(self.send_button)
        send_row.addWidget(self.stop_button)
        root.addLayout(send_row)

        self.result_bar = QWidget()
        result_layout = QGridLayout(self.result_bar)
        result_layout.setContentsMargins(0, 4, 0, 0)
        self.apply_button = QPushButton("Použít změny")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self._apply)
        self.discard_button = QPushButton("Zahodit")
        self.discard_button.clicked.connect(self._discard)
        self.preview_button = QPushButton("Zobrazit náhled…")
        self.preview_button.clicked.connect(self._view_preview)
        self.publication_button = QPushButton("Publikační obrázek…")
        self.publication_button.clicked.connect(self._view_publication)
        result_layout.addWidget(self.apply_button, 0, 0)
        result_layout.addWidget(self.discard_button, 0, 1)
        result_layout.addWidget(self.preview_button, 1, 0)
        result_layout.addWidget(self.publication_button, 1, 1)
        self.result_bar.hide()
        root.addWidget(self.result_bar)

    def _make_client(self):
        return EInfraClient(self.key.text() or stored_api_key(), self.url.text(), timeout=600)

    def _selected_ids(self):
        getter = getattr(self, "get_ids", None)
        if callable(getter):
            return list(getter())
        return [self.state.active_spectrum_id] if self.state.active_spectrum_id else []

    def _new_session(self):
        model = self.model.currentText().strip() or PREFERRED_MODEL
        self._session = AgentSession(
            None,
            model,
            include_names=self.send_names.isChecked(),
            on_event=lambda kind, payload: self._agent_event.emit(kind, payload),
            vision=supports_vision(model),
        )
        self._sync_session()

    def _sync_session(self):
        self._session.sync(
            self.state._snapshot(),
            self.state._workflow_signature(),
            selected_ids=self._selected_ids(),
        )

    def _model_changed(self, model):
        if self._session is not None:
            self._session.model = model.strip() or PREFERRED_MODEL
            self._session.vision = supports_vision(self._session.model)

    def _names_changed(self, enabled):
        if self._session is not None:
            self._session.include_names = enabled
            if self._session.toolbox is not None:
                self._session.toolbox.hide_names = not enabled

    def _persist_settings(self):
        self._settings.setValue("ai/model", self.model.currentText().strip() or PREFERRED_MODEL)
        self._settings.setValue("ai/base_url", self.url.text().strip())
        self._settings.setValue("ai/send_names", self.send_names.isChecked())

    def _append_html(self, fragment):
        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(fragment)
        cursor.insertBlock()
        self.chat.setTextCursor(cursor)
        self.chat.ensureCursorVisible()

    def _bubble(self, label, text, background, color="#24343c"):
        safe = html.escape(text).replace("\n", "<br>")
        self._append_html(
            f'<div style="background:{background};color:{color};padding:8px 10px;'
            f'margin:5px 2px;border-radius:8px;"><b>{html.escape(label)}</b><br>{safe}</div>'
        )

    def _system_line(self, text, error=False):
        color = "#a33d32" if error else "#697d84"
        background = "#fff1ee" if error else "#f1f5f4"
        self._append_html(
            f'<div style="color:{color};background:{background};padding:5px 8px;'
            f'margin:4px 2px;border-radius:5px;">{html.escape(text)}</div>'
        )

    def _send(self):
        if self._thread is not None and self._thread.isRunning():
            return
        text = self.prompt.toPlainText().strip()
        if not text and not self._pending:
            return
        signature = self.state._workflow_signature()
        if signature != self._session.base_signature:
            if self._session.has_changes():
                self.state.clear_preview()
                self._note = (
                    "The user changed the workspace manually since your last turn; "
                    "continue from the current state."
                )
                self._system_line("Pracovní prostor se změnil; předchozí návrh byl zahozen.")
                self._set_result_visible(False)
                self.preview_closed.emit()
            # Spectra may have been loaded or edited since the last turn.
            self._sync_session()
        self._session.toolbox.selected = self._selected_ids()
        self._persist_settings()
        self._session.model = self.model.currentText().strip() or PREFERRED_MODEL
        self._session.vision = supports_vision(self._session.model)
        self._session.include_names = self.send_names.isChecked()
        try:
            self._active_client = self._make_client()
        except AIError as exc:
            self._system_line(str(exc), error=True)
            return
        self._session.client = self._active_client
        attachments = list(self._pending)
        self._pending.clear()
        self._refresh_chips()
        self._bubble("Vy", text or "Přiložené soubory", "#e8f2ef")
        if text and not self._title:
            self._title = text
        for attachment in attachments:
            self._system_line(f"Přiloženo: {attachment.kind} · {attachment.name}")
            self._show_attachment(attachment)
        self.prompt.clear()
        self._stream_text = ""
        self.stream.clear()
        self._set_running(True)
        self._started_at = time.monotonic()
        self._clock.start()
        thread = _TurnThread(self._session, text, attachments, self._note, self)
        self._note = ""
        thread.agent_event.connect(self._agent_event)
        thread.result.connect(self._turn_finished)
        thread.failed.connect(self._turn_failed)
        thread.finished.connect(self._thread_done)
        self._thread = thread
        thread.start()

    def _running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _set_running(self, running):
        # The worker owns the sandbox while it runs: no apply/discard/preview meanwhile.
        self.result_bar.setEnabled(not running)
        self.model.setEnabled(not running)
        self.connection.setEnabled(not running)
        self.send_button.setEnabled(not running)
        self.stop_button.setVisible(running)
        self.prompt.setEnabled(not running)
        self.attach_button.setEnabled(not running)
        self.models_button.setEnabled(not running)
        self.new_button.setEnabled(not running)
        if not running:
            self._clock.stop()

    def _update_elapsed(self):
        elapsed = int(time.monotonic() - self._started_at)
        message = self.status.text().split(" · ")[0] or "AI pracuje…"
        self.status.setText(f"{message} · {elapsed} s")

    def _on_agent_event(self, kind, payload):
        if kind == "status":
            self.status.setText(str(payload))
        elif kind in {"content", "reasoning"}:
            self._stream_text = (self._stream_text + str(payload))[-1200:]
            self.stream.setText("AI píše: " + self._stream_text)
        elif kind == "note":
            self.stream.clear()
            self._bubble("AI · průběžná poznámka", str(payload), "#f1f5f4")
        elif kind == "tool":
            icon = "✓" if payload.get("ok") else "⚠"
            line = f"{icon} {payload.get('title', payload.get('name', 'Nástroj'))}"
            summary = payload.get("summary", "")
            # The finish summary follows as the assistant's message; do not repeat it.
            if summary and payload.get("name") != "finish":
                line += f" · {summary}"
            self._system_line(line, error=not payload.get("ok"))
        elif kind == "image":
            self._show_render(payload)
        elif kind == "message":
            self.stream.clear()
            self._bubble("AI", str(payload), "#f1f5f4")
        elif kind == "done":
            self.status.setText("")

    def _preview_changed(self):
        """A user edit (e.g. Undo) cleared the staged AI result: it can no longer be applied."""
        if self._own_preview_change or not self._preview_valid or self.state.preview_state() is not None:
            return
        self._preview_valid = False
        self._set_result_visible(False)
        self._system_line("Návrh AI zanikl, protože se pracovní prostor změnil. Další zpráva naváže na "
                          "současný stav.")
        self.preview_closed.emit()

    def _undo_label(self, prefix="AI"):
        title = " ".join(self._title.split())
        return f"{prefix}: {title[:70]}{'…' if len(title) > 70 else ''}" if title else f"{prefix}: úpravy"

    def _stage(self, label) -> bool:
        """Show the sandbox result for review; False if it can no longer be applied."""
        try:
            self._own_preview_change = True
            self.state.preview_snapshot(self._session.snapshot(), self._session.base_signature,
                                        label, source="ai")
        except ValueError as exc:
            self.state.clear_preview()
            self._preview_valid = False
            self._system_line(str(exc), error=True)
            self.preview_closed.emit()
            return False
        finally:
            self._own_preview_change = False
        self._preview_valid = True
        self.preview_ready.emit()
        return True

    def _turn_finished(self, _result):
        self._set_running(False)
        if self._session.has_changes():
            self._stage(self._undo_label())
            self._set_result_visible(True)
        else:
            self._set_result_visible(False)

    def _turn_failed(self, message):
        self._set_running(False)
        self._system_line(message, error=True)
        if self._session.has_changes() and self._stage(self._undo_label("AI (částečně)")):
            self._set_result_visible(True)

    def _thread_done(self):
        self._set_running(False)
        self._thread = None

    def _set_result_visible(self, visible):
        self.result_bar.setVisible(visible)
        self.apply_button.setEnabled(visible and self._preview_valid)
        self.preview_button.setEnabled(visible and self._preview_valid)
        self.publication_button.setEnabled(visible and self._preview_valid)

    def _cancel(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            if self._active_client is not None:
                self._active_client.cancel()
            self.status.setText("Zastavuji…")

    def _apply(self):
        if not self._preview_valid or self._running():
            return
        try:
            self._own_preview_change = True
            self.state.apply_preview()
            self._sync_session()
            self._preview_valid = False
            self._set_result_visible(False)
            self._system_line("Změny použity (Zpět je vrátí)")
        except ValueError as exc:
            self._preview_valid = False
            self.apply_button.setEnabled(False)
            self._system_line(str(exc), error=True)
        finally:
            self._own_preview_change = False
        self.preview_closed.emit()

    def _discard(self):
        if self._running():
            return
        self._own_preview_change = True
        self.state.clear_preview()
        self._own_preview_change = False
        self._sync_session()
        self._preview_valid = False
        self._note = "The user discarded your previous changes; continue from the current workspace."
        self._set_result_visible(False)
        self._system_line("Návrh zahozen; pokračuji z aktuálního pracovního prostoru.")
        self.preview_closed.emit()

    def _new_conversation(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self.state.clear_preview()
        self._preview_valid = False
        self.chat.clear()
        self._pending.clear()
        self._refresh_chips()
        self._note = ""
        self._title = ""
        self._new_session()
        self._bubble("AI", "Nová konverzace. S čím mám pomoci?", "#f1f5f4")
        self._set_result_visible(False)
        self.preview_closed.emit()

    def _view_preview(self):
        preview_state = self.state.preview_state()
        if preview_state is None:
            return
        from ui.plot_widget import SpectrumPlotWidget

        dialog = QDialog(self)
        dialog.setWindowTitle("Náhled změn AI")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(SpectrumPlotWidget(preview_state))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _view_publication(self):
        if not self._preview_valid or self._running():
            return
        try:
            png, report = self._session.toolbox.figure_report()
        except (AIError, ValueError) as exc:
            self._system_line(str(exc), error=True)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Publikační obrázek")
        dialog.resize(900, 700)
        layout = QVBoxLayout(dialog)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setPixmap(QPixmap.fromImage(QImage.fromData(png)).scaled(
            840, 560, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        layout.addWidget(image, 1)
        details = QLabel(json.dumps(report, ensure_ascii=False, indent=2))
        details.setWordWrap(True)
        details.setObjectName("muted")
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _show_data(self):
        try:
            temporary = AgentSession(
                None,
                self.model.currentText().strip() or PREFERRED_MODEL,
                include_names=self.send_names.isChecked(),
                vision=supports_vision(self.model.currentText()),
            )
            temporary.sync(
                self.state._snapshot(),
                self.state._workflow_signature(),
                selected_ids=self._selected_ids(),
            )
            content = json.dumps(temporary.toolbox.workspace(), ensure_ascii=False, indent=2)
        except (AIError, ValueError) as exc:
            self._system_line(str(exc), error=True)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Odesílaná data")
        dialog.resize(700, 550)
        layout = QVBoxLayout(dialog)
        display = QPlainTextEdit()
        display.setReadOnly(True)
        display.setPlainText(content)
        layout.addWidget(display, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _load_models(self):
        if self._models_thread is not None and self._models_thread.isRunning():
            return
        try:
            client = self._make_client()
        except AIError as exc:
            self._system_line(str(exc), error=True)
            return
        thread = _ModelsThread(client, self)
        thread.result.connect(self._models_loaded)
        thread.failed.connect(lambda message: self._system_line(message, error=True))
        thread.finished.connect(lambda: setattr(self, "_models_thread", None))
        self._models_thread = thread
        self.models_button.setEnabled(False)
        thread.finished.connect(lambda: self.models_button.setEnabled(True))
        thread.start()

    def _models_loaded(self, models):
        current = self.model.currentText()
        for model in chat_models(models):
            if self.model.findText(model) < 0:
                self.model.addItem(model)
        if current:
            self.model.setCurrentText(current)

    def _choose_files(self):
        file_filter = (
            "Všechny podporované soubory (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp "
            "*.pdf *.json *.txt *.csv *.tsv *.dat *.dpt *.asc *.xy *.spc *.spa *.spg *.wdf *.jdx *.dx);;"
            "Obrázky a PDF (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp *.pdf);;"
            "Projekty, presety a spektra (*.json *.txt *.csv *.tsv *.dat *.dpt *.asc *.xy *.spc *.spa "
            "*.spg *.wdf *.jdx *.dx);;"
            "Všechny soubory (*)"
        )
        paths, _ = QFileDialog.getOpenFileNames(self, "Přiložit vzor", "", file_filter)
        self._load_files(paths)

    def _load_files(self, paths):
        for path in paths:
            try:
                loaded = load_attachment(path, self._session.next_attachment_id())
            except ValueError as exc:
                self._system_line(str(exc), error=True)
                continue
            except OSError:
                self._system_line("Soubor se nepodařilo načíst.", error=True)
                continue
            self._pending.extend(loaded)
        self._refresh_chips()

    def _refresh_chips(self):
        while self.attachment_layout.count():
            item = self.attachment_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for index, attachment in enumerate(self._pending):
            chip = QWidget()
            row = QHBoxLayout(chip)
            row.setContentsMargins(5, 2, 3, 2)
            row.setSpacing(2)
            label = QLabel(f"{attachment.kind}: {attachment.name}")
            label.setToolTip(attachment.name)
            label.setMaximumWidth(230)
            row.addWidget(label)
            remove = QPushButton("×")
            remove.setFixedWidth(25)
            remove.clicked.connect(lambda _checked=False, i=index: self._remove_attachment(i))
            row.addWidget(remove)
            chip.setStyleSheet("QWidget { background:#edf3f2; border-radius:5px; }")
            self.attachment_layout.addWidget(chip)
        self.attachment_layout.addStretch(1)
        self.attachment_row.setVisible(bool(self._pending))

    def _remove_attachment(self, index):
        if 0 <= index < len(self._pending):
            del self._pending[index]
            self._refresh_chips()

    def _paste_image(self, data):
        try:
            attachment = image_attachment(
                data, "vložený obrázek.png", self._session.next_attachment_id()
            )
            self._pending.append(attachment)
            self._refresh_chips()
        except ValueError as exc:
            self._system_line(str(exc), error=True)

    def _clipboard_image(self):
        from PySide6.QtWidgets import QApplication

        image = QApplication.clipboard().image()
        if image.isNull():
            return None
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice

        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(array)

    def _add_image(self, key, image) -> None:
        """Keep at most 40 images in the chat; older ones are replaced by a stub."""
        if image.width() > 1100:
            image = image.scaledToWidth(1100, Qt.TransformationMode.SmoothTransformation)
        document = self.chat.document()
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), image)
        self._images.append(key)
        while len(self._images) > 40:
            old = self._images.pop(0)
            stub = QImage(1, 1, QImage.Format.Format_RGB32)
            stub.fill(Qt.GlobalColor.white)
            document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(old), stub)

    def _show_attachment(self, attachment):
        if not attachment.image:
            return
        key = f"attachment:{attachment.id}"
        image = QImage.fromData(attachment.image)
        if image.isNull():
            return
        self._add_image(key, image)
        self._append_html(
            f'<div style="margin:2px 4px 8px 14px;"><a href="{key}">'
            f'<img src="{key}" width="300"></a></div>'
        )

    def _show_render(self, data):
        key = f"render:{time.monotonic_ns()}"
        image = QImage.fromData(data)
        if image.isNull():
            return
        self._add_image(key, image)
        self._append_html(
            f'<div style="margin:5px 3px;"><a href="{key}">'
            f'<img src="{key}" width="300"></a></div>'
        )

    def _open_image(self, url):
        image = self.chat.document().resource(
            QTextDocument.ResourceType.ImageResource, url
        )
        if not isinstance(image, QImage):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Náhled obrázku")
        dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(QPixmap.fromImage(image).scaled(
            960, 680, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        layout.addWidget(label, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self._load_files(paths)
        event.acceptProposedAction()

    def shutdown(self, wait_ms: int = 3000) -> bool:
        if self._thread is not None and self._thread.isRunning():
            self._cancel()
            if not self._thread.wait(wait_ms):
                return False
        if self._models_thread is not None and self._models_thread.isRunning():
            if not self._models_thread.wait(wait_ms):
                return False
        return True

    def quit_when_idle(self) -> None:
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.finished.connect(self._close_window_after_idle)

    def _close_window_after_idle(self):
        self.window().close()
