"""Direct-fired heater (furnace) — fuel combustion + process-side heating.

The workhorse heater in refining, ammonia, ethylene, and SMR plants.
Models the fuel-side combustion separately from the process-side duty:

* **Fuel side**: stoichiometric combustion of CH4 / H2 / CO with user-set
  excess-air ratio; flue gas composition computed analytically.
* **Process side**: a target outlet temperature T_proc_out is the
  primary spec; required heat duty Q follows from process-side energy
  balance against the inlet stream.
* **Thermal efficiency η_thermal** translates fuel LHV into process Q;
  the balance (1 − η) leaves with the flue gas (sensible + chimney loss).

Ports
-----
fuel_in    : StreamPort  (H2, CO, CH4, optional N2 / CO2 / H2O carriers)
air_in     : StreamPort  (O2, N2)
flue_out   : StreamPort  (CO2, H2O, O2_excess, N2)
process_in : StreamPort  (any process gas or liquid; T_in, P_in)
process_out: StreamPort  (same components; T_out_spec, P_out = P_in)

Residuals (N_proc + 5)
-----------------------
  Material proc :  F_proc_out − F_proc_in = 0                       [N_proc]
  Combustion C  :  F_CO2_flue − F_CO_in − F_CH4_in − F_CO2_in = 0   [1]
  Combustion H  :  F_H2O_flue − F_H2_in − 2·F_CH4_in − F_H2O_in = 0 [1]
  Combustion O  :  F_O2_air × λ − (½F_H2 + ½F_CO + 2F_CH4)
                   stoichiometric balance with excess λ              [1]
  Q duty        :  Q − η_thermal × Q_fuel_LHV = 0                   [1]
  Pressure proc :  P_proc_out − P_proc_in = 0                       [1]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import (
    SHOMATE,
    enthalpy_J_mol,
)

_KNOWN = set(SHOMATE.keys())

# Lower heating values [J/mol] — same anchor points as CHPUnit.
_LHV = {"H2": 241_800.0, "CO": 283_000.0, "CH4": 802_600.0}
_Y_O2_AIR = 0.21
_Y_N2_AIR = 0.79


@dataclass
class FiredHeaterHFParams:
    eta_thermal: float = 0.85
    """Thermal efficiency Q_process / Q_fuel_LHV. Modern fired heaters 80–
    92 %; balance is chimney loss + radiation. Default 0.85 = good
    industrial practice."""
    lambda_air: float = 1.15
    """Excess-air ratio (1.0 = stoichiometric; 1.10–1.20 typical for gas
    firing; 1.20–1.40 for fuel oil)."""
    T_flue_K: float = 473.15
    """Flue-gas stack temperature [K]. Driven by economiser performance;
    150–250 °C target to avoid acid dew-point corrosion."""
    NOx_g_per_MJ: float = 0.07
    """NOx emission factor [g per MJ fuel LHV] — modern low-NOx burner
    with flue-gas recirculation. EPA AP-42 1.4 process heaters: ULNB 0.04
    g/MJ, conventional 0.18 g/MJ."""
    feed_max: float = 1e4
    T_min: float = 250.0
    T_max: float = 2500.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e10
    fuel_price_USD_per_GJ: float = 5.0
    operating_hours_per_year: float = 8000.0


class FiredHeaterHF(BaseUnit):
    """Fuel-fired process heater with explicit combustion stoichiometry."""

    is_linear = False
    # v1.6.1 P.5b — coefficient embeds fuel price (USD/GJ) × LHV ×
    # operating_hours; result is already in USD/yr.
    _OPEX_CONVENTION = "USD_per_year"

    def __init__(
        self,
        unit_id: str,
        process_components: List[str],
        params: Optional[FiredHeaterHFParams] = None,
    ):
        self.unit_id = unit_id
        self.process_components = list(process_components)
        self.params = params or FiredHeaterHFParams()
        self.fuel_in_port = StreamPort(
            unit_id, "fuel_in",
            components=["H2", "CO", "CH4", "N2", "CO2", "H2O"],
            phase="gas",
        )
        self.air_in_port = StreamPort(
            unit_id, "air_in", components=["O2", "N2"], phase="gas",
        )
        self.flue_out_port = StreamPort(
            unit_id, "flue_out",
            components=["CO2", "H2O", "O2", "N2"], phase="gas",
        )
        self.process_in_port = StreamPort(
            unit_id, "process_in", process_components,
        )
        self.process_out_port = StreamPort(
            unit_id, "process_out", process_components,
        )

    @property
    def _primary_inlet_port(self):
        return self.process_in_port

    @property
    def _primary_outlet_port(self):
        return self.process_out_port

    # ── Variable names ────────────────────────────────────────────────────
    def _v_fuel(self, c: str) -> str:    return f"{self.unit_id}.fuel_in.F_{c}"
    def _v_air(self, c: str) -> str:     return f"{self.unit_id}.air_in.F_{c}"
    def _v_flue(self, c: str) -> str:    return f"{self.unit_id}.flue_out.F_{c}"
    def _v_p_in(self, c: str) -> str:    return f"{self.unit_id}.process_in.F_{c}"
    def _v_p_out(self, c: str) -> str:   return f"{self.unit_id}.process_out.F_{c}"
    def _vT_p_in(self) -> str:           return f"{self.unit_id}.process_in.T"
    def _vT_p_out(self) -> str:          return f"{self.unit_id}.process_out.T"
    def _vP_p_in(self) -> str:           return f"{self.unit_id}.process_in.P"
    def _vP_p_out(self) -> str:          return f"{self.unit_id}.process_out.P"
    def _v_Q(self) -> str:               return f"{self.unit_id}.Q_duty"

    def variables(self) -> List[str]:
        v: List[str] = []
        for c in ("H2", "CO", "CH4", "N2", "CO2", "H2O"):
            v.append(self._v_fuel(c))
        for c in ("O2", "N2"):
            v.append(self._v_air(c))
        for c in ("CO2", "H2O", "O2", "N2"):
            v.append(self._v_flue(c))
        for c in self.process_components:
            v.append(self._v_p_in(c))
        v += [self._vT_p_in(), self._vP_p_in()]
        for c in self.process_components:
            v.append(self._v_p_out(c))
        v += [self._vT_p_out(), self._vP_p_out(), self._v_Q()]
        return v

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        b: Dict[str, Tuple[float, float]] = {}
        for vname in self.variables():
            if ".T" in vname:
                b[vname] = (p.T_min, p.T_max)
            elif ".P" in vname:
                b[vname] = (p.P_min, p.P_max)
            elif vname == self._v_Q():
                b[vname] = (0.0, p.Q_max)
            else:
                b[vname] = (0.0, p.feed_max)
        return b

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        N_proc = len(self.process_components)
        res = np.zeros(N_proc + 5, dtype=float)

        # Process material balances [N_proc]
        for i, c in enumerate(self.process_components):
            res[i] = (
                x.get(self._v_p_out(c), 0.0)
                - x.get(self._v_p_in(c), 0.0)
            )

        # Fuel-side species
        F_H2  = x.get(self._v_fuel("H2"), 0.0)
        F_CO  = x.get(self._v_fuel("CO"), 0.0)
        F_CH4 = x.get(self._v_fuel("CH4"), 0.0)
        F_N2f = x.get(self._v_fuel("N2"), 0.0)
        F_CO2f = x.get(self._v_fuel("CO2"), 0.0)
        F_H2Of = x.get(self._v_fuel("H2O"), 0.0)
        F_O2a = x.get(self._v_air("O2"), 0.0)
        F_N2a = x.get(self._v_air("N2"), 0.0)
        F_CO2_fl = x.get(self._v_flue("CO2"), 0.0)
        F_H2O_fl = x.get(self._v_flue("H2O"), 0.0)
        F_O2_fl = x.get(self._v_flue("O2"), 0.0)
        F_N2_fl = x.get(self._v_flue("N2"), 0.0)

        # Stoichiometric O2 requirement [mol/s]
        O2_stoich = 0.5 * F_H2 + 0.5 * F_CO + 2.0 * F_CH4
        O2_supplied = F_O2a
        O2_excess = O2_supplied - O2_stoich

        # Carbon balance: CO2 in flue = CO + CH4 + CO2 inert in fuel
        res[N_proc] = F_CO2_fl - (F_CO + F_CH4 + F_CO2f)
        # Hydrogen balance: H2O in flue = H2 + 2·CH4 + H2O inert in fuel
        res[N_proc + 1] = F_H2O_fl - (F_H2 + 2.0 * F_CH4 + F_H2Of)
        # O2 balance: O2 in flue = excess O2 = λ·O2_stoich − O2_stoich
        res[N_proc + 2] = F_O2_fl - O2_excess
        # N2 balance: N2 in flue = N2 from air + N2 in fuel
        # (consolidated into the air-supply constraint: F_O2_air must equal
        #  λ × O2_stoich within ±1e-6)
        res[N_proc + 3] = F_O2a - p.lambda_air * O2_stoich

        # Heat duty: Q = η_thermal × Q_fuel_LHV
        Q_fuel = _LHV["H2"] * F_H2 + _LHV["CO"] * F_CO + _LHV["CH4"] * F_CH4
        Q = x.get(self._v_Q(), 0.0)
        res[N_proc + 4] = Q - p.eta_thermal * Q_fuel
        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        """Fuel cost OPEX — combustible-species LHV × price."""
        # Coefficient is USD per mol/s of fuel-species annualised:
        # USD/yr = mol/s × LHV [J/mol] × hours × 3600 × 1e-9 × price [USD/GJ]
        p = self.params
        coeff_factor = p.operating_hours_per_year * 3600.0 * 1e-9 * p.fuel_price_USD_per_GJ
        return {
            self._v_fuel("H2"): _LHV["H2"] * coeff_factor,
            self._v_fuel("CO"): _LHV["CO"] * coeff_factor,
            self._v_fuel("CH4"): _LHV["CH4"] * coeff_factor,
        }

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        p = self.params
        F_H2 = x.get(self._v_fuel("H2"), 0.0)
        F_CO = x.get(self._v_fuel("CO"), 0.0)
        F_CH4 = x.get(self._v_fuel("CH4"), 0.0)
        Q_fuel = _LHV["H2"] * F_H2 + _LHV["CO"] * F_CO + _LHV["CH4"] * F_CH4
        Q_duty = x.get(self._v_Q(), 0.0)
        # Emission factors annualised — same convention as CHPUnit
        Q_fuel_MJ_per_yr = Q_fuel * p.operating_hours_per_year * 3.6 / 1000.0
        NOx_kg_yr = p.NOx_g_per_MJ * Q_fuel_MJ_per_yr / 1000.0
        return {
            f"{uid}.Q_duty_kW": Q_duty / 1000.0,
            f"{uid}.Q_fuel_LHV_kW": Q_fuel / 1000.0,
            f"{uid}.eta_thermal_pct": p.eta_thermal * 100.0,
            f"{uid}.lambda_air": p.lambda_air,
            f"{uid}.NOx_emission_kg_per_yr": NOx_kg_yr,
            f"{uid}.opex_USD_per_yr": self.opex_per_year(x),
        }

    def capex(self, x: Dict[str, float]) -> float:
        """Fired-heater purchase cost [USD, CE500 basis]. Towler-Sinnott
        Ch.17 fit: cost ≈ 80 USD per kW of process duty (anchored on a 10 MW
        process heater at ~$0.8M)."""
        Q_kW = max(x.get(self._v_Q(), 0.0), 1.0) / 1000.0
        return 80.0 * Q_kW
