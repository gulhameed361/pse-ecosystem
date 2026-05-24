"""Multi-component mixer with energy balance.

Combines M inlet streams into one outlet stream. Mass and energy balances
are enforced; pressure is taken as the minimum inlet pressure (parametrised
at construction; can be overridden by setting P_out bounds in the flowsheet).

Ports
-----
inlet_k  : StreamPort  (F_i_in_k, T_in_k, P_in_k)  for k = 0..M-1
outlet   : StreamPort  (F_i_out, T_out, P_out)

Residuals (N + 2 equations)
----------------------------
  Material  :  F_i_out - Σ_k F_i_in_k = 0   [N]
  Energy    :  Σ_i F_i_out * h_i(T_out) - Σ_k Σ_i F_i_in_k * h_i(T_in_k) = 0  [1]
  Pressure  :  P_out - P_ref = 0              [1]  (P_ref = P_in_0 by default)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol


@dataclass
class MixerHFParams:
    n_inlets: int = 2
    feed_max: float = 1e4   # mol/s
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    pressure_ref_inlet: int = 0  # which inlet sets P_out


class MixerHF(BaseUnit):
    """Multi-inlet, single-outlet mixer with ideal-gas energy balance."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: Optional[MixerHFParams] = None):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or MixerHFParams()
        M = self.params.n_inlets
        self.inlet_ports = [
            StreamPort(unit_id, f"inlet_{k}", components) for k in range(M)
        ]
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, k: int, c: str) -> str:
        return f"{self.unit_id}.inlet_{k}.F_{c}"

    def _v_T_in(self, k: int) -> str:
        return f"{self.unit_id}.inlet_{k}.T"

    def _v_P_in(self, k: int) -> str:
        return f"{self.unit_id}.inlet_{k}.P"

    def _v_F_out(self, c: str) -> str:
        return f"{self.unit_id}.outlet.F_{c}"

    def _v_T_out(self) -> str:
        return f"{self.unit_id}.outlet.T"

    def _v_P_out(self) -> str:
        return f"{self.unit_id}.outlet.P"

    def variables(self) -> List[str]:
        vlist = []
        p = self.params
        for k in range(p.n_inlets):
            for c in self.components:
                vlist.append(self._v_F_in(k, c))
            vlist += [self._v_T_in(k), self._v_P_in(k)]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out()]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for k in range(p.n_inlets):
            for c in self.components:
                bds[self._v_F_in(k, c)] = (0.0, p.feed_max)
            bds[self._v_T_in(k)] = (p.T_min, p.T_max)
            bds[self._v_P_in(k)] = (p.P_min, p.P_max)
        for c in self.components:
            bds[self._v_F_out(c)] = (0.0, p.feed_max)
        bds[self._v_T_out()] = (p.T_min, p.T_max)
        bds[self._v_P_out()] = (p.P_min, p.P_max)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        M = p.n_inlets
        N = len(self.components)
        res = np.zeros(N + 2, dtype=float)

        # Material balances
        for i, c in enumerate(self.components):
            F_out = x.get(self._v_F_out(c), 0.0)
            F_in_sum = sum(x.get(self._v_F_in(k, c), 0.0) for k in range(M))
            res[i] = F_out - F_in_sum

        # Energy balance
        T_out = x.get(self._v_T_out(), 298.15)
        H_out = sum(
            x.get(self._v_F_out(c), 0.0) * enthalpy_J_mol(c, T_out)
            for c in self.components
            if c in _KNOWN_SPECIES
        )
        H_in_total = 0.0
        for k in range(M):
            T_in_k = x.get(self._v_T_in(k), 298.15)
            H_in_total += sum(
                x.get(self._v_F_in(k, c), 0.0) * enthalpy_J_mol(c, T_in_k)
                for c in self.components
                if c in _KNOWN_SPECIES
            )
        res[N] = H_out - H_in_total  # [J/s = W]; zero at steady state

        # Pressure: outlet = first inlet pressure
        ref = p.pressure_ref_inlet
        res[N + 1] = x.get(self._v_P_out(), 0.0) - x.get(self._v_P_in(ref), 0.0)

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        F_out = {c: x.get(self._v_F_out(c), 0.0) for c in self.components}
        F_total = sum(F_out.values())
        T_out = x.get(self._v_T_out(), 0.0)
        P_out = x.get(self._v_P_out(), 0.0)
        result: Dict[str, float] = {
            f"{uid}.outlet_total_flow_mol_s": F_total,
            f"{uid}.T_out_K": T_out,
            f"{uid}.P_out_Pa": P_out,
        }
        # Per-inlet flow contribution — useful for diagnosing mass-balance
        # closure when wiring multiple mixer feeds. v1.6 audit A.4.
        for k in range(self.params.n_inlets):
            F_in_k = sum(
                x.get(self._v_F_in(k, c), 0.0) for c in self.components
            )
            result[f"{uid}.inlet_{k}_total_flow_mol_s"] = F_in_k
        return result


# Species present in ideal_gas database
from pse_ecosystem.models.properties.ideal_gas import SHOMATE as _SHOMATE
_KNOWN_SPECIES = set(_SHOMATE.keys())
