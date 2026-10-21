"""Publication renderer: typeset units, centred axis titles, clean label layout."""

import re

import numpy as np
import pytest

from core.figure import Curve, FigureSpec, render, to_mathtext


@pytest.mark.parametrize("raw, expected", [
    ("Raman shift (cm^{-1})", "Raman shift (cm$^{-1}$)"),
    ("Wavenumber (cm⁻¹)", "Wavenumber (cm$^{-1}$)"),
    ("CO_2 signal", "CO$_{2}$ signal"),
    ("Intensity (a.u.)", "Intensity (a.u.)"),
])
def test_units_become_mathtext(raw, expected):
    assert to_mathtext(raw) == expected


def _stack(seed=3, count=3, peaks=18):
    rng = np.random.default_rng(seed)
    x = np.linspace(400, 1800, 1400)
    curves = []
    for index in range(count):
        centres = np.sort(rng.uniform(450, 1750, peaks))
        heights = rng.uniform(5, 60, peaks)
        y = 5 + sum(h * np.exp(-0.5 * ((x - c) / rng.uniform(3, 9)) ** 2) for c, h in zip(centres, heights))
        marks = [(float(c), f"{c:.0f}", float(h), True) for c, h in zip(centres, heights)]
        curves.append(Curve(f"Sample {index + 1}", x, y, f"C{index}", offset=index * 30.0, peaks=marks))
    return curves


def _boxes(fig):
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    names = set(getattr(ax, "_speclab_names", []))
    return ax, renderer, [t.get_window_extent(renderer) for t in ax.texts if t not in names and t.get_visible()]


def test_stacked_labels_never_overlap_labels_or_other_curves():
    curves = _stack()
    fig = render(FigureSpec(curves=curves, x_label="Raman shift (cm^{-1})", y_label="Intensity (a.u.)",
                            show_y_values=False), 1800, 1100, 200)
    ax, renderer, boxes = _boxes(fig)
    assert len(boxes) >= 10
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a.x1 <= b.x0 + 0.5 or b.x1 <= a.x0 + 0.5 or a.y1 <= b.y0 + 0.5 or b.y1 <= a.y0 + 0.5
    # No label covers any curve (its own curve lies below it, others are separated).
    for curve in curves:
        points = ax.transData.transform(np.c_[curve.x, curve.y + curve.offset])
        for box in boxes:
            inside = ((points[:, 0] > box.x0 + 0.5) & (points[:, 0] < box.x1 - 0.5)
                      & (points[:, 1] > box.y0 + 0.5) & (points[:, 1] < box.y1 - 0.5))
            assert not inside.any()
    frame = ax.get_window_extent(renderer)
    for box in boxes:   # labels stay inside the plotting area
        assert box.y0 >= frame.y0 - 0.5 and box.y1 <= frame.y1 + 0.5


def test_axis_titles_are_centred_on_the_axes():
    fig = render(FigureSpec(curves=_stack(count=1), x_label="Raman shift (cm^{-1})", y_label="Intensity"),
                 1600, 900, 200)
    ax = fig.axes[0]
    renderer = fig.canvas.get_renderer()
    frame = ax.get_window_extent(renderer)
    xlabel = ax.xaxis.label.get_window_extent(renderer)
    ylabel = ax.yaxis.label.get_window_extent(renderer)
    assert abs((xlabel.x0 + xlabel.x1) / 2 - (frame.x0 + frame.x1) / 2) < 1.5
    assert abs((ylabel.y0 + ylabel.y1) / 2 - (frame.y0 + frame.y1) / 2) < 1.5



def test_decorations_stay_inside_the_canvas():
    curves = _stack(count=1)
    for curve in curves:
        curve.y = curve.y / 1000          # small values → wide tick labels after rescaling
    fig = render(FigureSpec(curves=curves, x_label="Raman shift (cm^{-1})", y_label="Intensity (a.u.)",
                            bold_axis_labels=True), 1800, 1000, 300)
    renderer = fig.canvas.get_renderer()
    tight = fig.axes[0].get_tightbbox(renderer)
    canvas = fig.get_window_extent(renderer)
    assert tight.x0 >= canvas.x0 and tight.y0 >= canvas.y0
    assert tight.x1 <= canvas.x1 and tight.y1 <= canvas.y1


@pytest.mark.parametrize("low, high, power", [(0.0001, 0.00083, -4), (0, 25000, 3), (0, 600, 0), (0, 0.5, 0)])
def test_tiny_or_huge_values_get_a_factor_in_the_axis_title(low, high, power):
    from core.figure import value_power, with_multiplier

    assert value_power(low, high) == power
    assert with_multiplier("Intensity (a.u.)", -4) == "Intensity (×10^{-4} a.u.)"
    assert with_multiplier("Absorbance", 3) == "Absorbance (×10^{3})"


def test_area_normalized_spectrum_has_short_tick_labels():
    curves = _stack(count=1)
    curves[0].y = curves[0].y / 1e6
    fig = render(FigureSpec(curves=curves, x_label="Raman shift (cm^{-1})", y_label="Intensity (a.u.)"),
                 1600, 900, 200)
    ax = fig.axes[0]
    labels = [re.sub(r"\\mathdefault\{(.*)\}", r"\1", t.get_text()).strip("$")
              for t in ax.get_yticklabels() if t.get_text()]
    assert labels and all(len(text) <= 4 for text in labels)
    assert "10$^{-5}$" in ax.get_ylabel() or "10$^{-6}$" in ax.get_ylabel()


def test_y_range_and_offsets_ignore_data_outside_the_x_limits():
    x = np.linspace(100, 3200, 3101)
    edge = 50000 * np.exp(-((x - 100) / 30) ** 2)        # Rayleigh edge outside the view
    band = 100 * np.exp(-0.5 * ((x - 1000) / 10) ** 2)
    curves = [Curve("a", x, edge + band, "C0"), Curve("b", x, edge + band, "C1", offset=150.0)]
    fig = render(FigureSpec(curves=curves, x_limits=(300, 1700), show_y_values=False), 1200, 800, 150)
    low, high = fig.axes[0].get_ylim()
    assert high < 1000                                    # not stretched to the 50000 edge


def test_horizontal_labels_are_drawn_above_their_peaks():
    x = np.linspace(400, 1800, 1400)
    y = sum(h * np.exp(-0.5 * ((x - c) / 15) ** 2) for c, h in [(1040, 1.0), (1158, 0.3), (1286, 0.35)])
    curve = Curve("s", x, y, "C0", peaks=[(c, f"{c}", h, True) for c, h in [(1040, 1.0), (1158, 0.3), (1286, 0.35)]])
    fig = render(FigureSpec(curves=[curve], label_angle=0, leader_lines=False), 1200, 800, 200)
    ax = fig.axes[0]
    renderer = fig.canvas.get_renderer()
    for (c, k), text in fig._speclab_texts.items():
        box = text.get_window_extent(renderer)
        px = ax.transData.transform((curve.peaks[k][0], 0))[0]
        assert box.x0 <= px <= box.x1
