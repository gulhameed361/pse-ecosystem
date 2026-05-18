"""High-fidelity PEM/AEL electrolyser unit model with StreamPort connectivity.

All residual equations are linear (at fixed efficiency), so ``is_linear=True``
and the SLP driver short-circuits to a single LP solve.

Physics
-------
H₂O (l) → H₂ (g) + ½ O₂ (g)

    W_elec = F_H2 × HHV_H2 / η_elec   [kW electricity in]
    F_H2O  = F_H2                       [mol/s water consumed, 1:1 molar]
    F_O2   = 0.5 × F_H2                [mol/s oxygen byproduct]

HHV_H₂ = 285.8 kJ/mol (includes condensation of product water).
Using HHV ensures the stack efficiency η_elec is referenced to the highest
energy content of hydrogen, consistent with industry LHV vs HHV conventions.

Typical η_elec: PEM 0.65–0.75, AEL 0.60–0.70, SOEL 0.70–0.85.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

_HHV_H2 = 285.8   # kJ/mol
_M_H2 = 0.002     # kg/mol
_M_H2O = 0.018    # kg/mol
_M_O2 = 0.032     # kg/mol


class ElectrolyserHF(BaseUnit):
    """Port-based PEM / AEL electrolyser with analytical Jacobian.

    Parameters
    ----------
    unit_id :
        Unique identifier for this unit instance.
    eta_elec :
        Stack efficiency (HHV basis), default 0.70.
    """

    is_linear: bool = True

    def __init__(self, unit_id: str, *, eta_elec: float = 0.70):
        # v1.4.0 audit N4 — clamp eta_elec to the physically realistic range
        # for PEM / AEL electrolysers (about 0.55 to 0.85 HHV-basis on the
        # stack alone; system-level can be lower). The pre-v1.4.0 model
        # accepted any positive value, so a typo or aggressive optimiser
        # could push it to 0.05 (→ 2858 kW/(mol/s) H₂, clearly unphysical).
        if not (0.30 <= eta_elec <= 0.95):
            raise ValueError(
                f"ElectrolyserHF eta_elec must be in [0.30, 0.95]; got "
                f"{eta_elec:.4f}. Typical PEM HHV-basis range is 0.55–0.85; "
                f"low-temp AEL down to ~0.45."
            )
        self.unit_id = unit_id
        self.eta_elec = float(eta_elec)

        # Derived coefficient
        self._k_elec = _HHV_H2 / self.eta_elec  # kW per (mol/s) H2

        # Port definitions (no T/P — electrolyser operates at fixed conditions)
        self.water_in_port = StreamPort(
            unit_id, "water_in",
            components=["H2O"],
            has_T=False, has_P=False,
            phase="liquid",
            species=frozenset({"H2O"}),
        )
        self.h2_out_port = StreamPort(
            unit_id, "h2_out",
            components=["H2"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"H2"}),
        )
        self.o2_out_port = StreamPort(
            unit_id, "o2_out",
            components=["O2"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"O2"}),
        )

        self._v_h2o = f"{unit_id}.water_in.F_H2O"
        self._v_h2 = f"{unit_id}.h2_out.F_H2"
        self._v_o2 = f"{unit_id}.o2_out.F_O2"
        self._v_w = f"{unit_id}.W_elec_kW"

    def variables(self) -> List[str]:
        return [self._v_h2o, self._v_h2, self._v_o2, self._v_w]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self._v_h2o: (0.0, 1e5),   # mol/s water feed
            self._v_h2:  (0.0, 1e5),   # mol/s H2 produced
            self._v_o2:  (0.0, 5e4),   # mol/s O2 byproduct
            self._v_w:   (0.0, 1e7),   # kW electricity
        }

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        F_h2 = x.get(self._v_h2, 0.0)
        return np.array([
            x.get(self._v_w, 0.0) - self._k_elec * F_h2,   # r0: W_elec balance
            x.get(self._v_h2o, 0.0) - F_h2,                 # r1: H2O stoichiometry
            x.get(self._v_o2, 0.0) - 0.5 * F_h2,            # r2: O2 stoichiometry
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        # v1.4.0 audit N15 — match the residual's floor convention and
        # report eta_elec as a *parameter* (the unit's nameplate stack
        # efficiency, fixed at construction) rather than as a per-iteration
        # KPI. The pre-v1.4.0 dict put eta_elec * 100 in here verbatim,
        # which looked like a KPI but was actually a constant.
        _FLOOR = 1.0e-3
        F_h2 = max(x.get(self._v_h2, 0.0), _FLOOR)
        W = x.get(self._v_w, 0.0)
        h2_kg_h = F_h2 * _M_H2 * 3600.0
        specific_kWh_kg = W / (F_h2 * _M_H2 * 3600.0) if F_h2 > 0 else 0.0
        return {
            "H2_production_kg_h": h2_kg_h,
            "efficiency_pct": self.eta_elec * 100.0,
            "specific_power_kWh_per_kgH2": specific_kWh_kg,
            "W_elec_kW": W,
        }

    def capex(self, x: Dict[str, float]) -> float:
        # Stack CAPEX: ~700 USD/kW installed capacity (2024, declining)
        W_kW = max(x.get(self._v_w, 0.0), 0.1)
        return 700.0 * W_kW  # USD, approximate 2024 PEM stack cost

    # ── Analytical linearise ──────────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        vnames = self.variables()
        idx = {v: i for i, v in enumerate(vnames)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in vnames}
        x0 = np.array([x0_dict[v] for v in vnames], dtype=float)
        f0 = self.residual(x0_dict)
        n = len(vnames)

        J = np.zeros((3, n), dtype=float)
        i_h2o, i_h2, i_o2, i_w = (
            idx[self._v_h2o], idx[self._v_h2], idx[self._v_o2], idx[self._v_w]
        )
        # r0: W_elec - k*F_H2 = 0
        J[0, i_w] = 1.0;   J[0, i_h2] = -self._k_elec
        # r1: F_H2O - F_H2 = 0
        J[1, i_h2o] = 1.0; J[1, i_h2] = -1.0
        # r2: F_O2 - 0.5*F_H2 = 0
        J[2, i_o2] = 1.0;  J[2, i_h2] = -0.5

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=vnames,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=True,
            trust_region=self.trust_region,
        )
