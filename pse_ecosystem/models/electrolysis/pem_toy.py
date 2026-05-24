"""Toy PEM electrolyser — linear model.

Variables (prefixed with ``unit_id``)
    {id}.electricity_kW   — electrical input
    {id}.h2_kg_per_h      — hydrogen output

Residuals (equalities)
    h2 = eta * electricity        (single linear constraint)

The unit advertises ``is_linear=True`` so the SLP driver short-circuits to a
single LP iteration when every other unit in the flowsheet is also linear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


@dataclass
class PEMToyParams:
    eta_kg_per_kWh: float = 0.018       # ≈ 55 kWh/kg H2
    capacity_kW: float = 10_000.0
    electricity_price_per_kWh: float = 0.05   # GBP / kWh
    capex_annual_per_kW: float = 100.0        # GBP / kW / yr
    operating_hours_per_year: float = 8000.0
    grid_carbon_intensity_kg_CO2_per_kWh: float = 0.233  # UK grid avg 2023


class PEMToy(BaseUnit):
    """Linear toy PEM electrolyser."""

    is_linear = True
    category = UnitCategory.DIDACTIC

    def __init__(self, unit_id: str = "pem", params: PEMToyParams | None = None):
        self.unit_id = unit_id
        self.params = params or PEMToyParams()

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def v_electricity(self) -> str:
        return f"{self.unit_id}.electricity_kW"

    @property
    def v_h2(self) -> str:
        return f"{self.unit_id}.h2_kg_per_h"

    def variables(self) -> List[str]:
        return [self.v_electricity, self.v_h2]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        h2_max = self.params.eta_kg_per_kWh * self.params.capacity_kW
        return {
            self.v_electricity: (0.0, self.params.capacity_kW),
            self.v_h2: (0.0, h2_max),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        eta = self.params.eta_kg_per_kWh
        return np.array([x[self.v_h2] - eta * x[self.v_electricity]])

    # ── Cost contribution ─────────────────────────────────────────────────

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        hours = self.params.operating_hours_per_year
        return {
            self.v_electricity: self.params.electricity_price_per_kWh * hours,
        }

    # ── KPIs ──────────────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        h2 = x.get(self.v_h2, 0.0)
        electricity = x.get(self.v_electricity, 0.0)
        hours = self.params.operating_hours_per_year
        annual_h2 = h2 * hours
        annual_opex = electricity * self.params.electricity_price_per_kWh * hours
        annual_capex = self.params.capex_annual_per_kW * self.params.capacity_kW
        lcoh = (annual_capex + annual_opex) / annual_h2 if annual_h2 > 1e-9 else float("nan")
        annual_co2_kg = (
            self.params.grid_carbon_intensity_kg_CO2_per_kWh
            * electricity * hours
        )
        ci = annual_co2_kg / annual_h2 if annual_h2 > 1e-9 else float("nan")
        return {
            f"{self.unit_id}.annual_h2_kg": annual_h2,
            f"{self.unit_id}.annual_opex_GBP": annual_opex,
            f"{self.unit_id}.annual_capex_GBP": annual_capex,
            f"{self.unit_id}.LCOH_GBP_per_kg": lcoh,
            f"{self.unit_id}.CI_kg_CO2_per_kg_H2": ci,
            # v1.5.0.dev-AUDIT2 L3-2: canonical uid-prefixed H₂ production rates
            # so compute_project_economics can aggregate across multiple PEMs
            # without namespace collisions. v_h2 is in kg/h.
            f"{self.unit_id}.H2_production_kg_h": h2,
            f"{self.unit_id}.H2_production_kg_s": h2 / 3600.0,
        }

    # ── Analytical linearisation override ─────────────────────────────────

    # The model is linear, so the default finite-difference fallback would
    # already work — we override only to set ``is_exact=True`` cleanly without
    # any FD round-trip. ``is_linear=True`` is also picked up by BaseUnit.
    def linearize(self, guess):
        from pse_ecosystem.core.contracts import LinearizedModel

        variables = self.variables()
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)
        eta = self.params.eta_kg_per_kWh

        # Residual: h2 - eta * electricity
        # ∂/∂electricity = -eta
        # ∂/∂h2          = +1
        J = np.array([[-eta, 1.0]])
        f0 = np.array([x0_dict[self.v_h2] - eta * x0_dict[self.v_electricity]])

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=True,
        )
