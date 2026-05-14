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
    # Reactors
    "StoichiometricReactor": "Stoichiometric reactor — linear (exact analytical J)",
    "MethanationReactor":    "Sabatier methanation — non-linear equilibrium, analytical J",
    # Separation / DAC
    "SeparatorHF":           "Separator — split fractions, linear",
    "TVSAContactor":         "TVSA DAC contactor — linear, analytical J (415 ppm CO2 feed)",
    # Heat Exchange
    "HeatExchangerNTU":      "Heat exchanger NTU — non-linear (counter-current)",
    # Power / CHP
    "ElectrolyserHF":        "PEM/AEL electrolyser — linear, port-based, analytical J",
    "CHPUnit":               "Combined Heat & Power — linear, analytical J (H2/CO/CH4 fuel)",
    # Separation / VLE
    "FlashVLHF":             "Rigorous V/L flash — Antoine K-values + Rachford-Rice (non-linear, terminal unit)",
    # Other
    "MixerHF":               "Multi-stream mixer — non-linear (energy balance)",
    "Compressor":            "Isentropic compressor — non-linear",
}

UNIT_CATEGORIES: Dict[str, List[str]] = {
    "Feed/Product":       ["PEMToy", "GasifierToy"],
    "Reactors":           ["StoichiometricReactor", "MethanationReactor"],
    "Separation/DAC":     ["SeparatorHF", "FlashVLHF", "TVSAContactor"],
    "Heat Exchange":      ["HeatExchangerNTU"],
    "Power/CHP":          ["ElectrolyserHF", "CHPUnit"],
    "Mixing":             ["MixerHF"],
    "Pressure Changers":  ["Compressor"],
}


# ── Internal template registry ────────────────────────────────────────────────

_REGISTRY: List[TemplateSpec] = [

    TemplateSpec(
        key="hydrogen.electrolysis_only",
        display_name="PEM Electrolysis",
        category="Hydrogen",
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
        category="Hydrogen",
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
        category="Industrial",
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
        category="Industrial",
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
        category="Industrial",
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
        category="Industrial",
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
        category="Small",
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
        category="Small",
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
        category="Small",
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
        category="Small",
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
        category="Hydrogen",
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
        key="dac.power_to_methane",
        display_name="Direct Air Capture → Methane (DAC-U)",
        category="Industrial",
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
        out_port = getattr(from_u, "outlet_port", None)
        in_port  = getattr(to_u,   "inlet_port",  None)
        if out_port is not None and in_port is not None:
            try:
                fs.connect(out_port, in_port,
                           description=f"{conn['from_unit']} → {conn['to_unit']}")
            except ValueError as exc:
                conn_warnings.append(
                    f"{conn['from_unit']} → {conn['to_unit']}: {exc}"
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
        hot  = params.get("hot_components",  ["H2", "CO"])
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
    "dac.power_to_methane":                    _load_dacu_power_to_methane,
}

_MILP_LOADER_MAP: Dict[str, Callable] = {
    "hydrogen.electrolysis_or_gasification":   _load_electrolysis_or_gasification_milp,
}
