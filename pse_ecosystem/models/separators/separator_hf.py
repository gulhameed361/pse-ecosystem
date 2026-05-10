"""Split-fraction separator.

Distributes each component across M outlet streams according to fixed split
fractions. Linear when split fractions are parameters; the SLP driver
short-circuits to a single LP solve.

Ports
-----
inlet     : StreamPort  (F_i_in, T_in, P_in)
outlet_k  : StreamPort  (F_i_out_k, T_out_k, P_out_k)  for k = 0..M-1

Residuals (N*M + 2*M equations)
---------------------------------
  Split   : F_i_out_k - sf_ik * F_i_in = 0   [N*(M-1)]
  Closure : Σ_k F_i_out_k - F_i_in = 0        [N]
  T/P     : T_out_k - T_in = 0, P_out_k - P_in = 0   [2*M]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class SeparatorHFParams:
    n_outlets: int = 2
    # split_fractions[i][k] = fraction of component i going to outlet k
    # Shape: [N_comp × N_outlets]. Rows must sum to 1.
    # If None, defaults to equal split.
    split_fractions: Optional[List[List[float]]] = None
    feed_max: float = 1e4   # mol/s
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7


class SeparatorHF(BaseUnit):
    """Linear split-fraction separator."""

    is_linear = True

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: Optional[SeparatorHFParams] = None,
    ):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or SeparatorHFParams()
        M = self.params.n_outlets
        N = len(components)

        # Build split fraction matrix [N × M]
        if self.params.split_fractions is not None:
            self._sf = np.array(self.params.split_fractions, dtype=float)
        else:
            self._sf = np.full((N, M), 1.0 / M)

        self.inlet_port = StreamPort(unit_id, "inlet", components)
        self.outlet_ports = [
            StreamPort(unit_id, f"outlet_{k}", components) for k in range(M)
        ]

    def _v_F_in(self, c: str) -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self) -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self) -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, k: int, c: str) -> str: return f"{self.unit_id}.outlet_{k}.F_{c}"
    def _v_T_out(self, k: int) -> str: return f"{self.unit_id}.outlet_{k}.T"
    def _v_P_out(self, k: int) -> str: return f"{self.unit_id}.outlet_{k}.P"

    def variables(self) -> List[str]:
        p = self.params
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for k in range(p.n_outlets):
            for c in self.components:
                vlist.append(self._v_F_out(k, c))
            vlist += [self._v_T_out(k), self._v_P_out(k)]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for c in self.components:
            bds[self._v_F_in(c)] = (0.0, p.feed_max)
        bds[self._v_T_in()] = (p.T_min, p.T_max)
        bds[self._v_P_in()] = (p.P_min, p.P_max)
        for k in range(p.n_outlets):
            for c in self.components:
                bds[self._v_F_out(k, c)] = (0.0, p.feed_max)
            bds[self._v_T_out(k)] = (p.T_min, p.T_max)
            bds[self._v_P_out(k)] = (p.P_min, p.P_max)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        N = len(self.components)
        M = self.params.n_outlets
        res_list = []

        # Split fraction residuals for outlets 0..M-2 (last outlet is determined)
        for i, c in enumerate(self.components):
            F_in = x.get(self._v_F_in(c), 0.0)
            for k in range(M - 1):
                F_out_k = x.get(self._v_F_out(k, c), 0.0)
                res_list.append(F_out_k - self._sf[i, k] * F_in)

        # Closure: Σ_k F_i_out_k = F_i_in
        for i, c in enumerate(self.components):
            F_in = x.get(self._v_F_in(c), 0.0)
            F_out_sum = sum(x.get(self._v_F_out(k, c), 0.0) for k in range(M))
            res_list.append(F_out_sum - F_in)

        # Temperature and pressure pass-through
        T_in = x.get(self._v_T_in(), 0.0)
        P_in = x.get(self._v_P_in(), 0.0)
        for k in range(M):
            res_list.append(x.get(self._v_T_out(k), 0.0) - T_in)
            res_list.append(x.get(self._v_P_out(k), 0.0) - P_in)

        return np.array(res_list, dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Exact analytical Jacobian — linear when split fractions are fixed."""
        variables = self.variables()
        n = len(variables)
        x0 = np.array([guess.values.get(v, 0.0) for v in variables], dtype=float)
        f0 = np.asarray(self.residual(guess.values), dtype=float)
        m = f0.size

        J = np.zeros((m, n), dtype=float)
        vidx = {v: i for i, v in enumerate(variables)}
        N = len(self.components)
        M = self.params.n_outlets

        row = 0
        # Split fraction rows
        for i, c in enumerate(self.components):
            for k in range(M - 1):
                J[row, vidx[self._v_F_out(k, c)]] = 1.0
                J[row, vidx[self._v_F_in(c)]] = -self._sf[i, k]
                row += 1

        # Closure rows
        for i, c in enumerate(self.components):
            J[row, vidx[self._v_F_in(c)]] = -1.0
            for k in range(M):
                J[row, vidx[self._v_F_out(k, c)]] = 1.0
            row += 1

        # T/P pass-through rows
        for k in range(M):
            J[row, vidx[self._v_T_out(k)]] = 1.0
            J[row, vidx[self._v_T_in()]] = -1.0
            row += 1
            J[row, vidx[self._v_P_out(k)]] = 1.0
            J[row, vidx[self._v_P_in()]] = -1.0
            row += 1

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms={},
            is_exact=True,
        )
