"""NTU-effectiveness heat exchanger (counter-current, ideal gases).

Physics
-------
C_hot  = F_hot * Cp_hot(T_avg_hot)
C_cold = F_cold * Cp_cold(T_avg_cold)
C_min  = min(C_hot, C_cold)  [evaluated at linearisation point for SLP]
C_star = C_min / C_max

Counter-current effectiveness:
    ε = (1 - exp(-NTU*(1-C*))) / (1 - C*·exp(-NTU*(1-C*)))
    (degenerate when C* → 1: ε = NTU/(1+NTU))

Q = ε * C_min * (T_hot_in - T_cold_in)

Residuals (5 equations)
-------------------------
  Hot energy  : Q - C_hot * (T_hot_in  - T_hot_out)  = 0  [1]
  Cold energy : Q - C_cold * (T_cold_out - T_cold_in) = 0  [1]
  Effectiveness: ε - ε_NTU(NTU, C*) = 0                   [1]
  Heat duty   : Q - ε * C_min * (T_hot_in - T_cold_in) = 0 [1]
  NTU def     : NTU - U_A / C_min = 0                      [1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import (
    cp_J_mol_K, dcp_dT_J_mol_K2, mixture_cp_J_mol_K, SHOMATE,
)

_KNOWN = set(SHOMATE.keys())


@dataclass
class HeatExchangerNTUParams:
    UA_W_per_K: float = 1000.0        # operating UA [W/K] (already includes fouling)
    flow_arrangement: str = "counter" # 'counter' or 'parallel'
    hot_species: Optional[List[str]] = None    # subset of hot components for Cp
    cold_species: Optional[List[str]] = None
    U_clean_W_per_m2_K: float = 500.0
    """Clean-condition overall HT coefficient [W/m²/K] used to back out the
    physical area required to deliver ``UA_W_per_K`` once fouling is included.
    Affects CAPEX only; the residual still uses ``UA_W_per_K`` as the
    operating value."""
    R_f_tube_m2K_per_W: float = 0.0
    """Tube-side fouling resistance [m²·K/W] used in the area back-out."""
    R_f_shell_m2K_per_W: float = 0.0
    feed_max: float = 1e4
    T_min: float = 200.0
    T_max: float = 2000.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e10

    def heat_transfer_area_m2(self) -> float:
        """Physical area [m²] needed to deliver ``UA_W_per_K`` once fouling
        is included: A = UA · (1/U_clean + R_f_tube + R_f_shell). With both
        ``R_f``'s zero this reduces to UA / U_clean, matching v1.5.3."""
        return self.UA_W_per_K * (
            1.0 / max(self.U_clean_W_per_m2_K, 1e-9)
            + self.R_f_tube_m2K_per_W
            + self.R_f_shell_m2K_per_W
        )


class HeatExchangerNTU(BaseUnit):
    """Counter-current NTU-effectiveness heat exchanger."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        hot_components: List[str],
        cold_components: List[str],
        params: Optional[HeatExchangerNTUParams] = None,
    ):
        self.unit_id = unit_id
        self.hot_components  = list(hot_components)
        self.cold_components = list(cold_components)
        self.params = params or HeatExchangerNTUParams()
        self.hot_inlet_port   = StreamPort(unit_id, "hot_in",   hot_components)
        self.hot_outlet_port  = StreamPort(unit_id, "hot_out",  hot_components)
        self.cold_inlet_port  = StreamPort(unit_id, "cold_in",  cold_components)
        self.cold_outlet_port = StreamPort(unit_id, "cold_out", cold_components)

    def _v(self, tag: str, c: str) -> str: return f"{self.unit_id}.{tag}.F_{c}"
    def _vT(self, tag: str)        -> str: return f"{self.unit_id}.{tag}.T"
    def _vP(self, tag: str)        -> str: return f"{self.unit_id}.{tag}.P"
    def _v_Q(self)                 -> str: return f"{self.unit_id}.Q"
    def _v_eps(self)               -> str: return f"{self.unit_id}.effectiveness"
    def _v_NTU(self)               -> str: return f"{self.unit_id}.NTU"

    def variables(self) -> List[str]:
        vlist = []
        for tag, comps in [("hot_in", self.hot_components), ("hot_out", self.hot_components),
                            ("cold_in", self.cold_components), ("cold_out", self.cold_components)]:
            for c in comps:
                vlist.append(self._v(tag, c))
            vlist += [self._vT(tag), self._vP(tag)]
        vlist += [self._v_Q(), self._v_eps(), self._v_NTU()]
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
        bds[self._v_Q()]   = (0.0, p.Q_max)
        bds[self._v_eps()] = (0.0, 1.0)
        bds[self._v_NTU()] = (0.0, 50.0)
        return bds

    def _C_hot_cold(self, x: Dict[str, float]) -> Tuple[float, float]:
        """Return (C_hot, C_cold) [W/K] at current x."""
        T_hi = x.get(self._vT("hot_in"), 500.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        T_co = x.get(self._vT("cold_out"), 350.0)

        flows_hot  = {c: x.get(self._v("hot_in", c), 0.0) for c in self.hot_components  if c in _KNOWN}
        flows_cold = {c: x.get(self._v("cold_in", c), 0.0) for c in self.cold_components if c in _KNOWN}

        Cp_hot  = mixture_cp_J_mol_K(flows_hot,  0.5*(T_hi+T_ho), basis="molar_flow")
        Cp_cold = mixture_cp_J_mol_K(flows_cold, 0.5*(T_ci+T_co), basis="molar_flow")
        C_hot  = sum(flows_hot.values())  * Cp_hot
        C_cold = sum(flows_cold.values()) * Cp_cold
        return C_hot, C_cold

    @staticmethod
    def _eps_from_NTU(NTU: float, C_star: float) -> float:
        if C_star >= 1.0 - 1e-6:
            eps = NTU / (1.0 + NTU)  # degenerate balanced case
        else:
            # Clamp the exponent argument to keep math.exp() in range. For very
            # effective exchangers the (-NTU*(1-C*)) magnitude can grow without
            # bound; once it exceeds ~700 the result saturates to 0 anyway, so
            # capping at 700 avoids spurious OverflowError without affecting
            # downstream numerics.
            arg = -NTU * (1.0 - C_star)
            arg = max(min(arg, 700.0), -700.0)
            e = math.exp(arg)
            eps = (1.0 - e) / (1.0 - C_star * e)
        # Clamp to [0, 1] — numerical noise near balanced-flow (C_star ≈ 1)
        # or near-zero NTU can push effectiveness slightly outside the
        # physically valid range, which would propagate to negative Q.
        return max(0.0, min(eps, 1.0))

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        T_hi = x.get(self._vT("hot_in"),  500.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        T_co = x.get(self._vT("cold_out"),350.0)
        Q    = x.get(self._v_Q(), 0.0)
        eps  = x.get(self._v_eps(), 0.5)
        NTU  = x.get(self._v_NTU(), 2.0)

        C_hot, C_cold = self._C_hot_cold(x)
        C_min = min(C_hot, C_cold)
        C_max = max(C_hot, C_cold)
        C_min = max(C_min, 1e-12)
        C_max = max(C_max, 1e-12)
        C_star = C_min / C_max

        UA = self.params.UA_W_per_K

        res = np.zeros(5, dtype=float)
        res[0] = Q - C_hot * (T_hi - T_ho)                              # hot energy
        res[1] = Q - C_cold * (T_co - T_ci)                             # cold energy
        res[2] = eps - self._eps_from_NTU(NTU, C_star)                  # ε-NTU relation
        res[3] = Q - eps * C_min * (T_hi - T_ci)                        # Q = ε*C_min*ΔT_max
        res[4] = NTU - UA / C_min                                        # NTU definition
        return res

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Closed-form Jacobian for the (5) residuals.

        With ``C_hot = Σ_i F_hot_in_i · Cp_i(T_avg_hot)`` (and likewise for
        cold) — that's exactly what ``mixture_cp × F_total`` reduces to —
        the algebraic structure is closed-form. The only non-trivial chain
        is through the Shomate polynomial ``dCp/dT`` (via
        :func:`~pse_ecosystem.models.properties.ideal_gas.dcp_dT_J_mol_K2`).

        Rows::

            0: r0 = Q − C_hot · (T_hi − T_ho)
            1: r1 = Q − C_cold · (T_co − T_ci)
            2: r2 = ε − ε_NTU(NTU, C*)
            3: r3 = Q − ε · C_min · (T_hi − T_ci)
            4: r4 = NTU − UA / C_min

        ``C_min`` / ``C_max`` ownership is frozen at the linearisation
        point (we record which side is min/max at x₀ and keep that for
        the derivative). This is identical to the FD scheme, which also
        sees discrete switching across the C_hot = C_cold knife-edge.

        Validated against the central-difference reference in
        ``tests/test_analytical_jacobians.py::TestHXNTUAnalyticalJacobian``
        at the same 1e-5 rel / 1e-6 abs tolerance as :class:`CSTRHF`.
        """
        variables = self.variables()
        n = len(variables)
        vidx = {v: i for i, v in enumerate(variables)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)
        f0 = np.asarray(self.residual(x0_dict), dtype=float).reshape(-1)
        m = f0.size  # = 5
        J = np.zeros((m, n), dtype=float)

        T_hi = x0_dict.get(self._vT("hot_in"),  500.0)
        T_ho = x0_dict.get(self._vT("hot_out"), 400.0)
        T_ci = x0_dict.get(self._vT("cold_in"), 300.0)
        T_co = x0_dict.get(self._vT("cold_out"), 350.0)
        NTU  = x0_dict.get(self._v_NTU(), 2.0)
        eps  = x0_dict.get(self._v_eps(), 0.5)

        T_avg_h = 0.5 * (T_hi + T_ho)
        T_avg_c = 0.5 * (T_ci + T_co)

        # Pre-compute per-species Cp and dCp/dT at the average T of each side.
        cp_hot = {c: cp_J_mol_K(c, T_avg_h) for c in self.hot_components if c in _KNOWN}
        cp_cold = {c: cp_J_mol_K(c, T_avg_c) for c in self.cold_components if c in _KNOWN}
        dcp_hot = {c: dcp_dT_J_mol_K2(c, T_avg_h) for c in self.hot_components if c in _KNOWN}
        dcp_cold = {c: dcp_dT_J_mol_K2(c, T_avg_c) for c in self.cold_components if c in _KNOWN}

        flows_h = {c: x0_dict.get(self._v("hot_in", c), 0.0) for c in self.hot_components if c in _KNOWN}
        flows_c = {c: x0_dict.get(self._v("cold_in", c), 0.0) for c in self.cold_components if c in _KNOWN}

        C_hot = sum(flows_h[c] * cp_hot[c] for c in flows_h)
        C_cold = sum(flows_c[c] * cp_cold[c] for c in flows_c)
        # d C / dT_in == d C / dT_out == 0.5 · Σ F_i · dCp_i/dT  (chain via T_avg)
        dC_hot_dT_either = 0.5 * sum(flows_h[c] * dcp_hot[c] for c in flows_h)
        dC_cold_dT_either = 0.5 * sum(flows_c[c] * dcp_cold[c] for c in flows_c)

        hot_is_min = C_hot <= C_cold
        C_min = C_hot if hot_is_min else C_cold
        C_max = C_cold if hot_is_min else C_hot
        C_min_safe = max(C_min, 1e-12)
        C_max_safe = max(C_max, 1e-12)
        C_star = C_min_safe / C_max_safe
        UA = self.params.UA_W_per_K

        # ── Row 0: r0 = Q − C_hot · (T_hi − T_ho) ───────────────────────────
        dT_h = T_hi - T_ho
        J[0, vidx[self._v_Q()]] = 1.0
        for c in flows_h:
            J[0, vidx[self._v("hot_in", c)]] = -cp_hot[c] * dT_h
        J[0, vidx[self._vT("hot_in")]]  = -dC_hot_dT_either * dT_h - C_hot
        J[0, vidx[self._vT("hot_out")]] = -dC_hot_dT_either * dT_h + C_hot

        # ── Row 1: r1 = Q − C_cold · (T_co − T_ci) ──────────────────────────
        dT_c = T_co - T_ci
        J[1, vidx[self._v_Q()]] = 1.0
        for c in flows_c:
            J[1, vidx[self._v("cold_in", c)]] = -cp_cold[c] * dT_c
        J[1, vidx[self._vT("cold_in")]]  = -dC_cold_dT_either * dT_c + C_cold
        J[1, vidx[self._vT("cold_out")]] = -dC_cold_dT_either * dT_c - C_cold

        # ── Row 2: r2 = ε − ε_NTU(NTU, C*) ──────────────────────────────────
        # ε_NTU = (1 − e) / (1 − C*·e), with e = exp(−NTU·(1−C*))
        # ∂ε/∂NTU = (1−C*)² · e / (1 − C*·e)²
        # ∂ε/∂C*  = e · [−NTU·(1 − C*·e) + (1 − e)·(1 + C*·NTU)] / (1 − C*·e)²
        # Balanced (C* → 1):  ε = NTU/(1+NTU), ∂ε/∂NTU = 1/(1+NTU)²,
        #                      ∂ε/∂C* ≈ 0 (smooth limit).
        J[2, vidx[self._v_eps()]] = 1.0
        if C_star >= 1.0 - 1e-6:
            deps_dNTU = 1.0 / (1.0 + NTU) ** 2
            deps_dCstar = 0.0
        else:
            arg = -NTU * (1.0 - C_star)
            arg = max(min(arg, 700.0), -700.0)
            e = math.exp(arg)
            denom = (1.0 - C_star * e) ** 2
            deps_dNTU = ((1.0 - C_star) ** 2) * e / denom
            deps_dCstar = e * (-NTU * (1.0 - C_star * e) + (1.0 - e) * (1.0 + C_star * NTU)) / denom
        J[2, vidx[self._v_NTU()]] = -deps_dNTU
        # C* depends on C_min and C_max. dC*/dC_min = 1/C_max; dC*/dC_max = -C_min/C_max²
        dCstar_dCmin = 1.0 / C_max_safe
        dCstar_dCmax = -C_min_safe / (C_max_safe ** 2)
        # And C_min / C_max each chain to F_in's and T's via the side they own.
        # Helper to scatter dC/dvars of a side into row 2:
        def _scatter_dCstar_term(scale, flows_dict, cp_dict, dC_dT_either, tag, T_in_tag, T_out_tag):
            for c, F in flows_dict.items():
                J[2, vidx[self._v(tag, c)]] += scale * cp_dict[c]
            J[2, vidx[self._vT(T_in_tag)]] += scale * dC_dT_either
            J[2, vidx[self._vT(T_out_tag)]] += scale * dC_dT_either
        if hot_is_min:
            _scatter_dCstar_term(-deps_dCstar * dCstar_dCmin,
                                  flows_h, cp_hot, dC_hot_dT_either,
                                  "hot_in", "hot_in", "hot_out")
            _scatter_dCstar_term(-deps_dCstar * dCstar_dCmax,
                                  flows_c, cp_cold, dC_cold_dT_either,
                                  "cold_in", "cold_in", "cold_out")
        else:
            _scatter_dCstar_term(-deps_dCstar * dCstar_dCmin,
                                  flows_c, cp_cold, dC_cold_dT_either,
                                  "cold_in", "cold_in", "cold_out")
            _scatter_dCstar_term(-deps_dCstar * dCstar_dCmax,
                                  flows_h, cp_hot, dC_hot_dT_either,
                                  "hot_in", "hot_in", "hot_out")

        # ── Row 3: r3 = Q − ε · C_min · (T_hi − T_ci) ───────────────────────
        dT_max = T_hi - T_ci
        J[3, vidx[self._v_Q()]] = 1.0
        J[3, vidx[self._v_eps()]] = -C_min * dT_max
        J[3, vidx[self._vT("hot_in")]] += -eps * C_min  # direct dependence
        J[3, vidx[self._vT("cold_in")]] += +eps * C_min
        # C_min chain on the owning side
        if hot_is_min:
            for c in flows_h:
                J[3, vidx[self._v("hot_in", c)]] += -eps * cp_hot[c] * dT_max
            J[3, vidx[self._vT("hot_in")]]  += -eps * dC_hot_dT_either * dT_max
            J[3, vidx[self._vT("hot_out")]] += -eps * dC_hot_dT_either * dT_max
        else:
            for c in flows_c:
                J[3, vidx[self._v("cold_in", c)]] += -eps * cp_cold[c] * dT_max
            J[3, vidx[self._vT("cold_in")]]  += -eps * dC_cold_dT_either * dT_max
            J[3, vidx[self._vT("cold_out")]] += -eps * dC_cold_dT_either * dT_max

        # ── Row 4: r4 = NTU − UA / C_min ────────────────────────────────────
        # d/dC_min (UA/C_min) = -UA/C_min² → ∂r4/∂C_min = +UA/C_min²
        J[4, vidx[self._v_NTU()]] = 1.0
        scale4 = UA / (C_min_safe ** 2)
        if hot_is_min:
            for c in flows_h:
                J[4, vidx[self._v("hot_in", c)]] += scale4 * cp_hot[c]
            J[4, vidx[self._vT("hot_in")]]  += scale4 * dC_hot_dT_either
            J[4, vidx[self._vT("hot_out")]] += scale4 * dC_hot_dT_either
        else:
            for c in flows_c:
                J[4, vidx[self._v("cold_in", c)]] += scale4 * cp_cold[c]
            J[4, vidx[self._vT("cold_in")]]  += scale4 * dC_cold_dT_either
            J[4, vidx[self._vT("cold_out")]] += scale4 * dC_cold_dT_either

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=False,
            trust_region=self.trust_region,
            kpi_gradients=self.kpi_gradients(x0_dict),
        )

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        Q = x.get(self._v_Q(), 0.0)
        eps = x.get(self._v_eps(), 0.0)
        from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
        A_m2 = self.params.heat_transfer_area_m2()
        return {
            "Q_W": Q,
            "effectiveness": eps,
            "area_m2": A_m2,
            "capex_USD": hx_purchase_cost_USD(A_m2),
            "opex_USD_per_yr": 0.0,
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
        return hx_purchase_cost_USD(self.params.heat_transfer_area_m2())

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required area + minimum approach ΔT from current operating state.

        The NTU model carries UA directly, so the area implied at the
        clean-condition U_clean (with fouling) comes from
        ``heat_transfer_area_m2()`` — exposed here as a sizing KPI for
        Design / Performance-Check workflows.
        """
        T_hi = x.get(self._vT("hot_in"), 500.0)
        T_co = x.get(self._vT("cold_out"), 380.0)
        T_ho = x.get(self._vT("hot_out"), 400.0)
        T_ci = x.get(self._vT("cold_in"), 300.0)
        return {
            "A_required_m2": self.params.heat_transfer_area_m2(),
            "UA_W_per_K": self.params.UA_W_per_K,
            "U_clean_W_per_m2_K": self.params.U_clean_W_per_m2_K,
            "dT_min_K": min(T_hi - T_co, T_ho - T_ci),
        }
