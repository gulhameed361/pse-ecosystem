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


# ── Unit specs + display-unit conversion ──────────────────────────────────────
# v1.6.1 P.9: moved to ``pse_ecosystem.ui.unit_specs``. Re-exported here.

from pse_ecosystem.ui.unit_specs import (  # noqa: E402, F401
    ParamSpec,
    UNIT_PARAM_SPECS,
    _bounds_specs,
    _family_of,
    from_native,
    get_unit_bounds_specs,
    get_unit_main_specs,
    get_unit_param_specs,
    si_baseline_of,
    supported_display_units,
    to_native,
)


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


# ── Economics bridge ──────────────────────────────────────────────────────────
# v1.6.1 P.9 — topology + objective_extra + compute_project_economics +
# build_sankey_data moved to ``pse_ecosystem.ui.economics_bridge``.

from pse_ecosystem.ui.economics_bridge import (  # noqa: E402, F401
    _aggregate_capex_purchase_USD,
    _aggregate_opex_annual_USD,
    _extract_h2_kg_per_s,
    _extract_power_out_kW,
    _most_downstream_h2_outlet,
    _topological_unit_order,
    build_objective_extra,
    compute_project_economics,
)


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


# ── Sensitivity analysis + break-even ──────────────────────────────────────────
# v1.6.1 P.9: moved to ``pse_ecosystem.ui.sensitivity_analysis``.

from pse_ecosystem.ui.sensitivity_analysis import (  # noqa: E402, F401
    TornadoRow,
    _extract_econ_kpi,
    compute_npv_with_revenue,
    tornado_sensitivity,
)


# ── Investor Report ──────────────────────────────────────────────────────────
# v1.6.1 P.9: moved to ``pse_ecosystem.ui.investor_report``.

from pse_ecosystem.ui.investor_report import (  # noqa: E402, F401
    generate_investor_report,
)


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
