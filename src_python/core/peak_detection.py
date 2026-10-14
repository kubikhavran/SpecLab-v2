"""
Peak detection for spectra using scipy.signal.find_peaks.
Replaces the manual JS implementation in detectPeaks.ts.
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, insort
from typing import List, Optional

import numpy as np
from scipy.signal import find_peaks

from app.models import Peak, _new_id


@dataclass
class DetectedPeak:
    x: float
    y: float
    i: int
    prominence: float
    kind: str = 'max'
    width: Optional[float] = None


def detect_peaks(
    x: List[float],
    y: List[float],
    min_prominence: float = 0.0,
    min_distance_x: float = 10.0,
    max_peaks: int = 20,
    x_min: Optional[float] = None,
    x_max: Optional[float] = None,
    polarity: str = "max",
) -> List[DetectedPeak]:
    """
    Detect peaks in spectrum (x, y).

    Parameters
    ----------
    x, y : lists of float (same length)
    min_prominence : minimum peak prominence
    min_distance_x : minimum distance between peaks in X units
    max_peaks : maximum number of peaks to return
    x_min, x_max : optional region filter
    polarity : "max" (peaks pointing up), "min" (valleys), or "both"

    Returns
    -------
    List of DetectedPeak sorted by x position.
    """
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    if xa.ndim != 1 or ya.ndim != 1 or len(xa) != len(ya):
        raise ValueError('Peak detection requires equally sized one-dimensional X/Y arrays.')
    if not np.all(np.isfinite(xa)) or not np.all(np.isfinite(ya)):
        raise ValueError('Peak detection requires finite data.')
    if polarity not in {'max', 'min', 'both'}:
        raise ValueError('Unknown peak polarity.')
    if not np.isfinite(min_prominence) or min_prominence < 0 or not np.isfinite(min_distance_x) or min_distance_x < 0:
        raise ValueError('Peak prominence and distance must be finite and nonnegative.')
    if isinstance(max_peaks, bool) or not isinstance(max_peaks, int) or not 1 <= max_peaks <= 10000:
        raise ValueError('Maximum peak count must be an integer between 1 and 10000.')
    n = len(xa)
    if n < 3:
        return []

    xa = xa[:n]
    ya = ya[:n]

    # Region filter
    if x_min is not None and x_max is not None:
        lo, hi = min(x_min, x_max), max(x_min, x_max)
        region_mask = (xa >= lo) & (xa <= hi)
    else:
        region_mask = np.ones(n, dtype=bool)
        if x_min is not None:
            region_mask &= xa >= x_min
        if x_max is not None:
            region_mask &= xa <= x_max

    results: List[DetectedPeak] = []
    sample_indices = np.arange(n)

    def _find(signal: np.ndarray, invert: bool = False) -> None:
        indices, props = find_peaks(
            signal,
            prominence=(min_prominence, None),
            width=(0, None),
        )
        proms = props.get("prominences", np.zeros(len(indices)))

        for position, (idx, prom) in enumerate(zip(indices, proms)):
            if not region_mask[idx]:
                continue
            if min_prominence > 0 and prom < min_prominence:
                continue
            results.append(DetectedPeak(
                x=float(xa[idx]),
                y=float(ya[idx]),
                i=int(idx),
                prominence=float(prom),
                kind='min' if invert else 'max',
                width=float(abs(np.interp(props['right_ips'][position], sample_indices, xa)
                                - np.interp(props['left_ips'][position], sample_indices, xa))),
            ))

    if polarity in ("max", "both"):
        _find(ya)
    if polarity in ("min", "both"):
        _find(-ya, invert=True)

    # Sort by prominence descending, pick top max_peaks
    results.sort(key=lambda p: p.prominence, reverse=True)
    selected = []
    selected_positions = []
    for candidate in results:
        # Suppress by actual X distance, including irregular sampling and mixed polarity.
        insertion = bisect_left(selected_positions, candidate.x)
        neighbours = selected_positions[max(0, insertion - 1):insertion + 1]
        if all(abs(candidate.x - position) >= min_distance_x for position in neighbours):
            selected.append(candidate)
            insort(selected_positions, candidate.x)
            if len(selected) >= max_peaks:
                break

    # Return sorted by x
    selected.sort(key=lambda p: p.x)
    return selected


def detected_to_peaks(detected: List[DetectedPeak]) -> List[Peak]:
    """Convert DetectedPeak list to model Peak list (for storage in AppState)."""
    return [
        Peak(
            id=_new_id(),
            x=d.x,
            source="auto",
            i=d.i,
            kind=d.kind,
            prominence=d.prominence,
            width=d.width,
        )
        for d in detected
    ]
