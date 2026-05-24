"""Toy two-component flash separator — non-linear unit model.

Binary VLE flash with a constant K-value (Raoult's law toy approximation).
K_A = y_A / x_A is treated as a fixed parameter to keep the model fully algebraic
without external property calls. This is appropriate for conceptual design and
SLP benchmarking; a temperature-dependent K should be used in rigorous models.

Variables
---------
{id}.F_in   total feed flowrate            [mol/s]
{id}.z_A    feed mole fraction of A        [-]
{id}.F_V    vapour product flowrate        [mol/s]
{id}.F_L    liquid product flowrate        [mol/s]
{id}.y_A    vapour mole fraction of A      [-]
{id}.x_A    liquid mole fraction of A      [-]

Degrees of freedom: 6 variables - 4 residuals = 2 DOF.
Pin F_in and z_A via flowsheet extra_equalities to get a fully determined system.

Residuals
---------
r0 = F_V + F_L - F_in                             (total mole balance)
r1 = y_A * F_V + x_A * F_L - z_A * F_in          (component A balance)
r2 = y_A - K_A_ref * x_A                          (K-value relation)
r3 = psi*(K_A_ref-1)*z_A / (1 + psi*(K_A_ref-1)) - (y_A - z_A)
     where psi = F_V / max(F_in, 1e-9)            (Rachford-Rice consistency)

r3 ensures the overall flash balance is consistent with the K-value and prevents
degenerate solutions where r0-r2 are satisfied but y_A = z_A (trivial split).
The Jacobian is computed via the base-class FD fallback.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


class FlashToy(BaseUnit):
    """Non-linear toy flash separator. Jacobian via FD (base-class default)."""

    is_linear = False
    category = UnitCategory.DIDACTIC

    def __init__(self, unit_id: str = "flash", K_A_ref: float = 2.0):
        self.unit_id = unit_id
        self.K_A_ref = float(K_A_ref)

    # ── Variable namespace ────────────────────────────────────────────────

    @property
    def v_F_in(self) -> str:
        return f"{self.unit_id}.F_in"

    @property
    def v_z_A(self) -> str:
        return f"{self.unit_id}.z_A"

    @property
    def v_F_V(self) -> str:
        return f"{self.unit_id}.F_V"

    @property
    def v_F_L(self) -> str:
        return f"{self.unit_id}.F_L"

    @property
    def v_y_A(self) -> str:
        return f"{self.unit_id}.y_A"

    @property
    def v_x_A(self) -> str:
        return f"{self.unit_id}.x_A"

    def variables(self) -> List[str]:
        return [self.v_F_in, self.v_z_A, self.v_F_V, self.v_F_L, self.v_y_A, self.v_x_A]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self.v_F_in: (0.0, 1e6),
            self.v_z_A:  (0.0, 1.0),
            self.v_F_V:  (0.0, 1e6),
            self.v_F_L:  (0.0, 1e6),
            self.v_y_A:  (0.0, 1.0),
            self.v_x_A:  (0.0, 1.0),
        }

    # ── Physics ───────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        K   = self.K_A_ref
        F_in = x.get(self.v_F_in, 0.0)
        z_A  = x.get(self.v_z_A,  0.0)
        F_V  = x.get(self.v_F_V,  0.0)
        F_L  = x.get(self.v_F_L,  0.0)
        y_A  = x.get(self.v_y_A,  0.0)
        x_A  = x.get(self.v_x_A,  0.0)

        F_safe = max(F_in, 1e-9)
        psi    = F_V / F_safe  # vapour fraction

        # Rachford-Rice: psi*(K-1)*z_A / (1 + psi*(K-1)) = y_A - z_A
        denom_rr = 1.0 + psi * (K - 1.0)
        rr_lhs   = psi * (K - 1.0) * z_A / max(denom_rr, 1e-9)

        return np.array([
            F_V + F_L - F_in,                     # r0: total balance
            y_A * F_V + x_A * F_L - z_A * F_in,  # r1: component balance
            y_A - K * x_A,                        # r2: K-value
            rr_lhs - (y_A - z_A),                 # r3: Rachford-Rice
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        F_in = x.get(self.v_F_in, 0.0)
        z_A  = x.get(self.v_z_A,  0.0)
        F_V  = x.get(self.v_F_V,  0.0)
        y_A  = x.get(self.v_y_A,  0.0)
        F_safe = max(F_in, 1e-9)
        za_safe = max(z_A * F_in, 1e-9)
        return {
            f"{self.unit_id}.vapor_fraction": F_V / F_safe,
            f"{self.unit_id}.recovery_A":     y_A * F_V / za_safe,
        }
