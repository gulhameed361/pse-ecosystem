"""Counter-current packed column — absorber / stripper via NTU·HTU.

For a key solute being transferred between two phases (gas–liquid) the
column height is set by the number of transfer units required to
achieve the specified outlet composition:

    NTU = ∫ dy / (y − y*)            (dilute, linear equilibrium)

with the closed-form Colburn equation for linear equilibrium and constant
flows:

    NTU = (1 / (1 − A)) · ln[
            (y_in − A·x_in_solvent) / (y_out − A·x_in_solvent) · (1 − A) + A
          ]

where A = L / (m·V) is the absorption factor (m = slope of the
equilibrium line y* = m·x). For a stripper invert L ↔ V.

Limitations
-----------
* Single-key solute. Multi-solute requires a stage-by-stage MESH solve.
* Linear equilibrium (m constant). For curved equilibrium use Kremser-
  style stage-by-stage or rigorous MESH (TrayColumnHF).

This is the screening-grade model for CO₂ absorption, sour-gas treating,
SO₂ scrubbing, and other dilute mass-transfer applications.

Ports
-----
gas_in     : StreamPort  (rich gas feed)
gas_out    : StreamPort  (lean gas at top)
liquid_in  : StreamPort  (lean solvent at top)
liquid_out : StreamPort  (rich solvent at bottom)

The unit tracks one key solute; non-key species are passed through
unchanged. ``solute`` names the key component.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class PackedColumnHFParams:
    solute: str = "CO2"
    """Key transferred component."""
    m_eq: float = 0.5
    """Slope of equilibrium line y* = m·x (dimensionless mole fractions).
    For CO₂ in aqueous MEA at 313 K: m ≈ 0.1–0.5; in water: m ≈ 1500."""
    HTU_m: float = 0.6
    """Height of a transfer unit (HOG basis) [m]. Random packings: 0.3–0.8;
    structured packings: 0.2–0.5. Driven by L/V and packing surface area."""
    NTU_max: float = 50.0
    """Upper bound on NTU (used to size column height)."""
    diameter_m: float = 1.0
    """Column diameter [m] — exposed for CAPEX and pressure-drop estimate."""
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 500.0
    P_min: float = 1e3
    P_max: float = 1e7


class PackedColumnHF(BaseUnit):
    """Dilute-system NTU·HTU packed absorber / stripper."""

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        gas_components: List[str],
        liquid_components: List[str],
        params: Optional[PackedColumnHFParams] = None,
    ):
        self.unit_id = unit_id
        self.gas_components = list(gas_components)
        self.liquid_components = list(liquid_components)
        self.params = params or PackedColumnHFParams()
        # Both phases must include the solute species.
        assert self.params.solute in self.gas_components, (
            f"solute {self.params.solute!r} must be in gas_components"
        )
        self.gas_in_port = StreamPort(
            unit_id, "gas_in", gas_components, phase="gas",
        )
        self.gas_out_port = StreamPort(
            unit_id, "gas_out", gas_components, phase="gas",
        )
        self.liquid_in_port = StreamPort(
            unit_id, "liquid_in", liquid_components, phase="liquid",
        )
        self.liquid_out_port = StreamPort(
            unit_id, "liquid_out", liquid_components, phase="liquid",
        )

    def _v_g_in(self, c: str) -> str:  return f"{self.unit_id}.gas_in.F_{c}"
    def _v_g_out(self, c: str) -> str: return f"{self.unit_id}.gas_out.F_{c}"
    def _v_l_in(self, c: str) -> str:  return f"{self.unit_id}.liquid_in.F_{c}"
    def _v_l_out(self, c: str) -> str: return f"{self.unit_id}.liquid_out.F_{c}"
    def _v_NTU(self) -> str:           return f"{self.unit_id}.NTU"
    def _v_height(self) -> str:        return f"{self.unit_id}.Z_m"

    def variables(self) -> List[str]:
        v: List[str] = []
        for c in self.gas_components:
            v.append(self._v_g_in(c))
            v.append(self._v_g_out(c))
        for c in self.liquid_components:
            v.append(self._v_l_in(c))
            v.append(self._v_l_out(c))
        v += [self._v_NTU(), self._v_height()]
        return v

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        b: Dict[str, Tuple[float, float]] = {}
        for c in self.gas_components:
            b[self._v_g_in(c)] = (0.0, p.feed_max)
            b[self._v_g_out(c)] = (0.0, p.feed_max)
        for c in self.liquid_components:
            b[self._v_l_in(c)] = (0.0, p.feed_max)
            b[self._v_l_out(c)] = (0.0, p.feed_max)
        b[self._v_NTU()] = (0.0, p.NTU_max)
        b[self._v_height()] = (0.0, p.NTU_max * p.HTU_m)
        return b

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        """Mass balance + Colburn NTU equation."""
        p = self.params
        N_g = len(self.gas_components)
        N_l = len(self.liquid_components)
        # Residual rows: (N_g + N_l) material + NTU/height + Colburn eqn
        res = np.zeros(N_g + N_l + 2, dtype=float)

        # Material balance per gas component (non-solutes pass through)
        for i, c in enumerate(self.gas_components):
            F_in = x.get(self._v_g_in(c), 0.0)
            F_out = x.get(self._v_g_out(c), 0.0)
            # Solute balance picks up the transferred amount through the
            # solute-bearing liquid stream.
            if c == p.solute and c in self.liquid_components:
                # Solute removed from gas equals solute added to liquid
                F_l_in_sol = x.get(self._v_l_in(c), 0.0)
                F_l_out_sol = x.get(self._v_l_out(c), 0.0)
                res[i] = (F_out - F_in) + (F_l_out_sol - F_l_in_sol)
            else:
                res[i] = F_out - F_in

        # Liquid balance per component
        for j, c in enumerate(self.liquid_components):
            F_in = x.get(self._v_l_in(c), 0.0)
            F_out = x.get(self._v_l_out(c), 0.0)
            if c == p.solute:
                # Already coupled to gas above; this row stays zero by closure.
                res[N_g + j] = 0.0
            else:
                # Inert solvent passes through unchanged.
                res[N_g + j] = F_out - F_in

        # Colburn NTU equation (Treybal Ch. 6)
        # y_in, y_out: gas mole fractions of solute IN / OUT
        # x_in: liquid mole fraction of solute IN (the lean solvent at top)
        # A = L/(m·V)  (absorption factor; A > 1 ⇒ asymptotic absorption)
        F_g_in_total = max(
            sum(x.get(self._v_g_in(c), 0.0) for c in self.gas_components), 1e-9,
        )
        F_g_out_total = max(
            sum(x.get(self._v_g_out(c), 0.0) for c in self.gas_components), 1e-9,
        )
        F_l_in_total = max(
            sum(x.get(self._v_l_in(c), 0.0) for c in self.liquid_components),
            1e-9,
        )
        y_in = x.get(self._v_g_in(p.solute), 0.0) / F_g_in_total
        y_out = x.get(self._v_g_out(p.solute), 0.0) / F_g_out_total
        x_in_sol = (
            x.get(self._v_l_in(p.solute), 0.0) / F_l_in_total
            if p.solute in self.liquid_components else 0.0
        )
        A = F_l_in_total / max(p.m_eq * F_g_in_total, 1e-9)

        # Driving forces at top and bottom of column
        dy_top = max(y_out - p.m_eq * x_in_sol, 1e-9)
        # x at bottom of column from solute balance: F_g_in·y_in − F_g_out·y_out
        # = F_l_out·x_bot − F_l_in·x_in_sol  (transferred amount conservation)
        # Combine into the closed-form Colburn formula.
        # NTU_OG = (1/(1−1/A)) · ln[(1−1/A)·(y_in − m·x_in)/(y_out − m·x_in) + 1/A]
        ratio_in = max(y_in - p.m_eq * x_in_sol, 1e-9)
        ratio_out = dy_top
        if abs(A - 1.0) < 1e-6:
            NTU_calc = (ratio_in - ratio_out) / ratio_out  # L'Hopital limit
        else:
            inner = (1.0 - 1.0 / A) * (ratio_in / ratio_out) + 1.0 / A
            inner = max(inner, 1e-12)
            NTU_calc = math.log(inner) / (1.0 - 1.0 / A)

        NTU = x.get(self._v_NTU(), 1.0)
        Z = x.get(self._v_height(), p.HTU_m)
        res[N_g + N_l] = NTU - NTU_calc
        res[N_g + N_l + 1] = Z - NTU * p.HTU_m
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        p = self.params
        F_g_in_total = max(
            sum(x.get(self._v_g_in(c), 0.0) for c in self.gas_components), 1e-9,
        )
        F_g_out_total = max(
            sum(x.get(self._v_g_out(c), 0.0) for c in self.gas_components), 1e-9,
        )
        F_solute_in = x.get(self._v_g_in(p.solute), 0.0)
        F_solute_out = x.get(self._v_g_out(p.solute), 0.0)
        recovery_pct = (
            100.0 * (F_solute_in - F_solute_out) / max(F_solute_in, 1e-12)
        )
        return {
            f"{uid}.solute_removal_pct": recovery_pct,
            f"{uid}.NTU": x.get(self._v_NTU(), 0.0),
            f"{uid}.column_height_m": x.get(self._v_height(), 0.0),
            f"{uid}.diameter_m": p.diameter_m,
            f"{uid}.A_factor": F_g_in_total / max(p.m_eq * F_g_in_total, 1e-9)
                                * (1.0),  # exposed for diagnostics
        }

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Packed-column height from NTU·HTU, diameter from F-factor."""
        p = self.params
        NTU = max(x.get(self._v_NTU(), 1.0), 0.1)
        Z = NTU * p.HTU_m
        # Diameter from Sherwood-Eckert flooding correlation, simplified:
        # u_flood ≈ 1 m/s (random rings); design at 70% of flood.
        F_g = max(
            sum(x.get(self._v_g_in(c), 0.0) for c in self.gas_components),
            1e-9,
        )
        u_design = 0.7  # m/s
        # Assume 300 K, 1 atm for sizing — adequate for screening
        Q_vol = F_g * 8.314462 * 300.0 / 101325.0
        A_cross = Q_vol / u_design
        D_req = max(2.0 * math.sqrt(A_cross / math.pi), 0.2)
        return {
            "column_height_m": Z,
            "NTU": NTU,
            "HTU_m": p.HTU_m,
            "column_diameter_m_required": D_req,
            "column_diameter_m_specified": p.diameter_m,
        }

    def capex(self, x: Dict[str, float]) -> float:
        """Packed-column purchase cost [USD, CE500 basis] = empty shell +
        packing volume. Towler-Sinnott Ch.17 simple correlation."""
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD

        Z = max(x.get(self._v_height(), self.params.HTU_m), 0.5)
        D = self.params.diameter_m
        volume_m3 = math.pi * (D / 2.0) ** 2 * Z
        # Packing cost ≈ 1500 USD/m³ for random rings; structured 4–8× more.
        c_shell = vessel_purchase_cost_USD(max(volume_m3, 0.1))
        c_packing = 1500.0 * volume_m3
        return c_shell + c_packing
