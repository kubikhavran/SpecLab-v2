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
        parse_plan("Some commentary " + json.dumps(plan()))


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
