"""Generic VLE flash routines built on :class:`PropertyPackage`.

The single public entry point :func:`flash_PT` solves a two-phase isothermal
(P, T, z) flash via successive substitution:

1. Initial K from ``package.K_values(T, P, z)`` (Wilson for cubic EOS,
   modified-Raoult with x ≈ z for activity models, Raoult for ideal gas).
2. Solve Rachford-Rice for V; compute x, y.
3. Update K via ``package.K_iteration(T, P, x, y)`` — rigorous fugacity ratio
   for cubic EOS, modified-Raoult re-evaluation for activity models.
4. Repeat until ‖ΔK / K‖∞ < tol.

Single-phase shortcuts (Σ z K ≤ 1 → all liquid; Σ z/K ≤ 1 → all vapour) avoid
the Newton inner loop when bracketing fails.

The routine is property-package-agnostic — any subclass of PropertyPackage
that implements ``K_values`` and ``K_iteration`` plugs straight in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from pse_ecosystem.models.properties.property_package import PropertyPackage
from pse_ecosystem.models.properties.vle import rachford_rice


@dataclass
class FlashResult:
    converged: bool
    n_iter: int
    V: float
    x: np.ndarray
    y: np.ndarray
    K: np.ndarray
    phase: str  # "two_phase" | "all_vapor" | "all_liquid" | "failed"


def flash_PT(
    package: PropertyPackage,
    z,
    T_K: float,
    P_Pa: float,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> FlashResult:
    """Solve a two-phase PT flash for the given property package.

    Parameters
    ----------
    package : PropertyPackage
        Pre-built package whose ``species`` order matches ``z``.
    z : array-like
        Overall mole fractions (any positive vector — internally normalised).
    T_K, P_Pa : float
        Flash temperature and pressure.
    tol : float
        Convergence tolerance on the maximum relative change in K_i between
        successive substitution iterations.
    max_iter : int
        Hard iteration cap. For poorly-conditioned mixtures (near-critical,
        sharply non-ideal) the caller should consider warm-starting with the
        previous flash's K vector.
    """
    z = np.asarray(z, dtype=float)
    if z.sum() <= 0.0:
        raise ValueError("Flash composition has zero total flow")
    z = z / z.sum()

    K = package.K_values(T_K, P_Pa, z)
    K = np.clip(K, 1e-30, 1e30)  # numerical floor

    # Quick single-phase test before any Newton work.
    sum_zK = float(np.dot(z, K))
    sum_z_over_K = float(np.dot(z, 1.0 / K))
    if sum_zK <= 1.0:
        x = z.copy()
        y = K * x
        y = y / y.sum() if y.sum() > 0 else y
        return FlashResult(True, 0, 0.0, x, y, K, "all_liquid")
    if sum_z_over_K <= 1.0:
        y = z.copy()
        x = z / K
        x = x / x.sum() if x.sum() > 0 else x
        return FlashResult(True, 0, 1.0, x, y, K, "all_vapor")

    x = z.copy()
    y = z.copy()
    V = 0.5
    for it in range(max_iter):
        V = rachford_rice(z, K)
        if math.isnan(V):
            return FlashResult(False, it, float("nan"), x, y, K, "failed")
        x = z / (1.0 + V * (K - 1.0))
        y = K * x
        # Normalise (Rachford-Rice ensures Σx = Σy = 1 analytically, but
        # floating-point drift can be visible after enough iterations).
        x = x / x.sum()
        y = y / y.sum()

        K_new = package.K_iteration(T_K, P_Pa, x, y)
        K_new = np.clip(K_new, 1e-30, 1e30)
        delta = float(np.max(np.abs((K_new - K) / np.where(K > 0, K, 1.0))))
        K = K_new
        if delta < tol:
            return FlashResult(True, it + 1, V, x, y, K, "two_phase")

    return FlashResult(False, max_iter, V, x, y, K, "two_phase")


__all__ = ["FlashResult", "flash_PT"]
