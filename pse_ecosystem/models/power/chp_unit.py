"""Combined Heat and Power (CHP) unit model.

Converts fuel energy (H₂, CO, CH₄ mix) into electricity via a gas turbine and
recoverable process heat via a Heat Recovery Steam Generator (HRSG).

The model is linear at fixed efficiency parameters — ``is_linear=True``.

Physics
-------
Fuel chemical input (raw, pre-combustor):
    Q_fuel = Σ_c (LHV_c × F_c)             [kW]

Combustor output (after combustion losses):
    Q_comb = η_comb × Q_fuel                [kW]

Electricity output (turbine + generator):
    W_elec = η_turb × Q_comb                [kW]
            = η_comb × η_turb × Q_fuel

Process heat (HRSG recovery from gas-turbine exhaust):
    Q_process = η_hrec × (Q_comb − W_elec)  [kW]
              = η_comb × (1 − η_turb) × η_hrec × Q_fuel

Audit N3 alignment (v1.4.0): the residual code computes ``W_elec`` and
``Q_process`` directly from the raw fuel input ``Q_fuel`` using the
collapsed coefficients ``_q_elec = η_comb × η_turb`` and
``_q_heat = η_comb × (1 − η_turb) × η_hrec``. The two formulations are
algebraically identical — earlier docstrings overloaded the symbol
``Q_comb`` between "pre-combustor raw fuel" and "post-combustor heat
release", which the audit flagged as a physics-mismatch. There is no
physics bug; this header now uses ``Q_fuel`` / ``Q_comb`` distinctly to
make the chain explicit.

Air stoichiometry (λ = excess air ratio):
    F_O2_air = λ × O2_stoich
    O2_stoich = 0.5·F_H2 + 0.5·F_CO + 2·F_CH4

Flue gas composition:
    F_CO2_flue = F_CO_in + F_CH4_in       [mol/s]
    F_H2O_flue = F_H2_in + 2·F_CH4_in    [mol/s]
    F_N2_flue  = F_N2_air                  [mol/s]
    F_O2_flue  = (λ−1) × O2_stoich        [mol/s — excess O2]

LHV values (kJ/mol, lower heating value):
    H₂:  241.8 kJ/mol
    CO:  283.0 kJ/mol
    CH₄: 802.6 kJ/mol
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

# Lower heating values [kJ/mol]
_LHV_H2  = 241.8
_LHV_CO  = 283.0
_LHV_CH4 = 802.6

# Air composition: 79% N2, 21% O2 by volume (mole fraction)
_Y_N2_AIR = 0.79
_Y_O2_AIR = 0.21


class CHPUnit(BaseUnit):
    """High-fidelity CHP model with analytical Jacobian.

    Parameters
    ----------
    unit_id :
        Unique identifier for this unit instance.
    eta_comb :
        Combustion efficiency (default 0.95).
    eta_isentropic :
        Turbine isentropic efficiency (default 0.85).
    eta_mechanical :
        Mechanical/generator efficiency (default 0.98).
    eta_hrec :
        Heat recovery efficiency (HRSG, default 0.85).
    lambda_air :
        Excess air ratio (1.0 = stoichiometric, default 1.1 = 10% excess).
    """

    is_linear: bool = True

    def __init__(
        self,
        unit_id: str,
        *,
        eta_comb: float = 0.95,
        eta_isentropic: float = 0.85,
        eta_mechanical: float = 0.98,
        eta_hrec: float = 0.85,
        lambda_air: float = 1.1,
        fuel_feed_max: float = 1e4,      # mol/s per species
        T_fuel_min: float = 273.0,       # K
        T_fuel_max: float = 1500.0,      # K
        P_fuel_min: float = 1e4,         # Pa (≈ 0.1 atm minimum)
        P_fuel_max: float = 5e6,         # Pa (≈ 50 atm max for gas turbine)
        W_max: float = 1e9,              # kW
    ):
        self.unit_id = unit_id
        self.lambda_air = lambda_air
        self._fuel_feed_max = fuel_feed_max
        self._T_fuel_min = T_fuel_min
        self._T_fuel_max = T_fuel_max
        self._P_fuel_min = P_fuel_min
        self._P_fuel_max = P_fuel_max
        self._W_max = W_max

        eta_turb = eta_isentropic * eta_mechanical
        self._q_elec = eta_comb * eta_turb
        self._q_heat = eta_comb * (1.0 - eta_turb) * eta_hrec

        # Fuel port now accepts full syngas species (H2, CO, CH4 combustible;
        # N2, CO2, H2O inert pass-through).  species=frozenset() skips port
        # species-mismatch validation so any syngas stream can connect.
        self.fuel_in_port = StreamPort(
            unit_id, "fuel_in",
            components=["H2", "CO", "CH4", "N2", "CO2", "H2O"],
            has_T=True, has_P=True,
            phase="gas",
            species=frozenset(),   # unconstrained — accept any gas mixture
        )
        self.air_in_port = StreamPort(
            unit_id, "air_in",
            components=["O2", "N2"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"O2", "N2"}),
        )
        self.flue_out_port = StreamPort(
            unit_id, "flue_out",
            components=["CO2", "H2O", "N2", "O2"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"CO2", "H2O", "N2", "O2"}),
        )

        uid = unit_id
        self._v_H2    = f"{uid}.fuel_in.F_H2"
        self._v_CO    = f"{uid}.fuel_in.F_CO"
        self._v_CH4   = f"{uid}.fuel_in.F_CH4"
        self._v_N2f   = f"{uid}.fuel_in.F_N2"    # inert N2 in fuel (e.g. syngas dilution)
        self._v_CO2f  = f"{uid}.fuel_in.F_CO2"   # inert CO2 in fuel (e.g. from gasifier)
        self._v_H2Of  = f"{uid}.fuel_in.F_H2O"   # moisture in fuel
        self._v_Tf    = f"{uid}.fuel_in.T"
        self._v_Pf    = f"{uid}.fuel_in.P"
        self._v_aO2   = f"{uid}.air_in.F_O2"
        self._v_aN2   = f"{uid}.air_in.F_N2"
        self._v_fCO2  = f"{uid}.flue_out.F_CO2"
        self._v_fH2O  = f"{uid}.flue_out.F_H2O"
        self._v_fN2   = f"{uid}.flue_out.F_N2"
        self._v_fO2   = f"{uid}.flue_out.F_O2"
        self._v_W     = f"{uid}.W_elec_kW"
        self._v_Q     = f"{uid}.Q_process_kW"

    @property
    def _primary_inlet_port(self):
        return self.fuel_in_port

    @property
    def _primary_outlet_port(self):
        return self.flue_out_port

    def variables(self) -> List[str]:
        return [
            self._v_H2, self._v_CO, self._v_CH4,
            self._v_N2f, self._v_CO2f, self._v_H2Of,
            self._v_Tf, self._v_Pf,
            self._v_aO2, self._v_aN2,
            self._v_fCO2, self._v_fH2O, self._v_fN2, self._v_fO2,
            self._v_W, self._v_Q,
        ]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        fm = self._fuel_feed_max
        return {
            self._v_H2:   (0.0, fm),
            self._v_CO:   (0.0, fm),
            self._v_CH4:  (0.0, fm),
            self._v_N2f:  (0.0, fm),
            self._v_CO2f: (0.0, fm),
            self._v_H2Of: (0.0, fm),
            self._v_Tf:  (self._T_fuel_min, self._T_fuel_max),
            self._v_Pf:  (self._P_fuel_min, self._P_fuel_max),  # Pa
            self._v_aO2: (0.0, 5e4),
            self._v_aN2: (0.0, 2e5),
            self._v_fCO2: (0.0, fm + fm),   # combustion + pass-through
            self._v_fH2O: (0.0, fm * 3),
            self._v_fN2:  (0.0, 2e5),
            self._v_fO2:  (0.0, 5e4),
            self._v_W:  (0.0, self._W_max),
            self._v_Q:  (0.0, self._W_max),
        }

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        g = x.get
        F_H2  = g(self._v_H2,   0.0)
        F_CO  = g(self._v_CO,   0.0)
        F_CH4 = g(self._v_CH4,  0.0)
        F_N2f = g(self._v_N2f,  0.0)   # inert N2 from fuel
        F_CO2f= g(self._v_CO2f, 0.0)   # inert CO2 from fuel
        F_H2Of= g(self._v_H2Of, 0.0)   # moisture from fuel
        lam = self.lambda_air
        o2_stoich = 0.5 * F_H2 + 0.5 * F_CO + 2.0 * F_CH4
        Q_comb = _LHV_H2 * F_H2 + _LHV_CO * F_CO + _LHV_CH4 * F_CH4

        return np.array([
            # r0: CO2 flue = combustion CO2 + pass-through CO2 from fuel
            g(self._v_fCO2, 0.0) - F_CO - F_CH4 - F_CO2f,
            # r1: H2O flue = combustion H2O + moisture pass-through
            g(self._v_fH2O, 0.0) - F_H2 - 2.0 * F_CH4 - F_H2Of,
            # r2: air O2 stoichiometry
            g(self._v_aO2, 0.0) - lam * o2_stoich,
            # r3: N2 flue = air N2 + fuel N2 pass-through
            g(self._v_fN2, 0.0) - g(self._v_aN2, 0.0) - F_N2f,
            # r4: excess O2 in flue
            g(self._v_fO2, 0.0) - (lam - 1.0) * o2_stoich,
            # r5: electricity
            g(self._v_W, 0.0) - self._q_elec * Q_comb,
            # r6: process heat
            g(self._v_Q, 0.0) - self._q_heat * Q_comb,
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        W = x.get(self._v_W, 0.0)
        Q = x.get(self._v_Q, 0.0)
        total = max(W + Q, 1e-9)
        F_H2  = x.get(self._v_H2, 0.0)
        F_CO  = x.get(self._v_CO, 0.0)
        F_CH4 = x.get(self._v_CH4, 0.0)
        Q_fuel = _LHV_H2 * F_H2 + _LHV_CO * F_CO + _LHV_CH4 * F_CH4
        return {
            f"{uid}.W_elec_kW":               W,
            f"{uid}.Q_process_kW":            Q,
            f"{uid}.total_useful_output_kW":  total,
            f"{uid}.power_to_heat_ratio":     W / max(Q, 1e-9),
            f"{uid}.electrical_efficiency_pct": self._q_elec * 100.0,
            f"{uid}.heat_efficiency_pct":     self._q_heat * 100.0,
            f"{uid}.fuel_LHV_input_kW":       Q_fuel,
            f"{uid}.combined_efficiency_pct": total / max(Q_fuel, 1e-9) * 100.0,
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import turbine_purchase_cost_USD
        W_kW = max(x.get(self._v_W, 0.0), 1.0)
        return turbine_purchase_cost_USD(W_kW * 1000.0)  # kW → W

    # ── Analytical linearise ──────────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        vnames = self.variables()
        idx = {v: j for j, v in enumerate(vnames)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in vnames}
        x0 = np.array([x0_dict[v] for v in vnames], dtype=float)
        f0 = self.residual(x0_dict)
        n = len(vnames)
        lam = self.lambda_air

        J = np.zeros((7, n), dtype=float)
        def ci(v): return idx[v]

        # r0: F_fCO2 - F_CO - F_CH4 - F_CO2f = 0
        J[0, ci(self._v_fCO2)] =  1.0
        J[0, ci(self._v_CO)]   = -1.0
        J[0, ci(self._v_CH4)]  = -1.0
        J[0, ci(self._v_CO2f)] = -1.0

        # r1: F_fH2O - F_H2 - 2*F_CH4 - F_H2Of = 0
        J[1, ci(self._v_fH2O)] =  1.0
        J[1, ci(self._v_H2)]   = -1.0
        J[1, ci(self._v_CH4)]  = -2.0
        J[1, ci(self._v_H2Of)] = -1.0

        # r2: F_aO2 - lam*(0.5H2 + 0.5CO + 2CH4) = 0
        J[2, ci(self._v_aO2)] =  1.0
        J[2, ci(self._v_H2)]  = -0.5 * lam
        J[2, ci(self._v_CO)]  = -0.5 * lam
        J[2, ci(self._v_CH4)] = -2.0 * lam

        # r3: F_fN2 - F_aN2 - F_N2f = 0
        J[3, ci(self._v_fN2)] =  1.0
        J[3, ci(self._v_aN2)] = -1.0
        J[3, ci(self._v_N2f)] = -1.0

        # r4: F_fO2 - (lam-1)*(0.5H2 + 0.5CO + 2CH4) = 0
        J[4, ci(self._v_fO2)] =  1.0
        J[4, ci(self._v_H2)]  = -0.5 * (lam - 1.0)
        J[4, ci(self._v_CO)]  = -0.5 * (lam - 1.0)
        J[4, ci(self._v_CH4)] = -2.0 * (lam - 1.0)

        # r5: W_elec - q_elec*(LHV_H2·H2 + LHV_CO·CO + LHV_CH4·CH4) = 0
        J[5, ci(self._v_W)]   =  1.0
        J[5, ci(self._v_H2)]  = -self._q_elec * _LHV_H2
        J[5, ci(self._v_CO)]  = -self._q_elec * _LHV_CO
        J[5, ci(self._v_CH4)] = -self._q_elec * _LHV_CH4

        # r6: Q_process - q_heat*(LHV_H2·H2 + ...) = 0
        J[6, ci(self._v_Q)]   =  1.0
        J[6, ci(self._v_H2)]  = -self._q_heat * _LHV_H2
        J[6, ci(self._v_CO)]  = -self._q_heat * _LHV_CO
        J[6, ci(self._v_CH4)] = -self._q_heat * _LHV_CH4

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=vnames,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=True,
            trust_region=self.trust_region,
        )
