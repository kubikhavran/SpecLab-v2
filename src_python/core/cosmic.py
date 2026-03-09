"""
Cosmic ray (spike) removal for Raman spectra.
Port of removeCosmicRays.ts.

Algorithm:
  1. Smooth the signal with Savitzky–Golay
  2. Compute residual = original − smoothed
  3. Find narrow spikes in residual via MAD-based thresholding
  4. Replace spike regions with linear interpolation from neighbours
  5. Repeat for *iterations* passes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
from scipy.signal import savgol_filter


@dataclass
class CosmicResult:
    y_clean: List[float]
    mask: List[bool]
    removed_count: int


def _ensure_odd(val: int) -> int:
    return val if val % 2 == 1 else val + 1


def _build_spike_mask(
    residual: np.ndarray,
    threshold: float,
    max_width: int,
    positive_only: bool,
) -> np.ndarray:
    """Return boolean mask where True = spike candidate."""
    med = np.median(residual)
    abs_dev = np.abs(residual - med)
    sigma = 1.4826 * np.median(abs_dev)

    if not np.isfinite(sigma) or sigma <= 0:
        return np.zeros(len(residual), dtype=bool)

    cut = threshold * sigma
    if positive_only:
        candidates = residual > cut
    else:
        candidates = np.abs(residual) > cut

    # Only keep narrow candidate groups (width <= max_width)
    mask = np.zeros(len(residual), dtype=bool)
    i = 0
    n = len(candidates)
    while i < n:
        if not candidates[i]:
            i += 1
            continue
        start = i
        while i < n and candidates[i]:
            i += 1
        end = i  # exclusive
        if (end - start) <= max_width:
            mask[start:end] = True

    return mask


def _interpolate_masked(
    y_source: np.ndarray,
    y_smooth: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """Replace masked segments with linear interpolation from neighbours."""
    output = y_source.copy()
    n = len(mask)
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        start = i
        while i < n and mask[i]:
            i += 1
        end = i  # exclusive

        # Find valid neighbours
        left = start - 1
        while left >= 0 and mask[left]:
            left -= 1
        right = end
        while right < n and mask[right]:
            right += 1

        if left >= 0 and right < n:
            lv = y_source[left]
            rv = y_source[right]
            if np.isfinite(lv) and np.isfinite(rv) and right > left:
                span = right - left
                for idx in range(start, end):
                    t = (idx - left) / span
                    output[idx] = lv + t * (rv - lv)
                continue

        # Fallback: use smoothed value
        for idx in range(start, end):
            sv = y_smooth[idx]
            output[idx] = sv if np.isfinite(sv) else y_source[idx]

    return output


def remove_cosmic_rays(
    y: List[float],
    window: int = 11,
    threshold: float = 6.0,
    max_width: int = 3,
    positive_only: bool = True,
    iterations: int = 1,
) -> CosmicResult:
    """
    Detect and remove cosmic ray spikes from spectrum *y*.

    Parameters
    ----------
    y : list of float
        Raw intensity values.
    window : int
        Savitzky–Golay smoothing window for background estimation.
    threshold : float
        MAD-based threshold multiplier for spike detection.
    max_width : int
        Maximum width (in points) of a single spike.
    positive_only : bool
        If True, only detect positive spikes (typical for cosmic rays).
    iterations : int
        Number of detection + interpolation passes.

    Returns
    -------
    CosmicResult with y_clean, boolean mask, and removed_count.
    """
    ya = np.asarray(y, dtype=np.float64)
    if len(ya) < 5:
        return CosmicResult(y_clean=list(ya), mask=[False] * len(ya), removed_count=0)

    w = _ensure_odd(max(5, int(window)))
    poly_order = max(2, min(3, w - 2))
    global_mask = np.zeros(len(ya), dtype=bool)
    y_clean = ya.copy()

    for _ in range(max(1, int(iterations))):
        w_safe = min(w, len(y_clean))
        if w_safe % 2 == 0:
            w_safe -= 1
        if w_safe < 5:
            break
        po_safe = min(poly_order, w_safe - 2)

        y_smooth = savgol_filter(y_clean, window_length=w_safe, polyorder=po_safe)
        residual = y_clean - y_smooth
        iter_mask = _build_spike_mask(residual, threshold, max_width, positive_only)

        if not np.any(iter_mask):
            break

        global_mask |= iter_mask
        y_clean = _interpolate_masked(y_clean, y_smooth, iter_mask)

    return CosmicResult(
        y_clean=y_clean.tolist(),
        mask=global_mask.tolist(),
        removed_count=int(np.sum(global_mask)),
    )
