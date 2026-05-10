"""Isentropic compressor (ideal gas).

Physics
-------
Isentropic outlet temperature:
    T_out_isen = T_in * (P_out/P_in)^((γ-1)/γ)

Actual outlet temperature with isentropic efficiency η:
    T_out = T_in + (T_out_isen - T_in) / η

Shaft work:
    W_shaft = F_in * Cp_mix(T_avg) * (T_out - T_in)   [W]

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Additional variables
---------------------
W_shaft  : shaft power consumed [W] (positive = work input)

Residuals (N + 3 equations)
-----------------------------
  Material  : F_i_out - F_i_in = 0                               [N]
  Temp      : T_out - (T_in + (T_in*(r_P^θ) - T_in) / η) = 0   [1]
  Work      : W_shaft - F_total * Cp_mix * (T_out - T_in) = 0   [1]
  Pressure  : (treated as degree of freedom — P_out is a free var) [0]
  P_outlet  : P_out - P_out_spec = 0 if P_out_spec given,        [1]
              else P_out is a free variable within bounds

where r_P = P_out/P_in, θ = (γ-1)/γ
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import mixture_cp_J_mol_K, gamma, SHOMATE

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())


@dataclass
class CompressorParams:
    eta_isentropic: float = 0.75   # isentropic efficiency [-]
    P_out_Pa: Optional[float] = None  # if None, P_out is a free variable
    feed_max: float = 1e4          # mol/s
    T_min: float = 250.0
    T_max: float = 1500.0
    P_min: float = 1e4
    P_max: float = 1e8
    W_max: float = 1e9             # W
    gamma_fixed: Optional[float] = None  # if None, computed from species


class Compressor(BaseUnit):
    """Isentropic gas compressor with efficiency correction."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: Optional[CompressorParams] = None):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or CompressorParams()
        self.inlet_port  = StreamPort(unit_id, "inlet",  components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, c: str)  -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self)          -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self)          -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self)         -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self)         -> str: return f"{self.unit_id}.outlet.P"
    def _v_W(self)             -> str: return f"{self.unit_id}.W_shaft"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out(), self._v_W()]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for c in self.components:
            bds[self._v_F_in(c)]  = (0.0, p.feed_max)
            bds[self._v_F_out(c)] = (0.0, p.feed_max)
        bds[self._v_T_in()]  = (p.T_min, p.T_max)
        bds[self._v_P_in()]  = (p.P_min, p.P_max)
        bds[self._v_T_out()] = (p.T_min, p.T_max)
        if p.P_out_Pa is not None:
            bds[self._v_P_out()] = (p.P_out_Pa, p.P_out_Pa)
        else:
            bds[self._v_P_out()] = (p.P_min, p.P_max)
        bds[self._v_W()] = (0.0, p.W_max)
        return bds

    def _gamma(self, x: Dict[str, float]) -> float:
        if self.params.gamma_fixed is not None:
            return self.params.gamma_fixed
        # Mixture γ from Cp at average T
        T_avg = 0.5 * (x.get(self._v_T_in(), 298.0) + x.get(self._v_T_out(), 400.0))
        flows = {c: x.get(self._v_F_in(c), 0.0) for c in self.components if c in _KNOWN}
        total = sum(flows.values())
        if total < 1e-12:
            return 1.4
        Cp_mix = mixture_cp_J_mol_K(flows, T_avg, basis="molar_flow")
        return Cp_mix / (Cp_mix - _R_GAS) if Cp_mix > _R_GAS else 1.4

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(N + 3, dtype=float)

        T_in  = x.get(self._v_T_in(), 298.15)
        P_in  = max(x.get(self._v_P_in(), 101325.0), 1e-3)
        T_out = x.get(self._v_T_out(), 400.0)
        P_out = max(x.get(self._v_P_out(), 300000.0), 1e-3)
        W     = x.get(self._v_W(), 0.0)

        F_in_total = sum(x.get(self._v_F_in(c), 0.0) for c in comps)

        # Material balances [N]
        for i, c in enumerate(comps):
            res[i] = x.get(self._v_F_out(c), 0.0) - x.get(self._v_F_in(c), 0.0)

        # Isentropic temperature rise [1]
        g = self._gamma(x)
        theta = (g - 1.0) / g
        r_P = P_out / P_in
        T_out_isen = T_in * (r_P ** theta)
        eta = self.params.eta_isentropic
        T_out_actual = T_in + (T_out_isen - T_in) / eta
        res[N] = T_out - T_out_actual

        # Shaft work [1]
        flows_in = {c: x.get(self._v_F_in(c), 0.0) for c in comps if c in _KNOWN}
        Cp_mix = mixture_cp_J_mol_K(flows_in, 0.5 * (T_in + T_out), basis="molar_flow")
        W_calc = max(F_in_total, 0.0) * Cp_mix * (T_out - T_in)
        res[N + 1] = W - W_calc

        # Pressure (P_out specified or free; if specified → bounds handle it, residual is 0)
        if self.params.P_out_Pa is not None:
            res[N + 2] = P_out - self.params.P_out_Pa
        else:
            res[N + 2] = 0.0  # P_out is a free variable; no additional residual

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        W = x.get(self._v_W(), 0.0)
        from pse_ecosystem.models.costing.sslw_costing import compressor_purchase_cost_USD
        return {
            "W_shaft_W": W,
            "capex_USD": compressor_purchase_cost_USD(W),
            "opex_USD_per_yr": self.opex_per_year(x),
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import compressor_purchase_cost_USD
        return compressor_purchase_cost_USD(x.get(self._v_W(), 0.0))
