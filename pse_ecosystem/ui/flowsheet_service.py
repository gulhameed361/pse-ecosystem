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


# ── Type-specific Unit ID suggestions ────────────────────────────────────────

def build_objective_extra(
    flowsheet: "BaseFlowsheet",
    mode: str,
    electricity_price_USD_per_kWh: float = 0.05,
    operating_hours: float = 8_000.0,
    crf: float = 0.10,
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
    """
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
    if mode in ("Minimize Energy", "Minimize TAC", "Minimize LCOH (Levelized Cost of H₂)"):
        for v in all_vars:
            lv = v.lower()
            if any(k in lv for k in ("w_shaft", "w_elec_kw", "electricity_kw")):
                obj[v] = obj.get(v, 0.0) + energy_coeff

    # ── Annualised CAPEX for linear-capex units ───────────────────────────────
    # ElectrolyserHF has strictly linear capex: 700 USD/kW.
    # Annualised = 700 × CRF per kW → inject on the W_elec_kW decision variable.
    # SSLW-correlated units (Compressor, HXN, vessels) have non-linear capex;
    # their costs are captured post-solve in kpis() and the Excel report.
    if mode in ("Minimize TAC", "Minimize LCOH (Levelized Cost of H₂)"):
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
    if mode in ("Maximize H₂ Yield", "Minimize LCOH (Levelized Cost of H₂)"):
        # Variable format: unit_id.port_tag.variable_name
        # Outlet port tags contain "out": syngas_out, shifted_out, h2_out, outlet, dry_out
        # Inlet port tags contain "in": syngas_in, feed_in, biomass_in, inlet, wet_in
        def _is_h2_outlet(v: str) -> bool:
            parts = v.split(".")
            if len(parts) < 3:
                return False
            return parts[-1].lower() == "f_h2" and "out" in parts[1].lower()

        h2_candidates = sorted(v for v in all_vars if _is_h2_outlet(v))
        if h2_candidates:
            obj[h2_candidates[-1]] = obj.get(h2_candidates[-1], 0.0) - 1.0

    return obj, False


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
    for v, est in _vars_est.items():
        lo = max(est * 0.4, 1e-6)
        hi = max(est * 4.0, lo + 0.1)
        fs.extra_bounds[v] = (lo, hi)

    # WGS inlet/outlet bounds — tight around stoichiometric estimate
    X_CO_est = 0.8
    fs.extra_bounds["wgs.syngas_in.F_H2"]  = (max(n_H2_est * 0.3, 1e-6), n_H2_est * 5.0)
    fs.extra_bounds["wgs.syngas_in.F_CO"]  = (max(n_CO_est * 0.3, 1e-6), n_CO_est * 5.0)
    fs.extra_bounds["wgs.syngas_in.F_CO2"] = (max(n_CO2_est * 0.3, 1e-6), n_CO2_est * 5.0)
    fs.extra_bounds["wgs.syngas_in.F_H2O"] = (max(n_H2O_est * 0.3, 1e-6), n_H2O_est * 5.0)
    fs.extra_bounds["wgs.syngas_in.F_CH4"] = (max(n_CH4_est * 0.3, 1e-6), n_CH4_est * 5.0)
    fs.extra_bounds["wgs.syngas_in.F_N2"]  = (max(n_N2_est * 0.1, 1e-9),  n_N2_est * 20.0)

    dn_CO = n_CO_est * X_CO_est
    fs.extra_bounds["wgs.shifted_out.F_H2"]  = (max((n_H2_est + dn_CO) * 0.3, 1e-6),
                                                  (n_H2_est + dn_CO) * 4.0)
    fs.extra_bounds["wgs.shifted_out.F_CO"]  = (max(n_CO_est * (1 - X_CO_est) * 0.3, 1e-6),
                                                  n_CO_est * 3.0)
    fs.extra_bounds["wgs.shifted_out.F_CO2"] = (max((n_CO2_est + dn_CO) * 0.3, 1e-6),
                                                  (n_CO2_est + dn_CO) * 4.0)
    fs.extra_bounds["wgs.shifted_out.F_H2O"] = (max((n_H2O_est - dn_CO) * 0.1, 1e-6),
                                                  n_H2O_est * 4.0)
    fs.extra_bounds["wgs.shifted_out.F_CH4"] = (max(n_CH4_est * 0.3, 1e-6), n_CH4_est * 4.0)
    fs.extra_bounds["wgs.shifted_out.F_N2"]  = (max(n_N2_est * 0.1, 1e-9), n_N2_est * 20.0)

    # PSA feed bounds (mirrors WGS shifted out)
    n_H2_wgs_est = n_H2_est + dn_CO
    fs.extra_bounds["psa.feed_in.F_H2"]  = (max(n_H2_wgs_est * 0.3, 1e-6), n_H2_wgs_est * 4.0)
    fs.extra_bounds["psa.feed_in.F_CO"]  = (max(n_CO_est * (1 - X_CO_est) * 0.3, 1e-6), n_CO_est * 3.0)
    fs.extra_bounds["psa.feed_in.F_CO2"] = (max((n_CO2_est + dn_CO) * 0.3, 1e-6),
                                              (n_CO2_est + dn_CO) * 4.0)
    fs.extra_bounds["psa.feed_in.F_H2O"] = (max((n_H2O_est - dn_CO) * 0.1, 1e-6), n_H2O_est * 4.0)
    fs.extra_bounds["psa.feed_in.F_CH4"] = (max(n_CH4_est * 0.3, 1e-6), n_CH4_est * 4.0)
    fs.extra_bounds["psa.feed_in.F_N2"]  = (max(n_N2_est * 0.1, 1e-9), n_N2_est * 20.0)

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
