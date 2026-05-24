"""HDA Flash Separator — BaseUnit wrapper around the BB2 black-box.

Wilson VLE / Rachford-Rice flash treated as a black box. 12 output variables
are constrained to equal the simulator outputs via residual equations.

Variables
---------
Inputs  (7): F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in, F_Diph_in [mol/s],
             T_FL [K], P_FL [Pa]
Outputs (12): 5 vapour flowrates + 5 liquid flowrates [mol/s],
              H_vap, H_liq [MJ/s]
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.models._blackbox.hda_flash_bb import HDA_Flash_sim
from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


class HDAFlashUnit(BaseUnit):
    """HDA flash separator wrapped as a BaseUnit. FD Jacobian (VLE black-box).

    Tagged ``LEGACY`` — superseded by the property-package-aware FlashVLHF
    (which now uses ideal-gas / PR / NRTL via the v1.6 thermo framework).
    Kept for existing flowsheet compatibility.
    """

    is_linear = False
    category = UnitCategory.LEGACY

    def __init__(self, unit_id: str = "hda_flash"):
        self.unit_id = unit_id
        self._cache_key: tuple | None = None
        self._cache_result: tuple | None = None

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def _input_vars(self) -> List[str]:
        p = self.unit_id
        return [f"{p}.F_H2_in", f"{p}.F_CH4_in", f"{p}.F_Tol_in",
                f"{p}.F_Benz_in", f"{p}.F_Diph_in", f"{p}.T_FL", f"{p}.P_FL"]

    @property
    def _output_vars(self) -> List[str]:
        p = self.unit_id
        return [
            f"{p}.F_H2_vap",  f"{p}.F_CH4_vap",  f"{p}.F_Tol_vap",
            f"{p}.F_Benz_vap", f"{p}.F_Diph_vap",
            f"{p}.F_H2_liq",  f"{p}.F_CH4_liq",  f"{p}.F_Tol_liq",
            f"{p}.F_Benz_liq", f"{p}.F_Diph_liq",
            f"{p}.H_vap", f"{p}.H_liq",
        ]

    def variables(self) -> List[str]:
        return self._input_vars + self._output_vars

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.unit_id
        b = {}
        for v in self._input_vars[:5]:
            b[v] = (0.0, 100.0)
        b[f"{p}.T_FL"] = (200.0, 600.0)
        b[f"{p}.P_FL"] = (1e4, 5e7)
        for v in self._output_vars[:10]:
            b[v] = (0.0, 100.0)
        b[f"{p}.H_vap"] = (-1e4, 1e4)
        b[f"{p}.H_liq"] = (-1e4, 1e4)
        return b

    # ── Physics ───────────────────────────────────────────────────────────

    def _simulate(self, x: Dict[str, float]) -> tuple:
        inputs = tuple(round(float(x.get(v, 0.0)), 6) for v in self._input_vars)
        if inputs != self._cache_key:
            self._cache_key    = inputs
            self._cache_result = HDA_Flash_sim(*[x.get(v, 0.0) for v in self._input_vars])
        return self._cache_result

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        sim_out = self._simulate(x)
        return np.array(
            [x.get(v, 0.0) - sim_out[k] for k, v in enumerate(self._output_vars)],
            dtype=float,
        )

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        p = self.unit_id
        vap_total = sum(x.get(f"{p}.F_{c}_vap", 0.0)
                        for c in ['H2', 'CH4', 'Tol', 'Benz', 'Diph'])
        feed_total = sum(x.get(f"{p}.F_{c}_in", 0.0)
                         for c in ['H2', 'CH4', 'Tol', 'Benz', 'Diph'])
        return {
            f"{p}.vapour_fraction": vap_total / max(feed_total, 1e-9),
            f"{p}.H_duty_MJ_s":     x.get(f"{p}.H_vap", 0.0) + x.get(f"{p}.H_liq", 0.0),
        }
