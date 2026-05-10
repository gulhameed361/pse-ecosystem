"""High-fidelity CSTR with Arrhenius kinetics and energy balance.

Physics correction vs. CSTRToy
--------------------------------
CSTRToy uses a bilinear rate expression (V × F_out) without temperature
dependence. This unit uses Arrhenius kinetics:
    r_r = k0_r * exp(-Ea_r / (R * T_out)) * V * Π_i (C_i)^α_ir
where C_i = F_i_out / (F_total_out * R_gas * T_out / P_out)  [mol/m³]
and a full ideal-gas energy balance including heat of reaction.

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Additional variables
---------------------
xi_r  : extent of reaction r [mol/s]   (= r_r * V)
Q     : heat duty [W]  (positive = heat added to reactor)

Residuals (N + R + 2 equations)
---------------------------------
  Material : F_i_out - F_i_in - Σ_r ν_ir * xi_r = 0             [N]
  Rate     : xi_r - k0_r * exp(-Ea_r/RT) * V * Π(C_j^α_jr) = 0 [R]
  Energy   : Q + Σ F_i_in*h_i(T_in) - Σ F_i_out*h_i(T_out)
             - Σ_r xi_r * ΔH_rxn_r(T_out) = 0                   [1]
  Pressure : P_out - P_in = 0                                     [1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, SHOMATE

_R_GAS = 8.314462  # J/mol/K
_KNOWN = set(SHOMATE.keys())


@dataclass
class ReactionConfig:
    """Single reaction specification for the CSTR."""
    stoichiometry: Dict[str, float]    # {species: ν}, positive = product
    k0: float                          # pre-exponential factor [mol/m³/s]
    Ea_J_per_mol: float                # activation energy [J/mol]
    reaction_orders: Dict[str, float]  # {species: α} (default: |ν| for reactants)
    delta_H_J_per_mol: float = 0.0     # heat of reaction [J/mol extent]; auto if 0
    name: str = "rxn"


@dataclass
class CSTRHFParams:
    reactions: List[ReactionConfig] = field(default_factory=list)
    volume_m3: float = 1.0
    feed_max: float = 1e4    # mol/s
    T_min: float = 250.0
    T_max: float = 1500.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e9
    xi_max: float = 1e4      # mol/s per reaction extent


class CSTRHF(BaseUnit):
    """Multi-component CSTR with Arrhenius kinetics and ideal-gas energy balance."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: CSTRHFParams):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        self._n_rxn = len(params.reactions)
        # Build stoichiometry matrix [N × R]
        self._nu = np.array(
            [[rxn.stoichiometry.get(c, 0.0) for rxn in params.reactions]
             for c in components],
            dtype=float,
        )
        self.inlet_port  = StreamPort(unit_id, "inlet",  components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, c: str)  -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self)          -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self)          -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self)         -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self)         -> str: return f"{self.unit_id}.outlet.P"
    def _v_xi(self, r: int)    -> str: return f"{self.unit_id}.xi_{r}"
    def _v_Q(self)             -> str: return f"{self.unit_id}.Q"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out()]
        for r in range(self._n_rxn):
            vlist.append(self._v_xi(r))
        vlist.append(self._v_Q())
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
        bds[self._v_P_out()] = (p.P_min, p.P_max)
        for r in range(self._n_rxn):
            bds[self._v_xi(r)] = (0.0, p.xi_max)
        bds[self._v_Q()] = (-p.Q_max, p.Q_max)
        return bds

    def _arrhenius_rate(self, rxn: ReactionConfig, T_out: float, x: Dict[str, float]) -> float:
        """Volumetric rate [mol/m³/s] = k0 * exp(-Ea/RT) * Π C_j^α_j."""
        k = rxn.k0 * math.exp(-rxn.Ea_J_per_mol / (_R_GAS * max(T_out, 1.0)))
        P_out = x.get(self._v_P_out(), 101325.0)
        F_total_out = max(sum(x.get(self._v_F_out(c), 0.0) for c in self.components), 1e-12)
        # Ideal gas: C_i = n_i/V, but for rate use concentration at outlet
        # C_i [mol/m³] = F_i_out * P_out / (F_total_out * R * T_out)
        # so concentration is consistent with ideal gas law
        C_ref = P_out / (_R_GAS * max(T_out, 1.0))  # total molar concentration [mol/m³]
        rate = k
        for c, alpha in rxn.reaction_orders.items():
            x_i = x.get(self._v_F_out(c), 0.0) / F_total_out  # mole fraction
            C_i = x_i * C_ref
            rate *= max(C_i, 1e-30) ** alpha
        return rate

    def _delta_H_rxn(self, rxn: ReactionConfig, T_out: float) -> float:
        """Heat of reaction [J/mol extent] at T_out.  Uses H_f° if delta_H == 0."""
        if rxn.delta_H_J_per_mol != 0.0:
            return rxn.delta_H_J_per_mol
        # Compute from stoichiometry and formation enthalpies
        dH = 0.0
        for c, nu in rxn.stoichiometry.items():
            if c in _KNOWN:
                dH += nu * enthalpy_J_mol(c, T_out)
        return dH

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        R = self._n_rxn
        res = np.zeros(N + R + 2, dtype=float)

        T_out = x.get(self._v_T_out(), 500.0)
        xi = np.array([x.get(self._v_xi(r), 0.0) for r in range(R)])

        # Material balances [N]
        for i, c in enumerate(comps):
            F_in  = x.get(self._v_F_in(c), 0.0)
            F_out = x.get(self._v_F_out(c), 0.0)
            res[i] = F_out - F_in - float(self._nu[i] @ xi)

        # Rate residuals: xi_r - rate_r * V = 0  [R]
        V = self.params.volume_m3
        for r, rxn in enumerate(self.params.reactions):
            rate_r = self._arrhenius_rate(rxn, T_out, x)
            res[N + r] = xi[r] - rate_r * V

        # Energy balance [1]
        T_in = x.get(self._v_T_in(), 298.15)
        Q    = x.get(self._v_Q(), 0.0)
        H_in  = sum(x.get(self._v_F_in(c), 0.0)  * enthalpy_J_mol(c, T_in)  for c in comps if c in _KNOWN)
        H_out = sum(x.get(self._v_F_out(c), 0.0) * enthalpy_J_mol(c, T_out) for c in comps if c in _KNOWN)
        H_rxn = sum(xi[r] * self._delta_H_rxn(rxn, T_out) for r, rxn in enumerate(self.params.reactions))
        res[N + R] = Q + H_in - H_out - H_rxn

        # Pressure [1]
        res[N + R + 1] = x.get(self._v_P_out(), 0.0) - x.get(self._v_P_in(), 0.0)

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        from pse_ecosystem.models.costing.sslw_costing import cstr_purchase_cost_USD
        V = self.params.volume_m3
        capex_v = cstr_purchase_cost_USD(V)
        return {
            "capex_USD": capex_v,
            "opex_USD_per_yr": self.opex_per_year(x),
            "Q_W": x.get(self._v_Q(), 0.0),
            "volume_m3": V,
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import cstr_purchase_cost_USD
        return cstr_purchase_cost_USD(self.params.volume_m3)
