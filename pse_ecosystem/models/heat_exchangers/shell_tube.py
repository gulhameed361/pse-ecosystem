"""Shell-and-tube heat exchanger with corrected LMTD.

Q = U * A * F * LMTD_cf

LMTD_cf is the counter-flow log-mean temperature difference.
F is the correction factor for a 1-2 (one shell pass, two tube passes)
exchanger, fitted from Bowman-Mueller-Nagle charts as an explicit function
of P (thermal effectiveness) and R (heat capacity ratio).

Physics correction vs. HeatExchangerToy
-----------------------------------------
HeatExchangerToy uses bare LMTD with FD Jacobian and no F-factor.
This unit adds:
  • Corrected LMTD (L'Hopital limit when ΔT₁ ≈ ΔT₂ avoids log singularity)
  • F-factor polynomial for 1-2 shell-and-tube geometry

Ports
-----
hot_in, hot_out   : StreamPort
cold_in, cold_out : StreamPort

Additional variable: Q [W]

Residuals (4 equations)
-------------------------
  Hot   : Q - F_hot * Cp_hot * (T_hi - T_ho) = 0
  Cold  : Q - F_cold * Cp_cold * (T_co - T_ci) = 0
  LMTD  : Q - U * A * F * LMTD_cf = 0
  Pressure hot  : P_ho - P_hi = 0  (no hot-side ΔP)
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
class ShellTubeParams:
    U_W_per_m2_K: float = 500.0   # overall heat-transfer coefficient [W/m²/K]
    A_m2: float = 10.0             # heat-transfer area [m²]
    n_shell_passes: int = 1
    n_tube_passes: int = 2
    feed_max: float = 1e4
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e10


def _lmtd_cf(T_hi: float, T_ho: float, T_ci: float, T_co: float) -> float:
    """Counter-flow LMTD [K].  L'Hopital limit when ΔT₁ ≈ ΔT₂."""
    dT1 = T_hi - T_co
    dT2 = T_ho - T_ci
    if abs(dT1 - dT2) < 1e-6:
        return 0.5 * (dT1 + dT2)  # L'Hopital limit
    if dT1 <= 0.0 or dT2 <= 0.0:
        return max(dT1, dT2, 0.0)
    return (dT1 - dT2) / math.log(dT1 / dT2)


def _f_factor_1_2(T_hi: float, T_ho: float, T_ci: float, T_co: float) -> float:
    """F-factor for 1-2 shell-and-tube (Bowman-Mueller-Nagle analytical form).
    Returns a value clamped to [0.5, 1.0].
    """
    denom = T_hi - T_ci
    if abs(denom) < 1e-6:
        return 1.0
    P = (T_co - T_ci) / denom
    R_num = T_hi - T_ho
    R_den = T_co - T_ci
    if abs(R_den) < 1e-6:
        R = 1.0
    else:
        R = R_num / R_den

    if abs(R - 1.0) < 1e-4:
        # Degenerate R=1 case
        S = P / (2 - P)
        num = math.sqrt(2) * (1 - P) if abs(1 - P) > 1e-9 else 1e-6
        if num <= 0:
            return 1.0
        try:
            F = math.sqrt(2) * S / ((1 - S) * math.log((1 + S - math.sqrt(2) * S) /
                                                          (1 + S + math.sqrt(2) * S)))
        except (ValueError, ZeroDivisionError):
            F = 0.9
    else:
        try:
            sqrt_R2 = math.sqrt(R ** 2 + 1)
            lhs = (1 - P * R) / (1 - P)
            if lhs <= 0:
                return 0.75
            ln_lhs = math.log(lhs)
            denom_f = (R - 1) * math.log(
                (2 - P * (R + 1 - sqrt_R2)) / (2 - P * (R + 1 + sqrt_R2))
            )
            if abs(denom_f) < 1e-12:
                return 1.0
            F = sqrt_R2 * ln_lhs / denom_f
        except (ValueError, ZeroDivisionError):
            F = 0.85

    return max(0.5, min(F, 1.0))


class ShellTubeHX(BaseUnit):
    """Shell-and-tube heat exchanger with corrected LMTD (1-2 pass geometry)."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        hot_components: List[str],
        cold_components: List[str],
        params: Optional[ShellTubeParams] = None,
    ):
        self.unit_id = unit_id
        self.hot_components  = list(hot_components)
        self.cold_components = list(cold_components)
        self.params = params or ShellTubeParams()
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

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        T_hi = x.get(self._vT("hot_in"),  500.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        T_co = x.get(self._vT("cold_out"),380.0)
        Q    = x.get(self._v_Q(), 0.0)
        p    = self.params

        flows_hot  = {c: x.get(self._v("hot_in",  c), 0.0) for c in self.hot_components  if c in _KNOWN}
        flows_cold = {c: x.get(self._v("cold_in", c), 0.0) for c in self.cold_components if c in _KNOWN}

        Cp_hot  = mixture_cp_J_mol_K(flows_hot,  0.5*(T_hi+T_ho), basis="molar_flow")
        Cp_cold = mixture_cp_J_mol_K(flows_cold, 0.5*(T_ci+T_co), basis="molar_flow")
        C_hot  = sum(flows_hot.values())  * Cp_hot
        C_cold = sum(flows_cold.values()) * Cp_cold

        lmtd = _lmtd_cf(T_hi, T_ho, T_ci, T_co)
        F    = _f_factor_1_2(T_hi, T_ho, T_ci, T_co)

        res = np.zeros(4, dtype=float)
        res[0] = Q - C_hot * (T_hi - T_ho)
        res[1] = Q - C_cold * (T_co - T_ci)
        res[2] = Q - p.U_W_per_m2_K * p.A_m2 * F * lmtd
        res[3] = x.get(self._vP("hot_out"), 0.0) - x.get(self._vP("hot_in"), 0.0)
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
        return hx_purchase_cost_USD(self.params.A_m2)

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        return {
            "Q_W": x.get(self._v_Q(), 0.0),
            "capex_USD": self.capex(x),
            "opex_USD_per_yr": 0.0,
        }
