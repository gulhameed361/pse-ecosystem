"""Toy gasifier — mildly non-linear model.

A deliberately simple non-linear model used to exercise the SLP loop in
Layer 2. The non-linearity is a quadratic yield curve: hydrogen yield per
unit feed decreases as throughput grows (a stand-in for off-design losses).

Variables
    {id}.feed_kg_per_h    — feedstock flow
    {id}.h2_kg_per_h      — hydrogen output
    {id}.steam_kg_per_h   — steam input

Residuals
    h2     - (a · feed - b · feed²)            = 0     (non-linear)
    steam  - (c · feed)                         = 0    (linear)

The unit ships an analytical Jacobian override so the SLP driver does not
have to fall back on finite differences. The default FD fallback in
:class:`BaseUnit` would still produce correct results — the override is
documentation-by-example for future surrogate authors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class GasifierToyParams:
    a: float = 0.10         # linear yield coefficient (kg H2 / kg feed)
    b: float = 1.0e-7       # quadratic loss coefficient
    c: float = 0.5          # steam-to-feed ratio
    feed_max_kg_per_h: float = 50_000.0
    feed_price_per_kg: float = 0.05
    steam_price_per_kg: float = 0.02
    operating_hours_per_year: float = 8000.0
    capex_annual_GBP: float = 5_000_000.0


class GasifierToy(BaseUnit):
    """Mildly non-linear toy gasifier with analytical Jacobian."""

    is_linear = False
    trust_region = 5_000.0  # kg/h — keep linearisations local

    def __init__(self, unit_id: str = "gasifier", params: GasifierToyParams | None = None):
        self.unit_id = unit_id
        self.params = params or GasifierToyParams()

    # ── Variables ─────────────────────────────────────────────────────────

    @property
    def v_feed(self) -> str:
        return f"{self.unit_id}.feed_kg_per_h"

    @property
    def v_h2(self) -> str:
        return f"{self.unit_id}.h2_kg_per_h"

    @property
    def v_steam(self) -> str:
        return f"{self.unit_id}.steam_kg_per_h"

    def variables(self) -> List[str]:
        return [self.v_feed, self.v_h2, self.v_steam]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        feed_max = self.params.feed_max_kg_per_h
        h2_max = self.params.a * feed_max
        steam_max = self.params.c * feed_max
        return {
            self.v_feed: (0.0, feed_max),
            self.v_h2: (0.0, h2_max),
            self.v_steam: (0.0, steam_max),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        a, b, c = self.params.a, self.params.b, self.params.c
        feed = x[self.v_feed]
        h2 = x[self.v_h2]
        steam = x[self.v_steam]
        return np.array([
            h2 - (a * feed - b * feed * feed),
            steam - c * feed,
        ])

    # ── Cost contribution ─────────────────────────────────────────────────

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        hours = self.params.operating_hours_per_year
        return {
            self.v_feed: self.params.feed_price_per_kg * hours,
            self.v_steam: self.params.steam_price_per_kg * hours,
        }

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        hours = self.params.operating_hours_per_year
        h2 = x.get(self.v_h2, 0.0)
        feed = x.get(self.v_feed, 0.0)
        steam = x.get(self.v_steam, 0.0)
        annual_h2 = h2 * hours
        annual_feed_cost = feed * self.params.feed_price_per_kg * hours
        annual_steam_cost = steam * self.params.steam_price_per_kg * hours
        annual_opex = annual_feed_cost + annual_steam_cost
        annual_capex = self.params.capex_annual_GBP
        lcoh = (annual_capex + annual_opex) / annual_h2 if annual_h2 > 1e-9 else float("nan")
        return {
            f"{self.unit_id}.annual_h2_kg": annual_h2,
            f"{self.unit_id}.annual_opex_GBP": annual_opex,
            f"{self.unit_id}.annual_capex_GBP": annual_capex,
            f"{self.unit_id}.LCOH_GBP_per_kg": lcoh,
        }

    # ── Analytical linearisation ──────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        a, b, c = self.params.a, self.params.b, self.params.c
        variables = self.variables()
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)

        feed0 = x0_dict[self.v_feed]

        # Row 0: h2 - (a * feed - b * feed²) = 0
        # ∂/∂feed = -(a - 2 b feed) = -a + 2 b feed
        # ∂/∂h2   = 1
        # ∂/∂steam = 0
        # Row 1: steam - c * feed = 0
        # ∂/∂feed = -c, ∂/∂h2 = 0, ∂/∂steam = 1
        J = np.array([
            [-a + 2.0 * b * feed0, 1.0, 0.0],
            [-c,                   0.0, 1.0],
        ])
        f0 = self.residual(x0_dict)

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=False,
            trust_region=self.trust_region,
            kpi_gradients=self._kpi_gradients(x0_dict),
        )

    def _kpi_gradients(self, x: Dict[str, float]) -> Dict[str, np.ndarray]:
        hours = self.params.operating_hours_per_year
        return {
            f"{self.unit_id}.annual_h2_kg": np.array([0.0, hours, 0.0]),
        }
