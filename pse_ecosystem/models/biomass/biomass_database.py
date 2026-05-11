"""Hardcoded biomass properties database.

All elemental fractions are dry mass fractions (including ash, excluding
moisture).  Constraint: C + H + O + N + ash ≈ 1.0.

MC  : moisture content as fraction of total wet mass.
LHV : lower heating value [MJ/kg dry].

Source: aggregated from IEA Bioenergy, Phyllis2 (ECN), and literature
        compilations consistent with B-HYPSYS reference data.
"""

from __future__ import annotations

from typing import Dict

# ── Atomic weights (g/mol) ────────────────────────────────────────────────────
MW = {"C": 12.011, "H": 1.008, "O": 15.999, "N": 14.007}

# ── Biomass database ──────────────────────────────────────────────────────────
# Keys: "C", "H", "O", "N" → dry mass fractions
#       "ash"               → dry mass fraction
#       "MC"                → moisture content (fraction of wet mass)
#       "LHV_MJ_kg"         → lower heating value [MJ/kg dry]
BIOMASS_DB: Dict[str, Dict] = {
    "Pine Wood": {
        "C": 0.497, "H": 0.062, "O": 0.418, "N": 0.002,
        "ash": 0.021, "MC": 0.10, "LHV_MJ_kg": 17.6,
    },
    "Miscanthus": {
        "C": 0.443, "H": 0.056, "O": 0.439, "N": 0.006,
        "ash": 0.056, "MC": 0.15, "LHV_MJ_kg": 16.2,
    },
    "Rice Straw": {
        "C": 0.363, "H": 0.044, "O": 0.340, "N": 0.009,
        "ash": 0.244, "MC": 0.10, "LHV_MJ_kg": 12.4,
    },
    "Wheat Straw": {
        "C": 0.433, "H": 0.055, "O": 0.467, "N": 0.005,
        "ash": 0.040, "MC": 0.08, "LHV_MJ_kg": 15.1,
    },
    "Willow": {
        "C": 0.472, "H": 0.059, "O": 0.441, "N": 0.006,
        "ash": 0.022, "MC": 0.45, "LHV_MJ_kg": 16.4,
    },
    "MSW": {
        "C": 0.441, "H": 0.064, "O": 0.323, "N": 0.018,
        "ash": 0.154, "MC": 0.20, "LHV_MJ_kg": 13.2,
    },
    "Sewage Sludge": {
        "C": 0.336, "H": 0.060, "O": 0.200, "N": 0.053,
        "ash": 0.351, "MC": 0.70, "LHV_MJ_kg": 9.1,
    },
    "Sugarcane Bagasse": {
        "C": 0.443, "H": 0.057, "O": 0.454, "N": 0.004,
        "ash": 0.042, "MC": 0.50, "LHV_MJ_kg": 14.7,
    },
}

_REQUIRED_KEYS = {"C", "H", "O", "N", "ash", "MC", "LHV_MJ_kg"}


def get_biomass(name: str) -> Dict:
    """Return properties dict for *name*. Raises ``KeyError`` if not found."""
    if name not in BIOMASS_DB:
        raise KeyError(
            f"Biomass '{name}' not in database. "
            f"Available: {list(BIOMASS_DB)}"
        )
    return BIOMASS_DB[name]


def element_feeds_mol_s(name: str, dry_feed_kg_s: float) -> Dict[str, float]:
    """Compute molar element flows [mol/s] from dry biomass feed rate [kg/s].

    Returns dict with keys "C", "H", "O", "N" (mol/s).

    Unit conversion: dry_feed [kg/s] × element fraction [kg_el/kg] × 1000 [g/kg]
                     / MW [g/mol] = [mol/s].
    """
    b = get_biomass(name)
    return {
        "C": dry_feed_kg_s * 1000.0 * b["C"] / MW["C"],
        "H": dry_feed_kg_s * 1000.0 * b["H"] / MW["H"],
        "O": dry_feed_kg_s * 1000.0 * b["O"] / MW["O"],
        "N": dry_feed_kg_s * 1000.0 * b["N"] / MW["N"],
    }
