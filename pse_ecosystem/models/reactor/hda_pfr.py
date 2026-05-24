"""HDA Plug-Flow Reactor — BaseUnit wrapper around the BB1 black-box.

The raw ODE-based simulator (HDA_Reactor_sim) is treated as a black box.
Each output variable is constrained to equal the corresponding simulator
output via a residual equation. The base-class FD Jacobian handles
linearisation automatically, so the SLP driver can use this unit like any
other algebraic model.

An instance-level cache prevents redundant ODE integrations within a single
linearise/evaluate call (2*n+1 residual evaluations for FD Jacobian).

Variables
---------
Inputs  (6): F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in [mol/s], T_in [K], V_R [m3]
Outputs (7): F_H2_out, F_CH4_out, F_Tol_out, F_Benz_out, F_Diph_out [mol/s],
             T_out [K], H_out [MJ/s]

Residuals (7): r_k = output_var_k - HDA_Reactor_sim(inputs)[k]
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.models._blackbox.hda_reactor_bb import HDA_Reactor_sim
from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


class HDAPFRUnit(BaseUnit):
    """HDA adiabatic PFR wrapped as a BaseUnit. FD Jacobian (ODE black-box).

    Tagged ``LEGACY`` — superseded by the native equation-oriented HDA
    tutorial built from PFRHF + new TrayColumnHF (Workstream B). Kept for
    existing flowsheet compatibility.
    """

    is_linear = False
    category = UnitCategory.LEGACY

    def __init__(self, unit_id: str = "hda_pfr"):
        self.unit_id = unit_id
        self._cache_key: tuple | None = None
        self._cache_result: tuple | None = None

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def _input_vars(self) -> List[str]:
        p = self.unit_id
        return [f"{p}.F_H2_in", f"{p}.F_CH4_in", f"{p}.F_Tol_in",
                f"{p}.F_Benz_in", f"{p}.T_in", f"{p}.V_R"]

    @property
    def _output_vars(self) -> List[str]:
        p = self.unit_id
        return [f"{p}.F_H2_out", f"{p}.F_CH4_out", f"{p}.F_Tol_out",
                f"{p}.F_Benz_out", f"{p}.F_Diph_out", f"{p}.T_out", f"{p}.H_out"]

    def variables(self) -> List[str]:
        return self._input_vars + self._output_vars

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.unit_id
        b = {}
        for v in [f"{p}.F_H2_in", f"{p}.F_CH4_in", f"{p}.F_Tol_in", f"{p}.F_Benz_in"]:
            b[v] = (0.0, 100.0)
        b[f"{p}.T_in"] = (300.0, 1300.0)
        b[f"{p}.V_R"]  = (0.1, 20.0)
        for v in [f"{p}.F_H2_out", f"{p}.F_CH4_out", f"{p}.F_Tol_out",
                  f"{p}.F_Benz_out", f"{p}.F_Diph_out"]:
            b[v] = (0.0, 100.0)
        b[f"{p}.T_out"] = (300.0, 1300.0)
        b[f"{p}.H_out"] = (-1e4, 1e4)
        return b

    # ── Physics ───────────────────────────────────────────────────────────

    def _simulate(self, x: Dict[str, float]) -> tuple:
        inputs = tuple(round(float(x.get(v, 0.0)), 6) for v in self._input_vars)
        if inputs != self._cache_key:
            self._cache_key    = inputs
            self._cache_result = HDA_Reactor_sim(*[x.get(v, 0.0) for v in self._input_vars])
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
        F_Tol_in  = max(x.get(f"{p}.F_Tol_in",  0.0), 1e-9)
        F_Tol_out = x.get(f"{p}.F_Tol_out", 0.0)
        F_Benz_out = x.get(f"{p}.F_Benz_out", 0.0)
        conv = 1.0 - F_Tol_out / F_Tol_in
        reacted = max(F_Tol_in - F_Tol_out, 1e-9)
        sel  = F_Benz_out / reacted
        return {
            f"{p}.toluene_conversion":  max(conv, 0.0),
            f"{p}.benzene_selectivity": min(max(sel, 0.0), 1.0),
            f"{p}.T_out_K":             x.get(f"{p}.T_out", 0.0),
        }
