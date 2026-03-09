"""
Peak detection for spectra using scipy.signal.find_peaks.
Replaces the manual JS implementation in detectPeaks.ts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    n = min(len(xa), len(ya))
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

    # Convert min_distance_x to sample distance
    if n > 1:
        dx_median = np.median(np.abs(np.diff(xa)))
        if dx_median > 0:
            distance_samples = max(1, int(round(min_distance_x / dx_median)))
        else:
            distance_samples = 1
    else:
        distance_samples = 1

    results: List[DetectedPeak] = []

    def _find(signal: np.ndarray, invert: bool = False) -> None:
        indices, props = find_peaks(
            signal,
            prominence=max(0, min_prominence) if min_prominence > 0 else None,
            distance=distance_samples,
        )
        proms = props.get("prominences", np.zeros(len(indices)))

        for idx, prom in zip(indices, proms):
            if not region_mask[idx]:
                continue
            if min_prominence > 0 and prom < min_prominence:
                continue
            results.append(DetectedPeak(
                x=float(xa[idx]),
                y=float(ya[idx]),
                i=int(idx),
                prominence=float(prom),
            ))

    if polarity in ("max", "both"):
        _find(ya)
    if polarity in ("min", "both"):
        _find(-ya, invert=True)

    # Sort by prominence descending, pick top max_peaks
    results.sort(key=lambda p: p.prominence, reverse=True)
    selected = results[:max(1, max_peaks)]

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
            kind="max",
            prominence=d.prominence,
        )
        for d in detected
    ]
