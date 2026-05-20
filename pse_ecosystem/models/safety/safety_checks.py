"""Post-solve engineering safety checks for PSE Ecosystem.

These functions are pure-Python utilities:
- No imports from pse_ecosystem.* (Layer boundary compliant)
- No side effects; all inputs → outputs
- Called exclusively POST-SOLVE from flowsheet_service.compute_safety_margins()
- Never entered into residual(), bounds(), or the LP/NLP objective

ASME reference: Section VIII Division 1 UG-27(c)(1), cylindrical shells.
Flammability reference: Le Chatelier (1891) mixing rule; NFPA 68.
"""

from __future__ import annotations

import math
from typing import Dict, List


# ── Flammability database [vol% in air] ──────────────────────────────────────

_LE_CHATELIER_DB: Dict[str, Dict[str, float]] = {
    "H2":   {"LFL": 4.0,   "UFL": 75.0},
    "CO":   {"LFL": 12.5,  "UFL": 74.0},
    "CH4":  {"LFL": 5.0,   "UFL": 15.0},
    "C2H6": {"LFL": 3.0,   "UFL": 12.4},
    "C3H8": {"LFL": 2.1,   "UFL": 9.5},
}

# Default ASME allowable stress: SA-516 Grade 70 carbon steel at ≤ 300 °C
_DEFAULT_ALLOWABLE_STRESS_PA: float = 138_000_000.0  # 138 MPa = 20,000 psi

# Default joint efficiency: full radiography (seamless or 100% X-ray)
_DEFAULT_JOINT_EFFICIENCY: float = 1.0


# ── ASME VIII Div. 1 UG-27(c)(1) ─────────────────────────────────────────────

def asme_minimum_wall_thickness(
    pressure_Pa: float,
    inner_radius_m: float,
    allowable_stress_Pa: float = _DEFAULT_ALLOWABLE_STRESS_PA,
    joint_efficiency: float = _DEFAULT_JOINT_EFFICIENCY,
) -> float:
    """Minimum wall thickness for a cylindrical shell under internal pressure.

    ASME Section VIII Division 1 Equation UG-27(c)(1):

        t = P * R / (S * E - 0.6 * P)

    Parameters
    ----------
    pressure_Pa :
        Internal design pressure [Pa].
    inner_radius_m :
        Inner radius R [m].
    allowable_stress_Pa :
        Maximum allowable stress S [Pa].
        Default: 138 MPa (SA-516-70 carbon steel, ≤ 300 °C).
    joint_efficiency :
        Weld joint efficiency E [-].  Range 0.6–1.0;
        1.0 = full radiography (seamless pipe or 100 % X-ray).

    Returns
    -------
    float
        Minimum required wall thickness [m].

    Raises
    ------
    ValueError
        If the denominator S·E - 0.6·P ≤ 0 (pressure exceeds formula validity
        per ASME UG-27 applicability limit P/(S·E) < 0.385).
    """
    denom = allowable_stress_Pa * joint_efficiency - 0.6 * pressure_Pa
    if denom <= 0.0:
        ratio = pressure_Pa / (allowable_stress_Pa * joint_efficiency)
        raise ValueError(
            f"ASME UG-27(c)(1) formula not valid: P/(S·E) = {ratio:.4f} ≥ 0.385. "
            "Use ASME UG-27(c)(2) or Division 2 design rules for this pressure."
        )
    return (pressure_Pa * inner_radius_m) / denom


# ── Operating pressure margin ─────────────────────────────────────────────────

def operating_pressure_margin(
    P_operating_Pa: float,
    P_design_Pa: float,
) -> float:
    """Fractional margin between operating pressure and Maximum Allowable Working Pressure.

        margin = (P_design - P_operating) / P_design

    Parameters
    ----------
    P_operating_Pa :
        Actual operating pressure from the solver solution [Pa].
    P_design_Pa :
        Maximum Allowable Working Pressure (MAWP) [Pa].

    Returns
    -------
    float
        Positive → operating below design pressure (safe).
        Zero      → at design pressure (alarm threshold).
        Negative  → above design pressure (violation).

    Raises
    ------
    ValueError
        If P_design_Pa ≤ 0.
    """
    if P_design_Pa <= 0.0:
        raise ValueError(f"P_design_Pa must be > 0, got {P_design_Pa}")
    return (P_design_Pa - P_operating_Pa) / P_design_Pa


# ── Le Chatelier flammability ─────────────────────────────────────────────────

def flammability_margins(
    composition_mol_fractions: Dict[str, float],
) -> Dict[str, float]:
    """Estimate mixture LFL and UFL for a process stream via Le Chatelier's rule.

    Le Chatelier (1891) for a mixture of flammable gases in air:

        LFL_mix = 1 / Σ_i( x_i / LFL_i )
        UFL_mix = 1 / Σ_i( x_i / UFL_i )

    where x_i are the mole fractions of the **flammable species only**,
    renormalized to sum to 1 before applying the formula.

    Non-flammable species (N₂, CO₂, H₂O, O₂, Ar, …) are silently ignored.

    Parameters
    ----------
    composition_mol_fractions :
        Mapping of species name → mole fraction (0–1 scale).
        Keys are matched against the Le Chatelier database (case-sensitive).

    Returns
    -------
    dict with keys:
        ``LFL_vol_pct``              — mixture lower flammability limit [vol%]
        ``UFL_vol_pct``              — mixture upper flammability limit [vol%]
        ``mixture_flammable_fraction`` — total mol fraction of flammable species
                                         in the stream (not renormalized) [-]
        ``margin_to_LFL_vol_pct``   — LFL_mix minus (flammable_fraction × 100).
                                       Negative → flammable region; positive → below LFL.
        ``margin_to_UFL_vol_pct``   — UFL_mix minus (flammable_fraction × 100).
                                       Positive → flammable region; negative → above UFL (too rich).
        ``flammable_species``        — list of species names that matched the database

    Raises
    ------
    ValueError
        If no recognised flammable species are present in the composition dict.
    """
    # Identify flammable components
    flammable: Dict[str, float] = {
        sp: frac
        for sp, frac in composition_mol_fractions.items()
        if sp in _LE_CHATELIER_DB and frac > 0.0
    }
    if not flammable:
        raise ValueError(
            "No recognised flammable species found in composition. "
            f"Known species: {sorted(_LE_CHATELIER_DB)}. "
            f"Provided species: {sorted(composition_mol_fractions)}."
        )

    mixture_flammable_fraction = sum(flammable.values())

    # Renormalize flammable fractions to sum = 1 for Le Chatelier
    total_flamm = mixture_flammable_fraction
    if total_flamm <= 0.0:
        raise ValueError("Sum of flammable mol fractions is zero.")

    x_renorm = {sp: frac / total_flamm for sp, frac in flammable.items()}

    # Le Chatelier sums
    lfl_sum = sum(x / _LE_CHATELIER_DB[sp]["LFL"] for sp, x in x_renorm.items())
    ufl_sum = sum(x / _LE_CHATELIER_DB[sp]["UFL"] for sp, x in x_renorm.items())

    lfl_mix = 1.0 / lfl_sum
    ufl_mix = 1.0 / ufl_sum

    # The total flammable content of the stream in vol%
    flammable_pct = mixture_flammable_fraction * 100.0

    return {
        "LFL_vol_pct":               lfl_mix,
        "UFL_vol_pct":               ufl_mix,
        "mixture_flammable_fraction": mixture_flammable_fraction,
        "margin_to_LFL_vol_pct":     lfl_mix - flammable_pct,
        "margin_to_UFL_vol_pct":     ufl_mix - flammable_pct,
        "flammable_species":          sorted(flammable),
    }


# ── Public surface ────────────────────────────────────────────────────────────

__all__ = [
    "asme_minimum_wall_thickness",
    "operating_pressure_margin",
    "flammability_margins",
    "_LE_CHATELIER_DB",
    "_DEFAULT_ALLOWABLE_STRESS_PA",
    "_DEFAULT_JOINT_EFFICIENCY",
]
