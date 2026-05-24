"""Cross-flow membrane module with per-component permeance.

For a single feed entering a membrane, each component permeates at a rate
proportional to its partial-pressure driving force:

    F_i_perm = P_i · A_mem · (P_feed · y_i − P_perm · z_i)

where P_i [mol/(m²·s·Pa)] is the permeance, A_mem the membrane area,
y_i the feed-side mole fraction at the local cross-section, and z_i the
permeate-side mole fraction. For a *well-mixed* permeate (cross-flow
with permeate sweep), an explicit closed form for log-mean composition
isn't available; we use a *flat-sheet* approximation evaluated at the
feed mole fraction (acceptable when stage cut θ = F_perm/F_feed < 0.3).

The unit handles multi-component gas separation — H2/CH4 (Pd
membranes), CO2/N2 (polymeric), O2/N2 (zeolite). Permeance values are
project-specific and supplied via ``permeance_mol_m2_s_Pa``.

Residuals (2N + 4)
-------------------
  Material  :  F_i_retentate + F_i_permeate − F_i_feed = 0          [N]
  Flux eqn  :  F_i_permeate − P_i · A · ΔP_i_feed_basis = 0          [N]
  T pass    :  T_ret − T_feed = 0, T_perm − T_feed = 0               [2]
  P spec    :  P_ret − P_feed = 0  (no retentate pressure drop)      [1]
                P_perm − P_perm_spec (permeate side pressure)         [1]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class MembraneModuleHFParams:
    area_m2: float = 100.0
    permeance_mol_m2_s_Pa: Dict[str, float] = field(default_factory=dict)
    """Per-component permeance [mol·m⁻²·s⁻¹·Pa⁻¹]. Typical orders:
    H2  in Pd-alloy:     5e-6
    H2  in polyimide:    1e-8
    CO2 in polyimide:    2e-9
    N2  in polyimide:    1e-10
    Components absent from the dict default to 0 (no permeation)."""
    P_permeate_Pa: float = 1.0e5
    """Permeate-side pressure [Pa]. Default 1 atm (vacuum or atmospheric
    sweep). For high-pressure permeate, raise this; flux drops accordingly."""
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 800.0
    P_min: float = 1e3
    P_max: float = 1e8


class MembraneModuleHF(BaseUnit):
    """Multi-component permeation module with cross-flow approximation."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: Optional[MembraneModuleHFParams] = None,
    ):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or MembraneModuleHFParams()
        self.feed_in_port = StreamPort(unit_id, "feed_in", components, phase="gas")
        self.retentate_port = StreamPort(unit_id, "retentate", components, phase="gas")
        self.permeate_port = StreamPort(unit_id, "permeate", components, phase="gas")

    def _v_feed(self, c: str) -> str: return f"{self.unit_id}.feed_in.F_{c}"
    def _v_ret(self, c: str) -> str:  return f"{self.unit_id}.retentate.F_{c}"
    def _v_perm(self, c: str) -> str: return f"{self.unit_id}.permeate.F_{c}"
    def _vT(self, tag: str) -> str:   return f"{self.unit_id}.{tag}.T"
    def _vP(self, tag: str) -> str:   return f"{self.unit_id}.{tag}.P"

    def variables(self) -> List[str]:
        v = []
        for tag in ("feed_in", "retentate", "permeate"):
            for c in self.components:
                v.append(f"{self.unit_id}.{tag}.F_{c}")
            v += [self._vT(tag), self._vP(tag)]
        return v

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        b: Dict[str, Tuple[float, float]] = {}
        for vname in self.variables():
            if ".T" in vname:
                b[vname] = (p.T_min, p.T_max)
            elif ".P" in vname:
                b[vname] = (p.P_min, p.P_max)
            else:
                b[vname] = (0.0, p.feed_max)
        return b

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        N = len(self.components)
        res = np.zeros(2 * N + 4, dtype=float)

        F_feed = np.array([x.get(self._v_feed(c), 0.0) for c in self.components])
        F_ret = np.array([x.get(self._v_ret(c), 0.0) for c in self.components])
        F_perm = np.array([x.get(self._v_perm(c), 0.0) for c in self.components])
        T_feed = x.get(self._vT("feed_in"), 350.0)
        P_feed = max(x.get(self._vP("feed_in"), 1.0e6), 1.0)
        P_perm = max(x.get(self._vP("permeate"), p.P_permeate_Pa), 1.0)

        F_feed_total = max(float(F_feed.sum()), 1e-9)
        F_perm_total = max(float(F_perm.sum()), 1e-9)
        y_feed = F_feed / F_feed_total
        z_perm = F_perm / F_perm_total

        # Material balances [N]
        for i in range(N):
            res[i] = F_ret[i] + F_perm[i] - F_feed[i]

        # Flux equations: F_perm_i = P_i · A · (P_feed · y_i − P_perm · z_i)
        # The driving force may go negative if z_i > y_i × (P_feed/P_perm);
        # we use a softplus-ish max(·, 0) guard so the residual doesn't push
        # F_perm_i below zero.
        for i, c in enumerate(self.components):
            P_i = p.permeance_mol_m2_s_Pa.get(c, 0.0)
            driving = P_feed * y_feed[i] - P_perm * z_perm[i]
            flux_i = max(P_i * p.area_m2 * driving, 0.0)
            res[N + i] = F_perm[i] - flux_i

        # T pass-through [2]
        res[2 * N] = x.get(self._vT("retentate"), T_feed) - T_feed
        res[2 * N + 1] = x.get(self._vT("permeate"), T_feed) - T_feed
        # P specs [2]
        res[2 * N + 2] = x.get(self._vP("retentate"), P_feed) - P_feed
        res[2 * N + 3] = x.get(self._vP("permeate"), P_perm) - p.P_permeate_Pa
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        F_feed_total = sum(x.get(self._v_feed(c), 0.0) for c in self.components)
        F_perm_total = sum(x.get(self._v_perm(c), 0.0) for c in self.components)
        stage_cut = F_perm_total / max(F_feed_total, 1e-12)
        result: Dict[str, float] = {
            f"{uid}.stage_cut": stage_cut,
            f"{uid}.area_m2": self.params.area_m2,
            f"{uid}.F_permeate_mol_s": F_perm_total,
        }
        # Per-component selectivity vs the slowest permeating species
        for c in self.components:
            F_feed_c = max(x.get(self._v_feed(c), 0.0), 1e-12)
            F_perm_c = max(x.get(self._v_perm(c), 0.0), 0.0)
            result[f"{uid}.recovery_{c}_pct"] = (
                100.0 * F_perm_c / F_feed_c
            )
        return result

    def capex(self, x: Dict[str, float]) -> float:
        """Membrane-module purchase cost [USD]. Towler-Sinnott Ch.17:
        typical polymer modules ~1000 USD/m² installed; Pd-alloy ~10×."""
        return 1000.0 * max(self.params.area_m2, 0.1)
