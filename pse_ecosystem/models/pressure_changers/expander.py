"""Turbo-expander / turbine — counterpart to :class:`Compressor`.

Isentropic expansion with efficiency η:
    T_out_isen = T_in × (P_out / P_in)^((γ-1)/γ)   [P_out < P_in]
    T_out      = T_in − η × (T_in − T_out_isen)
    W_shaft    = F_total × Cp_mix × (T_in − T_out)   [W, positive = work OUT]

Used for power recovery in cryogenic plants, hydrogen liquefaction
expansion turbines, gas-pressure let-down (instead of throttling), and
turbo-expanders on syngas / fuel-gas headers.

Sign convention
----------------
``W_shaft`` is the **work delivered to the shaft** — positive when the
expander extracts power. This is the opposite of the Compressor's
``W_shaft`` (which is the work consumed). Downstream economics treat
expander W as electricity *generated* (negative coefficient in OPEX).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import (
    SHOMATE,
    mixture_cp_J_mol_K,
)

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())


@dataclass
class ExpanderParams:
    eta_isentropic: float = 0.80
    P_out_Pa: Optional[float] = None
    feed_max: float = 1e4
    T_min: float = 100.0
    T_max: float = 1500.0
    P_min: float = 1e3
    P_max: float = 1e8
    W_max: float = 1e9
    gamma_fixed: Optional[float] = None
    electricity_price_USD_per_kWh: float = 0.05
    operating_hours_per_year: float = 8000.0


class ExpanderHF(BaseUnit):
    """Isentropic expander / turbine with efficiency correction."""

    is_linear = False
    # v1.6.1 P.5b — coefficient is a negative ``electricity_price × hours``
    # credit for the recovered shaft work; already in USD/yr.
    _OPEX_CONVENTION = "USD_per_year"

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: Optional[ExpanderParams] = None,
    ):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or ExpanderParams()
        self.inlet_port = StreamPort(unit_id, "inlet", components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    # ── Variable layout ───────────────────────────────────────────────────
    def _v_F_in(self, c: str) -> str:  return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self) -> str:          return f"{self.unit_id}.inlet.T"
    def _v_P_in(self) -> str:          return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self) -> str:         return f"{self.unit_id}.outlet.T"
    def _v_P_out(self) -> str:         return f"{self.unit_id}.outlet.P"
    def _v_W(self) -> str:             return f"{self.unit_id}.W_shaft"

    def variables(self) -> List[str]:
        v = []
        for c in self.components:
            v.append(self._v_F_in(c))
        v += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            v.append(self._v_F_out(c))
        v += [self._v_T_out(), self._v_P_out(), self._v_W()]
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
        if p.P_out_Pa is not None:
            b[self._v_P_out()] = (p.P_out_Pa, p.P_out_Pa)
        else:
            b[self._v_P_out()] = (p.P_min, p.P_max)
        b[self._v_W()] = (0.0, p.W_max)
        return b

    # ── Physics helpers ───────────────────────────────────────────────────
    def _gamma(self, x: Dict[str, float]) -> float:
        if self.params.gamma_fixed is not None:
            return self.params.gamma_fixed
        flows = {
            c: x.get(self._v_F_in(c), 0.0)
            for c in self.components if c in _KNOWN
        }
        if sum(flows.values()) < 1e-12:
            return 1.4
        T_in = x.get(self._v_T_in(), 600.0)
        Cp_mix = mixture_cp_J_mol_K(flows, T_in, basis="molar_flow")
        return Cp_mix / (Cp_mix - _R_GAS) if Cp_mix > _R_GAS else 1.4

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        N = len(self.components)
        res = np.zeros(N + 3, dtype=float)

        T_in = x.get(self._v_T_in(), 600.0)
        P_in = max(x.get(self._v_P_in(), 5.0e6), 1e-3)
        T_out = x.get(self._v_T_out(), 400.0)
        P_out = max(x.get(self._v_P_out(), 1.0e6), 1e-3)
        W = x.get(self._v_W(), 0.0)

        F_in_total = sum(
            x.get(self._v_F_in(c), 0.0) for c in self.components
        )

        # Material balances — no composition change [N]
        for i, c in enumerate(self.components):
            res[i] = (
                x.get(self._v_F_out(c), 0.0)
                - x.get(self._v_F_in(c), 0.0)
            )

        # Isentropic expansion — for P_out < P_in, r_P < 1, T_out_isen < T_in [1]
        g = self._gamma(x)
        theta = (g - 1.0) / g
        r_P = P_out / P_in
        T_out_isen = T_in * (r_P ** theta)
        eta = self.params.eta_isentropic
        # Actual outlet temperature accounts for irreversibility: real T_out
        # is higher than T_out_isen (less cooling than ideal).
        T_out_actual = T_in - eta * (T_in - T_out_isen)
        res[N] = T_out - T_out_actual

        # Shaft work — positive when work is extracted [1]
        flows_in = {
            c: x.get(self._v_F_in(c), 0.0)
            for c in self.components if c in _KNOWN
        }
        Cp_mix = mixture_cp_J_mol_K(
            flows_in, 0.5 * (T_in + T_out), basis="molar_flow"
        )
        W_calc = max(F_in_total, 0.0) * Cp_mix * (T_in - T_out)
        res[N + 1] = W - W_calc

        # Pressure spec [1]
        if self.params.P_out_Pa is not None:
            res[N + 2] = P_out - self.params.P_out_Pa
        else:
            res[N + 2] = 0.0
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        """Electricity *credit* — negative coefficient since the expander
        generates power. Sign chosen so that maximising W shows up as a
        cost reduction in the OPEX objective."""
        p = self.params
        coeff_USD_per_W_yr = (
            p.electricity_price_USD_per_kWh * p.operating_hours_per_year / 1000.0
        )
        return {self._v_W(): -coeff_USD_per_W_yr}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        W = x.get(self._v_W(), 0.0)
        P_in = max(x.get(self._v_P_in(), 1e6), 1.0)
        P_out = max(x.get(self._v_P_out(), 1e5), 1.0)
        return {
            f"{uid}.W_shaft_W": W,
            f"{uid}.W_shaft_kW": W / 1000.0,
            f"{uid}.expansion_ratio": P_in / P_out,
            f"{uid}.T_out_K": x.get(self._v_T_out(), 0.0),
            f"{uid}.isentropic_efficiency_pct": self.params.eta_isentropic * 100.0,
            f"{uid}.opex_USD_per_yr": self.opex_per_year(x),
        }

    def capex(self, x: Dict[str, float]) -> float:
        """Turbo-expander purchase cost [USD, CE500 basis]. Reuses the
        SSLW turbine correlation since expander/turbine sizing is essentially
        the same as a gas-turbine generator at this fidelity level."""
        from pse_ecosystem.models.costing.sslw_costing import (
            turbine_purchase_cost_USD,
        )
        return turbine_purchase_cost_USD(max(x.get(self._v_W(), 0.0), 1.0))
