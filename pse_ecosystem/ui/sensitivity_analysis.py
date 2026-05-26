"""Tornado sensitivity + break-even / NPV-with-revenue helpers.

v1.6.1 P.9: extracted from ``flowsheet_service.py``. Re-exported from
the facade for back-compat.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pse_ecosystem.ui.economics_bridge import (
    _aggregate_capex_purchase_USD,
    _aggregate_opex_annual_USD,
    _extract_h2_kg_per_s,
    compute_project_economics,
)
from pse_ecosystem.ui.flowsheet_service import ProjectEconomicsConfig


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
