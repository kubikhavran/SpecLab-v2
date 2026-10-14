"""Publication-quality figure rendering with matplotlib (independent of Qt).

The interactive plot is for exploration; exported figures are typeset here:
centred axis titles, refined ticks and spines, mathtext units, spectrum
names beside their curves and peak labels from ``core.label_layout`` that
never overlap and whose leaders never cross.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from matplotlib import colormaps, rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator, MaxNLocator, ScalarFormatter

from core.label_layout import LabelRequest, LayoutStyle, fits, layout_labels
from core.palettes import get_palette_colors

# Settings sizes were designed for a large canvas; 1/3 maps them to points
# for a ~5 in wide figure (label 32 → 10.7 pt, ticks 30 → 10 pt, peaks 24 → 8 pt).
PT_PER_SETTING = 1 / 3
INK = "#1d2327"
AXIS_INK = "#2b3137"
LEADER = "#9aa1a9"
# Calm, print-safe colours for a few spectra; long series use a sequential map.
REFINED = ["#24557f", "#c0503f", "#2f8a62", "#7a5aa6", "#c88a1e", "#2a96b0", "#9c3d6b", "#5b6168"]
FONT_FALLBACKS = {"Inter": "Helvetica Neue"}
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉₋₊", "0123456789-+")


@dataclass
class Curve:
    name: str
    x: np.ndarray
    y: np.ndarray
    color: str
    offset: float = 0.0
    peaks: list = field(default_factory=list)       # (x, text, importance, upward)


@dataclass
class FigureSpec:
    curves: list
    x_label: str = "X"
    y_label: str = "Y"
    invert_x: bool = False
    x_limits: tuple | None = None
    y_limits: tuple | None = None
    font_family: str = "Arial"
    label_pt: float = 10.5
    tick_pt: float = 9.5
    peak_pt: float = 8.0
    trace_width: float = 1.2
    axis_width: float = 0.8
    frame: str = "open"
    grid: bool = False
    show_y_values: bool = True
    show_x_values: bool = True
    show_names: bool = True
    peak_color_mode: str = "trace"
    peak_color: str = INK
    leader_lines: bool = True
    markers: bool = False
    bold_axis_labels: bool = False


def to_mathtext(text: str) -> str:
    """Units such as cm^{-1}, cm^-1 or cm⁻¹ → mathtext super/subscripts."""
    if "$" in text:
        return text
    text = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)", lambda m: "^{" + m.group(1).translate(_SUPERSCRIPT) + "}", text)
    text = re.sub(r"([₀₁₂₃₄₅₆₇₈₉₋₊]+)", lambda m: "_{" + m.group(1).translate(_SUBSCRIPT) + "}", text)
    pattern = r"([\^_])(?:\{([^}]+)\}|([A-Za-z0-9−+\-]+))"
    return re.sub(pattern, lambda m: f"${m.group(1)}{{{(m.group(2) or m.group(3)).replace('−', '-')}}}$", text)


def typographic(text: str) -> str:
    """Hyphen before a number → true minus sign (−200 mV, −1)."""
    return re.sub(r"(?<![\w.])-(?=\d)", "\u2212", text)


def value_power(low: float, high: float) -> int:
    """Power of ten that turns tiny or huge tick values into short numbers (0 = none).

    0.00083 → −4 (ticks 2…8), 25 000 → 3 (ticks 5…25); 0.01–10 000 stay as they are.
    """
    magnitude = max(abs(low), abs(high))
    if not np.isfinite(magnitude) or magnitude == 0 or 1e-2 <= magnitude < 1e4:
        return 0
    power = int(np.floor(np.log10(magnitude)))
    return power - 1 if magnitude / 10 ** power < 3 else power


def with_multiplier(label: str, power: int) -> str:
    """'Intensity (a.u.)' → 'Intensity (×10^{-4} a.u.)'; without a unit → '… (×10^{-4})'."""
    factor = f"×10^{{{power}}}"
    match = re.match(r"^(.*)\(([^()]*)\)\s*$", label)
    if match:
        return f"{match.group(1)}({factor} {match.group(2)})"
    return f"{label} ({factor})"


def series_colors(palette: str, count: int) -> list:
    if palette == "auto":
        if count <= len(REFINED):
            return REFINED[:count]
        cmap = colormaps["viridis"]
        return [cmap(value) for value in np.linspace(0.08, 0.85, count)]
    colors = get_palette_colors(palette, count) or REFINED
    return [colors[i % len(colors)] for i in range(count)]


def figure_spec(state) -> FigureSpec:
    """Collect what the current view shows into a renderer-independent spec."""
    from app.state import LABEL_OFFSETS  # noqa: F401  (documented: manual offsets are not used)

    plot, graphics, peaks = state.plot, state.graphics, state.peaks_settings
    spectra = list(reversed(state.spectra)) if plot.reverse_overlay_order else list(state.spectra)
    if not plot.show_all_spectra:
        spectra = [state.active_spectrum or spectra[0]] if spectra else []
    colors = series_colors(graphics.palette, len(state.spectra))
    curves = []
    for index, spec in enumerate(spectra):
        color = colors[next(i for i, s in enumerate(state.spectra) if s.id == spec.id)]
        x = np.asarray(spec.x, dtype=float)
        y = np.asarray(state.displayed_y(spec.id), dtype=float)
        transmittance = str(spec.meta.get("y_kind", "")).startswith("transmittance")
        curve = Curve(spec.name, x, y, color, index * plot.stack_offset if plot.show_all_spectra else 0.0)
        if peaks.enabled and peaks.show_labels and (peaks.mode == "all" or spec.id == state.active_spectrum_id):
            median = float(np.median(y))
            for peak in state.peaks_auto.get(spec.id, []) + state.peaks_manual.get(spec.id, []):
                if not min(x[0], x[-1]) <= peak.x <= max(x[0], x[-1]):
                    continue
                py = float(np.interp(peak.x, x, y) if x[-1] > x[0] else np.interp(peak.x, x[::-1], y[::-1]))
                importance = peak.prominence if peak.prominence is not None else abs(py - median)
                text = peak.label or f"{peak.x:.{peaks.decimals}f}"
                curve.peaks.append((float(peak.x), text, float(importance), not (transmittance or peak.kind == "min")))
        curves.append(curve)
    # Offset curves have no common ordinate; their tick values would mislead.
    stacked = plot.show_all_spectra and plot.stack_offset != 0 and len(spectra) > 1
    return FigureSpec(
        curves=curves,
        x_label=graphics.x_label, y_label=graphics.y_label, invert_x=plot.invert_x,
        x_limits=(plot.x_min, plot.x_max) if plot.x_min is not None and plot.x_max is not None else None,
        y_limits=(plot.y_min, plot.y_max) if plot.y_min is not None and plot.y_max is not None else None,
        font_family=FONT_FALLBACKS.get(graphics.font_family, graphics.font_family),
        label_pt=graphics.base_font_size * PT_PER_SETTING,
        tick_pt=graphics.tick_font_size * PT_PER_SETTING,
        peak_pt=peaks.label_font_size * PT_PER_SETTING,
        trace_width=0.4 * graphics.trace_line_width,
        axis_width=0.4 * graphics.axis_line_width,
        # The on-screen grid is a reading aid; figures follow the Appearance setting only.
        frame=graphics.frame_mode, grid=graphics.show_grid,
        show_y_values=graphics.show_y_tick_labels and not stacked,
        show_x_values=graphics.show_x_tick_labels,
        show_names=len(curves) > 1 or graphics.inline_spectrum_labels,
        peak_color_mode=peaks.label_color_mode, peak_color=peaks.label_color,
        leader_lines=peaks.show_leader_lines, markers=False,
        bold_axis_labels=graphics.axis_label_bold,
    )


def _style(spec: FigureSpec) -> dict:
    family = spec.font_family
    return {
        "font.family": "sans-serif" if family not in ("Times New Roman", "Courier New") else "serif",
        "font.sans-serif": [family, "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.serif": [family, "STIX Two Text", "Times New Roman", "DejaVu Serif"],
        "mathtext.fontset": "custom", "mathtext.rm": family, "mathtext.it": f"{family}:italic",
        "mathtext.bf": f"{family}:bold", "mathtext.default": "regular",
        "axes.unicode_minus": True, "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
    }


def _curve_at(curve, x):
    xs, ys = (curve.x, curve.y) if curve.x[-1] > curve.x[0] else (curve.x[::-1], curve.y[::-1])
    return float(np.interp(x, xs, ys)) + curve.offset


def _peak_layout(ax, renderer, curve, texts):
    """Lay out one curve's labels in display space.

    Returns (overflow above axes, overflow below axes, crowded) in pixels.
    """
    scale = ax.figure.dpi / 72.0
    style = LayoutStyle(gap=2.5 * scale, stub=5 * scale, bend_min=5 * scale, bend_max=18 * scale,
                        spacing=1.2 * scale, label_gap=1.2 * scale)
    bbox = ax.get_window_extent(renderer)
    points = ax.transData.transform(np.c_[curve.x, curve.y + curve.offset])
    order = np.argsort(points[:, 0])
    cx, cy = points[order, 0], points[order, 1]
    over_top = over_bottom = 0.0
    crowded = False
    worst = None   # (shift in label widths, key) of the most displaced label
    for upward in (True, False):
        chosen = [k for k in texts if curve.peaks[k][3] == upward]
        if not chosen:
            continue
        sign = 1.0 if upward else -1.0
        requests = []
        for k in chosen:
            px, py = ax.transData.transform((curve.peaks[k][0], _curve_at(curve, curve.peaks[k][0])))
            extent = texts[k].get_window_extent(renderer)
            requests.append(LabelRequest(px, sign * py, extent.width, extent.height, curve.peaks[k][2]))
        placements = layout_labels(requests, cx, sign * cy, bbox.x0, bbox.x1, style)
        crowded = crowded or not fits(placements, requests, bbox.x0, bbox.x1)
        inverse = ax.transData.inverted()
        for k, request, placement in zip(chosen, requests, placements):
            shift = abs(placement.x - request.peak_x) / max(request.width, 1e-9)
            if worst is None or shift > worst[0]:
                worst = (shift, k)
            base = sign * placement.base
            # Rotated text boxes include the descender space beside the digits;
            # shift by half of it so the glyphs sit optically on the leader.
            _, _, descent = renderer.get_text_width_height_descent(
                texts[k].get_text(), texts[k].get_fontproperties(), ismath=False)
            texts[k].set_position(inverse.transform((placement.x + descent / 2, base)))
            texts[k].set_verticalalignment("bottom" if upward else "top")
            texts[k].leader = [inverse.transform((lx, sign * ly)) for lx, ly in placement.leader]
            tip = base + sign * request.height
            margin = 4 * scale   # keep labels clear of the frame and tick marks
            if upward:
                over_top = max(over_top, tip + margin - bbox.y1)
            else:
                over_bottom = max(over_bottom, bbox.y0 + margin - tip)
    return over_top, over_bottom, crowded, worst


# Legibility and calm leaders matter more than labelling every band: labels
# shrink a little at most, and a label pushed far from its band means the
# region is too dense, so its weakest neighbour is left unlabelled.
MIN_PEAK_FRACTION = 0.85
MAX_SHIFT_WIDTHS = 2.5


def render(spec: FigureSpec, width_px: int = 1600, height_px: int = 900, dpi: int = 300,
           transparent: bool = False) -> Figure:
    """Build the figure; save it with ``save(fig, path)``."""
    from core.sampling import with_gap_breaks

    with rc_context(_style(spec)):
        fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
        FigureCanvasAgg(fig)
        fig.patch.set_alpha(0.0 if transparent else 1.0)
        ax = fig.add_subplot(111)
        ax.set_facecolor("none" if transparent else "white")
        weight = "bold" if spec.bold_axis_labels else "normal"
        ax.set_xlabel(to_mathtext(spec.x_label), fontsize=spec.label_pt, color=INK, labelpad=5, fontweight=weight)
        ax.set_ylabel(to_mathtext(spec.y_label), fontsize=spec.label_pt, color=INK, labelpad=7, fontweight=weight)
        for side, spine in ax.spines.items():
            spine.set_linewidth(spec.axis_width)
            spine.set_color(AXIS_INK)
            spine.set_visible(spec.frame == "box" or side in ("left", "bottom"))
        ax.tick_params(axis="both", which="major", direction="out", length=3.5, width=spec.axis_width,
                       color=AXIS_INK, labelcolor=INK, labelsize=spec.tick_pt, pad=3)
        ax.tick_params(axis="both", which="minor", direction="out", length=2.0, width=spec.axis_width * 0.8,
                       color=AXIS_INK)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=7, steps=[1, 2, 2.5, 5, 10]))
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10]))
        ax.ticklabel_format(useOffset=False)   # never "+1e3" offsets on a spectrum axis
        if not spec.show_y_values:
            ax.tick_params(axis="y", which="both", left=False, labelleft=False)
            if len(spec.curves) > 1 and spec.frame != "box":
                ax.spines["left"].set_visible(False)   # offset stacks need no ordinate line
        if not spec.show_x_values:
            ax.tick_params(axis="x", which="both", labelbottom=False)
        if spec.grid:
            ax.grid(True, which="major", color="#e6e8eb", linewidth=0.5)
            ax.set_axisbelow(True)

        lines, xs = [], []
        for curve in spec.curves:
            gx, gy = with_gap_breaks(curve.x, curve.y + curve.offset)
            lines.append(ax.plot(gx, gy, color=curve.color, linewidth=spec.trace_width,
                                 solid_joinstyle="round", solid_capstyle="round", zorder=3)[0])
            xs += [float(np.min(curve.x)), float(np.max(curve.x))]
        x_low, x_high = spec.x_limits or (min(xs), max(xs))
        ax.set_xlim((x_high, x_low) if spec.invert_x else (x_low, x_high))

        def data_limits():
            lows = [float(np.min(c.y + c.offset)) for c in spec.curves]
            highs = [float(np.max(c.y + c.offset)) for c in spec.curves]
            span = max(highs) - min(lows) or 1.0
            return spec.y_limits or (min(lows) - 0.04 * span, max(highs) + 0.06 * span)

        bottom, top = data_limits()
        ax.set_ylim(bottom, top)
        power = value_power(bottom, top) if spec.show_y_values else 0
        if power:
            # 0.0008 or 250000 as tick text looks like raw instrument output: show
            # short numbers and put the factor into the axis title instead.
            formatter = ScalarFormatter(useMathText=True, useOffset=False)
            formatter.set_powerlimits((power, power))
            ax.yaxis.set_major_formatter(formatter)
            ax.yaxis.get_offset_text().set_visible(False)
            ax.yaxis.label.set_text(to_mathtext(with_multiplier(spec.y_label, power)))

        renderer = fig.canvas.get_renderer()
        # Fix the axes geometry first (names included), then lay out labels in it.
        if spec.show_names:
            _name_curves(ax, renderer, spec)
        fig.tight_layout(pad=0.5)
        if spec.show_names:
            # tight_layout may still let long names run past the right edge.
            right = max((t.get_window_extent(renderer).x1 for t in ax._speclab_names), default=0)
            limit = fig.get_window_extent(renderer).x1 - 0.5 * fig.dpi / 72 * 6
            if right > limit:
                box = ax.get_position()
                shrink = (right - limit) / fig.get_window_extent(renderer).width
                ax.set_position([box.x0, box.y0, box.width - shrink, box.height])

        texts = {}
        for c, curve in enumerate(spec.curves):
            for k, (px, text, _importance, upward) in enumerate(curve.peaks):
                color = curve.color if spec.peak_color_mode == "trace" else spec.peak_color
                texts[c, k] = ax.text(px, _curve_at(curve, px), typographic(text), rotation=90, ha="center",
                                      va="bottom" if upward else "top", fontsize=spec.peak_pt,
                                      color=color, zorder=5, clip_on=False)
        stacked = len(spec.curves) > 1 and any(c.offset for c in spec.curves)
        peak_pt = spec.peak_pt
        for _round in range(4 * len(spec.curves) if stacked else 1):
            bottom, top, peak_pt = _layout_all(ax, renderer, spec, texts, peak_pt, bottom, top)
            if not stacked or not _separate(ax, renderer, spec, texts, lines):
                break
            bottom, top = data_limits()
            ax.set_ylim(bottom, top)
        else:   # the last pass moved curves: lay labels out once more
            bottom, top, peak_pt = _layout_all(ax, renderer, spec, texts, peak_pt, bottom, top)
        # The y range grew for labels, so tick labels may have widened: keep the
        # whole axes (titles, ticks, names) inside the canvas, then lay out again.
        for _ in range(3):
            if not _fit_inside(fig, ax, renderer):
                break
            if texts:
                bottom, top, peak_pt = _layout_all(ax, renderer, spec, texts, peak_pt, bottom, top)
        for text in texts.values():
            if spec.leader_lines and getattr(text, "leader", None) is not None:
                points = np.asarray(text.leader)
                ax.plot(points[:, 0], points[:, 1], color=LEADER, linewidth=0.5, zorder=4,
                        solid_joinstyle="round", solid_capstyle="butt", clip_on=False)
        if spec.show_names:
            _name_curves(ax, renderer, spec)
        fig._speclab_dropped_labels = sum(len(c.peaks) for c in spec.curves) - len(texts)
        return fig


def _fit_inside(fig, ax, renderer) -> bool:
    """Shrink the axes if its decorations stick out of the figure; True if moved."""
    pad = 4 * fig.dpi / 72
    canvas = fig.get_window_extent(renderer)
    tight = ax.get_tightbbox(renderer)
    left = max(0.0, canvas.x0 + pad - tight.x0)
    right = max(0.0, tight.x1 - (canvas.x1 - pad))
    below = max(0.0, canvas.y0 + pad - tight.y0)
    above = max(0.0, tight.y1 - (canvas.y1 - pad))
    if max(left, right, below, above) < 0.5:
        return False
    box = ax.get_position()
    ax.set_position([box.x0 + left / canvas.width, box.y0 + below / canvas.height,
                     box.width - (left + right) / canvas.width, box.height - (below + above) / canvas.height])
    return True


def _layout_all(ax, renderer, spec, texts, peak_pt, bottom, top):
    """Lay out all labels, thinning crowded regions and growing the y range."""
    for _ in range(400):
        top_over = bottom_over = 0.0
        thin = None
        for c, curve in enumerate(spec.curves):
            own = {k: texts[c, k] for k in range(len(curve.peaks)) if (c, k) in texts}
            if not own:
                continue
            over = _peak_layout(ax, renderer, curve, own)
            top_over, bottom_over = max(top_over, over[0]), max(bottom_over, over[1])
            if over[2] or (over[3] and over[3][0] > MAX_SHIFT_WIDTHS):
                thin = (c, over[3][1] if over[3] else None)
        if thin is not None:
            if peak_pt > spec.peak_pt * MIN_PEAK_FRACTION:   # slightly smaller first
                peak_pt = max(spec.peak_pt * MIN_PEAK_FRACTION, peak_pt * 0.95)
                for text in texts.values():
                    text.set_fontsize(peak_pt)
                continue
            c, key = thin
            curve = spec.curves[c]
            centre = curve.peaks[key][0] if key is not None else None
            keys = [k for (cc, k) in texts if cc == c]
            if centre is not None:
                # The weakest band near the over-crowded spot loses its label.
                reach = abs(curve.x[-1] - curve.x[0]) * 0.06
                near = [k for k in keys if abs(curve.peaks[k][0] - centre) <= reach] or keys
            else:
                near = keys
            weakest = min(near, key=lambda k: curve.peaks[k][2])
            texts.pop((c, weakest)).remove()
            continue
        if spec.y_limits is not None or (top_over <= 0.5 and bottom_over <= 0.5):
            break
        height = ax.get_window_extent(renderer).height
        per_px = (top - bottom) / height
        if top_over > 0.5:
            top += (top_over + 3) * per_px * 1.15
        if bottom_over > 0.5:
            bottom -= (bottom_over + 3) * per_px * 1.15
        ax.set_ylim(bottom, top)
    return bottom, top, peak_pt


def _separate(ax, renderer, spec, texts, lines) -> bool:
    """Raise upper spectra until curves, labels and leaders of neighbours clear.

    Envelopes are measured per pixel column in display space; returns True if
    any offset changed (the caller then repeats the label layout).
    """
    bbox = ax.get_window_extent(renderer)
    columns = np.arange(np.floor(bbox.x0), np.ceil(bbox.x1) + 1)
    margin = 5 * ax.figure.dpi / 72
    envelopes = []
    for c, curve in enumerate(spec.curves):
        points = ax.transData.transform(np.c_[curve.x, curve.y + curve.offset])
        order = np.argsort(points[:, 0])
        y = np.interp(columns, points[order, 0], points[order, 1], left=np.nan, right=np.nan)
        upper, lower = y.copy(), y.copy()
        for (cc, _k), text in texts.items():
            if cc != c:
                continue
            box = text.get_window_extent(renderer)
            inside = (columns >= box.x0) & (columns <= box.x1)
            upper[inside] = np.fmax(upper[inside], box.y1)
            lower[inside] = np.fmin(lower[inside], box.y0)
        envelopes.append((upper, lower))
    per_px = np.diff(ax.get_ylim())[0] / bbox.height
    changed = False
    for c in range(1, len(spec.curves)):
        overlap = envelopes[c - 1][0] - envelopes[c][1]
        need = np.nanmax(overlap) + margin if np.any(np.isfinite(overlap)) else -1
        if need > 0.5:
            # Raising curves widens the y range, which makes labels taller in
            # data units; a small overshoot avoids many tiny iterations.
            shift = need * per_px * 1.25
            for upper_curve in spec.curves[c:]:
                upper_curve.offset += shift
            changed = True
            break   # remeasure after each raise; labels move with their curves
    if changed:
        from core.sampling import with_gap_breaks

        for line, curve in zip(lines, spec.curves):
            gx, gy = with_gap_breaks(curve.x, curve.y + curve.offset)
            line.set_data(gx, gy)
    return changed


def _name_curves(ax, renderer, spec):
    """Names right of the visually right curve ends, spread so they never touch."""
    for text in getattr(ax, "_speclab_names", []):
        text.remove()
    ax._speclab_names = []
    entries = []
    for curve in spec.curves:
        x, y = curve.x, curve.y + curve.offset
        right = int(np.argmin(x) if spec.invert_x else np.argmax(x))
        window = y[max(right - 5, 0):right + 6]
        _, display_y = ax.transData.transform((x[right], float(np.median(window))))
        entries.append([display_y, curve])
    entries.sort(key=lambda e: e[0])
    height = spec.tick_pt * ax.figure.dpi / 72 * 1.3
    for i in range(1, len(entries)):
        entries[i][0] = max(entries[i][0], entries[i - 1][0] + height)
    inverse = ax.transAxes.inverted()
    for display_y, curve in entries:
        _, axes_y = inverse.transform((0, display_y))
        text = ax.text(1.015, axes_y, typographic(curve.name), transform=ax.transAxes, ha="left", va="center",
                       fontsize=spec.tick_pt, color=curve.color, clip_on=False)
        ax._speclab_names.append(text)


def save(fig: Figure, path: str, transparent: bool = False) -> None:
    fig.savefig(path, dpi=fig.dpi, transparent=transparent, facecolor="none" if transparent else "white")
