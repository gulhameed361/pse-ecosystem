"""Ideal-gas thermodynamic properties.

Shomate equation (NIST Webbook form):
    Cp°(T) = A + B*t + C*t² + D*t³ + E/t²          [J/mol/K]
    H°(T) - H°(298) = A*t + B*t²/2 + C*t³/3 + D*t⁴/4 - E/t + F - H   [kJ/mol]

where t = T[K] / 1000.

Coefficients and formation enthalpies are taken directly from the NIST
Chemistry WebBook (https://webbook.nist.gov) — the same source used by the
IDAES generic property framework, enabling direct cross-validation.

Valid range: 298 K – 1200 K for most species listed.

v1.6 update
-----------
The ``SHOMATE``, ``MW``, and ``H_REF_298`` dictionaries are now rebuilt from
the unified component registry in ``components.py``. The public interface,
keys, and numeric values are byte-identical to v1.5.3 — only the data source
has moved. New v1.6 species (cubic-EOS-only) do **not** appear in these
dictionaries because they lack Shomate coefficients; the ``if species in
SHOMATE`` guards used throughout the unit models therefore behave exactly
as before.
"""

from __future__ import annotations

import math
from typing import Dict, List

from pse_ecosystem.models.properties.components import (
    _build_hf_298_dict,
    _build_mw_dict,
    _build_shomate_dict,
)

# ── Shomate coefficients ──────────────────────────────────────────────────────
# Keys: A, B, C, D, E, F, H  (all in kJ/mol or J/mol/K as per NIST convention)
# H° - H°(298.15 K) = A*t + B*t²/2 + C*t³/3 + D*t⁴/4 - E/t + F - H  [kJ/mol]
# Cp°(T) = A + B*t + C*t² + D*t³ + E/t²                                [J/mol/K]
SHOMATE: Dict[str, Dict[str, float]] = _build_shomate_dict()

# Molecular weights [g/mol]
MW: Dict[str, float] = _build_mw_dict()

# Standard enthalpy of formation at 298.15 K [J/mol]  (= H field × 1000)
H_REF_298: Dict[str, float] = _build_hf_298_dict()

_R_GAS = 8.314462  # J/mol/K


# ── Pure-component functions ──────────────────────────────────────────────────


def cp_J_mol_K(species: str, T_K: float) -> float:
    """Shomate Cp [J/mol/K] at T_K.  Valid ~298–1200 K."""
    p = SHOMATE[species]
    t = T_K / 1000.0
    return p["A"] + p["B"] * t + p["C"] * t ** 2 + p["D"] * t ** 3 + p["E"] / t ** 2


def dcp_dT_J_mol_K2(species: str, T_K: float) -> float:
    """Closed-form ``dCp/dT`` [J/mol/K²] at T_K.

    Used by analytical Jacobians of energy-balance residuals (v1.6.1 P.4).
    Differentiating ``Cp(T) = A + B·t + C·t² + D·t³ + E/t²`` with ``t = T/1000``
    gives ``dCp/dt = B + 2C·t + 3D·t² − 2E/t³``, then ``dCp/dT = (1/1000)·dCp/dt``.
    """
    p = SHOMATE[species]
    t = T_K / 1000.0
    dCp_dt = p["B"] + 2.0 * p["C"] * t + 3.0 * p["D"] * t * t - 2.0 * p["E"] / (t ** 3)
    return dCp_dt / 1000.0


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
    """Heat-capacity ratio Cp/Cv for an ideal gas at T_K.

    Guards against the Shomate polynomial dipping below R = 8.314 J/mol/K
    at low temperatures (some species have a negative A coefficient and a
    Cp(T) that becomes unphysically small near 200 K). When that happens
    we floor Cv at 1 J/mol/K so gamma stays finite and positive; the caller
    is responsible for staying inside each species' valid T range.
    """
    cp = cp_J_mol_K(species, T_K)
    cv = max(cp - _R_GAS, 1.0)
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
