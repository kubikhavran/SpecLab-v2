"""Live check of the e-INFRA AI connection with a synthetic spectrum.

Usage (the key is read from E_INFRA_API_TOKEN, then from the macOS Keychain item
"e-infra-api", otherwise asked for without echo; it is never printed or stored):

    python3 scripts/ai_smoke_test.py            # list models, use the first one
    python3 scripts/ai_smoke_test.py MODEL_ID   # use a specific model
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src_python"))

import numpy as np  # noqa: E402

from app.models import Spectrum  # noqa: E402
from core.ai_client import AIError, EInfraClient, spectrum_context, stored_api_key  # noqa: E402
from core.processing import run_operations  # noqa: E402


def main() -> int:
    key = stored_api_key() or getpass.getpass("e-INFRA API klíč: ")
    client = EInfraClient(key)
    try:
        models = client.list_models()
    except AIError as exc:
        print(f"Seznam modelů selhal: {exc}")
        return 1
    print(f"Dostupné modely ({len(models)}): {', '.join(models)}")
    if not models:
        return 1
    model = sys.argv[1] if len(sys.argv) > 1 else models[0]
    x = np.linspace(200, 2000, 1801)
    rng = np.random.default_rng(7)
    y = 40 + 0.018 * x + 150 * np.exp(-0.5 * ((x - 1000) / 15) ** 2) + rng.normal(0, 2, len(x))
    spec = Spectrum(name="synthetic", x=x.tolist(), y=y.tolist(),
                    meta={"technique": "raman", "y_kind": "intensity", "x_unit": "cm^-1"})
    print(f"Žádám o návrh u modelu {model}…")
    try:
        plan = client.propose(model, "Odstraň pozadí a jemně vyhlaď šum, zachovej pás u 1000 cm-1.",
                              spectrum_context(spec, spec.y))
    except AIError as exc:
        print(f"Návrh selhal: {exc}")
        return 1
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if plan["operations"]:
        result = run_operations(spec.x, spec.y, spec.meta, plan["operations"])
        print(f"Plán lze lokálně spočítat: {len(result['y'])} bodů, kroky: "
              + " → ".join(op["op"] for op in plan["operations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
