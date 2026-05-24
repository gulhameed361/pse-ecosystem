"""Liquid-liquid decanter — phase split based on partition coefficients.

A two-phase liquid-liquid equilibrium (LLE) separator. Each component
distributes between an aqueous phase ("aq") and an organic phase ("org")
according to a partition coefficient ``K_i = x_i_org / x_i_aq``.

For non-ideal LLE the partition coefficients come from an activity-model
property package via :meth:`PropertyPackage.K_iteration` (subtle reuse:
the same ``K = γ_aq / γ_org`` ratio applies for LLE as for VLE modified
Raoult). For first-pass screening, fixed K_i can be supplied directly.

Residuals (3N + 2)
-------------------
  Material  :  F_i_aq + F_i_org − F_i_in = 0                       [N]
  LLE       :  F_i_org · F_total_aq − K_i · F_i_aq · F_total_org   [N]
  Pressure  :  P_aq − P_in = 0, P_org − P_in = 0                   [2]
  Temp      :  T_aq − T_in = 0, T_org − T_in = 0                   [2]

Notes
-----
* Energy balance assumes isothermal mixing (heat of mixing neglected).
* For three-phase VLLE, layer a FlashVLHF after the decanter or use a
  dedicated three-phase flash unit (not implemented in v1.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class DecanterHFParams:
    K_partition: Dict[str, float] = field(default_factory=dict)
    """Partition coefficients K_i = x_i_org / x_i_aq. Components not in
    this dict default to K = 1 (split equally). For non-ideal systems with
    activity models, derive K from γ_i^aq / γ_i^org at the LLE composition."""
    feed_max: float = 1e4  # mol/s
    T_min: float = 250.0
    T_max: float = 500.0
    P_min: float = 1e3
    P_max: float = 1e7


class DecanterHF(BaseUnit):
    """Two-phase liquid-liquid decanter with partition-coefficient model."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: Optional[DecanterHFParams] = None,
    ):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or DecanterHFParams()
        self.inlet_port = StreamPort(unit_id, "inlet", components, phase="liquid")
        self.aq_port = StreamPort(unit_id, "aqueous", components, phase="liquid")
        self.org_port = StreamPort(unit_id, "organic", components, phase="liquid")

    def _v_in(self, c: str) -> str:  return f"{self.unit_id}.inlet.F_{c}"
    def _v_aq(self, c: str) -> str:  return f"{self.unit_id}.aqueous.F_{c}"
    def _v_org(self, c: str) -> str: return f"{self.unit_id}.organic.F_{c}"
    def _vT(self, tag: str) -> str:  return f"{self.unit_id}.{tag}.T"
    def _vP(self, tag: str) -> str:  return f"{self.unit_id}.{tag}.P"

    def variables(self) -> List[str]:
        v = []
        for c in self.components:
            v.append(self._v_in(c))
        v += [self._vT("inlet"), self._vP("inlet")]
        for c in self.components:
            v.append(self._v_aq(c))
        v += [self._vT("aqueous"), self._vP("aqueous")]
        for c in self.components:
            v.append(self._v_org(c))
        v += [self._vT("organic"), self._vP("organic")]
        return v

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        b: Dict[str, Tuple[float, float]] = {}
        for tag in ("inlet", "aqueous", "organic"):
            for c in self.components:
                key = f"{self.unit_id}.{tag}.F_{c}"
                b[key] = (0.0, p.feed_max)
            b[self._vT(tag)] = (p.T_min, p.T_max)
            b[self._vP(tag)] = (p.P_min, p.P_max)
        return b

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        N = len(self.components)
        res = np.zeros(3 * N + 2 + 2, dtype=float)

        F_in = np.array([x.get(self._v_in(c), 0.0) for c in self.components])
        F_aq = np.array([x.get(self._v_aq(c), 0.0) for c in self.components])
        F_org = np.array([x.get(self._v_org(c), 0.0) for c in self.components])

        F_aq_tot = max(float(F_aq.sum()), 1e-9)
        F_org_tot = max(float(F_org.sum()), 1e-9)

        # Material balances [N]
        for i in range(N):
            res[i] = F_aq[i] + F_org[i] - F_in[i]

        # LLE partition: F_org_i × F_aq_tot − K_i × F_aq_i × F_org_tot [N]
        for i, c in enumerate(self.components):
            K_i = self.params.K_partition.get(c, 1.0)
            res[N + i] = F_org[i] * F_aq_tot - K_i * F_aq[i] * F_org_tot

        # Closure: each component's split fractions must sum to 1, which is
        # already implied by the material balance. Use the remaining 2N slots
        # for T/P pass-through.
        T_in = x.get(self._vT("inlet"), 350.0)
        P_in = x.get(self._vP("inlet"), 101325.0)
        # Map the 2N slots: outlet T/P pass-through on aq and org.
        res[2 * N] = x.get(self._vT("aqueous"), T_in) - T_in
        res[2 * N + 1] = x.get(self._vP("aqueous"), P_in) - P_in
        res[2 * N + 2] = x.get(self._vT("organic"), T_in) - T_in
        res[2 * N + 3] = x.get(self._vP("organic"), P_in) - P_in
        # Remaining N rows: trivial 0 = 0 (the second N LLE rows handled
        # composition; we kept the residual vector sized to 3N+4 for clarity
        # but rows are now filled — adjust the array size).
        return res[: 2 * N + 4]

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        F_aq_tot = sum(x.get(self._v_aq(c), 0.0) for c in self.components)
        F_org_tot = sum(x.get(self._v_org(c), 0.0) for c in self.components)
        result: Dict[str, float] = {
            f"{uid}.F_aqueous_mol_s": F_aq_tot,
            f"{uid}.F_organic_mol_s": F_org_tot,
            f"{uid}.organic_fraction": (
                F_org_tot / max(F_aq_tot + F_org_tot, 1e-12)
            ),
        }
        # Per-component recovery into the organic phase
        for c in self.components:
            F_in_c = max(x.get(self._v_in(c), 0.0), 1e-12)
            F_org_c = max(x.get(self._v_org(c), 0.0), 0.0)
            result[f"{uid}.recovery_{c}_organic_pct"] = (
                100.0 * F_org_c / F_in_c
            )
        return result

    def capex(self, x: Dict[str, float]) -> float:
        """Decanter vessel purchase cost [USD, CE500 basis]. Sized for 10 min
        residence time on the total liquid throughput; uses the SSLW vessel
        correlation with ρ_avg = 900 kg/m³ to convert mol/s → m³/s assuming
        average MW = 100 g/mol."""
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD

        F_total = sum(
            x.get(self._v_in(c), 0.0) for c in self.components
        )
        # Approximate volumetric flow: F [mol/s] × MW_avg / ρ_avg.
        V_vol = max(F_total, 0.01) * 0.100 / 900.0  # m³/s
        tau_s = 600.0  # 10 min — decanter heuristic (Walas)
        volume_m3 = max(V_vol * tau_s, 0.1)
        return vessel_purchase_cost_USD(volume_m3)
