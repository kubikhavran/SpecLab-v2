"""Sampling structure of spectral axes shared by processing, peaks and plotting."""

from __future__ import annotations

import numpy as np

# Detector axes (e.g. Raman CCD pixels converted to cm⁻¹) change their step
# slowly; a step this many times larger than the typical one is a real gap,
# such as a region blanked in OMNIC or cropped out before export.
GAP_STEP_RATIO = 3.0


def gap_positions(x) -> np.ndarray:
    """Indices i where the step x[i] → x[i+1] is a gap."""
    step = np.abs(np.diff(np.asarray(x, dtype=float)))
    if len(step) < 1:
        return np.array([], dtype=int)
    # The median of two steps is their mean, which would hide a gap.
    typical = np.median(step) if len(step) >= 3 else np.min(step)
    if typical <= 0:
        return np.array([], dtype=int)
    return np.flatnonzero(step > GAP_STEP_RATIO * typical)


def segments(x) -> list[slice]:
    """Contiguous runs of points separated by gaps."""
    bounds = np.r_[0, gap_positions(x) + 1, len(x)]
    return [slice(int(a), int(b)) for a, b in zip(bounds[:-1], bounds[1:])]


def with_gap_breaks(x, y):
    """Copies of x/y with NaN inserted at gaps, for plots drawn with connect='finite'."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    gaps = gap_positions(x)
    if not len(gaps):
        return x, y
    return np.insert(x, gaps + 1, np.nan), np.insert(y, gaps + 1, np.nan)
