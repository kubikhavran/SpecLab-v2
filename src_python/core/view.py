"""View transforms shared by the interactive graph and publication export."""

import numpy as np


def view_y(values, mode="common"):
    values = np.asarray(values, dtype=float)
    if mode == "full":
        span = float(np.ptp(values))
        return (values - np.min(values)) / span if span else np.zeros_like(values)
    return values


def trace_style(spectrum, color, width):
    style = spectrum.meta.get("trace_style", {})
    return (
        style.get("color", color),
        style.get("width", width),
        style.get("line", "solid"),
    )


def stack_offset(curves, gap=0.1, x_range=None):
    """Smallest common offset that lifts every curve clear of the one below it.

    ``curves`` are (x, y) pairs in plotting order (bottom first); the curves are
    compared point by point over their common X range, and ``gap`` adds a
    fraction of the tallest curve as free space. ``x_range`` limits everything
    to the visible part of the axis.
    """
    if x_range is not None:
        low, high = min(x_range), max(x_range)
        trimmed = []
        for x, y in curves:
            x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
            inside = (x >= low) & (x <= high)
            trimmed.append((x[inside], y[inside]) if np.count_nonzero(inside) > 1 else (x, y))
        curves = trimmed
    need, span = 0.0, 0.0
    for x, y in curves:
        span = max(span, float(np.ptp(np.asarray(y, dtype=float))))
    for (xa, ya), (xb, yb) in zip(curves, curves[1:]):
        xa, ya = _ascending(xa, ya)
        xb, yb = _ascending(xb, yb)
        low, high = max(xa[0], xb[0]), min(xa[-1], xb[-1])
        if high <= low:
            continue
        grid = np.linspace(low, high, 2000)
        need = max(need, float(np.max(np.interp(grid, xa, ya) - np.interp(grid, xb, yb))))
    return max(need, 0.0) + gap * span


def _ascending(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    return (x, y) if x[-1] >= x[0] else (x[::-1], y[::-1])
