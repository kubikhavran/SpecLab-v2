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
