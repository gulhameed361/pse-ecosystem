"""Economics bridge — topology helpers + LP objective + project economics.

v1.6.1 P.9: extracted from ``flowsheet_service.py`` to drop the facade
under the < 700-line verification gate.  Public symbols re-exported by the
facade for back-compat: every existing import keeps working.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet

from pse_ecosystem.ui.flowsheet_service import (
    ProductionConfig,
    ProjectEconomicsConfig,
)


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
