"""
Preset storage - save/load application setting snapshots to JSON.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import fields
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models import (
    BaselineSettings,
    CosmicSettings,
    GraphicsSettings,
    PeaksSettings,
    PlotSettings,
    SmoothingSettings,
)

PRESETS_FILENAME = "speclab_presets.json"


def _get_presets_path() -> str:
    """Return the path to the presets JSON file in user's config directory."""
    config_dir = os.path.join(os.path.expanduser("~"), ".speclab")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, PRESETS_FILENAME)


def _dataclass_to_dict(obj) -> dict:
    """Convert a dataclass instance to a dict, handling special field names."""
    result = {}
    for f in fields(obj):
        val = getattr(obj, f.name)
        result[f.name] = val
    return result


def _dict_to_dataclass(cls, data: dict):
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    valid_fields = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered)


class Preset:
    """A named snapshot of application settings."""

    def __init__(
        self,
        name: str,
        preset_id: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        self.id = preset_id or uuid.uuid4().hex
        self.name = name
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or self.created_at
        self.payload = payload or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Preset":
        return cls(
            name=data.get("name", "Unnamed"),
            preset_id=data.get("id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            payload=data.get("payload", {}),
        )


def capture_preset_payload(state) -> Dict[str, Any]:
    """Capture current settings from AppState into a preset payload dict."""
    return {
        "plot": _dataclass_to_dict(state.plot),
        "graphics": _dataclass_to_dict(state.graphics),
        "baseline": _dataclass_to_dict(state.baseline),
        "smoothing": _dataclass_to_dict(state.smoothing),
        "cosmic": _dataclass_to_dict(state.cosmic),
        "peaks": _dataclass_to_dict(state.peaks_settings),
    }


def apply_preset_payload(state, payload: Dict[str, Any]) -> None:
    """Apply a preset payload dict back to AppState."""
    if "plot" in payload:
        state.set_plot(**payload["plot"])
    if "graphics" in payload:
        state.set_graphics(**payload["graphics"])
    if "baseline" in payload:
        state.set_baseline(**payload["baseline"])
    if "smoothing" in payload:
        state.set_smoothing(**payload["smoothing"])
    if "cosmic" in payload:
        state.set_cosmic(**payload["cosmic"])
    if "peaks" in payload:
        state.set_peaks(**payload["peaks"])


def load_presets() -> List[Preset]:
    """Load presets from disk. Returns empty list if file doesn't exist."""
    path = _get_presets_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [Preset.from_dict(item) for item in data if isinstance(item, dict)]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_presets(presets: List[Preset]) -> None:
    """Save all presets to disk."""
    path = _get_presets_path()
    try:
        data = [p.to_dict() for p in presets]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def export_presets_to_file(presets: List[Preset], filepath: str) -> None:
    """Export presets to a user-chosen JSON file."""
    data = [p.to_dict() for p in presets]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def import_presets_from_file(filepath: str) -> List[Preset]:
    """Import presets from a user-chosen JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [Preset.from_dict(item) for item in data if isinstance(item, dict)]
    return []

