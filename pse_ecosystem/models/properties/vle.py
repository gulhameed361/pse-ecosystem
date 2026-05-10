"""Vapour-liquid equilibrium (VLE) property functions.

Uses Antoine equation (log₁₀ form) for vapour pressure and Raoult's Law
(ideal VLE) for K-values.  Rachford-Rice solver uses Brent's method from
scipy.  Bubble and dew point calculations use Newton-Raphson.

Antoine constants: Perry's Chemical Engineers' Handbook, 8th Ed., Table 2-8.
    log₁₀(P_sat / mmHg) = A - B / (T_°C + C)

Non-ideal VLE (NRTL, Wilson activity coefficients) is deferred to v0.3.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

# ── Antoine constants ─────────────────────────────────────────────────────────
# Format: {species: {"A": ..., "B": ..., "C": ..., "T_min": K, "T_max": K}}
# Temperature range in K (converted from °C in sources).

ANTOINE: Dict[str, Dict[str, float]] = {
    "benzene":   {"A": 6.90565, "B": 1211.033, "C": 220.790, "T_min": 278, "T_max": 377},
    "toluene":   {"A": 6.95334, "B": 1343.943, "C": 219.377, "T_min": 280, "T_max": 410},
    "n-hexane":  {"A": 6.87601, "B": 1171.170, "C": 224.408, "T_min": 286, "T_max": 342},
    "n-heptane": {"A": 6.89385, "B": 1264.370, "C": 216.636, "T_min": 270, "T_max": 400},
    "methanol":  {"A": 7.89750, "B": 1474.080, "C": 217.840, "T_min": 288, "T_max": 357},
    "ethanol":   {"A": 8.11220, "B": 1592.864, "C": 226.184, "T_min": 290, "T_max": 369},
    "water":     {"A": 8.07131, "B": 1730.630, "C": 233.426, "T_min": 273, "T_max": 373},
    # Light gases — pseudo-Antoine valid in narrow sub-critical range
    "H2":        {"A": 6.23400, "B": 99.395,   "C": 307.180, "T_min":  15, "T_max":  33},
    "CO2":       {"A": 6.81228, "B": 975.700,  "C": 270.580, "T_min": 194, "T_max": 304},
    "methane":   {"A": 6.69561, "B": 405.420,  "C": 267.780, "T_min": 111, "T_max": 190},
}

_MMHG_TO_PA = 133.322  # 1 mmHg in Pascal


def K_value(species: str, T_K: float, P_Pa: float) -> float:
    """K-value (y/x) via Raoult's Law and Antoine vapour pressure.

    K_i = P_sat_i(T) / P

    Returns a very large value when T is below the Antoine valid range
    (species is a light gas or supercritical) and a very small value when T
    is above the valid range (species is a heavy liquid at high T).
    """
    p = ANTOINE[species]
    T_C = T_K - 273.15
    log10_Psat_mmHg = p["A"] - p["B"] / (T_C + p["C"])
    Psat_Pa = (10.0 ** log10_Psat_mmHg) * _MMHG_TO_PA
    return Psat_Pa / P_Pa


def rachford_rice(
    z: np.ndarray,
    K: np.ndarray,
    tol: float = 1e-10,
    max_iter: int = 100,
) -> float:
    """Solve Rachford-Rice equation for vapour fraction V ∈ (0, 1).

    Σ_i  z_i (K_i - 1) / (1 + V (K_i - 1)) = 0

    Uses Michelsen (1982) bounds for the bracket, then Brent's method.
    Returns ``float("nan")`` if the mixture is single-phase (all vapour or
    all liquid) or if K-values indicate trivial solution.

    Parameters
    ----------
    z : array-like, shape (N,)
        Overall mole fractions (should sum to 1).
    K : array-like, shape (N,)
        K-values K_i = y_i / x_i.
    """
    z = np.asarray(z, dtype=float)
    K = np.asarray(K, dtype=float)

    # Michelsen bounds
    idx_gt1 = K > 1.0
    idx_lt1 = K < 1.0
    V_min = 1.0 / (1.0 - float(np.max(K))) if idx_gt1.any() else 0.0
    V_max = 1.0 / (1.0 - float(np.min(K))) if idx_lt1.any() else 1.0
    V_min = max(V_min + 1e-12, 0.0)
    V_max = min(V_max - 1e-12, 1.0)

    if V_min >= V_max:
        return float("nan")  # single-phase condition

    def _rr(V: float) -> float:
        return float(np.sum(z * (K - 1.0) / (1.0 + V * (K - 1.0))))

    # Check that root exists in the bracket
    fa, fb = _rr(V_min), _rr(V_max)
    if fa * fb > 0:
        return float("nan")

    # Brent's method (fallback to bisection if scipy unavailable)
    try:
        from scipy.optimize import brentq
        return float(brentq(_rr, V_min, V_max, xtol=tol, maxiter=max_iter))
    except ImportError:
        # Pure-Python bisection fallback
        a, b = V_min, V_max
        for _ in range(max_iter):
            mid = 0.5 * (a + b)
            if abs(b - a) < tol:
                return mid
            if _rr(mid) * _rr(a) < 0:
                b = mid
            else:
                a = mid
        return 0.5 * (a + b)


def bubble_T(
    z: np.ndarray,
    P_Pa: float,
    species_list: List[str],
    T_guess: float = 350.0,
    tol: float = 1e-6,
    max_iter: int = 50,
) -> float:
    """Bubble-point temperature at pressure P_Pa [K].

    Solves Σ_i z_i K_i(T, P) = 1 by Newton-Raphson on T.

    Returns ``float("nan")`` on failure.
    """
    z = np.asarray(z, dtype=float)
    T = T_guess
    for _ in range(max_iter):
        Ks = np.array([K_value(sp, T, P_Pa) for sp in species_list])
        f = float(np.dot(z, Ks)) - 1.0
        if abs(f) < tol:
            return T
        # Numerical derivative ∂(ΣzK)/∂T
        dT = 0.5
        Ks_p = np.array([K_value(sp, T + dT, P_Pa) for sp in species_list])
        dfdT = (float(np.dot(z, Ks_p)) - float(np.dot(z, Ks))) / dT
        if abs(dfdT) < 1e-15:
            break
        T -= f / dfdT
    return float("nan")


def dew_T(
    y: np.ndarray,
    P_Pa: float,
    species_list: List[str],
    T_guess: float = 350.0,
    tol: float = 1e-6,
    max_iter: int = 50,
) -> float:
    """Dew-point temperature at pressure P_Pa [K].

    Solves Σ_i y_i / K_i(T, P) = 1 by Newton-Raphson on T.

    Returns ``float("nan")`` on failure.
    """
    y = np.asarray(y, dtype=float)
    T = T_guess
    for _ in range(max_iter):
        Ks = np.array([K_value(sp, T, P_Pa) for sp in species_list])
        f = float(np.dot(y, 1.0 / Ks)) - 1.0
        if abs(f) < tol:
            return T
        dT = 0.5
        Ks_p = np.array([K_value(sp, T + dT, P_Pa) for sp in species_list])
        dfdT = (float(np.dot(y, 1.0 / Ks_p)) - float(np.dot(y, 1.0 / Ks))) / dT
        if abs(dfdT) < 1e-15:
            break
        T -= f / dfdT
    return float("nan")
