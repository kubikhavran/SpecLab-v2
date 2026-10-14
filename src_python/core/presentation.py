"""Validated figure styling that an AI plan may propose next to processing.

Only a whitelist of cosmetic and peak-detection settings is accepted; values
are merged into the current settings and checked by the same validator as
presets and projects, so a plan can never touch export paths or data.
"""

from __future__ import annotations

from dataclasses import asdict

from app.models import GraphicsSettings, PeaksSettings, PlotSettings
from core.palettes import _FIXED, _GRADIENT
from core.project_io import settings_from_dict

FONT_FAMILIES = ("Arial", "Inter", "Times New Roman", "Courier New")
PALETTES = ("auto", *_FIXED, *_GRADIENT)
ALLOWED = {
    "graphics": (GraphicsSettings, {
        "x_label", "y_label", "axis_label_bold", "font_family", "base_font_size",
        "tick_font_size", "trace_line_width", "axis_line_width", "show_grid",
        "frame_mode", "palette", "inline_spectrum_labels", "show_x_tick_labels",
        "show_y_tick_labels", "show_x_tick_marks", "show_y_tick_marks",
    }),
    "peaks": (PeaksSettings, {
        "polarity", "min_prominence", "min_distance", "max_peaks", "decimals",
        "show_labels", "show_markers", "show_leader_lines", "label_angle_deg",
        "label_font_size", "label_bold", "label_italic", "label_color_mode",
    }),
    "plot": (PlotSettings, {"invert_x", "show_grid"}),
}
STATE_ATTRS = {"graphics": "graphics", "peaks": "peaks_settings", "plot": "plot"}


class PresentationError(ValueError):
    pass


def validate_presentation(value, state=None) -> dict:
    """Return {'settings': {section: full dict}, 'detect_peaks': bool,
    'relative_prominence': float | None}.

    ``peaks.relative_prominence`` is a fraction of the processed spectrum's Y
    range; unlike min_prominence it stays valid after normalisation.

    With a state, partial sections are merged into its current settings;
    without one (plan parsing) they are merged into defaults for validation.
    """
    if not isinstance(value, dict) or set(value) - set(ALLOWED) - {"detect_peaks"}:
        raise PresentationError("Návrh vzhledu smí obsahovat jen graphics, peaks, plot a detect_peaks.")
    detect = value.get("detect_peaks", False)
    if not isinstance(detect, bool):
        raise PresentationError("detect_peaks musí být logická hodnota.")
    settings = {}
    relative = None
    for section, (cls, keys) in ALLOWED.items():
        given = value.get(section)
        if given is None:
            continue
        if section == "peaks" and isinstance(given, dict) and "relative_prominence" in given:
            given = dict(given)
            relative = given.pop("relative_prominence")
            if isinstance(relative, bool) or not isinstance(relative, (int, float)) or not 0 < relative <= 1:
                raise PresentationError("relative_prominence musí být číslo v rozmezí (0, 1].")
        if not isinstance(given, dict) or set(given) - keys:
            unknown = ", ".join(sorted(set(given) - keys)) if isinstance(given, dict) else section
            raise PresentationError(f"Nepovolené nastavení vzhledu: {unknown}.")
        current = asdict(getattr(state, STATE_ATTRS[section])) if state is not None else asdict(cls())
        merged = {**current, **given}
        if "font_family" in given and given["font_family"] not in FONT_FAMILIES:
            raise PresentationError("Nepodporované písmo.")
        if "palette" in given and given["palette"] not in PALETTES:
            raise PresentationError("Neznámá barevná paleta.")
        for key, low in (("base_font_size", 18), ("tick_font_size", 18), ("label_font_size", 15)):
            # SpecLab units are 3 x points; smaller values give unreadable figures.
            if key in given and isinstance(given[key], (int, float)) and given[key] < low:
                raise PresentationError(
                    f"{key} {given[key]} je příliš malé (jednotky SpecLabu = 3× body; min. {low}).")
        if "label_angle_deg" in given and not (
            isinstance(given["label_angle_deg"], (int, float)) and -180 <= given["label_angle_deg"] <= 180
        ):
            raise PresentationError("Úhel popisku musí být v rozmezí −180 až 180°.")
        try:
            settings_from_dict(cls, merged)
        except ValueError as exc:
            raise PresentationError(f"Neplatné nastavení vzhledu: {exc}") from None
        settings[section] = merged
    if not settings and not detect and relative is None:
        raise PresentationError("Návrh vzhledu je prázdný.")
    return {"settings": settings, "detect_peaks": detect, "relative_prominence": relative}
