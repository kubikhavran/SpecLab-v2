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

import numpy as np

from core.baseline import apply_baseline, asls_baseline
from core.cosmic import remove_cosmic_rays
from core.peak_detection import detect_peaks, detected_to_peaks
from core.smoothing import savgol_smooth

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


def _payload_section(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Return a payload subsection if it is a dict, otherwise an empty dict."""
    data = payload.get(key, {})
    return data if isinstance(data, dict) else {}


def _cache_present_for_loaded_spectra(state, cache: Dict[str, Any]) -> bool:
    """Return True if cache has data for at least one currently loaded spectrum."""
    if not isinstance(cache, dict):
        return False
    spectra = getattr(state, "spectra", [])
    if not spectra:
        return bool(cache)
    loaded_ids = {spec.id for spec in spectra}
    return any(spec_id in cache for spec_id in loaded_ids)


def _capture_pipeline_state(state) -> Dict[str, Any]:
    """
    Capture which processing stages are currently materialized in AppState caches.

    These flags are used by preset restore to decide whether to recompute or clear
    each processing stage for currently loaded spectra.
    """
    cosmic_applied = _cache_present_for_loaded_spectra(state, state.cosmic_clean_y)
    baseline_applied = (
        _cache_present_for_loaded_spectra(state, state.processed_y)
        or _cache_present_for_loaded_spectra(state, state.baseline_y)
        or bool(getattr(state.baseline, "enabled", False))
    )
    smoothing_applied = _cache_present_for_loaded_spectra(state, state.smoothed_y)
    auto_peaks_applied = _cache_present_for_loaded_spectra(state, state.peaks_auto)
    return {
        "cosmic_applied": cosmic_applied,
        "baseline_applied": baseline_applied,
        "smoothing_applied": smoothing_applied,
        "auto_peaks_applied": auto_peaks_applied,
        "raw_only": not (
            cosmic_applied
            or baseline_applied
            or smoothing_applied
            or auto_peaks_applied
        ),
    }


def _resolve_pipeline_state(payload: Dict[str, Any]) -> Dict[str, bool]:
    """
    Resolve processing stage flags from payload with backward-compatible defaults.

    Older presets may not contain payload['pipeline'].
    """
    pipeline = _payload_section(payload, "pipeline")
    baseline_payload = _payload_section(payload, "baseline")
    peaks_payload = _payload_section(payload, "peaks")

    raw_only = bool(pipeline.get("raw_only", False))
    has_stage_keys = any(
        key in pipeline
        for key in (
            "cosmic_applied",
            "baseline_applied",
            "smoothing_applied",
            "auto_peaks_applied",
        )
    )

    if raw_only and not has_stage_keys:
        return {
            "cosmic_applied": False,
            "baseline_applied": False,
            "smoothing_applied": False,
            "auto_peaks_applied": False,
        }

    return {
        "cosmic_applied": bool(pipeline.get("cosmic_applied", False)),
        "baseline_applied": bool(
            pipeline.get(
                "baseline_applied",
                baseline_payload.get("enabled", False),
            )
        ),
        "smoothing_applied": bool(pipeline.get("smoothing_applied", False)),
        "auto_peaks_applied": bool(
            pipeline.get(
                "auto_peaks_applied",
                peaks_payload.get("enabled", False),
            )
        ),
    }


def _recompute_pipeline_from_preset(state, pipeline_state: Dict[str, bool]) -> None:
    """
    Rebuild processing caches for currently loaded spectra to match preset state.

    Order is fixed:
      cosmic -> baseline -> smoothing -> auto peak detection
    Manual peaks are intentionally preserved.
    """
    spectra = list(getattr(state, "spectra", []))

    # Cosmic stage
    state.cosmic_clean_y.clear()
    if pipeline_state["cosmic_applied"]:
        c = state.cosmic
        for spec in spectra:
            result = remove_cosmic_rays(
                spec.y,
                window=c.window,
                threshold=c.threshold,
                max_width=c.max_width,
                positive_only=c.positive_only,
                iterations=c.iterations,
            )
            state.cosmic_clean_y[spec.id] = result.y_clean

    # Baseline stage
    state.processed_y.clear()
    state.baseline_y.clear()
    if pipeline_state["baseline_applied"]:
        b = state.baseline
        for spec in spectra:
            y_input = np.array(
                state.cosmic_clean_y.get(spec.id, spec.y),
                dtype=np.float64,
            )
            baseline = asls_baseline(
                y_input,
                lam=b.lambda_,
                p=b.p,
                n_iter=b.iterations,
            )
            corrected = apply_baseline(y_input, baseline)
            state.baseline_y[spec.id] = baseline.tolist()
            state.processed_y[spec.id] = corrected.tolist()

    # Smoothing stage
    state.smoothed_y.clear()
    if pipeline_state["smoothing_applied"]:
        s = state.smoothing
        for spec in spectra:
            if spec.id in state.processed_y:
                y_input = np.array(state.processed_y[spec.id], dtype=np.float64)
            elif spec.id in state.cosmic_clean_y:
                y_input = np.array(state.cosmic_clean_y[spec.id], dtype=np.float64)
            else:
                y_input = np.array(spec.y, dtype=np.float64)
            smooth = savgol_smooth(
                y_input,
                window=s.window,
                poly_order=s.poly_order,
            )
            state.smoothed_y[spec.id] = smooth.tolist()

    # Peak detection stage (auto peaks only). Manual peaks are preserved.
    state.peaks_auto.clear()
    should_detect_auto = (
        pipeline_state["auto_peaks_applied"] and state.peaks_settings.enabled
    )
    if should_detect_auto:
        p = state.peaks_settings
        for spec in spectra:
            y_data = state.displayed_y(spec.id)
            if y_data is None:
                y_data = spec.y
            detected = detect_peaks(
                spec.x,
                y_data,
                min_prominence=p.min_prominence,
                min_distance_x=p.min_distance,
                max_peaks=p.max_peaks,
                polarity=p.polarity if hasattr(p, "polarity") else "max",
            )
            state.peaks_auto[spec.id] = detected_to_peaks(detected)


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
        "spectral_mode": state.spectral_mode,
        "plot": _dataclass_to_dict(state.plot),
        "graphics": _dataclass_to_dict(state.graphics),
        "baseline": _dataclass_to_dict(state.baseline),
        "smoothing": _dataclass_to_dict(state.smoothing),
        "cosmic": _dataclass_to_dict(state.cosmic),
        "peaks": _dataclass_to_dict(state.peaks_settings),
        "pipeline": _capture_pipeline_state(state),
    }


def apply_preset_payload(state, payload: Dict[str, Any]) -> None:
    """
    Apply a preset payload back to AppState.

    This restores settings and then materializes the full processing pipeline
    (cosmic -> baseline -> smoothing -> auto peaks) for currently loaded spectra.
    """
    plot_payload = _payload_section(payload, "plot")
    graphics_payload = _payload_section(payload, "graphics")
    baseline_payload = _payload_section(payload, "baseline")
    smoothing_payload = _payload_section(payload, "smoothing")
    cosmic_payload = _payload_section(payload, "cosmic")
    peaks_payload = _payload_section(payload, "peaks")

    mode = payload.get("spectral_mode", "custom")
    if isinstance(mode, str):
        state.set_spectral_mode(mode, apply_defaults=False)

    if plot_payload:
        state.set_plot(**plot_payload)
    if graphics_payload:
        state.set_graphics(**graphics_payload)
    if baseline_payload:
        state.set_baseline(**baseline_payload)
    if smoothing_payload:
        state.set_smoothing(**smoothing_payload)
    if cosmic_payload:
        state.set_cosmic(**cosmic_payload)
    if peaks_payload:
        state.set_peaks(**peaks_payload)

    pipeline_state = _resolve_pipeline_state(payload)
    _recompute_pipeline_from_preset(state, pipeline_state)

    # Ensure plot and peak overlays refresh after cache recomputation.
    state.spectra_changed.emit()
    state.peaks_changed.emit()


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
