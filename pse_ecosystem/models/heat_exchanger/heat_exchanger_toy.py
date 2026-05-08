"""Toy shell-and-tube heat exchanger — non-linear unit model.

Hot fluid transfers heat Q to cold fluid. The non-linearity arises from the
Log Mean Temperature Difference (LMTD) in the rate equation.

Variables
---------
{id}.T_hot_in    hot-side inlet temperature   [K]
{id}.T_hot_out   hot-side outlet temperature  [K]
{id}.T_cold_in   cold-side inlet temperature  [K]
{id}.T_cold_out  cold-side outlet temperature [K]
{id}.Q           heat duty                    [W]

Residuals
---------
r0 = Q - m_hot  * Cp_hot  * (T_hot_in  - T_hot_out)
r1 = Q - m_cold * Cp_cold * (T_cold_out - T_cold_in)
r2 = Q - U * A * LMTD

where LMTD = (dT1 - dT2) / ln(dT1 / dT2)
      dT1  = T_hot_in  - T_cold_out   (hot end)
      dT2  = T_hot_out - T_cold_in    (cold end)
      (limit case dT1 == dT2: LMTD = dT1)

The LMTD in r2 is non-linear, so the SLP driver iterates. The Jacobian is
computed via the base-class finite-difference fallback (FD is accurate for
smooth LMTD with well-conditioned temperature differences).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class HeatExchangerToyParams:
    U: float = 500.0       # overall HTC  [W / (m2 K)]
    A: float = 10.0        # heat transfer area [m2]
    m_hot: float = 1.0     # hot-side mass flowrate  [kg/s]
    Cp_hot: float = 4186.0 # hot-side specific heat  [J / (kg K)]
    m_cold: float = 1.0    # cold-side mass flowrate [kg/s]
    Cp_cold: float = 4186.0


class HeatExchangerToy(BaseUnit):
    """Non-linear toy heat exchanger. Jacobian via FD (base-class default)."""

    is_linear = False
    trust_region = 20.0  # K — keep SLP steps local around current temperatures

    def __init__(
        self,
        unit_id: str = "hx",
        params: HeatExchangerToyParams | None = None,
    ):
        self.unit_id = unit_id
        self.params = params or HeatExchangerToyParams()

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def v_T_hot_in(self) -> str:
        return f"{self.unit_id}.T_hot_in"

    @property
    def v_T_hot_out(self) -> str:
        return f"{self.unit_id}.T_hot_out"

    @property
    def v_T_cold_in(self) -> str:
        return f"{self.unit_id}.T_cold_in"

    @property
    def v_T_cold_out(self) -> str:
        return f"{self.unit_id}.T_cold_out"

    @property
    def v_Q(self) -> str:
        return f"{self.unit_id}.Q"

    def variables(self) -> List[str]:
        return [
            self.v_T_hot_in, self.v_T_hot_out,
            self.v_T_cold_in, self.v_T_cold_out,
            self.v_Q,
        ]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self.v_T_hot_in:   (250.0, 800.0),
            self.v_T_hot_out:  (250.0, 800.0),
            self.v_T_cold_in:  (250.0, 800.0),
            self.v_T_cold_out: (250.0, 800.0),
            self.v_Q:          (0.0, 1e8),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    @staticmethod
    def _lmtd(T_hot_in: float, T_hot_out: float,
              T_cold_in: float, T_cold_out: float) -> float:
        dT1 = T_hot_in  - T_cold_out  # temperature difference at hot end
        dT2 = T_hot_out - T_cold_in   # temperature difference at cold end
        # Guard: temperatures must give positive driving forces for physical HX
        dT1 = max(dT1, 1e-4)
        dT2 = max(dT2, 1e-4)
        if abs(dT1 - dT2) < 1e-8:
            return dT1
        return (dT1 - dT2) / np.log(max(dT1 / dT2, 1e-8))

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        T_hi = x.get(self.v_T_hot_in,   0.0)
        T_ho = x.get(self.v_T_hot_out,  0.0)
        T_ci = x.get(self.v_T_cold_in,  0.0)
        T_co = x.get(self.v_T_cold_out, 0.0)
        Q    = x.get(self.v_Q,          0.0)

        lmtd = self._lmtd(T_hi, T_ho, T_ci, T_co)
        return np.array([
            Q - p.m_hot  * p.Cp_hot  * (T_hi - T_ho),   # r0: hot energy balance
            Q - p.m_cold * p.Cp_cold * (T_co - T_ci),   # r1: cold energy balance
            Q - p.U * p.A * lmtd,                        # r2: rate equation
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        p = self.params
        Q     = x.get(self.v_Q,         0.0)
        T_hi  = x.get(self.v_T_hot_in,  0.0)
        T_ci  = x.get(self.v_T_cold_in, 0.0)
        q_max = p.m_hot * p.Cp_hot * max(T_hi - T_ci, 1e-9)
        return {
            f"{self.unit_id}.Q_kW":        Q / 1e3,
            f"{self.unit_id}.effectiveness": Q / q_max,
        }
