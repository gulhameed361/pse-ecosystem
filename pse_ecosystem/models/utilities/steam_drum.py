"""Saturated steam drum — utility steam balance for plant-wide flowsheets.

Mass and energy balance for a steam drum / boiler at fixed operating pressure
(saturation T set by P). Feedwater + heat input → saturated steam + blowdown.

    F_steam + F_blowdown = F_feedwater                [mass balance]
    Q + F_fw · h_fw       = F_steam · h_g  +
                            F_blowdown · h_f          [energy balance]
    T_drum                = T_sat(P_drum)             [saturation]
    F_blowdown            = blowdown_frac · F_feedwater

The drum operates at saturation, so the steam quality is 1 (dry-saturated)
unless ``superheat_K`` is set, in which case the steam enthalpy uses
``h_g + Cp_steam · superheat_K``.

Units
-----
Flows in kg/s, temperatures in K, pressures in Pa, enthalpies in kJ/kg,
duties in kW. We use a simple correlation for saturation properties:

    T_sat(P) ≈ A − B / (ln(P) − C)                    (Antoine inverse)
    h_f(T)   ≈ 4.186 × (T − 273.15)                    [liquid water Cp]
    h_g(T)   ≈ h_f + h_fg(T), h_fg ≈ 2257 − 2.55 × (T − 373.15)

These hold to ~3 % over 100–250 °C — adequate for plant-wide steam
balances. For tight design fidelity, replace with IAPWS-IF97 calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

# NIST Antoine for water, valid 304–470 K (covers 0.04–25 bar, the
# industrial steam-drum range): log10(P/bar) = A − B/(T + C).
_ANTOINE_A_WATER = 4.6543
_ANTOINE_B_WATER = 1435.264
_ANTOINE_C_WATER = -64.848
_CP_WATER_kJ_kg_K = 4.186
_CP_STEAM_kJ_kg_K = 2.0
_H_FG_REF_kJ_kg = 2257.0  # at 100 °C
_DH_FG_dT_kJ_kg_K = -2.55  # slope of h_fg vs T


def _T_sat_K(P_Pa: float) -> float:
    """Saturation temperature [K] at pressure P [Pa]. ±1 K over 0.04–25 bar."""
    P_bar = max(P_Pa, 1e3) / 1.0e5
    return (
        _ANTOINE_B_WATER
        / max(_ANTOINE_A_WATER - math.log10(P_bar), 1e-9)
        - _ANTOINE_C_WATER
    )


def _h_fg(T_K: float) -> float:
    return max(_H_FG_REF_kJ_kg + _DH_FG_dT_kJ_kg_K * (T_K - 373.15), 0.0)


@dataclass
class SteamDrumHFParams:
    P_op_Pa: float = 10.0e5
    """Drum operating pressure [Pa] — fixes saturation temperature."""
    blowdown_frac: float = 0.02
    """Continuous-blowdown fraction (typical 1–3% of feedwater) — purges
    accumulated dissolved solids to prevent scaling."""
    superheat_K: float = 0.0
    """Superheat above saturation [K]. ``0`` = dry-saturated steam."""
    T_fw_K: float = 333.15
    """Feedwater temperature [K] — default 60 °C (deaerator outlet)."""
    feed_max_kg_s: float = 100.0
    Q_max_kW: float = 1e7


class SteamDrumHF(BaseUnit):
    """Saturated steam drum with sensible/latent heat balance.

    Ports
    -----
    feedwater_in : single-component water inlet [kg/s]
    steam_out    : saturated/superheated steam outlet [kg/s]
    blowdown_out : liquid water blowdown [kg/s]

    Variables
    ---------
    feedwater_in.F_H2O, Q_kW, steam_out.F_H2O, blowdown_out.F_H2O
    """

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        params: Optional[SteamDrumHFParams] = None,
    ):
        self.unit_id = unit_id
        self.params = params or SteamDrumHFParams()
        self.feedwater_in_port = StreamPort(
            unit_id, "feedwater_in", components=["H2O"], phase="liquid",
        )
        self.steam_out_port = StreamPort(
            unit_id, "steam_out", components=["H2O"], phase="gas",
        )
        self.blowdown_out_port = StreamPort(
            unit_id, "blowdown_out", components=["H2O"], phase="liquid",
        )

    @property
    def _primary_inlet_port(self):
        return self.feedwater_in_port

    @property
    def _primary_outlet_port(self):
        return self.steam_out_port

    def _v_fw(self) -> str: return f"{self.unit_id}.feedwater_in.F_H2O"
    def _v_steam(self) -> str: return f"{self.unit_id}.steam_out.F_H2O"
    def _v_blow(self) -> str: return f"{self.unit_id}.blowdown_out.F_H2O"
    def _v_Q(self) -> str: return f"{self.unit_id}.Q_kW"

    def variables(self) -> List[str]:
        return [self._v_fw(), self._v_steam(), self._v_blow(), self._v_Q()]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        return {
            self._v_fw(): (0.0, p.feed_max_kg_s),
            self._v_steam(): (0.0, p.feed_max_kg_s),
            self._v_blow(): (0.0, p.feed_max_kg_s),
            self._v_Q(): (0.0, p.Q_max_kW),
        }

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        F_fw = max(x.get(self._v_fw(), 0.0), 0.0)
        F_steam = x.get(self._v_steam(), 0.0)
        F_blow = x.get(self._v_blow(), 0.0)
        Q = x.get(self._v_Q(), 0.0)

        T_sat = _T_sat_K(p.P_op_Pa)
        T_steam = T_sat + p.superheat_K
        h_fw = _CP_WATER_kJ_kg_K * (p.T_fw_K - 273.15)
        h_blow = _CP_WATER_kJ_kg_K * (T_sat - 273.15)
        h_steam = h_blow + _h_fg(T_sat) + _CP_STEAM_kJ_kg_K * p.superheat_K

        res = np.zeros(3, dtype=float)
        # Mass balance: F_steam + F_blow − F_fw = 0
        res[0] = F_steam + F_blow - F_fw
        # Energy balance [kW]: Q + F_fw·h_fw = F_steam·h_steam + F_blow·h_blow
        res[1] = Q + F_fw * h_fw - F_steam * h_steam - F_blow * h_blow
        # Blowdown spec
        res[2] = F_blow - p.blowdown_frac * F_fw
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        p = self.params
        T_sat = _T_sat_K(p.P_op_Pa)
        return {
            f"{uid}.T_sat_K": T_sat,
            f"{uid}.P_op_Pa": p.P_op_Pa,
            f"{uid}.steam_kg_s": x.get(self._v_steam(), 0.0),
            f"{uid}.blowdown_kg_s": x.get(self._v_blow(), 0.0),
            f"{uid}.Q_kW": x.get(self._v_Q(), 0.0),
            f"{uid}.superheat_K": p.superheat_K,
        }

    def capex(self, x: Dict[str, float]) -> float:
        """Drum + boiler purchase cost [USD, CE500 basis]. Six-tenths rule
        anchored at 250 k USD for a 1 t/h water-tube boiler. Towler-Sinnott
        Ch.17 Table 17.10 calibration."""
        F_fw = max(x.get(self._v_fw(), 0.1), 0.1)
        return 250_000.0 * (F_fw / 1.0) ** 0.6
