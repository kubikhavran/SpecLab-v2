"""Offscreen coverage for the chat assistant's sandbox/apply workflow."""

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.models import Spectrum
from app.state import AppState
from ui.ai_panel import AIPanel


class FakeClient:
    def __init__(self):
        self.replies = [
            {
                "content": "",
                "reasoning": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "set_spectra",
                        "arguments": json.dumps(
                            {"changes": [{"spectrum": "S1", "color": "#ff0000"}]}
                        ),
                    }
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "Hotovo",
                "tool_calls": [],
                "finish_reason": "stop",
                "reasoning": "",
            },
        ]
        self.messages = []
        self.cancelled = False

    def chat(self, model, messages, tools=None, cancel=None, on_delta=None, max_tokens=None):
        self.messages.append(messages)
        return self.replies.pop(0)

    def cancel(self):
        self.cancelled = True

    def list_models(self):
        return ["kimi-k3"]


def make_state():
    state = AppState()
    state.add_spectra(
        [
            (
                Spectrum(
                    name="sample 532 nm",
                    x=[float(i) for i in range(20)],
                    y=[float(i * i) for i in range(20)],
                ),
                [],
            )
        ]
    )
    return state


def wait_for_turn(app, panel):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        app.processEvents()
        if panel._thread is None:
            return
        time.sleep(0.01)
    raise AssertionError("AI worker did not finish")


def make_panel(state, fake):
    panel = AIPanel(state)
    panel._make_client = lambda: fake
    panel._session.client = fake
    panel.get_ids = lambda: [state.active_spectrum_id]
    return panel


def test_chat_turn_stages_and_apply_is_one_undo_step():
    app = QApplication.instance() or QApplication([])
    state = make_state()
    fake = FakeClient()
    panel = make_panel(state, fake)
    before = state.spectra[0].meta.get("trace_style")
    history_size = len(state._undo_stack)

    panel.prompt.setPlainText("Změň barvu spektra.")
    panel._send()
    wait_for_turn(app, panel)

    assert "Barvy a názvy spekter" in panel.chat.toPlainText()
    assert "Hotovo" in panel.chat.toPlainText()
    assert not panel.result_bar.isHidden()
    assert state.spectra[0].meta.get("trace_style") == before
    assert panel.apply_button.isEnabled()
    panel._apply()

    assert state.spectra[0].meta["trace_style"]["color"] == "#ff0000"
    assert len(state._undo_stack) == history_size + 1
    assert "Změny použity" in panel.chat.toPlainText()
    state.undo()
    assert state.spectra[0].meta.get("trace_style") == before
    panel.close()


def test_discard_keeps_workspace_unchanged():
    app = QApplication.instance() or QApplication([])
    state = make_state()
    fake = FakeClient()
    panel = make_panel(state, fake)
    before = state._snapshot()
    panel.prompt.setPlainText("Změň barvu.")
    panel._send()
    wait_for_turn(app, panel)
    panel._discard()
    assert state._snapshot() == before
    assert not panel.result_bar.isVisible()
    panel.close()


def test_pasted_image_is_attached_to_next_turn():
    app = QApplication.instance() or QApplication([])
    state = make_state()
    fake = FakeClient()
    panel = make_panel(state, fake)
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (12, 8), "white").save(output, format="PNG")
    panel._paste_image(output.getvalue())
    assert len(panel._pending) == 1
    assert not panel.attachment_row.isHidden()

    panel.prompt.setPlainText("Použij tento obrázek jako vzor.")
    panel._send()
    wait_for_turn(app, panel)
    sent_messages = json.dumps(fake.messages, ensure_ascii=False)
    assert "image_url" in sent_messages
    assert "vložený obrázek.png" in sent_messages
    panel._discard()
    panel.close()


def test_undo_after_staging_invalidates_the_proposal():
    app = QApplication.instance() or QApplication([])
    state = make_state()
    state.rename_spectra({state.spectra[0].id: "renamed"})       # something to undo
    fake = FakeClient()
    panel = make_panel(state, fake)
    panel.prompt.setPlainText("Změň barvu spektra.")
    panel._send()
    wait_for_turn(app, panel)
    assert panel.apply_button.isEnabled()
    state.undo()
    app.processEvents()
    assert panel.result_bar.isHidden() and not panel._preview_valid
    assert "zanikl" in panel.chat.toPlainText()
    panel.close()
