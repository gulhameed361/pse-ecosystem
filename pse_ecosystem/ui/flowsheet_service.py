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


UNIT_PARAM_SPECS: Dict[str, List[ParamSpec]] = {
    "BiomassStorageHF": [
        ParamSpec("biomass_type", "Biomass Type", "select", "Pine Wood",
                  ["Pine Wood", "Miscanthus", "Wheat Straw"]),
        ParamSpec("T_preheat_C", "Preheat Temperature", "float", 200.0,
                  unit="°C", help="Target preheat temperature for dry biomass"),
    ],
    "BiomassGasifierHF": [
        ParamSpec("T_gasifier_C", "Gasifier Temperature", "float", 800.0,
                  unit="°C", help="Thermochemical equilibrium temperature"),
        ParamSpec("gasifying_agent", "Gasifying Agent", "select", "Steam",
                  ["Steam", "Air"], help="Steam gives higher H₂ yield; Air is cheaper"),
        ParamSpec("P_atm", "Pressure", "float", 1.0,
                  unit="atm", help="Operating pressure"),
    ],
    "WGSReactorHF": [
        ParamSpec("T_wgs_C", "WGS Temperature", "float", 400.0,
                  unit="°C", help="400 °C = High-Temperature Shift; 220 °C = Low-Temperature Shift"),
    ],
    "CoolerHF": [
        ParamSpec("T_out_K", "Outlet Temperature", "float", 310.0,
                  unit="K", help="Fixed outlet temperature (parameter, not solver variable)"),
    ],
    "SeparatorHF": [
        ParamSpec("n_outlets", "Number of Outlets", "int", 2,
                  help="Typically 2 for binary split; up to 4 supported"),
    ],
    "Compressor": [
        ParamSpec("eta_isentropic", "Isentropic Efficiency", "float", 0.78,
                  unit="—", help="0–1; typical industrial range 0.70–0.85"),
        ParamSpec("P_out_Pa", "Outlet Pressure", "float", 500_000.0,
                  unit="Pa", help="5e5 Pa = 5 bar; 5e6 Pa = 50 bar"),
    ],
    "HeatExchangerNTU": [
        ParamSpec("UA_W_per_K", "UA Product", "float", 5000.0,
                  unit="W/K", help="Overall heat transfer coefficient × area"),
    ],
    "MixerHF": [
        ParamSpec("n_inlets", "Number of Inlets", "int", 2,
                  help="Number of feed streams entering the mixer"),
    ],
    "FlashVLHF": [
        ParamSpec("T_min", "T min", "float", 250.0, unit="K"),
        ParamSpec("T_max", "T max", "float", 550.0, unit="K"),
        ParamSpec("P_min", "P min", "float", 1e3,  unit="Pa"),
        ParamSpec("P_max", "P max", "float", 1e7,  unit="Pa"),
    ],
    "StoichiometricReactor": [
        ParamSpec("feed_max", "Max Feed Flow", "float", 50.0,
                  unit="mol/s", help="Upper bound on inlet flow variables"),
    ],
    "MethanationReactor": [
        ParamSpec("T_rx_K", "Reactor Temperature", "float", 673.0,
                  unit="K", help="Sabatier reaction temperature (400 °C default)"),
    ],
    "TVSAContactor": [
        ParamSpec("eta_cap", "CO₂ Capture Efficiency", "float", 0.85,
                  unit="—", help="Fraction of inlet CO₂ captured (0–1)"),
        ParamSpec("T_des_K", "Desorption Temperature", "float", 393.0,
                  unit="K", help="120 °C default; higher = more regen energy"),
    ],
    "ElectrolyserHF": [
        ParamSpec("eta_elec", "Electrolyser Efficiency", "float", 0.70,
                  unit="—", help="HHV basis; typical PEM 0.65–0.75"),
    ],
    "CHPUnit": [
        ParamSpec("eta_comb", "Combustion Efficiency", "float", 0.95, unit="—"),
        ParamSpec("eta_isentropic", "Turbine Isentropic Efficiency", "float", 0.85, unit="—"),
    ],
    # ── v1.4.0 audit H11: extra UI-selectable types ──────────────────────────
    "Pump": [
        ParamSpec("eta_pump", "Pump Efficiency", "float", 0.75,
                  unit="—", help="Mechanical efficiency, 0–1; typical 0.65–0.85"),
        ParamSpec("P_out_Pa", "Outlet Pressure", "float", 1_000_000.0,
                  unit="Pa", help="Set to 0 to leave P_out free"),
    ],
    "Valve": [
        ParamSpec("Cv", "Valve Coefficient (Cv)", "float", 1.0,
                  unit="—", help="Flow coefficient; sets the throttle resistance"),
        ParamSpec("P_out_Pa", "Outlet Pressure", "float", 200_000.0,
                  unit="Pa", help="Throttle target pressure"),
    ],
    "ShellTubeHX": [
        ParamSpec("U_W_per_m2_K", "Overall U", "float", 500.0,
                  unit="W/m²/K", help="Heat-transfer coefficient"),
        ParamSpec("A_m2", "Heat-transfer Area", "float", 16.0,
                  unit="m²", help="Total tube surface area"),
        ParamSpec("n_shell_passes", "Shell Passes", "int", 1,
                  help="LMTD F-factor depends on the shell/tube pass combination"),
        ParamSpec("n_tube_passes", "Tube Passes", "int", 2,
                  help="LMTD F-factor depends on the shell/tube pass combination"),
    ],
    "H2SeparatorPSA": [
        ParamSpec("H2_recovery", "H₂ Recovery", "float", 0.85,
                  unit="—", help="Fraction of feed H₂ recovered to product, 0–1"),
    ],
    "GibbsReactor": [
        # No tunable params; T is a solver variable inside the reactor.
        ParamSpec("T_max", "Max Temperature", "float", 2000.0,
                  unit="K", help="Upper bound used by the inner Gibbs minimiser"),
    ],
    "EquilibriumReactor": [
        ParamSpec("T_ref_K", "Reference Temperature", "float", 673.0,
                  unit="K", help="van't Hoff reference for Keq(T) scaling"),
        ParamSpec("Keq_ref", "Reference Keq", "float", 8.9,
                  unit="—", help="Equilibrium constant at T_ref. Default reaction = WGS"),
    ],
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
    ],
    # Toy units and units with no tunable params default to empty list (components-only)
}


def get_unit_param_specs(utype: str) -> List[ParamSpec]:
    """Return the list of ParamSpec descriptors for *utype*, or [] if none defined."""
    return UNIT_PARAM_SPECS.get(utype, [])


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
    # shaft work or electrical power draw.
    _energy_modes = (
        "Minimize Energy",
        "Minimize TAC",
        "Minimize LCOH (Levelized Cost of H₂)",
        "Minimize Specific Energy Consumption",
        "Maximize NPV (Net Present Value)",
        "Maximize IRR (Internal Rate of Return)",
        "Minimize LCOE (Levelized Cost of Energy)",
    )
    if mode in _energy_modes:
        for v in all_vars:
            lv = v.lower()
            if any(k in lv for k in ("w_shaft", "w_elec_kw", "electricity_kw")):
                obj[v] = obj.get(v, 0.0) + energy_coeff

    # ── Annualised CAPEX for linear-capex units ───────────────────────────────
    # ElectrolyserHF has strictly linear capex: 700 USD/kW.
    # Annualised = 700 × CRF per kW → inject on the W_elec_kW decision variable.
    # SSLW-correlated units (Compressor, HXN, vessels) have non-linear capex;
    # their costs are captured post-solve in kpis() and the Excel report.
    _capex_modes = (
        "Minimize TAC",
        "Minimize LCOH (Levelized Cost of H₂)",
        "Maximize NPV (Net Present Value)",
        "Maximize IRR (Internal Rate of Return)",
    )
    if mode in _capex_modes:
        for unit in flowsheet.units:
            if type(unit).__name__ == "ElectrolyserHF":
                w_var = next(
                    (v for v in all_vars
                     if unit.unit_id in v and "w_elec_kw" in v.lower()),
                    None,
                )
                if w_var:
                    obj[w_var] = obj.get(w_var, 0.0) + 700.0 * crf  # $70/kW/yr

    # ── H₂ yield maximisation ────────────────────────────────────────────────
    # Negative coefficient (−1.0) on the last H₂ outlet flow variable in the chain.
    # "Last" is determined by lexicographic sort; for sequential chains this gives
    # the most downstream H₂ variable.
    def _is_h2_outlet(v: str) -> bool:
        parts = v.split(".")
        return len(parts) >= 3 and parts[-1].lower() == "f_h2" and "out" in parts[1].lower()

    if mode in ("Maximize H₂ Yield", "Minimize LCOH (Levelized Cost of H₂)",
                "Minimize Specific Energy Consumption"):
        h2_candidates = sorted(v for v in all_vars if _is_h2_outlet(v))
        if h2_candidates:
            obj[h2_candidates[-1]] = obj.get(h2_candidates[-1], 0.0) - 1.0

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
    if mode == "Minimize LCOE (Levelized Cost of Energy)":
        for v in all_vars:
            lv = v.lower()
            if any(k in lv for k in ("w_net_kw", "power_out_kw", "w_turbine_kw")):
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
            # Pass hours; fall back if a v1.4 unit hasn't been migrated.
            total += float(unit.opex_per_year(solution_x, operating_hours))
        except TypeError:
            # Backward-compat shim for any caller still on the v1.4 (x,) signature.
            total += float(unit.opex_per_year(solution_x))
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
    """Find net electrical output in kW.

    Priority order:
      1. KPI keys ending in ``W_elec_kW`` (CHP, PEM — note PEM consumes power
         so this can be negative if PEM dominates).
      2. KPI keys ending in ``total_useful_output_kW`` (CHP combined output).
      3. KPI keys ending in ``power_out_kW`` / ``W_net_kW`` (forward-compat).
    """
    for suffix in ("total_useful_output_kW", "power_out_kW", "W_net_kW"):
        vals = [v for k, v in kpis.items() if k.endswith(suffix)]
        if vals:
            return max(vals)
    # Fallback: sum any W_elec_kW; this favours generation-dominant flowsheets.
    elec = [v for k, v in kpis.items() if k.endswith("W_elec_kW")]
    return sum(elec) if elec else 0.0


def compute_project_economics(
    flowsheet: "BaseFlowsheet",
    solution_x: Dict[str, float],
    kpis: Dict[str, float],
    econ_config: Optional[ProjectEconomicsConfig] = None,
    obj_config: Optional[Dict] = None,
) -> List[Dict]:
    """Compute project-economics rows for the Excel 'Project Economics' sheet.

    This is the Layer-1 bridge between the solver result and the
    EconomicEngine.  All Layer-3 imports are deferred inside this function so
    that ``app_streamlit.py`` never imports from ``pse_ecosystem.models.*``
    directly — the UI audit (`tests/ui_audit.py`) enforces this boundary.

    Parameters
    ----------
    flowsheet  : ``BaseFlowsheet`` that was solved (provides per-unit capex/opex).
    solution_x : ``SolveResult.x`` — the solution dictionary.
    kpis       : ``SolveResult.kpis`` — aggregated unit KPIs.
    econ_config: ``ProjectEconomicsConfig`` instance (uses defaults when None).
    obj_config : Raw ``objective_config`` dict from session state (metadata only).

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
    # Cash flow assumption (v1.5.0.dev): pre-tax, treating annual OPEX as a net
    # outflow and ignoring product revenue (the LP doesn't know prices).  v1.6
    # will add a revenue stream + after-tax DCF using cfg.tax_rate/inflation.
    npv = ee.npv(annual_net_cashflow=-opex_annual, initial_capex=installed)
    irr = ee.irr(initial_capex=installed, annual_net_cashflow=-opex_annual)

    import math

    def _fmt_irr(r: float) -> float:
        if math.isnan(r):
            return float("nan")
        if math.isinf(r):
            return float("inf")
        return round(r * 100.0, 4)

    return [
        {"Metric": "Plant Life",            "Value": cfg.plant_life_yr,                          "Unit": "years"},
        {"Metric": "Discount Rate (WACC)",  "Value": round(cfg.interest_rate * 100, 2),          "Unit": "%"},
        {"Metric": "Tax Rate",              "Value": round(cfg.tax_rate * 100, 2),               "Unit": "% (informational)"},
        {"Metric": "Inflation Rate",        "Value": round(cfg.inflation_rate * 100, 2),         "Unit": "% (informational)"},
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
        {"Metric": "TAC",                   "Value": round(capex_annual + opex_annual, 2),       "Unit": "USD/yr"},
        {"Metric": "H₂ Production",         "Value": round(h2_kg_s, 6),                          "Unit": "kg/s"},
        {"Metric": "Power Output",          "Value": round(power_kw, 4),                         "Unit": "kW"},
        {"Metric": "LCOH",                  "Value": round(lcoh, 6) if not math.isnan(lcoh) else float("nan"), "Unit": "USD/kg H₂"},
        {"Metric": "LCOE",                  "Value": round(lcoe, 6) if not math.isnan(lcoe) else float("nan"), "Unit": "USD/kWh"},
        {"Metric": "NPV",                   "Value": round(npv, 2),                              "Unit": "USD"},
        {"Metric": "IRR",                   "Value": _fmt_irr(irr),                              "Unit": "%"},
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
    """Construct node + link arrays for a Plotly Sankey diagram of flows.

    Returns a dict with keys:
        ``labels``  : node names (one per unit)
        ``sources`` : source-node indices for each link
        ``targets`` : target-node indices for each link
        ``values``  : link magnitudes (sum of all flow vars on the connection)
        ``link_labels`` : hover-text per link describing components

    v1.5.0.dev-AUDIT3 UI-1: quantitative topology view supplementing the
    static Mermaid box-and-arrow diagram.
    """
    # Build node table: one per unit.
    unit_ids = [u.unit_id for u in flowsheet.units]
    name_to_idx = {uid: i for i, uid in enumerate(unit_ids)}

    sources: List[int] = []
    targets: List[int] = []
    values:  List[float] = []
    link_labels: List[str] = []

    for conn in getattr(flowsheet, "connections", []):
        # Connection holds two variable names (var_a, var_b). Parse unit_id
        # prefix (first dotted segment) to find source and target nodes.
        var_a = getattr(conn, "var_a", None)
        var_b = getattr(conn, "var_b", None)
        if not var_a or not var_b:
            continue
        src_uid = var_a.split(".", 1)[0]
        tgt_uid = var_b.split(".", 1)[0]
        if src_uid not in name_to_idx or tgt_uid not in name_to_idx:
            continue
        flow_val = abs(float(solution_x.get(var_a, 0.0)))
        sources.append(name_to_idx[src_uid])
        targets.append(name_to_idx[tgt_uid])
        values.append(max(flow_val, 1e-12))   # plotly hates exact zeros
        link_labels.append(f"{var_a.split('.')[-1]} = {flow_val:.4g}")

    return {
        "labels":     unit_ids,
        "sources":    sources,
        "targets":    targets,
        "values":     values,
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
    path = _get_history_path()
    if path and path is not False:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
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


# ── TemplateSpec ─────────────────────────────────────────────────────────────

@dataclass
class TemplateSpec:
    """Metadata for one entry in the template registry."""

    key: str
    display_name: str
    category: str          # "Small" | "Hydrogen" | "Industrial" | "Custom"
    description: str
    topology_diagram: str  # Mermaid flowchart string
    unit_labels: List[str]
    default_params: Dict[str, Any] = field(default_factory=dict)
    supports_milp: bool = False
    connections_human: List[Tuple[str, str, str]] = field(default_factory=list)


# ── Unit catalogue for the custom flowsheet assembler ─────────────────────────

AVAILABLE_UNITS: Dict[str, str] = {
    # Feed / Product
    "PEMToy":                "Electrolyser — linear (LCOH + Carbon Intensity KPIs)",
    "GasifierToy":           "Gasifier toy — non-linear (LCOH + Carbon Intensity KPIs)",
    # Biomass chain
    "BiomassStorageHF":      "Biomass dryer/storage — linear, solid feedstock",
    "BiomassGasifierHF":     "Biomass gasifier — non-linear equilibrium, 6-species syngas",
    "WGSReactorHF":          "Water-Gas Shift reactor — non-linear equilibrium, analytical J",
    # Reactors
    "StoichiometricReactor": "Stoichiometric reactor — linear (exact analytical J)",
    "MethanationReactor":    "Sabatier methanation — non-linear equilibrium, analytical J",
    "EquilibriumReactor":    "Equilibrium reactor — van't Hoff Keq (default WGS reaction)",
    "GibbsReactor":          "Isothermal Gibbs-energy-minimising reactor",
    # Separation / DAC
    "SeparatorHF":           "Separator — split fractions, linear",
    "TVSAContactor":         "TVSA DAC contactor — linear, analytical J (415 ppm CO2 feed)",
    "H2SeparatorPSA":        "PSA hydrogen separator — linear, configurable H₂ recovery",
    "DistillationHF":        "Distillation column — Fenske/Underwood (light/heavy key)",
    # Heat Exchange
    "HeatExchangerNTU":      "Heat exchanger NTU — non-linear (counter-current)",
    "ShellTubeHX":           "Shell-and-tube HX — corrected LMTD (1-2 pass)",
    "CoolerHF":              "Single-stream gas cooler — linear, fixed T_out parameter",
    # Power / CHP
    "ElectrolyserHF":        "PEM/AEL electrolyser — linear, port-based, analytical J",
    "CHPUnit":               "Combined Heat & Power — linear, analytical J (H2/CO/CH4 fuel)",
    # Separation / VLE
    "FlashVLHF":             "Rigorous V/L flash — Antoine K-values + Rachford-Rice (non-linear, terminal unit)",
    # Mixing
    "MixerHF":               "Multi-stream mixer — non-linear (energy balance)",
    # Pressure Changers
    "Compressor":            "Isentropic compressor — non-linear",
    "Pump":                  "Liquid pump — non-linear, isentropic efficiency",
    "Valve":                 "Throttle valve — isenthalpic, smoothed Cv·√(dP)",
}

UNIT_CATEGORIES: Dict[str, List[str]] = {
    "Feed/Product":       ["PEMToy", "GasifierToy"],
    "Biomass":            ["BiomassStorageHF", "BiomassGasifierHF", "WGSReactorHF"],
    "Reactors":           ["StoichiometricReactor", "MethanationReactor",
                           "EquilibriumReactor", "GibbsReactor"],
    "Separation/DAC":     ["SeparatorHF", "FlashVLHF", "TVSAContactor",
                           "H2SeparatorPSA", "DistillationHF"],
    "Heat Exchange":      ["HeatExchangerNTU", "ShellTubeHX", "CoolerHF"],
    "Power/CHP":          ["ElectrolyserHF", "CHPUnit"],
    "Mixing":             ["MixerHF"],
    "Pressure Changers":  ["Compressor", "Pump", "Valve"],
}


# ── Internal template registry ────────────────────────────────────────────────

_REGISTRY: List[TemplateSpec] = [

    TemplateSpec(
        key="hydrogen.electrolysis_only",
        display_name="PEM Electrolysis",
        category="Hydrogen Production",
        description="Single PEM electrolyser meeting a fixed H2 demand. "
                    "Fully linear — solves in one LP step. Reports LCOH and Carbon Intensity.",
        topology_diagram=(
            "graph LR\n"
            "    Grid([Grid / Renewables]) --> PEM[PEM Electrolyser]\n"
            "    PEM --> H2([H2 product])\n"
            "    style PEM fill:#4a90e2,color:#fff"
        ),
        unit_labels=["PEMToy"],
        default_params={
            "h2_demand_kg_per_h": 100.0,
            "pem.eta_kg_per_kWh": 0.018,
            "pem.capacity_kW": 10_000.0,
            "pem.electricity_price_per_kWh": 0.05,
            "pem.capex_annual_per_kW": 100.0,
            "pem.grid_carbon_intensity_kg_CO2_per_kWh": 0.233,
        },
    ),

    TemplateSpec(
        key="hydrogen.electrolysis_or_gasification",
        display_name="PEM + Gasifier (MILP)",
        category="Hydrogen Production",
        description="Technology selection between PEM electrolysis and gasification "
                    "to meet H2 demand at minimum cost. Solved via MILP.",
        topology_diagram=(
            "graph LR\n"
            "    Grid([Grid]) --> PEM[PEM Electrolyser]\n"
            "    Biomass([Biomass]) --> Gas[Gasifier]\n"
            "    PEM --> Demand([H2 Demand])\n"
            "    Gas --> Demand\n"
            "    style PEM fill:#4a90e2,color:#fff\n"
            "    style Gas fill:#e67e22,color:#fff"
        ),
        unit_labels=["PEMToy", "GasifierToy"],
        default_params={
            "h2_demand_kg_per_h": 100.0,
            "pem.electricity_price_per_kWh": 0.05,
            "pem.grid_carbon_intensity_kg_CO2_per_kWh": 0.233,
            "gasifier.biomass_carbon_intensity_kg_CO2_per_kg": 0.03,
        },
        supports_milp=True,
    ),

    TemplateSpec(
        key="industrial.green_hydrogen",
        display_name="Green Hydrogen Hub",
        category="Hydrogen Production",
        description="PEM electrolyser with H2 buffer mixer. "
                    "Reports LCOH and Carbon Intensity KPIs.",
        topology_diagram=(
            "graph LR\n"
            "    Elec([Electricity]) --> PEM[PEM Electrolyser]\n"
            "    PEM -->|H2 kg/h| Buf[H2 Buffer Mixer]\n"
            "    Buf --> Out([H2 Output])\n"
            "    style PEM fill:#2ecc71,color:#fff\n"
            "    style Buf fill:#27ae60,color:#fff"
        ),
        unit_labels=["PEMToy", "MixerHF"],
        default_params={
            "h2_demand_kg_per_h": 100.0,
            "pem.eta_kg_per_kWh": 0.018,
            "pem.capacity_kW": 10_000.0,
            "pem.electricity_price_per_kWh": 0.05,
            "pem.capex_annual_per_kW": 100.0,
            "pem.grid_carbon_intensity_kg_CO2_per_kWh": 0.233,
        },
        connections_human=[("PEM H2 out", "Buffer inlet_0", "H2 mass balance")],
    ),

    TemplateSpec(
        key="industrial.power_to_methanol",
        display_name="Power-to-Methanol",
        category="Petrochemicals",
        description="CO2 + 3H2 → methanol + H2O, then split-fraction "
                    "separation of liquid methanol. Fully linear.",
        topology_diagram=(
            "graph LR\n"
            "    CO2([CO2 feed]) --> Rxr[Stoich. Reactor\nCO2+3H2→MeOH+H2O]\n"
            "    H2([H2 feed]) --> Rxr\n"
            "    Rxr --> Sep[Separator]\n"
            "    Sep --> Vap([Gas phase\nCO2/H2])\n"
            "    Sep --> Liq([Liquid MeOH\n+water])\n"
            "    style Rxr fill:#9b59b6,color:#fff\n"
            "    style Sep fill:#8e44ad,color:#fff"
        ),
        unit_labels=["StoichiometricReactor", "SeparatorHF"],
        default_params={
            "extent_max": 3.0,
            "sep.split_methanol_liquid": 0.95,
            "sep.split_water_liquid": 0.98,
        },
        connections_human=[("Reactor outlet", "Separator inlet", "Reactor → Separator")],
    ),

    TemplateSpec(
        key="industrial.gasification_to_power",
        display_name="Gasification to Power",
        category="Power Generation",
        description="Biomass dry reforming (CH4+CO2→2CO+2H2) then syngas "
                    "compression to 5 bar for power generation.",
        topology_diagram=(
            "graph LR\n"
            "    Feed([Biomass feed\nCH4+CO2]) --> Rxr[Stoich. Reactor\ndry reforming]\n"
            "    Rxr --> Comp[Compressor\n1 atm → 5 bar]\n"
            "    Comp --> Out([Compressed syngas\nCO+H2])\n"
            "    style Rxr fill:#e74c3c,color:#fff\n"
            "    style Comp fill:#c0392b,color:#fff"
        ),
        unit_labels=["StoichiometricReactor", "Compressor"],
        default_params={
            "extent_max": 4.0,
            "comp.eta_isentropic": 0.78,
            "comp.P_out_Pa": 500_000.0,
        },
        connections_human=[("Gasifier outlet", "Compressor inlet", "Syngas feed")],
    ),

    TemplateSpec(
        key="industrial.syngas_production",
        display_name="Syngas Production",
        category="Petrochemicals",
        description="Toy gasifier → CO2 scrubber (PSA/membrane) → clean syngas. "
                    "Reports LCOH and Carbon Intensity KPIs.",
        topology_diagram=(
            "graph LR\n"
            "    Feed([Biomass / waste]) --> Gas[GasifierToy\nnon-linear]\n"
            "    Gas --> Scrub[CO2 Scrubber\nSeparatorHF]\n"
            "    Scrub --> Syngas([Clean syngas\nH2-rich])\n"
            "    Scrub --> CO2([CO2 captured])\n"
            "    style Gas fill:#e67e22,color:#fff\n"
            "    style Scrub fill:#d35400,color:#fff"
        ),
        unit_labels=["GasifierToy", "SeparatorHF"],
        default_params={
            "h2_demand_kg_per_h": 200.0,
            "co2_capture_fraction": 0.95,
            "gasifier.biomass_carbon_intensity_kg_CO2_per_kg": 0.03,
        },
        connections_human=[("Gasifier H2 out", "Scrubber H2_syngas inlet", "H2 mass balance")],
    ),

    TemplateSpec(
        key="custom.user_flowsheet",
        display_name="Custom Flowsheet",
        category="Custom",
        description="Assemble your own flowsheet: pick up to 8 units from the "
                    "allowlist, set their engineering parameters, and wire ports.",
        topology_diagram=(
            "graph LR\n"
            "    U1[Unit 1] --> U2[Unit 2]\n"
            "    U2 --> U3[Unit 3]\n"
            "    style U1 fill:#95a5a6,color:#fff\n"
            "    style U2 fill:#7f8c8d,color:#fff\n"
            "    style U3 fill:#636e72,color:#fff"
        ),
        unit_labels=[],
        default_params={},
    ),

    TemplateSpec(
        key="small.cstr_flash",
        display_name="CSTR + Flash",
        category="Other Industrial Processes",
        description="Water-gas shift CSTR with adiabatic Arrhenius kinetics "
                    "followed by V/L flash separation (CO2/H2 light, CO/H2O heavy).",
        topology_diagram=(
            "graph LR\n"
            "    Feed([Feed CO/H2O]) --> CSTR[CSTR HF\nArrhenius kinetics]\n"
            "    CSTR --> Flash[Flash V/L\nRachford-Rice]\n"
            "    Flash --> Vap([Vapor CO2/H2])\n"
            "    Flash --> Liq([Liquid CO/H2O])\n"
            "    style CSTR fill:#4a90e2,color:#fff\n"
            "    style Flash fill:#7b68ee,color:#fff"
        ),
        unit_labels=["CSTRHF", "FlashVLHF"],
        default_params={"cstr.volume_m3": 1.0},
        connections_human=[("CSTR outlet", "Flash inlet", "Reactor effluent")],
    ),

    TemplateSpec(
        key="small.compression_train",
        display_name="Compression Train",
        category="Other Industrial Processes",
        description="Gas compressor followed by shell & tube intercooler "
                    "and let-down valve.",
        topology_diagram=(
            "graph LR\n"
            "    Feed([Gas feed]) --> Comp[Compressor]\n"
            "    Comp --> HX[Shell & Tube HX\nIntercooling]\n"
            "    HX --> Valve[Valve]\n"
            "    Valve --> Out([Let-down gas])\n"
            "    style Comp fill:#3498db,color:#fff\n"
            "    style HX fill:#2980b9,color:#fff\n"
            "    style Valve fill:#1a6fa0,color:#fff"
        ),
        unit_labels=["Compressor", "ShellTubeHX", "Valve"],
        default_params={
            "comp.eta_isentropic": 0.75,
            "comp.P_out_Pa": 500_000.0,
            "hx.U_W_per_m2_K": 500.0,
            "hx.A_m2": 10.0,
        },
        connections_human=[
            ("Compressor outlet", "HX hot inlet", "Compressed gas → cooler"),
            ("HX hot outlet", "Valve inlet", "Cooled gas → let-down"),
        ],
    ),

    TemplateSpec(
        key="small.mixer_settler",
        display_name="Mixer + Settler",
        category="Other Industrial Processes",
        description="Two-stream mixer with adiabatic energy balance, "
                    "then split-fraction settler.",
        topology_diagram=(
            "graph LR\n"
            "    F1([Stream 1]) --> Mix[Mixer HF]\n"
            "    F2([Stream 2]) --> Mix\n"
            "    Mix --> Sep[Separator HF]\n"
            "    Sep --> P1([Product 1])\n"
            "    Sep --> P2([Product 2])\n"
            "    style Mix fill:#1abc9c,color:#fff\n"
            "    style Sep fill:#16a085,color:#fff"
        ),
        unit_labels=["MixerHF", "SeparatorHF"],
        connections_human=[("Mixer outlet", "Separator inlet", "Mixed stream")],
    ),

    TemplateSpec(
        key="small.distillation",
        display_name="Distillation Column",
        category="Other Industrial Processes",
        description="FUG shortcut distillation column separating "
                    "benzene (light key) from toluene (heavy key).",
        topology_diagram=(
            "graph LR\n"
            "    Feed([Benzene/Toluene\nfeed]) --> Col[Distillation HF\nFUG shortcut]\n"
            "    Col --> Dist([Distillate\nbenzene-rich])\n"
            "    Col --> Bot([Bottoms\ntoluene-rich])\n"
            "    style Col fill:#f39c12,color:#fff"
        ),
        unit_labels=["DistillationHF"],
    ),

    TemplateSpec(
        key="biomass.gasification_to_hydrogen",
        display_name="Biomass → H2 (Gasification)",
        category="Biomass Processing",
        description=(
            "Full B-HYPSYS flowsheet: drying → thermochemical equilibrium "
            "gasification → WGS reactor → PSA separation. "
            "Reports LCOH, CGE, and H2 production KPIs. SLP-solved."
        ),
        topology_diagram=(
            "graph LR\n"
            "    BS[Biomass Storage\nDrying+Preheating] --> BG[Gasifier\nEquilibrium]\n"
            "    BG -->|Syngas| WGS[WGS Reactor\nCO+H2O→CO2+H2]\n"
            "    WGS -->|H2-rich| PSA[PSA Separator]\n"
            "    PSA --> H2([H2 Product])\n"
            "    PSA --> TG([Tail Gas])\n"
            "    style BS fill:#8e44ad,color:#fff\n"
            "    style BG fill:#e67e22,color:#fff\n"
            "    style WGS fill:#c0392b,color:#fff\n"
            "    style PSA fill:#27ae60,color:#fff"
        ),
        unit_labels=["BiomassStorageHF", "BiomassGasifierHF", "WGSReactorHF", "H2SeparatorPSA"],
        default_params={
            "biomass_type": "Pine Wood",
            "gasifying_agent": "Steam",
            "biomass_feed_kg_s": 1.0,
            "steam_to_biomass_ratio": 1.0,
            "T_gasifier_C": 800.0,
            "T_wgs_C": 400.0,
            "H2_recovery": 0.85,
            "plant_life_yr": 20,
            "interest_rate": 0.08,
            "target_year": 2024,
        },
        supports_milp=False,
        connections_human=[
            ("Biomass Storage dry out", "Gasifier biomass in", "Dry biomass feed"),
            ("Gasifier syngas out", "WGS syngas in", "Raw syngas"),
            ("WGS shifted out", "PSA feed in", "H2-rich shifted gas"),
        ],
    ),

    TemplateSpec(
        key="industrial.grand_challenge_10unit",
        display_name="Grand Challenge: Biomass → H2 (10-Unit)",
        category="Biomass Processing",
        description=(
            "Full 10-unit biomass-to-green-H2 flowsheet: drying → gasification → "
            "cyclone → HTS-WGS → LTS-WGS → moisture separator → CO2 scrubber → "
            "PSA → H2 compression → H2 polisher. "
            "Grand-challenge validation case with analytical mass-balance verification."
        ),
        topology_diagram=(
            "graph LR\n"
            "    ST[1. Storage\nDrying] --> GAS[2. Gasifier\nEquilibrium]\n"
            "    GAS -->|Syngas| CYC[3. Cyclone\nChar Removal]\n"
            "    CYC -->|Clean Gas| HTS[4. HTS-WGS\n400°C]\n"
            "    HTS -->|Shifted| LTS[5. LTS-WGS\n220°C]\n"
            "    LTS -->|H2-rich| MSP[6. Moisture\nSeparator]\n"
            "    MSP -->|Dry Gas| CO2[7. CO2\nScrubber]\n"
            "    CO2 -->|H2-rich| PSA[8. PSA\nSeparator]\n"
            "    PSA -->|Pure H2| CMP[9. Compressor]\n"
            "    CMP -->|Compressed H2| POL[10. H2 Polisher]\n"
            "    POL --> H2PROD([H2 Product])\n"
            "    style ST fill:#8e44ad,color:#fff\n"
            "    style GAS fill:#e67e22,color:#fff\n"
            "    style HTS fill:#c0392b,color:#fff\n"
            "    style LTS fill:#c0392b,color:#fff\n"
            "    style PSA fill:#27ae60,color:#fff\n"
            "    style CMP fill:#2980b9,color:#fff\n"
            "    style POL fill:#16a085,color:#fff"
        ),
        unit_labels=[
            "BiomassStorageHF", "BiomassGasifierHF", "SeparatorHF(cyclone)",
            "WGSReactorHF(hts)", "WGSReactorHF(lts)", "SeparatorHF(moisture_sep)",
            "SeparatorHF(co2_scrubber)", "H2SeparatorPSA", "Compressor", "SeparatorHF(h2_polisher)",
        ],
        default_params={
            "biomass_type": "Pine Wood",
            "gasifying_agent": "Steam",
            "biomass_feed_kg_s": 1.0,
            "steam_to_biomass_ratio": 1.0,
            "T_gasifier_C": 800.0,
            "T_hts_C": 400.0,
            "T_lts_C": 220.0,
            "H2_recovery": 0.94,
            "P_out_Pa": 5_000_000.0,
            "plant_life_yr": 20,
            "interest_rate": 0.08,
            "target_year": 2024,
        },
        supports_milp=False,
        connections_human=[
            ("Storage dry out", "Gasifier biomass in", "Dry biomass feed"),
            ("Gasifier syngas out", "Cyclone inlet", "Raw syngas with char"),
            ("Cyclone outlet 0", "HTS-WGS syngas in", "Clean syngas"),
            ("HTS shifted out", "LTS-WGS syngas in", "HTS-shifted gas"),
            ("LTS shifted out", "Moisture sep inlet", "H2-rich wet gas"),
            ("Moisture sep outlet 0", "CO2 scrubber inlet", "Dry H2-rich gas"),
            ("CO2 scrubber outlet 0", "PSA feed in", "H2/CO2 lean gas"),
            ("PSA h2 out", "Compressor inlet", "Pure H2 product"),
            ("Compressor outlet", "H2 polisher inlet", "Compressed H2"),
        ],
    ),

    TemplateSpec(
        key="dac.power_to_methane",
        display_name="Direct Air Capture → Methane (DAC-U)",
        category="Carbon Capture & Utilization",
        description=(
            "Power-to-Methane via TVSA CO₂ capture (415 ppm), PEM electrolysis, "
            "and Sabatier methanation (CO₂ + 4H₂ → CH₄ + 2H₂O). "
            "Reports CO₂ capture rate, SNG production, and specific energy KPIs."
        ),
        topology_diagram=(
            "graph LR\n"
            "    AIR([Ambient Air]) --> TVSA[TVSA Contactor\nCO2 capture]\n"
            "    TVSA --> CO2([CO2 stream])\n"
            "    WATER([Water]) --> ELEC[PEM Electrolyser]\n"
            "    ELEC --> H2([H2 stream])\n"
            "    CO2 --> MR[Methanation\nSabatier Reactor]\n"
            "    H2 --> MR\n"
            "    MR --> SNG([Synthetic Natural Gas])\n"
            "    style TVSA fill:#1a6b8a,color:#fff\n"
            "    style ELEC fill:#4a90e2,color:#fff\n"
            "    style MR fill:#c0392b,color:#fff"
        ),
        unit_labels=["TVSAContactor", "ElectrolyserHF", "MethanationReactor"],
        default_params={
            "F_air_mol_s": 10_000.0,
            "eta_cap": 0.85,
            "eta_elec": 0.70,
            "T_rx_K": 673.0,
            "plant_life_yr": 20,
            "interest_rate": 0.08,
            "target_year": 2024,
        },
        supports_milp=False,
        connections_human=[
            ("TVSAContactor.co2_out", "MethanationReactor.co2_in", "Captured CO2"),
            ("ElectrolyserHF.h2_out", "MethanationReactor.h2_in", "Green H2"),
        ],
    ),
]

_REGISTRY_MAP: Dict[str, TemplateSpec] = {t.key: t for t in _REGISTRY}


# ── Public API ────────────────────────────────────────────────────────────────

def list_templates() -> List[TemplateSpec]:
    """Return all registered templates."""
    return list(_REGISTRY)


def get_template(key: str) -> TemplateSpec:
    """Return a single TemplateSpec by key.  Raises ``KeyError`` if absent."""
    return _REGISTRY_MAP[key]


def load_template(key: str, params: Optional[Dict[str, Any]] = None) -> "BaseFlowsheet":
    """Import the factory for *key* and return a ``BaseFlowsheet``."""
    p = dict(_REGISTRY_MAP[key].default_params)
    p.update(params or {})
    loader = _LOADER_MAP.get(key)
    if loader is None:
        raise ValueError(f"No loader registered for template key '{key}'.")
    return loader(p)


def load_template_with_choices(
    key: str,
    params: Optional[Dict[str, Any]] = None,
) -> "Tuple[BaseFlowsheet, list]":
    """Like ``load_template`` but returns ``(flowsheet, technology_choices)``.

    Only valid for MILP templates (``supports_milp=True``).
    """
    spec = _REGISTRY_MAP[key]
    if not spec.supports_milp:
        raise ValueError(
            f"Template '{key}' does not support MILP.  "
            "Use load_template() instead."
        )
    p = dict(spec.default_params)
    p.update(params or {})
    loader = _MILP_LOADER_MAP.get(key)
    if loader is None:
        raise ValueError(f"No MILP loader registered for template key '{key}'.")
    return loader(p)


# ── Port-resolution helpers ───────────────────────────────────────────────────
# Units use various port attribute names.  These helpers try candidates in
# priority order so build_custom_flowsheet() works across all AVAILABLE_UNITS.

_OUTLET_NAMED: tuple = (
    "outlet_port",       # StoichiometricReactor, Compressor, Pump, Valve, MixerHF
    "hot_outlet_port",   # HeatExchangerNTU (process hot side)
    "syngas_out_port",   # BiomassGasifierHF
    "shifted_out_port",  # WGSReactorHF
    "h2_out_port",       # H2SeparatorPSA
    "dry_out_port",      # BiomassStorageHF
    "vapor_port",        # FlashVLHF (primary vapour outlet)
)
_OUTLET_LISTS: tuple = ("outlet_ports",)   # SeparatorHF

_INLET_NAMED: tuple = (
    "inlet_port",        # StoichiometricReactor, SeparatorHF, Compressor, FlashVLHF
    "hot_inlet_port",    # HeatExchangerNTU
    "syngas_in_port",    # WGSReactorHF
    "feed_in_port",      # H2SeparatorPSA
    "biomass_in_port",   # BiomassGasifierHF
    "wet_in_port",       # BiomassStorageHF
)
_INLET_LISTS: tuple = ("inlet_ports",)     # MixerHF


def _primary_outlet(unit: Any):
    """Return the unit's primary outlet StreamPort, or None for flat-variable units."""
    for name in _OUTLET_NAMED:
        p = getattr(unit, name, None)
        if p is not None:
            return p
    for name in _OUTLET_LISTS:
        lst = getattr(unit, name, None)
        if lst:
            return lst[0]
    return None


def _primary_inlet(unit: Any):
    """Return the unit's primary inlet StreamPort, or None for flat-variable units."""
    for name in _INLET_NAMED:
        p = getattr(unit, name, None)
        if p is not None:
            return p
    for name in _INLET_LISTS:
        lst = getattr(unit, name, None)
        if lst:
            return lst[0]
    return None


def build_custom_flowsheet(config: Dict[str, Any]) -> "BaseFlowsheet":
    """Assemble a BaseFlowsheet from a user-defined unit + connection config.

    Parameters
    ----------
    config : dict with keys:
        ``"units"`` — list of dicts: {``"type"``: str, ``"id"``: str, ``"params"``: dict}
            Use ``"type": "__composite__"`` for pre-built CompositeUnit objects
            supplied via the ``"__composites__"`` key.
        ``"connections"`` — list of dicts: {``"from_unit"``: str, ``"to_unit"``: str}
            Each connection wires *from_unit*.outlet_port → *to_unit*.inlet_port.
        ``"__composites__"`` — optional dict mapping unit_id → pre-built CompositeUnit.

    Only unit types in ``AVAILABLE_UNITS`` (or ``"__composite__"``) are accepted.
    """
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet

    composites: Dict[str, Any] = config.get("__composites__", {})
    unit_objects = []
    unit_map: Dict[str, Any] = {}

    for unit_cfg in config.get("units", []):
        utype  = unit_cfg["type"]
        uid    = unit_cfg["id"]
        params = unit_cfg.get("params", {})

        if utype == "__composite__":
            unit_obj = composites.get(uid)
            if unit_obj is None:
                raise ValueError(
                    f"Composite unit '{uid}' declared but not found in '__composites__' dict."
                )
        elif utype not in AVAILABLE_UNITS:
            raise ValueError(
                f"Unit type '{utype}' is not in the allowed list. "
                f"Choose from: {list(AVAILABLE_UNITS)}"
            )
        else:
            unit_obj = _instantiate_unit(utype, uid, params)

        unit_objects.append(unit_obj)
        unit_map[uid] = unit_obj

    fs = BaseFlowsheet(name="custom.user_flowsheet", units=unit_objects)

    conn_warnings: list = []
    for conn in config.get("connections", []):
        from_u = unit_map.get(conn["from_unit"])
        to_u   = unit_map.get(conn["to_unit"])
        if from_u is None or to_u is None:
            continue
        out_port = _primary_outlet(from_u)
        in_port  = _primary_inlet(to_u)
        if out_port is not None and in_port is not None:
            try:
                fs.connect(out_port, in_port,
                           description=f"{conn['from_unit']} → {conn['to_unit']}")
            except ValueError:
                # Variable-count mismatch (usually T/P present on one port but not the other).
                # Fall back to linking only component flow variables (.F_*).
                from pse_ecosystem.flowsheets.base_flowsheet import Connection as _Conn
                a_flows = [v for v in out_port.variable_names() if ".F_" in v]
                b_flows = [v for v in in_port.variable_names() if ".F_" in v]
                if len(a_flows) == len(b_flows) and a_flows:
                    for va, vb in zip(a_flows, b_flows):
                        fs.connections.append(_Conn(
                            var_a=va, var_b=vb,
                            description=f"{conn['from_unit']} → {conn['to_unit']} (flow-only)",
                        ))
                else:
                    conn_warnings.append(
                        f"{conn['from_unit']} → {conn['to_unit']}: "
                        f"component count mismatch ({len(a_flows)} vs {len(b_flows)}), skipped"
                    )
        elif out_port is None and in_port is None:
            conn_warnings.append(
                f"{conn['from_unit']} → {conn['to_unit']}: "
                "neither unit exposes outlet_port / inlet_port (toy units connect via KPI flow, not StreamPorts)"
            )

    fs._conn_warnings = conn_warnings
    return fs


def build_composite_unit(
    template_key: str,
    unit_id: str,
    exposed_inputs: List[str],
    exposed_outputs: List[str],
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Wrap a built-in template as a CompositeUnit for hierarchical flowsheet composition.

    The inner template is solved as a sub-problem during the outer SLP
    iteration.  ``exposed_inputs`` / ``exposed_outputs`` are variable names
    from the inner flowsheet that the parent flowsheet can drive / read.
    """
    from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit
    inner_fs = load_template(template_key, params or {})
    return CompositeUnit(unit_id, inner_fs, exposed_inputs, exposed_outputs)


def _instantiate_unit(utype: str, uid: str, params: dict) -> Any:
    """Instantiate a unit by type name using safe deferred imports."""
    if utype == "PEMToy":
        from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams
        p = PEMToyParams(
            eta_kg_per_kWh=float(params.get("eta_kg_per_kWh", 0.018)),
            capacity_kW=float(params.get("capacity_kW", 10_000.0)),
            electricity_price_per_kWh=float(params.get("electricity_price_per_kWh", 0.05)),
            capex_annual_per_kW=float(params.get("capex_annual_per_kW", 100.0)),
            grid_carbon_intensity_kg_CO2_per_kWh=float(
                params.get("grid_carbon_intensity_kg_CO2_per_kWh", 0.233)
            ),
        )
        return PEMToy(uid, p)

    if utype == "GasifierToy":
        from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy, GasifierToyParams
        p = GasifierToyParams(
            biomass_carbon_intensity_kg_CO2_per_kg=float(
                params.get("biomass_carbon_intensity_kg_CO2_per_kg", 0.03)
            ),
        )
        return GasifierToy(uid, p)

    if utype == "StoichiometricReactor":
        from pse_ecosystem.models.reactors.stoichiometric_reactor import (
            StoichiometricReactor, StoichiometricParams,
        )
        components = params.get("components", ["CO2", "H2", "methanol", "water"])
        stoich = params.get("stoichiometry", {"CO2": [-1.0], "H2": [-3.0],
                                               "methanol": [1.0], "water": [1.0]})
        sp = StoichiometricParams(
            stoichiometry={c: stoich.get(c, [0.0]) for c in components},
            xi_max=params.get("xi_max", None),
            feed_max=float(params.get("feed_max", 50.0)),
        )
        return StoichiometricReactor(uid, components, sp)

    if utype == "MixerHF":
        from pse_ecosystem.models.mixers.mixer_hf import MixerHF, MixerHFParams
        components = params.get("components", ["H2", "H2O"])
        mp = MixerHFParams(n_inlets=int(params.get("n_inlets", 2)))
        return MixerHF(uid, components, mp)

    if utype == "SeparatorHF":
        from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
        components = params.get("components", ["H2", "CO2"])
        sp = SeparatorHFParams(n_outlets=int(params.get("n_outlets", 2)))
        return SeparatorHF(uid, components, sp)

    if utype == "FlashVLHF":
        from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
        from pse_ecosystem.models.properties.vle import ANTOINE
        components = params.get("components", ["benzene", "toluene"])
        # Only include species that have Antoine constants; fall back to benzene/toluene
        vle_species = [c for c in components if c in ANTOINE]
        if len(vle_species) < 2:
            vle_species = ["benzene", "toluene"]
            components = vle_species
        fp = FlashVLHFParams(
            species_vle=list(vle_species),
            feed_max=float(params.get("feed_max", 1e4)),
            T_min=float(params.get("T_min", 250.0)),
            T_max=float(params.get("T_max", 550.0)),
            P_min=float(params.get("P_min", 1e3)),
            P_max=float(params.get("P_max", 1e7)),
        )
        return FlashVLHF(uid, components, fp)

    if utype == "Compressor":
        from pse_ecosystem.models.pressure_changers.compressor import Compressor, CompressorParams
        components = params.get("components", ["H2", "CO", "CO2"])
        cp = CompressorParams(
            eta_isentropic=float(params.get("eta_isentropic", 0.78)),
            P_out_Pa=float(params.get("P_out_Pa", 500_000.0)),
        )
        return Compressor(uid, components, cp)

    if utype == "HeatExchangerNTU":
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import (
            HeatExchangerNTU, HeatExchangerNTUParams,
        )
        shared = params.get("components", [])
        hot  = params.get("hot_components",  shared or ["H2", "CO"])
        cold = params.get("cold_components", ["H2O"])
        hp = HeatExchangerNTUParams(
            UA_W_per_K=float(params.get("UA_W_per_K", 5000.0)),
        )
        return HeatExchangerNTU(uid, hot, cold, hp)

    if utype == "TVSAContactor":
        from pse_ecosystem.models.dac.tvsa_contactor import TVSAContactor
        return TVSAContactor(
            uid,
            eta_cap=float(params.get("eta_cap", 0.85)),
            dP_fan_Pa=float(params.get("dP_fan_Pa", 200.0)),
            eta_fan=float(params.get("eta_fan", 0.75)),
            dH_des_kJ_per_mol=float(params.get("dH_des_kJ_per_mol", 70.0)),
            T_des_K=float(params.get("T_des_K", 393.0)),
            P_ads_kPa=float(params.get("P_ads_kPa", 101.325)),
            P_des_kPa=float(params.get("P_des_kPa", 5.0)),
            eta_vac=float(params.get("eta_vac", 0.70)),
        )

    if utype == "ElectrolyserHF":
        from pse_ecosystem.models.dac.electrolyser_hf import ElectrolyserHF
        return ElectrolyserHF(uid, eta_elec=float(params.get("eta_elec", 0.70)))

    if utype == "MethanationReactor":
        from pse_ecosystem.models.dac.methanation_reactor import MethanationReactor
        return MethanationReactor(
            uid, T_rx_K_default=float(params.get("T_rx_K", 673.0))
        )

    if utype == "CHPUnit":
        from pse_ecosystem.models.power.chp_unit import CHPUnit
        return CHPUnit(
            uid,
            eta_comb=float(params.get("eta_comb", 0.95)),
            eta_isentropic=float(params.get("eta_isentropic", 0.85)),
            eta_mechanical=float(params.get("eta_mechanical", 0.98)),
            eta_hrec=float(params.get("eta_hrec", 0.85)),
            lambda_air=float(params.get("lambda_air", 1.1)),
        )

    if utype == "BiomassStorageHF":
        from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
        return BiomassStorageHF(
            uid,
            biomass_type=params.get("biomass_type", "Pine Wood"),
            T_in_C=float(params.get("T_in_C", 15.0)),
            T_preheat_C=float(params.get("T_preheat_C", 200.0)),
        )

    if utype == "BiomassGasifierHF":
        from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
        return BiomassGasifierHF(
            uid,
            biomass_type=params.get("biomass_type", "Pine Wood"),
            T_gasifier_C=float(params.get("T_gasifier_C", 800.0)),
            gasifying_agent=params.get("gasifying_agent", "Steam"),
            P_atm=float(params.get("P_atm", 1.0)),
            biomass_cost_USD_per_kg=float(params.get("biomass_cost_USD_per_kg", 0.05)),
        )

    if utype == "WGSReactorHF":
        from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
        return WGSReactorHF(
            uid,
            T_wgs_C=float(params.get("T_wgs_C", 400.0)),
        )

    if utype == "CoolerHF":
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF, CoolerHFParams
        components = params.get("components", ["H2", "CO", "CO2", "H2O", "CH4", "N2"])
        cp = CoolerHFParams(
            T_out_K=float(params.get("T_out_K", 400.0)),
            feed_max=float(params.get("feed_max", 1_000.0)),
        )
        return CoolerHF(uid, components, cp)

    # ── v1.4.0 audit H11: newly registered UI types ──────────────────────────
    if utype == "Pump":
        from pse_ecosystem.models.pressure_changers.pump import Pump, PumpParams
        components = params.get("components", ["H2O"])
        p_out = params.get("P_out_Pa", 1_000_000.0)
        pp = PumpParams(
            eta_pump=float(params.get("eta_pump", 0.75)),
            P_out_Pa=float(p_out) if p_out else None,
        )
        return Pump(uid, components, pp)

    if utype == "Valve":
        from pse_ecosystem.models.pressure_changers.valve import Valve, ValveParams
        components = params.get("components", ["H2", "CO", "CO2"])
        cv_val = params.get("Cv", None)
        p_out = params.get("P_out_Pa", None)
        vp = ValveParams(
            Cv=float(cv_val) if cv_val not in (None, 0.0) else None,
            P_out_Pa=float(p_out) if p_out not in (None, 0.0) else None,
        )
        return Valve(uid, components, vp)

    if utype == "ShellTubeHX":
        from pse_ecosystem.models.heat_exchangers.shell_tube import ShellTubeHX, ShellTubeParams
        shared = params.get("components", [])
        hot  = params.get("hot_components",  shared or ["H2", "CO"])
        cold = params.get("cold_components", ["H2O"])
        sp = ShellTubeParams(
            U_W_per_m2_K=float(params.get("U_W_per_m2_K", 500.0)),
            A_m2=float(params.get("A_m2", 16.0)),
            n_shell_passes=int(params.get("n_shell_passes", 1)),
            n_tube_passes=int(params.get("n_tube_passes", 2)),
        )
        return ShellTubeHX(uid, hot, cold, sp)

    if utype == "H2SeparatorPSA":
        from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
        return H2SeparatorPSA(uid, H2_recovery=float(params.get("H2_recovery", 0.85)))

    if utype == "GibbsReactor":
        from pse_ecosystem.models.reactors.gibbs_reactor import GibbsReactor, GibbsReactorParams
        components = params.get("components", ["H2", "CO", "CO2", "H2O"])
        gp = GibbsReactorParams(T_max=float(params.get("T_max", 2000.0)))
        return GibbsReactor(uid, components, gp)

    if utype == "EquilibriumReactor":
        from pse_ecosystem.models.reactors.equilibrium_reactor import (
            EquilibriumReactor, EquilReactorParams,
        )
        from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
        components = params.get("components", ["CO", "H2O", "CO2", "H2"])
        # Default reaction set is WGS (CO + H₂O ↔ CO₂ + H₂). ReactionConfig
        # carries kinetic fields (k0, Ea, orders) that the equilibrium driver
        # ignores; we still have to fill them. Override by passing a full
        # `reactions` list through the Python API.
        default_rxn = ReactionConfig(
            stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
            k0=1.0,
            Ea_J_per_mol=0.0,
            reaction_orders={"CO": 1.0, "H2O": 1.0},
            delta_H_J_per_mol=-41_200.0,
            name="WGS",
        )
        ep = EquilReactorParams(
            reactions=params.get("reactions", [default_rxn]),
            Keq_ref=params.get("Keq_ref_list", [float(params.get("Keq_ref", 8.9))]),
            T_ref_K=float(params.get("T_ref_K", 673.0)),
        )
        return EquilibriumReactor(uid, components, ep)

    if utype == "DistillationHF":
        from pse_ecosystem.models.separators.distillation_hf import (
            DistillationHF, DistillationHFParams,
        )
        from pse_ecosystem.models.properties.vle import ANTOINE
        components = params.get("components", ["benzene", "toluene"])
        vle_species = [c for c in components if c in ANTOINE]
        if len(vle_species) < 2:
            vle_species = ["benzene", "toluene"]
            components = vle_species
        hk = params.get("hk", "toluene")
        lk = params.get("lk", "benzene")
        # v1.4.0 audit N20 — pre-fix this silently rewrote user-selected
        # hk/lk to the first/last VLE species when they were missing from
        # the component list. The user's intent was lost. Now we raise so
        # the caller knows the mismatch and can pass valid keys.
        if hk not in components:
            raise ValueError(
                f"DistillationHF heavy key {hk!r} not in components "
                f"{components!r}. Pass a 'hk' that names one of the unit's "
                f"declared species."
            )
        if lk not in components:
            raise ValueError(
                f"DistillationHF light key {lk!r} not in components "
                f"{components!r}. Pass a 'lk' that names one of the unit's "
                f"declared species."
            )
        dp = DistillationHFParams(
            species_vle=vle_species,
            lk=lk,
            hk=hk,
            T_op_K=float(params.get("T_op_K", 350.0)),
            R_over_Rmin=float(params.get("R_over_Rmin", 1.3)),
        )
        return DistillationHF(uid, components, dp)

    raise ValueError(f"Unknown unit type: {utype}")


# ── Deferred layer-3 loaders ─────────────────────────────────────────────────

def _load_electrolysis_only(p: dict):
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.models.electrolysis.pem_toy import PEMToyParams
    pem_p = PEMToyParams(
        eta_kg_per_kWh=float(p.get("pem.eta_kg_per_kWh", 0.018)),
        capacity_kW=float(p.get("pem.capacity_kW", 10_000.0)),
        electricity_price_per_kWh=float(p.get("pem.electricity_price_per_kWh", 0.05)),
        capex_annual_per_kW=float(p.get("pem.capex_annual_per_kW", 100.0)),
        grid_carbon_intensity_kg_CO2_per_kWh=float(
            p.get("pem.grid_carbon_intensity_kg_CO2_per_kWh", 0.233)
        ),
    )
    return make_electrolysis_only(
        h2_demand_kg_per_h=float(p["h2_demand_kg_per_h"]),
        pem_params=pem_p,
    )


def _load_electrolysis_or_gasification_flowsheet(p: dict):
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_or_gasification
    fs, _ = make_electrolysis_or_gasification(
        h2_demand_kg_per_h=float(p["h2_demand_kg_per_h"])
    )
    return fs


def _load_electrolysis_or_gasification_milp(p: dict):
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_or_gasification
    return make_electrolysis_or_gasification(
        h2_demand_kg_per_h=float(p["h2_demand_kg_per_h"])
    )


def _load_green_hydrogen(p: dict):
    from pse_ecosystem.flowsheets.industrial.green_hydrogen import make_green_hydrogen_hub
    from pse_ecosystem.models.electrolysis.pem_toy import PEMToyParams
    pem_p = PEMToyParams(
        eta_kg_per_kWh=float(p.get("pem.eta_kg_per_kWh", 0.018)),
        capacity_kW=float(p.get("pem.capacity_kW", 10_000.0)),
        electricity_price_per_kWh=float(p.get("pem.electricity_price_per_kWh", 0.05)),
        capex_annual_per_kW=float(p.get("pem.capex_annual_per_kW", 100.0)),
        grid_carbon_intensity_kg_CO2_per_kWh=float(
            p.get("pem.grid_carbon_intensity_kg_CO2_per_kWh", 0.233)
        ),
    )
    return make_green_hydrogen_hub(
        h2_demand_kg_per_h=float(p["h2_demand_kg_per_h"]),
        pem_params=pem_p,
    )


def _load_power_to_methanol(p: dict):
    from pse_ecosystem.flowsheets.industrial.power_to_methanol import make_power_to_methanol
    return make_power_to_methanol(extent_max=float(p.get("extent_max", 3.0)))


def _load_gasification_to_power(p: dict):
    from pse_ecosystem.flowsheets.industrial.gasification_to_power import make_gasification_to_power
    from pse_ecosystem.models.pressure_changers.compressor import CompressorParams
    comp_p = CompressorParams(
        eta_isentropic=float(p.get("comp.eta_isentropic", 0.78)),
        P_out_Pa=float(p.get("comp.P_out_Pa", 500_000.0)),
        feed_max=30.0, T_min=300.0, T_max=2000.0, P_min=1e4, P_max=2e7,
    )
    return make_gasification_to_power(
        extent_max=float(p.get("extent_max", 4.0)),
        comp_params=comp_p,
    )


def _load_syngas_production(p: dict):
    from pse_ecosystem.flowsheets.industrial.syngas_production import make_syngas_production
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToyParams
    gas_p = GasifierToyParams(
        biomass_carbon_intensity_kg_CO2_per_kg=float(
            p.get("gasifier.biomass_carbon_intensity_kg_CO2_per_kg", 0.03)
        ),
    )
    return make_syngas_production(
        h2_demand_kg_per_h=float(p.get("h2_demand_kg_per_h", 200.0)),
        gasifier_params=gas_p,
        co2_capture_fraction=float(p.get("co2_capture_fraction", 0.95)),
    )


def _load_cstr_flash(p: dict):
    from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig
    from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    components = ["CO", "H2O", "CO2", "H2"]
    wgs = ReactionConfig(
        stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
        k0=1e3, Ea_J_per_mol=50_000.0,
        reaction_orders={"CO": 1.0, "H2O": 1.0},
        delta_H_J_per_mol=-41_000.0,
    )
    cstr  = CSTRHF("cstr", components,
                   CSTRHFParams(reactions=[wgs],
                                volume_m3=float(p.get("cstr.volume_m3", 1.0))))
    flash = FlashVLHF("flash", components,
                      FlashVLHFParams(species_vle=["CO2", "H2"],
                                      T_min=200.0, T_max=1500.0))
    fs = BaseFlowsheet(name="small.cstr_flash", units=[cstr, flash])
    fs.connect(cstr.outlet_port, flash.inlet_port, description="CSTR → Flash")
    fs.extra_bounds["cstr.inlet.F_CO"]  = (10.0, 10.0)
    fs.extra_bounds["cstr.inlet.F_H2O"] = (10.0, 10.0)
    fs.extra_bounds["cstr.inlet.F_CO2"] = (0.0, 0.0)
    fs.extra_bounds["cstr.inlet.F_H2"]  = (0.0, 0.0)
    fs.extra_bounds["cstr.inlet.T"]     = (700.0, 700.0)
    fs.extra_bounds["cstr.inlet.P"]     = (101325.0, 101325.0)
    return fs


def _load_compression_train(p: dict):
    from pse_ecosystem.flowsheets.small.compression_train import make_compression_train
    from pse_ecosystem.models.pressure_changers.compressor import CompressorParams
    from pse_ecosystem.models.heat_exchangers.shell_tube import ShellTubeParams
    comp_p = CompressorParams(
        eta_isentropic=float(p.get("comp.eta_isentropic", 0.75)),
        P_out_Pa=float(p.get("comp.P_out_Pa", 500_000.0)),
    )
    hx_p = ShellTubeParams(
        U_W_per_m2_K=float(p.get("hx.U_W_per_m2_K", 500.0)),
        A_m2=float(p.get("hx.A_m2", 10.0)),
    )
    return make_compression_train(
        hot_components=["CO", "H2", "CO2"],
        cold_components=["H2O"],
        P_compressed_Pa=float(p.get("comp.P_out_Pa", 500_000.0)),
        comp_params=comp_p,
        hx_params=hx_p,
    )


def _load_mixer_settler(p: dict):
    from pse_ecosystem.flowsheets.small.mixer_settler import make_mixer_settler
    components = ["H2", "CH4", "CO2"]
    fs = make_mixer_settler(
        components=components,
        split_fractions=[[0.8, 0.2], [0.3, 0.7], [0.6, 0.4]],
    )
    for inlet_k in ["0", "1"]:
        for c in components:
            fs.extra_bounds[f"mixer.inlet_{inlet_k}.F_{c}"] = (0.0, 100.0)
        fs.extra_bounds[f"mixer.inlet_{inlet_k}.T"] = (300.0, 800.0)
        fs.extra_bounds[f"mixer.inlet_{inlet_k}.P"] = (1e4, 1e7)
    return fs


def _load_distillation(p: dict):
    from pse_ecosystem.flowsheets.small.distillation_column import make_distillation_column
    fs = make_distillation_column(
        components=["benzene", "toluene"],
        lk="benzene", hk="toluene",
        species_vle=["benzene", "toluene"],
    )
    fs.extra_bounds["col.feed.F_benzene"] = (5.0, 5.0)
    fs.extra_bounds["col.feed.F_toluene"] = (5.0, 5.0)
    fs.extra_bounds["col.feed.T"] = (350.0, 350.0)
    fs.extra_bounds["col.feed.P"] = (101325.0, 101325.0)
    return fs


def _load_custom_user_flowsheet(p: dict):
    # Returns an empty single-PEM flowsheet as a safe placeholder.
    # The real custom flowsheet is built via build_custom_flowsheet().
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    return make_electrolysis_only(h2_demand_kg_per_h=100.0)


def _load_biomass_gasification_to_h2(p: dict):
    from pse_ecosystem.models.biomass.biomass_database import get_biomass, element_feeds_mol_s
    from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
    from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
    from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
    from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet

    biomass_type   = str(p.get("biomass_type", "Pine Wood"))
    agent          = str(p.get("gasifying_agent", "Steam"))
    feed_wet_kg_s  = float(p.get("biomass_feed_kg_s", 1.0))
    sb_ratio       = float(p.get("steam_to_biomass_ratio", 1.0))
    T_gas_C        = float(p.get("T_gasifier_C", 800.0))
    T_wgs_C        = float(p.get("T_wgs_C", 400.0))
    H2_recovery    = float(p.get("H2_recovery", 0.85))

    b = get_biomass(biomass_type)
    MC = b["MC"]
    feed_dry_kg_s = feed_wet_kg_s * (1.0 - MC)

    # Instantiate units
    storage  = BiomassStorageHF("storage",  biomass_type=biomass_type)
    gasifier = BiomassGasifierHF("gasifier", biomass_type=biomass_type,
                                  T_gasifier_C=T_gas_C, gasifying_agent=agent)
    wgs      = WGSReactorHF("wgs", T_wgs_C=T_wgs_C)
    psa      = H2SeparatorPSA("psa", H2_recovery=H2_recovery)

    fs = BaseFlowsheet(name="biomass.gasification_to_hydrogen",
                       units=[storage, gasifier, wgs, psa])

    # Port-validated connections
    fs.connect(storage.dry_out_port,  gasifier.biomass_in_port,
               description="Dry biomass → gasifier")
    fs.connect(gasifier.syngas_out_port, wgs.syngas_in_port,
               description="Raw syngas → WGS")
    fs.connect(wgs.shifted_out_port,  psa.feed_in_port,
               description="Shifted gas → PSA")

    # Fix wet biomass feed (design basis)
    fs.extra_bounds["storage.wet_in.F_Biomass"]  = (feed_wet_kg_s,  feed_wet_kg_s)

    # Fix steam agent feed (computed from mass ratio)
    n_steam = feed_dry_kg_s * sb_ratio * 1000.0 / 18.015   # mol/s
    fs.extra_bounds["gasifier.agent_in.F_H2O"] = (n_steam, n_steam)

    # Approximate initial syngas composition for SLP warm start
    # Based on element feeds at 800°C typical distribution
    feeds = element_feeds_mol_s(biomass_type, feed_dry_kg_s)
    n_C = feeds["C"]
    n_H = feeds["H"] + 2.0 * n_steam
    n_O = feeds["O"] + n_steam
    # Rough split: 60% CO, 30% CO2, 10% CH4 for carbon; remaining H2
    n_CO_est  = max(0.60 * n_C, 0.01)
    n_CO2_est = max(0.30 * n_C, 0.01)
    n_CH4_est = max(0.10 * n_C, 0.01)
    n_H2O_est = max(0.10 * n_O, 0.01)
    n_H2_est  = max((n_H - 2.0 * n_H2O_est - 4.0 * n_CH4_est) / 2.0, 0.01)
    n_N2_est  = max(feeds["N"] / 2.0, 0.001)

    _vars_est = {
        "gasifier.syngas_out.F_H2":  n_H2_est,
        "gasifier.syngas_out.F_CO":  n_CO_est,
        "gasifier.syngas_out.F_CO2": n_CO2_est,
        "gasifier.syngas_out.F_H2O": n_H2O_est,
        "gasifier.syngas_out.F_CH4": n_CH4_est,
        "gasifier.syngas_out.F_N2":  n_N2_est,
    }
    # v1.5.0.dev-AUDIT4 (#1): loosen bounds 10× wider than the v1.4 heuristic
    # (was 0.4×–4×; now 0.05×–20×).  The tight heuristic intersected with the
    # nonlinear equilibrium residuals to give LP-infeasible iterations at
    # iter=27 under every SLP config tried.  The wider bounds let the SLP
    # explore the equilibrium manifold; physics still constrained by the
    # element balance + equilibrium residuals from the gasifier model.
    for v, est in _vars_est.items():
        lo = max(est * 0.05, 1e-6)
        hi = max(est * 20.0, lo + 0.1)
        fs.extra_bounds[v] = (lo, hi)

    # WGS inlet/outlet bounds — also widened to 0.05×–20×
    X_CO_est = 0.8
    fs.extra_bounds["wgs.syngas_in.F_H2"]  = (max(n_H2_est * 0.05, 1e-6), n_H2_est * 20.0)
    fs.extra_bounds["wgs.syngas_in.F_CO"]  = (max(n_CO_est * 0.05, 1e-6), n_CO_est * 20.0)
    fs.extra_bounds["wgs.syngas_in.F_CO2"] = (max(n_CO2_est * 0.05, 1e-6), n_CO2_est * 20.0)
    fs.extra_bounds["wgs.syngas_in.F_H2O"] = (max(n_H2O_est * 0.05, 1e-6), n_H2O_est * 20.0)
    fs.extra_bounds["wgs.syngas_in.F_CH4"] = (max(n_CH4_est * 0.05, 1e-6), n_CH4_est * 20.0)
    fs.extra_bounds["wgs.syngas_in.F_N2"]  = (max(n_N2_est * 0.05, 1e-9),  n_N2_est * 20.0)

    dn_CO = n_CO_est * X_CO_est
    fs.extra_bounds["wgs.shifted_out.F_H2"]  = (max((n_H2_est + dn_CO) * 0.05, 1e-6),
                                                  (n_H2_est + dn_CO) * 20.0)
    fs.extra_bounds["wgs.shifted_out.F_CO"]  = (max(n_CO_est * (1 - X_CO_est) * 0.05, 1e-6),
                                                  n_CO_est * 20.0)
    fs.extra_bounds["wgs.shifted_out.F_CO2"] = (max((n_CO2_est + dn_CO) * 0.05, 1e-6),
                                                  (n_CO2_est + dn_CO) * 20.0)
    fs.extra_bounds["wgs.shifted_out.F_H2O"] = (max((n_H2O_est - dn_CO) * 0.05, 1e-6),
                                                  n_H2O_est * 20.0)
    fs.extra_bounds["wgs.shifted_out.F_CH4"] = (max(n_CH4_est * 0.05, 1e-6), n_CH4_est * 20.0)
    fs.extra_bounds["wgs.shifted_out.F_N2"]  = (max(n_N2_est * 0.05, 1e-9), n_N2_est * 20.0)

    # PSA feed bounds (mirrors WGS shifted out, same widened convention)
    n_H2_wgs_est = n_H2_est + dn_CO
    fs.extra_bounds["psa.feed_in.F_H2"]  = (max(n_H2_wgs_est * 0.05, 1e-6), n_H2_wgs_est * 20.0)
    fs.extra_bounds["psa.feed_in.F_CO"]  = (max(n_CO_est * (1 - X_CO_est) * 0.05, 1e-6), n_CO_est * 20.0)
    fs.extra_bounds["psa.feed_in.F_CO2"] = (max((n_CO2_est + dn_CO) * 0.05, 1e-6),
                                              (n_CO2_est + dn_CO) * 20.0)
    fs.extra_bounds["psa.feed_in.F_H2O"] = (max((n_H2O_est - dn_CO) * 0.05, 1e-6), n_H2O_est * 20.0)
    fs.extra_bounds["psa.feed_in.F_CH4"] = (max(n_CH4_est * 0.05, 1e-6), n_CH4_est * 20.0)
    fs.extra_bounds["psa.feed_in.F_N2"]  = (max(n_N2_est * 0.05, 1e-9), n_N2_est * 20.0)

    # Tighter X_CO bound: physically meaningful WGS conversion range
    fs.extra_bounds["wgs.X_CO"] = (0.5, 0.95)

    # Seed heuristic initial point — avoids catastrophic midpoint-of-bounds start
    fs.initial_x0 = dict(_vars_est)
    fs.initial_x0["wgs.X_CO"] = 0.75
    for k, v in _vars_est.items():
        wk = k.replace("gasifier.syngas_out.", "wgs.syngas_in.")
        if wk not in fs.initial_x0:
            fs.initial_x0[wk] = v

    fs.objective_kpi = "LCOH"

    return fs


def _load_dacu_power_to_methane(p: dict):
    from pse_ecosystem.models.dac.tvsa_contactor import TVSAContactor
    from pse_ecosystem.models.dac.electrolyser_hf import ElectrolyserHF
    from pse_ecosystem.models.dac.methanation_reactor import MethanationReactor
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet

    F_air   = float(p.get("F_air_mol_s", 10_000.0))
    eta_cap = float(p.get("eta_cap", 0.85))
    eta_elec = float(p.get("eta_elec", 0.70))
    T_rx    = float(p.get("T_rx_K", 673.0))

    tvsa   = TVSAContactor("tvsa",    eta_cap=eta_cap)
    elec   = ElectrolyserHF("elec",   eta_elec=eta_elec)
    meth   = MethanationReactor("meth", T_rx_K_default=T_rx)

    fs = BaseFlowsheet(name="dac.power_to_methane", units=[tvsa, elec, meth])

    # Wire CO2 and H2 streams to methanation reactor
    fs.connect(tvsa.co2_out_port, meth.co2_in_port,  description="Captured CO2 → reactor")
    fs.connect(elec.h2_out_port,  meth.h2_in_port,   description="Green H2 → reactor")

    # Fix air feed flow (design basis)
    fs.extra_bounds["tvsa.air_in.F_Air"] = (F_air, F_air)
    fs.extra_bounds["tvsa.air_in.T"]     = (288.15, 288.15)   # 15°C ambient
    fs.extra_bounds["tvsa.air_in.P"]     = (101.325, 101.325) # kPa

    # H2:CO2 stoichiometry (4:1 molar) — enforced via extra_equality
    # F_H2_elec = 4 × F_CO2_tvsa  →  F_H2 - 4*F_CO2 = 0
    fs.extra_equalities.append(
        ({"elec.h2_out.F_H2": 1.0, "tvsa.co2_out.F_CO2": -4.0}, 0.0)
    )

    # Fix reactor temperature (user-adjustable via sensitivity sweep)
    fs.extra_bounds["meth.T_rx_K"] = (T_rx, T_rx)

    # Physics-informed bounds to give SLP a well-scaled warm-start
    cap_rate = eta_cap * 415e-6 * F_air  # mol/s CO2 captured
    h2_rate  = 4.0 * cap_rate

    # TVSA flow bounds
    fs.extra_bounds["tvsa.co2_out.F_CO2"]          = (cap_rate * 0.5, cap_rate * 2.0)
    fs.extra_bounds["tvsa.depleted_air_out.F_Air"] = (F_air * 0.99, F_air * 1.01)

    # TVSA energy bounds (physics-derived to avoid 50,000-kW midpoints)
    import math as _math
    _k_fan   = 0.029 * 200.0 / (1.225 * 0.75 * 1000.0)
    _k_regen = 70.0
    _k_vac   = 8.314e-3 * 393.0 * _math.log(101.325 / 5.0) / 0.70
    fs.extra_bounds["tvsa.W_fan_kW"]   = (0.0, _k_fan   * F_air    * 2.0 + 10.0)
    fs.extra_bounds["tvsa.Q_regen_kW"] = (0.0, _k_regen * cap_rate * 2.0 + 10.0)
    fs.extra_bounds["tvsa.W_vac_kW"]   = (0.0, _k_vac   * cap_rate * 2.0 + 10.0)

    # Electrolyser bounds (physics-derived)
    _k_elec = 285.8 / eta_elec
    fs.extra_bounds["elec.h2_out.F_H2"]    = (h2_rate * 0.5, h2_rate * 2.0)
    fs.extra_bounds["elec.water_in.F_H2O"] = (h2_rate * 0.5, h2_rate * 2.0)
    fs.extra_bounds["elec.o2_out.F_O2"]    = (h2_rate * 0.25, h2_rate * 1.0)
    fs.extra_bounds["elec.W_elec_kW"]      = (0.0, _k_elec * h2_rate * 2.0 + 10.0)

    # Methanation bounds — set co2_in and h2_in tight so the bilinear
    # X*F_CO2 Jacobian term is evaluated near the true feasible point
    # (default [0,1e4] gives midpoint=5000, 2800× off from 1.764 → LP infeasible)
    fs.extra_bounds["meth.co2_in.F_CO2"]      = (cap_rate * 0.5, cap_rate * 2.0)
    fs.extra_bounds["meth.h2_in.F_H2"]        = (h2_rate  * 0.5, h2_rate  * 2.0)
    fs.extra_bounds["meth.product_out.F_CH4"] = (0.0, cap_rate * 1.5)
    fs.extra_bounds["meth.product_out.F_H2O"] = (0.0, 2.0 * cap_rate * 1.5)
    fs.extra_bounds["meth.X_CO2"]             = (0.01, 0.9999)

    fs.objective_kpi = "CH4_production_mol_s"
    return fs


def _load_grand_challenge_gasification(p: dict):
    """10-unit Biomass → Green H2 Grand Challenge flowsheet.

    Chain: Storage → Gasifier → Cyclone → HTS-WGS → LTS-WGS →
           Moisture Sep → CO2 Scrubber → PSA → Compressor → H2 Polisher
    """
    from pse_ecosystem.models.biomass.biomass_database import get_biomass, element_feeds_mol_s
    from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
    from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
    from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
    from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
    from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
    from pse_ecosystem.models.pressure_changers.compressor import Compressor, CompressorParams
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection

    def _link_flows(port_a, port_b, desc=""):
        """Append flow-variable connections without T/P — handles T/P count mismatches."""
        a_flows = [v for v in port_a.variable_names() if ".F_" in v]
        b_flows = [v for v in port_b.variable_names() if ".F_" in v]
        for va, vb in zip(a_flows, b_flows):
            fs.connections.append(Connection(var_a=va, var_b=vb, description=desc))

    _SYNGAS = ["H2", "CO", "CO2", "H2O", "CH4", "N2"]

    biomass_type    = str(p.get("biomass_type", "Pine Wood"))
    agent           = str(p.get("gasifying_agent", "Steam"))
    feed_wet_kg_s   = float(p.get("biomass_feed_kg_s", 1.0))
    sb_ratio        = float(p.get("steam_to_biomass_ratio", 1.0))
    T_gas_C         = float(p.get("T_gasifier_C", 800.0))
    T_hts_C         = float(p.get("T_hts_C", 400.0))
    T_lts_C         = float(p.get("T_lts_C", 220.0))
    H2_recovery     = float(p.get("H2_recovery", 0.94))
    P_out_Pa        = float(p.get("P_out_Pa", 5_000_000.0))

    b = get_biomass(biomass_type)
    MC = b["MC"]
    feed_dry_kg_s = feed_wet_kg_s * (1.0 - MC)

    # ── Unit 1: Biomass Storage (drying) ─────────────────────────────────────
    storage = BiomassStorageHF("storage", biomass_type=biomass_type)

    # ── Unit 2: Gasifier ─────────────────────────────────────────────────────
    gasifier = BiomassGasifierHF("gasifier", biomass_type=biomass_type,
                                  T_gasifier_C=T_gas_C, gasifying_agent=agent)

    # ── Unit 3: Cyclone — char/ash removal (99% efficiency) ──────────────────
    # Outlet 0 = clean syngas, Outlet 1 = char/ash (not tracked further)
    _char_sf = [[0.99, 0.01]] * len(_SYNGAS)   # all syngas species through outlet_0
    cyclone = SeparatorHF("cyclone", _SYNGAS,
                           SeparatorHFParams(n_outlets=2, split_fractions=_char_sf))

    # ── Unit 4: High-Temperature WGS Reactor (HTS) ───────────────────────────
    hts = WGSReactorHF("hts", T_wgs_C=T_hts_C)

    # ── Unit 5: Low-Temperature WGS Reactor (LTS) ────────────────────────────
    lts = WGSReactorHF("lts", T_wgs_C=T_lts_C)

    # ── Unit 6: Moisture Separator (condensate knockout) ─────────────────────
    # H2O: 30% to gas (outlet_0), 70% to condensate (outlet_1)
    # Other species: 99% to gas, 1% to condensate
    _mois_sf = []
    for c in _SYNGAS:
        _mois_sf.append([0.30, 0.70] if c == "H2O" else [0.99, 0.01])
    moisture_sep = SeparatorHF("moisture_sep", _SYNGAS,
                                SeparatorHFParams(n_outlets=2, split_fractions=_mois_sf))

    # ── Unit 7: CO2 Scrubber (amine absorption simplified) ───────────────────
    # CO2: 3% escapes to gas (outlet_0), 97% absorbed (outlet_1)
    # H2O: 20% to gas, 80% to absorber sump
    # Other species (H2, CO, CH4, N2): 97% to gas, 3% dissolved/lost
    _co2_sf = []
    for c in _SYNGAS:
        if c == "CO2":
            _co2_sf.append([0.03, 0.97])
        elif c == "H2O":
            _co2_sf.append([0.20, 0.80])
        else:
            _co2_sf.append([0.97, 0.03])
    co2_scrubber = SeparatorHF("co2_scrubber", _SYNGAS,
                                SeparatorHFParams(n_outlets=2, split_fractions=_co2_sf))

    # ── Unit 8: PSA Separator ─────────────────────────────────────────────────
    psa = H2SeparatorPSA("psa", H2_recovery=H2_recovery)

    # ── Unit 9: H2 Compressor ─────────────────────────────────────────────────
    cp = CompressorParams(eta_isentropic=0.78, P_out_Pa=P_out_Pa)
    h2_comp = Compressor("h2_comp", ["H2"], cp)

    # ── Unit 10: H2 Polisher (final trace-impurity removal) ──────────────────
    _pol_sf = [[0.995, 0.005]]   # 99.5% product, 0.5% purge
    h2_polisher = SeparatorHF("h2_polisher", ["H2"],
                               SeparatorHFParams(n_outlets=2, split_fractions=_pol_sf))

    fs = BaseFlowsheet(
        name="industrial.grand_challenge_10unit",
        units=[storage, gasifier, cyclone, hts, lts,
               moisture_sep, co2_scrubber, psa, h2_comp, h2_polisher],
    )

    # ── Port connections ──────────────────────────────────────────────────────
    # Exact-match pairs use fs.connect(); T/P-mismatched pairs use _link_flows().
    fs.connect(storage.dry_out_port, gasifier.biomass_in_port,
               description="Dry biomass → gasifier")                        # 1:1 no T/P
    _link_flows(gasifier.syngas_out_port, cyclone.inlet_port,
                desc="Raw syngas → cyclone")                                 # 6 vs 8 vars
    _link_flows(cyclone.outlet_ports[0], hts.syngas_in_port,
                desc="Clean syngas → HTS")                                  # 8 vs 6 vars
    fs.connect(hts.shifted_out_port, lts.syngas_in_port,
               description="HTS shifted gas → LTS")                         # 6:6 no T/P
    _link_flows(lts.shifted_out_port, moisture_sep.inlet_port,
                desc="LTS shifted gas → moisture sep")                       # 6 vs 8 vars
    fs.connect(moisture_sep.outlet_ports[0], co2_scrubber.inlet_port,
               description="Dry gas → CO2 scrubber")                        # 8:8 with T/P
    _link_flows(co2_scrubber.outlet_ports[0], psa.feed_in_port,
                desc="H2-rich gas → PSA")                                   # 8 vs 6 vars
    _link_flows(psa.h2_out_port, h2_comp.inlet_port,
                desc="Pure H2 → compressor")                                # 1 vs 3 vars
    fs.connect(h2_comp.outlet_port, h2_polisher.inlet_port,
               description="Compressed H2 → polisher")                      # 3:3 with T/P

    # ── Design-basis fixed feeds ──────────────────────────────────────────────
    fs.extra_bounds["storage.wet_in.F_Biomass"] = (feed_wet_kg_s, feed_wet_kg_s)
    n_steam = feed_dry_kg_s * sb_ratio * 1000.0 / 18.015
    fs.extra_bounds["gasifier.agent_in.F_H2O"]  = (n_steam, n_steam)

    # ── Warm-start bounds (gasifier estimates) ────────────────────────────────
    feeds = element_feeds_mol_s(biomass_type, feed_dry_kg_s)
    n_C = feeds["C"]
    n_H = feeds["H"] + 2.0 * n_steam
    n_O = feeds["O"] + n_steam
    n_CO_est  = max(0.60 * n_C, 0.01)
    n_CO2_est = max(0.30 * n_C, 0.01)
    n_CH4_est = max(0.10 * n_C, 0.01)
    n_H2O_est = max(0.10 * n_O, 0.01)
    n_H2_est  = max((n_H - 2.0 * n_H2O_est - 4.0 * n_CH4_est) / 2.0, 0.01)
    n_N2_est  = max(feeds["N"] / 2.0, 0.001)

    def _bnd(est, lo_f=0.4, hi_f=4.0):
        lo = max(est * lo_f, 1e-6)
        return (lo, max(est * hi_f, lo + 0.1))

    for c, est in zip(_SYNGAS, [n_H2_est, n_CO_est, n_CO2_est, n_H2O_est, n_CH4_est, n_N2_est]):
        fs.extra_bounds[f"gasifier.syngas_out.F_{c}"] = _bnd(est)
        fs.extra_bounds[f"cyclone.inlet.F_{c}"]       = _bnd(est)
        fs.extra_bounds[f"cyclone.outlet_0.F_{c}"]    = _bnd(est, 0.3, 3.0)

    # HTS warm-start (75% CO conversion)
    X_hts = 0.75
    dn_hts = n_CO_est * X_hts
    n_H2_hts  = n_H2_est + dn_hts
    n_CO_hts  = n_CO_est * (1.0 - X_hts)
    n_CO2_hts = n_CO2_est + dn_hts
    n_H2O_hts = max(n_H2O_est - dn_hts, 0.001)
    for uid in ("hts",):
        for c, est in zip(_SYNGAS,
                          [n_H2_est, n_CO_est, n_CO2_est, n_H2O_est, n_CH4_est, n_N2_est]):
            fs.extra_bounds[f"{uid}.syngas_in.F_{c}"] = _bnd(est, 0.3, 5.0)
        for c, est in zip(_SYNGAS,
                          [n_H2_hts, n_CO_hts, n_CO2_hts, n_H2O_hts, n_CH4_est, n_N2_est]):
            fs.extra_bounds[f"{uid}.shifted_out.F_{c}"] = _bnd(est, 0.3, 5.0)

    # LTS warm-start (90% additional CO conversion)
    X_lts = 0.90
    dn_lts = n_CO_hts * X_lts
    n_H2_lts  = n_H2_hts + dn_lts
    n_CO_lts  = n_CO_hts * (1.0 - X_lts)
    n_CO2_lts = n_CO2_hts + dn_lts
    n_H2O_lts = max(n_H2O_hts - dn_lts, 0.001)
    for uid in ("lts",):
        for c, est in zip(_SYNGAS,
                          [n_H2_hts, n_CO_hts, n_CO2_hts, n_H2O_hts, n_CH4_est, n_N2_est]):
            fs.extra_bounds[f"{uid}.syngas_in.F_{c}"] = _bnd(est, 0.3, 5.0)
        for c, est in zip(_SYNGAS,
                          [n_H2_lts, n_CO_lts, n_CO2_lts, n_H2O_lts, n_CH4_est, n_N2_est]):
            fs.extra_bounds[f"{uid}.shifted_out.F_{c}"] = _bnd(est, 0.3, 5.0)

    # Moisture separator warm-start
    for c, est in zip(_SYNGAS,
                      [n_H2_lts, n_CO_lts, n_CO2_lts, n_H2O_lts, n_CH4_est, n_N2_est]):
        fs.extra_bounds[f"moisture_sep.inlet.F_{c}"]    = _bnd(est, 0.3, 5.0)
        sf0 = 0.30 if c == "H2O" else 0.99
        fs.extra_bounds[f"moisture_sep.outlet_0.F_{c}"] = _bnd(est * sf0, 0.3, 5.0)

    # CO2 scrubber warm-start
    n_CO2_in_scrub = n_CO2_lts
    for c, est in zip(_SYNGAS,
                      [n_H2_lts, n_CO_lts, n_CO2_lts, n_H2O_lts * 0.99, n_CH4_est, n_N2_est]):
        sf0 = 0.03 if c == "CO2" else (0.20 if c == "H2O" else 0.97)
        fs.extra_bounds[f"co2_scrubber.inlet.F_{c}"]    = _bnd(est, 0.3, 5.0)
        fs.extra_bounds[f"co2_scrubber.outlet_0.F_{c}"] = _bnd(est * sf0, 0.2, 6.0)

    # PSA warm-start
    n_H2_psa_in = n_H2_lts * 0.97
    for c, est in zip(_SYNGAS,
                      [n_H2_psa_in, n_CO_lts * 0.97, n_CO2_lts * 0.03,
                       n_H2O_lts * 0.99 * 0.20, n_CH4_est * 0.97, n_N2_est * 0.97]):
        fs.extra_bounds[f"psa.feed_in.F_{c}"] = _bnd(est, 0.2, 6.0)
    n_H2_prod = n_H2_psa_in * H2_recovery
    fs.extra_bounds["psa.h2_out.F_H2"] = _bnd(n_H2_prod, 0.3, 3.0)

    # Compressor and polisher warm-start (flow variables)
    fs.extra_bounds["h2_comp.inlet.F_H2"]        = _bnd(n_H2_prod, 0.3, 3.0)
    fs.extra_bounds["h2_comp.outlet.F_H2"]       = _bnd(n_H2_prod, 0.3, 3.0)
    fs.extra_bounds["h2_polisher.inlet.F_H2"]    = _bnd(n_H2_prod, 0.3, 3.0)
    fs.extra_bounds["h2_polisher.outlet_0.F_H2"] = _bnd(n_H2_prod * 0.995, 0.3, 3.0)

    # ── Temperature and pressure bounds for intermediate streams ──────────────
    # The WGS and biomass units track no T/P, leaving T/P of the SeparatorHF
    # units unconstrained.  Without bounds the LP can drive T to extreme values,
    # which inflates Compressor work and causes LP infeasibility.
    T_gas_K  = T_gas_C  + 273.15   # gasifier outlet ≈ 1073 K
    T_hts_K  = T_hts_C  + 273.15   # HTS ≈ 673 K
    T_lts_K  = T_lts_C  + 273.15   # LTS ≈ 493 K
    T_amb_K  = 298.15               # near-ambient compression
    P_lo, P_hi = 80_000.0, 600_000.0   # 0.8–6 bar (syngas train)

    for tag in ("inlet", "outlet_0", "outlet_1"):
        fs.extra_bounds[f"cyclone.{tag}.T"]      = (T_gas_K * 0.5,  T_gas_K * 1.2)
        fs.extra_bounds[f"cyclone.{tag}.P"]      = (P_lo, P_hi)
        fs.extra_bounds[f"moisture_sep.{tag}.T"] = (T_lts_K * 0.5,  T_hts_K * 1.2)
        fs.extra_bounds[f"moisture_sep.{tag}.P"] = (P_lo, P_hi)
        fs.extra_bounds[f"co2_scrubber.{tag}.T"] = (T_amb_K * 0.8,  T_lts_K * 1.2)
        fs.extra_bounds[f"co2_scrubber.{tag}.P"] = (P_lo, P_hi)

    # Compressor (H2 inlet near-ambient; outlet at target pressure)
    fs.extra_bounds["h2_comp.inlet.T"]        = (T_amb_K * 0.8, T_amb_K * 1.5)
    fs.extra_bounds["h2_comp.inlet.P"]        = (P_lo, P_hi)
    fs.extra_bounds["h2_comp.outlet.T"]       = (T_amb_K,       T_amb_K * 5.0)
    fs.extra_bounds["h2_comp.outlet.P"]       = (P_out_Pa * 0.5, P_out_Pa * 1.5)

    # H2 polisher (post-compression)
    for tag in ("inlet", "outlet_0", "outlet_1"):
        fs.extra_bounds[f"h2_polisher.{tag}.T"] = (T_amb_K, T_amb_K * 5.0)
        fs.extra_bounds[f"h2_polisher.{tag}.P"] = (P_out_Pa * 0.5, P_out_Pa * 1.5)

    fs.objective_kpi = "H2_production_kg_h"
    return fs


# ── Loader dispatch maps ──────────────────────────────────────────────────────

_LOADER_MAP: Dict[str, Callable] = {
    "hydrogen.electrolysis_only":              _load_electrolysis_only,
    "hydrogen.electrolysis_or_gasification":   _load_electrolysis_or_gasification_flowsheet,
    "industrial.green_hydrogen":               _load_green_hydrogen,
    "industrial.power_to_methanol":            _load_power_to_methanol,
    "industrial.gasification_to_power":        _load_gasification_to_power,
    "industrial.syngas_production":            _load_syngas_production,
    "custom.user_flowsheet":                   _load_custom_user_flowsheet,
    "small.cstr_flash":                        _load_cstr_flash,
    "small.compression_train":                 _load_compression_train,
    "small.mixer_settler":                     _load_mixer_settler,
    "small.distillation":                      _load_distillation,
    "biomass.gasification_to_hydrogen":        _load_biomass_gasification_to_h2,
    "industrial.grand_challenge_10unit":       _load_grand_challenge_gasification,
    "dac.power_to_methane":                    _load_dacu_power_to_methane,
}

_MILP_LOADER_MAP: Dict[str, Callable] = {
    "hydrogen.electrolysis_or_gasification":   _load_electrolysis_or_gasification_milp,
}


# v1.4.0 audit N35 — at module-load time assert that every entry in
# _REGISTRY (except the special "custom.user_flowsheet" key which is
# handled via build_custom_flowsheet rather than a loader) has a matching
# entry in either _LOADER_MAP or _MILP_LOADER_MAP. A typo or omission
# would otherwise surface only when the user picks the broken template.
def _validate_registry_loader_sync() -> None:
    _all_loaders = set(_LOADER_MAP) | set(_MILP_LOADER_MAP)
    _CUSTOM_KEYS = {"custom.user_flowsheet"}
    missing = [
        spec.key for spec in _REGISTRY
        if spec.key not in _all_loaders and spec.key not in _CUSTOM_KEYS
    ]
    if missing:
        raise RuntimeError(
            f"flowsheet_service: _REGISTRY entries without a loader: {missing}. "
            f"Add a corresponding entry to _LOADER_MAP or _MILP_LOADER_MAP."
        )
    # Reverse direction: loaders without registry entries are dead code.
    _registry_keys = {spec.key for spec in _REGISTRY}
    orphan = [k for k in _all_loaders if k not in _registry_keys]
    if orphan:
        import warnings as _w
        _w.warn(
            f"flowsheet_service: loaders without _REGISTRY entries (dead "
            f"code, not user-reachable): {orphan}",
            RuntimeWarning,
            stacklevel=2,
        )


_validate_registry_loader_sync()


# ── Post-solve safety margins ─────────────────────────────────────────────────

# Units considered pressure vessels for ASME sizing (by Python class name).
# Extend this set when adding new vessel-type units to Layer 3.
_ASME_VESSEL_UNIT_TYPES: frozenset = frozenset({
    "Compressor",
    "FlashVLHF",
    "CSTRHF",
    "EquilibriumReactor",
    "GibbsReactor",
    "BiomassGasifierHF",
})

# ASME minimum wall thickness below which a WARNING is raised [m]
_ASME_WARNING_THICKNESS_M: float = 0.003  # 3 mm practical minimum

# Pressure margin fraction below which a WARNING is raised
_PRESSURE_WARNING_MARGIN: float = 0.05  # 5 % of design pressure

# Flammability margin below which a WARNING is raised [vol%]
_FLAMM_WARNING_MARGIN_VOL_PCT: float = 2.0


def _extract_vessel_radius(unit) -> Tuple[float, str]:
    """Four-tier cascade for inner vessel radius [m].

    Returns (radius_m, source_label) where source_label is one of
    "params", "volume_derived", or "default".
    """
    import math as _math

    # Tier 1: explicit vessel_radius_m attribute on params dataclass
    params = getattr(unit, "params", None)
    if params is not None:
        r = getattr(params, "vessel_radius_m", None)
        if r is not None and r > 0.0:
            return float(r), "params"

    # Tier 2: explicit instance attribute
    r = getattr(unit, "vessel_radius_m", None)
    if r is not None and r > 0.0:
        return float(r), "params"

    # Tier 3: derive from volume_m3 (cylindrical vessel, L/D = 4)
    volume_m3 = None
    if params is not None:
        volume_m3 = getattr(params, "volume_m3", None)
    if volume_m3 is None:
        volume_m3 = getattr(unit, "volume_m3", None)
    if volume_m3 is not None and volume_m3 > 0.0:
        # V = π r² L with L/D = 4 → L = 8r → V = 8π r³ → r = (V / (8π))^(1/3)
        r = (float(volume_m3) / (8.0 * _math.pi)) ** (1.0 / 3.0)
        return r, "volume_derived"

    # Tier 4: conservative default
    return 0.5, "default"


def compute_safety_margins(
    flowsheet,
    solution_x: Dict[str, float],
    design_pressure_factor: float = 1.1,
    allowable_stress_Pa: float = 138_000_000.0,
    joint_efficiency: float = 1.0,
) -> List[SafetyMarginRow]:
    """Compute ASME and flammability safety margins for pressure-containing units.

    POST-SOLVE ONLY.  This function must never be called during LP/NLP
    optimisation.  It is called by the UI after a ``SolveResult`` is returned.

    Parameters
    ----------
    flowsheet :
        Assembled ``BaseFlowsheet`` (same object passed to the Orchestrator).
    solution_x :
        ``SolveResult.x`` — the converged solution dict.
    design_pressure_factor :
        P_design = P_operating × factor (default 1.1 = 10 % engineering margin).
    allowable_stress_Pa :
        ASME allowable stress for shell material [Pa].
    joint_efficiency :
        ASME weld joint efficiency [-].

    Returns
    -------
    List[SafetyMarginRow]
        One or more rows per pressure-containing unit; empty list if none match.

    Layer boundary
    --------------
    Imports ``safety_checks`` from ``models/safety/`` (Layer 3 → Layer 1 bridge,
    permitted only from this module per the single-gateway rule).
    """
    from pse_ecosystem.models.safety.safety_checks import (
        asme_minimum_wall_thickness,
        flammability_margins,
        operating_pressure_margin,
    )

    rows: List[SafetyMarginRow] = []

    for unit in flowsheet.units:
        unit_type = type(unit).__name__
        uid = unit.unit_id

        if unit_type not in _ASME_VESSEL_UNIT_TYPES:
            continue

        # ── Extract operating pressure ────────────────────────────────────────
        # Try outlet pressure first (post-compression), then inlet, then fallback.
        P_operating: Optional[float] = None
        for p_key in (f"{uid}.outlet.P", f"{uid}.inlet.P"):
            val = solution_x.get(p_key)
            if val is not None and val > 0.0:
                P_operating = float(val)
                break

        if P_operating is None:
            # Search solution_x for any pressure variable belonging to this unit
            p_vals = [
                v for k, v in solution_x.items()
                if k.startswith(uid + ".") and k.endswith(".P") and v > 0.0
            ]
            P_operating = max(p_vals) if p_vals else None

        if P_operating is None:
            continue  # no pressure variable found; skip unit

        P_design = P_operating * design_pressure_factor

        # ── ASME wall thickness ───────────────────────────────────────────────
        radius_m, radius_source = _extract_vessel_radius(unit)
        try:
            t_min = asme_minimum_wall_thickness(
                P_operating, radius_m, allowable_stress_Pa, joint_efficiency
            )
            if t_min < _ASME_WARNING_THICKNESS_M:
                status = "WARNING"
            else:
                status = "OK"
            rows.append(SafetyMarginRow(
                unit_id=uid,
                unit_type=unit_type,
                check_type="ASME_wall_thickness",
                value=t_min,
                limit=_ASME_WARNING_THICKNESS_M,
                status=status,
                detail=(
                    f"t_min = {t_min*1000:.2f} mm at P = {P_operating/1e5:.1f} bar, "
                    f"R = {radius_m*1000:.0f} mm ({radius_source})"
                ),
                radius_source=radius_source,
            ))
        except ValueError:
            rows.append(SafetyMarginRow(
                unit_id=uid,
                unit_type=unit_type,
                check_type="ASME_wall_thickness",
                value=float("nan"),
                limit=_ASME_WARNING_THICKNESS_M,
                status="VIOLATION",
                detail=f"ASME UG-27(c)(1) not applicable: P = {P_operating/1e5:.1f} bar "
                       f"exceeds formula validity (P/(S·E) ≥ 0.385). Use Div. 2 rules.",
                radius_source=radius_source,
            ))

        # ── Operating pressure margin ─────────────────────────────────────────
        try:
            margin = operating_pressure_margin(P_operating, P_design)
            # By construction P_design = P_operating * factor, so margin = 1 - 1/factor
            # This will always be (factor - 1)/factor ≈ 0.091 for factor=1.1.
            # The check is meaningful when the user supplies a custom P_design_Pa override.
            if margin < _PRESSURE_WARNING_MARGIN:
                p_status = "WARNING"
            elif margin < 0.0:
                p_status = "VIOLATION"
            else:
                p_status = "OK"
            rows.append(SafetyMarginRow(
                unit_id=uid,
                unit_type=unit_type,
                check_type="pressure_margin",
                value=margin,
                limit=_PRESSURE_WARNING_MARGIN,
                status=p_status,
                detail=(
                    f"P_op = {P_operating/1e5:.2f} bar, "
                    f"P_design = {P_design/1e5:.2f} bar, "
                    f"margin = {margin*100:.1f} %"
                ),
            ))
        except ValueError:
            pass

        # ── Flammability check ────────────────────────────────────────────────
        components = getattr(unit, "components", None) or getattr(
            getattr(unit, "params", None), "components", None
        )
        if not components:
            continue

        # Build a rough composition dict from outlet molar flows
        flow_vars = {
            sp: solution_x.get(f"{uid}.outlet.F_{sp}", 0.0)
            for sp in components
        }
        total_flow = sum(flow_vars.values())
        if total_flow <= 0.0:
            # Try inlet
            flow_vars = {
                sp: solution_x.get(f"{uid}.inlet.F_{sp}", 0.0)
                for sp in components
            }
            total_flow = sum(flow_vars.values())

        if total_flow <= 0.0:
            continue

        comp_fracs = {sp: f / total_flow for sp, f in flow_vars.items()}

        try:
            fm = flammability_margins(comp_fracs)
        except ValueError:
            continue  # no flammable species in this unit's component set

        margin_to_lfl = fm["margin_to_LFL_vol_pct"]
        if margin_to_lfl < 0.0:
            f_status = "VIOLATION"
        elif margin_to_lfl < _FLAMM_WARNING_MARGIN_VOL_PCT:
            f_status = "WARNING"
        else:
            f_status = "OK"

        rows.append(SafetyMarginRow(
            unit_id=uid,
            unit_type=unit_type,
            check_type="flammability",
            value=margin_to_lfl,
            limit=_FLAMM_WARNING_MARGIN_VOL_PCT,
            status=f_status,
            detail=(
                f"LFL_mix = {fm['LFL_vol_pct']:.1f} vol%, "
                f"UFL_mix = {fm['UFL_vol_pct']:.1f} vol%, "
                f"flammable content = {fm['mixture_flammable_fraction']*100:.1f} vol% "
                f"({', '.join(fm['flammable_species'])})"
            ),
        ))

    return rows


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
