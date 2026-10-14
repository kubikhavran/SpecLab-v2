"""Protocol and transport tests use deterministic fake responses; no API key needed."""

import io
import json
from unittest.mock import patch
import numpy as np
import pytest
from app.models import Spectrum
from core.ai_client import AIError, EInfraClient, parse_plan, spectrum_context
from core.analysis import integrate_band


def plan(operations=None):
    return {
        "explanation": "Jemné vyhlazení",
        "warnings": [],
        "operations": operations
        if operations is not None
        else [{"op": "smooth", "params": {"window": 11, "poly_order": 3}}],
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"op": "exec", "params": {"code": "print('x')"}},
        {"op": "smooth", "params": {"window": True}},
        {"op": "normalize", "params": {"method": "made_up"}},
        {"op": "shift", "params": {"y": float("nan")}},
        {"op": "smooth", "params": {"window": 10}},
        {"op": "smooth", "params": {"window": 11, "new_y": [1, 2]}},
    ],
)
def test_reject_untrusted_operations(bad):
    with pytest.raises(ValueError):
        parse_plan(json.dumps(plan([bad])))


def test_strict_envelope_and_empty_information_response():
    assert parse_plan(json.dumps(plan([])))["operations"] == []
    bad = plan()
    bad["new_data"] = [1, 2]
    with pytest.raises(AIError):
        parse_plan(json.dumps(bad))
    with pytest.raises(AIError):
        parse_plan("No plan here, only {braces} and prose.")
    with pytest.raises(AIError):
        parse_plan(json.dumps(plan()) + " or alternatively " + json.dumps(plan([])))


@pytest.mark.parametrize(
    "wrap",
    [
        lambda text: "Here is the plan:\n" + text + "\nCheck the preview.",
        lambda text: "<think>The user wants {smoothing}; maybe window 11.</think>\n" + text,
        lambda text: "Plán:\n```json\n" + text + "\n```",
    ],
)
def test_reasoning_and_prose_around_single_plan(wrap):
    assert parse_plan(wrap(json.dumps(plan()))) == plan()


def test_tls_context_has_certificate_authorities():
    from core.ai_client import _ssl_context

    context = _ssl_context()
    assert context.verify_mode.name == "CERT_REQUIRED"
    assert context.cert_store_stats()["x509_ca"] > 0


def test_cancel_before_stream_aborts_without_plan():
    content = json.dumps(plan())
    wire = (
        "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n"
        "data: [DONE]\n\n"
    ).encode()
    client = EInfraClient("fake_key")

    def request(*_args):
        client.cancel()
        return Response(wire)

    with patch.object(client, "_request", side_effect=request):
        with pytest.raises(AIError, match="zrušen"):
            client.propose("test", "smooth", {})


def test_context_retains_spike_omits_paths():
    x = np.arange(10000, dtype=float)
    y = np.zeros(10000)
    y[4321] = 100
    spec = Spectrum(
        name="secret sample",
        x=x.tolist(),
        y=y.tolist(),
        meta={
            "sourcePath": "/secret/path",
            "technique": "raman",
            "y_kind": "intensity",
        },
    )
    context = spectrum_context(spec, y)
    assert len(context["preview_xy"]) <= 258
    assert [4321.0, 100.0] in context["preview_xy"]
    assert "secret" not in json.dumps(context)
    assert "preview_xy" not in spectrum_context(spec, y, False)


class Response(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


def test_stream_json_chunks_and_complete_marker():
    content = json.dumps(plan())
    chunks = [content[:30], content[30:]]
    wire = b"".join(
        (
            "data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n\n"
        ).encode()
        for chunk in chunks
    )
    wire += (
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    )
    client = EInfraClient("fake_key")
    with patch.object(client, "_request", return_value=Response(wire)):
        assert client.propose("test-model", "smooth", {}) == plan()


def test_truncated_stream_rejected():
    wire = (
        "data: "
        + json.dumps({"choices": [{"delta": {"content": json.dumps(plan())}}]})
        + "\n\n"
    ).encode()
    client = EInfraClient("fake_key")
    with patch.object(client, "_request", return_value=Response(wire)):
        with pytest.raises(AIError, match="nedokončil"):
            client.propose("test", "smooth", {})


def test_no_credential_url_or_plaintext_endpoint():
    for url in [
        "http://example.test/v1",
        "https://key@example.test/v1",
        "https://example.test/v1?key=test",
    ]:
        with pytest.raises(AIError):
            EInfraClient("secret", url)


def test_integrate_exact_interpolated_edges():
    assert integrate_band([0, 1, 3], [0, 2, 6], 0.5, 2.5) == pytest.approx(6.0)
    with pytest.raises(ValueError):
        integrate_band([0, 1, 3], [0, 2, 6], -0.5, 2.5)


def test_cancelled_model_listing_reports_cancellation():
    client = EInfraClient("fake_key")

    class Stalled(io.BytesIO):
        def read(self, *_args):
            client.cancel()
            raise OSError("socket shut down")

    with patch.object(client, "_request", return_value=Stalled(b"")):
        with pytest.raises(AIError, match="zrušen"):
            client.list_models()


def test_stored_key_prefers_environment_then_keychain(monkeypatch):
    import subprocess

    from core import ai_client

    monkeypatch.setenv("E_INFRA_API_TOKEN", " env-key ")
    assert ai_client.stored_api_key() == "env-key"
    monkeypatch.delenv("E_INFRA_API_TOKEN")
    monkeypatch.setattr(ai_client.sys, "platform", "darwin")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="chain-key\n", stderr="")

    monkeypatch.setattr(ai_client.subprocess, "run", fake_run)
    assert ai_client.stored_api_key() == "chain-key"
    assert calls[0][:2] == ["security", "find-generic-password"]
    monkeypatch.setattr(
        ai_client.subprocess, "run",
        lambda args, **_kw: subprocess.CompletedProcess(args, 44, stdout="", stderr="not found"),
    )
    assert ai_client.stored_api_key() == ""
    monkeypatch.setattr(ai_client.sys, "platform", "win32")
    assert ai_client.stored_api_key() == ""


def test_integral_floats_accepted_and_non_chat_models_hidden():
    from core.ai_client import chat_models

    parsed = parse_plan(json.dumps(plan([{"op": "smooth", "params": {"window": 11.0, "poly_order": 3.0}}])))
    from core.processing import validate_operations

    assert validate_operations(parsed["operations"])[0]["params"] == {"window": 11, "poly_order": 3}
    with pytest.raises(ValueError):
        parse_plan(json.dumps(plan([{"op": "smooth", "params": {"window": 11.5}}])))
    assert chat_models(["gpt-oss-120b", "nomic-embed-text-v1.5", "qwen3-reranker-4b",
                        "whisper-large-v3", "multilingual-e5-large-instruct", "qwen3.5"]) == [
        "gpt-oss-120b", "qwen3.5"]


def test_presentation_is_whitelisted_and_validated():
    ok = plan()
    ok["presentation"] = {"graphics": {"palette": "pubBold"}, "peaks": {"max_peaks": 8}, "detect_peaks": True}
    assert parse_plan(json.dumps(ok))["presentation"]["detect_peaks"] is True
    for bad in [
        {"graphics": {"export_width": 99999}},          # not whitelisted
        {"graphics": {"font_family": "Comic Sans"}},    # unknown font
        {"peaks": {"max_peaks": True}},                 # bool as number
        {"peaks": {"polarity": "sideways"}},
        {"plot": {"x_min": 0}},
        {"detect_peaks": "yes"},
        {"peaks": {"relative_prominence": 2}},
        {"peaks": {"relative_prominence": True}},
        {"script": "rm -rf /"},
        {},
    ]:
        bad_plan = plan()
        bad_plan["presentation"] = bad
        with pytest.raises(AIError):
            parse_plan(json.dumps(bad_plan))


def test_context_reports_band_widths_for_safe_filters():
    x = np.linspace(100, 1100, 1001)
    y = 1000 * np.exp(-0.5 * ((x - 520) / 3.0) ** 2) + 100 * np.exp(-0.5 * ((x - 900) / 20) ** 2)
    spec = Spectrum(x=x.tolist(), y=y.tolist(), meta={"technique": "raman"})
    context = spectrum_context(spec, y, False)
    strongest = context["strongest_bands"][0]
    assert abs(strongest["x"] - 520) < 1 and strongest["relative_prominence"] > 0.9
    assert 6 < strongest["fwhm_points"] < 8      # FWHM = 2.355 sigma = 7 points
    assert context["narrowest_strong_band_fwhm_points"] == strongest["fwhm_points"]
    assert len(context["strongest_bands"]) == 2


def test_detection_listed_as_operation_moves_to_presentation():
    raw = plan([{"op": "smooth", "params": {"window": 5, "poly_order": 2}},
                {"op": "detect_peaks", "params": {"threshold": 0.1}}])
    parsed = parse_plan(json.dumps(raw))
    assert [op["op"] for op in parsed["operations"]] == ["smooth"]
    assert parsed["presentation"]["detect_peaks"] is True
    assert any("Detekce" in warning for warning in parsed["warnings"])


def test_transient_server_error_is_retried_once():
    import urllib.error

    client = EInfraClient("fake_key")
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 500, "busy", {}, None)
            return Response(json.dumps({"data": [{"id": "m"}]}).encode())

    with patch("urllib.request.build_opener", return_value=Opener()), patch("time.sleep"):
        assert client.list_models() == ["m"]
    assert len(calls) == 2


def test_band_summary_sees_bands_on_a_broad_background():
    x = np.linspace(100, 1900, 1801)
    background = 5000 * np.exp(-0.5 * ((x - 1300) / 400) ** 2)
    bands = sum(h * np.exp(-0.5 * ((x - c) / 12) ** 2) for c, h in [(400, 600), (900, 500), (1600, 400)])
    y = background + bands + np.random.default_rng(1).normal(0, 10, len(x))
    spec = Spectrum(x=x.tolist(), y=y.tolist(), meta={"technique": "raman"})
    context = spectrum_context(spec, y, False)
    found = sorted(round(band["x"] / 100) * 100 for band in context["strongest_bands"])
    assert {400, 900, 1600} <= set(found)
    assert 20 < context["typical_band_fwhm_points"] < 40      # FWHM 28 points, not the background
