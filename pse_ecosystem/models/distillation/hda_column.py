"""HDA Distillation Train — BaseUnit wrapper around the BB3 black-box.

FUG shortcut two-column train treated as a black box. 5 output variables
are constrained to equal the simulator outputs via residual equations.

Variables
---------
Inputs  (5): F_Benz_in, F_Tol_in, F_Diph_in [mol/s], RR2 [-], RR3 [-]
Outputs (5): F_Benz_product, F_Tol_recycle, F_Diph_out [mol/s], Q_T2, Q_T3 [MJ/s]
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.models._blackbox.hda_distillation_bb import HDA_Distillation_sim
from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


class HDADistillationUnit(BaseUnit):
    """HDA two-column distillation train wrapped as a BaseUnit. FD Jacobian.

    Tagged ``LEGACY`` — superseded by the native ``DistillationHF`` (FUG
    shortcut, screening) plus the forthcoming ``TrayColumnHF`` (rigorous
    MESH). Kept for existing flowsheet compatibility.
    """

    is_linear = False
    category = UnitCategory.LEGACY

    def __init__(self, unit_id: str = "hda_dist"):
        self.unit_id = unit_id
        self._cache_key: tuple | None = None
        self._cache_result: tuple | None = None

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def _input_vars(self) -> List[str]:
        p = self.unit_id
        return [f"{p}.F_Benz_in", f"{p}.F_Tol_in", f"{p}.F_Diph_in",
                f"{p}.RR2", f"{p}.RR3"]

    @property
    def _output_vars(self) -> List[str]:
        p = self.unit_id
        return [f"{p}.F_Benz_product", f"{p}.F_Tol_recycle", f"{p}.F_Diph_out",
                f"{p}.Q_T2", f"{p}.Q_T3"]

    def variables(self) -> List[str]:
        return self._input_vars + self._output_vars

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.unit_id
        return {
            f"{p}.F_Benz_in":       (0.0, 100.0),
            f"{p}.F_Tol_in":        (0.0, 100.0),
            f"{p}.F_Diph_in":       (0.0, 100.0),
            f"{p}.RR2":             (1.0, 20.0),
            f"{p}.RR3":             (1.0, 20.0),
            f"{p}.F_Benz_product":  (0.0, 100.0),
            f"{p}.F_Tol_recycle":   (0.0, 100.0),
            f"{p}.F_Diph_out":      (0.0, 100.0),
            f"{p}.Q_T2":            (0.0, 1000.0),
            f"{p}.Q_T3":            (0.0, 1000.0),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    def _simulate(self, x: Dict[str, float]) -> tuple:
        inputs = tuple(round(float(x.get(v, 0.0)), 6) for v in self._input_vars)
        if inputs != self._cache_key:
            self._cache_key    = inputs
            self._cache_result = HDA_Distillation_sim(
                *[x.get(v, 0.0) for v in self._input_vars]
            )
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
        Q_total = x.get(f"{p}.Q_T2", 0.0) + x.get(f"{p}.Q_T3", 0.0)
        return {
            f"{p}.total_duty_MJ_s":  Q_total,
            f"{p}.F_Benz_product":   x.get(f"{p}.F_Benz_product", 0.0),
            f"{p}.F_Tol_recycle":    x.get(f"{p}.F_Tol_recycle",  0.0),
        }
