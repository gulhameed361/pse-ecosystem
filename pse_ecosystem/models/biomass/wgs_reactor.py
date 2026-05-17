"""WGSReactorHF — Water-Gas Shift reactor with equilibrium constraint.

Physics fixes vs. B-HYPSYS legacy code
---------------------------------------
* Single CO conversion variable X_CO drives BOTH CO and H2O depletion,
  enforcing 1:1 stoichiometry (Issue #8 fix).
* Temperature is a unit parameter decoupled from gasifier temperature —
  separate WGS operating point, typically 400 °C HTS (Issue #3 fix).
* Equilibrium constant Kp_WGS(T) applied to outlet composition (not inlet
  molar flows), with correct form for Δn=0 reaction (Issues #1, #2 fix).

Equilibrium correlation
-----------------------
  CO + H2O ⇌ CO2 + H2   (Δn = 0, pressure-independent)
  K_WGS(T) = exp(4300/T − 3.84)

Ports
-----
syngas_in   : 6-component gas (H2, CO, CO2, H2O, CH4, N2)
shifted_out : same species set

Variables (13 total)
--------------------
syngas_in.*  (6), shifted_out.* (6), X_CO (1)

Residuals (7)
-------------
f[0..5] : stoichiometric balance for each species outlet
f[6]    : K_WGS(T) · n_CO_out · n_H2O_out − n_CO2_out · n_H2_out = 0
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

_SYNGAS_COMPS = ["H2", "CO", "CO2", "H2O", "CH4", "N2"]
_SYNGAS_SPECIES = frozenset(_SYNGAS_COMPS)


def _kp_wgs(T_K: float) -> float:
    """K_WGS(T) = exp(4300/T - 3.84), valid ~600–1200 K."""
    return math.exp(4300.0 / T_K - 3.84)


class WGSReactorHF(BaseUnit):
    """High-temperature Water-Gas Shift reactor at equilibrium.

    Parameters
    ----------
    unit_id    : Unique identifier.
    T_wgs_C    : WGS reactor temperature [°C].  Default 400 °C (HTS range).
    """

    is_linear: bool = False

    def __init__(
        self,
        unit_id: str,
        T_wgs_C: float = 400.0,
    ) -> None:
        self.unit_id = unit_id
        self.T_K = T_wgs_C + 273.15

        self.syngas_in_port = StreamPort(
            unit_id=unit_id, tag="syngas_in",
            components=_SYNGAS_COMPS, has_T=False, has_P=False,
            phase="gas", species=_SYNGAS_SPECIES,
        )
        self.shifted_out_port = StreamPort(
            unit_id=unit_id, tag="shifted_out",
            components=_SYNGAS_COMPS, has_T=False, has_P=False,
            phase="gas", species=_SYNGAS_SPECIES,
        )

    # ── Variable helpers ──────────────────────────────────────────────────────

    def _in_vars(self) -> List[str]:
        return [f"{self.unit_id}.syngas_in.F_{c}" for c in _SYNGAS_COMPS]

    def _out_vars(self) -> List[str]:
        return [f"{self.unit_id}.shifted_out.F_{c}" for c in _SYNGAS_COMPS]

    def _xco_var(self) -> str:
        return f"{self.unit_id}.X_CO"

    def variables(self) -> List[str]:
        return self._in_vars() + self._out_vars() + [self._xco_var()]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        b: Dict[str, Tuple[float, float]] = {}
        for v in self._in_vars():
            b[v] = (0.0, 1e4)
        for v in self._out_vars():
            b[v] = (0.0, 1e4)
        b[self._xco_var()] = (0.01, 0.999)   # CO conversion 1–99.9%
        return b

    # ── Residuals ─────────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        uid = self.unit_id

        n_H2_in  = x.get(f"{uid}.syngas_in.F_H2",  0.0)
        n_CO_in  = x.get(f"{uid}.syngas_in.F_CO",  0.0)
        n_CO2_in = x.get(f"{uid}.syngas_in.F_CO2", 0.0)
        n_H2O_in = x.get(f"{uid}.syngas_in.F_H2O", 0.0)
        n_CH4_in = x.get(f"{uid}.syngas_in.F_CH4", 0.0)
        n_N2_in  = x.get(f"{uid}.syngas_in.F_N2",  0.0)

        n_H2_out  = x.get(f"{uid}.shifted_out.F_H2",  0.0)
        n_CO_out  = x.get(f"{uid}.shifted_out.F_CO",  0.0)
        n_CO2_out = x.get(f"{uid}.shifted_out.F_CO2", 0.0)
        n_H2O_out = x.get(f"{uid}.shifted_out.F_H2O", 0.0)
        n_CH4_out = x.get(f"{uid}.shifted_out.F_CH4", 0.0)
        n_N2_out  = x.get(f"{uid}.shifted_out.F_N2",  0.0)

        X_CO = x.get(self._xco_var(), 0.5)
        K_wgs = _kp_wgs(self.T_K)
        dn_CO = n_CO_in * X_CO   # moles of CO converted per second

        f = np.array([
            n_H2_out  - (n_H2_in  + dn_CO),                 # f[0]: H2 balance
            n_CO_out  - (n_CO_in  - dn_CO),                 # f[1]: CO balance
            n_CO2_out - (n_CO2_in + dn_CO),                 # f[2]: CO2 balance
            n_H2O_out - (n_H2O_in - dn_CO),                 # f[3]: H2O balance
            n_CH4_out - n_CH4_in,                            # f[4]: CH4 inert
            n_N2_out  - n_N2_in,                             # f[5]: N2 inert
            # f[6]: equilibrium — variable lower bounds enforce species ≥ 0
            # at the LP level, so the residual stays smooth in x. The
            # pre-v1.4.0 max(x, 1e-12) guards introduced a Jacobian kink at
            # the floor that the SLP linearisation could not see; audit H5.
            K_wgs * n_CO_out * n_H2O_out - n_CO2_out * n_H2_out,
        ], dtype=float)
        return f

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        X_CO = x.get(self._xco_var(), 0.0)
        n_H2_out = max(x.get(f"{uid}.shifted_out.F_H2", 0.0), 0.0)
        n_total = sum(
            max(x.get(f"{uid}.shifted_out.F_{c}", 0.0), 0.0)
            for c in _SYNGAS_COMPS
        )
        h2_pct = 100.0 * n_H2_out / n_total if n_total > 1e-12 else 0.0
        return {
            f"{uid}.CO_conversion_pct": X_CO * 100.0,
            f"{uid}.H2_pct_vol_out": h2_pct,
        }
