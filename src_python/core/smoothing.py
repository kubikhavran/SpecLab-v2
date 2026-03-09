"""
Savitzky–Golay smoothing.
Port of savgol.ts — uses scipy.signal.savgol_filter.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter


def savgol_smooth(
    y: np.ndarray,
    window: int = 11,
    poly_order: int = 3,
) -> np.ndarray:
    """
    Apply Savitzky–Golay smoothing to signal *y*.

    Parameters
    ----------
    y : 1-D array
        Input signal.
    window : int
        Window length (must be odd and > poly_order).
    poly_order : int
        Polynomial order for the local fit.

    Returns
    -------
    y_smooth : 1-D array (same length as y)
    """
    y = np.asarray(y, dtype=np.float64)
    if len(y) < 4:
        return y.copy()

    # Ensure window is odd and valid
    w = max(5, int(window))
    if w % 2 == 0:
        w += 1
    w = min(w, len(y))
    if w % 2 == 0:
        w -= 1

    po = max(1, min(int(poly_order), w - 2))

    return savgol_filter(y, window_length=w, polyorder=po)
