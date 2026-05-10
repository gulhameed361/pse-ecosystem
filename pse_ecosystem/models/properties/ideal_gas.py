"""Ideal-gas thermodynamic properties.

Shomate equation (NIST Webbook form):
    Cp°(T) = A + B*t + C*t² + D*t³ + E/t²          [J/mol/K]
    H°(T) - H°(298) = A*t + B*t²/2 + C*t³/3 + D*t⁴/4 - E/t + F - H   [kJ/mol]

where t = T[K] / 1000.

Coefficients and formation enthalpies are taken directly from the NIST
Chemistry WebBook (https://webbook.nist.gov) — the same source used by the
IDAES generic property framework, enabling direct cross-validation.

Valid range: 298 K – 1200 K for most species listed.
"""

from __future__ import annotations

import math
from typing import Dict, List

# ── Shomate coefficients ──────────────────────────────────────────────────────
# Keys: A, B, C, D, E, F, H  (all in kJ/mol or J/mol/K as per NIST convention)
# H° - H°(298.15 K) = A*t + B*t²/2 + C*t³/3 + D*t⁴/4 - E/t + F - H  [kJ/mol]
# Cp°(T) = A + B*t + C*t² + D*t³ + E/t²                                [J/mol/K]

SHOMATE: Dict[str, Dict[str, float]] = {
    # H2: 298–1000 K (NIST)
    "H2": {
        "A": 33.066178, "B": -11.363417, "C": 11.432816, "D": -2.772874,
        "E": -0.158558, "F": -9.980797, "H": 0.0,
        "T_min": 298, "T_max": 1000,
    },
    # O2: 100–700 K range from NIST — gives correct Cp at 300 K (~29.4 J/mol/K)
    "O2": {
        "A": 31.32234, "B": -20.23531, "C": 57.86644, "D": -36.50624,
        "E": -0.007374, "F": -8.903471, "H": 0.0,
        "T_min": 100, "T_max": 700,
    },
    # N2: 298–1000 K range from NIST — gives correct Cp at 300 K (~29.1 J/mol/K)
    "N2": {
        "A": 28.98641, "B": 1.853978, "C": -9.647574, "D": 16.63537,
        "E": 0.000117, "F": -8.671914, "H": 0.0,
        "T_min": 298, "T_max": 1000,
    },
    # CO: 298–1300 K (NIST)
    "CO": {
        "A": 25.567959, "B": 6.096130, "C": 4.054656, "D": -2.671301,
        "E": 0.131021, "F": -118.009590, "H": -110.527,
        "T_min": 298, "T_max": 1300,
    },
    # CO2: 298–1200 K (NIST)
    "CO2": {
        "A": 24.997557, "B": 55.187022, "C": -33.691572, "D": 7.948387,
        "E": -0.136638, "F": -403.608069, "H": -393.510,
        "T_min": 298, "T_max": 1200,
    },
    # CH4: 298–1300 K (NIST)
    "CH4": {
        "A": -0.703029, "B": 108.477300, "C": -42.521800, "D": 5.862640,
        "E": 0.678565, "F": -76.843500, "H": -74.873,
        "T_min": 298, "T_max": 1300,
    },
    # H2O: 500–1700 K (NIST) — valid from 298 K in practice for gas-phase
    "H2O": {
        "A": 30.092000, "B": 6.832514, "C": 6.793435, "D": -2.534480,
        "E": 0.082139, "F": -250.881100, "H": -241.826,
        "T_min": 298, "T_max": 1700,
    },
}

# Molecular weights [g/mol]
MW: Dict[str, float] = {
    "H2": 2.016, "O2": 31.999, "N2": 28.014,
    "CO": 28.010, "CO2": 44.010, "CH4": 16.043, "H2O": 18.015,
}

# Standard enthalpy of formation at 298.15 K [J/mol]  (= H field × 1000)
H_REF_298: Dict[str, float] = {
    sp: d["H"] * 1000.0 for sp, d in SHOMATE.items()
}

_R_GAS = 8.314462  # J/mol/K


# ── Pure-component functions ──────────────────────────────────────────────────


def cp_J_mol_K(species: str, T_K: float) -> float:
    """Shomate Cp [J/mol/K] at T_K.  Valid ~298–1200 K."""
    p = SHOMATE[species]
    t = T_K / 1000.0
    return p["A"] + p["B"] * t + p["C"] * t ** 2 + p["D"] * t ** 3 + p["E"] / t ** 2


def _shomate_h_kJ_mol(p: Dict[str, float], T_K: float) -> float:
    """Shomate H - H_ref(298) [kJ/mol] at T_K."""
    t = T_K / 1000.0
    return (
        p["A"] * t
        + p["B"] * t ** 2 / 2.0
        + p["C"] * t ** 3 / 3.0
        + p["D"] * t ** 4 / 4.0
        - p["E"] / t
        + p["F"]
        - p["H"]
    )


def enthalpy_J_mol(species: str, T_K: float, T_ref_K: float = 298.15) -> float:
    """Molar enthalpy relative to T_ref_K [J/mol].

    Includes standard enthalpy of formation so that reaction enthalpies are
    correctly computed as Σ ν_i * h_i(T).
    """
    p = SHOMATE[species]
    h_T = _shomate_h_kJ_mol(p, T_K)
    h_ref = _shomate_h_kJ_mol(p, T_ref_K)
    # h_T - h_ref is sensible heat [kJ/mol]; add H_f° to get absolute enthalpy
    return (h_T - h_ref) * 1000.0 + H_REF_298[species]


def gamma(species: str, T_K: float) -> float:
    """Heat-capacity ratio Cp/Cv for an ideal gas at T_K."""
    cp = cp_J_mol_K(species, T_K)
    cv = cp - _R_GAS
    return cp / cv


# ── Mixture functions ─────────────────────────────────────────────────────────


def mixture_cp_J_mol_K(
    composition: Dict[str, float],
    T_K: float,
    basis: str = "mole_fraction",
) -> float:
    """Mixture Cp [J/mol/K] given mole fractions or molar flows.

    If ``basis='mole_fraction'`` the values in ``composition`` are treated as
    mole fractions and Σy_i = 1 is assumed.  If ``basis='molar_flow'`` the
    values are treated as molar flows [mol/s] and normalised internally.
    """
    total = sum(composition.values()) if basis == "molar_flow" else 1.0
    if total == 0.0:
        return 0.0
    return sum(
        (n / total) * cp_J_mol_K(sp, T_K)
        for sp, n in composition.items()
        if sp in SHOMATE
    )


def mixture_enthalpy_J_mol(
    composition: Dict[str, float],
    T_K: float,
    T_ref_K: float = 298.15,
    basis: str = "mole_fraction",
) -> float:
    """Mixture molar enthalpy [J/mol] given mole fractions or molar flows."""
    total = sum(composition.values()) if basis == "molar_flow" else 1.0
    if total == 0.0:
        return 0.0
    return sum(
        (n / total) * enthalpy_J_mol(sp, T_K, T_ref_K)
        for sp, n in composition.items()
        if sp in SHOMATE
    )
