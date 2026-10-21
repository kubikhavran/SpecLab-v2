"""Publication-quality figure rendering with matplotlib (independent of Qt).

The interactive plot is for exploration; exported figures are typeset here:
centred axis titles, refined ticks and spines, mathtext units, spectrum
names beside their curves and peak labels from ``core.label_layout`` that
never overlap and whose leaders never cross.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import numpy as np
from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator, MaxNLocator, ScalarFormatter

from core.label_layout import LabelRequest, LayoutStyle, fits, layout_labels, layout_upright_labels
from core.palettes import get_palette_colors
from core.view import view_y, trace_style

# Settings sizes were designed for a large canvas; 1/3 maps them to points
# for a ~5 in wide figure (label 32 → 10.7 pt, ticks 30 → 10 pt, peaks 24 → 8 pt).
PT_PER_SETTING = 1 / 3
INK = "#1d2327"
AXIS_INK = "#2b3137"
LEADER = "#9aa1a9"
# Calm, print-safe colours for a few spectra; long series use a sequential map.
REFINED = [
    "#24557f",
    "#c0503f",
    "#2f8a62",
    "#7a5aa6",
    "#c88a1e",
    "#2a96b0",
    "#9c3d6b",
    "#5b6168",
]
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
    peaks: list = field(default_factory=list)  # (x, text, importance, upward)
    width: float | None = None
    line: str = "solid"
    label_offsets: dict = field(default_factory=dict)


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
    italic_axis_labels: bool = False
    tick_bold: bool = False
    tick_italic: bool = False
    x_marks: bool = True
    y_marks: bool = True
    tick_direction: str = "out"
    mirror_ticks: bool = False
    axis_color: str = AXIS_INK
    grid_color: str = "#e6e8eb"
    grid_width: float = 0.5
    label_angle: float = 90
    label_bold: bool = False
    label_italic: bool = False
    leader_width: float = 0.5
    leader_color_mode: str = "custom"
    leader_color: str = LEADER
    name_bold: bool = False
    name_italic: bool = False
    name_position: str = "right"     # "right" (beside the plot) | "inside" (above curve ends)
    respect_offsets: bool = False   # stack offsets are minimums; collisions still raise spectra
    show_peak_labels: bool = True
    background: str = "white"
    text_color: str = INK


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
    from core.palettes import get_color_for_index

    colors = get_palette_colors(palette, count)
    return [get_color_for_index(colors, i) for i in range(count)]


def figure_spec(state) -> FigureSpec:
    """Collect what the current view shows into a renderer-independent spec."""
    from app.state import LABEL_OFFSETS

    plot, graphics, peaks = state.plot, state.graphics, state.peaks_settings
    spectra = (
        list(reversed(state.spectra))
        if plot.reverse_overlay_order
        else list(state.spectra)
    )
    if plot.show_all_spectra:
        spectra = [s for s in spectra if s.meta.get("trace_style",{}).get("visible",True)]
    if not plot.show_all_spectra:
        spectra = [state.active_spectrum or spectra[0]] if spectra else []
    colors = series_colors(graphics.palette, len(state.spectra))
    curves = []
    for index, spec in enumerate(spectra):
        color = colors[next(i for i, s in enumerate(state.spectra) if s.id == spec.id)]
        x = np.asarray(spec.x, dtype=float)
        y = view_y(state.displayed_y(spec.id), plot.scale_mode)
        transmittance = str(spec.meta.get("y_kind", "")).startswith("transmittance")
        color, width, line = trace_style(spec, color, graphics.trace_line_width)
        curve = Curve(
            spec.name,
            x,
            y,
            color,
            index * plot.stack_offset if plot.show_all_spectra else 0.0,
            width=0.4 * width,
            line=line,
        )
        if peaks.enabled and (
            peaks.mode == "all" or spec.id == state.active_spectrum_id
        ):
            median = float(np.median(y))
            for peak in state.peaks_auto.get(spec.id, []) + state.peaks_manual.get(
                spec.id, []
            ):
                if not min(x[0], x[-1]) <= peak.x <= max(x[0], x[-1]):
                    continue
                py = float(
                    np.interp(peak.x, x, y)
                    if x[-1] > x[0]
                    else np.interp(peak.x, x[::-1], y[::-1])
                )
                importance = (
                    peak.prominence if peak.prominence is not None else abs(py - median)
                )
                text = peak.label or f"{peak.x:.{peaks.decimals}f}"
                key = len(curve.peaks)
                curve.peaks.append(
                    (
                        float(peak.x),
                        text,
                        float(importance),
                        not (transmittance or peak.kind == "min"),
                    )
                )
                if peak.id in spec.meta.get(LABEL_OFFSETS, {}):
                    dx, dy = spec.meta[LABEL_OFFSETS][peak.id]
                    span = (
                        (float(np.ptp(state.displayed_y(spec.id))) or 1.0)
                        if plot.scale_mode == "full"
                        else 1.0
                    )
                    curve.label_offsets[key] = [dx, dy / span]
        curves.append(curve)
    # Offset curves have no common ordinate; their tick values would mislead.
    stacked = plot.show_all_spectra and plot.stack_offset != 0 and len(spectra) > 1
    return FigureSpec(
        curves=curves,
        x_label=graphics.x_label,
        # Full scale is a view of curves scaled 0–1: a generic title says so, a
        # title chosen by the user (or the AI) is kept.
        y_label="Normalized intensity (a.u.)"
        if plot.scale_mode == "full" and graphics.y_label.strip() in {"", "Y", "Intensity (a.u.)"}
        else graphics.y_label,
        invert_x=plot.invert_x,
        x_limits=(plot.x_min, plot.x_max)
        if plot.x_min is not None and plot.x_max is not None
        else None,
        y_limits=(plot.y_min, plot.y_max)
        if plot.y_min is not None and plot.y_max is not None
        else None,
        font_family=FONT_FALLBACKS.get(graphics.font_family, graphics.font_family),
        label_pt=graphics.base_font_size * PT_PER_SETTING,
        tick_pt=graphics.tick_font_size * PT_PER_SETTING,
        peak_pt=peaks.label_font_size * PT_PER_SETTING,
        trace_width=0.4 * graphics.trace_line_width,
        axis_width=0.4 * graphics.axis_line_width,
        # The on-screen grid is a reading aid; figures follow the Appearance setting only.
        frame=graphics.frame_mode,
        grid=graphics.show_grid,
        show_y_values=graphics.show_y_tick_labels and not stacked,
        show_x_values=graphics.show_x_tick_labels,
        show_names=graphics.inline_spectrum_labels,
        peak_color_mode=peaks.label_color_mode,
        peak_color=peaks.label_color,
        leader_lines=peaks.show_leader_lines,
        markers=peaks.show_markers,
        show_peak_labels=peaks.show_labels,
        bold_axis_labels=graphics.axis_label_bold,
        italic_axis_labels=graphics.axis_label_italic,
        tick_bold=graphics.tick_label_bold,
        tick_italic=graphics.tick_label_italic,
        x_marks=graphics.show_x_tick_marks,
        y_marks=graphics.show_y_tick_marks,
        tick_direction=graphics.tick_direction,
        mirror_ticks=graphics.mirror_ticks,
        axis_color="#b5c7c7" if graphics.plot_canvas == "dark" and graphics.axis_line_color == "#000000" else graphics.axis_line_color,
        background="#162629" if graphics.plot_canvas == "dark" else "white",
        text_color="#b5c7c7" if graphics.plot_canvas == "dark" else INK,
        grid_color=graphics.grid_color,
        grid_width=0.4 * graphics.grid_width,
        label_angle=peaks.label_angle_deg,
        label_bold=peaks.label_bold,
        label_italic=peaks.label_italic,
        leader_width=0.4 * peaks.leader_line_width,
        leader_color_mode=peaks.leader_color_mode,
        leader_color=peaks.leader_color,
        name_bold=graphics.spectrum_label_bold,
        name_italic=graphics.spectrum_label_italic,
        name_position=graphics.spectrum_label_position,
        respect_offsets=True,
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
    style = LayoutStyle(
        gap=2.5 * scale,
        stub=5 * scale,
        bend_min=5 * scale,
        bend_max=18 * scale,
        spacing=1.2 * scale,
        label_gap=1.2 * scale,
    )
    bbox = ax.get_window_extent(renderer)
    points = ax.transData.transform(np.c_[curve.x, curve.y + curve.offset])
    order = np.argsort(points[:, 0])
    cx, cy = points[order, 0], points[order, 1]
    over_top = over_bottom = 0.0
    crowded = False
    worst = None  # (shift in label widths, key) of the most displaced label
    for upward in (True, False):
        chosen = [
            k
            for k in texts
            if curve.peaks[k][3] == upward and k not in curve.label_offsets
        ]
        if not chosen:
            continue
        sign = 1.0 if upward else -1.0
        requests = []
        for k in chosen:
            px, py = ax.transData.transform(
                (curve.peaks[k][0], _curve_at(curve, curve.peaks[k][0]))
            )
            extent = texts[k].get_window_extent(renderer)
            requests.append(
                LabelRequest(
                    px, sign * py, extent.width, extent.height, curve.peaks[k][2]
                )
            )
        # Horizontal text stays above its band; vertical text uses shared bends.
        upright = abs(np.sin(np.radians(texts[chosen[0]].get_rotation()))) < 0.5
        placements = (layout_upright_labels if upright else layout_labels)(
            requests, cx, sign * cy, bbox.x0, bbox.x1, style)
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
                texts[k].get_text(), texts[k].get_fontproperties(), ismath=False
            )
            nudge = 0.0 if upright else descent / 2
            texts[k].set_position(inverse.transform((placement.x + nudge, base)))
            texts[k].set_verticalalignment("bottom" if upward else "top")
            texts[k].leader = [
                inverse.transform((lx, sign * ly)) for lx, ly in placement.leader
            ] or None
            tip = base + sign * request.height
            margin = 4 * scale  # keep labels clear of the frame and tick marks
            if upward:
                over_top = max(over_top, tip + margin - bbox.y1)
            else:
                over_bottom = max(over_bottom, bbox.y0 + margin - tip)
    for k, text in texts.items():
        if k not in curve.label_offsets:
            continue
        px = curve.peaks[k][0]
        anchor = (px, _curve_at(curve, px))
        dx, dy = curve.label_offsets[k]
        text.set_position((px + dx, anchor[1] + dy))
        text.leader = [anchor, text.get_position()]
        extent = text.get_window_extent(renderer)
        over_top = max(over_top, extent.y1 + 4 * scale - bbox.y1)
        over_bottom = max(over_bottom, bbox.y0 + 4 * scale - extent.y0)
    return over_top, over_bottom, crowded, worst


# Legibility and calm leaders matter more than labelling every band: labels
# shrink a little at most, and a label pushed far from its band means the
# region is too dense, so its weakest neighbour is left unlabelled.
MIN_PEAK_FRACTION = 0.85
MAX_SHIFT_WIDTHS = 2.5


# rc_context changes global rcParams; the AI agent renders from a worker thread.
_RENDER_LOCK = threading.RLock()


def render(
    spec: FigureSpec,
    width_px: int = 1600,
    height_px: int = 900,
    dpi: int = 300,
    transparent: bool = False,
) -> Figure:
    """Build the figure; save it with ``save(fig, path)``."""
    from core.sampling import with_gap_breaks

    if not spec.curves:
        raise ValueError("Žádné viditelné spektrum k vykreslení.")

    with _RENDER_LOCK, rc_context(_style(spec)):
        fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
        # Generic font families resolve at draw time: saving must use the same
        # rcParams as the layout, otherwise text is drawn in another (wider) font.
        fig._speclab_rc = _style(spec)
        FigureCanvasAgg(fig)
        fig.patch.set_alpha(0.0 if transparent else 1.0)
        fig.patch.set_facecolor(spec.background)
        ax = fig.add_subplot(111)
        axis_style = "italic" if spec.italic_axis_labels else "normal"
        ax.set_facecolor("none" if transparent else spec.background)
        weight = "bold" if spec.bold_axis_labels else "normal"
        ax.set_xlabel(
            to_mathtext(spec.x_label),
            fontsize=spec.label_pt,
            color=spec.text_color,
            labelpad=5,
            fontweight=weight,
            fontstyle=axis_style,
        )
        ax.set_ylabel(
            to_mathtext(spec.y_label),
            fontsize=spec.label_pt,
            color=spec.text_color,
            labelpad=7,
            fontweight=weight,
            fontstyle=axis_style,
        )
        for side, spine in ax.spines.items():
            spine.set_linewidth(spec.axis_width)
            spine.set_color(spec.axis_color)
            spine.set_visible(spec.frame == "box" or side in ("left", "bottom"))
        ax.tick_params(
            axis="both",
            which="major",
            direction="out",
            length=3.5,
            width=spec.axis_width,
            color=spec.axis_color,
            labelcolor=spec.text_color,
            labelsize=spec.tick_pt,
            pad=3,
        )
        ax.tick_params(
            axis="both",
            which="minor",
            direction="out",
            length=2.0,
            width=spec.axis_width * 0.8,
            color=spec.axis_color,
        )
        ax.xaxis.set_major_locator(MaxNLocator(nbins=7, steps=[1, 2, 2.5, 5, 10]))
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 2.5, 5, 10]))
        ax.ticklabel_format(useOffset=False)  # never "+1e3" offsets on a spectrum axis
        if not spec.show_y_values:
            ax.tick_params(axis="y", which="both", left=False, labelleft=False)
            if len(spec.curves) > 1 and spec.frame != "box":
                ax.spines["left"].set_visible(
                    False
                )  # offset stacks need no ordinate line
        if not spec.show_x_values:
            ax.tick_params(axis="x", which="both", labelbottom=False)
        ax.tick_params(axis="x", which="both", bottom=spec.x_marks)
        # Tick marks without values only make sense on a drawn ordinate line.
        ax.tick_params(axis="y", which="both",
                       left=spec.y_marks and (spec.show_y_values or ax.spines["left"].get_visible()))
        ax.tick_params(axis="both", which="both", direction=spec.tick_direction)
        if spec.mirror_ticks and spec.frame == "box":
            ax.tick_params(axis="x", which="both", top=spec.x_marks, labeltop=False)
            ax.tick_params(axis="y", which="both", right=spec.y_marks and ax.spines["left"].get_visible(),
                           labelright=False)
        for tick in ax.get_xticklabels() + ax.get_yticklabels():
            tick.set_fontweight("bold" if spec.tick_bold else "normal")
            tick.set_fontstyle("italic" if spec.tick_italic else "normal")
        if spec.grid:
            ax.grid(
                True, which="major", color=spec.grid_color, linewidth=spec.grid_width
            )
            ax.set_axisbelow(True)

        lines, xs = [], []
        for curve in spec.curves:
            gx, gy = with_gap_breaks(curve.x, curve.y + curve.offset)
            lines.append(
                ax.plot(
                    gx,
                    gy,
                    color=curve.color,
                    linewidth=curve.width
                    if curve.width is not None
                    else spec.trace_width,
                    linestyle={"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}[
                        curve.line
                    ],
                    solid_joinstyle="round",
                    solid_capstyle="round",
                    zorder=3,
                )[0]
            )
            xs += [float(np.min(curve.x)), float(np.max(curve.x))]
        x_low, x_high = spec.x_limits or (min(xs), max(xs))
        ax.set_xlim((x_high, x_low) if spec.invert_x else (x_low, x_high))

        def data_limits():
            # Only what is visible counts: a Rayleigh edge or a solvent band outside
            # the chosen X range must not flatten the shown spectra.
            lows, highs = [], []
            for c in spec.curves:
                inside = (c.x >= x_low) & (c.x <= x_high) & np.isfinite(c.y)
                values = (c.y[inside] if np.count_nonzero(inside) > 1 else c.y) + c.offset
                lows.append(float(np.min(values)))
                highs.append(float(np.max(values)))
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
            right = max(
                (t.get_window_extent(renderer).x1 for t in ax._speclab_names), default=0
            )
            limit = fig.get_window_extent(renderer).x1 - 0.5 * fig.dpi / 72 * 6
            if right > limit:
                box = ax.get_position()
                shrink = (right - limit) / fig.get_window_extent(renderer).width
                ax.set_position([box.x0, box.y0, box.width - shrink, box.height])

        texts = {}
        fig._speclab_texts_live = texts   # inside curve names avoid these labels
        for c, curve in enumerate(spec.curves):
            for k, (px, text, _importance, upward) in enumerate(curve.peaks):
                if not spec.show_peak_labels:
                    continue
                color = (
                    curve.color if spec.peak_color_mode == "trace" else spec.peak_color
                )
                texts[c, k] = ax.text(
                    px,
                    _curve_at(curve, px),
                    typographic(text),
                    rotation=spec.label_angle,
                    ha="center",
                    va="bottom" if upward else "top",
                    fontsize=spec.peak_pt,
                    color=color,
                    fontweight="bold" if spec.label_bold else "normal",
                    fontstyle="italic" if spec.label_italic else "normal",
                    zorder=5,
                    clip_on=False,
                )
        stacked = len(spec.curves) > 1 and any(c.offset for c in spec.curves)
        peak_pt = spec.peak_pt
        # Separation may enlarge the Y range only so far: beyond that the curves
        # would turn into flat lines under labels of fixed size. Remaining
        # collisions are reported (collisions()) instead.
        span_limit = 3.0 * (top - bottom)

        def settle_labels():
            nonlocal bottom, top, peak_pt
            for _round in range(4 * len(spec.curves) if stacked else 1):
                bottom, top, peak_pt = _layout_all(ax, renderer, spec, texts, peak_pt, bottom, top)
                # The chosen stack offset is a minimum: upper spectra are raised only
                # where labels or curves of neighbours would otherwise collide.
                if not stacked or not _separate(ax, renderer, spec, texts, lines, span_limit):
                    return
                bottom, top = data_limits()
                ax.set_ylim(bottom, top)
            # the last pass moved curves: lay labels out once more
            bottom, top, peak_pt = _layout_all(ax, renderer, spec, texts, peak_pt, bottom, top)

        # Labels, curve names and the canvas interact: growing the y range widens the
        # tick labels and names need room, so the axes shrink, which changes the
        # label geometry again. Repeat until nothing moves.
        for _settle in range(4):
            if spec.show_names and spec.name_position == "inside":
                _name_curves(ax, renderer, spec)   # obstacles for the separation
            settle_labels()
            moved = False
            for _ in range(4):
                if spec.show_names:
                    _name_curves(ax, renderer, spec)
                if not _fit_inside(fig, ax, renderer):
                    break
                moved = True
            if not moved:
                break
        # Explicit positions are data-space offsets from the actual peak anchor.
        # Apply after automatic layout so export keeps the scientist's placement.
        for (c, k), text in texts.items():
            curve = spec.curves[c]
            px = curve.peaks[k][0]
            anchor = (px, _curve_at(curve, px))
            if k in curve.label_offsets:
                dx, dy = curve.label_offsets[k]
                text.set_position((anchor[0] + dx, anchor[1] + dy))
                text.leader = [anchor, text.get_position()]
            text.set_rotation(spec.label_angle)
        if spec.markers:
            for curve in spec.curves:
                for px, *_ in curve.peaks:
                    ax.plot(
                        px,
                        _curve_at(curve, px),
                        marker="o",
                        markersize=2.5,
                        color=curve.color,
                        zorder=4,
                    )
        for (c, k), text in texts.items():
            if spec.leader_lines and getattr(text, "leader", None) is not None:
                points = np.asarray(text.leader)
                ax.plot(
                    points[:, 0],
                    points[:, 1],
                    color=spec.curves[c].color
                    if spec.leader_color_mode == "trace"
                    else spec.leader_color,
                    linewidth=spec.leader_width,
                    zorder=4,
                    solid_joinstyle="round",
                    solid_capstyle="butt",
                    clip_on=False,
                )
        if spec.show_names:
            _name_curves(ax, renderer, spec)
            _fit_inside(fig, ax, renderer)
        _thin_x_ticks(ax, renderer, spec)
        fig._speclab_dropped_labels = sum(len(c.peaks) for c in spec.curves) - len(
            texts
        )
        fig._speclab_lines = lines
        fig._speclab_texts = dict(texts)
        # Per curve: (labels shown, labels requested), e.g. for the AI figure check.
        fig._speclab_label_counts = [
            (sum(1 for (cc, _k) in texts if cc == c), len(curve.peaks))
            for c, curve in enumerate(spec.curves)
        ]
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
            if peak_pt > spec.peak_pt * MIN_PEAK_FRACTION:  # slightly smaller first
                peak_pt = max(spec.peak_pt * MIN_PEAK_FRACTION, peak_pt * 0.95)
                for text in texts.values():
                    text.set_fontsize(peak_pt)
                continue
            c, key = thin
            curve = spec.curves[c]
            centre = curve.peaks[key][0] if key is not None else None
            keys = [k for (cc, k) in texts if cc == c and k not in curve.label_offsets]
            if not keys:
                break
            if centre is not None:
                # The weakest band near the over-crowded spot loses its label.
                reach = abs(curve.x[-1] - curve.x[0]) * 0.06
                near = [
                    k for k in keys if abs(curve.peaks[k][0] - centre) <= reach
                ] or keys
            else:
                near = keys
            weakest = min(near, key=lambda k: curve.peaks[k][2])
            texts.pop((c, weakest)).remove()
            continue
        if spec.show_names and spec.name_position == "inside":
            # Names inside the plot need headroom just like peak labels.
            _name_curves(ax, renderer, spec)
            frame_top = ax.get_window_extent(renderer).y1
            margin = 3 * ax.figure.dpi / 72
            for name in getattr(ax, "_speclab_names", []):
                top_over = max(top_over, name.get_window_extent(renderer).y1 + margin - frame_top)
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


def _separate(ax, renderer, spec, texts, lines, span_limit=None) -> bool:
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
        for name in getattr(ax, "_speclab_names", []):
            if getattr(name, "_speclab_curve", None) == c:
                box = name.get_window_extent(renderer)
                inside = (columns >= box.x0) & (columns <= box.x1)
                upper[inside] = np.fmax(upper[inside], box.y1)
        envelopes.append((upper, lower))
    needs = []
    for c in range(1, len(spec.curves)):
        overlap = envelopes[c - 1][0] - envelopes[c][1]
        need = np.nanmax(overlap) + margin if np.any(np.isfinite(overlap)) else 0.0
        needs.append(need if need > 0.5 else 0.0)
    total = sum(needs)
    changed = total > 0
    if changed:
        # Raising curves widens the y range, which shrinks the data per pixel while
        # labels keep their size in pixels. Solve for the final range in one step,
        # R' = R / (1 − Σneed / H), so that every pair gains its pixels at once.
        height = bbox.height
        span = float(np.diff(ax.get_ylim())[0])
        grown = span / max(0.2, 1.0 - total / height)
        if span_limit is not None and grown > span_limit:
            if span >= 0.98 * span_limit:
                return False
            # Use the remaining room proportionally; neighbours may still touch.
            share = (span_limit - span) / (grown - span)
            needs = [need * share for need in needs]
            grown = span_limit
        per_px = grown / height
        lift = 0.0
        for c, need in enumerate(needs, start=1):
            lift += need * per_px * 1.05
            spec.curves[c].offset += lift
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
    if spec.name_position == "inside":
        _name_curves_inside(ax, renderer, spec)
        return
    entries = []
    low, high = sorted(ax.get_xlim())
    for curve in spec.curves:
        x, y = np.asarray(curve.x, dtype=float), np.asarray(curve.y, dtype=float) + curve.offset
        # Anchor at the curve end that is visible at the right edge of the axes.
        inside = (x >= low) & (x <= high)
        if not np.any(inside):
            inside = np.ones_like(x, dtype=bool)
        xs, ys = x[inside], y[inside]
        right = int(np.argmin(xs) if spec.invert_x else np.argmax(xs))
        window = ys[np.argsort(np.abs(xs - xs[right]))[:11]]
        _, display_y = ax.transData.transform((xs[right], float(np.median(window))))
        entries.append([display_y, curve])
    entries.sort(key=lambda e: e[0])
    height = spec.tick_pt * ax.figure.dpi / 72 * 1.3
    for i in range(1, len(entries)):
        entries[i][0] = max(entries[i][0], entries[i - 1][0] + height)
    inverse = ax.transAxes.inverted()
    for display_y, curve in entries:
        _, axes_y = inverse.transform((0, display_y))
        text = ax.text(
            1.015,
            axes_y,
            typographic(curve.name),
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=spec.tick_pt,
            color=curve.color,
            fontweight="bold" if spec.name_bold else "normal",
            fontstyle="italic" if spec.name_italic else "normal",
            clip_on=False,
        )
        _fit_name(text, renderer, 0.30 * ax.figure.get_window_extent(renderer).width, spec.tick_pt)
        ax._speclab_names.append(text)


def _name_curves_inside(ax, renderer, spec):
    """Names inside the plot, right-aligned just above the visible right end of
    each curve and above its own peak labels there (a common journal style)."""
    bbox = ax.get_window_extent(renderer)
    pad = 4 * ax.figure.dpi / 72
    right = bbox.x1 - pad
    texts = getattr(ax.figure, "_speclab_texts_live", {})
    inverse = ax.transAxes.inverted()
    for c, curve in enumerate(spec.curves):
        text = ax.text(0, 0, typographic(curve.name), transform=ax.transAxes, ha="right", va="bottom",
                       fontsize=spec.tick_pt, color=curve.color, clip_on=False,
                       fontweight="bold" if spec.name_bold else "normal",
                       fontstyle="italic" if spec.name_italic else "normal")
        _fit_name(text, renderer, 0.45 * bbox.width, spec.tick_pt)
        width = text.get_window_extent(renderer).width
        points = ax.transData.transform(np.c_[curve.x, curve.y + curve.offset])
        under = (points[:, 0] >= right - width) & (points[:, 0] <= right)
        top = float(np.max(points[under, 1])) if np.any(under) else float(np.median(points[:, 1]))
        for (cc, _k), label in texts.items():
            box = label.get_window_extent(renderer)
            if cc == c and box.x1 > right - width and box.x0 < right:
                top = max(top, box.y1)
        _, axes_y = inverse.transform((right, top + pad))
        axes_x, _ = inverse.transform((right, 0))
        text.set_position((axes_x, axes_y))
        text._speclab_curve = c
        ax._speclab_names.append(text)


def save(fig: Figure, path, transparent: bool = False, **kwargs) -> None:
    """Save with the fonts used for the layout (``path`` may be a file object)."""
    with _RENDER_LOCK, rc_context(getattr(fig, "_speclab_rc", {})):
        fig.savefig(path, dpi=fig.dpi, transparent=transparent,
                    facecolor="none" if transparent else fig.get_facecolor(), **kwargs)


def draw(fig: Figure) -> None:
    """Draw onto the Agg canvas (e.g. for an on-screen preview) with the layout fonts."""
    with _RENDER_LOCK, rc_context(getattr(fig, "_speclab_rc", {})):
        fig.canvas.draw()


def to_png(fig: Figure) -> bytes:
    import io

    buffer = io.BytesIO()
    save(fig, buffer, format="png")
    return buffer.getvalue()


def _fit_name(text, renderer, limit: float, size: float) -> None:
    """Long names (e.g. raw file names) may take at most ``limit`` pixels:
    first a slightly smaller font, then an ellipsis in the middle."""
    if text.get_window_extent(renderer).width <= limit:
        return
    text.set_fontsize(0.8 * size)
    if text.get_window_extent(renderer).width <= limit:
        return
    full = text.get_text()
    keep_low, keep_high = 4, len(full) - 1
    best = full[:4] + "…"
    while keep_low <= keep_high:
        keep = (keep_low + keep_high) // 2
        head = (keep + 1) // 2
        candidate = full[:head] + "…" + full[len(full) - (keep - head):]
        text.set_text(candidate)
        if text.get_window_extent(renderer).width <= limit:
            best, keep_low = candidate, keep + 1
        else:
            keep_high = keep - 1
    text.set_text(best)


def _thin_x_ticks(ax, renderer, spec) -> None:
    """Fewer major X ticks when their labels would touch on a narrow axis."""
    from matplotlib.font_manager import FontProperties

    if not spec.show_x_values:
        return
    font = FontProperties(size=spec.tick_pt, weight="bold" if spec.tick_bold else "normal")
    gap = 0.6 * spec.tick_pt * ax.figure.dpi / 72
    low, high = sorted(ax.get_xlim())
    for bins in (7, 6, 5, 4, 3, 2):
        locator = MaxNLocator(nbins=bins, steps=[1, 2, 2.5, 5, 10])
        values = [v for v in locator.tick_values(low, high) if low <= v <= high]
        labels = ax.xaxis.get_major_formatter().format_ticks(values)
        spans = []
        for value, label in zip(values, labels):
            width = renderer.get_text_width_height_descent(label.replace("$", ""), font, ismath=False)[0]
            centre = ax.transData.transform((value, 0))[0]
            spans.append((centre - width / 2, centre + width / 2))
        spans.sort()
        if all(b[0] - a[1] >= gap for a, b in zip(spans, spans[1:])):
            if bins != 7:
                ax.xaxis.set_major_locator(locator)
            return
    ax.xaxis.set_major_locator(MaxNLocator(nbins=2, steps=[1, 2, 2.5, 5, 10]))


def collisions(fig: Figure) -> dict:
    """Peak labels touching another spectrum or another spectrum's labels.

    {'label_curve': [(label text, curve index of the label, curve index hit)],
     'label_label': [(text a, text b)]}; used to check AI-made figures.
    """
    with _RENDER_LOCK, rc_context(getattr(fig, "_speclab_rc", {})):
        renderer = fig.canvas.get_renderer()
        ax = fig.axes[0]
        texts = getattr(fig, "_speclab_texts", {})
        lines = getattr(fig, "_speclab_lines", [])
        boxes = [((c, k), text.get_text(), text.get_window_extent(renderer).shrunk(0.92, 0.92))
                 for (c, k), text in texts.items() if text.get_visible()]
        paths = [ax.transData.transform(np.c_[line.get_xdata(), line.get_ydata()]) for line in lines]
    hits, pairs = [], []
    for (c, _k), label, box in boxes:
        for index, points in enumerate(paths):
            if index == c:
                continue
            finite = np.isfinite(points).all(axis=1)
            inside = ((points[finite, 0] > box.x0) & (points[finite, 0] < box.x1)
                      & (points[finite, 1] > box.y0) & (points[finite, 1] < box.y1))
            if inside.any():
                hits.append((label, c, index))
    for i, ((ca, _ka), label_a, a) in enumerate(boxes):
        for (cb, _kb), label_b, b in boxes[i + 1:]:
            if ca != cb and a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1:
                pairs.append((label_a, label_b))
    return {"label_curve": hits, "label_label": pairs}
