"""Equilibrium reactor — van't Hoff Keq with Newton inner solve.

For each reaction r, the thermodynamic equilibrium constant is:
    Keq_r(T) = Keq_ref * exp(-ΔH_rxn_r / R * (1/T - 1/T_ref))

Equilibrium condition (gas phase, concentration basis):
    Keq_r - Π_i (F_i_out / F_total)^ν_ir = 0

The extent of reaction xi_r that satisfies this is found by a Newton inner
solve.  The outer residual links declared outlet flows to the inner solution.

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Additional variable: Q [W]

Residuals (N + 2)
------------------
  Material : F_i_out - F_i_in - Σ_r ν_ir * xi_r = 0  [N]  (xi from inner Newton)
  Energy   : Q + H_in - H_out = 0                     [1]
  Pressure : P_out - P_in = 0                         [1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, SHOMATE
from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())


@dataclass
class EquilReactorParams:
    reactions: List[ReactionConfig] = field(default_factory=list)
    Keq_ref: List[float] = field(default_factory=list)  # Keq at T_ref for each rxn
    T_ref_K: float = 298.15
    max_inner_iter: int = 50
    inner_tol: float = 1e-8
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e9


class EquilibriumReactor(BaseUnit):
    """Equilibrium reactor using van't Hoff Keq and Newton inner solve."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: EquilReactorParams):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        self._n_rxn = len(params.reactions)
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
    def _v_Q(self)             -> str: return f"{self.unit_id}.Q"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out(), self._v_Q()]
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
        bds[self._v_Q()]     = (-p.Q_max, p.Q_max)
        return bds

    def _Keq(self, rxn_idx: int, T: float) -> float:
        p = self.params
        rxn = p.reactions[rxn_idx]
        Keq_ref = p.Keq_ref[rxn_idx] if rxn_idx < len(p.Keq_ref) else 1.0
        dH = rxn.delta_H_J_per_mol
        if dH == 0.0:
            dH = sum(
                nu * enthalpy_J_mol(c, p.T_ref_K)
                for c, nu in rxn.stoichiometry.items()
                if c in _KNOWN
            )
        exponent = -dH / _R_GAS * (1.0 / max(T, 1.0) - 1.0 / p.T_ref_K)
        return Keq_ref * math.exp(exponent)

    def _inner_solve(self, F_in: np.ndarray, T: float) -> np.ndarray:
        """Newton-Raphson for extents xi [mol/s] to meet equilibrium."""
        p = self.params
        R = self._n_rxn
        xi = np.zeros(R)

        for _ in range(p.max_inner_iter):
            F_out = F_in + self._nu @ xi
            F_out = np.maximum(F_out, 1e-12)
            F_total = F_out.sum()
            x_mole = F_out / F_total

            g = np.zeros(R)
            prod_baseline = np.ones(R)  # Π x_i^ν per reaction at the current iterate
            for r in range(R):
                Keq_r = self._Keq(r, T)
                prod = 1.0
                for i, c in enumerate(self.components):
                    nu_ir = self._nu[i, r]
                    if nu_ir != 0.0:
                        prod *= max(float(x_mole[i]), 1e-30) ** nu_ir
                prod_baseline[r] = prod
                g[r] = prod - Keq_r

            if np.max(np.abs(g)) < p.inner_tol:
                break

            # Numerical Jacobian for Newton step
            eps = 1e-6
            Jac = np.zeros((R, R))
            for j in range(R):
                xi_p = xi.copy()
                xi_p[j] += eps
                F_p = np.maximum(F_in + self._nu @ xi_p, 1e-12)
                x_p = F_p / F_p.sum()
                for r in range(R):
                    prod_p = 1.0
                    for i in range(len(self.components)):
                        nu_ir = self._nu[i, r]
                        if nu_ir != 0.0:
                            prod_p *= max(float(x_p[i]), 1e-30) ** nu_ir
                    # Forward difference of g[r] = Π x_i^ν − Keq_r (Keq_r is constant
                    # in xi), so dg[r]/dxi_j = (prod_p − prod_baseline[r]) / eps.
                    Jac[r, j] = (prod_p - prod_baseline[r]) / eps

            try:
                dxi = np.linalg.solve(Jac + 1e-10 * np.eye(R), -g)
                xi = xi + 0.5 * dxi  # damped Newton step
            except np.linalg.LinAlgError:
                break

        return xi

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        F_in = np.array([x.get(self._v_F_in(c), 0.0) for c in comps])
        T_in = x.get(self._v_T_in(), 500.0)
        T_out = x.get(self._v_T_out(), 500.0)

        # Inner solve at T_out
        xi = self._inner_solve(F_in, T_out)
        F_out_calc = np.maximum(F_in + self._nu @ xi, 0.0)

        F_out_decl = np.array([x.get(self._v_F_out(c), 0.0) for c in comps])

        res = np.zeros(N + 2, dtype=float)
        res[:N] = F_out_decl - F_out_calc

        Q = x.get(self._v_Q(), 0.0)
        H_in  = sum(F_in[i]  * enthalpy_J_mol(c, T_in)  for i, c in enumerate(comps) if c in _KNOWN)
        H_out = sum(F_out_calc[i] * enthalpy_J_mol(c, T_out) for i, c in enumerate(comps) if c in _KNOWN)
        res[N] = Q + H_in - H_out

        res[N + 1] = x.get(self._v_P_out(), 0.0) - x.get(self._v_P_in(), 0.0)
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        """Vessel purchase cost [USD, CE500 basis]."""
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD
        F_total = sum(
            max(x.get(self._v_F_in(c), 0.0), 0.0) for c in self.components
        )
        T = max(x.get(self._v_T_in(), 500.0), 273.0)
        P = max(x.get(self._v_P_in(), 101325.0), 1.0)
        tau_s = 10.0   # 10 s residence time
        Q_vol = max(F_total, 0.01) * _R_GAS * T / P
        volume_m3 = max(Q_vol * tau_s, 0.05)
        return vessel_purchase_cost_USD(volume_m3)

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required vessel volume + L/D from feed × τ at inlet state."""
        F_total = sum(
            max(x.get(self._v_F_in(c), 0.0), 0.0) for c in self.components
        )
        T = max(x.get(self._v_T_in(), 500.0), 273.0)
        P = max(x.get(self._v_P_in(), 101325.0), 1.0)
        tau_s = 10.0
        Q_vol = max(F_total, 0.01) * _R_GAS * T / P
        V_req = max(Q_vol * tau_s, 0.05)
        D = (2.0 * V_req / math.pi) ** (1.0 / 3.0)
        return {
            "V_required_m3": V_req,
            "residence_time_s": tau_s,
            "L_over_D": 2.0,
            "diameter_m": D,
            "length_m": 2.0 * D,
        }

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        Q = x.get(self._v_Q(), 0.0)
        comps = self.components
        F_in  = {c: max(x.get(self._v_F_in(c), 0.0), 1e-12) for c in comps}
        F_out = {c: max(x.get(self._v_F_out(c), 0.0), 0.0) for c in comps}
        result: Dict[str, float] = {
            f"{uid}.Q_duty_W": Q,
            f"{uid}.T_out_K": x.get(self._v_T_out(), 0.0),
        }
        for c in comps:
            result[f"{uid}.conversion_{c}_pct"] = (
                100.0 * max(F_in[c] - F_out[c], 0.0) / F_in[c]
            )
        return result
