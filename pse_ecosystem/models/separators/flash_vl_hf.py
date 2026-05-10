"""High-fidelity vapour-liquid flash (V/L).

Uses Antoine K-values (temperature- and pressure-dependent) with Rachford-Rice
phase equilibrium. Supports isothermal (T specified) and adiabatic (Q=0) modes.

Physics correction vs. FlashToy
---------------------------------
FlashToy uses constant K-values independent of T and P.  This unit uses
K_i(T, P) = P_sat_i(T) / P  (Raoult's Law + Antoine), which is the correct
formulation for ideal VLE and is the first step toward rigorous VLE.

Ports
-----
inlet   : StreamPort  (F_i_feed, T_feed, P_feed)
vapor   : StreamPort  (F_i_vap, T_vap, P_vap)
liquid  : StreamPort  (F_i_liq, T_liq, P_liq)

Additional variables
---------------------
V_frac  : vapour mole fraction [-]
Q       : heat duty [W]  (positive = heat added)

Residuals (2N + 4 equations)
------------------------------
  Material  :  F_i_feed - F_i_vap - F_i_liq = 0         [N]
  VLE       :  y_i - K_i(T_vap, P_vap) * x_i = 0        [N]
               where y_i = F_i_vap / Σ_j F_j_vap
                     x_i = F_i_liq / Σ_j F_j_liq
  Energy    :  Q + H_feed - H_vap - H_liq = 0            [1]
  Pressure  :  P_vap - P_feed = 0, P_liq - P_feed = 0   [2]
  V_frac def:  V_frac - Σ F_i_vap / Σ F_i_feed = 0      [1]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, SHOMATE
from pse_ecosystem.models.properties.vle import K_value, rachford_rice

_KNOWN = set(SHOMATE.keys())
_SMALL = 1e-12  # floor to avoid division by zero


@dataclass
class FlashVLHFParams:
    species_vle: List[str]   # species that participate in VLE (must be in ANTOINE)
    feed_max: float = 1e4   # mol/s
    T_min: float = 250.0
    T_max: float = 550.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e9      # W


class FlashVLHF(BaseUnit):
    """Rigorous V/L flash with Antoine K-values and Rachford-Rice."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: FlashVLHFParams):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        self.inlet_port = StreamPort(unit_id, "inlet", components)
        self.vapor_port = StreamPort(unit_id, "vapor", components)
        self.liquid_port = StreamPort(unit_id, "liquid", components)

    def _v_F(self, tag: str, c: str) -> str: return f"{self.unit_id}.{tag}.F_{c}"
    def _v_T(self, tag: str) -> str: return f"{self.unit_id}.{tag}.T"
    def _v_P(self, tag: str) -> str: return f"{self.unit_id}.{tag}.P"
    def _v_Vfrac(self) -> str: return f"{self.unit_id}.V_frac"
    def _v_Q(self) -> str: return f"{self.unit_id}.Q"

    def variables(self) -> List[str]:
        vlist = []
        for tag in ("inlet", "vapor", "liquid"):
            for c in self.components:
                vlist.append(self._v_F(tag, c))
            vlist += [self._v_T(tag), self._v_P(tag)]
        vlist += [self._v_Vfrac(), self._v_Q()]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for tag in ("inlet", "vapor", "liquid"):
            for c in self.components:
                bds[self._v_F(tag, c)] = (0.0, p.feed_max)
            bds[self._v_T(tag)] = (p.T_min, p.T_max)
            bds[self._v_P(tag)] = (p.P_min, p.P_max)
        bds[self._v_Vfrac()] = (0.0, 1.0)
        bds[self._v_Q()] = (-p.Q_max, p.Q_max)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(2 * N + 4, dtype=float)

        F_feed = np.array([x.get(self._v_F("inlet", c), 0.0) for c in comps])
        F_vap  = np.array([x.get(self._v_F("vapor",  c), 0.0) for c in comps])
        F_liq  = np.array([x.get(self._v_F("liquid", c), 0.0) for c in comps])

        T_feed = x.get(self._v_T("inlet"), 350.0)
        T_vap  = x.get(self._v_T("vapor"), 350.0)
        T_liq  = x.get(self._v_T("liquid"), 350.0)
        P_feed = x.get(self._v_P("inlet"), 101325.0)
        P_vap  = x.get(self._v_P("vapor"), 101325.0)
        P_liq  = x.get(self._v_P("liquid"), 101325.0)
        Q      = x.get(self._v_Q(), 0.0)
        V_frac = x.get(self._v_Vfrac(), 0.5)

        F_vap_total = max(float(F_vap.sum()), _SMALL)
        F_liq_total = max(float(F_liq.sum()), _SMALL)
        F_feed_total = max(float(F_feed.sum()), _SMALL)

        y = F_vap / F_vap_total  # vapour mole fractions
        xi = F_liq / F_liq_total  # liquid mole fractions

        # Material balances [N]
        res[:N] = F_feed - F_vap - F_liq

        # VLE: y_i = K_i(T_vap, P_vap) * x_i  [N]
        for i, c in enumerate(comps):
            if c in self.params.species_vle:
                K_i = K_value(c, T_vap, P_vap)
            else:
                K_i = 1.0  # non-VLE species: equal distribution
            res[N + i] = y[i] - K_i * xi[i]

        # Energy balance [1]
        H_feed = sum(F_feed[i] * enthalpy_J_mol(c, T_feed) for i, c in enumerate(comps) if c in _KNOWN)
        H_vap  = sum(F_vap[i]  * enthalpy_J_mol(c, T_vap)  for i, c in enumerate(comps) if c in _KNOWN)
        H_liq  = sum(F_liq[i]  * enthalpy_J_mol(c, T_liq)  for i, c in enumerate(comps) if c in _KNOWN)
        res[2 * N] = Q + H_feed - H_vap - H_liq

        # Pressure equalities [2]
        res[2 * N + 1] = P_vap - P_feed
        res[2 * N + 2] = P_liq - P_feed

        # Vapour fraction definition [1]
        res[2 * N + 3] = V_frac - F_vap_total / F_feed_total

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        V_frac = x.get(self._v_Vfrac(), float("nan"))
        F_vap_total = sum(x.get(self._v_F("vapor", c), 0.0) for c in self.components)
        F_liq_total = sum(x.get(self._v_F("liquid", c), 0.0) for c in self.components)
        return {
            "V_frac": V_frac,
            "vapor_flow_mol_s": F_vap_total,
            "liquid_flow_mol_s": F_liq_total,
            "Q_W": x.get(self._v_Q(), 0.0),
        }
