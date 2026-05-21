"""Sabatier / DFM Methanation Reactor for CO₂ utilisation.

Equilibrium-limited reactor for the Sabatier reaction:
    CO₂ + 4H₂ → CH₄ + 2H₂O    ΔH° = −165 kJ/mol

The equilibrium conversion X_CO2 is a non-linear function of reactor
temperature T_rx.  The unit provides an analytical Jacobian so the SLP
driver can converge in 1–3 iterations for this model.

Equilibrium model
-----------------
Empirical lumped equilibrium fit to match published DAC-to-methane literature:

    K_Sab(T) = exp(A/T − B)   where A = 4786, B = 4.92

Calibration points:
    T = 673 K (400 °C): X = 0.90
    T = 973 K (700 °C): X = 0.50

Pseudo-equilibrium approximation (H₂ in large excess):
    X_CO2 = K_Sab / (1 + K_Sab)

Analytical dX/dT:
    dX/dT = −A × X × (1−X) / T²

References (v1.4.0 audit N13)
-----------------------------
The lumped form was fitted against:
- Vannice (1976) "The Catalytic Synthesis of Hydrocarbons from H₂/CO Mixtures"
  J. Catal. 44, 152–162 (calibration of Sabatier equilibrium 600–800 K).
- Lunde & Kester (1973) "Kinetics of CO₂ methanation over Ru/Al₂O₃",
  J. Catal. 30, 423–429 (high-T equilibrium limit).
- NIST JANAF tables for ΔG°_f(CO₂, CH₄, H₂O) yielding K_eq(T) within ~10 % of
  the lumped fit over 600–1000 K — appropriate for the SLP linearisation.

Treat the fit as a calibrated *operational* equilibrium for v1.4.0 ranges
(600–1000 K, low-pressure operation). For high-pressure (>10 bar) or
strongly non-stoichiometric feeds, plug in a Gibbs minimisation via the
``GibbsReactor`` unit instead.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

_M_CO2 = 0.044   # kg/mol
_M_CH4 = 0.016   # kg/mol
_M_H2O = 0.018   # kg/mol

# Equilibrium constants  K_Sab(T) = exp(A/T - B)
_A_KSAB = 4786.0
_B_KSAB = 4.92

# Sabatier reaction heat [kJ/mol CH4]
_DH_SAB = -165.0   # exothermic


class MethanationReactor(BaseUnit):
    """Equilibrium Sabatier methanation reactor.

    CO₂ and H₂ streams enter; CH₄ and H₂O exit.  CO₂ conversion X_CO2 and
    reactor temperature T_rx_K are optimisation variables.

    Note: the H₂:CO₂ feed ratio should be fixed at 4:1 (stoichiometric) via
    ``flowsheet.extra_equalities`` in the template loader.  The unit residuals
    do not enforce the H₂ feed quantity — they enforce mass balance on products
    and the equilibrium constraint.

    Parameters
    ----------
    unit_id :
        Unique identifier.
    T_rx_K_default :
        Default operating temperature [K] (default 673 K = 400 °C).
    """

    is_linear: bool = False

    def __init__(self, unit_id: str, *, T_rx_K_default: float = 673.0):
        self.unit_id = unit_id
        self._T_default = T_rx_K_default

        # Port definitions (no T/P: simple molar flow ports)
        self.co2_in_port = StreamPort(
            unit_id, "co2_in",
            components=["CO2"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"CO2"}),
        )
        self.h2_in_port = StreamPort(
            unit_id, "h2_in",
            components=["H2"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"H2"}),
        )
        self.product_out_port = StreamPort(
            unit_id, "product_out",
            components=["CH4", "H2O"],
            has_T=False, has_P=False,
            phase="gas",
            species=frozenset({"CH4", "H2O"}),
        )

        self._v_co2_in = f"{unit_id}.co2_in.F_CO2"
        self._v_h2_in  = f"{unit_id}.h2_in.F_H2"
        self._v_ch4    = f"{unit_id}.product_out.F_CH4"
        self._v_h2o    = f"{unit_id}.product_out.F_H2O"
        self._v_X      = f"{unit_id}.X_CO2"
        self._v_T      = f"{unit_id}.T_rx_K"
        self._v_Q      = f"{unit_id}.Q_duty_kW"  # cooling duty [kW] ≥ 0

    @property
    def _primary_inlet_port(self):
        return self.co2_in_port

    @property
    def _primary_outlet_port(self):
        return self.product_out_port

    # ── Helper: equilibrium ───────────────────────────────────────────────

    @staticmethod
    def _K_sab(T: float) -> float:
        return math.exp(_A_KSAB / max(T, 1.0) - _B_KSAB)

    @staticmethod
    def _X_eq(T: float) -> float:
        K = MethanationReactor._K_sab(T)
        return K / (1.0 + K)

    # ── Abstract interface ────────────────────────────────────────────────

    def variables(self) -> List[str]:
        return [
            self._v_co2_in, self._v_h2_in,
            self._v_ch4, self._v_h2o,
            self._v_X, self._v_T, self._v_Q,
        ]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            self._v_co2_in: (0.0, 1e4),
            self._v_h2_in:  (0.0, 4e4),
            self._v_ch4:    (0.0, 1e4),
            self._v_h2o:    (0.0, 2e4),
            self._v_X:      (0.01, 0.9999),
            self._v_T:      (373.0, 1073.0),
            self._v_Q:      (0.0, 1e7),      # cooling duty ≥ 0 [kW]
        }

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        F_co2 = x.get(self._v_co2_in, 0.0)
        F_ch4 = x.get(self._v_ch4, 0.0)
        F_h2o = x.get(self._v_h2o, 0.0)
        X = x.get(self._v_X, 0.5)
        T = x.get(self._v_T, self._T_default)
        K = self._K_sab(T)
        Q = x.get(self._v_Q, 0.0)

        return np.array([
            # r0: CH4 yield balance
            F_ch4 - X * F_co2,
            # r1: H2O yield balance
            F_h2o - 2.0 * X * F_co2,
            # r2: equilibrium K*(1-X) = X
            K * (1.0 - X) - X,
            # r3: energy balance — cooling duty equals exothermic heat released
            # Q_duty = |ΔH_Sab| × F_CH4  (Sabatier: ΔH = -165 kJ/mol, exothermic)
            Q - abs(_DH_SAB) * F_ch4,
        ], dtype=float)

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        # v1.4.0 audit N15 — use the same near-zero floor (1e-3 mol/s) for any
        # division-by-flow KPI so a 1e-10 trace flow does not blow specific
        # energies to nonsense 1e13 levels.
        _FLOOR = 1.0e-3
        F_co2 = max(x.get(self._v_co2_in, 0.0), _FLOOR)
        F_ch4 = max(x.get(self._v_ch4, 0.0), 0.0)
        X = x.get(self._v_X, 0.0)
        T = x.get(self._v_T, self._T_default)
        Q_rx = abs(_DH_SAB) * F_ch4  # kW heat released
        sng_Nm3_h = F_ch4 * 22.414 * 3600.0 / 1000.0  # Nm³/h (22.414 L/mol)
        uid = self.unit_id
        Q_duty = x.get(self._v_Q, Q_rx)
        kpis = {
            f"{uid}.CH4_yield_pct":          X * 100.0,
            f"{uid}.CH4_production_mol_s":   F_ch4,
            f"{uid}.SNG_production_Nm3_h":   sng_Nm3_h,
            f"{uid}.Q_duty_kW":              Q_duty,
            f"{uid}.heat_released_kW":       Q_rx,
            f"{uid}.T_rx_K":                 T,
            f"{uid}.T_rx_C":                 T - 273.15,
        }
        if F_co2 <= _FLOOR * 1.001:
            kpis[f"{uid}._warning_low_feed"] = 1.0
        return kpis

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD

        F_ch4 = max(x.get(self._v_ch4, 0.0), 1e-6)
        # Rough sizing: 1 m³ reactor per mol/s CH4 (GHSV ~ 3600 h⁻¹)
        vol_m3 = max(F_ch4 * 1.0, 0.01)
        return vessel_purchase_cost_USD(vol_m3, material="SS")

    # ── Analytical linearise ──────────────────────────────────────────────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        vnames = self.variables()
        idx = {v: i for i, v in enumerate(vnames)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in vnames}
        x0 = np.array([x0_dict[v] for v in vnames], dtype=float)
        f0 = self.residual(x0_dict)
        n = len(vnames)

        X = x0_dict.get(self._v_X, 0.5)
        T = max(x0_dict.get(self._v_T, self._T_default), 1.0)
        F_co2 = x0_dict.get(self._v_co2_in, 0.0)
        K = self._K_sab(T)

        J = np.zeros((4, n), dtype=float)
        i_co2 = idx[self._v_co2_in]
        i_ch4 = idx[self._v_ch4]
        i_h2o = idx[self._v_h2o]
        i_X   = idx[self._v_X]
        i_T   = idx[self._v_T]
        i_Q   = idx[self._v_Q]

        # r0: F_CH4 - X*F_CO2 = 0
        J[0, i_ch4] =  1.0
        J[0, i_co2] = -X
        J[0, i_X]   = -F_co2

        # r1: F_H2O - 2X*F_CO2 = 0
        J[1, i_h2o] =  1.0
        J[1, i_co2] = -2.0 * X
        J[1, i_X]   = -2.0 * F_co2

        # r2: K*(1-X) - X = 0
        dK_dT = K * (-_A_KSAB / (T * T))
        J[2, i_X] = -(K + 1.0)
        J[2, i_T] = (1.0 - X) * dK_dT

        # r3: Q_duty - |ΔH_Sab| * F_CH4 = 0  (energy balance, linear in Q and F_CH4)
        J[3, i_Q]   =  1.0
        J[3, i_ch4] = -abs(_DH_SAB)

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=vnames,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=False,
            trust_region=self.trust_region,
        )
