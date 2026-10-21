"""AI agent: tools on a sandboxed workspace, the tool-calling loop and its transport.

No network: the model is a scripted fake client.
"""

import io
import json
from unittest.mock import patch

import numpy as np
import pytest

from app.models import Spectrum
from app.state import AppState
from core.ai_agent import AgentSession
from core.ai_client import AIError, EInfraClient, VisionUnsupported
from core.ai_tools import Toolbox, parse_arguments
from core.colors import parse_color, wavelength_color


def _raman(name, laser_cm1, bands, scale=1.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    x = np.linspace(100, 3200, 3101)
    y = 200 + 4000 * np.exp(-((x - 100) / 25) ** 2)            # Rayleigh/notch edge
    for centre, height in bands:
        y += height * np.exp(-0.5 * ((x - centre) / 8) ** 2)
    y = scale * (y + noise * rng.normal(size=len(x)))
    return Spectrum(name=name, x=x.tolist(), y=y.tolist(),
                    meta={"technique": "raman", "x_unit": "cm-1", "y_kind": "intensity",
                          "sourceName": name + ".wdf", "laser_wavenumber_cm1": laser_cm1})


@pytest.fixture
def state():
    state = AppState()
    state.add_spectra([
        (_raman("ABT_Au_785_1200_m1", 12738.0, [(403, 900), (1078, 3000), (1182, 700), (1590, 2800)]), []),
        (_raman("ABT_Au_785_1200_m2", 12738.0, [(403, 800), (1078, 2600), (1182, 600), (1590, 3000)], seed=1), []),
        (_raman("Au_ABT_633_1800_m1", 15803.0, [(405, 90), (1079, 250), (1180, 80), (1590, 400)], 0.1, seed=2), []),
    ])
    state.set_active_spectrum(state.spectra[0].id)
    return state


def toolbox(state):
    return Toolbox(state, {f"S{i + 1}": s.id for i, s in enumerate(state.spectra)})


def run(box, name, **arguments):
    result = box.run(name, json.dumps(arguments))
    return result, json.loads(result.text)


def test_references_accept_aliases_names_files_and_numbers(state):
    box = toolbox(state)
    a, b, c = (s.id for s in state.spectra)
    assert box.ids(["S1", 2, "Au_ABT_633_1800_m1.wdf"]) == [a, b, c]
    assert box.ids(["all"]) == [a, b, c]
    assert box.ids(["633"]) == [c]                       # unique substring of a file name
    result, payload = run(box, "set_spectra", changes=[{"spectrum": "785", "color": "red"}])
    assert not result.ok and "several" in payload["error"]


def test_workspace_reports_laser_bands_and_figure(state):
    summary = toolbox(state).workspace()
    first = summary["spectra"][0]
    assert first["ref"] == "S1" and first["file"].endswith(".wdf")
    assert first["laser_nm"] == pytest.approx(785.1, abs=0.1)
    assert any(abs(b["x"] - 1078) < 3 for b in first["strongest_bands"])
    assert summary["figure"]["layout"] == "single"
    box = toolbox(state)
    box.hide_names = True
    hidden = box.workspace()["spectra"][0]
    assert "file" not in hidden and hidden["name"] == "S1"


def test_process_normalises_parameters_and_clamps_crop(state):
    box = toolbox(state)
    result, payload = run(box, "process", operations=[
        {"op": "savgol", "params": {"window_length": 10, "polyorder": 3}},
        {"op": "crop", "params": {"x_min": 50, "x_max": 1800}}])
    assert result.ok and result.mutated
    assert payload["applied"][0] == {"op": "smooth", "params": {"window": 11, "poly_order": 3}}
    assert any("odd" in w for w in payload["warnings"]) and any("clamped" in w for w in payload["warnings"])
    assert all(max(s.x) <= 1800 for s in state.spectra)
    result, payload = run(box, "process", operations=[{"op": "crop", "params": {"min": 5000, "max": 6000}}])
    assert not result.ok and "outside" in payload["error"]
    result, payload = run(box, "process", operations=[{"op": "detect_peaks"}])
    assert not result.ok and "detect_peaks" in payload["error"]


def test_failed_tool_leaves_the_sandbox_unchanged(state):
    box = toolbox(state)
    before = state._workflow_signature()
    result, _ = run(box, "set_spectra", changes=[{"spectrum": "S1", "color": "#123456"},
                                                 {"spectrum": "S9", "color": "#654321"}])
    assert not result.ok and state._workflow_signature() == before


def test_peaks_are_labelled_on_every_spectrum_relative_to_its_own_height(state):
    box = toolbox(state)
    result, payload = run(box, "detect_peaks", spectra=["all"], top_n=3)
    assert result.ok
    for item in payload["spectra"]:
        assert item["found"] == 3                       # weak 633 nm spectrum too
        assert all(x > 160 for x in item["peaks"])      # notch-filter edge is no band
    assert state.peaks_settings.enabled and state.peaks_settings.mode == "all"
    weak = sorted(p.x for p in state.peaks_auto[state.spectra[2].id])
    assert weak == pytest.approx([405, 1079, 1590], abs=3)        # the three strongest bands


def test_stacking_adapts_offset_when_processing_rescales(state):
    box = toolbox(state)
    result, payload = run(box, "arrange_spectra", layout="stacked", bottom_to_top=["S3", "S1", "S2"])
    assert result.ok and payload["plotted_bottom_to_top"] == ["S3", "S1", "S2"]
    assert state.plot.stack_offset > 100
    result, payload = run(box, "process", operations=[{"op": "normalize", "params": {"method": "max"}}])
    assert result.ok and 0 < state.plot.stack_offset < 2
    assert any("Stack offset adapted" in w for w in payload["warnings"])
    assert "detect_peaks" in (payload["note"] or "")


def test_style_and_axes_use_points_and_explain_bad_ranges(state):
    box = toolbox(state)
    result, payload = run(box, "set_style", font_family="Helvetica", axis_title_pt=11, tick_label_pt=9,
                          curve_line_width_pt=1.2, axis_line_width_pt=0.8, frame="open")
    assert result.ok
    assert state.graphics.base_font_size == 33 and state.graphics.tick_font_size == 27
    assert state.graphics.trace_line_width == 3 and state.graphics.axis_line_width == 2
    result, payload = run(box, "set_axes", x_min=1800, x_max=200, x_label="Raman shift (cm^{-1})")
    assert result.ok and (state.plot.x_min, state.plot.x_max) == (200, 1800)
    assert any("swapped" in w for w in payload["warnings"])
    result, payload = run(box, "set_axes", x_min=5000, x_max=6000)
    assert not result.ok and "no data" in payload["error"]


def test_spectrum_styles_names_and_undo(state):
    box = toolbox(state)
    run(box, "set_spectra", changes=[{"spectrum": "S1", "color": "darkred", "line_width_pt": 1.0,
                                      "line_style": "dashed", "name": "785 nm · m1"}])
    spec = state.spectra[0]
    assert spec.meta["trace_style"] == {"color": "#8b0000", "width": 2.5, "line": "dash"}
    assert spec.name == "785 nm · m1"
    result, _ = run(box, "undo_last_change")
    assert result.ok and "trace_style" not in state.spectra[0].meta


def test_render_reports_curves_labels_and_problems(state):
    box = toolbox(state)
    run(box, "arrange_spectra", layout="stacked")
    run(box, "detect_peaks", top_n=4)
    result, payload = run(box, "render_figure")
    assert result.ok and result.image[:8] == b"\x89PNG\r\n\x1a\n"
    assert [c["spectrum"] for c in payload["curves"]] == ["S1", "S2", "S3"]
    assert all(c["labels_shown"] == 4 for c in payload["curves"])
    assert any("tiny" in issue for issue in payload["issues"])        # 633 nm spectrum is 10× weaker
    assert any("long" in issue for issue in payload["issues"]) is False


def test_suggested_laser_colours_are_print_safe():
    assert wavelength_color(785) == "#8c0a1a"
    for nm in (488, 532, 561):
        r, g, b = (int(wavelength_color(nm)[i:i + 2], 16) / 255 for i in (1, 3, 5))
        assert 0.2126 * r ** 2.2 + 0.7152 * g ** 2.2 + 0.0722 * b ** 2.2 < 0.25
    assert parse_color("ABC123") == "#abc123" and parse_color("Dark Red") == "#8b0000"


def test_lenient_arguments():
    assert parse_arguments('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_arguments("{'a': True}") == {"a": True}
    assert parse_arguments("") == {}


class FakeClient:
    """Scripted model: returns queued replies and records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def chat(self, model, messages, tools=None, cancel=None, on_delta=None, max_tokens=None):
        self.sent.append(json.loads(json.dumps(messages)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"content": "", "reasoning": "", "tool_calls": [], "finish_reason": "stop", **reply}

    def cancel(self):
        pass


def call(name, call_id="c1", **arguments):
    return {"id": call_id, "name": name, "arguments": json.dumps(arguments)}


def session_for(state, replies, **kwargs):
    client = FakeClient(replies)
    session = AgentSession(client, "kimi-k3", **kwargs)
    session.sync(state._snapshot(), state._workflow_signature())
    return session, client


def test_agent_loop_runs_tools_in_the_sandbox_and_checks_the_result(state):
    events = []
    session, client = session_for(state, [
        {"tool_calls": [call("set_spectra", changes=[{"spectrum": "S1", "color": "#8c0a1a"}])]},
        {"tool_calls": [call("finish", "c2", summary="Obarveno.")]},
        {"tool_calls": [call("finish", "c3", summary="Obarveno podle laseru.")]},
    ], on_event=lambda kind, payload: events.append(kind))
    result = session.run_turn("obarvi podle laseru")
    assert result.finished and result.text == "Obarveno podle laseru."
    assert "trace_style" not in state.spectra[0].meta            # real workspace untouched
    assert session.has_changes()
    first = client.sent[0]
    assert first[0]["role"] == "system" and "Workspace" in first[1]["content"]
    # The automatic final check showed the figure before accepting finish.
    check = client.sent[2][-1]
    assert check["role"] == "user" and any(part.get("type") == "image_url" for part in check["content"])
    assert {"tool", "staged", "image", "message"} <= set(events)
    tool_messages = [m for m in client.sent[1] if m["role"] == "tool"]
    assert tool_messages[0]["tool_call_id"] == "c1" and '"ok": true' in tool_messages[0]["content"]


def test_agent_result_is_applied_as_one_undo_step(state):
    session, _ = session_for(state, [
        {"tool_calls": [call("set_spectra", changes=[{"spectrum": "S2", "color": "#123456"}]),
                        call("arrange_spectra", "c2", layout="stacked")]},
        {"tool_calls": [call("render_figure", "c3")]},
        {"tool_calls": [call("finish", "c4", summary="Hotovo")]},
    ])
    session.run_turn("…")
    history = len(state.history)
    state.preview_snapshot(session.snapshot(), session.base_signature, "AI: test")
    state.apply_preview()
    assert state.spectra[1].meta["trace_style"]["color"] == "#123456" and state.plot.show_all_spectra
    assert len(state.history) == history + 1
    state.undo()
    assert "trace_style" not in state.spectra[1].meta and not state.plot.show_all_spectra


def test_stale_agent_result_is_refused(state):
    session, _ = session_for(state, [{"tool_calls": [call("set_style", grid=True)]},
                                     {"content": "Hotovo"}])
    session.run_turn("…")
    state.rename_spectra({state.spectra[0].id: "renamed by the user"})
    with pytest.raises(ValueError):
        state.preview_snapshot(session.snapshot(), session.base_signature, "AI")


def test_errors_go_back_to_the_model_and_text_only_models_get_no_images(state):
    session, client = session_for(state, [
        {"tool_calls": [call("set_axes", x_min=9000, x_max=9500)]},
        {"tool_calls": [call("render_figure", "c2")]},
        {"content": "Rozsah je mimo data; nic jsem neměnil."},
    ], vision=False)
    result = session.run_turn("osa 9000–9500")
    assert not result.finished and "mimo" in result.text
    error = [m for m in client.sent[1] if m["role"] == "tool"][0]["content"]
    assert '"ok": false' in error and "no data" in error
    assert not any(part.get("type") == "image_url" for message in client.sent[-1]
                   if isinstance(message.get("content"), list) for part in message["content"])


def test_model_without_vision_is_detected_and_retried_without_images(state):
    session, client = session_for(state, [VisionUnsupported("no"), {"content": "OK"}])
    session.run_turn("ahoj")
    assert session.vision is False and len(client.sent) == 2


def _sse(*events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode() + b"data: [DONE]\n\n"


class _Response(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


def test_streamed_tool_call_deltas_are_assembled():
    wire = _sse(
        {"choices": [{"delta": {"reasoning_content": "plan "}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "fc_1", "function": {"name": "set_",
                                                                                       "arguments": '{"a"'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "style", "arguments": ': 1}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )
    client = EInfraClient("fake_key")
    with patch.object(client, "_open_chat", return_value=_Response(wire)):
        result = client.chat("m", [{"role": "user", "content": "x"}], [])
    assert result["tool_calls"] == [{"id": "fc_1", "name": "set_style", "arguments": '{"a": 1}'}]
    assert result["reasoning"] == "plan " and result["finish_reason"] == "tool_calls"


def test_tool_calls_written_as_text_are_recovered():
    wire = _sse({"choices": [{"delta": {"content": 'Ok <tool_call>{"name": "finish", "arguments": '
                                                   '{"summary": "x"}}</tool_call>'}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]})
    client = EInfraClient("fake_key")
    with patch.object(client, "_open_chat", return_value=_Response(wire)):
        result = client.chat("m", [], [])
    assert result["tool_calls"][0]["name"] == "finish" and result["content"] == "Ok"


def test_rate_limit_is_retried_and_vision_refusal_is_typed():
    import urllib.error

    attempts = []

    class Opener:
        def __init__(self, code, body=b""):
            self.code, self.body = code, body

        def open(self, request, timeout):
            attempts.append(self.code)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(request.full_url, self.code, "x", {}, io.BytesIO(self.body))
            return _Response(_sse({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}))

    client = EInfraClient("fake_key")
    with patch("urllib.request.build_opener", return_value=Opener(429)), patch("time.sleep"):
        assert client.chat("m", [])["content"] == "hi"
    assert attempts == [429, 429]
    attempts.clear()
    body = b'{"error": {"message": "glm-5.3 is not a multimodal model"}}'
    with patch("urllib.request.build_opener", return_value=Opener(400, body)):
        with pytest.raises(VisionUnsupported):
            client.chat("glm-5.3", [])
    attempts.clear()
    with patch("urllib.request.build_opener", return_value=Opener(401)):
        with pytest.raises(AIError, match="klíč"):
            client.chat("m", [])


def test_series_spikes_are_removed_and_shifting_data_to_stack_is_refused():
    state = AppState()                              # one coherent series (e.g. potentials)
    state.add_spectra([(_raman(f"EC_{v}mV", 12738.0, [(403, 900), (1078, 3000)], seed=i), [])
                       for i, v in enumerate((-600, -400, -200))])
    box = toolbox(state)
    spiky = np.asarray(state.spectra[1].y, dtype=float)
    spiky[1500:1502] += 50000                       # cosmic hit in one spectrum only
    state.spectra[1].y = spiky.tolist()
    result, payload = run(box, "remove_series_spikes", spectra=["all"])
    assert result.ok and payload["spikes_removed"].get("S2", 0) >= 1
    assert max(state.displayed_y(state.spectra[1].id)) < 20000
    result, payload = run(box, "process", spectra=["S2"], operations=[{"op": "shift", "params": {"y": 500}}])
    assert not result.ok and "arrange_spectra" in payload["error"]


def test_curve_names_inside_the_plot(state):
    box = toolbox(state)
    run(box, "arrange_spectra", layout="stacked")
    result, _ = run(box, "set_style", curve_names="inside")
    assert result.ok and state.graphics.spectrum_label_position == "inside"
    assert box.workspace()["figure"]["curve_names"] == "inside"
    result, payload = run(box, "render_figure")
    assert result.ok


def test_attachments_images_projects_and_bad_files(tmp_path):
    from PIL import Image

    from core.ai_attachments import load_attachment
    from core.project_io import save_project

    image = tmp_path / "ref.png"
    Image.new("RGBA", (2400, 1200), (255, 0, 0, 128)).save(image)
    item, = load_attachment(image, "A1")
    with Image.open(io.BytesIO(item.image)) as decoded:
        assert item.kind == "image" and max(decoded.size) == 1600 and decoded.mode == "RGB"
    state = AppState()
    state.add_spectra([(_raman("ref", 12738.0, [(1000, 500)]), [])])
    state.set_spectral_mode("raman")
    project = tmp_path / "vzor.speclab.json"
    save_project(state, project)
    reference, = load_attachment(project, "A2")
    assert reference.kind == "project" and reference.image[:4] == b"\x89PNG"
    broken = tmp_path / "broken.spa"
    broken.write_bytes(b"not a spectrum")
    with pytest.raises(ValueError):
        load_attachment(broken, "A3")


def test_review_regressions_privacy_hidden_spectra_and_lenient_flags(state):
    box = toolbox(state)
    box.hide_names = True
    _, details = run(box, "get_spectrum_details", spectrum="S1")
    assert details["name"] == "S1"
    _, error = run(box, "set_spectra", changes=[{"spectrum": "nonexistent", "color": "red"}])
    assert "ABT" not in error["error"]
    run(box, "detect_peaks", top_n=3)
    result, _ = run(box, "remove_peaks", all="false", x_values=[1078])
    assert result.ok and len(state.peaks_auto[state.spectra[0].id]) == 2   # only the 1078 label went
    run(box, "arrange_spectra", layout="overlay")
    run(box, "set_spectra", changes=[{"spectrum": s, "visible": False} for s in ("S1", "S2", "S3")])
    result, payload = run(box, "render_figure")
    assert not result.ok and "hidden" in payload["error"]


def test_peak_indices_follow_a_descending_axis():
    state = AppState()
    spec = _raman("ir", 0.0, [(1000, 900)])
    spec.x, spec.y = spec.x[::-1], spec.y[::-1]              # descending like many IR files
    state.add_spectra([(spec, [])])
    box = toolbox(state)
    run(box, "detect_peaks", top_n=1)
    peak = state.peaks_auto[state.spectra[0].id][0]
    assert abs(state.spectra[0].x[peak.i] - peak.x) < 1e-9
