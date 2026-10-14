"""
Asymmetric Least Squares (AsLS) baseline estimation.
Port of aslsBaseline.ts + applyBaseline.ts.

The system (W + lambda·DᵀD) z = W y is symmetric, positive definite and
pentadiagonal, so each reweighting step uses a banded Cholesky solve; the
general sparse LU solver remains as a fallback for ill-conditioned input.
"""

from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.linalg import LinAlgError, solveh_banded
from scipy.sparse.linalg import spsolve


def asls_baseline(
    y: np.ndarray,
    lam: float = 1e6,
    p: float = 0.01,
    n_iter: int = 10,
) -> np.ndarray:
    """
    Estimate the baseline of signal *y* using Asymmetric Least Squares.

    Parameters
    ----------
    y : 1-D array
        Input signal (intensity values).
    lam : float
        Smoothness parameter (lambda). Larger = smoother baseline.
        Typical range: 1e4 – 1e9.
    p : float
        Asymmetry parameter. Smaller p penalises points above the
        baseline more (good for spectra with peaks pointing up).
        Typical range: 0.001 – 0.1.
    n_iter : int
        Number of reweighted iterations.

    Returns
    -------
    z : 1-D array  (same length as y)
        The estimated baseline.
    """
    y = np.asarray(y, dtype=np.float64)
    L = len(y)

    if L < 3:
        return y.copy()

    # Second-difference matrix D
    diags = np.array([1.0, -2.0, 1.0], dtype=np.float64)
    D = sparse.diags(diags, [0, 1, 2], shape=(L - 2, L), format="csc")
    DTD = lam * D.T.dot(D)

    # Upper banded storage of lambda·DᵀD: rows = 2nd, 1st super-diagonal, main.
    bands = np.zeros((3, L), dtype=np.float64)
    bands[0, 2:] = DTD.diagonal(2)
    bands[1, 1:] = DTD.diagonal(1)
    main = DTD.diagonal(0)

    w = np.ones(L, dtype=np.float64)
    z = y.copy()

    for _ in range(n_iter):
        bands[2] = main + w
        try:
            z = solveh_banded(bands, w * y, check_finite=False)
        except LinAlgError:
            W = sparse.diags(w, 0, shape=(L, L), format="csc")
            z = spsolve(W + DTD, w * y)
        # Update weights: points above baseline get weight p, below get (1 - p)
        w = np.where(y > z, p, 1.0 - p)

    return z


def apply_baseline(y: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """Subtract baseline from signal."""
    n = min(len(y), len(baseline))
    result = np.array(y, dtype=np.float64)
    result[:n] -= baseline[:n]
    return result
