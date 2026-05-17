"""Isoenthalpic pressure-drop valve (throttling).

For ideal gases: h(T) = Cp*T is pressure-independent → isenthalpic = isothermal.
For real applications the Joule-Thomson coefficient is non-zero, but this
model uses the ideal-gas limit which is appropriate for the SLP conceptual
design context.

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Additional variables
---------------------
Cv : valve coefficient [mol/s/Pa^0.5]  — relates flow to pressure drop

Residuals (N + 3 equations)
-----------------------------
  Material    : F_i_out - F_i_in = 0                          [N]
  Isenthalpic : T_out - T_in = 0  (ideal gas)                 [1]
  Valve eqn   : F_total_out - Cv * sqrt(P_in - P_out) = 0     [1]
  (P_out is a free variable within bounds or fixed by connection)
  Extra       : 0 = 0  (placeholder if Cv is parametric)      [1]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class ValveParams:
    Cv: Optional[float] = None   # if None, Cv is a free variable
    P_out_Pa: Optional[float] = None  # if None, P_out is free
    feed_max: float = 1e4
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    Cv_max: float = 1e6


class Valve(BaseUnit):
    """Isoenthalpic throttling valve."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: Optional[ValveParams] = None):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or ValveParams()
        self.inlet_port  = StreamPort(unit_id, "inlet",  components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, c: str)  -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self)          -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self)          -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self)         -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self)         -> str: return f"{self.unit_id}.outlet.P"
    def _v_Cv(self)            -> str: return f"{self.unit_id}.Cv"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out(), self._v_Cv()]
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
        bds[self._v_P_out()] = (p.P_min, p.P_max) if p.P_out_Pa is None else (p.P_out_Pa, p.P_out_Pa)
        bds[self._v_Cv()]    = (0.0, p.Cv_max) if p.Cv is None else (p.Cv, p.Cv)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(N + 3, dtype=float)

        T_in  = x.get(self._v_T_in(), 300.0)
        P_in  = x.get(self._v_P_in(), 200000.0)
        T_out = x.get(self._v_T_out(), 300.0)
        P_out = x.get(self._v_P_out(), 100000.0)
        Cv    = x.get(self._v_Cv(), self.params.Cv or 1.0)

        F_total_out = sum(x.get(self._v_F_out(c), 0.0) for c in comps)

        # Material [N]
        for i, c in enumerate(comps):
            res[i] = x.get(self._v_F_out(c), 0.0) - x.get(self._v_F_in(c), 0.0)

        # Isenthalpic (ideal gas: T_out = T_in) [1]
        res[N] = T_out - T_in

        # Valve flow equation [1] — Cv·√(dP). Smoothed with a tiny floor so
        # the Jacobian stays finite at dP → 0 (the raw √x derivative blows
        # up at zero). Audit M5: pre-v1.4.0 the residual was identically
        # zero in the reverse-flow regime, hiding sensitivity to P_out.
        dP = max(P_in - P_out, 0.0) + 1e-9
        res[N + 1] = F_total_out - Cv * dP ** 0.5

        # Pressure spec residual [1]
        if self.params.P_out_Pa is not None:
            res[N + 2] = P_out - self.params.P_out_Pa
        else:
            res[N + 2] = 0.0

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}
