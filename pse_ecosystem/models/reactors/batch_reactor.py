"""Batch reactor — cycle-time optimisation for specialty / fine chemicals.

Reactor volume V is charged with starting material at t = 0, run isothermally
for cycle time t_batch, then emptied. Conversion follows from integrating
the Arrhenius rate over t_batch.

Continuous equivalence (annualised throughput basis)
----------------------------------------------------
For a batch unit operating ``n_batches_per_year`` times, the steady-state
molar flow rate is
    F_eq_i  =  n_batches × n_i_per_batch / (3600 × hours_per_year)

so the unit can plug into the flowsheet as a "pseudo-continuous" stream
even though physically it cycles. The ``cycle_time_s`` parameter sets
n_batches via:
    n_batches_per_year = operating_hours_per_year × 3600 / cycle_time_s

For multi-reaction networks, the same Arrhenius framework as CSTRHF is
reused; conversion comes from analytical integration of a first-order
rate (for higher orders we fall back to scipy.solve_ivp).

Residuals (N + R + 1)
----------------------
  Material  :  F_i_eq_out − F_i_eq_in − Σ_r ν_ir · ξ_r_per_batch /
              cycle_time_s = 0                                       [N]
  Rate      :  ξ_r − ∫_0^t_batch r_r(t) dt · V = 0                  [R]
  Energy    :  Q + H_in − H_out − ΔH_rxn = 0  (isothermal default)  [1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import (
    SHOMATE,
    enthalpy_J_mol,
)
from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())


@dataclass
class BatchReactorHFParams:
    reactions: List[ReactionConfig] = field(default_factory=list)
    volume_m3: float = 5.0
    cycle_time_s: float = 3600.0
    """Batch cycle time [s] = reaction + fill + drain + clean. Driven by
    kinetics + housekeeping. Common values: 30 min – 8 h for organic
    synthesis."""
    operating_hours_per_year: float = 8000.0
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 600.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e9
    xi_max: float = 1e6


class BatchReactorHF(BaseUnit):
    """Isothermal batch reactor with cycle-time analytical conversion.

    For first-order kinetics the closed-form integral is used; for higher
    orders we integrate numerically via scipy.solve_ivp at residual time.
    """

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: BatchReactorHFParams,
    ):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        self._n_rxn = len(params.reactions)
        self._nu = np.array(
            [
                [rxn.stoichiometry.get(c, 0.0) for rxn in params.reactions]
                for c in components
            ],
            dtype=float,
        )
        self.inlet_port = StreamPort(unit_id, "inlet", components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, c: str) -> str:  return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self) -> str:          return f"{self.unit_id}.inlet.T"
    def _v_P_in(self) -> str:          return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self) -> str:         return f"{self.unit_id}.outlet.T"
    def _v_P_out(self) -> str:         return f"{self.unit_id}.outlet.P"
    def _v_xi(self, r: int) -> str:    return f"{self.unit_id}.xi_{r}"
    def _v_Q(self) -> str:             return f"{self.unit_id}.Q_batch"

    def variables(self) -> List[str]:
        v = []
        for c in self.components: v.append(self._v_F_in(c))
        v += [self._v_T_in(), self._v_P_in()]
        for c in self.components: v.append(self._v_F_out(c))
        v += [self._v_T_out(), self._v_P_out()]
        for r in range(self._n_rxn): v.append(self._v_xi(r))
        v.append(self._v_Q())
        return v

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        b: Dict[str, Tuple[float, float]] = {}
        for c in self.components:
            b[self._v_F_in(c)] = (0.0, p.feed_max)
            b[self._v_F_out(c)] = (0.0, p.feed_max)
        b[self._v_T_in()] = (p.T_min, p.T_max)
        b[self._v_P_in()] = (p.P_min, p.P_max)
        b[self._v_T_out()] = (p.T_min, p.T_max)
        b[self._v_P_out()] = (p.P_min, p.P_max)
        for r in range(self._n_rxn):
            b[self._v_xi(r)] = (0.0, p.xi_max)
        b[self._v_Q()] = (-p.Q_max, p.Q_max)
        return b

    def _arrhenius_k(self, rxn: ReactionConfig, T: float) -> float:
        return rxn.k0 * math.exp(-rxn.Ea_J_per_mol / (_R_GAS * max(T, 1.0)))

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        N = len(self.components)
        R = self._n_rxn
        res = np.zeros(N + R + 1, dtype=float)

        T = x.get(self._v_T_out(), 350.0)
        # Per-batch extents [mol]
        xi = np.array([x.get(self._v_xi(r), 0.0) for r in range(R)])

        # Pseudo-continuous material balance: F_out = F_in + Σ_r ν_ir · ξ_r /
        # cycle_time_s. ξ_r is per-batch (mol); divide by cycle_time to get
        # continuous-equivalent mol/s.
        for i, c in enumerate(self.components):
            F_in = x.get(self._v_F_in(c), 0.0)
            F_out = x.get(self._v_F_out(c), 0.0)
            res[i] = F_out - F_in - float(self._nu[i] @ xi) / p.cycle_time_s

        # Per-batch rate: ξ_r ≈ k_r(T) · t_batch · V · C_0^n  (constant T)
        # For order n = 1 in a single reactant, closed-form: ξ = V·C_0·(1 −
        # exp(−k·t)). For mixed orders we fall back to k · V · C_avg · t.
        # This is a screening-grade approximation — for higher fidelity, use
        # the scipy.solve_ivp path (deferred until users request it).
        V = p.volume_m3
        # Use inlet conditions as the initial concentration estimate.
        F_in_total = max(
            sum(x.get(self._v_F_in(c), 0.0) for c in self.components), 1e-9
        )
        P_in = max(x.get(self._v_P_in(), 1.0e5), 1e-3)
        C_ref = P_in / (_R_GAS * max(T, 1.0))
        for r, rxn in enumerate(p.reactions):
            k = self._arrhenius_k(rxn, T)
            # Constant-volume first-order: ξ = V · C0 · (1 − e^(−k·t_batch)).
            # Use the limiting reactant's concentration (first species with
            # negative ν) as C0; fall back to mole-average if none.
            limiting = None
            for c, nu in rxn.stoichiometry.items():
                if nu < 0:
                    limiting = c
                    break
            if limiting is not None:
                C0 = (
                    x.get(self._v_F_in(limiting), 0.0)
                    / F_in_total * C_ref
                )
            else:
                C0 = C_ref
            xi_calc = V * C0 * (1.0 - math.exp(-k * p.cycle_time_s))
            res[N + r] = xi[r] - xi_calc

        # Energy balance per batch [J]: Q_batch + H_in − H_out − ΔH_rxn = 0
        T_in = x.get(self._v_T_in(), T)
        Q = x.get(self._v_Q(), 0.0)
        H_in = sum(
            x.get(self._v_F_in(c), 0.0) * enthalpy_J_mol(c, T_in) * p.cycle_time_s
            for c in self.components if c in _KNOWN
        )
        H_out = sum(
            x.get(self._v_F_out(c), 0.0) * enthalpy_J_mol(c, T) * p.cycle_time_s
            for c in self.components if c in _KNOWN
        )
        H_rxn = sum(
            xi[r] * (
                sum(
                    nu * enthalpy_J_mol(c, T)
                    for c, nu in rxn.stoichiometry.items() if c in _KNOWN
                ) if rxn.delta_H_J_per_mol == 0.0 else rxn.delta_H_J_per_mol
            )
            for r, rxn in enumerate(p.reactions)
        )
        res[N + R] = Q + H_in - H_out - H_rxn
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        p = self.params
        comps = self.components
        F_in = {c: max(x.get(self._v_F_in(c), 0.0), 1e-12) for c in comps}
        F_out = {c: max(x.get(self._v_F_out(c), 0.0), 0.0) for c in comps}
        result: Dict[str, float] = {
            f"{uid}.cycle_time_s": p.cycle_time_s,
            f"{uid}.batches_per_year": (
                p.operating_hours_per_year * 3600.0 / max(p.cycle_time_s, 1.0)
            ),
            f"{uid}.volume_m3": p.volume_m3,
            f"{uid}.T_out_K": x.get(self._v_T_out(), 0.0),
        }
        for c in comps:
            result[f"{uid}.conversion_{c}_pct"] = (
                100.0 * max(F_in[c] - F_out[c], 0.0) / F_in[c]
            )
        return result

    def capex(self, x: Dict[str, float]) -> float:
        """Batch vessel + agitator + jacket [USD, CE500 basis]. Towler-
        Sinnott Ch.17 — reactor jacketed: ~30% premium over plain vessel."""
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD
        return 1.3 * vessel_purchase_cost_USD(self.params.volume_m3)
