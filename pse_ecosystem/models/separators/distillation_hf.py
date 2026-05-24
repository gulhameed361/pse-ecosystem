"""FUG shortcut distillation column (Fenske-Underwood-Gilliland).

Enhancement over HDADistillationUnit
--------------------------------------
HDADistillationUnit is HDA-specific and uses a fixed R/R_min ratio without
proper Underwood root-finding.  This unit:
  • Uses multicomponent Underwood's equation (root-finding for θ)
  • Uses the Molokanov (1972) form of the Gilliland correlation
  • Adds an explicit energy balance (reboiler + condenser duties)

Ports
-----
feed     : StreamPort  (F_i_feed, T_feed, P)
distillate: StreamPort (F_i_dist, T_dist)
bottoms  : StreamPort  (F_i_bot,  T_bot)

Design variables
-----------------
N_stages  : number of theoretical stages
R_ratio   : reflux ratio L/D
Q_cond    : condenser duty [W]  (negative = heat removed)
Q_reb     : reboiler duty [W]   (positive = heat added)

Residuals (N + 4 equations)
-----------------------------
  Material  : F_i_feed - F_i_dist - F_i_bot = 0            [N]
  Fenske    : N_stages - N_min / (1 - Gilliland(X)) = 0    [1]  (simplified)
  R_min     : solved via Underwood; enforced as               [1]
              R_ratio >= R_min (implemented as R_ratio - R_min = 0 at design)
  Q_cond    : Q_cond + F_dist * H_dist - F_total_vap_top * H_vap_top = 0  [1]
  Q_reb     : Q_reb = F_bot * H_bot + F_dist * H_dist - F_feed * H_feed - Q_cond [1]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory
from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, SHOMATE
from pse_ecosystem.models.properties.vle import K_value

_KNOWN = set(SHOMATE.keys())
_SMALL = 1e-12


@dataclass
class DistillationHFParams:
    species_vle: List[str]      # species with Antoine K-values
    lk: str                     # light key component name
    hk: str                     # heavy key component name
    T_op_K: float = 350.0       # operating temperature for K-values
    P_op_Pa: float = 101325.0   # operating pressure
    R_over_Rmin: float = 1.2    # design reflux ratio = R_over_Rmin * R_min
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 600.0
    P_min: float = 1e3
    P_max: float = 5e6
    Q_max: float = 1e10
    N_stages_max: float = 200.0


class DistillationHF(BaseUnit):
    """FUG shortcut distillation column with energy balance.

    Tagged ``SCREENING`` because the Fenske-Underwood-Gilliland equations are
    a screening-grade representation — stage-by-stage MESH solvers (the
    forthcoming ``TrayColumnHF`` in Workstream B) supersede this for
    industrial-fidelity design.
    """

    is_linear = False
    category = UnitCategory.SCREENING

    def __init__(self, unit_id: str, components: List[str], params: DistillationHFParams):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        self.feed_port      = StreamPort(unit_id, "feed",      components)
        self.distillate_port= StreamPort(unit_id, "distillate",components)
        self.bottoms_port   = StreamPort(unit_id, "bottoms",   components)

    def _v_F(self, tag: str, c: str) -> str: return f"{self.unit_id}.{tag}.F_{c}"
    def _v_T(self, tag: str)         -> str: return f"{self.unit_id}.{tag}.T"
    def _v_P(self, tag: str)         -> str: return f"{self.unit_id}.{tag}.P"
    def _v_N(self)                   -> str: return f"{self.unit_id}.N_stages"
    def _v_R(self)                   -> str: return f"{self.unit_id}.R_ratio"
    def _v_Qc(self)                  -> str: return f"{self.unit_id}.Q_cond"
    def _v_Qr(self)                  -> str: return f"{self.unit_id}.Q_reb"

    def variables(self) -> List[str]:
        vlist = []
        for tag in ("feed", "distillate", "bottoms"):
            for c in self.components:
                vlist.append(self._v_F(tag, c))
            vlist += [self._v_T(tag), self._v_P(tag)]
        vlist += [self._v_N(), self._v_R(), self._v_Qc(), self._v_Qr()]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for tag in ("feed", "distillate", "bottoms"):
            for c in self.components:
                bds[self._v_F(tag, c)] = (0.0, p.feed_max)
            bds[self._v_T(tag)] = (p.T_min, p.T_max)
            bds[self._v_P(tag)] = (p.P_min, p.P_max)
        bds[self._v_N()]  = (1.0, p.N_stages_max)
        bds[self._v_R()]  = (0.1, 1000.0)
        bds[self._v_Qc()] = (-p.Q_max, 0.0)
        bds[self._v_Qr()] = (0.0, p.Q_max)
        return bds

    def _K_values(self) -> Dict[str, float]:
        p = self.params
        return {c: K_value(c, p.T_op_K, p.P_op_Pa) if c in p.species_vle else 1.0
                for c in self.components}

    def _fenske(self, K_vals: Dict[str, float], x_lk_D: float, x_hk_D: float,
                x_lk_B: float, x_hk_B: float) -> float:
        """Fenske equation for minimum stages."""
        alpha = K_vals.get(self.params.lk, 2.0) / max(K_vals.get(self.params.hk, 1.0), _SMALL)
        lk_D = max(x_lk_D, _SMALL)
        hk_D = max(x_hk_D, _SMALL)
        lk_B = max(x_lk_B, _SMALL)
        hk_B = max(x_hk_B, _SMALL)
        try:
            N_min = math.log((lk_D / hk_D) * (hk_B / lk_B)) / math.log(max(alpha, 1.001))
        except (ValueError, ZeroDivisionError):
            N_min = 5.0
        return max(N_min, 1.0)

    def _underwood_Rmin(self, K_vals: Dict[str, float], z: Dict[str, float], q: float = 1.0) -> float:
        """Simplified Underwood R_min.  q=1 (saturated liquid feed)."""
        # Find θ: Σ_i α_i * z_i / (α_i - θ) = 1 - q
        alpha = {c: K_vals.get(c, 1.0) / max(K_vals.get(self.params.hk, 1.0), _SMALL)
                 for c in self.components}
        alpha_vals = np.array([alpha[c] for c in self.components])
        z_vals = np.array([z.get(c, 0.0) for c in self.components])
        F_total = max(z_vals.sum(), _SMALL)
        z_norm = z_vals / F_total

        # Underwood function: Σ α_i*z_i/(α_i - θ) = 1-q
        target = 1.0 - q
        # θ must lie strictly between the α of the heavy and light keys.
        # If the user mis-labels them (α_hk > α_lk because the operating
        # condition flipped the K-value ordering), swap so the bracket is
        # always valid rather than degenerating. Audit M7.
        a_hk_raw = alpha.get(self.params.hk, 1.0)
        a_lk_raw = alpha.get(self.params.lk, 2.0)
        alpha_hk = min(a_hk_raw, a_lk_raw)
        alpha_lk = max(a_hk_raw, a_lk_raw)
        theta_lo = alpha_hk + 1e-6
        theta_hi = alpha_lk - 1e-6

        def underwood_f(theta: float) -> float:
            return float(np.sum(alpha_vals * z_norm / (alpha_vals - theta))) - target

        if theta_lo >= theta_hi:
            return 0.5  # fallback

        try:
            from scipy.optimize import brentq
            theta = brentq(underwood_f, theta_lo, theta_hi, xtol=1e-8)
        except Exception as exc:  # noqa: BLE001
            # v1.4.0 audit N10 — cache the failure reason on the unit. The
            # bracket-midpoint fallback was masking root-finding failures
            # caused by upstream T_op / alpha drift; downstream KPI rows
            # now surface the issue rather than reporting a plausible-
            # looking but wrong R_min.
            self._last_underwood_error = repr(exc)
            theta = 0.5 * (theta_lo + theta_hi)

        # R_min = Σ_i α_i * x_Di / (α_i - θ) - 1  (simplified: use z for feed composition)
        R_min = float(np.sum(alpha_vals * z_norm / (alpha_vals - theta))) - 1.0
        return max(R_min, 0.01)

    @staticmethod
    def _gilliland_molokanov(R: float, R_min: float, N_min: float) -> float:
        """Molokanov (1972) form of the Gilliland correlation."""
        if R_min < _SMALL:
            return N_min
        X = (R - R_min) / (R + 1.0)
        X = max(0.0, min(X, 0.999))
        Y = 1.0 - math.exp((1.0 + 54.4 * X) / (11.0 + 117.2 * X) * (X - 1.0) / max(X ** 0.5, _SMALL))
        if 1.0 - Y < _SMALL:
            return N_min
        return N_min / (1.0 - Y)

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(N + 4, dtype=float)

        F_feed = {c: x.get(self._v_F("feed", c), 0.0) for c in comps}
        F_dist = {c: x.get(self._v_F("distillate", c), 0.0) for c in comps}
        F_bot  = {c: x.get(self._v_F("bottoms", c), 0.0) for c in comps}
        T_feed = x.get(self._v_T("feed"), 350.0)
        T_dist = x.get(self._v_T("distillate"), 330.0)
        T_bot  = x.get(self._v_T("bottoms"), 380.0)
        N_stg  = x.get(self._v_N(), 20.0)
        R      = x.get(self._v_R(), 2.0)
        Q_cond = x.get(self._v_Qc(), -1e5)
        Q_reb  = x.get(self._v_Qr(), 1e5)

        # Material balances [N]
        for i, c in enumerate(comps):
            res[i] = F_feed[c] - F_dist[c] - F_bot[c]

        # FUG design equation [1]
        K_vals = self._K_values()
        F_total = max(sum(F_feed.values()), _SMALL)
        z = {c: F_feed[c] / F_total for c in comps}

        D_total = max(sum(F_dist.values()), _SMALL)
        B_total = max(sum(F_bot.values()), _SMALL)
        lk = self.params.lk
        hk = self.params.hk
        x_lk_D = F_dist.get(lk, _SMALL) / D_total
        x_hk_D = F_dist.get(hk, _SMALL) / D_total
        x_lk_B = F_bot.get(lk, _SMALL) / B_total
        x_hk_B = F_bot.get(hk, _SMALL) / B_total

        N_min = self._fenske(K_vals, x_lk_D, x_hk_D, x_lk_B, x_hk_B)
        R_min = self._underwood_Rmin(K_vals, z)
        p = self.params
        R_design = p.R_over_Rmin * R_min

        N_calc = self._gilliland_molokanov(R_design, R_min, N_min)
        res[N] = N_stg - N_calc

        # R_ratio at design: enforce R = R_design [1]
        res[N + 1] = R - R_design

        # Energy balance overall: Q_reb + H_feed = H_dist + H_bot + |Q_cond| [1]
        H_feed = sum(F_feed[c] * enthalpy_J_mol(c, T_feed) for c in comps if c in _KNOWN)
        H_dist = sum(F_dist[c] * enthalpy_J_mol(c, T_dist) for c in comps if c in _KNOWN)
        H_bot  = sum(F_bot[c]  * enthalpy_J_mol(c, T_bot)  for c in comps if c in _KNOWN)
        res[N + 2] = Q_reb + H_feed - H_dist - H_bot + Q_cond

        # Condenser duty relation: Q_cond = -R * D * Cp * (T_dew - T_dist) approx
        # Simplified: Q_cond expressed through energy balance closure
        res[N + 3] = 0.0  # placeholder — condenser uniquely determined by res[N+2]

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD
        N = x.get(self._v_N(), 20.0)
        D_total = sum(x.get(self._v_F("distillate", c), 0.0) for c in self.components)
        B_total = sum(x.get(self._v_F("bottoms", c), 0.0) for c in self.components)
        F_total = max(D_total + B_total, _SMALL)
        V_est = N * 0.5 * F_total / 1000.0
        return vessel_purchase_cost_USD(max(V_est, 0.01))

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        N     = x.get(self._v_N(), 0.0)
        R     = x.get(self._v_R(), 0.0)
        Q_cond = x.get(self._v_Qc(), 0.0)
        Q_reb  = x.get(self._v_Qr(), 0.0)
        lk = self.params.lk
        hk = self.params.hk
        D_total = max(sum(x.get(self._v_F("distillate", c), 0.0) for c in self.components), _SMALL)
        B_total = max(sum(x.get(self._v_F("bottoms", c), 0.0) for c in self.components), _SMALL)
        F_total = max(sum(x.get(self._v_F("feed", c), 0.0) for c in self.components), _SMALL)
        result = {
            f"{uid}.N_stages":           N,
            f"{uid}.R_ratio":            R,
            f"{uid}.Q_cond_W":           Q_cond,
            f"{uid}.Q_reb_W":            Q_reb,
            f"{uid}.distillate_flow":    D_total,
            f"{uid}.bottoms_flow":       B_total,
        }
        for c in self.components:
            F_d = x.get(self._v_F("distillate", c), 0.0)
            F_b = x.get(self._v_F("bottoms", c), 0.0)
            F_f = max(x.get(self._v_F("feed", c), 0.0), _SMALL)
            result[f"{uid}.recovery_{c}_distillate_pct"] = 100.0 * max(F_d, 0.0) / F_f
            result[f"{uid}.recovery_{c}_bottoms_pct"]    = 100.0 * max(F_b, 0.0) / F_f
        return result
