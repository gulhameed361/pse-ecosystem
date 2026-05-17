"""NTU-effectiveness heat exchanger (counter-current, ideal gases).

Physics
-------
C_hot  = F_hot * Cp_hot(T_avg_hot)
C_cold = F_cold * Cp_cold(T_avg_cold)
C_min  = min(C_hot, C_cold)  [evaluated at linearisation point for SLP]
C_star = C_min / C_max

Counter-current effectiveness:
    ε = (1 - exp(-NTU*(1-C*))) / (1 - C*·exp(-NTU*(1-C*)))
    (degenerate when C* → 1: ε = NTU/(1+NTU))

Q = ε * C_min * (T_hot_in - T_cold_in)

Residuals (5 equations)
-------------------------
  Hot energy  : Q - C_hot * (T_hot_in  - T_hot_out)  = 0  [1]
  Cold energy : Q - C_cold * (T_cold_out - T_cold_in) = 0  [1]
  Effectiveness: ε - ε_NTU(NTU, C*) = 0                   [1]
  Heat duty   : Q - ε * C_min * (T_hot_in - T_cold_in) = 0 [1]
  NTU def     : NTU - U_A / C_min = 0                      [1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import mixture_cp_J_mol_K, SHOMATE

_KNOWN = set(SHOMATE.keys())


@dataclass
class HeatExchangerNTUParams:
    UA_W_per_K: float = 1000.0        # overall UA [W/K] (UA = U*A)
    flow_arrangement: str = "counter" # 'counter' or 'parallel'
    hot_species: Optional[List[str]] = None    # subset of hot components for Cp
    cold_species: Optional[List[str]] = None
    feed_max: float = 1e4
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e10


class HeatExchangerNTU(BaseUnit):
    """Counter-current NTU-effectiveness heat exchanger."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        hot_components: List[str],
        cold_components: List[str],
        params: Optional[HeatExchangerNTUParams] = None,
    ):
        self.unit_id = unit_id
        self.hot_components  = list(hot_components)
        self.cold_components = list(cold_components)
        self.params = params or HeatExchangerNTUParams()
        self.hot_inlet_port   = StreamPort(unit_id, "hot_in",   hot_components)
        self.hot_outlet_port  = StreamPort(unit_id, "hot_out",  hot_components)
        self.cold_inlet_port  = StreamPort(unit_id, "cold_in",  cold_components)
        self.cold_outlet_port = StreamPort(unit_id, "cold_out", cold_components)

    def _v(self, tag: str, c: str) -> str: return f"{self.unit_id}.{tag}.F_{c}"
    def _vT(self, tag: str)        -> str: return f"{self.unit_id}.{tag}.T"
    def _vP(self, tag: str)        -> str: return f"{self.unit_id}.{tag}.P"
    def _v_Q(self)                 -> str: return f"{self.unit_id}.Q"
    def _v_eps(self)               -> str: return f"{self.unit_id}.effectiveness"
    def _v_NTU(self)               -> str: return f"{self.unit_id}.NTU"

    def variables(self) -> List[str]:
        vlist = []
        for tag, comps in [("hot_in", self.hot_components), ("hot_out", self.hot_components),
                            ("cold_in", self.cold_components), ("cold_out", self.cold_components)]:
            for c in comps:
                vlist.append(self._v(tag, c))
            vlist += [self._vT(tag), self._vP(tag)]
        vlist += [self._v_Q(), self._v_eps(), self._v_NTU()]
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
        bds[self._v_Q()]   = (0.0, p.Q_max)
        bds[self._v_eps()] = (0.0, 1.0)
        bds[self._v_NTU()] = (0.0, 50.0)
        return bds

    def _C_hot_cold(self, x: Dict[str, float]) -> Tuple[float, float]:
        """Return (C_hot, C_cold) [W/K] at current x."""
        T_hi = x.get(self._vT("hot_in"), 500.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        T_co = x.get(self._vT("cold_out"), 350.0)

        flows_hot  = {c: x.get(self._v("hot_in", c), 0.0) for c in self.hot_components  if c in _KNOWN}
        flows_cold = {c: x.get(self._v("cold_in", c), 0.0) for c in self.cold_components if c in _KNOWN}

        Cp_hot  = mixture_cp_J_mol_K(flows_hot,  0.5*(T_hi+T_ho), basis="molar_flow")
        Cp_cold = mixture_cp_J_mol_K(flows_cold, 0.5*(T_ci+T_co), basis="molar_flow")
        C_hot  = sum(flows_hot.values())  * Cp_hot
        C_cold = sum(flows_cold.values()) * Cp_cold
        return C_hot, C_cold

    @staticmethod
    def _eps_from_NTU(NTU: float, C_star: float) -> float:
        if C_star >= 1.0 - 1e-6:
            return NTU / (1.0 + NTU)  # degenerate balanced case
        # Clamp the exponent argument to keep math.exp() in range. For very
        # effective exchangers the (-NTU*(1-C*)) magnitude can grow without
        # bound; once it exceeds ~700 the result saturates to 0 anyway, so
        # capping at 700 avoids spurious OverflowError without affecting
        # downstream numerics.
        arg = -NTU * (1.0 - C_star)
        arg = max(min(arg, 700.0), -700.0)
        e = math.exp(arg)
        return (1.0 - e) / (1.0 - C_star * e)

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        T_hi = x.get(self._vT("hot_in"),  500.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        T_co = x.get(self._vT("cold_out"),350.0)
        Q    = x.get(self._v_Q(), 0.0)
        eps  = x.get(self._v_eps(), 0.5)
        NTU  = x.get(self._v_NTU(), 2.0)

        C_hot, C_cold = self._C_hot_cold(x)
        C_min = min(C_hot, C_cold)
        C_max = max(C_hot, C_cold)
        C_min = max(C_min, 1e-12)
        C_max = max(C_max, 1e-12)
        C_star = C_min / C_max

        UA = self.params.UA_W_per_K

        res = np.zeros(5, dtype=float)
        res[0] = Q - C_hot * (T_hi - T_ho)                              # hot energy
        res[1] = Q - C_cold * (T_co - T_ci)                             # cold energy
        res[2] = eps - self._eps_from_NTU(NTU, C_star)                  # ε-NTU relation
        res[3] = Q - eps * C_min * (T_hi - T_ci)                        # Q = ε*C_min*ΔT_max
        res[4] = NTU - UA / C_min                                        # NTU definition
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        Q = x.get(self._v_Q(), 0.0)
        eps = x.get(self._v_eps(), 0.0)
        from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
        A_m2 = self.params.UA_W_per_K / 500.0  # assume U=500 W/m²/K
        return {
            "Q_W": Q,
            "effectiveness": eps,
            "capex_USD": hx_purchase_cost_USD(A_m2),
            "opex_USD_per_yr": 0.0,
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
        A_m2 = self.params.UA_W_per_K / 500.0
        return hx_purchase_cost_USD(A_m2)
