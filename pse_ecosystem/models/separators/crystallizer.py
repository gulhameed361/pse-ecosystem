"""Cooling / evaporative crystalliser — solid-product separation.

A feed solution is cooled (or solvent evaporated) until the solute
concentration exceeds the temperature-dependent solubility S(T), at
which point crystals form. The unit produces three streams:

* ``mother_liquor`` — saturated solution at T_op
* ``crystals``      — solid crystalline product
* ``vapor``         — evaporated solvent (optional; zero unless
                       ``evaporation_kg_s > 0``)

Solubility model: ``S(T) = S_ref · exp(ΔH_sol / R · (1/T_ref − 1/T))``
(van't Hoff form, same as :class:`FlashSL`). For a single solute the
crystal mass per second is:

    m_xtal = m_feed_solute − S(T_op) · m_solvent_remaining

where m_solvent_remaining = m_feed_solvent − m_vapor.

Used for inorganic-salt recovery (NaCl, KCl), pharmaceutical APIs, and
sugar refining. For polymorphic / habit-controlled crystallisation the
unit is screening-grade only — population-balance models live elsewhere.

Residuals (5)
-------------
  Solvent balance  :  m_solvent_ml + m_vapor − m_solvent_feed = 0
  Solute balance   :  m_solute_ml + m_xtal − m_solute_feed = 0
  Solubility       :  m_solute_ml − S(T_op) · m_solvent_ml = 0
  Energy           :  Q + h_feed · m_feed − h_ml · m_ml
                       − h_xtal · m_xtal − h_vap · m_vapor = 0
  Vapor spec       :  m_vapor − vapor_spec = 0 (if specified)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

_R_GAS = 8.314462
# Bulk solvent thermo (water default)
_CP_SOLVENT_kJ_kg_K = 4.186
_H_VAP_kJ_kg = 2257.0
_CP_SOLUTE_kJ_kg_K = 0.9   # generic salt Cp


@dataclass
class CrystallizerHFParams:
    solute: str = "NaCl"
    S_ref_kg_per_kg: float = 0.360
    """Reference solubility [kg solute / kg solvent] at T_ref."""
    dH_sol_J_per_mol: float = 3000.0
    """Dissolution enthalpy [J/mol]. Positive for endothermic dissolution
    (most salts); negative for exothermic (e.g. anhydrous CaCl2)."""
    MW_solute_kg_per_mol: float = 0.0585
    T_ref_K: float = 298.15
    T_op_K: float = 283.15
    """Operating temperature [K]. Cooling crystalliser: 5–15 °C. Evaporative
    crystalliser: at the solvent boiling point."""
    vapor_kg_s: float = 0.0
    """Solvent evaporation rate [kg/s]. 0 = cooling crystalliser; > 0 =
    evaporative."""
    h_xtal_kJ_kg: float = -50.0
    """Crystallisation heat / dissolution heat at T_op [kJ/kg solid] —
    negative because crystallisation is exothermic (heat released)."""
    feed_max_kg_s: float = 100.0
    Q_max_kW: float = 1e7


class CrystallizerHF(BaseUnit):
    """Single-solute cooling / evaporative crystalliser."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        params: Optional[CrystallizerHFParams] = None,
    ):
        self.unit_id = unit_id
        self.params = params or CrystallizerHFParams()
        sol = self.params.solute
        self.feed_in_port = StreamPort(
            unit_id, "feed_in", [sol, "solvent"], phase="liquid",
        )
        self.mother_liquor_port = StreamPort(
            unit_id, "mother_liquor", [sol, "solvent"], phase="liquid",
        )
        self.crystals_port = StreamPort(
            unit_id, "crystals", [sol], phase="any",
        )
        self.vapor_port = StreamPort(
            unit_id, "vapor", ["solvent"], phase="gas",
        )

    def _v_feed(self, c: str) -> str: return f"{self.unit_id}.feed_in.F_{c}"
    def _v_ml(self, c: str) -> str:   return f"{self.unit_id}.mother_liquor.F_{c}"
    def _v_xtal(self) -> str:         return f"{self.unit_id}.crystals.F_{self.params.solute}"
    def _v_vapor(self) -> str:        return f"{self.unit_id}.vapor.F_solvent"
    def _v_Q(self) -> str:            return f"{self.unit_id}.Q_kW"
    def _v_T_feed(self) -> str:       return f"{self.unit_id}.feed_in.T"

    def variables(self) -> List[str]:
        sol = self.params.solute
        return [
            self._v_feed(sol), self._v_feed("solvent"),
            self._v_ml(sol), self._v_ml("solvent"),
            self._v_xtal(), self._v_vapor(),
            self._v_T_feed(), self._v_Q(),
        ]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        return {
            self._v_feed(p.solute): (0.0, p.feed_max_kg_s),
            self._v_feed("solvent"): (0.0, p.feed_max_kg_s),
            self._v_ml(p.solute): (0.0, p.feed_max_kg_s),
            self._v_ml("solvent"): (0.0, p.feed_max_kg_s),
            self._v_xtal(): (0.0, p.feed_max_kg_s),
            self._v_vapor(): (0.0, p.feed_max_kg_s),
            self._v_T_feed(): (260.0, 400.0),
            self._v_Q(): (-p.Q_max_kW, p.Q_max_kW),
        }

    def _solubility_kg_per_kg(self) -> float:
        p = self.params
        # van't Hoff: ln(S/S_ref) = ΔH_sol/R · (1/T_ref − 1/T_op)
        ln_ratio = (p.dH_sol_J_per_mol / _R_GAS) * (
            1.0 / p.T_ref_K - 1.0 / p.T_op_K
        )
        return p.S_ref_kg_per_kg * math.exp(ln_ratio)

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        res = np.zeros(5, dtype=float)

        m_feed_sol = x.get(self._v_feed(p.solute), 0.0)
        m_feed_solv = x.get(self._v_feed("solvent"), 0.0)
        m_ml_sol = x.get(self._v_ml(p.solute), 0.0)
        m_ml_solv = x.get(self._v_ml("solvent"), 0.0)
        m_xtal = x.get(self._v_xtal(), 0.0)
        m_vapor = x.get(self._v_vapor(), 0.0)
        T_feed = x.get(self._v_T_feed(), 298.15)
        Q = x.get(self._v_Q(), 0.0)

        S = self._solubility_kg_per_kg()

        # Solvent balance: m_solv_in = m_ml_solv + m_vapor
        res[0] = m_ml_solv + m_vapor - m_feed_solv
        # Solute balance: m_solute_in = m_ml + m_xtal
        res[1] = m_ml_sol + m_xtal - m_feed_sol
        # Saturation: mother liquor is at the solubility limit at T_op
        res[2] = m_ml_sol - S * m_ml_solv
        # Energy balance [kW]: cool feed from T_feed to T_op + evaporate
        # solvent + release crystallisation heat.
        h_feed = _CP_SOLVENT_kJ_kg_K * (T_feed - 273.15)
        h_ml = _CP_SOLVENT_kJ_kg_K * (p.T_op_K - 273.15)
        h_xtal = _CP_SOLUTE_kJ_kg_K * (p.T_op_K - 273.15) + p.h_xtal_kJ_kg
        h_vap = _CP_SOLVENT_kJ_kg_K * (p.T_op_K - 273.15) + _H_VAP_kJ_kg
        H_in = (m_feed_sol + m_feed_solv) * h_feed
        H_out = (
            (m_ml_sol + m_ml_solv) * h_ml
            + m_xtal * h_xtal
            + m_vapor * h_vap
        )
        res[3] = Q + H_in - H_out
        # Vapor spec
        res[4] = m_vapor - p.vapor_kg_s
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        p = self.params
        m_feed_sol = max(x.get(self._v_feed(p.solute), 0.0), 1e-12)
        m_xtal = max(x.get(self._v_xtal(), 0.0), 0.0)
        yield_pct = 100.0 * m_xtal / m_feed_sol
        return {
            f"{uid}.solubility_kg_per_kg_at_T_op": self._solubility_kg_per_kg(),
            f"{uid}.T_op_K": p.T_op_K,
            f"{uid}.crystal_yield_pct": yield_pct,
            f"{uid}.crystals_kg_s": m_xtal,
            f"{uid}.mother_liquor_kg_s": (
                x.get(self._v_ml(p.solute), 0.0) + x.get(self._v_ml("solvent"), 0.0)
            ),
            f"{uid}.Q_kW": x.get(self._v_Q(), 0.0),
            f"{uid}.vapor_kg_s": x.get(self._v_vapor(), 0.0),
        }

    def capex(self, x: Dict[str, float]) -> float:
        """Crystalliser (forced-circulation) purchase cost [USD, CE500].
        Anchored on 1 t/h capacity: ~$500k for FC unit (Towler-Sinnott
        Ch.17 Table 17.10). Six-tenths scaling with feed rate."""
        F_feed = max(
            x.get(self._v_feed(self.params.solute), 0.0)
            + x.get(self._v_feed("solvent"), 0.1),
            0.1,
        )  # kg/s
        return 500_000.0 * (F_feed * 3.6 / 1.0) ** 0.6  # convert to t/h
