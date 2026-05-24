"""Ideal mixer — linear unit model.

N inlet streams are mixed into one outlet with perfect mixing (no reaction,
no heat of mixing, no pressure drop). One mass balance per component.

Variables
---------
{id}.F_in_{j}_{c}   inlet flowrate of component c on stream j  [mol/s or kg/s]
{id}.F_out_{c}       outlet flowrate of component c            [mol/s or kg/s]

Residuals
---------
r_c = F_out_c - sum_j( F_in_j_c ) = 0    [n_components equations]

The model is fully linear, so the SLP driver short-circuits to a single LP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess
from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


class IdealMixer(BaseUnit):
    """Ideal n-inlet mixer — linear, analytical Jacobian."""

    is_linear = True
    category = UnitCategory.DIDACTIC

    def __init__(
        self,
        unit_id: str = "mixer",
        n_inlets: int = 2,
        components: Sequence[str] = ("A",),
    ):
        self.unit_id = unit_id
        self.n_inlets = int(n_inlets)
        self.components = list(components)

    # ── Variable namespace ────────────────────────────────────────────────

    def _inlet_var(self, j: int, c: str) -> str:
        return f"{self.unit_id}.F_in_{j}_{c}"

    def _outlet_var(self, c: str) -> str:
        return f"{self.unit_id}.F_out_{c}"

    def variables(self) -> List[str]:
        inlets = [
            self._inlet_var(j, c)
            for j in range(self.n_inlets)
            for c in self.components
        ]
        outlets = [self._outlet_var(c) for c in self.components]
        return inlets + outlets

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {v: (0.0, 1e6) for v in self.variables()}

    # ── Physics ───────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        r = []
        for c in self.components:
            inlet_sum = sum(
                x.get(self._inlet_var(j, c), 0.0) for j in range(self.n_inlets)
            )
            r.append(x.get(self._outlet_var(c), 0.0) - inlet_sum)
        return np.array(r, dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        total = sum(x.get(self._outlet_var(c), 0.0) for c in self.components)
        return {f"{self.unit_id}.total_F_out": total}

    # ── Analytical linearisation ──────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        variables = self.variables()
        n = len(variables)
        m = len(self.components)

        x0 = np.array([guess.values.get(v, 0.0) for v in variables], dtype=float)
        f0 = self.residual(dict(zip(variables, x0)))

        # J is constant (linear model):
        # For residual row k (component components[k]):
        #   d r_k / d F_in_j_k = -1
        #   d r_k / d F_out_k  = +1
        #   all other columns   =  0
        J = np.zeros((m, n), dtype=float)
        var_index = {v: i for i, v in enumerate(variables)}

        for k, c in enumerate(self.components):
            for j in range(self.n_inlets):
                col = var_index[self._inlet_var(j, c)]
                J[k, col] = -1.0
            J[k, var_index[self._outlet_var(c)]] = 1.0

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(dict(zip(variables, x0))),
            is_exact=True,
        )
