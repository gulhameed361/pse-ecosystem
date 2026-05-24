"""Gibbs free energy minimisation reactor.

Minimises the total Gibbs free energy subject to element balance constraints:
    min  G = Σ_i n_i * (μᵢ°(T) + R*T*ln(n_i*R*T/P))
    s.t. Σ_i a_ij * n_i = Σ_i a_ij * n_i_feed   for each element j
         n_i ≥ 0

where μᵢ°(T) = h_i°(T) - T*s_i°(T)  (chemical potential at standard state).

This is solved by scipy.optimize.minimize (SLSQP) internally.  The outer
residual is declared_outlet - Gibbs_solution.

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Residuals (N + 2)
------------------
  F_i_out - Gibbs_F_i = 0   [N]
  P_out   - P_in = 0        [1]
  T_out   - T_in = 0        [1]  (isothermal Gibbs by default)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, cp_J_mol_K, SHOMATE

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())

# Element composition matrix: {species: {element: count}}
_ELEMENT_COMP: Dict[str, Dict[str, int]] = {
    "H2":  {"H": 2},
    "O2":  {"O": 2},
    "N2":  {"N": 2},
    "CO":  {"C": 1, "O": 1},
    "CO2": {"C": 1, "O": 2},
    "CH4": {"C": 1, "H": 4},
    "H2O": {"H": 2, "O": 1},
}

# Standard entropy at 298.15 K [J/mol/K]  (NIST WebBook)
_S_REF_298: Dict[str, float] = {
    "H2": 130.68, "O2": 205.15, "N2": 191.61,
    "CO": 197.66, "CO2": 213.78, "CH4": 186.26, "H2O": 188.83,
}


@dataclass
class GibbsReactorParams:
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    max_inner_iter: int = 500
    inner_tol: float = 1e-8
    tau_s: float = 10.0
    """Notional residence time [s] used to back-out a vessel volume for the
    SSLW CAPEX correlation. Gibbs reactors are conceptual zero-time units in
    Aspen, but charging zero CAPEX is misleading for techno-economic
    comparisons — so we size the vessel from feed × τ at the inlet state."""


class GibbsReactor(BaseUnit):
    """Gibbs free energy minimisation reactor (SLSQP inner solve).

    **Isothermal only.** ``T_out`` is constrained to equal ``T_in`` (no
    energy balance, no heat duty Q). For adiabatic or with-Q operation use
    :class:`pse_ecosystem.models.reactors.EquilibriumReactor` instead, or
    pair this unit with an upstream/downstream heat exchanger to set T.
    Audit L8 clarification.
    """

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: Optional[GibbsReactorParams] = None):
        self.unit_id = unit_id
        self.components = [c for c in components if c in _KNOWN]
        self.params = params or GibbsReactorParams()
        self.inlet_port  = StreamPort(unit_id, "inlet",  components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, c: str)  -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self)          -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self)          -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self)         -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self)         -> str: return f"{self.unit_id}.outlet.P"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out()]
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
        return bds

    def _mu_std(self, c: str, T: float) -> float:
        """Standard chemical potential μ°(T) = H°(T) - T*S°(T)  [J/mol]."""
        H = enthalpy_J_mol(c, T)
        # Approximate S(T) ≈ S_ref + Cp_avg * ln(T/T_ref) (ideal gas entropy)
        S = _S_REF_298.get(c, 200.0) + cp_J_mol_K(c, 298.15) * math.log(T / 298.15)
        return H - T * S

    def _gibbs_solve(self, F_in: np.ndarray, T: float, P: float) -> np.ndarray:
        """SLSQP minimisation of Gibbs free energy.  Returns F_out [mol/s]."""
        from scipy.optimize import minimize, LinearConstraint

        N = len(self.components)
        comps = self.components
        mu_std = np.array([self._mu_std(c, T) for c in comps])

        # Build element balance constraint matrix A [E × N]
        elements = sorted({e for c in comps for e in _ELEMENT_COMP.get(c, {})})
        E = len(elements)
        A = np.zeros((E, N))
        for j, el in enumerate(elements):
            for i, c in enumerate(comps):
                A[j, i] = _ELEMENT_COMP.get(c, {}).get(el, 0)

        b = A @ F_in  # element balance RHS

        def G_func(n: np.ndarray) -> float:
            n_safe = np.maximum(n, 1e-30)
            n_total = n_safe.sum()
            G = float(np.dot(n_safe, mu_std))
            G += _R_GAS * T * float(np.dot(n_safe, np.log(n_safe * _R_GAS * T / P)))
            return G

        def G_grad(n: np.ndarray) -> np.ndarray:
            n_safe = np.maximum(n, 1e-30)
            return mu_std + _R_GAS * T * (np.log(n_safe * _R_GAS * T / P) + 1.0)

        n0 = np.maximum(F_in, 1e-6)
        bounds_sp = [(0.0, None)] * N
        # Element balance: A @ n == b
        constraints = [{"type": "eq", "fun": lambda n: A @ n - b, "jac": lambda n: A}]

        try:
            result = minimize(
                G_func,
                n0,
                jac=G_grad,
                method="SLSQP",
                bounds=bounds_sp,
                constraints=constraints,
                options={"maxiter": self.params.max_inner_iter, "ftol": self.params.inner_tol},
            )
            return np.maximum(result.x, 0.0)
        except Exception as exc:  # noqa: BLE001
            # v1.4.0 audit N10 — cache the failure reason on the unit so
            # downstream code (kpis(), the Streamlit Solver Monitor) can
            # surface that the Gibbs inner solve fell back to F_in instead
            # of silently returning physically-implausible state.
            self._last_inner_error = repr(exc)
            return F_in.copy()

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        F_in = np.array([max(x.get(self._v_F_in(c), 0.0), 0.0) for c in comps])
        T_in = x.get(self._v_T_in(), 800.0)
        P_in = max(x.get(self._v_P_in(), 101325.0), 1.0)

        F_gibbs = self._gibbs_solve(F_in, T_in, P_in)
        F_out_decl = np.array([x.get(self._v_F_out(c), 0.0) for c in comps])

        res = np.zeros(N + 2, dtype=float)
        res[:N] = F_out_decl - F_gibbs
        res[N]     = x.get(self._v_T_out(), 0.0) - T_in   # isothermal
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
        T = max(x.get(self._v_T_in(), 800.0), 273.0)
        P = max(x.get(self._v_P_in(), 101325.0), 1.0)
        Q_vol = max(F_total, 0.01) * _R_GAS * T / P
        volume_m3 = max(Q_vol * self.params.tau_s, 0.05)
        return vessel_purchase_cost_USD(volume_m3)

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        comps = self.components
        F_in = {c: max(x.get(self._v_F_in(c), 0.0), 1e-12) for c in comps}
        F_out = {c: max(x.get(self._v_F_out(c), 0.0), 0.0) for c in comps}
        result: Dict[str, float] = {
            f"{uid}.T_out_K": x.get(self._v_T_out(), 0.0),
        }
        for c in comps:
            result[f"{uid}.conversion_{c}_pct"] = (
                100.0 * max(F_in[c] - F_out[c], 0.0) / F_in[c]
            )
        return result

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required vessel volume + L/D from feed × τ at inlet state."""
        F_total = sum(
            max(x.get(self._v_F_in(c), 0.0), 0.0) for c in self.components
        )
        T = max(x.get(self._v_T_in(), 800.0), 273.0)
        P = max(x.get(self._v_P_in(), 101325.0), 1.0)
        tau_s = self.params.tau_s
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
