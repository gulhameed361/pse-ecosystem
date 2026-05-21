"""BiomassStorageHF — drying and preheating unit.

Computes dry biomass outlet flow from wet feed and reports drying /
preheating thermal duties as KPIs.  The latent heat of evaporation is
included in the drying duty (Issue #13 fix from B-HYPSYS audit).

Ports
-----
wet_in  : StreamPort(phase="solid_dry", species={"Biomass_wet"}) — wet feed
dry_out : StreamPort(phase="solid_dry", species={"Biomass"})     — dry feed

Variables
---------
{uid}.wet_in.F_Biomass  [kg/s]  — total wet biomass feed (optimisation variable)
{uid}.dry_out.F_Biomass [kg/s]  — dried biomass leaving to gasifier

Residuals
---------
f[0] : dry_out.F_Biomass - wet_in.F_Biomass * (1 - MC) = 0

KPIs
----
Q_drying_kW      : thermal duty for drying [kW]
Q_preheating_kW  : sensible heat to preheat dry biomass to T_preheat [kW]
dry_feed_kg_s    : dry biomass feed rate [kg/s]
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.biomass.biomass_database import get_biomass


# Physical constants
_CP_WATER_kJ_kg_K = 4.186      # liquid water
_H_VAP_kJ_kg = 2257.0          # latent heat of vaporisation at 100 °C
_CP_STEAM_kJ_kg_K = 1.996      # steam at ~100 °C
_CP_BIOMASS_kJ_kg_K = 1.5      # generic dry biomass heat capacity


_SYNGAS_SPECIES = frozenset({"H2", "CO", "CO2", "H2O", "CH4", "N2"})


class BiomassStorageHF(BaseUnit):
    """Drying + preheating of wet biomass feed.

    Parameters
    ----------
    unit_id       : Unique identifier.
    biomass_type  : Key into BIOMASS_DB.
    T_in_C        : Ambient temperature of incoming biomass [°C].
    T_preheat_C   : Target preheat temperature for dry biomass [°C].
    """

    is_linear: bool = True   # single linear mass-balance residual

    def __init__(
        self,
        unit_id: str,
        biomass_type: str = "Pine Wood",
        T_in_C: float = 15.0,
        T_preheat_C: float = 200.0,
    ) -> None:
        self.unit_id = unit_id
        self.biomass_type = biomass_type
        self._b = get_biomass(biomass_type)
        self.MC = self._b["MC"]
        self.T_in_C = T_in_C
        self.T_preheat_C = T_preheat_C

        _wet_species = frozenset({"Biomass_wet"})
        _dry_species = frozenset({"Biomass"})

        self.wet_in_port = StreamPort(
            unit_id=unit_id, tag="wet_in",
            components=["Biomass"], has_T=False, has_P=False,
            phase="solid_dry", species=_wet_species,
        )
        self.dry_out_port = StreamPort(
            unit_id=unit_id, tag="dry_out",
            components=["Biomass"], has_T=False, has_P=False,
            phase="solid_dry", species=_dry_species,
        )

    @property
    def _primary_inlet_port(self):
        return self.wet_in_port

    @property
    def _primary_outlet_port(self):
        return self.dry_out_port

    # ── Variable names ────────────────────────────────────────────────────────

    def _v_wet(self) -> str:
        return f"{self.unit_id}.wet_in.F_Biomass"

    def _v_dry(self) -> str:
        return f"{self.unit_id}.dry_out.F_Biomass"

    def variables(self) -> List[str]:
        return [self._v_wet(), self._v_dry()]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self._v_wet(): (0.0, 1e3),
            self._v_dry(): (0.0, 1e3),
        }

    # ── Residuals ─────────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        F_wet = x.get(self._v_wet(), 0.0)
        F_dry = x.get(self._v_dry(), 0.0)
        # f[0]: dry flow = wet flow × (1 - MC)
        return np.array([F_dry - F_wet * (1.0 - self.MC)], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        F_wet = max(x.get(self._v_wet(), 0.0), 0.0)
        F_dry = F_wet * (1.0 - self.MC)
        m_moisture = F_wet * self.MC   # kg/s moisture

        # Drying duty: sensible (water to 100°C) + latent + sensible (steam to T_preheat)
        dT_liquid = max(100.0 - self.T_in_C, 0.0)
        dT_steam = max(self.T_preheat_C - 100.0, 0.0)
        Q_dry = m_moisture * (
            _CP_WATER_kJ_kg_K * dT_liquid + _H_VAP_kJ_kg + _CP_STEAM_kJ_kg_K * dT_steam
        )

        # Preheating duty: sensible heat for dry biomass from ~100°C to T_preheat
        Q_preheat = F_dry * _CP_BIOMASS_kJ_kg_K * max(self.T_preheat_C - 100.0, 0.0)

        return {
            f"{self.unit_id}.Q_drying_kW": Q_dry,
            f"{self.unit_id}.Q_preheating_kW": Q_preheat,
            f"{self.unit_id}.dry_feed_kg_s": F_dry,
        }
