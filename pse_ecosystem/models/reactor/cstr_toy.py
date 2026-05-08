"""Toy CSTR — non-linear unit model.

Steady-state continuous stirred-tank reactor for first-order irreversible A -> B.
The concentration of A is approximated as F_A_out / F_total_nom (lumped, volumetric
concentration not tracked; suitable for relative sizing studies).

Variables
---------
{id}.F_A_in      A inlet  molar flowrate [mol/s]
{id}.F_A_out     A outlet molar flowrate [mol/s]
{id}.F_B_out     B outlet molar flowrate [mol/s]
{id}.V_reactor   reactor volume          [m3]

Residuals (2 equations, 2 DOF — fix F_A_in and V_reactor via flowsheet)
---------
r0 = F_A_in - F_A_out - k * V_reactor * (F_A_out / F_total_nom)
r1 = F_B_out - k * V_reactor * (F_A_out / F_total_nom)

The non-linearity is the bilinear product V_reactor * F_A_out.

Analytical Jacobian supplied — avoids FD cost for a clean 2x4 matrix.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess
from pse_ecosystem.models.base_unit import BaseUnit


class CSTRToy(BaseUnit):
    """Non-linear toy CSTR with analytical Jacobian."""

    is_linear = False
    trust_region = 50.0  # m3 — keep reactor volume steps bounded

    def __init__(
        self,
        unit_id: str = "cstr",
        k: float = 0.5,
        F_total_nom: float = 10.0,
    ):
        self.unit_id = unit_id
        self.k = float(k)
        self.F_total_nom = float(F_total_nom)

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def v_F_A_in(self) -> str:
        return f"{self.unit_id}.F_A_in"

    @property
    def v_F_A_out(self) -> str:
        return f"{self.unit_id}.F_A_out"

    @property
    def v_F_B_out(self) -> str:
        return f"{self.unit_id}.F_B_out"

    @property
    def v_V(self) -> str:
        return f"{self.unit_id}.V_reactor"

    def variables(self) -> List[str]:
        return [self.v_F_A_in, self.v_F_A_out, self.v_F_B_out, self.v_V]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self.v_F_A_in:  (0.0, 1000.0),
            self.v_F_A_out: (0.0, 1000.0),
            self.v_F_B_out: (0.0, 1000.0),
            self.v_V:       (0.001, 500.0),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        F_Ain  = x.get(self.v_F_A_in,  0.0)
        F_Aout = x.get(self.v_F_A_out, 0.0)
        F_Bout = x.get(self.v_F_B_out, 0.0)
        V      = x.get(self.v_V,       1.0)
        rate   = self.k * V * (F_Aout / self.F_total_nom)
        return np.array([
            F_Ain - F_Aout - rate,   # r0: A balance
            F_Bout - rate,           # r1: B balance
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        F_Ain  = x.get(self.v_F_A_in,  0.0)
        F_Aout = x.get(self.v_F_A_out, 0.0)
        V      = x.get(self.v_V,       1.0)
        conv   = 1.0 - F_Aout / max(F_Ain, 1e-9)
        Da     = self.k * V / self.F_total_nom
        return {
            f"{self.unit_id}.conversion":   max(conv, 0.0),
            f"{self.unit_id}.Damkohler_Da": Da,
        }

    # ── Analytical linearisation ──────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        variables = self.variables()
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)

        F_Aout0 = x0_dict[self.v_F_A_out]
        V0      = x0_dict[self.v_V]
        k       = self.k
        Fnom    = self.F_total_nom

        # Column order: [F_A_in, F_A_out, F_B_out, V_reactor]
        # r0 = F_Ain - F_Aout - k*V*(F_Aout/Fnom)
        # dr0/dF_Ain  = 1
        # dr0/dF_Aout = -(1 + k*V0/Fnom)
        # dr0/dF_Bout = 0
        # dr0/dV      = -k*F_Aout0/Fnom
        # r1 = F_Bout - k*V*(F_Aout/Fnom)
        # dr1/dF_Ain  = 0
        # dr1/dF_Aout = -k*V0/Fnom
        # dr1/dF_Bout = 1
        # dr1/dV      = -k*F_Aout0/Fnom
        J = np.array([
            [1.0,  -(1.0 + k * V0 / Fnom),  0.0,  -k * F_Aout0 / Fnom],
            [0.0,  -k * V0 / Fnom,           1.0,  -k * F_Aout0 / Fnom],
        ], dtype=float)

        f0 = self.residual(x0_dict)

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=False,
            trust_region=self.trust_region,
        )
