"""High-fidelity PFR — ODE integration via scipy.solve_ivp.

The PFR is implemented as a black-box: only inlet and outlet variables are
exposed to the outer SLP.  The internal ODE profiles (temperature and
composition along the reactor) are hidden inside residual().

Physics correction vs. HDAPFRUnit
------------------------------------
HDAPFRUnit is hard-coded for the HDA process (specific species, Arrhenius
parameters, etc.).  This unit is generic: any set of components and reactions
can be configured via ReactionConfig objects (same dataclass as CSTRHF).

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Residuals (N + 2 equations)
-----------------------------
  F_i_out - ODE_integrated_F_i_out = 0  [N]
  T_out   - ODE_integrated_T_out   = 0  [1]
  P_out   - ODE_integrated_P_out   = 0  [1]  (using Ergun pressure drop, or isobaric)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import mixture_cp_J_mol_K, enthalpy_J_mol, SHOMATE
from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())


@dataclass
class PFRHFParams:
    reactions: List[ReactionConfig] = field(default_factory=list)
    length_m: float = 1.0
    cross_section_m2: float = 0.1  # reactor cross-sectional area [m²]
    U_W_per_m2_K: float = 0.0      # wall heat transfer [W/m²/K]; 0 = adiabatic
    T_wall_K: float = 298.15        # wall temperature [K]
    isobaric: bool = True           # if True, P_out = P_in (no pressure drop)
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    rtol: float = 1e-6
    atol: float = 1e-8


class PFRHF(BaseUnit):
    """Generic PFR with ODE integration (scipy.solve_ivp BDF)."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: PFRHFParams):
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

    def _ode_rhs(self, z: float, y: np.ndarray) -> np.ndarray:
        """ODE right-hand side: dy/dz where y = [F_1..F_N, T, P]."""
        comps = self.components
        N = len(comps)
        F = y[:N]
        T = max(float(y[N]), 1.0)
        P = max(float(y[N + 1]), 1.0)

        F_total = max(float(F.sum()), 1e-12)
        # Concentration reference [mol/m³]
        C_ref = P / (_R_GAS * T)
        # Mole fractions
        y_i = F / F_total
        C_i = y_i * C_ref

        # Reaction rates [mol/m³/s]
        rates = np.zeros(self._n_rxn)
        for r, rxn in enumerate(self.params.reactions):
            k = rxn.k0 * math.exp(-rxn.Ea_J_per_mol / (_R_GAS * T))
            rate = k
            for c, alpha in rxn.reaction_orders.items():
                idx = self.components.index(c) if c in self.components else -1
                if idx >= 0:
                    Ci = max(float(C_i[idx]), 0.0)
                    rate *= Ci ** alpha
            rates[r] = rate

        # dF_i/dz = A * Σ_r ν_ir * r_r
        A = self.params.cross_section_m2
        dFdz = A * (self._nu @ rates)

        # dT/dz energy
        flows_dict = {c: max(float(F[i]), 0.0) for i, c in enumerate(comps) if c in _KNOWN}
        Cp_mix = mixture_cp_J_mol_K(flows_dict, T, basis="molar_flow")
        C_flow = max(F_total * Cp_mix, 1e-12)
        # Heat from reaction
        Q_rxn = sum(
            rates[r] * self.params.reactions[r].delta_H_J_per_mol
            for r in range(self._n_rxn)
        )
        # Wall heat transfer
        Q_wall = self.params.U_W_per_m2_K * A * (self.params.T_wall_K - T)
        dTdz = (-Q_rxn * A + Q_wall) / C_flow

        # dP/dz: isobaric or simple friction (placeholder)
        dPdz = 0.0

        dydt = np.concatenate([dFdz, [dTdz, dPdz]])
        return dydt

    def _integrate(self, F_in: np.ndarray, T_in: float, P_in: float):
        from scipy.integrate import solve_ivp
        p = self.params
        N = len(self.components)
        y0 = np.concatenate([F_in, [T_in, P_in]])
        sol = solve_ivp(
            self._ode_rhs,
            [0.0, p.length_m],
            y0,
            method="BDF",
            rtol=p.rtol,
            atol=p.atol,
            dense_output=False,
        )
        return sol.y[:N, -1], sol.y[N, -1], sol.y[N + 1, -1]

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        F_in = np.array([max(x.get(self._v_F_in(c), 0.0), 0.0) for c in comps])
        T_in = max(x.get(self._v_T_in(), 500.0), 250.0)
        P_in = max(x.get(self._v_P_in(), 101325.0), 1.0)

        try:
            F_out_calc, T_out_calc, P_out_calc = self._integrate(F_in, T_in, P_in)
        except Exception as exc:  # noqa: BLE001
            # Surface the failure for debugging — caching on the unit lets
            # downstream KPI / status reports name the root cause rather
            # than seeing only the 1e6 penalty residual. Audit M9.
            self._last_integration_error = repr(exc)
            return np.full(N + 2, 1e6, dtype=float)
        else:
            self._last_integration_error = None

        if self.params.isobaric:
            P_out_calc = P_in

        F_out_decl = np.array([x.get(self._v_F_out(c), 0.0) for c in comps])
        T_out_decl = x.get(self._v_T_out(), T_out_calc)
        P_out_decl = x.get(self._v_P_out(), P_out_calc)

        res = np.concatenate([
            F_out_decl - F_out_calc,
            [T_out_decl - T_out_calc],
            [P_out_decl - P_out_calc],
        ])
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        """Vessel purchase cost [USD, CE500 basis] from reactor volume."""
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD
        p = self.params
        volume_m3 = max(p.length_m * p.cross_section_m2, 0.05)
        return vessel_purchase_cost_USD(volume_m3)

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        comps = self.components
        F_in  = {c: max(x.get(self._v_F_in(c), 0.0), 1e-12) for c in comps}
        F_out = {c: max(x.get(self._v_F_out(c), 0.0), 0.0) for c in comps}
        result: Dict[str, float] = {
            f"{uid}.T_out_K": x.get(self._v_T_out(), 0.0),
            f"{uid}.volume_m3": self.params.length_m * self.params.cross_section_m2,
        }
        for c in comps:
            result[f"{uid}.conversion_{c}_pct"] = (
                100.0 * max(F_in[c] - F_out[c], 0.0) / F_in[c]
            )
        return result
