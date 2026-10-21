"""Tools through which the AI assistant edits a sandboxed copy of the workspace.

Every tool works on a private ``AppState`` copy.  Calls are forgiving: values
in natural units (points, nm, cm⁻¹) are converted, out-of-range numbers are
clamped with a warning, and anything the tool cannot do comes back to the
model as an explanatory error so that it can correct itself.  Nothing here
writes files, runs code or creates spectral data.
"""

from __future__ import annotations

import ast
import copy
import io
import json
import math
import re
from dataclasses import asdict, dataclass, field

import numpy as np

# core.figure maps font settings with 1/3 pt per unit and lines with 0.4 pt per unit.
FONT_UNITS_PER_PT = 3.0
PT_PER_LINE_UNIT = 0.4
MAX_CHECKPOINTS = 40


class ToolError(ValueError):
    """Explains to the model why a call failed and how to fix it."""


@dataclass
class ToolResult:
    text: str
    image: bytes | None = None
    mutated: bool = False
    finished: bool = False
    summary: str = ""          # one line for the user's activity log
    ok: bool = True


@dataclass
class Attachment:
    """A reference the user attached: an image, a SpecLab project/preset or spectra."""
    id: str
    kind: str                       # image | project | preset | spectra
    name: str
    image: bytes | None = None      # PNG shown to the model (rendered for project/spectra)
    state: object | None = None     # AppState for project/spectra references
    presets: list = field(default_factory=list)
    description: str = ""           # vision-helper transcription for text-only models


def _round(value, digits=4):
    if value is None or isinstance(value, (bool, str)):
        return value
    value = float(value)
    if not math.isfinite(value) or value == 0:
        return 0.0 if value == 0 else None
    return float(f"{value:.{digits}g}")


def _json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, default=lambda o: _round(o) if isinstance(o, (np.floating, float)) else str(o))


def _ok(**payload) -> str:
    return _json({"ok": True, **payload})


def _bool(value, name):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "1", "ano"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "no", "0", "ne"}:
        return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ToolError(f"{name} must be true or false.")


def _number(value, name, low=None, high=None, warnings=None, integer=False):
    if isinstance(value, bool) or value is None:
        raise ToolError(f"{name} must be a number.")
    if isinstance(value, str):
        try:
            value = float(value.replace(",", ".").strip())
        except ValueError:
            raise ToolError(f"{name} must be a number, got {value!r}.") from None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ToolError(f"{name} must be a finite number.")
    value = float(value)
    clamped = value
    if low is not None:
        clamped = max(low, clamped)
    if high is not None:
        clamped = min(high, clamped)
    if clamped != value and warnings is not None:
        warnings.append(f"{name} {value:g} adjusted to {clamped:g} (allowed {low:g}–{high:g}).")
    return int(round(clamped)) if integer else clamped


def parse_arguments(raw) -> dict:
    """Tool arguments as a dict; tolerates code fences, Python literals and empty strings."""
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    if not text:
        return {}
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except ValueError:
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            raise ToolError("Arguments are not valid JSON; send one JSON object.") from None
    if isinstance(value, str):
        return parse_arguments(value)
    if not isinstance(value, dict):
        raise ToolError("Arguments must be a JSON object.")
    return value


# ── Schemas ──────────────────────────────────────────────────────────────────

_SPECTRA = {"type": "array", "items": {"type": "string"},
            "description": 'Spectrum references: S1, S2… (or names/file names); ["all"] or omitted = all spectra.'}


def _tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": list(required)}}}


SCHEMAS = [
    _tool("get_workspace", "Current spectra (refs S1…, names, file names, laser, ranges, processing, colours, "
          "strongest bands) and all figure settings. Call again after larger changes."),
    _tool("get_spectrum_details", "More detail on one spectrum: up to 25 strongest bands with FWHM, noise, "
          "sampling and a decimated min/max envelope, optionally in an X window.",
          {"spectrum": {"type": "string"}, "x_min": {"type": "number"}, "x_max": {"type": "number"}},
          ["spectrum"]),
    _tool("process", "Process spectral data (sequential, validated). Operations: baseline {lam, p, iterations} "
          "(AsLS), smooth {window, poly_order} (Savitzky–Golay, window in points), despike {window, threshold, "
          "max_width, positive_only, iterations}, normalize {method: max|vector|area|minmax}, crop {min, max} "
          "(X units; clamped to each spectrum), interpolate {min, max}, resample {step}, shift {x, y}, scale "
          "{factor}, derivative {order, window, poly_order}, convert_y {target: absorbance|transmittance_percent|"
          "transmittance_fraction}. Peak labelling is NOT processing (use detect_peaks).",
          {"spectra": _SPECTRA, "operations": {"type": "array", "items": {"type": "object", "properties": {
              "op": {"type": "string"}, "params": {"type": "object"}}, "required": ["op"]}}},
          ["operations"]),
    _tool("remove_series_spikes", "Remove cosmic-ray spikes by comparing each spectrum with its neighbours in "
          "a series (e.g. potentials, time, map points); needs ≥3 similar spectra in series order and keeps "
          "real bands that appear in neighbours. Prefer it over despike for series; run it on the whole series "
          "(also hidden spectra) before other processing.",
          {"spectra": _SPECTRA}),
    _tool("reset_processing", "Restore original imported data (all processing removed) or remove only one "
          "processing stage (operation) and replay the rest.",
          {"spectra": _SPECTRA, "operation": {"type": "string", "description": "e.g. smooth; omit for all"}}),
    _tool("set_spectra", "Per-spectrum appearance and names: colour (#RRGGBB or CSS name), line width in pt, "
          "line style (solid|dash|dot|dashdot), visibility, new display name.",
          {"changes": {"type": "array", "items": {"type": "object", "properties": {
              "spectrum": {"type": "string"}, "color": {"type": "string"}, "line_width_pt": {"type": "number"},
              "line_style": {"type": "string"}, "visible": {"type": "boolean"}, "name": {"type": "string"}},
              "required": ["spectrum"]}}},
          ["changes"]),
    _tool("arrange_spectra", "Layout of the figure. stacked = vertical offset so spectra do not overlap "
          "(offset auto unless given in Y units; gap = extra fraction of the largest spectrum height), overlay = "
          "common baseline, single = only one spectrum. bottom_to_top sets the vertical order. scale_mode full "
          "shows each curve 0–1 (view only).",
          {"layout": {"type": "string", "enum": ["stacked", "overlay", "single"]}, "bottom_to_top": _SPECTRA,
           "offset": {"type": "number"}, "gap": {"type": "number"},
           "scale_mode": {"type": "string", "enum": ["common", "full"]}, "spectrum": {"type": "string"}}),
    _tool("detect_peaks", "Label the most prominent bands of EACH listed spectrum separately: top_n per spectrum, "
          "relative_prominence = fraction of that spectrum's own Y range in the region (auto from noise), "
          "min_distance in X units (auto from band widths), polarity auto (minima for transmittance). Region "
          "defaults to the current X axis limits. replace=true replaces earlier automatic labels.",
          {"spectra": _SPECTRA, "top_n": {"type": "integer"}, "relative_prominence": {"type": "number"},
           "min_distance": {"type": "number"}, "polarity": {"type": "string", "enum": ["auto", "max", "min", "both"]},
           "x_min": {"type": "number"}, "x_max": {"type": "number"}, "replace": {"type": "boolean"}}),
    _tool("annotate_peaks", "Add or relabel peak labels at given X positions of one spectrum (snapped to the "
          "nearest band maximum/minimum); label is optional custom text (else the position).",
          {"spectrum": {"type": "string"}, "peaks": {"type": "array", "items": {"type": "object", "properties": {
              "x": {"type": "number"}, "label": {"type": "string"}}, "required": ["x"]}},
           "snap": {"type": "boolean"}},
          ["spectrum", "peaks"]),
    _tool("remove_peaks", "Remove peak labels: all of them, those nearest to x_values, or all but the keep_top_n "
          "most prominent automatic ones.",
          {"spectra": _SPECTRA, "x_values": {"type": "array", "items": {"type": "number"}},
           "all": {"type": "boolean"}, "keep_top_n": {"type": "integer"}}),
    _tool("set_peak_labels", "Appearance of peak labels: font_size_pt, angle_deg (90 = vertical), bold, italic, "
          "color ('trace' = curve colour or #RRGGBB), leader_lines, leader_color ('trace' or #RRGGBB), "
          "leader_width_pt, markers, decimals, show_labels, shown_on (all|active spectrum).",
          {"font_size_pt": {"type": "number"}, "angle_deg": {"type": "number"}, "bold": {"type": "boolean"},
           "italic": {"type": "boolean"}, "color": {"type": "string"}, "leader_lines": {"type": "boolean"},
           "leader_color": {"type": "string"}, "leader_width_pt": {"type": "number"},
           "markers": {"type": "boolean"}, "decimals": {"type": "integer"}, "show_labels": {"type": "boolean"},
           "shown_on": {"type": "string", "enum": ["all", "active"]}}),
    _tool("set_axes", "Axis titles, limits (data X/Y units; auto_x/auto_y = automatic), direction and tick "
          "labels. Use ^{-1} or ⁻¹ for superscripts, e.g. 'Raman shift (cm^{-1})'.",
          {"x_label": {"type": "string"}, "y_label": {"type": "string"}, "x_min": {"type": "number"},
           "x_max": {"type": "number"}, "y_min": {"type": "number"}, "y_max": {"type": "number"},
           "auto_x": {"type": "boolean"}, "auto_y": {"type": "boolean"}, "invert_x": {"type": "boolean"},
           "show_x_values": {"type": "boolean"}, "show_y_values": {"type": "boolean"},
           "x_tick_marks": {"type": "boolean"}, "y_tick_marks": {"type": "boolean"},
           "tick_direction": {"type": "string", "enum": ["out", "in", "inout"]},
           "mirror_ticks": {"type": "boolean", "description": "ticks also on top/right (box frame)"},
           "axis_title_bold": {"type": "boolean"}, "axis_title_italic": {"type": "boolean"},
           "tick_labels_bold": {"type": "boolean"}, "tick_labels_italic": {"type": "boolean"}}),
    _tool("set_style", "Global figure style: font_family, axis_title_pt, tick_label_pt (also used for curve "
          "names), curve_line_width_pt (default for all curves), axis_line_width_pt, frame (open|box), grid, "
          "grid_color, axis_color, background (white|dark), palette (default colours: auto, pubBold, "
          "pubColorblind, tolBright, tolMuted, colorblind, tableau10, dark2, paired, mono, viridis, plasma, "
          "magma, cividis, deepRainbow, electrochem…), curve_names (beside|none), curve_name_bold/italic, "
          "export_width_px/export_height_px (canvas and aspect ratio of the exported figure).",
          {"font_family": {"type": "string"}, "axis_title_pt": {"type": "number"}, "tick_label_pt": {"type": "number"},
           "curve_line_width_pt": {"type": "number"}, "axis_line_width_pt": {"type": "number"},
           "frame": {"type": "string", "enum": ["open", "box"]}, "grid": {"type": "boolean"},
           "grid_color": {"type": "string"}, "axis_color": {"type": "string"},
           "background": {"type": "string", "enum": ["white", "dark"]}, "palette": {"type": "string"},
           "curve_names": {"type": "string", "enum": ["beside", "inside", "none"],
                           "description": "beside = right of the plot; inside = above each curve end inside the plot"},
           "curve_name_bold": {"type": "boolean"},
           "curve_name_italic": {"type": "boolean"}, "export_width_px": {"type": "integer"},
           "export_height_px": {"type": "integer"}}),
    _tool("suggest_colors", "Deterministic colour suggestions: print-safe colours for laser wavelengths in nm "
          "(e.g. 532 green, 633 orange-red, 785 dark red, 1064 brown-red) and/or count colours sampled from a "
          "palette or matplotlib colormap.",
          {"laser_wavelengths_nm": {"type": "array", "items": {"type": "number"}}, "palette": {"type": "string"},
           "count": {"type": "integer"}}),
    _tool("render_figure", "Render the publication figure exactly as it will be exported and return a report "
          "(per spectrum: colour, offset, labels shown/hidden; overlaps). Vision models also receive the image. "
          "Optional x_min/x_max zoom for checking details (does not change the figure).",
          {"x_min": {"type": "number"}, "x_max": {"type": "number"}}),
    _tool("get_reference", "Details of an attachment (A1…): for SpecLab projects/presets the exact settings, "
          "styles and processing; for spectra files their ranges and bands; for images the description.",
          {"attachment": {"type": "string"}}, ["attachment"]),
    _tool("apply_reference_settings", "Copy settings from a SpecLab project or preset attachment exactly. parts: "
          "graphics, plot, peaks (label style), styles (per-spectrum colours/lines by position or name), "
          "names, processing (replays the reference recipes from original data), peaks_positions (label "
          "the same bands).",
          {"attachment": {"type": "string"}, "parts": {"type": "array", "items": {"type": "string"}},
           "mapping": {"type": "string", "enum": ["order", "name"]}},
          ["attachment"]),
    _tool("undo_last_change", "Revert the most recent change made by a tool in this session."),
    _tool("finish", "End your turn after the figure fulfils the request. summary = short message for the user "
          "in their language: what you changed and anything they should check.",
          {"summary": {"type": "string"}}, ["summary"]),
]
MUTATING = {"process", "reset_processing", "remove_series_spikes", "set_spectra", "arrange_spectra", "detect_peaks", "annotate_peaks",
            "remove_peaks", "set_peak_labels", "set_axes", "set_style", "apply_reference_settings"}
TOOL_TITLES = {
    "get_workspace": "Přehled spekter", "get_spectrum_details": "Detail spektra", "process": "Zpracování dat",
    "reset_processing": "Obnova dat", "remove_series_spikes": "Spiky podle série", "set_spectra": "Barvy a názvy spekter", "arrange_spectra": "Rozložení spekter",
    "detect_peaks": "Popisky píků", "annotate_peaks": "Vlastní popisky", "remove_peaks": "Odebrání popisků",
    "set_peak_labels": "Vzhled popisků", "set_axes": "Osy", "set_style": "Styl obrázku",
    "suggest_colors": "Návrh barev", "render_figure": "Kontrola obrázku", "get_reference": "Vzor",
    "apply_reference_settings": "Převzetí vzoru", "undo_last_change": "Vrácení kroku", "finish": "Hotovo",
}

_OP_ALIASES = {
    "baseline_correction": "baseline", "asls": "baseline", "background": "baseline", "subtract_baseline": "baseline",
    "savgol": "smooth", "savitzky_golay": "smooth", "smoothing": "smooth", "smoothen": "smooth",
    "cosmic": "despike", "cosmic_ray_removal": "despike", "despiking": "despike", "spikes": "despike",
    "normalise": "normalize", "normalization": "normalize", "normalisation": "normalize",
    "trim": "crop", "cut": "crop", "clip": "crop", "range": "crop", "crop_x": "crop",
    "derivate": "derivative", "multiply": "scale", "offset": "shift", "convert": "convert_y",
    "interpolation": "interpolate",
}
_PARAM_ALIASES = {
    "lambda": "lam", "lambda_": "lam", "smoothness": "lam", "asymmetry": "p", "niter": "iterations",
    "n_iter": "iterations", "iter": "iterations", "window_length": "window", "window_size": "window",
    "polyorder": "poly_order", "poly": "poly_order", "order_poly": "poly_order", "x_min": "min", "xmin": "min",
    "start": "min", "low": "min", "x_max": "max", "xmax": "max", "end": "max", "high": "max", "dx": "x", "dy": "y",
    "multiplier": "factor", "positive": "positive_only",
}
_DETECTION_NAMES = {"detect_peaks", "peak_detection", "find_peaks", "detect", "peaks", "label_peaks"}
_NORMALIZE = {"max": "max", "maximum": "max", "peak": "max", "highest": "max", "vector": "vector", "l2": "vector",
              "norm": "vector", "unit_vector": "vector", "area": "area", "integral": "area", "minmax": "minmax",
              "min_max": "minmax", "min-max": "minmax", "range": "minmax", "0-1": "minmax"}
_LINE_STYLES = {"solid": "solid", "-": "solid", "line": "solid", "dash": "dash", "dashed": "dash", "--": "dash",
                "dot": "dot", "dotted": "dot", ":": "dot", "dashdot": "dashdot", "dash-dot": "dashdot",
                "dash_dot": "dashdot", "-.": "dashdot"}


class Toolbox:
    """Dispatches model tool calls onto a staged AppState."""

    def __init__(self, state, aliases: dict[str, str], attachments=(), render_size=None, selected=()):
        self.state = state
        self.aliases = dict(aliases)            # "S1" → spectrum id (stable for the session)
        self.attachments = {a.id: a for a in attachments}
        self.render_size = render_size
        self.selected = list(selected)
        self.checkpoints: list[tuple[str, dict]] = []
        self.changes_since_render = 0
        self.renders = 0
        self.hide_names = False     # privacy option: no names or file names in summaries
        self.offset_gap = None      # gap of the last automatic stack offset (None = fixed/unknown)

    # ── references ────────────────────────────────────────────────────────

    def ref(self, sid: str) -> str:
        for alias, value in self.aliases.items():
            if value == sid:
                return alias
        alias = f"S{len(self.aliases) + 1}"
        self.aliases[alias] = sid
        return alias

    def _spectrum(self, sid):
        return next(s for s in self.state.spectra if s.id == sid)

    def _name(self, sid) -> str:
        """Display name, or only the S-number when names must not be sent."""
        return self.ref(sid) if self.hide_names else self._spectrum(sid).name

    def _one(self, ref) -> str:
        spectra = self.state.spectra
        loaded = {s.id for s in spectra}
        if isinstance(ref, bool):
            raise ToolError("Spectrum reference must be text like S1.")
        if isinstance(ref, (int, float)):
            ref = f"S{int(ref)}"
        text = str(ref).strip()
        if not text:
            raise ToolError("Empty spectrum reference.")
        alias = text.upper()
        if re.fullmatch(r"\d+", alias):
            alias = "S" + alias
        if alias in self.aliases and self.aliases[alias] in loaded:
            return self.aliases[alias]
        if text in loaded:
            return text
        lowered = text.lower()

        def keys(spec):
            source = str(spec.meta.get("sourceName", ""))
            return {spec.name.lower(), source.lower(), source.rsplit(".", 1)[0].lower()} - {""}

        exact = [s.id for s in spectra if lowered in keys(s)]
        if len(exact) == 1:
            return exact[0]
        partial = [s.id for s in spectra if any(lowered in key for key in keys(s))]
        if len(partial) == 1:
            return partial[0]
        options = ", ".join(f"{self.ref(s.id)} ({self._name(s.id)})" for s in spectra[:40])
        if len(exact) > 1 or len(partial) > 1:
            raise ToolError(f"Reference {text!r} matches several spectra; use S-numbers: {options}.")
        raise ToolError(f"Unknown spectrum {text!r}. Available: {options}.")

    def ids(self, refs, default_all=True) -> list[str]:
        spectra = self.state.spectra
        if refs is None or refs == [] or refs == "":
            if default_all:
                return [s.id for s in spectra]
            raise ToolError("Name at least one spectrum.")
        if isinstance(refs, (str, int)):
            refs = [refs]
        if not isinstance(refs, list):
            raise ToolError("spectra must be a list such as [\"S1\", \"S2\"] or [\"all\"].")
        result = []
        for ref in refs:
            word = str(ref).strip().lower()
            if word in {"all", "*", "všechna", "vse", "vše"}:
                result += [s.id for s in spectra]
            elif word in {"visible", "shown"}:
                result += [s.id for s in spectra if s.meta.get("trace_style", {}).get("visible", True)]
            elif word in {"active", "current"}:
                if self.state.active_spectrum_id:
                    result.append(self.state.active_spectrum_id)
            elif word in {"selected", "selection"}:
                result += [sid for sid in self.selected if sid in {s.id for s in spectra}]
            else:
                result.append(self._one(ref))
        result = list(dict.fromkeys(result))
        if not result:
            raise ToolError("No spectrum matches the reference.")
        return result

    # ── dispatch ──────────────────────────────────────────────────────────

    def run(self, name: str, raw_arguments) -> ToolResult:
        handler = getattr(self, "_t_" + str(name), None)
        if handler is None:
            available = ", ".join(tool["function"]["name"] for tool in SCHEMAS)
            return ToolResult(_json({"ok": False, "error": f"Unknown tool {name!r}. Tools: {available}."}),
                              summary=f"neznámý nástroj {name}", ok=False)
        try:
            arguments = parse_arguments(raw_arguments)
        except ToolError as exc:
            return ToolResult(_json({"ok": False, "error": str(exc)}), summary="neplatné argumenty", ok=False)
        before = self.state._snapshot() if name in MUTATING else None
        try:
            result = handler(**arguments) if arguments else handler()
        except TypeError as exc:
            if before is not None:
                self.state._restore(before)
            message = str(exc)
            if "unexpected keyword argument" in message:
                bad = message.split("argument")[-1].strip(" '\"")
                message = f"Unknown parameter {bad!r} for {name}; see the tool schema."
            return ToolResult(_json({"ok": False, "error": message}), summary="chybné parametry", ok=False)
        except (ToolError, ValueError) as exc:
            if before is not None:
                self.state._restore(before)
            return ToolResult(_json({"ok": False, "error": str(exc)}), summary=str(exc)[:120], ok=False)
        except Exception as exc:  # noqa: BLE001 - an internal tool bug must not end the conversation
            import traceback

            traceback.print_exc()
            if before is not None:
                self.state._restore(before)
            message = f"Internal error in {name}: {type(exc).__name__}: {exc}. Try another way or skip this step."
            return ToolResult(_json({"ok": False, "error": message}), summary="vnitřní chyba nástroje", ok=False)
        if not isinstance(result, ToolResult):
            result = ToolResult(result)
        if before is not None:
            result.mutated = True
            self.checkpoints.append((name, before))
            self.checkpoints = self.checkpoints[-MAX_CHECKPOINTS:]
            self.changes_since_render += 1
        return result

    # ── settings helpers ──────────────────────────────────────────────────

    def _update(self, attr: str, changes: dict):
        from core.project_io import SETTINGS, settings_from_dict

        cls = next(c for a, c in SETTINGS.values() if a == attr)
        merged = {**asdict(getattr(self.state, attr)), **changes}
        try:
            setattr(self.state, attr, settings_from_dict(cls, merged))
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    def _colors(self) -> dict[str, str]:
        from core.colors import parse_color
        from core.palettes import get_color_for_index, get_palette_colors

        state = self.state
        palette = get_palette_colors(state.graphics.palette, len(state.spectra))
        return {s.id: parse_color(s.meta.get("trace_style", {}).get("color", get_color_for_index(palette, i)))
                for i, s in enumerate(state.spectra)}

    def _plotted(self):
        state = self.state
        order = list(reversed(state.spectra)) if state.plot.reverse_overlay_order else list(state.spectra)
        if not state.plot.show_all_spectra:
            active = state.active_spectrum or (order[0] if order else None)
            return [active] if active else []
        return [s for s in order if s.meta.get("trace_style", {}).get("visible", True)]

    def _xy(self, sid):
        spec = self._spectrum(sid)
        x = np.asarray(spec.x, dtype=float)
        y = np.asarray(self.state.displayed_y(sid), dtype=float)
        if x[0] > x[-1]:
            x, y = x[::-1], y[::-1]
        return x, y

    # ── read tools ────────────────────────────────────────────────────────

    def workspace(self) -> dict:
        from core.ai_client import _band_summary

        state = self.state
        colors = self._colors()
        spectra = []
        for spec in state.spectra:
            x, y = self._xy(spec.id)
            meta = spec.meta
            style = meta.get("trace_style", {})
            item = {"ref": self.ref(spec.id), "name": self.ref(spec.id) if self.hide_names else spec.name}
            if meta.get("sourceName") and not self.hide_names:
                item["file"] = meta["sourceName"]
            laser = meta.get("laser_wavenumber_cm1")
            if isinstance(laser, (int, float)) and laser > 0:
                item["laser_nm"] = round(1e7 / laser, 1)
            for key in ("technique", "x_unit", "y_kind", "series_label", "potential_mV"):
                if meta.get(key) not in (None, "", "unknown", "custom"):
                    item[key] = meta[key]
            item.update({
                "points": len(x), "x_range": [_round(x.min(), 5), _round(x.max(), 5)],
                "y_range": [_round(y.min()), _round(y.max())],
                "visible": style.get("visible", True), "color": colors[spec.id],
            })
            if "width" in style:
                item["line_width_pt"] = _round(style["width"] * PT_PER_LINE_UNIT, 3)
            if style.get("line", "solid") != "solid":
                item["line_style"] = style["line"]
            recipe = state.processing_recipe(spec.id)
            if recipe:
                item["processing"] = [op["op"] + "(" + ", ".join(f"{k}={_round(v)}" for k, v in op["params"].items()
                                                                if v is not None) + ")" for op in recipe]
            peaks = state.peaks_auto.get(spec.id, []) + state.peaks_manual.get(spec.id, [])
            if peaks:
                item["peak_labels"] = [
                    _round(p.x, 5) if not p.label else f"{_round(p.x, 5)}:{p.label}" for p in
                    sorted(peaks, key=lambda p: p.x)][:40]
            try:
                bands = _band_summary(x, y, meta.get("y_kind", "intensity"), limit=6)
                item["relative_noise"] = bands["relative_noise"]
                item["strongest_bands"] = [{"x": b["x"], "rel": b["relative_prominence"], "fwhm": b["fwhm_x"]}
                                           for b in bands["strongest_bands"]]
            except (ValueError, IndexError):
                pass
            spectra.append(item)
        plot, graphics, peaks = state.plot, state.graphics, state.peaks_settings
        plotted = [self.ref(s.id) for s in self._plotted()]
        if not plot.show_all_spectra:
            layout = "single"
        else:
            layout = "stacked" if plot.stack_offset else "overlay"
        figure = {
            "layout": layout, "plotted_bottom_to_top": plotted, "stack_offset": _round(plot.stack_offset),
            "scale_mode": plot.scale_mode, "x_label": graphics.x_label, "y_label": graphics.y_label,
            "x_limits": [plot.x_min, plot.x_max] if plot.x_min is not None and plot.x_max is not None else "auto",
            "y_limits": [plot.y_min, plot.y_max] if plot.y_min is not None and plot.y_max is not None else "auto",
            "invert_x": plot.invert_x, "font_family": graphics.font_family,
            "axis_title_pt": _round(graphics.base_font_size / FONT_UNITS_PER_PT, 3),
            "tick_label_pt": _round(graphics.tick_font_size / FONT_UNITS_PER_PT, 3),
            "curve_line_width_pt": _round(graphics.trace_line_width * PT_PER_LINE_UNIT, 3),
            "axis_line_width_pt": _round(graphics.axis_line_width * PT_PER_LINE_UNIT, 3),
            "frame": graphics.frame_mode, "grid": graphics.show_grid, "palette": graphics.palette,
            "background": "dark" if graphics.plot_canvas == "dark" else "white",
            "curve_names": ("none" if not graphics.inline_spectrum_labels else
                            "inside" if graphics.spectrum_label_position == "inside" else "beside"),
            "x_values": graphics.show_x_tick_labels, "y_values": graphics.show_y_tick_labels,
            "tick_direction": graphics.tick_direction, "mirror_ticks": graphics.mirror_ticks,
            "axis_title_bold": graphics.axis_label_bold,
            "export_size_px": [graphics.export_width, graphics.export_height],
            "peak_labels": {
                "enabled": peaks.enabled, "shown_on": peaks.mode, "show_labels": peaks.show_labels,
                "font_size_pt": _round(peaks.label_font_size / FONT_UNITS_PER_PT, 3), "angle_deg": peaks.label_angle_deg,
                "bold": peaks.label_bold, "color": "trace" if peaks.label_color_mode == "trace" else peaks.label_color,
                "leader_lines": peaks.show_leader_lines, "markers": peaks.show_markers, "decimals": peaks.decimals,
            },
        }
        result = {"spectra": spectra, "active": self.ref(state.active_spectrum_id) if state.active_spectrum_id else None,
                  "figure": figure}
        if self.selected:
            result["selected_in_ui"] = [self.ref(sid) for sid in self.selected
                                        if sid in {s.id for s in state.spectra}]
        if self.attachments:
            result["attachments"] = [{"id": a.id, "kind": a.kind, "name": a.name} for a in self.attachments.values()]
        return result

    def _t_get_workspace(self):
        return ToolResult(_ok(**self.workspace()), summary="přehled")

    def _t_get_spectrum_details(self, spectrum, x_min=None, x_max=None):
        from core.ai_client import _band_summary

        sid = self._one(spectrum)
        x, y = self._xy(sid)
        if x_min is not None or x_max is not None:
            low = x.min() if x_min is None else _number(x_min, "x_min")
            high = x.max() if x_max is None else _number(x_max, "x_max")
            low, high = min(low, high), max(low, high)
            mask = (x >= low) & (x <= high)
            if np.count_nonzero(mask) < 5:
                raise ToolError(f"Window {low:g}–{high:g} has no data; {self.ref(sid)} spans "
                                f"{x.min():g}–{x.max():g}.")
            x, y = x[mask], y[mask]
        spec = self._spectrum(sid)
        bands = _band_summary(x, y, spec.meta.get("y_kind", "intensity"), limit=25)
        bins = np.array_split(np.arange(len(x)), min(120, len(x)))
        envelope = sorted({int(b[np.argmin(y[b])]) for b in bins} | {int(b[np.argmax(y[b])]) for b in bins})
        step = float(np.median(np.abs(np.diff(x)))) if len(x) > 1 else 0.0
        return ToolResult(_ok(spectrum=self.ref(sid), name=self._name(sid), points=len(x), x_step=_round(step),
                              y_range=[_round(y.min()), _round(y.max())], **bands,
                              envelope_xy=[[_round(x[i], 5), _round(y[i])] for i in envelope]),
                          summary=f"{self.ref(sid)}")

    # ── processing ────────────────────────────────────────────────────────

    def _normalise_operation(self, item, warnings) -> dict:
        if not isinstance(item, dict):
            raise ToolError("Each operation must be an object {op, params}.")
        op = str(item.get("op", item.get("operation", item.get("name", "")))).strip().lower().replace(" ", "_")
        op = _OP_ALIASES.get(op, op)
        if op in _DETECTION_NAMES:
            raise ToolError("Peak labelling is not a processing operation; call detect_peaks instead.")
        from core.processing import DEFAULTS

        if op not in DEFAULTS:
            raise ToolError(f"Unknown operation {op!r}. Allowed: {', '.join(DEFAULTS)}.")
        params = item.get("params", {k: v for k, v in item.items() if k not in {"op", "operation", "name"}})
        if not isinstance(params, dict):
            raise ToolError(f"params of {op} must be an object.")
        clean = {}
        for key, value in params.items():
            key = _PARAM_ALIASES.get(str(key).lower(), str(key).lower())
            if key not in DEFAULTS[op]:
                warnings.append(f"{op}: ignored unknown parameter {key!r}.")
                continue
            clean[key] = value
        if op in {"smooth", "derivative", "despike"} and "window" in clean:
            window = _number(clean["window"], f"{op}.window", 5 if op == "despike" else 3, 1001, warnings, True)
            if window % 2 == 0:
                window += 1
                warnings.append(f"{op}.window made odd ({window}).")
            clean["window"] = window
        if op in {"smooth", "derivative"} and "poly_order" in clean:
            clean["poly_order"] = _number(clean["poly_order"], f"{op}.poly_order", 0, 9, warnings, True)
        if op in {"smooth", "derivative"}:
            window = clean.get("window", DEFAULTS[op]["window"])
            order = clean.get("poly_order", DEFAULTS[op]["poly_order"])
            if order >= window:
                clean["poly_order"] = max(0, window - 2)
                warnings.append(f"{op}.poly_order lowered to {clean['poly_order']} (< window).")
        if op == "baseline":
            for key, low, high, integer in (("lam", 1, 1e12, False), ("p", 1e-6, 1 - 1e-6, False),
                                            ("iterations", 1, 100, True)):
                if key in clean:
                    clean[key] = _number(clean[key], f"baseline.{key}", low, high, warnings, integer)
        if op == "despike":
            for key, low, high, integer in (("threshold", 0.1, 100, False), ("max_width", 1, 100, True),
                                            ("iterations", 1, 100, True)):
                if key in clean:
                    clean[key] = _number(clean[key], f"despike.{key}", low, high, warnings, integer)
            if "positive_only" in clean:
                clean["positive_only"] = _bool(clean["positive_only"], "positive_only")
        if op == "normalize":
            method = str(clean.get("method", "max")).strip().lower()
            if method not in _NORMALIZE:
                raise ToolError("normalize.method must be max, vector, area or minmax.")
            clean["method"] = _NORMALIZE[method]
        if op == "convert_y":
            target = str(clean.get("target", "")).strip().lower()
            target = {"a": "absorbance", "abs": "absorbance", "%t": "transmittance_percent",
                      "transmittance": "transmittance_percent", "t%": "transmittance_percent",
                      "percent_transmittance": "transmittance_percent", "t": "transmittance_fraction",
                      "fraction": "transmittance_fraction"}.get(target, target)
            clean["target"] = target
        if op == "derivative" and "order" in clean:
            clean["order"] = _number(clean["order"], "derivative.order", 1, 2, warnings, True)
        for key in ("min", "max", "x", "y", "factor", "step"):
            if key in clean and clean[key] is not None:
                clean[key] = _number(clean[key], f"{op}.{key}")
        if op == "shift" and clean.get("y"):
            raise ToolError("Do not shift intensities to arrange spectra: use arrange_spectra (stack offset, view "
                            "only). Use shift only for an X calibration (shift x) or when the user asks for it.")
        return {"op": op, "params": clean}

    def _t_process(self, operations, spectra=None):
        from core.processing import validate_operations

        if not isinstance(operations, list) or not operations:
            raise ToolError("operations must be a non-empty list.")
        ids = self.ids(spectra)
        warnings: list[str] = []
        normalised = [self._normalise_operation(item, warnings) for item in operations]
        groups: dict[str, list[str]] = {}
        recipes = {}
        for sid in ids:
            x, _ = self._xy(sid)
            recipe = []
            for item in normalised:
                params = dict(item["params"])
                if item["op"] in {"crop", "interpolate"}:
                    low = params.get("min", x.min())
                    high = params.get("max", x.max())
                    low, high = (low, high) if low <= high else (high, low)
                    if high < x.min() or low > x.max():
                        raise ToolError(f"{item['op']} {low:g}–{high:g} lies outside {self.ref(sid)} "
                                        f"({x.min():g}–{x.max():g}); exclude this spectrum or change the range.")
                    if item["op"] == "crop" and (low < x.min() or high > x.max()):
                        warnings.append(f"crop clamped to {max(low, x.min()):g}–{min(high, x.max()):g} "
                                        f"for {self.ref(sid)}.")
                        low, high = max(low, float(x.min())), min(high, float(x.max()))
                    params["min"], params["max"] = low, high
                if item["op"] in {"smooth", "derivative", "despike"}:
                    window = params.get("window")
                    if window is not None and window > len(x):
                        params["window"] = len(x) - (1 - len(x) % 2)
                        warnings.append(f"{item['op']}.window reduced to {params['window']} for {self.ref(sid)}.")
                recipe.append({"op": item["op"], "params": params})
            try:
                recipe = validate_operations(recipe)
            except ValueError as exc:
                raise ToolError(f"{exc}") from None
            key = json.dumps(recipe, sort_keys=True)
            groups.setdefault(key, []).append(sid)
            recipes[key] = recipe
        for key, group in groups.items():
            try:
                self.state.apply_operations(recipes[key], group, source="ai",
                                            label="AI: " + " → ".join(op["op"] for op in recipes[key]))
            except ValueError as exc:
                raise ToolError(f"{exc} (spectra {', '.join(self.ref(s) for s in group)})") from None
        result = []
        for sid in ids:
            x, y = self._xy(sid)
            result.append({"spectrum": self.ref(sid), "points": len(x), "x_range": [_round(x.min(), 5), _round(x.max(), 5)],
                           "y_range": [_round(y.min()), _round(y.max())]})
        applied = next(iter(recipes.values()))
        self._refit_offset(warnings)
        cleared = [self.ref(sid) for sid in ids if not self.state.peaks_auto.get(sid)]
        note = ("Data changed, so automatic peak labels of the processed spectra were removed; call "
                "detect_peaks after the last processing step." if cleared else None)
        return ToolResult(_ok(applied=applied, spectra=result, warnings=warnings, note=note),
                          summary=" → ".join(op["op"] for op in applied) + f" · {len(ids)} spekter")

    def _t_remove_series_spikes(self, spectra=None):
        ids = self.ids(spectra)
        if len(ids) < 3:
            raise ToolError("Series spike removal needs at least 3 spectra of one series.")
        preview = self.state.preview_series_despike(ids)
        if preview is None:
            return ToolResult(_ok(removed=0, note="No spikes found."), summary="žádné spiky")
        self.state.apply_preview(preview)
        found = {self.ref(sid): len(ops) for sid, ops in preview.get("operations_by_id", {}).items()}
        warnings = []
        self._refit_offset(warnings)
        return ToolResult(_ok(spikes_removed=found, warnings=warnings,
                              note="Automatic peak labels of these spectra were cleared; detect again if needed."),
                          summary=f"{sum(found.values())} míst · {len(found)} spekter")

    def _t_reset_processing(self, spectra=None, operation=None):
        ids = self.ids(spectra)
        if operation:
            name = _OP_ALIASES.get(str(operation).lower(), str(operation).lower())
            ids = [sid for sid in ids if any(op["op"] == name for op in self.state.processing_recipe(sid))]
            if not ids:
                raise ToolError(f"No listed spectrum contains {name!r} in its processing.")
            self.state.reset_operation(name, ids)
        else:
            self.state.reset_processing(ids)
        warnings = []
        self._refit_offset(warnings)
        return ToolResult(_ok(spectra=[self.ref(s) for s in ids], removed=operation or "all processing",
                              warnings=warnings),
                          summary=f"{operation or 'vše'} · {len(ids)} spekter")

    # ── appearance of spectra ─────────────────────────────────────────────

    def _t_set_spectra(self, changes):
        from core.collection import validate_style
        from core.colors import parse_color

        if isinstance(changes, dict):
            changes = [changes]
        if not isinstance(changes, list) or not changes:
            raise ToolError("changes must be a list of {spectrum, color, line_width_pt, line_style, visible, name}.")
        warnings, done = [], []
        for change in changes:
            if not isinstance(change, dict) or "spectrum" not in change:
                raise ToolError("Every change needs a spectrum reference.")
            unknown = set(change) - {"spectrum", "color", "line_width_pt", "line_style", "visible", "name", "width"}
            if unknown:
                warnings.append(f"ignored {', '.join(sorted(unknown))}")
            for sid in self.ids([change["spectrum"]]):
                spec = self._spectrum(sid)
                style = dict(spec.meta.get("trace_style", {}))
                if change.get("color") is not None:
                    style["color"] = parse_color(change["color"])
                width = change.get("line_width_pt", change.get("width"))
                if width is not None:
                    pt = _number(width, "line_width_pt", 0.1, 10, warnings)
                    style["width"] = round(pt / PT_PER_LINE_UNIT, 3)
                if change.get("line_style") is not None:
                    line = _LINE_STYLES.get(str(change["line_style"]).strip().lower())
                    if line is None:
                        raise ToolError("line_style must be solid, dash, dot or dashdot.")
                    style["line"] = line
                if change.get("visible") is not None:
                    style["visible"] = _bool(change["visible"], "visible")
                spec.meta["trace_style"] = validate_style(style)
                if change.get("name") is not None:
                    name = str(change["name"]).strip()
                    if not 1 <= len(name) <= 1000:
                        raise ToolError("Names must have 1–1000 characters.")
                    spec.name = name
                done.append({"spectrum": self.ref(sid), "name": self._name(sid), **{k: v for k, v in style.items()
                                                                              if k != "width"},
                             **({"line_width_pt": _round(style["width"] * PT_PER_LINE_UNIT, 3)} if "width" in style else {})})
        return ToolResult(_ok(changed=done, warnings=warnings), summary=f"{len(done)} spekter")

    def _t_arrange_spectra(self, layout=None, bottom_to_top=None, offset=None, gap=None, scale_mode=None,
                           spectrum=None):
        state = self.state
        warnings = []
        if bottom_to_top:
            order = self.ids(bottom_to_top, default_all=False)
            rest = [s.id for s in state.spectra if s.id not in order]
            by_id = {s.id: s for s in state.spectra}
            state._spectra = [by_id[sid] for sid in order + rest]
            self._update("_plot", {"reverse_overlay_order": False})
            if rest:
                warnings.append("Spectra not listed stay above the listed ones: "
                                + ", ".join(self.ref(s) for s in rest))
        if scale_mode is not None:
            if scale_mode not in {"common", "full"}:
                raise ToolError("scale_mode must be common or full.")
            self._update("_plot", {"scale_mode": scale_mode})
        layout = layout or ("stacked" if offset is not None or gap is not None else None)
        if layout == "single":
            sid = self._one(spectrum) if spectrum else state.active_spectrum_id or state.spectra[0].id
            state._active_spectrum_id = sid
            self._update("_plot", {"show_all_spectra": False})
        elif layout in {"stacked", "overlay"}:
            changes = {"show_all_spectra": True}
            if layout == "overlay":
                changes["stack_offset"] = 0.0
            self._update("_plot", changes)
            if layout == "stacked":
                if offset is not None and str(offset).lower() != "auto":
                    value = _number(offset, "offset", 0, None, warnings)
                    self.offset_gap = None
                else:
                    gap_value = 0.10 if gap is None else _number(gap, "gap", 0, 3, warnings)
                    value = self._auto_offset(gap_value)
                    self.offset_gap = gap_value
                self._update("_plot", {"stack_offset": float(value)})
        elif layout is not None:
            raise ToolError("layout must be stacked, overlay or single.")
        plotted = [self.ref(s.id) for s in self._plotted()]
        return ToolResult(_ok(layout=layout or "unchanged", stack_offset=_round(state.plot.stack_offset),
                              plotted_bottom_to_top=plotted, warnings=warnings),
                          summary=f"{layout or 'pořadí'} · offset {_round(state.plot.stack_offset, 3)}")

    def _auto_offset(self, gap: float) -> float:
        from core.view import stack_offset, view_y

        plot = self.state.plot
        peaks = self.state.peaks_settings
        if peaks.enabled and peaks.show_labels and any(
                self.state.peaks_auto.get(s.id) or self.state.peaks_manual.get(s.id) for s in self._plotted()):
            # Room for peak labels above each curve (the export also separates exactly).
            gap += 0.35 if abs(np.sin(np.radians(peaks.label_angle_deg))) > 0.5 else 0.15
        curves = [(x, view_y(y, plot.scale_mode))
                  for x, y in (self._xy(spec.id) for spec in self._plotted())]
        visible = (plot.x_min, plot.x_max) if plot.x_min is not None and plot.x_max is not None else None
        return stack_offset(curves, gap, visible)

    def _refit_offset(self, warnings) -> None:
        """Processing can change the Y scale by orders of magnitude (normalise,
        baseline); keep a stacked layout readable instead of leaving an offset
        that flattens or overlaps the curves."""
        plot = self.state.plot
        if not plot.show_all_spectra or not plot.stack_offset or len(self._plotted()) < 2:
            return
        gap = self.offset_gap if self.offset_gap is not None else 0.10
        needed = self._auto_offset(gap)
        if self.offset_gap is not None or not 0.5 * needed <= plot.stack_offset <= 4 * needed:
            old = plot.stack_offset
            self._update("_plot", {"stack_offset": float(needed)})
            if abs(old - needed) > 1e-9 * max(1.0, abs(old)):
                warnings.append(f"Stack offset adapted to the new Y scale: {old:.4g} → {needed:.4g}.")

    # ── peaks ─────────────────────────────────────────────────────────────

    def _region(self, x, x_min, x_max):
        plot = self.state.plot
        low = x_min if x_min is not None else (plot.x_min if plot.x_min is not None and plot.x_max is not None else None)
        high = x_max if x_max is not None else (plot.x_max if plot.x_min is not None and plot.x_max is not None else None)
        low = float(x.min()) if low is None else _number(low, "x_min")
        high = float(x.max()) if high is None else _number(high, "x_max")
        return min(low, high), max(low, high)

    def _t_detect_peaks(self, spectra=None, top_n=8, relative_prominence=None, min_distance=None,
                        polarity="auto", x_min=None, x_max=None, replace=True):
        from core.ai_client import _band_summary
        from core.peak_detection import detect_peaks, detected_to_peaks
        from app.state import LABEL_OFFSETS

        state = self.state
        ids = self.ids(spectra)
        warnings = []
        top_n = _number(top_n, "top_n", 1, 60, warnings, True)
        replace = _bool(replace, "replace")
        report = []
        for sid in ids:
            spec = self._spectrum(sid)
            x, y = self._xy(sid)
            low, high = self._region(x, x_min, x_max)
            mask = (x >= low) & (x <= high)
            if np.count_nonzero(mask) < 5:
                warnings.append(f"{self.ref(sid)} has no data in {low:g}–{high:g}; skipped.")
                continue
            kind = spec.meta.get("y_kind", "intensity")
            pol = polarity if polarity in {"max", "min", "both"} else (
                "min" if str(kind).startswith("transmittance") else "max")
            step = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
            fwhm_points = _band_summary(x[mask], y[mask], kind, limit=10).get("typical_band_fwhm_points") or 8
            # Data ends (e.g. the Rayleigh/notch filter edge) are not bands unless
            # the region was given explicitly; they also must not set the scale.
            edge = max(0.02 * float(x.max() - x.min()), 3 * fwhm_points * step)
            search_low = low if (x_min is not None or low > x.min() + edge) else float(x.min()) + edge
            search_high = high if (x_max is not None or high < x.max() - edge) else float(x.max()) - edge
            inner = (x >= search_low) & (x <= search_high)
            if np.count_nonzero(inner) < 5:
                inner = mask
            span = float(np.ptp(y[inner])) or 1.0
            noise = _band_summary(x[inner], y[inner], kind, limit=1).get("relative_noise", 0.0)
            if relative_prominence is None:
                rel = float(np.clip(max(0.03, 8 * noise), 0.03, 0.5))
            else:
                rel = _number(relative_prominence, "relative_prominence", 0.0005, 1, warnings)
            if min_distance is None:
                distance = max(3 * step, 0.8 * fwhm_points * step)
            else:
                distance = _number(min_distance, "min_distance", 0, None, warnings)
            found = detect_peaks(x, y, min_prominence=rel * span, min_distance_x=distance, max_peaks=top_n,
                                 polarity=pol, x_min=search_low, x_max=search_high)
            peaks = detected_to_peaks(found)
            if spec.x[0] > spec.x[-1]:
                # Detection ran on the ascending copy; indices refer to the stored order.
                for peak in peaks:
                    peak.i = len(spec.x) - 1 - peak.i if peak.i is not None else None
            manual = [p.x for p in state.peaks_manual.get(sid, [])]
            tolerance = max(distance / 2, 2 * step)
            peaks = [p for p in peaks if all(abs(p.x - m) > tolerance for m in manual)]
            if replace:
                for old in state.peaks_auto.get(sid, []):
                    spec.meta.get(LABEL_OFFSETS, {}).pop(old.id, None)
                state.peaks_auto[sid] = peaks
            else:
                existing = state.peaks_auto.get(sid, [])
                state.peaks_auto[sid] = existing + [p for p in peaks if all(abs(p.x - e.x) > tolerance for e in existing)]
            report.append({"spectrum": self.ref(sid), "found": len(peaks),
                           "relative_prominence": _round(rel, 3), "min_distance": _round(distance, 3),
                           "peaks": [_round(p.x, 5) for p in sorted(peaks, key=lambda p: p.x)]})
            if len(found) < top_n:
                warnings.append(f"{self.ref(sid)}: only {len(found)} bands above relative_prominence {rel:.3g}.")
        self._update("_peaks", {"enabled": True, "show_labels": True, "mode": "all"})
        if self.offset_gap is not None:
            self._refit_offset(warnings)
        return ToolResult(_ok(spectra=report, warnings=warnings),
                          summary=f"{sum(r['found'] for r in report)} píků · {len(report)} spekter")

    def _snap(self, sid, value, upward=True, window=None):
        """Nearest band maximum (minimum for transmittance) around ``value``.

        A narrow window first; if the requested position sits on a slope, the
        search widens (up to ~3 band widths) so a label never ends up beside
        its band. Returns the position unchanged when no extremum is found.
        """
        from core.ai_client import _band_summary

        from scipy.signal import savgol_filter

        x, y = self._xy(sid)
        signal = y if upward else -y
        step = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
        narrow = window if window is not None else max(5 * step, 0.002 * float(x.max() - x.min()))
        fwhm_points = _band_summary(x, y, "intensity" if upward else "transmittance_percent",
                                    limit=10).get("typical_band_fwhm_points") or 10
        # Noise has local maxima everywhere: find the band top on a smoothed copy.
        length = int(np.clip(0.6 * fwhm_points, 5, 51)) | 1
        smooth = savgol_filter(signal, length, 2) if len(signal) > length else signal
        for half in (narrow, max(narrow, 1.5 * fwhm_points * step), max(narrow, 3 * fwhm_points * step)):
            index = np.flatnonzero((x >= value - half) & (x <= value + half))
            if len(index) < 3:
                continue
            best = int(np.argmax(smooth[index]))
            if 0 < best < len(index) - 1:
                return float(x[index[best]])
        return float(value)

    def _t_annotate_peaks(self, spectrum, peaks, snap=True):
        from app.models import Peak

        sid = self._one(spectrum)
        spec = self._spectrum(sid)
        if isinstance(peaks, dict):
            peaks = [peaks]
        if not isinstance(peaks, list) or not peaks:
            raise ToolError("peaks must be a list of {x, label}.")
        x, _ = self._xy(sid)
        upward = not str(spec.meta.get("y_kind", "")).startswith("transmittance")
        step = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
        warnings, done = [], []
        state = self.state
        for item in peaks:
            if isinstance(item, (int, float)):
                item = {"x": item}
            value = _number(item.get("x"), "x")
            if not x.min() <= value <= x.max():
                warnings.append(f"x={value:g} is outside {self.ref(sid)} ({x.min():g}–{x.max():g}); skipped.")
                continue
            position = self._snap(sid, value, upward) if _bool(snap, "snap") else value
            if abs(position - value) > 3 * step:
                warnings.append(f"x={value:g} is on a band slope; label moved to the band maximum at {position:.1f}.")
            label = item.get("label")
            label = None if label in (None, "") else str(label)[:200]
            if label is not None and re.fullmatch(r"\s*[-−]?\d+(?:[.,]\d+)?\s*", label):
                # A bare number is a position: it must show where the band of THIS
                # spectrum is, not a value copied from a reference figure.
                if abs(float(label.replace(",", ".").replace("−", "-")) - position) > 0.5:
                    warnings.append(f"label {label.strip()} replaced by the measured position {position:.0f}.")
                label = None
            existing = [p for p in state.peaks_auto.get(sid, []) + state.peaks_manual.get(sid, [])
                        if abs(p.x - position) <= max(3 * step, 1e-9)]
            if existing:
                existing[0].label = label if label is not None else existing[0].label
                done.append({"x": _round(existing[0].x, 6), "label": existing[0].label, "updated": True})
                continue
            index = int(np.argmin(np.abs(np.asarray(spec.x) - position)))
            peak = Peak(x=float(position), source="manual", label=label, i=index,
                        kind="max" if upward else "min")
            state.peaks_manual.setdefault(sid, []).append(peak)
            done.append({"x": _round(position, 6), "label": label})
        self._update("_peaks", {"enabled": True, "show_labels": True, "mode": "all"})
        return ToolResult(_ok(spectrum=self.ref(sid), labels=done, warnings=warnings),
                          summary=f"{len(done)} popisků · {self.ref(sid)}")

    def _t_remove_peaks(self, spectra=None, x_values=None, all=None, keep_top_n=None):  # noqa: A002
        from app.state import LABEL_OFFSETS

        state = self.state
        ids = self.ids(spectra)
        everything = _bool(all, "all") if all is not None else False
        removed = 0
        for sid in ids:
            spec = self._spectrum(sid)
            offsets = spec.meta.get(LABEL_OFFSETS, {})
            if everything:
                removed += len(state.peaks_auto.pop(sid, [])) + len(state.peaks_manual.pop(sid, []))
                spec.meta.pop(LABEL_OFFSETS, None)
                continue
            if keep_top_n is not None:
                keep = _number(keep_top_n, "keep_top_n", 0, 1000, None, True)
                auto = sorted(state.peaks_auto.get(sid, []), key=lambda p: -(p.prominence or 0))
                for peak in auto[keep:]:
                    offsets.pop(peak.id, None)
                removed += max(0, len(auto) - keep)
                state.peaks_auto[sid] = sorted(auto[:keep], key=lambda p: p.x)
            for value in x_values or []:
                value = _number(value, "x")
                candidates = [(abs(p.x - value), store, p) for store in (state.peaks_auto, state.peaks_manual)
                              for p in store.get(sid, [])]
                if not candidates:
                    continue
                _, store, peak = min(candidates, key=lambda item: item[0])
                x, _ = self._xy(sid)
                step = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
                if abs(peak.x - value) > max(10 * step, 5):
                    continue
                store[sid] = [p for p in store[sid] if p.id != peak.id]
                offsets.pop(peak.id, None)
                removed += 1
        if not (everything or keep_top_n is not None or x_values):
            raise ToolError("Say what to remove: all=true, x_values=[…] or keep_top_n.")
        return ToolResult(_ok(removed=removed), summary=f"odebráno {removed}")

    def _t_set_peak_labels(self, font_size_pt=None, angle_deg=None, bold=None, italic=None, color=None,
                           leader_lines=None, leader_color=None, leader_width_pt=None, markers=None, decimals=None,
                           show_labels=None, shown_on=None):
        from core.colors import parse_color

        warnings = []
        changes = {}
        if font_size_pt is not None:
            changes["label_font_size"] = int(round(_number(font_size_pt, "font_size_pt", 5, 16, warnings)
                                                   * FONT_UNITS_PER_PT))
        if angle_deg is not None:
            changes["label_angle_deg"] = _number(angle_deg, "angle_deg", -180, 180, warnings)
        flags = {"label_bold": ("bold", bold), "label_italic": ("italic", italic),
                 "show_leader_lines": ("leader_lines", leader_lines), "show_markers": ("markers", markers),
                 "show_labels": ("show_labels", show_labels)}
        for target, (key, value) in flags.items():
            if value is not None:
                changes[target] = _bool(value, key)
        if color is not None:
            if str(color).strip().lower() in {"trace", "curve", "spectrum"}:
                changes["label_color_mode"] = "trace"
            else:
                changes.update(label_color_mode="custom", label_color=parse_color(color))
        if leader_color is not None:
            if str(leader_color).strip().lower() in {"trace", "curve", "spectrum"}:
                changes["leader_color_mode"] = "trace"
            else:
                changes.update(leader_color_mode="custom", leader_color=parse_color(leader_color))
        if leader_width_pt is not None:
            changes["leader_line_width"] = max(1, int(round(_number(leader_width_pt, "leader_width_pt", 0.4, 4,
                                                                    warnings) / PT_PER_LINE_UNIT)))
        if decimals is not None:
            changes["decimals"] = _number(decimals, "decimals", 0, 4, warnings, True)
        if shown_on is not None:
            if shown_on not in {"all", "active"}:
                raise ToolError("shown_on must be all or active.")
            changes["mode"] = shown_on
        if not changes:
            raise ToolError("No label property given.")
        self._update("_peaks", changes)
        return ToolResult(_ok(changed=sorted(changes), warnings=warnings), summary=", ".join(sorted(changes)))

    # ── axes and style ────────────────────────────────────────────────────

    def _t_set_axes(self, x_label=None, y_label=None, x_min=None, x_max=None, y_min=None, y_max=None,
                    auto_x=None, auto_y=None, invert_x=None, show_x_values=None, show_y_values=None,
                    x_tick_marks=None, y_tick_marks=None, axis_title_bold=None, axis_title_italic=None,
                    tick_labels_bold=None, tick_labels_italic=None, tick_direction=None, mirror_ticks=None):
        state = self.state
        warnings = []
        graphics, plot = {}, {}
        for key, value in (("x_label", x_label), ("y_label", y_label)):
            if value is not None:
                text = str(value).strip()
                if len(text) > 300:
                    raise ToolError(f"{key} is too long.")
                graphics[key] = text
        flags = {"show_x_tick_labels": ("show_x_values", show_x_values),
                 "show_y_tick_labels": ("show_y_values", show_y_values),
                 "show_x_tick_marks": ("x_tick_marks", x_tick_marks), "show_y_tick_marks": ("y_tick_marks", y_tick_marks),
                 "axis_label_bold": ("axis_title_bold", axis_title_bold),
                 "axis_label_italic": ("axis_title_italic", axis_title_italic),
                 "tick_label_bold": ("tick_labels_bold", tick_labels_bold),
                 "tick_label_italic": ("tick_labels_italic", tick_labels_italic),
                 "mirror_ticks": ("mirror_ticks", mirror_ticks)}
        for target, (key, value) in flags.items():
            if value is not None:
                graphics[target] = _bool(value, key)
        if tick_direction is not None:
            if tick_direction not in {"out", "in", "inout"}:
                raise ToolError("tick_direction must be out, in or inout.")
            graphics["tick_direction"] = tick_direction
        if invert_x is not None:
            plot["invert_x"] = _bool(invert_x, "invert_x")
        plotted = self._plotted() or state.spectra
        xs = [self._xy(s.id)[0] for s in plotted]
        data_low, data_high = min(float(x.min()) for x in xs), max(float(x.max()) for x in xs)
        if auto_x:
            plot.update(x_min=None, x_max=None)
        elif x_min is not None or x_max is not None:
            current_low = state.plot.x_min if state.plot.x_min is not None else data_low
            current_high = state.plot.x_max if state.plot.x_max is not None else data_high
            low = _number(x_min, "x_min") if x_min is not None else current_low
            high = _number(x_max, "x_max") if x_max is not None else current_high
            # One given bound beyond the other current one: extend to the data instead of swapping.
            if x_max is None and low >= high:
                high = data_high
            if x_min is None and high <= low:
                low = data_low
            if low > high:
                low, high = high, low
                warnings.append("x_min and x_max swapped (use invert_x to reverse the axis direction).")
            if low == high:
                raise ToolError("x_min and x_max must differ.")
            if high < data_low or low > data_high:
                raise ToolError(f"X range {low:g}–{high:g} contains no data; plotted data span "
                                f"{data_low:g}–{data_high:g}.")
            if low < data_low or high > data_high:
                warnings.append(f"Part of the X range has no data (data span {data_low:g}–{data_high:g}).")
            plot.update(x_min=low, x_max=high)
        if auto_y:
            plot.update(y_min=None, y_max=None)
        elif y_min is not None or y_max is not None:
            if y_min is None or y_max is None:
                raise ToolError("Give both y_min and y_max (or auto_y=true).")
            low, high = sorted((_number(y_min, "y_min"), _number(y_max, "y_max")))
            if low == high:
                raise ToolError("y_min and y_max must differ.")
            plot.update(y_min=low, y_max=high)
        if not graphics and not plot:
            raise ToolError("No axis property given.")
        if graphics:
            self._update("_graphics", graphics)
        if plot:
            self._update("_plot", plot)
        return ToolResult(_ok(changed=sorted(graphics) + sorted(plot), warnings=warnings),
                          summary=", ".join(sorted(graphics) + sorted(plot)))

    def _t_set_style(self, font_family=None, axis_title_pt=None, tick_label_pt=None, curve_line_width_pt=None,
                     axis_line_width_pt=None, frame=None, grid=None, grid_color=None, axis_color=None,
                     background=None, palette=None, curve_names=None, curve_name_bold=None,
                     curve_name_italic=None, export_width_px=None, export_height_px=None):
        from core.colors import parse_color
        from core.presentation import PALETTES

        warnings = []
        changes = {}
        if font_family is not None:
            changes["font_family"] = _font(font_family, warnings)
        for key, target, low, high, value in (("axis_title_pt", "base_font_size", 6, 24, axis_title_pt),
                                              ("tick_label_pt", "tick_font_size", 5, 20, tick_label_pt)):
            if value is not None:
                changes[target] = int(round(_number(value, key, low, high, warnings) * FONT_UNITS_PER_PT))
        for key, target, value in (("curve_line_width_pt", "trace_line_width", curve_line_width_pt),
                                   ("axis_line_width_pt", "axis_line_width", axis_line_width_pt)):
            if value is not None:
                pt = _number(value, key, PT_PER_LINE_UNIT, 4, warnings)
                units = max(1, int(round(pt / PT_PER_LINE_UNIT)))
                if abs(units * PT_PER_LINE_UNIT - pt) > 0.05:
                    warnings.append(f"{key} {pt:g} pt stored as {units * PT_PER_LINE_UNIT:g} pt (0.4 pt steps; "
                                    "per-spectrum widths in set_spectra are exact).")
                changes[target] = units
        if frame is not None:
            if frame not in {"open", "box"}:
                raise ToolError("frame must be open or box.")
            changes["frame_mode"] = frame
        if grid is not None:
            changes["show_grid"] = _bool(grid, "grid")
        if grid_color is not None:
            changes["grid_color"] = parse_color(grid_color)
        if axis_color is not None:
            changes["axis_line_color"] = parse_color(axis_color)
        if background is not None:
            if background not in {"white", "dark"}:
                raise ToolError("background must be white or dark.")
            changes["plot_canvas"] = background
        if palette is not None:
            if palette not in PALETTES:
                raise ToolError(f"Unknown palette {palette!r}. Use one of {', '.join(PALETTES)}, or set exact "
                                "colours with set_spectra (suggest_colors samples any matplotlib colormap).")
            changes["palette"] = palette
        if curve_names is not None:
            if curve_names not in {"beside", "inside", "none"}:
                raise ToolError("curve_names must be beside, inside or none.")
            changes["inline_spectrum_labels"] = curve_names != "none"
            if curve_names != "none":
                changes["spectrum_label_position"] = "inside" if curve_names == "inside" else "right"
        for key, target, value in (("curve_name_bold", "spectrum_label_bold", curve_name_bold),
                                   ("curve_name_italic", "spectrum_label_italic", curve_name_italic)):
            if value is not None:
                changes[target] = _bool(value, key)
        for key, target, value in (("export_width_px", "export_width", export_width_px),
                                   ("export_height_px", "export_height", export_height_px)):
            if value is not None:
                changes[target] = _number(value, key, 300, 8000, warnings, True)
        if not changes:
            raise ToolError("No style property given.")
        self._update("_graphics", changes)
        return ToolResult(_ok(changed=sorted(changes), warnings=warnings), summary=", ".join(sorted(changes)))

    def _t_suggest_colors(self, laser_wavelengths_nm=None, palette=None, count=None):
        from core.colors import palette_colors, wavelength_color

        result = {}
        if laser_wavelengths_nm:
            result["laser"] = {f"{_number(nm, 'nm'):g}": wavelength_color(_number(nm, "nm"))
                               for nm in laser_wavelengths_nm}
        if palette:
            result["palette"] = palette_colors(str(palette), int(count or len(self.state.spectra) or 1))
        if not result:
            raise ToolError("Give laser_wavelengths_nm and/or palette.")
        return ToolResult(_ok(**result), summary="barvy")

    # ── rendering and checking ────────────────────────────────────────────

    def figure_report(self, x_min=None, x_max=None):
        """(PNG bytes, report dict) of the publication figure of the staged state."""
        from core.figure import collisions, figure_spec, render, to_png

        state = self.state
        if not state.spectra:
            raise ToolError("No spectra are loaded.")
        spec = figure_spec(state)
        if not spec.curves:
            raise ToolError("All spectra are hidden; make at least one visible (set_spectra visible=true).")
        if x_min is not None and x_max is not None:
            spec.x_limits = tuple(sorted((_number(x_min, "x_min"), _number(x_max, "x_max"))))
        width = int(self.render_size[0] if self.render_size else state.graphics.export_width)
        height = int(self.render_size[1] if self.render_size else state.graphics.export_height)
        width, height = max(300, min(width, 8000)), max(300, min(height, 8000))
        fig = render(spec, width, height, dpi=300)
        png = _downscale_png(to_png(fig), 1600)
        plotted = self._plotted()
        counts = getattr(fig, "_speclab_label_counts", [(0, len(c.peaks)) for c in spec.curves])
        curves = []
        for spec_item, curve, (shown, total) in zip(plotted, spec.curves, counts):
            entry = {"spectrum": self.ref(spec_item.id), "name": self._name(spec_item.id), "color": curve.color,
                     "offset_in_figure": _round(curve.offset)}
            if total:
                entry["labels_shown"] = shown
                if shown < total:
                    entry["labels_hidden_for_space"] = total - shown
            curves.append(entry)
        issues = []
        hidden = sum(total - shown for shown, total in counts)
        if hidden:
            issues.append(f"{hidden} labels hidden because they would overlap (reduce top_n, label font size, "
                          "or widen export_width_px).")
        layout = "single" if not state.plot.show_all_spectra else ("stacked" if state.plot.stack_offset else "overlay")
        y_low, y_high = fig.axes[0].get_ylim()
        x_low, x_high = sorted(fig.axes[0].get_xlim())
        for curve in spec.curves:
            inside = (curve.x >= x_low) & (curve.x <= x_high)
            visible_height = float(np.ptp(curve.y[inside])) if np.count_nonzero(inside) > 1 else 0.0
            fraction = visible_height / ((y_high - y_low) or 1.0)
            if fraction < 0.04:
                issues.append(f"{curve.name} is almost flat in the figure ({fraction:.1%} of the plot height); "
                              "the stack offset or Y limits do not fit the data scale — call "
                              "arrange_spectra(layout='stacked') or set_axes(auto_y=true).")
        for lower, upper in zip(spec.curves, spec.curves[1:]):
            if layout != "stacked":
                break
            lo = max(lower.x.min(), upper.x.min())
            hi = min(lower.x.max(), upper.x.max())
            if hi <= lo:
                continue
            grid = np.linspace(lo, hi, 800)
            a = np.interp(grid, *_ascending(lower.x, lower.y)) + lower.offset
            b = np.interp(grid, *_ascending(upper.x, upper.y)) + upper.offset
            if np.any(b < a):
                issues.append(f"{upper.name} overlaps {lower.name} below it; increase the stack offset.")
        clashes = collisions(fig)
        if clashes["label_curve"]:
            sample = ", ".join(f"'{label}' of {spec.curves[c].name} hits {spec.curves[o].name}"
                               for label, c, o in clashes["label_curve"][:4])
            issues.append(f"{len(clashes['label_curve'])} peak labels touch a neighbouring spectrum ({sample}); "
                          "increase the stack offset/gap, lower top_n or the label font size.")
        if clashes["label_label"]:
            issues.append(f"{len(clashes['label_label'])} pairs of labels of different spectra overlap.")
        if any(c.peaks for c in spec.curves) and not state.peaks_settings.show_labels:
            issues.append("Peak labels exist but show_labels is false.")
        if len(spec.curves) > 1:
            low, high = spec.x_limits or (min(c.x.min() for c in spec.curves), max(c.x.max() for c in spec.curves))
            heights = []
            for curve in spec.curves:
                inside = (curve.x >= low) & (curve.x <= high)
                heights.append(float(np.ptp(curve.y[inside])) if np.count_nonzero(inside) > 1 else 0.0)
            tallest = max(heights) or 1.0
            small = [f"{c.name} ({h / tallest:.0%})" for c, h in zip(spec.curves, heights) if h < 0.15 * tallest]
            if small:
                issues.append("Some spectra are tiny compared with the tallest: " + ", ".join(small)
                              + ". For comparison normalise them (process normalize max) or use scale_mode full.")
            labelled = [c.name for c in spec.curves if c.peaks]
            unlabelled = [c.name for c in spec.curves if not c.peaks]
            if labelled and unlabelled and state.peaks_settings.enabled:
                issues.append("Spectra without peak labels: " + ", ".join(unlabelled) + ".")
        if layout == "stacked" and any("almost flat" in i for i in issues) and clashes["label_curve"]:
            issues.append(f"The stacked figure is too crowded vertically for {len(spec.curves)} spectra with "
                          f"their labels: increase export_height_px (now {height}, try ~{int(height * 1.7)}), "
                          "label fewer bands (top_n 3) or use smaller labels.")
        long_names = [c.name for c in spec.curves if len(c.name) > 28]
        if spec.show_names and long_names:
            issues.append(f"Curve names are long (e.g. {long_names[0]!r}) and get shortened in the figure; "
                          "give short names with set_spectra name (e.g. '785 nm', '633 nm · 1 %').")
        report = {"canvas_px": [width, height], "layout": layout, "x_label": spec.x_label, "y_label": spec.y_label,
                  "x_limits": list(spec.x_limits) if spec.x_limits else "auto", "curves": curves,
                  "issues": issues}
        return png, report

    def _t_render_figure(self, x_min=None, x_max=None):
        png, report = self.figure_report(x_min, x_max)
        self.renders += 1
        if x_min is None:
            self.changes_since_render = 0
        return ToolResult(_ok(**report, note="The rendered image follows in the next message."
                              ), image=png, summary=f"vykresleno · {len(report['issues'])} upozornění")

    # ── references ────────────────────────────────────────────────────────

    def _attachment(self, ref) -> Attachment:
        key = str(ref).strip().upper()
        if key not in self.attachments:
            options = ", ".join(f"{a.id} ({a.name})" for a in self.attachments.values()) or "none"
            raise ToolError(f"Unknown attachment {ref!r}. Attachments: {options}.")
        return self.attachments[key]

    def _t_get_reference(self, attachment):
        item = self._attachment(attachment)
        info = {"id": item.id, "kind": item.kind, "name": item.name}
        if item.description:
            info["description"] = item.description
        if item.kind in {"project", "spectra"} and item.state is not None:
            reference = Toolbox(item.state, {f"R{i + 1}": s.id for i, s in enumerate(item.state.spectra)})
            summary = reference.workspace()
            for entry in summary["spectra"]:
                sid = reference.aliases[entry["ref"]]
                entry["processing_recipe"] = item.state.processing_recipe(sid)
                style = next(s for s in item.state.spectra if s.id == sid).meta.get("trace_style", {})
                if style:
                    entry["style"] = style
            info["reference"] = summary
            info["note"] = ("Reference spectra are R1…; the rendered reference figure was shown as an image. "
                            "apply_reference_settings copies its settings exactly.")
        if item.kind == "preset":
            info["presets"] = [{"name": p.name, "settings": {k: v for k, v in p.payload.items()
                                                            if k in {"graphics", "plot", "peaks", "spectral_mode",
                                                                     "pipeline", "series_template"}}}
                               for p in item.presets]
        if item.kind == "image":
            info["note"] = "The image is in the conversation; reproduce its style with the tools."
        return ToolResult(_ok(**info), summary=item.name)

    def _t_apply_reference_settings(self, attachment, parts=None, mapping="order"):
        from core.presets import apply_preset_payload
        from core.project_io import SETTINGS, settings_from_dict

        item = self._attachment(attachment)
        allowed = {"graphics", "plot", "peaks", "styles", "names", "processing", "peaks_positions"}
        parts = set(parts or ["graphics", "plot", "peaks", "styles"])
        if parts - allowed:
            raise ToolError(f"Unknown parts {sorted(parts - allowed)}; allowed {sorted(allowed)}.")
        state = self.state
        if item.kind == "preset":
            if not item.presets:
                raise ToolError("The preset file is empty.")
            apply_preset_payload(state, item.presets[0].payload, apply_recipe="processing" in parts)
            return ToolResult(_ok(applied=f"preset {item.presets[0].name}"), summary=item.presets[0].name)
        if item.kind not in {"project", "spectra"} or item.state is None:
            raise ToolError("Only SpecLab projects, presets and spectra attachments carry exact settings; "
                            "for images reproduce the style with the other tools.")
        reference = item.state
        applied = []
        for key in ("graphics", "plot", "peaks"):
            if key in parts and item.kind == "project":
                attr = SETTINGS[key][0]
                current = asdict(getattr(state, attr))
                values = asdict(getattr(reference, attr))
                if key == "plot":
                    # Y limits belong to the reference's intensities; X limits only
                    # transfer when they still show data.
                    values = {**values, "y_min": None, "y_max": None}
                    if not _limits_fit(values, state):
                        values.update(x_min=current["x_min"], x_max=current["x_max"])
                if key == "peaks":
                    values = {**values, "enabled": current["enabled"] or values["enabled"]}
                setattr(state, attr, settings_from_dict(SETTINGS[key][1], values))
                applied.append(key)
        pairs = _pair_spectra(reference.spectra, state.spectra, mapping)
        for ref_spec, spec in pairs:
            if "styles" in parts and ref_spec.meta.get("trace_style"):
                spec.meta["trace_style"] = copy.deepcopy(ref_spec.meta["trace_style"])
            if "names" in parts:
                spec.name = ref_spec.name
            if "processing" in parts:
                recipe = reference.processing_recipe(ref_spec.id)
                state.reset_processing([spec.id])
                if recipe:
                    adjusted = []
                    x, _ = self._xy(spec.id)
                    for op in recipe:
                        op = copy.deepcopy(op)
                        if op["op"] in {"crop", "interpolate"}:
                            op["params"]["min"] = max(op["params"]["min"], float(x.min()))
                            op["params"]["max"] = min(op["params"]["max"], float(x.max()))
                        adjusted.append(op)
                    state.apply_operations(adjusted, [spec.id], source="ai", label="AI: recept ze vzoru")
            if "peaks_positions" in parts:
                positions = [p.x for p in reference.peaks_auto.get(ref_spec.id, []) +
                             reference.peaks_manual.get(ref_spec.id, [])]
                labels = {p.x: p.label for p in reference.peaks_manual.get(ref_spec.id, [])}
                if positions:
                    self._t_annotate_peaks(self.ref(spec.id), [{"x": v, "label": labels.get(v)} for v in positions])
        for key in ("styles", "names", "processing", "peaks_positions"):
            if key in parts:
                applied.append(key)
        if "plot" in parts and item.kind == "project":
            order = [spec.id for _ref, spec in pairs]
            rest = [s.id for s in state.spectra if s.id not in order]
            by_id = {s.id: s for s in state.spectra}
            state._spectra = [by_id[sid] for sid in order + rest]
        return ToolResult(_ok(applied=applied, pairs=[[r.name, self.ref(s.id)] for r, s in pairs]),
                          summary=", ".join(applied))

    def _t_undo_last_change(self):
        if not self.checkpoints:
            raise ToolError("Nothing to undo in this session.")
        name, before = self.checkpoints.pop()
        self.state._restore(before)
        self.changes_since_render += 1
        return ToolResult(_ok(undone=name), summary=TOOL_TITLES.get(name, name))

    def _t_finish(self, summary=""):
        return ToolResult(_ok(), finished=True, summary=str(summary)[:4000])


def _ascending(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    return (x, y) if x[-1] >= x[0] else (x[::-1], y[::-1])


def _limits_fit(values, state) -> bool:
    if values.get("x_min") is None or values.get("x_max") is None:
        return True
    for spec in state.spectra:
        x = np.asarray(spec.x, dtype=float)
        if x.min() < values["x_max"] and x.max() > values["x_min"]:
            return True
    return False


def _pair_spectra(reference, current, mapping):
    if mapping == "name":
        names = {s.name.lower(): s for s in current}
        pairs, used = [], set()
        for ref in reference:
            target = names.get(ref.name.lower())
            if target is not None and target.id not in used:   # each spectrum once
                used.add(target.id)
                pairs.append((ref, target))
        return pairs
    return list(zip(reference, current))


_FONT_ALIASES = {"helvetica": "Helvetica", "arial": "Arial", "times": "Times New Roman",
                 "times new roman": "Times New Roman", "courier": "Courier New", "inter": "Inter"}


def _font(name, warnings) -> str:
    from matplotlib import font_manager

    text = str(name).strip()
    wanted = _FONT_ALIASES.get(text.lower(), text)
    available = {f.name for f in font_manager.fontManager.ttflist}
    if wanted in available or wanted in {"Arial", "Inter", "Times New Roman", "Courier New"}:
        return wanted
    lowered = {n.lower(): n for n in available}
    if wanted.lower() in lowered:
        return lowered[wanted.lower()]
    serif = any(word in wanted.lower() for word in ("serif", "times", "garamond", "georgia", "palatino", "cambria"))
    fallback = "Times New Roman" if serif and "sans" not in wanted.lower() else "Arial"
    warnings.append(f"Font {text!r} is not installed; using {fallback}.")
    return fallback


def _downscale_png(data: bytes, max_side: int) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= max_side:
            return data
        scale = max_side / max(image.size)
        resized = image.convert("RGB").resize((round(image.width * scale), round(image.height * scale)),
                                              Image.Resampling.LANCZOS)
        output = io.BytesIO()
        resized.save(output, format="PNG", optimize=True)
        return output.getvalue()
