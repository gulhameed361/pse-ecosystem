"""Flowsheet service bridge — the sole Layer-1 module authorised to import
from Layer-3 factories.

This module is the single gateway through which the Streamlit UI accesses
flowsheet templates.  ``app_streamlit.py`` imports ONLY from here, never
directly from ``pse_ecosystem.models.*`` or ``pse_ecosystem.flowsheets.*``.

Layer-boundary contract
------------------------
* This module lives in ``pse_ecosystem/ui/`` (Layer 1).
* It is the ONLY file in Layer 1 that imports from Layer 3.
* Nothing in ``pse_ecosystem/solvers/`` (Layer 2) may import this module.
* All Layer-3 imports are deferred inside ``_load_*`` helper functions so that
  ``import pse_ecosystem.ui.flowsheet_service`` is safe even when scipy,
  pvlib, or other optional dependencies are absent.
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


# ── ProjectEconomicsConfig ────────────────────────────────────────────────────


@dataclass
class ProjectEconomicsConfig:
    """All financial and utility parameters for a single solve run.

    Passed from Layer 1 UI to ``build_objective_extra()`` so the LP objective
    coefficients correctly reflect the user's project-economics settings.

    Notes
    -----
    ``tax_rate`` and ``inflation_rate`` are collected for completeness and
    reported in the Excel Project Economics sheet, but are NOT yet consumed
    by the v1.5.0.dev LP objective (which uses pre-tax nominal cash flows).
    They are reserved for the v1.6 after-tax DCF rollout.
    """

    # Financial
    plant_life_yr: int = 20
    interest_rate: float = 0.08       # WACC (fraction)
    tax_rate: float = 0.20            # v1.6 placeholder
    inflation_rate: float = 0.025     # v1.6 placeholder
    target_year: int = 2024           # CEPCI cost-escalation target year
    # Operational
    operating_hours_per_year: float = 8_000.0
    # Utilities / feedstocks
    electricity_price_USD_per_kWh: float = 0.05
    biomass_price_USD_per_tonne: float = 60.0
    water_price_USD_per_tonne: float = 0.5
    cooling_water_price_USD_per_GJ: float = 0.35
    carbon_tax_USD_per_tonne: float = 50.0
    # Installation cost factor for SSLW purchase → installed conversion
    lang_factor: float = 5.0

    def __post_init__(self) -> None:
        # v1.5.0.dev-AUDIT D3+D6: fail loudly on misconfiguration.
        if self.plant_life_yr <= 0:
            raise ValueError(
                f"plant_life_yr must be a positive integer, got {self.plant_life_yr}"
            )
        if self.interest_rate < 0.0:
            raise ValueError(
                f"interest_rate must be >= 0, got {self.interest_rate}"
            )
        if not (0.0 < self.operating_hours_per_year <= 8760.0):
            raise ValueError(
                f"operating_hours_per_year must be in (0, 8760], "
                f"got {self.operating_hours_per_year}"
            )
        if self.lang_factor < 1.0:
            raise ValueError(
                f"lang_factor must be >= 1.0 (installed >= purchase), got {self.lang_factor}"
            )

    @property
    def crf(self) -> float:
        """Capital Recovery Factor = i(1+i)^n / ((1+i)^n − 1)."""
        i, n = self.interest_rate, self.plant_life_yr
        if i == 0.0:
            return 1.0 / n
        return i * (1 + i) ** n / ((1 + i) ** n - 1)

    @property
    def energy_coeff(self) -> float:
        """Annual electricity cost coefficient [USD / kW / yr]."""
        return self.electricity_price_USD_per_kWh * self.operating_hours_per_year

    # CAPEX scaling coefficient for linear-capex electrolysers [USD/kW].
    # NREL 2024 reference: PEM electrolysis system ~1 200 USD/kW (stack + BoP).
    pem_capex_USD_per_kW: float = 1_200.0


@dataclass
class ProductionConfig:
    """Optional product-price model enabling meaningful NPV / IRR computation.

    When passed to ``compute_project_economics()``, annual revenue is computed
    as ``annual_production × product_price``, allowing the DCF model to
    calculate a cash flow that is not purely negative.

    All price fields default to 0, producing the pre-v1.5.3 behaviour
    (revenue = 0, NPV always negative, IRR always NaN).  Set at least one
    price to enable revenue-side economics.

    Parameters
    ----------
    h2_price_USD_per_kg :
        Green hydrogen sale price [USD/kg H₂].
        IRENA 2023 green H₂ cost target: 2–4 USD/kg by 2030.
    electricity_sale_price_USD_per_kWh :
        Electricity export price [USD/kWh].
        Used when the flowsheet exports power (e.g. CHP or gas-to-power).
    heat_sale_price_USD_per_GJ :
        Heat/steam export price [USD/GJ].
    methane_price_USD_per_GJ :
        Synthetic methane (SNG) sale price [USD/GJ].
        1 GJ ≈ 26.9 kg CH₄ at LHV (50 MJ/kg).
    """

    h2_price_USD_per_kg: float = 0.0
    electricity_sale_price_USD_per_kWh: float = 0.0
    heat_sale_price_USD_per_GJ: float = 0.0
    methane_price_USD_per_GJ: float = 0.0


# ── SafetyMarginRow — post-solve engineering safety check result ──────────────

@dataclass
class SafetyMarginRow:
    """One safety check result for a single unit.

    Produced by ``compute_safety_margins()`` after a converged solve.
    Never used inside the LP/NLP solver path.
    """

    unit_id: str
    unit_type: str
    check_type: str        # "ASME_wall_thickness" | "pressure_margin" | "flammability"
    value: float           # computed result (wall thickness [m], margin fraction, etc.)
    limit: float           # threshold for status evaluation
    status: str            # "OK" | "WARNING" | "VIOLATION"
    detail: str            # human-readable description for the UI
    radius_source: str = "params"  # "params" | "volume_derived" | "default"


# ── Objective tier taxonomy ───────────────────────────────────────────────────

OBJECTIVE_TIERS: Dict[str, List[str]] = {
    "Technical": [
        "Feasibility Only",
        "Minimize Energy",
        "Maximize H₂ Yield",
        "Minimize Specific Energy Consumption",
        "Minimize Carbon Intensity",
    ],
    "Economic": [
        "Minimize OPEX",
        "Minimize TAC",
        "Maximize NPV (Net Present Value)",
        "Maximize IRR (Internal Rate of Return)",
    ],
    "Technoeconomic": [
        "Minimize LCOH (Levelized Cost of H₂)",
        "Minimize LCOE (Levelized Cost of Energy)",
    ],
}

# Objective modes where the LP proxy is TAC minimisation but the true metric
# (NPV, IRR) is evaluated post-solve from KPIs.  The UI should display a
# banner for these so the analyst knows the LP is not directly optimising the
# labelled metric.
OBJECTIVE_LP_PROXY_NOTE: Dict[str, str] = {
    "Maximize NPV (Net Present Value)": (
        "The LP optimises a **TAC proxy** (CAPEX annualisation + OPEX). "
        "True NPV is computed post-solve and requires a revenue model "
        "(set product prices in ProductionConfig)."
    ),
    "Maximize IRR (Internal Rate of Return)": (
        "The LP optimises a **TAC proxy** (CAPEX annualisation + OPEX). "
        "True IRR is computed post-solve and requires a revenue model "
        "(set product prices in ProductionConfig)."
    ),
}


# ── Topology helpers ─────────────────────────────────────────────────────────

def _topological_unit_order(flowsheet: "BaseFlowsheet") -> List[str]:
    """Return unit_ids in feed-forward (topological) order.

    Uses Kahn's algorithm on the directed connection graph.  Units with no
    resolved ordering (cycles or isolated units) are appended in their
    declaration order.  The result is used to identify the most-downstream
    unit without relying on lexicographic naming.
    """
    unit_ids: List[str] = [u.unit_id for u in flowsheet.units]
    # Build adjacency: predecessor count and successor sets.
    in_degree: Dict[str, int] = {uid: 0 for uid in unit_ids}
    successors: Dict[str, List[str]] = {uid: [] for uid in unit_ids}
    for conn in getattr(flowsheet, "connections", []):
        src = getattr(conn, "var_a", "").split(".", 1)[0]
        tgt = getattr(conn, "var_b", "").split(".", 1)[0]
        if src == tgt or src not in in_degree or tgt not in in_degree:
            continue
        if tgt not in successors.get(src, []):
            successors[src].append(tgt)
            in_degree[tgt] += 1

    queue = [uid for uid in unit_ids if in_degree[uid] == 0]
    order: List[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for succ in successors.get(node, []):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)
    # Append any remaining (cycle members) in declaration order.
    remaining = [uid for uid in unit_ids if uid not in set(order)]
    return order + remaining


def _most_downstream_h2_outlet(
    flowsheet: "BaseFlowsheet",
    all_vars: List[str],
) -> Optional[str]:
    """Return the H₂ outlet variable of the most-downstream unit in the chain.

    Walks the topologically sorted unit list from last to first, looking for a
    unit that has an F_H2 flow variable on an outlet-like port.  Falls back to
    the lexicographically last variable if topology gives no clear answer.
    """
    def _is_h2_outlet_var(v: str) -> bool:
        parts = v.split(".")
        return (
            len(parts) >= 3
            and parts[-1].lower() == "f_h2"
            and any(tag in parts[1].lower() for tag in ("out", "product", "h2", "vapor"))
        )

    h2_vars = [v for v in all_vars if _is_h2_outlet_var(v)]
    if not h2_vars:
        # Widen fallback: any variable ending in .F_H2
        h2_vars = [v for v in all_vars if v.split(".")[-1].lower() == "f_h2"]
    if not h2_vars:
        return None

    # Build set of unit_ids that have H₂ outlet variables.
    h2_unit_vars: Dict[str, List[str]] = {}
    for v in h2_vars:
        uid = v.split(".", 1)[0]
        h2_unit_vars.setdefault(uid, []).append(v)

    # Walk topological order from last to find the most-downstream H₂ unit.
    topo = _topological_unit_order(flowsheet)
    for uid in reversed(topo):
        if uid in h2_unit_vars:
            candidates = h2_unit_vars[uid]
            # Prefer "outlet" tag over others.
            outlet_cands = [v for v in candidates if "outlet" in v.split(".", 2)[1].lower()]
            return outlet_cands[0] if outlet_cands else candidates[0]

    return sorted(h2_vars)[-1]  # lexicographic last as final fallback


# ── Type-specific Unit ID suggestions ────────────────────────────────────────

def build_objective_extra(
    flowsheet: "BaseFlowsheet",
    mode: str,
    electricity_price_USD_per_kWh: float = 0.05,
    operating_hours: float = 8_000.0,
    crf: float = 0.10,
    econ_config: Optional[ProjectEconomicsConfig] = None,
) -> tuple:
    """Compute (objective_extra, force_feasibility) for the given objective mode.

    Called by the UI's Objective Function tab before each solve.  Returns a
    two-tuple ``(extra_dict, force_feas)`` which should be applied to the
    flowsheet as::

        fs.objective_extra, fs.force_feasibility = build_objective_extra(fs, mode)

    Parameters
    ----------
    flowsheet             : assembled BaseFlowsheet
    mode                  : one of the UI objective mode labels
    electricity_price_USD_per_kWh : multiplied by annual hours to give $/kW/yr
    operating_hours       : annual operating hours (default 8 000 h/yr)
    crf                   : Capital Recovery Factor for annualising capex
    econ_config           : optional; when provided its values override the three
                            scalar arguments above for all financial calculations
    """
    # If a full economics config is provided, use it as the source of truth.
    if econ_config is not None:
        electricity_price_USD_per_kWh = econ_config.electricity_price_USD_per_kWh
        operating_hours = econ_config.operating_hours_per_year
        crf = econ_config.crf

    all_vars: List[str] = flowsheet.all_variables()
    energy_coeff = electricity_price_USD_per_kWh * operating_hours  # $/kW/yr

    # ── Feasibility Only ─────────────────────────────────────────────────────
    if mode == "Feasibility Only":
        return {}, True   # force_feasibility=True zeros out all LP cost terms

    obj: dict = {}

    # ── Minimize OPEX ────────────────────────────────────────────────────────
    # Unit objective_contribution() terms (feedstock, electricity) are ALREADY
    # injected into the LP via LinearizedModel.objective_terms.  No extra terms
    # are needed — just ensure force_feasibility is False.
    if mode == "Minimize OPEX":
        return {}, False

    # ── Energy penalty ───────────────────────────────────────────────────────
    # Add electricity price × hours on any decision variable representing
    # shaft work or electrical power draw.  Use suffix matching (preceded by
    # a dot) to avoid false positives on variables that merely contain these
    # strings (e.g. "net_electricity_kw_limit").
    _energy_modes = (
        "Minimize Energy",
        "Minimize TAC",
        "Minimize LCOH (Levelized Cost of H₂)",
        "Minimize Specific Energy Consumption",
        "Maximize NPV (Net Present Value)",
        "Maximize IRR (Internal Rate of Return)",
        "Minimize LCOE (Levelized Cost of Energy)",
    )
    _energy_suffixes = (".w_shaft", ".w_elec_kw", ".electricity_kw",
                        ".w_net_kw", ".power_kw")
    if mode in _energy_modes:
        for v in all_vars:
            lv = v.lower()
            if any(lv.endswith(sfx) for sfx in _energy_suffixes):
                obj[v] = obj.get(v, 0.0) + energy_coeff

    # ── Annualised CAPEX for linear-capex units ───────────────────────────────
    # ElectrolyserHF has strictly linear capex: capex_coeff USD/kW (default 1200
    # per NREL 2024 estimate, configurable via econ_config.pem_capex_USD_per_kW).
    # Annualised = capex_coeff × CRF per kW → inject on the W_elec_kW variable.
    # SSLW-correlated units (Compressor, HXN, vessels) have non-linear capex;
    # their costs are captured post-solve in kpis() and the Excel report.
    _capex_modes = (
        "Minimize TAC",
        "Minimize LCOH (Levelized Cost of H₂)",
        "Maximize NPV (Net Present Value)",
        "Maximize IRR (Internal Rate of Return)",
    )
    if mode in _capex_modes:
        _pem_capex = (
            econ_config.pem_capex_USD_per_kW if econ_config is not None else 1_200.0
        )
        from pse_ecosystem.models.dac.electrolyser_hf import ElectrolyserHF
        for unit in flowsheet.units:
            if isinstance(unit, ElectrolyserHF):
                w_var = next(
                    (v for v in all_vars
                     if unit.unit_id in v and v.lower().endswith(".w_elec_kw")),
                    None,
                )
                if w_var:
                    obj[w_var] = obj.get(w_var, 0.0) + _pem_capex * crf

    # ── H₂ yield maximisation ────────────────────────────────────────────────
    # Negative coefficient (−1.0) on the H₂ outlet flow of the most-downstream
    # unit in the connection graph (topology-aware, not lexicographic).
    if mode in ("Maximize H₂ Yield", "Minimize LCOH (Levelized Cost of H₂)",
                "Minimize Specific Energy Consumption"):
        best_h2_var = _most_downstream_h2_outlet(flowsheet, all_vars)
        if best_h2_var is not None:
            obj[best_h2_var] = obj.get(best_h2_var, 0.0) - 1.0

    # ── Carbon intensity minimisation ────────────────────────────────────────
    # Penalise CO₂ outlet flows by the carbon tax rate scaled to an annual cost.
    # carbon_tax [USD/tonne CO₂] × 3600 s/h × operating_hours [h/yr]
    # × 1e-3 [tonne/kg] = coefficient on F_CO2 [kg/s] → [USD/yr per kg/s]
    if mode == "Minimize Carbon Intensity":
        _ct = econ_config.carbon_tax_USD_per_tonne if econ_config else 50.0
        _carbon_coeff = _ct * 3600.0 * operating_hours * 1e-3  # USD/yr per kg/s of CO₂
        for v in all_vars:
            parts = v.split(".")
            if (len(parts) >= 3
                    and parts[-1].lower() in ("f_co2", "f_co2_captured")
                    and "out" in parts[1].lower()):
                obj[v] = obj.get(v, 0.0) + _carbon_coeff

    # ── LCOE proxy ───────────────────────────────────────────────────────────
    # Minimise cost per unit of electrical output: same energy penalty as
    # "Minimize Energy" (numerator proxy); power outlet variables get a negative
    # coefficient to reward high output (denominator proxy).
    _power_out_suffixes = (".w_net_kw", ".power_out_kw", ".w_turbine_kw",
                           ".total_useful_output_kw")
    if mode == "Minimize LCOE (Levelized Cost of Energy)":
        for v in all_vars:
            lv = v.lower()
            if any(lv.endswith(sfx) for sfx in _power_out_suffixes):
                obj[v] = obj.get(v, 0.0) - energy_coeff

    return obj, False


def _aggregate_capex_purchase_USD(flowsheet: "BaseFlowsheet",
                                   solution_x: Dict[str, float]) -> float:
    """Sum every unit's ``capex(x)`` (CE500-basis purchase cost) in USD."""
    total = 0.0
    for unit in flowsheet.units:
        try:
            total += float(unit.capex(solution_x))
        except Exception:
            # A broken unit-level capex() must not bring down the whole report.
            continue
    return total


def _aggregate_opex_annual_USD(flowsheet: "BaseFlowsheet",
                                solution_x: Dict[str, float],
                                operating_hours: float = 8000.0) -> float:
    """Sum every unit's ``opex_per_year(x, operating_hours)`` (USD/yr).

    v1.5.0.dev-AUDIT2 L3-1: ``operating_hours`` is now forwarded so units with
    ``_OPEX_CONVENTION="USD_per_second"`` (e.g., BiomassGasifierHF) scale their
    rate-basis coefficient correctly to annual USD/yr.

    The default BaseUnit implementation sums
    ``coef × x[var]`` over ``objective_contribution`` and applies the
    convention-driven conversion (see ``BaseUnit._OPEX_CONVENTION``).
    """
    total = 0.0
    for unit in flowsheet.units:
        try:
            total += float(unit.opex_per_year(solution_x, operating_hours))
        except Exception:
            continue
    return total


def _extract_h2_kg_per_s(kpis: Dict[str, float],
                          flowsheet: "BaseFlowsheet",
                          solution_x: Dict[str, float]) -> float:
    """Find the most-downstream H₂ production rate in kg/s.

    Priority order:
      1. KPI keys ending in ``H2_production_kg_s`` (PSA convention).
      2. KPI keys ending in ``H2_production_kg_h`` ÷ 3600 (PEM convention).
      3. Most-downstream ``F_H2`` outlet variable × M_H2 (assumes mol/s).
    """
    s_keys = [v for k, v in kpis.items() if k.endswith("H2_production_kg_s")]
    if s_keys:
        return max(s_keys)
    h_keys = [v for k, v in kpis.items() if k.endswith("H2_production_kg_h")]
    if h_keys:
        return max(h_keys) / 3600.0
    # Fallback: scan the LP solution for the most-downstream F_H2 outlet.
    def _is_h2_outlet(name: str) -> bool:
        parts = name.split(".")
        return len(parts) >= 3 and parts[-1].lower() == "f_h2" and "out" in parts[1].lower()
    h2_vars = sorted(v for v in solution_x if _is_h2_outlet(v))
    if h2_vars:
        # 0.002016 kg/mol — H₂ molecular weight; assumes the variable is mol/s.
        return float(solution_x[h2_vars[-1]]) * 2.016e-3
    return 0.0


def _extract_power_out_kW(kpis: Dict[str, float]) -> float:
    """Find total net electrical output across all power-producing units [kW].

    Sums across all matching KPI keys so multi-generator flowsheets (e.g. two
    CHP units) report their combined output rather than the single largest unit.

    Priority order (tried in sequence; first non-empty set wins):
      1. KPI keys ending in ``total_useful_output_kW`` (CHP combined output).
      2. KPI keys ending in ``power_out_kW`` / ``W_net_kW`` (forward-compat).
      3. KPI keys ending in ``W_elec_kW`` (PEM consumes power so this can be
         negative when electrolysers dominate — included as last resort).
    """
    for suffix in ("total_useful_output_kW", "power_out_kW", "W_net_kW"):
        vals = [v for k, v in kpis.items() if k.endswith(suffix)]
        if vals:
            return sum(vals)
    elec = [v for k, v in kpis.items() if k.endswith("W_elec_kW")]
    return sum(elec) if elec else 0.0


def compute_project_economics(
    flowsheet: "BaseFlowsheet",
    solution_x: Dict[str, float],
    kpis: Dict[str, float],
    econ_config: Optional[ProjectEconomicsConfig] = None,
    obj_config: Optional[Dict] = None,
    prod_config: Optional["ProductionConfig"] = None,
) -> List[Dict]:
    """Compute project-economics rows for the Excel 'Project Economics' sheet.

    This is the Layer-1 bridge between the solver result and the
    EconomicEngine.  All Layer-3 imports are deferred inside this function so
    that ``app_streamlit.py`` never imports from ``pse_ecosystem.models.*``
    directly — the UI audit (`tests/ui_audit.py`) enforces this boundary.

    Parameters
    ----------
    flowsheet   : ``BaseFlowsheet`` that was solved (provides per-unit capex/opex).
    solution_x  : ``SolveResult.x`` — the solution dictionary.
    kpis        : ``SolveResult.kpis`` — aggregated unit KPIs.
    econ_config : ``ProjectEconomicsConfig`` instance (uses defaults when None).
    obj_config  : Raw ``objective_config`` dict from session state (metadata only).
    prod_config : Optional ``ProductionConfig`` with product sale prices.
                  When None (default), revenue is zero and NPV/IRR are flagged
                  as "N/A — no revenue model" in the returned rows.

    Returns
    -------
    List of row dicts with keys ``Metric``, ``Value``, ``Unit``.

    Notes
    -----
    The CAPEX pipeline is:
      Σ unit.capex(x)  [CE500 purchase, USD]
        → × sslw_cepci_factor(target_year)   [target-year USD]
        → × lang_factor                      [installed cost USD]
        → × CRF(r, N)                        [USD/yr]

    The revenue pipeline (when prod_config is provided):
      H₂ revenue    = h2_kg_per_s × 3600 × op_hours × h2_price_USD_per_kg
      Power revenue = power_kW × op_hours × electricity_sale_price_USD_per_kWh
      annual_CF     = revenue − opex_annual  (pre-tax)
      NPV           = −installed_capex + CF × PVF(r, N)
      IRR           = r* such that NPV(r*) = 0
    """
    from pse_ecosystem.models.costing.economic_engine import EconomicEngine

    cfg = econ_config or ProjectEconomicsConfig()
    oc  = obj_config  or {}

    ee = EconomicEngine(
        target_year=cfg.target_year,
        plant_life_yr=cfg.plant_life_yr,
        interest_rate=cfg.interest_rate,
        operating_hours_per_year=cfg.operating_hours_per_year,
    )

    purchase_CE500 = _aggregate_capex_purchase_USD(flowsheet, solution_x)
    capex_annual   = ee.annualized_capex(purchase_CE500, lang_factor=cfg.lang_factor)
    opex_annual    = _aggregate_opex_annual_USD(
        flowsheet, solution_x, operating_hours=cfg.operating_hours_per_year,
    )
    h2_kg_s        = _extract_h2_kg_per_s(kpis, flowsheet, solution_x)
    power_kw       = _extract_power_out_kW(kpis)

    lcoh = ee.lcoh(capex_annual, opex_annual, h2_kg_s) if h2_kg_s > 0 else float("nan")
    lcoe = (
        ee.lcoe(capex_annual, opex_annual, power_kw * ee.operating_hours_per_year)
        if power_kw > 0 else float("nan")
    )
    installed = capex_annual / ee.capital_recovery_factor()

    # ── Revenue & DCF (requires ProductionConfig with non-zero prices) ───────
    # Revenue is zero when prod_config is None or all prices are zero.
    # In that case NPV is always negative (pure-cost plant) and IRR is NaN —
    # both are labelled "N/A (no revenue)" to avoid misleading the analyst.
    pc = prod_config
    revenue_annual = 0.0
    has_revenue = False
    if pc is not None:
        h2_rev  = h2_kg_s * 3600.0 * cfg.operating_hours_per_year * pc.h2_price_USD_per_kg
        pwr_rev = power_kw * cfg.operating_hours_per_year * pc.electricity_sale_price_USD_per_kWh
        revenue_annual = h2_rev + pwr_rev
        has_revenue = revenue_annual > 0.0

    annual_net_cashflow = revenue_annual - opex_annual
    npv = ee.npv(annual_net_cashflow=annual_net_cashflow, initial_capex=installed)
    irr = ee.irr(initial_capex=installed, annual_net_cashflow=annual_net_cashflow)

    import math

    def _fmt_irr(r: float) -> float:
        if math.isnan(r):
            return float("nan")
        if math.isinf(r):
            return float("inf")
        return round(r * 100.0, 4)

    _na = "N/A (no revenue model)"

    return [
        {"Metric": "Plant Life",            "Value": cfg.plant_life_yr,                          "Unit": "years"},
        {"Metric": "Discount Rate (WACC)",  "Value": round(cfg.interest_rate * 100, 2),          "Unit": "%"},
        {"Metric": "Tax Rate",              "Value": round(cfg.tax_rate * 100, 2),               "Unit": "% (informational — pre-tax model)"},
        {"Metric": "Inflation Rate",        "Value": round(cfg.inflation_rate * 100, 2),         "Unit": "% (informational — pre-tax model)"},
        {"Metric": "Target Year (CEPCI)",   "Value": cfg.target_year,                            "Unit": "—"},
        {"Metric": "CEPCI Escalation",      "Value": round(ee.sslw_cepci_factor(), 4),           "Unit": "× CE500"},
        {"Metric": "Lang Factor",           "Value": cfg.lang_factor,                            "Unit": "—"},
        {"Metric": "CRF",                   "Value": round(ee.capital_recovery_factor(), 6),     "Unit": "—"},
        {"Metric": "Operating Hours",       "Value": cfg.operating_hours_per_year,               "Unit": "h/yr"},
        {"Metric": "Electricity Price",     "Value": cfg.electricity_price_USD_per_kWh,          "Unit": "USD/kWh"},
        {"Metric": "Biomass Price",         "Value": cfg.biomass_price_USD_per_tonne,            "Unit": "USD/tonne"},
        {"Metric": "Carbon Tax",            "Value": cfg.carbon_tax_USD_per_tonne,               "Unit": "USD/tonne CO₂"},
        {"Metric": "Purchase CAPEX (CE500)", "Value": round(purchase_CE500, 2),                   "Unit": "USD"},
        {"Metric": "Installed CAPEX",       "Value": round(installed, 2),                        "Unit": "USD"},
        {"Metric": "Annualised CAPEX",      "Value": round(capex_annual, 2),                     "Unit": "USD/yr"},
        {"Metric": "Annual OPEX",           "Value": round(opex_annual, 2),                      "Unit": "USD/yr"},
        {"Metric": "Annual Revenue",        "Value": round(revenue_annual, 2) if has_revenue else _na, "Unit": "USD/yr"},
        {"Metric": "Annual Net Cash Flow",  "Value": round(annual_net_cashflow, 2) if has_revenue else _na, "Unit": "USD/yr"},
        {"Metric": "TAC",                   "Value": round(capex_annual + opex_annual, 2),       "Unit": "USD/yr"},
        {"Metric": "H₂ Production",         "Value": round(h2_kg_s, 6),                          "Unit": "kg/s"},
        {"Metric": "Power Output",          "Value": round(power_kw, 4),                         "Unit": "kW"},
        {"Metric": "LCOH",                  "Value": round(lcoh, 6) if not math.isnan(lcoh) else float("nan"), "Unit": "USD/kg H₂"},
        {"Metric": "LCOE",                  "Value": round(lcoe, 6) if not math.isnan(lcoe) else float("nan"), "Unit": "USD/kWh"},
        {"Metric": "NPV",                   "Value": round(npv, 2) if has_revenue else _na,      "Unit": "USD"},
        {"Metric": "IRR",                   "Value": _fmt_irr(irr) if has_revenue else _na,      "Unit": "%"},
        {"Metric": "Objective Mode",        "Value": oc.get("mode", "—"),                        "Unit": "—"},
    ]


# ── UI helpers (v1.5.0.dev-AUDIT3 Layer 1: UI-4/UI-1/UI-3) ───────────────────


PSE_PLOTLY_TEMPLATE: Dict[str, Any] = {
    "layout": {
        "font":            {"family": "Helvetica, Arial, sans-serif", "size": 13},
        "plot_bgcolor":    "#ffffff",
        "paper_bgcolor":   "#ffffff",
        "colorway":        ["#4a90e2", "#e07b00", "#2ca02c", "#d62728",
                            "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"],
        "xaxis":           {"gridcolor": "#e6e6e6", "zerolinecolor": "#cccccc",
                            "ticks": "outside"},
        "yaxis":           {"gridcolor": "#e6e6e6", "zerolinecolor": "#cccccc",
                            "ticks": "outside"},
        "legend":          {"bgcolor": "rgba(255,255,255,0.85)",
                            "bordercolor": "#d0d0d0", "borderwidth": 1},
        "margin":          {"l": 60, "r": 30, "t": 50, "b": 50},
    }
}
"""Unified Plotly layout template for every chart in the UI.

v1.5.0.dev-AUDIT3 UI-4: previously each plot built its own ad-hoc layout —
some white, some default grey, fonts inconsistent.  Apply via
``fig.update_layout(**PSE_PLOTLY_TEMPLATE['layout'])`` after constructing
any plotly figure.
"""


def build_sankey_data(flowsheet: "BaseFlowsheet",
                       solution_x: Dict[str, float]) -> Dict[str, List]:
    """Construct node + link arrays for a Plotly Sankey diagram of molar flows.

    Only ``F_*`` (molar/mass flow) variables are included.  Temperature and
    pressure variables are intensive quantities whose numerical magnitude
    (300–1200 K, 1e4–5e6 Pa) would swamp the actual flow values and make
    the diagram quantitatively meaningless.

    Multiple connections between the same unit pair (one per species) are
    aggregated into a single Sankey link showing the total molar flow and
    listing the components in the hover label.

    Returns a dict with keys:
        ``labels``     : node names (one per unit)
        ``sources``    : source-node index per link
        ``targets``    : target-node index per link
        ``values``     : total molar/mass flow per link [mol/s or kg/s]
        ``link_labels``: hover-text per link (component breakdown)

    v1.5.0.dev-AUDIT3 UI-1: quantitative topology view supplementing the
    static Mermaid box-and-arrow diagram.
    """
    unit_ids = [u.unit_id for u in flowsheet.units]
    name_to_idx = {uid: i for i, uid in enumerate(unit_ids)}

    # Aggregate by (src_uid, tgt_uid) to collapse per-species connections.
    pair_flow:   Dict[Tuple[int, int], float] = {}
    pair_comps:  Dict[Tuple[int, int], List[str]] = {}

    for conn in getattr(flowsheet, "connections", []):
        var_a = getattr(conn, "var_a", None)
        var_b = getattr(conn, "var_b", None)
        if not var_a or not var_b:
            continue

        # Skip intensive (T, P) variables — only molar/mass flows begin with F_
        var_leaf = var_a.split(".")[-1]
        if not var_leaf.upper().startswith("F_"):
            continue

        src_uid = var_a.split(".", 1)[0]
        tgt_uid = var_b.split(".", 1)[0]
        if src_uid == tgt_uid:
            continue  # self-loops (shared variables within one unit)
        if src_uid not in name_to_idx or tgt_uid not in name_to_idx:
            continue

        key = (name_to_idx[src_uid], name_to_idx[tgt_uid])
        flow_val = abs(float(solution_x.get(var_a, 0.0)))
        pair_flow[key] = pair_flow.get(key, 0.0) + flow_val
        comp_name = var_leaf[2:] if var_leaf.upper().startswith("F_") else var_leaf
        pair_comps.setdefault(key, []).append(f"{comp_name}={flow_val:.3g}")

    sources: List[int] = []
    targets: List[int] = []
    values:  List[float] = []
    link_labels: List[str] = []

    for (src_idx, tgt_idx), total_flow in pair_flow.items():
        sources.append(src_idx)
        targets.append(tgt_idx)
        values.append(max(total_flow, 1e-12))  # Plotly requires > 0
        link_labels.append(", ".join(pair_comps.get((src_idx, tgt_idx), [])))

    return {
        "labels":      unit_ids,
        "sources":     sources,
        "targets":     targets,
        "values":      values,
        "link_labels": link_labels,
    }


def serialize_flowsheet_config(template_key: str,
                                params: Dict[str, Any],
                                custom_cfg: Optional[Dict] = None,
                                objective_config: Optional[Dict] = None,
                                user_persona: str = "Academic") -> str:
    """Serialise a flowsheet selection + parameters to a JSON string.

    Round-trips through ``deserialize_flowsheet_config`` for save/load.

    v1.5.0.dev-AUDIT3 UI-3: reproducibility — exports everything needed to
    re-run an identical solve from a fresh session.

    v1.5.0: ``user_persona`` persisted so the reopened config restores the
    view mode (Academic / Industrial) the analyst was using.  Callers that
    omit the argument default to "Academic" for backward compatibility.
    """
    import json
    payload = {
        "schema_version": "1.5.0",
        "template_key":   template_key,
        "params":         params,
        "custom_cfg":     custom_cfg,
        "objective_config": objective_config,
        "user_persona":   user_persona,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def deserialize_flowsheet_config(blob: str) -> Dict[str, Any]:
    """Parse a JSON config emitted by ``serialize_flowsheet_config``.

    Raises ``ValueError`` with a descriptive message on bad JSON or missing
    required keys.
    """
    import json
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")
    sv = data.get("schema_version")
    if sv is None:
        raise ValueError("Missing 'schema_version' field")
    return data


_SOLVE_HISTORY_PATH = None  # lazy: set on first use to ~/.pse_ecosystem/history.jsonl


def _get_history_path():
    global _SOLVE_HISTORY_PATH
    if _SOLVE_HISTORY_PATH is None:
        import pathlib
        home = pathlib.Path.home() / ".pse_ecosystem"
        try:
            home.mkdir(parents=True, exist_ok=True)
            _SOLVE_HISTORY_PATH = home / "history.jsonl"
        except OSError:
            _SOLVE_HISTORY_PATH = False   # disable persistence on permission errors
    return _SOLVE_HISTORY_PATH


def record_solve_in_history(session_state, result, mode_label: str,
                              objective_label: str, max_entries: int = 20) -> None:
    """Append a compact record of a SolveResult to the session-state history
    AND append to ``~/.pse_ecosystem/history.jsonl`` for cross-session
    persistence (v1.5.0.dev-AUDIT4 #6).

    The in-memory list is capped at ``max_entries`` (default 20) via FIFO
    eviction; the on-disk JSONL is unbounded (the user can rotate it).
    """
    import datetime
    import json
    entry = {
        "timestamp":  datetime.datetime.now().isoformat(timespec="seconds"),
        "mode":       mode_label,
        "objective":  objective_label,
        "status":     str(result.status).split(".")[-1],
        "iterations": result.iterations,
        "obj_value":  result.objective,
        "converged":  bool(result.converged),
        "n_vars":     len(result.x),
        "n_kpis":     len(result.kpis),
        "message":    (result.message or "")[:200],
    }
    history = session_state.setdefault("solve_history", [])
    history.append(entry)
    if len(history) > max_entries:
        del history[: len(history) - max_entries]
    # Disk persistence — best-effort, never block the solve flow.
    # The file is capped at _HISTORY_MAX_DISK_ENTRIES lines to prevent unbounded
    # growth on long-running installations.
    _HISTORY_MAX_DISK_ENTRIES = 200
    path = _get_history_path()
    if path and path is not False:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            # Rotate: keep only the last _HISTORY_MAX_DISK_ENTRIES lines.
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            if len(lines) > _HISTORY_MAX_DISK_ENTRIES:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines[-_HISTORY_MAX_DISK_ENTRIES:])
        except OSError:
            pass


def load_persisted_solve_history(max_entries: int = 20) -> List[Dict]:
    """Read up to the most recent ``max_entries`` entries from
    ``~/.pse_ecosystem/history.jsonl``.  v1.5.0.dev-AUDIT4 #6.

    Returns an empty list if the file is absent or unreadable.  Used by the
    Solve History page to seed the in-memory list on first render.
    """
    import json
    path = _get_history_path()
    if not path or path is False:
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out: List[Dict] = []
    for ln in lines[-max_entries:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


TYPE_ID_SUGGESTIONS: Dict[str, str] = {
    "PEMToy":                "pem",
    "GasifierToy":           "gasifier",
    "BiomassStorageHF":      "storage",
    "BiomassGasifierHF":     "gasifier",
    "WGSReactorHF":          "wgs",
    "StoichiometricReactor": "stoich_rx",
    "MethanationReactor":    "meth",
    "SeparatorHF":           "sep",
    "FlashVLHF":             "flash",
    "TVSAContactor":         "dac",
    "HeatExchangerNTU":      "hex",
    "CoolerHF":              "cooler",
    "ElectrolyserHF":        "elec",
    "CHPUnit":               "chp",
    "MixerHF":               "mixer",
    "Compressor":            "comp",
    # v1.4.0 audit H11 — newly exposed UI types
    "Pump":                  "pump",
    "Valve":                 "valve",
    "ShellTubeHX":           "stx",
    "H2SeparatorPSA":        "psa",
    "GibbsReactor":          "gibbs",
    "EquilibriumReactor":    "eq_rx",
    "DistillationHF":        "col",
}


# ── Unit catalogue + Industrial Mode persona filter ───────────────────────────
# v1.6.1 P.1.3 — extracted to ``pse_ecosystem.ui.catalogue``. Re-exported
# here so existing call sites keep working.
from pse_ecosystem.ui.catalogue import (  # noqa: E402, F401
    AVAILABLE_UNITS,
    UNIT_CATEGORIES,
    _unit_class_for_label,
    available_units_for_persona,
    unit_categories_for_persona,
)


# ── Custom-flowsheet builder + unit factory ───────────────────────────────────
# v1.6.1 P.1.4 — extracted to ``pse_ecosystem.ui.instantiate``.
from pse_ecosystem.ui.instantiate import (  # noqa: E402, F401
    _instantiate_unit,
    build_composite_unit,
    build_custom_flowsheet,
)


# ── Built-in flowsheet templates ──────────────────────────────────────────────
# v1.6.1 P.1.5 — TemplateSpec / _REGISTRY / loaders extracted to
# ``pse_ecosystem.ui.templates``. Re-exported here for back-compat.
from pse_ecosystem.ui.templates import (  # noqa: E402, F401
    TemplateSpec,
    _LOADER_MAP,
    _MILP_LOADER_MAP,
    _REGISTRY,
    _REGISTRY_MAP,
    _validate_registry_loader_sync,
    get_template,
    list_templates,
    load_template,
    load_template_with_choices,
)


# ── Post-solve safety margins ──────────────────────────────
# v1.6.1 P.1.6 — extracted to ``pse_ecosystem.ui.safety_bridge``.
from pse_ecosystem.ui.safety_bridge import (  # noqa: E402, F401
    _ASME_VESSEL_UNIT_TYPES,
    _ASME_WARNING_THICKNESS_M,
    _FLAMM_WARNING_MARGIN_VOL_PCT,
    _PRESSURE_WARNING_MARGIN,
    _extract_vessel_radius,
    compute_safety_margins,
)


# ── Tornado sensitivity + break-even (v1.5.1) ────────────────────────────────

@dataclass
class TornadoRow:
    """One row of the sensitivity tornado chart."""

    param_label: str    # human-readable parameter name
    param_field: str    # ProjectEconomicsConfig field name
    base_value: float
    low_value: float    # perturbed downward
    high_value: float   # perturbed upward
    kpi_at_low: float
    kpi_at_high: float
    kpi_base: float
    delta_low: float    # kpi_at_low - kpi_base
    delta_high: float   # kpi_at_high - kpi_base
    impact: float       # |kpi_at_high - kpi_at_low|  — sort key


# Perturb-able ProjectEconomicsConfig fields for the tornado chart.
# (field_name, human label, perturbation mode)
# mode "frac": ± perturbation_frac × base_value
# mode "abs_yr": ±abs_delta years (for integer plant_life_yr)
_TORNADO_PARAMS: List[Tuple[str, str, str]] = [
    ("electricity_price_USD_per_kWh",  "Electricity Price",       "frac"),
    ("biomass_price_USD_per_tonne",    "Biomass Feedstock Price",  "frac"),
    ("interest_rate",                  "Discount Rate (WACC)",     "frac"),
    ("plant_life_yr",                  "Plant Life",               "abs_yr"),
    ("lang_factor",                    "Lang Factor (EPC)",        "frac"),
    ("operating_hours_per_year",       "Operating Hours",          "frac"),
    ("carbon_tax_USD_per_tonne",       "Carbon Tax",               "frac"),
    ("water_price_USD_per_tonne",      "Water Price",              "frac"),
]

_ABS_YR_DELTA: int = 5   # ±5 years for plant life


def _extract_econ_kpi(rows: List[Dict], metric: str) -> float:
    """Pull a scalar value from compute_project_economics() rows by Metric name."""
    for r in rows:
        if r.get("Metric") == metric:
            try:
                return float(r["Value"])
            except (TypeError, ValueError):
                return float("nan")
    return float("nan")


def tornado_sensitivity(
    flowsheet,
    solution_x: Dict[str, float],
    kpis: Dict[str, float],
    econ_config: "ProjectEconomicsConfig",
    target_metric: str = "LCOH",
    perturbation_frac: float = 0.20,
) -> List[TornadoRow]:
    """One-at-a-time sensitivity analysis for project economics parameters.

    For each field in ``_TORNADO_PARAMS``, the function perturbs the value
    ±``perturbation_frac`` (or ±5 years for plant life), calls
    ``compute_project_economics()`` at each point, and records the change in
    ``target_metric`` (default LCOH; also supports LCOE, NPV, TAC).

    No re-solve is performed — the economics are re-computed analytically from
    the existing ``solution_x``.  Each call takes <5 ms; the full sweep <100 ms.

    Returns
    -------
    List[TornadoRow] sorted descending by ``impact`` (largest swing first).
    """
    import dataclasses

    base_rows = compute_project_economics(flowsheet, solution_x, kpis, econ_config)
    kpi_base = _extract_econ_kpi(base_rows, target_metric)

    results: List[TornadoRow] = []

    for field, label, mode in _TORNADO_PARAMS:
        base_val = getattr(econ_config, field, None)
        if base_val is None:
            continue

        if mode == "abs_yr":
            low_val  = max(1, int(base_val) - _ABS_YR_DELTA)
            high_val = int(base_val) + _ABS_YR_DELTA
        else:
            low_val  = base_val * (1.0 - perturbation_frac)
            high_val = base_val * (1.0 + perturbation_frac)
            if base_val == 0.0:
                continue  # skip zero-valued fields (would give no swing)

        def _kpi_at(val):
            try:
                cfg_low = dataclasses.replace(econ_config, **{field: val})
                rows = compute_project_economics(flowsheet, solution_x, kpis, cfg_low)
                return _extract_econ_kpi(rows, target_metric)
            except Exception:
                return float("nan")

        kpi_low  = _kpi_at(low_val)
        kpi_high = _kpi_at(high_val)

        results.append(TornadoRow(
            param_label=label,
            param_field=field,
            base_value=float(base_val),
            low_value=float(low_val),
            high_value=float(high_val),
            kpi_at_low=kpi_low,
            kpi_at_high=kpi_high,
            kpi_base=kpi_base,
            delta_low=kpi_low - kpi_base,
            delta_high=kpi_high - kpi_base,
            impact=abs(kpi_high - kpi_low),
        ))

    results.sort(key=lambda r: r.impact, reverse=True)
    return results


def compute_npv_with_revenue(
    flowsheet,
    solution_x: Dict[str, float],
    kpis: Dict[str, float],
    econ_config: "ProjectEconomicsConfig",
    product_price_USD_per_kg: float = 0.0,
) -> Dict[str, float]:
    """Compute NPV when a product selling price is provided.

    The economic identity NPV = 0  ⟺  product_price = LCOH holds exactly for
    a single-product plant.  This function makes that relationship explicit and
    computes the full NPV at an arbitrary product price.

    Parameters
    ----------
    product_price_USD_per_kg :
        Expected market price for H₂ (or the primary product) [USD/kg].

    Returns
    -------
    dict with keys:
        ``lcoh``                 — Levelised Cost of H₂ = break-even price [USD/kg]
        ``product_price``        — input product price [USD/kg]
        ``npv_with_revenue``     — NPV at the given product price [USD]
        ``annual_revenue``       — product_price × H₂ production [USD/yr]
        ``margin_USD_per_kg``    — product_price − LCOH [USD/kg]
        ``payback_yr``           — installed_capex / max(annual_profit, ε) [yr]
    """
    from pse_ecosystem.models.costing.economic_engine import EconomicEngine

    cfg = econ_config
    ee  = EconomicEngine(
        target_year=cfg.target_year,
        plant_life_yr=cfg.plant_life_yr,
        interest_rate=cfg.interest_rate,
        operating_hours_per_year=cfg.operating_hours_per_year,
    )

    purchase_CE500 = _aggregate_capex_purchase_USD(flowsheet, solution_x)
    installed      = purchase_CE500 * ee.sslw_cepci_factor() * cfg.lang_factor
    capex_annual   = installed * ee.capital_recovery_factor()
    opex_annual    = _aggregate_opex_annual_USD(
        flowsheet, solution_x, operating_hours=cfg.operating_hours_per_year
    )
    h2_kg_s = _extract_h2_kg_per_s(kpis, flowsheet, solution_x)
    h2_kg_yr = h2_kg_s * cfg.operating_hours_per_year * 3600.0

    lcoh = ee.lcoh(capex_annual, opex_annual, h2_kg_s) if h2_kg_s > 0 else float("nan")

    annual_revenue = product_price_USD_per_kg * h2_kg_yr
    annual_profit  = annual_revenue - opex_annual - capex_annual
    npv_rev = ee.npv(annual_net_cashflow=annual_revenue - opex_annual,
                     initial_capex=installed)

    payback = installed / max(annual_revenue - opex_annual, 1e-9) if annual_revenue > opex_annual else float("inf")

    return {
        "lcoh":              lcoh,
        "product_price":     product_price_USD_per_kg,
        "npv_with_revenue":  npv_rev,
        "annual_revenue":    annual_revenue,
        "annual_opex":       opex_annual,
        "installed_capex":   installed,
        "margin_USD_per_kg": product_price_USD_per_kg - (lcoh if lcoh == lcoh else 0.0),
        "payback_yr":        payback,
        "h2_kg_yr":          h2_kg_yr,
    }


# ── Investor Report generator (v1.5.1) ───────────────────────────────────────

def generate_investor_report(
    flowsheet,
    result,
    econ_config: "ProjectEconomicsConfig",
    safety_rows: Optional[List["SafetyMarginRow"]] = None,
    template_spec=None,
    scenario_label: str = "Base Case",
    tornado_rows: Optional[List[TornadoRow]] = None,
) -> str:
    """Generate an investor-grade Markdown summary report.

    Produces a structured Markdown document suitable for:
    - Internal investment committee review
    - Preliminary due diligence package
    - Grant application technical annex

    All assumptions are explicitly listed so the document is self-contained and
    auditable.  Suitable for download via ``st.download_button(mime="text/markdown")``.

    Parameters
    ----------
    flowsheet      : Solved ``BaseFlowsheet``.
    result         : ``SolveResult`` from the Orchestrator.
    econ_config    : ``ProjectEconomicsConfig`` used for the solve.
    safety_rows    : Output of ``compute_safety_margins()``.
    template_spec  : ``TemplateSpec`` for the selected template (display name, description).
    scenario_label : Name of this scenario (e.g., "Base Case", "Optimistic").
    tornado_rows   : Pre-computed tornado sensitivity (top-5 shown).

    Returns
    -------
    str — Markdown document.
    """
    import datetime, math

    today = datetime.date.today().isoformat()
    plant_name = getattr(template_spec, "display_name", "Process Plant") if template_spec else "Process Plant"
    plant_desc = getattr(template_spec, "description", "") if template_spec else ""
    status_str = "CONVERGED" if result.converged else f"NOT CONVERGED ({result.message})"

    lines: List[str] = []

    # ── Cover ────────────────────────────────────────────────────────────────
    lines += [
        f"# Investment Summary — {plant_name}",
        f"**Scenario:** {scenario_label}  |  **Date:** {today}  |  "
        f"**Status:** {status_str}  |  "
        f"**Solver iterations:** {result.iterations}",
        "",
        "> *Generated by PSE Ecosystem v1.5.1.  "
        "This report contains preliminary steady-state simulation results.  "
        "All assumptions are listed in §6.  "
        "Not a certified engineering design — engage a qualified process engineer for final design.*",
        "",
    ]

    # ── §1 Process Description ───────────────────────────────────────────────
    lines += [
        "## §1 Process Description",
        "",
        f"**Technology:** {plant_name}",
    ]
    if plant_desc:
        lines += [f"**Summary:** {plant_desc}", ""]

    if flowsheet is not None:
        unit_lines = [f"- `{u.unit_id}` ({type(u).__name__})" for u in flowsheet.units]
        lines += ["**Unit inventory:**", ""] + unit_lines + [""]

    # ── §2 Key Performance Indicators ────────────────────────────────────────
    lines += ["## §2 Key Performance Indicators", ""]
    if result.kpis:
        lines += ["| KPI | Value |", "|---|---|"]
        for k, v in result.kpis.items():
            lines.append(f"| {k} | {v:.4g} |")
        lines.append("")

    # ── §3 Project Economics ─────────────────────────────────────────────────
    lines += ["## §3 Project Economics", ""]
    try:
        econ_rows = compute_project_economics(flowsheet, result.x, result.kpis, econ_config)
        _KEY_METRICS = ["Installed CAPEX", "Annual OPEX", "TAC", "LCOH", "LCOE", "NPV", "IRR"]
        lines += ["| Metric | Value | Unit |", "|---|---|---|"]
        for row in econ_rows:
            if row["Metric"] in _KEY_METRICS:
                v = row["Value"]
                v_str = f"{v:,.2f}" if isinstance(v, float) and not math.isnan(v) and not math.isinf(v) else str(v)
                lines.append(f"| {row['Metric']} | {v_str} | {row['Unit']} |")
        lines.append("")

        lcoh = _extract_econ_kpi(econ_rows, "LCOH")
        if not math.isnan(lcoh):
            lines += [
                f"> **Break-even H₂ price = LCOH = ${lcoh:.3f}/kg.**  "
                "The plant is profitable at any H₂ market price above this value.",
                "",
            ]
    except Exception as e:
        lines += [f"*Economics computation failed: {e}*", ""]

    # ── §4 Engineering Safety Assessment ─────────────────────────────────────
    lines += ["## §4 Engineering Safety Assessment", ""]
    if safety_rows:
        lines += [
            "| Unit | Check | Value | Status | Detail |",
            "|---|---|---|---|---|",
        ]
        for row in safety_rows:
            v_str = f"{row.value:.4g}" if row.value == row.value else "—"
            lines.append(f"| {row.unit_id} | {row.check_type} | {v_str} | **{row.status}** | {row.detail} |")
        lines += [
            "",
            "*ASME estimates use default vessel radius unless unit declares `vessel_radius_m`.  "
            "Not a certified ASME pressure vessel calculation.*",
            "",
        ]
    else:
        lines += ["*No pressure-vessel units identified in this flowsheet.*", ""]

    # ── §5 Economic Sensitivity (Tornado) ────────────────────────────────────
    if tornado_rows:
        lines += ["## §5 Economic Sensitivity (Top 5 Drivers)", ""]
        lines += ["| Parameter | −20% Impact | +20% Impact | Swing |", "|---|---|---|---|"]
        for row in tornado_rows[:5]:
            lines.append(
                f"| {row.param_label} | {row.delta_low:+.4g} | {row.delta_high:+.4g} | {row.impact:.4g} |"
            )
        lines.append("")

    # ── §6 Assumptions & Limitations ─────────────────────────────────────────
    lines += [
        "## §6 Assumptions & Limitations",
        "",
        "| Parameter | Value |",
        "|---|---|",
        f"| Plant life | {econ_config.plant_life_yr} yr |",
        f"| Discount rate (WACC) | {econ_config.interest_rate*100:.1f}% |",
        f"| Target CEPCI year | {econ_config.target_year} |",
        f"| Lang factor | {econ_config.lang_factor} |",
        f"| Operating hours | {econ_config.operating_hours_per_year:,.0f} h/yr |",
        f"| Electricity price | ${econ_config.electricity_price_USD_per_kWh:.3f}/kWh |",
        f"| Biomass price | ${econ_config.biomass_price_USD_per_tonne:.1f}/tonne |",
        f"| Carbon tax | ${econ_config.carbon_tax_USD_per_tonne:.1f}/tonne CO₂ |",
        f"| Tax rate | {econ_config.tax_rate*100:.1f}% (informational — pre-tax model) |",
        "",
        "**Model limitations:**",
        "- Steady-state, single-period, deterministic simulation",
        "- Pre-tax DCF (after-tax model reserved for v1.6)",
        "- No revenue term in NPV unless product price is explicitly set",
        "- Equipment costs from SSLW correlations (±30% accuracy)",
        "- ASME sizing uses conservative default geometry where unit params are absent",
        "",
        "---",
        f"*PSE Ecosystem v1.5.1 — Private — University of Surrey — {today}*",
    ]

    return "\n".join(lines)


# ── Thin gateway helpers for safety module constants (v1.5.1) ─────────────────
# These keep app_streamlit.py free of direct models.* imports (layer boundary).

def get_asme_materials() -> Dict[str, float]:
    """Return the ASME allowable-stress material database [Pa].

    Deferred import ensures the safety module is only loaded when needed.
    """
    from pse_ecosystem.models.safety.safety_checks import ASME_MATERIALS
    return dict(ASME_MATERIALS)


def compute_outlet_flammability_warnings(
    flowsheet,
    solution_x: Dict[str, float],
    warning_margin_vol_pct: float = 2.0,
) -> List[str]:
    """Return human-readable flammability warning strings for each unit outlet.

    POST-SOLVE ONLY.  Deferred import of safety_checks preserves layer boundary.

    Returns
    -------
    List of warning strings (one per flagged unit outlet).  Empty list if no
    flammable species are detected or all margins are safe.
    """
    from pse_ecosystem.models.safety.safety_checks import flammability_margins

    warnings_out: List[str] = []
    for unit in flowsheet.units:
        components = getattr(unit, "components", None) or getattr(
            getattr(unit, "params", None), "components", None
        )
        if not components:
            continue
        flows = {sp: solution_x.get(f"{unit.unit_id}.outlet.F_{sp}", 0.0)
                 for sp in components}
        total = sum(flows.values())
        if total <= 0.0:
            continue
        fracs = {sp: f / total for sp, f in flows.items()}
        try:
            fm = flammability_margins(fracs)
        except ValueError:
            continue
        if fm["margin_to_LFL_vol_pct"] < warning_margin_vol_pct:
            severity = "VIOLATION" if fm["margin_to_LFL_vol_pct"] < 0 else "WARNING"
            warnings_out.append(
                f"**{unit.unit_id}** outlet: "
                f"LFL_mix = {fm['LFL_vol_pct']:.1f} vol%  |  "
                f"flammable content = {fm['mixture_flammable_fraction']*100:.1f}%  "
                f"({severity})"
            )
    return warnings_out
