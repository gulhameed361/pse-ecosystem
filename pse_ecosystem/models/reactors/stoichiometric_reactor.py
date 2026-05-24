"""Stoichiometric reactor (extent-of-reaction basis).

The simplest reactor model: component mole balances driven by reaction extents.
Linear when extents are free variables — the SLP driver short-circuits to a
single LP solve.

Ports
-----
inlet : StreamPort  (F_i_in, T_in, P_in)
outlet: StreamPort  (F_i_out, T_out, P_out)

Design variables (free in the LP)
----------------------------------
xi_r  : extent of reaction r  [mol/s]

Parameters (fixed at construction)
------------------------------------
stoichiometry : Dict[str, List[float]]  {species: [ν_1, ν_2, ...]}
    Positive = produced, negative = consumed.
xi_max_r : Optional[List[float]]
    Upper bounds on each extent [mol/s].  If None, derived from inlet feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


_R_GAS = 8.314462  # J/mol/K — needed for the τ-based volume estimate.


@dataclass
class StoichiometricParams:
    stoichiometry: Dict[str, List[float]]
    xi_max: Optional[List[float]] = None
    feed_max: float = 1e6  # mol/s upper bound for flow variables
    tau_s: float = 10.0
    """Notional residence time [s] used to back-out a vessel volume for the
    SSLW CAPEX correlation. Stoichiometric reactors carry no real volume in
    Aspen, but a 10 s placeholder lets techno-economic comparisons across
    reactor types stay meaningful."""


class StoichiometricReactor(BaseUnit):
    """Linear stoichiometric reactor with configurable reaction set."""

    is_linear = True

    def __init__(self, unit_id: str, components: List[str], params: StoichiometricParams):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        n_rxn = len(next(iter(params.stoichiometry.values())))
        self._n_rxn = n_rxn
        # Build stoichiometry matrix ν [N_comp × N_rxn]
        self._nu = np.array(
            [params.stoichiometry.get(c, [0.0] * n_rxn) for c in components],
            dtype=float,
        )
        self.inlet_port = StreamPort(unit_id, "inlet", components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    # ── Variable layout: F_i_in, T_in, P_in, F_i_out, T_out, P_out, xi_r ──

    def _v_F_in(self, c: str) -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self) -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self) -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self) -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self) -> str: return f"{self.unit_id}.outlet.P"
    def _v_xi(self, r: int) -> str: return f"{self.unit_id}.xi_{r}"

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
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for c in self.components:
            bds[self._v_F_in(c)] = (0.0, p.feed_max)
            bds[self._v_F_out(c)] = (0.0, p.feed_max)
        bds[self._v_T_in()] = (200.0, 2000.0)
        bds[self._v_P_in()] = (1e3, 1e7)
        bds[self._v_T_out()] = (200.0, 2000.0)
        bds[self._v_P_out()] = (1e3, 1e7)
        for r in range(self._n_rxn):
            xi_ub = p.xi_max[r] if p.xi_max and r < len(p.xi_max) else p.feed_max
            bds[self._v_xi(r)] = (0.0, xi_ub)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        N = len(self.components)
        res = np.zeros(N + 2, dtype=float)
        xi = np.array([x.get(self._v_xi(r), 0.0) for r in range(self._n_rxn)])
        for i, c in enumerate(self.components):
            F_in = x.get(self._v_F_in(c), 0.0)
            F_out = x.get(self._v_F_out(c), 0.0)
            # F_out - F_in - Σ_r ν_ir * xi_r = 0
            res[i] = F_out - F_in - float(self._nu[i] @ xi)
        # Temperature and pressure pass-through
        res[N] = x.get(self._v_T_out(), 0.0) - x.get(self._v_T_in(), 0.0)
        res[N + 1] = x.get(self._v_P_out(), 0.0) - x.get(self._v_P_in(), 0.0)
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        """Vessel purchase cost [USD, CE500 basis] from feed × τ vessel sizing."""
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD

        F_total = sum(
            max(x.get(self._v_F_in(c), 0.0), 0.0) for c in self.components
        )
        T = max(x.get(self._v_T_in(), 500.0), 273.0)
        P = max(x.get(self._v_P_in(), 101325.0), 1.0)
        Q_vol = max(F_total, 0.01) * _R_GAS * T / P
        volume_m3 = max(Q_vol * self.params.tau_s, 0.05)
        return vessel_purchase_cost_USD(volume_m3)

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        comps = self.components
        F_in = {c: max(x.get(self._v_F_in(c), 0.0), 1e-12) for c in comps}
        F_out = {c: max(x.get(self._v_F_out(c), 0.0), 0.0) for c in comps}
        result: Dict[str, float] = {}
        for r in range(self._n_rxn):
            result[f"{uid}.xi_{r}_mol_per_s"] = x.get(self._v_xi(r), 0.0)
        for c in comps:
            result[f"{uid}.conversion_{c}_pct"] = (
                100.0 * max(F_in[c] - F_out[c], 0.0) / F_in[c]
            )
        return result

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required vessel volume + L/D from feed × τ at inlet state."""
        import math as _math

        F_total = sum(
            max(x.get(self._v_F_in(c), 0.0), 0.0) for c in self.components
        )
        T = max(x.get(self._v_T_in(), 500.0), 273.0)
        P = max(x.get(self._v_P_in(), 101325.0), 1.0)
        tau_s = self.params.tau_s
        Q_vol = max(F_total, 0.01) * _R_GAS * T / P
        V_req = max(Q_vol * tau_s, 0.05)
        D = (2.0 * V_req / _math.pi) ** (1.0 / 3.0)
        return {
            "V_required_m3": V_req,
            "residence_time_s": tau_s,
            "L_over_D": 2.0,
            "diameter_m": D,
            "length_m": 2.0 * D,
        }

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Exact analytical Jacobian — unit is truly linear."""
        variables = self.variables()
        n = len(variables)
        x0 = np.array([guess.values.get(v, 0.0) for v in variables], dtype=float)
        f0 = np.asarray(self.residual(guess.values), dtype=float)
        N = len(self.components)
        m = f0.size  # N + 2

        J = np.zeros((m, n), dtype=float)
        var_idx = {v: i for i, v in enumerate(variables)}

        for i, c in enumerate(self.components):
            # ∂r_i / ∂F_out_c = +1
            J[i, var_idx[self._v_F_out(c)]] = 1.0
            # ∂r_i / ∂F_in_c = -1
            J[i, var_idx[self._v_F_in(c)]] = -1.0
            # ∂r_i / ∂xi_r = -ν_ir
            for r in range(self._n_rxn):
                J[i, var_idx[self._v_xi(r)]] = -self._nu[i, r]

        # T_out - T_in = 0
        J[N, var_idx[self._v_T_out()]] = 1.0
        J[N, var_idx[self._v_T_in()]] = -1.0
        # P_out - P_in = 0
        J[N + 1, var_idx[self._v_P_out()]] = 1.0
        J[N + 1, var_idx[self._v_P_in()]] = -1.0

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(guess.values),
            is_exact=True,
        )
