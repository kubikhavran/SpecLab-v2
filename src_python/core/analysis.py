"""Read-only measurements on current spectral data."""

import numpy as np


def integrate_band(x, y, low, high):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (
        len(x) < 2
        or len(x) != len(y)
        or not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y))
    ):
        raise ValueError("Neplatná data pro integraci.")
    if not np.all(np.diff(x) > 0):
        raise ValueError("Integrace vyžaduje vzestupnou osu X.")
    if not np.isfinite(low) or not np.isfinite(high) or not x[0] <= low < high <= x[-1]:
        raise ValueError(
            "Interval musí ležet uvnitř měřeného rozsahu a mít kladnou šířku."
        )
    mask = (x > low) & (x < high)
    xx = np.concatenate(([low], x[mask], [high]))
    yy = np.concatenate(([np.interp(low, x, y)], y[mask], [np.interp(high, x, y)]))
    return float(np.trapezoid(yy, xx))
