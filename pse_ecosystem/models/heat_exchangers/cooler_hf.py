"""CoolerHF — single-stream gas cooler with fixed outlet temperature.

Represents a shell-and-tube or air-cooled heat exchanger where the syngas
(or any multi-component gas) is cooled to a target temperature.  The cooling
utility (water, air) is not modelled explicitly; only the process-side stream
is tracked.

Design choice: both ports are T/P-free so this unit chains directly to
WGS-style units (which also have no T/P on their ports) without a T/P
variable-count mismatch.  The outlet temperature is a fixed parameter, not
an optimisation variable.

Ports
-----
inlet_port  : N-component gas feed (no T, no P)
outlet_port : same N components (no T, no P)

Variables (2N)
--------------
{uid}.inlet.F_{comp}   [mol/s or kg/s]  — inlet flows
{uid}.outlet.F_{comp}  [mol/s or kg/s]  — outlet flows

Residuals (N)
-------------
f[i] = outlet.F_{comp[i]} − inlet.F_{comp[i]}  = 0   (mass conservation)

KPIs
----
{uid}.T_out_K : target outlet temperature [K] (informational)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class CoolerHFParams:
    T_out_K: float = 400.0      # target outlet temperature [K]
    feed_max: float = 1_000.0   # upper bound on all flow variables


class CoolerHF(BaseUnit):
    """Single-stream gas cooler — linear, fixed-T_out, flow-through.

    Parameters
    ----------
    unit_id    : Unique identifier.
    components : List of species tracked through the cooler.
    params     : CoolerHFParams with T_out_K and feed_max.
    """

    is_linear: bool = True

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: CoolerHFParams | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or CoolerHFParams()

        self.inlet_port = StreamPort(
            unit_id=unit_id, tag="inlet",
            components=self.components, has_T=False, has_P=False,
            phase="gas",
        )
        self.outlet_port = StreamPort(
            unit_id=unit_id, tag="outlet",
            components=self.components, has_T=False, has_P=False,
            phase="gas",
        )

    # ── Variable helpers ──────────────────────────────────────────────────────

    def _v_in(self, c: str) -> str:
        return f"{self.unit_id}.inlet.F_{c}"

    def _v_out(self, c: str) -> str:
        return f"{self.unit_id}.outlet.F_{c}"

    def variables(self) -> List[str]:
        return [self._v_in(c) for c in self.components] + \
               [self._v_out(c) for c in self.components]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        ub = self.params.feed_max
        return {v: (0.0, ub) for v in self.variables()}

    # ── Residuals ─────────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        N = len(self.components)
        res = np.zeros(N)
        for i, c in enumerate(self.components):
            res[i] = x.get(self._v_out(c), 0.0) - x.get(self._v_in(c), 0.0)
        return res

    # ── Linearisation (exact analytical Jacobian) ─────────────────────────────

    def linearize(self, guess):
        from pse_ecosystem.core.contracts import LinearizedModel
        N = len(self.components)
        var_names = self.variables()   # [in_0..in_N-1, out_0..out_N-1]
        n_vars = len(var_names)        # 2N
        J = np.zeros((N, n_vars))
        for i in range(N):
            J[i, i]     = -1.0   # d res[i]/d in[i]
            J[i, N + i] =  1.0   # d res[i]/d out[i]
        x0 = guess.vector(var_names)
        f0 = self.residual(guess.values)
        return LinearizedModel(
            unit_id=self.unit_id,
            variables=var_names,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            is_exact=True,
        )

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        total_out = sum(x.get(self._v_out(c), 0.0) for c in self.components)
        return {
            f"{self.unit_id}.T_out_K": self.params.T_out_K,
            f"{self.unit_id}.total_flow_out": total_out,
        }

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex_USD(self, x: Dict[str, float]) -> float:
        return 0.0
