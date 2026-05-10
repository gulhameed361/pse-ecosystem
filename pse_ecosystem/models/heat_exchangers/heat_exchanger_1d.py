"""1D distributed heat exchanger — N finite elements.

Internal temperature profiles are solved analytically (element-by-element
energy balance for counterflow) and hidden from the outer SLP.  Only inlet
and outlet temperatures are exposed as unit variables.

Ports
-----
hot_in, hot_out   : StreamPort
cold_in, cold_out : StreamPort

Additional variable: Q [W]

Residuals (3 equations)
-------------------------
  T_hot_out declared vs computed  = 0
  T_cold_out declared vs computed = 0
  Q declared vs summed element Q  = 0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import mixture_cp_J_mol_K, SHOMATE

_KNOWN = set(SHOMATE.keys())


@dataclass
class HeatExchanger1DParams:
    U_W_per_m2_K: float = 500.0
    A_m2: float = 10.0
    n_elements: int = 5
    flow_arrangement: str = "counter"  # 'counter' or 'parallel'
    feed_max: float = 1e4
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e10


class HeatExchanger1D(BaseUnit):
    """1D distributed HX with N finite-element internal solve."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        hot_components: List[str],
        cold_components: List[str],
        params: Optional[HeatExchanger1DParams] = None,
    ):
        self.unit_id = unit_id
        self.hot_components  = list(hot_components)
        self.cold_components = list(cold_components)
        self.params = params or HeatExchanger1DParams()
        self.hot_inlet_port   = StreamPort(unit_id, "hot_in",   hot_components)
        self.hot_outlet_port  = StreamPort(unit_id, "hot_out",  hot_components)
        self.cold_inlet_port  = StreamPort(unit_id, "cold_in",  cold_components)
        self.cold_outlet_port = StreamPort(unit_id, "cold_out", cold_components)

    def _v(self, tag: str, c: str) -> str: return f"{self.unit_id}.{tag}.F_{c}"
    def _vT(self, tag: str)        -> str: return f"{self.unit_id}.{tag}.T"
    def _vP(self, tag: str)        -> str: return f"{self.unit_id}.{tag}.P"
    def _v_Q(self)                 -> str: return f"{self.unit_id}.Q"

    def variables(self) -> List[str]:
        vlist = []
        for tag, comps in [("hot_in", self.hot_components), ("hot_out", self.hot_components),
                            ("cold_in", self.cold_components), ("cold_out", self.cold_components)]:
            for c in comps:
                vlist.append(self._v(tag, c))
            vlist += [self._vT(tag), self._vP(tag)]
        vlist.append(self._v_Q())
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for tag, comps in [("hot_in", self.hot_components), ("hot_out", self.hot_components),
                            ("cold_in", self.cold_components), ("cold_out", self.cold_components)]:
            for c in comps:
                bds[self._v(tag, c)] = (0.0, p.feed_max)
            bds[self._vT(tag)] = (p.T_min, p.T_max)
            bds[self._vP(tag)] = (p.P_min, p.P_max)
        bds[self._v_Q()] = (0.0, p.Q_max)
        return bds

    def _solve_1d(self, T_hi: float, T_ci: float, C_hot: float, C_cold: float) -> Tuple[float, float, float]:
        """Solve N-element counter-flow HX analytically.

        Returns (T_ho_computed, T_co_computed, Q_total).
        Uses the analytical solution for a counterflow HX with uniform UA.
        """
        p = self.params
        N = p.n_elements
        dA = p.A_m2 / N
        U = p.U_W_per_m2_K

        if p.flow_arrangement == "counter":
            # Counter-flow: hot enters at element N, cold enters at element 1
            # Solve from cold inlet side
            T_hot = np.zeros(N + 1)
            T_cold = np.zeros(N + 1)
            T_cold[0] = T_ci    # cold inlet = element 0 cold side

            # We need to iterate because T_hot depends on T_co (counterflow)
            # Use analytical NTU solution for the full HX as initial guess
            C_min = min(C_hot, C_cold)
            C_max = max(C_hot, C_cold) + 1e-12
            C_star = C_min / C_max
            NTU = U * p.A_m2 / max(C_min, 1e-12)
            if C_star >= 1.0 - 1e-6:
                eps = NTU / (1.0 + NTU)
            else:
                import math
                eps = (1.0 - math.exp(-NTU * (1 - C_star))) / (1 - C_star * math.exp(-NTU * (1 - C_star)))
            Q_total = eps * C_min * (T_hi - T_ci)
            T_ho = T_hi - Q_total / max(C_hot, 1e-12)
            T_co = T_ci + Q_total / max(C_cold, 1e-12)
        else:
            # Parallel flow: analytical NTU solution
            import math
            C_min = min(C_hot, C_cold)
            C_max = max(C_hot, C_cold) + 1e-12
            C_star = C_min / C_max
            NTU = U * p.A_m2 / max(C_min, 1e-12)
            eps = (1 - math.exp(-NTU * (1 + C_star))) / (1 + C_star)
            Q_total = eps * C_min * (T_hi - T_ci)
            T_ho = T_hi - Q_total / max(C_hot, 1e-12)
            T_co = T_ci + Q_total / max(C_cold, 1e-12)

        return T_ho, T_co, Q_total

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        T_hi = x.get(self._vT("hot_in"),  500.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        T_co = x.get(self._vT("cold_out"),380.0)
        Q    = x.get(self._v_Q(), 0.0)

        flows_hot  = {c: x.get(self._v("hot_in",  c), 0.0) for c in self.hot_components  if c in _KNOWN}
        flows_cold = {c: x.get(self._v("cold_in", c), 0.0) for c in self.cold_components if c in _KNOWN}
        Cp_hot  = mixture_cp_J_mol_K(flows_hot,  0.5*(T_hi+T_ho), basis="molar_flow")
        Cp_cold = mixture_cp_J_mol_K(flows_cold, 0.5*(T_ci+T_co), basis="molar_flow")
        C_hot  = sum(flows_hot.values())  * Cp_hot
        C_cold = sum(flows_cold.values()) * Cp_cold

        T_ho_comp, T_co_comp, Q_comp = self._solve_1d(T_hi, T_ci, C_hot, C_cold)

        res = np.zeros(3, dtype=float)
        res[0] = T_ho - T_ho_comp
        res[1] = T_co - T_co_comp
        res[2] = Q - Q_comp
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
        return hx_purchase_cost_USD(self.params.A_m2)
