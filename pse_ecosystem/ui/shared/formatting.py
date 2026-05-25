"""SI-unit inference for Excel / CSV export annotations.

Used by the Excel exporter and the Stream Table sheet renderer to attach
an explicit unit to every numeric value, derived from the solver
variable's name conventions:

* ``F_<species>``      → kg/s mass flow
* ``T`` / ``T_in`` / ``T_out`` → K
* ``P`` / ``P_in`` / ``P_out`` / ``P_out_Pa`` → Pa
* ``X_<reaction>``     → dimensionless conversion
* ``W_shaft`` / ``W_elec`` → W shaft work
* and so on per the suffix / prefix tables below.
"""

from __future__ import annotations


_SI_UNIT_SUFFIX_RULES = [
    # Order matters: longest / most specific suffix first to avoid being
    # short-circuited by a shorter match (e.g. ``Y_H2_kg_per_h`` must hit
    # ``_kg_per_h`` before any single-token suffix). v1.4.0 audit M11.
    ("_kg_per_h", "kg/h"),
    ("_mol_per_s", "mol/s"),
    ("_per_kWh",   "USD/kWh"),
    ("_per_kg",    "USD/kg"),
    ("_USD",       "USD"),
    ("_Pa",        "Pa"),
    ("_kPa",       "kPa"),
    ("_bar",       "bar"),
    ("_MW",        "MW"),
    ("_kW",        "kW"),
    ("_MJ",        "MJ"),
    ("_kJ",        "kJ"),
    ("_K",         "K"),
    ("_C",         "°C"),
]

_SI_UNIT_PREFIX_RULES = [
    ("F_", "kg/s"),
    ("n_", "mol/s"),
    ("X_", "—"),
    ("Y_", "—"),
]

_SI_UNIT_EXACT = {
    "T":         "K",
    "T_in":      "K",
    "T_out":     "K",
    "T_avg":     "K",
    "P":         "Pa",
    "P_in":      "Pa",
    "P_out":     "Pa",
    "W":         "W",
    "W_shaft":   "W",
    "W_elec":    "W",
    "Q":         "W",
    "duty":      "W",
    "duty_W":    "W",
    "H":         "J/s",
    "enthalpy":  "J/s",
}


def _infer_si_unit(var_name: str) -> str:
    """Best-effort guess at the SI unit of a solver variable from its name.

    Returns an empty string when no inference is possible — never raises.

    Implementation: a longest-suffix-wins dispatch over
    ``_SI_UNIT_SUFFIX_RULES`` eliminates the v1.3.x order-dependent bug
    where short suffixes shadowed longer ones in compound variable names
    (audit M11).
    """
    if not var_name:
        return ""
    n = var_name.strip()

    # Exact bare names first.
    if n in _SI_UNIT_EXACT:
        return _SI_UNIT_EXACT[n]

    # Longest matching suffix wins (rules are pre-sorted longest-first).
    for suffix, unit in _SI_UNIT_SUFFIX_RULES:
        if n.endswith(suffix):
            return unit

    # Prefix conventions.
    for prefix, unit in _SI_UNIT_PREFIX_RULES:
        if n.startswith(prefix):
            return unit

    return ""


__all__ = [
    "_infer_si_unit",
    "_SI_UNIT_SUFFIX_RULES",
    "_SI_UNIT_PREFIX_RULES",
    "_SI_UNIT_EXACT",
]
