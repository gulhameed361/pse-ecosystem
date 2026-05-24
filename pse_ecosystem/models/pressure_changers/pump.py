"""Incompressible liquid pump.

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Additional variable: W_shaft [W]

Residuals (N + 3 equations)
-----------------------------
  Material : F_i_out - F_i_in = 0                                [N]
  Work     : W_shaft - F_vol * (P_out - P_in) / η = 0           [1]
  Temp     : T_out - T_in = 0  (isothermal approximation)        [1]
  Pressure : (P_out is a free variable or fixed by params)        [1]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class PumpParams:
    eta_pump: float = 0.75
    density_kg_m3: float = 1000.0  # liquid density (water default)
    molar_mass_kg_mol: float = 0.018  # kg/mol (water default)
    P_out_Pa: Optional[float] = None
    feed_max: float = 1e4    # mol/s
    T_min: float = 250.0
    T_max: float = 600.0
    P_min: float = 1e3
    P_max: float = 1e8
    W_max: float = 1e9       # W
    electricity_price_USD_per_kWh: float = 0.05
    operating_hours_per_year: float = 8_000.0
    Psat_inlet_Pa: float = 2_339.0
    """Saturated vapour pressure of the liquid at the inlet temperature [Pa].
    Default = 2339 Pa = water at 20 °C. Drives NPSHa = (P_in − Psat)/(ρ·g).
    For tight industrial fidelity supply the actual value at the operating T
    (from a property package or DIPPR / Perry's correlation)."""
    NPSHr_m: float = 3.0
    """Manufacturer-quoted Net Positive Suction Head Required [m of fluid].
    Typical centrifugal pumps: 2–5 m. NPSHa must exceed this with margin
    (usually NPSHa − NPSHr ≥ 0.5–1 m) or cavitation will occur."""
    g_m_s2: float = 9.80665
    """Gravitational acceleration [m/s²]. Exposed so users at extreme
    latitudes or in centrifuge testbeds can override if desired."""


class Pump(BaseUnit):
    """Liquid pump with isentropic efficiency."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: Optional[PumpParams] = None):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or PumpParams()
        self.inlet_port  = StreamPort(unit_id, "inlet",  components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def _v_F_in(self, c: str)  -> str: return f"{self.unit_id}.inlet.F_{c}"
    def _v_T_in(self)          -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self)          -> str: return f"{self.unit_id}.inlet.P"
    def _v_F_out(self, c: str) -> str: return f"{self.unit_id}.outlet.F_{c}"
    def _v_T_out(self)         -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self)         -> str: return f"{self.unit_id}.outlet.P"
    def _v_W(self)             -> str: return f"{self.unit_id}.W_shaft"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.components:
            vlist.append(self._v_F_in(c))
        vlist += [self._v_T_in(), self._v_P_in()]
        for c in self.components:
            vlist.append(self._v_F_out(c))
        vlist += [self._v_T_out(), self._v_P_out(), self._v_W()]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for c in self.components:
            bds[self._v_F_in(c)]  = (0.0, p.feed_max)
            bds[self._v_F_out(c)] = (0.0, p.feed_max)
        bds[self._v_T_in()]  = (p.T_min, p.T_max)
        bds[self._v_P_in()]  = (p.P_min, p.P_max)
        bds[self._v_T_out()] = (p.T_min, p.T_max)
        bds[self._v_P_out()] = (p.P_min, p.P_max) if p.P_out_Pa is None else (p.P_out_Pa, p.P_out_Pa)
        bds[self._v_W()]     = (0.0, p.W_max)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(N + 3, dtype=float)

        T_in  = x.get(self._v_T_in(), 300.0)
        P_in  = x.get(self._v_P_in(), 101325.0)
        P_out = x.get(self._v_P_out(), 500000.0)
        T_out = x.get(self._v_T_out(), 300.0)
        W     = x.get(self._v_W(), 0.0)

        F_total = sum(x.get(self._v_F_in(c), 0.0) for c in comps)
        p = self.params
        # Volumetric flow [m³/s] = F_total [mol/s] * M [kg/mol] / ρ [kg/m³]
        V_vol = F_total * p.molar_mass_kg_mol / p.density_kg_m3

        # Material [N]
        for i, c in enumerate(comps):
            res[i] = x.get(self._v_F_out(c), 0.0) - x.get(self._v_F_in(c), 0.0)

        # Shaft work [1]
        W_ideal = V_vol * (P_out - P_in)
        res[N] = W - W_ideal / p.eta_pump

        # Temperature (isothermal) [1]
        res[N + 1] = T_out - T_in

        # Pressure spec [1]
        if p.P_out_Pa is not None:
            res[N + 2] = P_out - p.P_out_Pa
        else:
            res[N + 2] = 0.0

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        """Electricity cost [USD/yr] for shaft work."""
        p = self.params
        coeff_USD_per_W_yr = p.electricity_price_USD_per_kWh * p.operating_hours_per_year / 1000.0
        return {self._v_W(): coeff_USD_per_W_yr}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        W = x.get(self._v_W(), 0.0)
        P_in  = max(x.get(self._v_P_in(), 101325.0), 1.0)
        P_out = max(x.get(self._v_P_out(), 500000.0), 1.0)
        # Net Positive Suction Head Available [m of fluid]:
        # NPSHa = (P_in − P_sat(T_in)) / (ρ · g). Cavitation occurs when
        # NPSHa drops below NPSHr; the margin KPI exposes the safety buffer
        # so the operator can flag at-risk operating points before they
        # damage the impeller. v1.6 audit A.4.
        p = self.params
        NPSHa = max(P_in - p.Psat_inlet_Pa, 0.0) / (p.density_kg_m3 * p.g_m_s2)
        NPSHr = p.NPSHr_m
        return {
            f"{uid}.W_shaft_W":           W,
            f"{uid}.W_shaft_kW":          W / 1000.0,
            f"{uid}.compression_ratio":   P_out / P_in,
            f"{uid}.pump_efficiency_pct": p.eta_pump * 100.0,
            f"{uid}.NPSHa_m":             NPSHa,
            f"{uid}.NPSHr_m":             NPSHr,
            f"{uid}.NPSH_margin_m":       NPSHa - NPSHr,
            f"{uid}.cavitation_risk":     1.0 if NPSHa < NPSHr else 0.0,
            f"{uid}.opex_USD_per_yr":     self.opex_per_year(x),
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import pump_purchase_cost_USD
        return pump_purchase_cost_USD(x.get(self._v_W(), 0.0))

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required hydraulic head, shaft power, and NPSH margin.

        H = (P_out − P_in) / (ρ · g) [m]; W_shaft = ρ · g · H · Q / η;
        margin = NPSHa − NPSHr (positive ⇒ no cavitation).
        """
        p = self.params
        P_in = max(x.get(self._v_P_in(), 101325.0), 1.0)
        P_out = max(x.get(self._v_P_out(), 500000.0), 1.0)
        F_total = sum(x.get(self._v_F_in(c), 0.0) for c in self.components)
        V_vol = F_total * p.molar_mass_kg_mol / p.density_kg_m3  # m³/s
        head_m = (P_out - P_in) / (p.density_kg_m3 * p.g_m_s2)
        W_shaft_W = (
            p.density_kg_m3 * p.g_m_s2 * head_m * V_vol / max(p.eta_pump, 0.01)
        )
        NPSHa = max(P_in - p.Psat_inlet_Pa, 0.0) / (p.density_kg_m3 * p.g_m_s2)
        return {
            "head_required_m": head_m,
            "W_shaft_required_W": W_shaft_W,
            "V_flow_m3_per_s": V_vol,
            "NPSHa_m": NPSHa,
            "NPSHr_m": p.NPSHr_m,
            "NPSH_margin_m": NPSHa - p.NPSHr_m,
        }
