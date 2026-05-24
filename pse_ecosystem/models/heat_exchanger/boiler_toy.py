"""Toy steam boiler — linear unit model.

A simplified boiler: fuel combustion produces thermal energy which generates
steam. Two linear constraints relate fuel, steam, and thermal output.

Variables
---------
{id}.F_fuel   fuel mass flowrate  [kg/s]
{id}.F_steam  steam mass flowrate [kg/s]
{id}.Q_out    thermal output      [W]

Residuals
---------
r0 = Q_out - eta * LHV * F_fuel        energy balance
r1 = Q_out - F_steam * h_steam         steam enthalpy balance

Both residuals are linear in the variables (eta, LHV, h_steam are parameters),
so is_linear = True and the SLP driver short-circuits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess
from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


@dataclass
class BoilerToyParams:
    eta: float = 0.85               # thermal efficiency [-]
    LHV: float = 50e6               # lower heating value [J/kg fuel]
    h_steam: float = 2.7e6          # steam specific enthalpy [J/kg steam]
    fuel_cost_per_kg: float = 0.02  # GBP/kg fuel
    operating_hours: float = 8000.0 # hours per year


class BoilerToy(BaseUnit):
    """Linear toy steam boiler with analytical Jacobian."""

    is_linear = True
    category = UnitCategory.DIDACTIC

    def __init__(self, unit_id: str = "boiler", params: BoilerToyParams | None = None):
        self.unit_id = unit_id
        self.params = params or BoilerToyParams()

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def v_fuel(self) -> str:
        return f"{self.unit_id}.F_fuel"

    @property
    def v_steam(self) -> str:
        return f"{self.unit_id}.F_steam"

    @property
    def v_Q(self) -> str:
        return f"{self.unit_id}.Q_out"

    def variables(self) -> List[str]:
        return [self.v_fuel, self.v_steam, self.v_Q]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self.v_fuel:  (0.0, 100.0),
            self.v_steam: (0.0, 5000.0),
            self.v_Q:     (0.0, 5e9),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        Q    = x.get(self.v_Q,    0.0)
        fuel  = x.get(self.v_fuel, 0.0)
        steam = x.get(self.v_steam, 0.0)
        return np.array([
            Q - p.eta * p.LHV * fuel,       # r0: energy balance
            Q - p.h_steam * steam,           # r1: steam enthalpy
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        p = self.params
        return {self.v_fuel: p.fuel_cost_per_kg * p.operating_hours}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        Q = x.get(self.v_Q, 0.0)
        return {
            f"{self.unit_id}.Q_MW": Q / 1e6,
            f"{self.unit_id}.fuel_efficiency_pct": self.params.eta * 100.0,
        }

    # ── Analytical linearisation ──────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        p = self.params
        variables = self.variables()
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)
        f0 = self.residual(x0_dict)

        # Column order: [F_fuel, F_steam, Q_out]
        J = np.array([
            [-p.eta * p.LHV,  0.0,         1.0],
            [0.0,             -p.h_steam,   1.0],
        ], dtype=float)

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
