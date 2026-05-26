"""Per-unit-type parameter descriptors + display-unit conversion.

v1.6.1 P.9: extracted from ``flowsheet_service.py`` (ParamSpec + the
``_bounds_specs`` table + UMS display-unit conversion helpers). The
facade re-exports every public symbol for back-compat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── ParamSpec — per-unit-type parameter descriptor for the Custom Flowsheet UI ─

@dataclass
class ParamSpec:
    """Describes one editable parameter for a unit type in the Custom Flowsheet builder.

    The UI uses this to render a pre-filled form instead of requiring users to
    know parameter names and default values from memory.
    """

    name: str           # key in the params dict passed to _instantiate_unit
    label: str          # human-readable UI label
    dtype: str          # "float" | "int" | "select"
    default: Any        # pre-filled value shown in the UI
    options: List[str] = field(default_factory=list)   # for dtype="select"
    unit: str = ""      # physical unit string shown in brackets, e.g. "°C"
    help: str = ""      # tooltip shown in the UI
    group: str = ""     # "bounds" → rendered in collapsed Advanced Bounds expander


def _bounds_specs(
    feed_max: float = 1e4,
    T_min: float = 200.0,
    T_max: float = 2000.0,
    P_min: float = 1e3,
    P_max: float = 1e8,
    W_max: Optional[float] = None,
    Q_max: Optional[float] = None,
    include_tp: bool = True,
) -> List[ParamSpec]:
    """Return standard Advanced Bounds ParamSpec entries for a unit.

    These are rendered in a collapsed "Advanced Bounds" expander in the
    Custom Flowsheet Builder so casual users don't see them but power users
    can scale up or constrain the unit.
    """
    specs = [
        ParamSpec("feed_max", "Max Flow (all species)", "float", feed_max,
                  unit="mol/s",
                  help="Upper bound on every molar flow variable in this unit. "
                       "Increase for high-throughput industrial scale.",
                  group="bounds"),
    ]
    if include_tp:
        specs += [
            ParamSpec("T_min", "Min Temperature", "float", T_min,
                      unit="K", help="Lower temperature bound.", group="bounds"),
            ParamSpec("T_max", "Max Temperature", "float", T_max,
                      unit="K", help="Upper temperature bound.", group="bounds"),
            ParamSpec("P_min", "Min Pressure", "float", P_min,
                      unit="Pa", help="Lower pressure bound.", group="bounds"),
            ParamSpec("P_max", "Max Pressure", "float", P_max,
                      unit="Pa", help="Upper pressure bound.", group="bounds"),
        ]
    if W_max is not None:
        specs.append(
            ParamSpec("W_max", "Max Work/Power", "float", W_max,
                      unit="W", help="Upper bound on shaft work or electrical power.",
                      group="bounds")
        )
    if Q_max is not None:
        specs.append(
            ParamSpec("Q_max_kW", "Max Heat Duty", "float", Q_max,
                      unit="kW", help="Upper bound on heat duty (cooling or heating).",
                      group="bounds")
        )
    return specs


UNIT_PARAM_SPECS: Dict[str, List[ParamSpec]] = {
    "BiomassStorageHF": [
        ParamSpec("biomass_type", "Biomass Type", "select", "Pine Wood",
                  ["Pine Wood", "Miscanthus", "Wheat Straw"]),
        ParamSpec("T_preheat_C", "Preheat Temperature", "float", 200.0,
                  unit="°C", help="Target preheat temperature for dry biomass"),
    ] + _bounds_specs(feed_max=1000.0, include_tp=False),

    "BiomassGasifierHF": [
        ParamSpec("T_gasifier_C", "Gasifier Temperature", "float", 800.0,
                  unit="°C", help="Thermochemical equilibrium temperature"),
        ParamSpec("gasifying_agent", "Gasifying Agent", "select", "Steam",
                  ["Steam", "Air"], help="Steam gives higher H₂ yield; Air is cheaper"),
        ParamSpec("P_atm", "Pressure", "float", 1.0,
                  unit="atm", help="Operating pressure"),
    ] + _bounds_specs(feed_max=1000.0, include_tp=False),

    "WGSReactorHF": [
        ParamSpec("T_wgs_C", "WGS Temperature", "float", 400.0,
                  unit="°C", help="400 °C = High-Temperature Shift; 220 °C = Low-Temperature Shift"),
    ] + _bounds_specs(feed_max=1e4, include_tp=False),

    "CoolerHF": [
        ParamSpec("T_out_K", "Outlet Temperature", "float", 310.0,
                  unit="K", help="Fixed cooling target temperature"),
        ParamSpec("cooling_water_price_USD_per_GJ", "Cooling Water Price", "float", 0.35,
                  unit="USD/GJ", help="Utility cost for cooling water; affects OPEX"),
    ] + _bounds_specs(feed_max=1_000.0, T_min=200.0, T_max=2000.0,
                      P_min=1e3, P_max=1e8, Q_max=1e7),

    "SeparatorHF": [
        ParamSpec("n_outlets", "Number of Outlets", "int", 2,
                  help="Typically 2 for binary split; up to 4 supported"),
    ] + _bounds_specs(),

    "Compressor": [
        ParamSpec("eta_isentropic", "Isentropic Efficiency", "float", 0.78,
                  unit="—", help="0–1; typical industrial range 0.70–0.85"),
        ParamSpec("P_out_Pa", "Outlet Pressure", "float", 500_000.0,
                  unit="Pa", help="5e5 Pa = 5 bar; 5e6 Pa = 50 bar"),
        ParamSpec("electricity_price_USD_per_kWh", "Electricity Price", "float", 0.05,
                  unit="USD/kWh", help="Used to compute compressor electricity OPEX"),
    ] + _bounds_specs(W_max=1e9),

    "HeatExchangerNTU": [
        ParamSpec("UA_W_per_K", "UA Product", "float", 5000.0,
                  unit="W/K", help="Overall heat transfer coefficient × area"),
    ] + _bounds_specs(),

    "MixerHF": [
        ParamSpec("n_inlets", "Number of Inlets", "int", 2,
                  help="Number of feed streams entering the mixer"),
    ] + _bounds_specs(),

    "FlashVLHF": [
        ParamSpec("T_min", "T min", "float", 250.0, unit="K"),
        ParamSpec("T_max", "T max", "float", 550.0, unit="K"),
        ParamSpec("P_min", "P min", "float", 1e3,  unit="Pa"),
        ParamSpec("P_max", "P max", "float", 1e7,  unit="Pa"),
    ] + _bounds_specs(include_tp=False),

    "StoichiometricReactor": [
        ParamSpec("feed_max", "Max Feed Flow", "float", 50.0,
                  unit="mol/s", help="Upper bound on inlet flow variables"),
    ],

    "MethanationReactor": [
        ParamSpec("T_rx_K", "Reactor Temperature", "float", 673.0,
                  unit="K", help="Sabatier reaction temperature (400 °C default)"),
    ] + _bounds_specs(),

    "TVSAContactor": [
        ParamSpec("eta_cap", "CO₂ Capture Efficiency", "float", 0.85,
                  unit="—", help="Fraction of inlet CO₂ captured (0–1)"),
        ParamSpec("T_des_K", "Desorption Temperature", "float", 393.0,
                  unit="K", help="120 °C default; higher = more regen energy"),
        ParamSpec("dH_des_kJ_per_mol", "Desorption Enthalpy", "float", 70.0,
                  unit="kJ/mol", help="Sorbent regeneration enthalpy per mol CO₂"),
        ParamSpec("y_co2_atm", "Ambient CO₂ (ppm)", "float", 415.0,
                  unit="ppm", help="Atmospheric CO₂ concentration (default 415 ppm 2024)"),
    ],

    "ElectrolyserHF": [
        ParamSpec("eta_elec", "Electrolyser Efficiency", "float", 0.70,
                  unit="—", help="HHV basis; typical PEM 0.65–0.75"),
        ParamSpec("capex_USD_per_kW", "Stack CAPEX", "float", 1_200.0,
                  unit="USD/kW", help="Purchase cost per kW installed (NREL 2024: 1200 USD/kW)"),
    ] + _bounds_specs(feed_max=1e5, include_tp=False, W_max=1e7),

    "CHPUnit": [
        ParamSpec("eta_comb", "Combustion Efficiency", "float", 0.95, unit="—"),
        ParamSpec("eta_isentropic", "Turbine Isentropic Efficiency", "float", 0.85, unit="—"),
        ParamSpec("eta_hrec", "Heat Recovery Efficiency", "float", 0.85, unit="—",
                  help="HRSG efficiency — fraction of turbine exhaust heat recovered"),
        ParamSpec("lambda_air", "Excess Air Ratio", "float", 1.1, unit="—",
                  help="1.0 = stoichiometric; >1.0 = excess air (1.1 typical for stable combustion)"),
    ] + _bounds_specs(T_min=273.0, T_max=1500.0, P_min=1e4, P_max=5e6, W_max=1e9),

    # ── v1.4.0 audit H11: extra UI-selectable types ──────────────────────────
    "Pump": [
        ParamSpec("eta_pump", "Pump Efficiency", "float", 0.75,
                  unit="—", help="Mechanical efficiency, 0–1; typical 0.65–0.85"),
        ParamSpec("P_out_Pa", "Outlet Pressure", "float", 1_000_000.0,
                  unit="Pa", help="Set to 0 to leave P_out free"),
        ParamSpec("density_kg_m3", "Liquid Density", "float", 1000.0,
                  unit="kg/m³", help="Water=1000, methanol=791, glycol=1113 kg/m³"),
        ParamSpec("molar_mass_kg_mol", "Molar Mass", "float", 0.018,
                  unit="kg/mol", help="Water=0.018, methanol=0.032, ethanol=0.046 kg/mol"),
        ParamSpec("electricity_price_USD_per_kWh", "Electricity Price", "float", 0.05,
                  unit="USD/kWh", help="Used to compute pump electricity OPEX"),
    ] + _bounds_specs(W_max=1e9),

    "Valve": [
        ParamSpec("Cv", "Valve Coefficient (Cv)", "float", 1.0,
                  unit="—", help="Flow coefficient; sets the throttle resistance"),
        ParamSpec("P_out_Pa", "Outlet Pressure", "float", 200_000.0,
                  unit="Pa", help="Throttle target pressure"),
    ] + _bounds_specs(),

    "ShellTubeHX": [
        ParamSpec("U_W_per_m2_K", "Overall U", "float", 500.0,
                  unit="W/m²/K", help="Heat-transfer coefficient"),
        ParamSpec("A_m2", "Heat-transfer Area", "float", 16.0,
                  unit="m²", help="Total tube surface area"),
        ParamSpec("n_shell_passes", "Shell Passes", "int", 1,
                  help="LMTD F-factor depends on the shell/tube pass combination"),
        ParamSpec("n_tube_passes", "Tube Passes", "int", 2,
                  help="LMTD F-factor depends on the shell/tube pass combination"),
    ] + _bounds_specs(),

    "H2SeparatorPSA": [
        ParamSpec("H2_recovery", "H₂ Recovery", "float", 0.85,
                  unit="—", help="Fraction of feed H₂ recovered to product, 0–1"),
        ParamSpec("electricity_price_USD_per_kWh", "Electricity Price", "float", 0.05,
                  unit="USD/kWh", help="PSA electricity OPEX cost rate"),
    ] + _bounds_specs(include_tp=False),

    "GibbsReactor": [
        ParamSpec("T_max", "Max Temperature", "float", 2000.0,
                  unit="K", help="Upper bound used by the inner Gibbs minimiser"),
    ] + _bounds_specs(),

    "EquilibriumReactor": [
        ParamSpec("T_ref_K", "Reference Temperature", "float", 673.0,
                  unit="K", help="van't Hoff reference for Keq(T) scaling"),
        ParamSpec("Keq_ref", "Reference Keq", "float", 8.9,
                  unit="—", help="Equilibrium constant at T_ref. Default reaction = WGS"),
    ] + _bounds_specs(),

    "DistillationHF": [
        ParamSpec("hk", "Heavy Key Species", "select", "toluene",
                  ["toluene", "benzene", "methanol", "water"],
                  help="Component recovered in the bottoms"),
        ParamSpec("lk", "Light Key Species", "select", "benzene",
                  ["benzene", "toluene", "methanol", "water"],
                  help="Component recovered in the distillate"),
        ParamSpec("R_over_Rmin", "Reflux Multiplier (R/Rmin)", "float", 1.3,
                  unit="—", help="Operating reflux as a multiple of minimum reflux"),
        ParamSpec("T_op_K", "Operating Temperature", "float", 350.0,
                  unit="K", help="T used to evaluate K-values"),
    ] + _bounds_specs(T_min=250.0, T_max=600.0, P_min=1e3, P_max=5e6),
    # Toy units and units with no tunable params default to empty list (components-only)
}


def get_unit_param_specs(utype: str) -> List[ParamSpec]:
    """Return the list of ParamSpec descriptors for *utype*, or [] if none defined."""
    return UNIT_PARAM_SPECS.get(utype, [])


def get_unit_bounds_specs(utype: str) -> List[ParamSpec]:
    """Return only the 'bounds' group ParamSpec entries for *utype*."""
    return [s for s in UNIT_PARAM_SPECS.get(utype, []) if s.group == "bounds"]


def get_unit_main_specs(utype: str) -> List[ParamSpec]:
    """Return non-bounds ParamSpec entries (the main parameter form)."""
    return [s for s in UNIT_PARAM_SPECS.get(utype, []) if s.group != "bounds"]


# ── Unit Management System (UMS) — Layer-1 display↔native conversion ─────────
#
# Backend Layer-3 models accept parameters in the unit each ParamSpec declares
# (e.g. "°C" for T_gasifier_C, "Pa" for P_out_Pa, "atm" for P_atm). Internally
# every model converts to SI before evaluating residuals / Jacobians, so the
# numerical core is SI-native even though parameter intake is mixed.
#
# The UMS lets the user pick a *display unit* for any float parameter; the UI
# stores the user's value in that display unit, then converts to the
# ParamSpec's native unit before passing to ``build_custom_flowsheet``. Nothing
# downstream of this module sees display units.

# Each family lists units in canonical order: first key is the SI baseline.
# Each value is a (to_si, from_si) lambda pair operating on float values.
_TEMP_K = {
    "K":  (lambda x: x,                     lambda x: x),
    "°C": (lambda x: x + 273.15,            lambda x: x - 273.15),
    "°F": (lambda x: (x - 32) * 5 / 9 + 273.15, lambda x: (x - 273.15) * 9 / 5 + 32),
}
_PRESS_Pa = {
    "Pa":  (lambda x: x,           lambda x: x),
    "kPa": (lambda x: x * 1e3,     lambda x: x / 1e3),
    "bar": (lambda x: x * 1e5,     lambda x: x / 1e5),
    "atm": (lambda x: x * 101325.0, lambda x: x / 101325.0),
    "psi": (lambda x: x * 6894.757, lambda x: x / 6894.757),
}
_MASS_FLOW_kgps = {
    "kg/s": (lambda x: x,         lambda x: x),
    "kg/h": (lambda x: x / 3600.0, lambda x: x * 3600.0),
    "t/h":  (lambda x: x / 3.6,    lambda x: x * 3.6),
}
_MASS_kg = {
    "kg": (lambda x: x,          lambda x: x),
    "t":  (lambda x: x * 1000.0, lambda x: x / 1000.0),
}
_POWER_W = {
    "W":  (lambda x: x,         lambda x: x),
    "kW": (lambda x: x * 1e3,   lambda x: x / 1e3),
    "MW": (lambda x: x * 1e6,   lambda x: x / 1e6),
}
_ENERGY_J = {
    "J":  (lambda x: x,         lambda x: x),
    "kJ": (lambda x: x * 1e3,   lambda x: x / 1e3),
    "MJ": (lambda x: x * 1e6,   lambda x: x / 1e6),
}

UNIT_FAMILIES: Dict[str, Dict[str, Tuple[Callable[[float], float], Callable[[float], float]]]] = {
    "temperature": _TEMP_K,
    "pressure":    _PRESS_Pa,
    "mass_flow":   _MASS_FLOW_kgps,
    "mass":        _MASS_kg,
    "power":       _POWER_W,
    "energy":      _ENERGY_J,
}


def _family_of(unit: str) -> Optional[str]:
    """Return the family name (e.g. 'temperature') containing *unit*, or None."""
    for fam_name, table in UNIT_FAMILIES.items():
        if unit in table:
            return fam_name
    return None


def supported_display_units(native_unit: str) -> List[str]:
    """All display units the user may pick for a parameter whose native unit is *native_unit*.

    Returns an empty list if the unit has no recognised conversion family
    (e.g. "—" for dimensionless, "W/K" for UA products, "mol/s" — these
    stay as-is in the UI).
    """
    fam = _family_of(native_unit)
    if not fam:
        return []
    return list(UNIT_FAMILIES[fam].keys())


def to_native(value: float, display_unit: str, native_unit: str) -> float:
    """Convert *value* from *display_unit* into *native_unit*.

    No-op when display_unit == native_unit or when no conversion path exists.
    """
    if display_unit == native_unit:
        return value
    fam = _family_of(native_unit)
    if not fam or display_unit not in UNIT_FAMILIES[fam]:
        return value
    table = UNIT_FAMILIES[fam]
    to_si, _   = table[display_unit]
    _, from_si = table[native_unit]
    return from_si(to_si(value))


def from_native(value: float, native_unit: str, display_unit: str) -> float:
    """Convert *value* from *native_unit* into *display_unit* (inverse of to_native)."""
    return to_native(value, display_unit=native_unit, native_unit=display_unit)


def si_baseline_of(unit: str) -> Optional[str]:
    """Return the SI baseline unit for the family containing *unit* (e.g. 'K' for '°C').

    Used by the Excel exporter to annotate variable columns with the canonical
    SI tag the solver internally operates on.
    """
    fam = _family_of(unit)
    if not fam:
        return None
    return next(iter(UNIT_FAMILIES[fam]))
