"""CoolerHF — single-stream gas cooler with fixed outlet temperature.

Represents a shell-and-tube or air-cooled heat exchanger where the process
stream is cooled to a target temperature.  The cooling utility (water, air)
is modelled via an energy balance: the heat duty Q is computed from the
enthalpy difference between inlet and outlet conditions.

Unlike the legacy version this unit now includes T and P on both ports and
a heat-duty variable Q_duty_kW.  The outlet temperature T_out is fixed at
``params.T_out_K`` via a residual; T_in and P are free variables supplied
by the upstream unit.

Ports
-----
inlet_port  : N-component gas feed  (has_T=True, has_P=True)
outlet_port : same N components     (has_T=True, has_P=True)

Variables (2N + 5)
------------------
{uid}.inlet.F_{comp}   [mol/s]  — inlet molar flows
{uid}.inlet.T          [K]      — inlet temperature (from upstream)
{uid}.inlet.P          [Pa]     — inlet pressure
{uid}.outlet.F_{comp}  [mol/s]  — outlet molar flows
{uid}.outlet.T         [K]      — outlet temperature (fixed by residual)
{uid}.outlet.P         [Pa]     — outlet pressure (= inlet, no drop)
{uid}.Q_duty_kW        [kW]     — cooling duty removed from stream (≥ 0)

Residuals (N + 3)
-----------------
f[i]   = outlet.F_comp[i] − inlet.F_comp[i]       [N]   (mass conservation)
f[N]   = outlet.T − T_out_param                   [1]   (T_out pinned)
f[N+1] = outlet.P − inlet.P                       [1]   (no pressure drop)
f[N+2] = Q_duty_kW − ΔH_kW                        [1]   (energy balance)
         ΔH_kW = Σ F_i·[h_i(T_in) − h_i(T_out)] / 1000
         (positive = heat removed → cooling duty)

The energy balance is non-linear in T_in because h_i(T_in) = Shomate(T_in).
The Jacobian ∂Q/∂T_in = Σ F_i·Cp_i(T_in)/1000 is computed analytically.

KPIs
----
{uid}.T_out_K           : target outlet temperature [K]
{uid}.T_in_K            : actual inlet temperature [K]
{uid}.Q_duty_kW         : cooling duty [kW]
{uid}.total_flow_out    : total outlet molar flow [mol/s]
{uid}.cooling_UA_kW_K   : Q/(T_in - T_out) [kW/K] — approximate UA
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class CoolerHFParams:
    T_out_K: float = 400.0           # target outlet temperature [K]
    feed_max: float = 1_000.0        # upper bound on all flow variables [mol/s]
    T_min: float = 200.0             # K
    T_max: float = 2000.0            # K
    P_min: float = 1e3               # Pa
    P_max: float = 1e8               # Pa
    Q_max_kW: float = 1e7            # kW — maximum cooling duty
    cooling_water_price_USD_per_GJ: float = 0.35  # utility cost


class CoolerHF(BaseUnit):
    """Single-stream gas cooler — fixed T_out, full energy balance.

    Parameters
    ----------
    unit_id    : Unique identifier.
    components : List of species tracked through the cooler.
    params     : CoolerHFParams.
    """

    is_linear: bool = False   # energy balance is non-linear in T_in
    _OPEX_CONVENTION = "USD_per_year"

    def __init__(
        self,
        unit_id: str,
        components: List[str],
        params: CoolerHFParams | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or CoolerHFParams()

        self.inlet_port = StreamPort(
            unit_id=unit_id, tag="inlet",
            components=self.components,
            has_T=True, has_P=True,
            phase="gas",
        )
        self.outlet_port = StreamPort(
            unit_id=unit_id, tag="outlet",
            components=self.components,
            has_T=True, has_P=True,
            phase="gas",
        )

    @property
    def _primary_inlet_port(self):
        return self.inlet_port

    @property
    def _primary_outlet_port(self):
        return self.outlet_port

    # ── Variable helpers ──────────────────────────────────────────────────────

    def _v_in(self, c: str) -> str:
        return f"{self.unit_id}.inlet.F_{c}"

    def _v_out(self, c: str) -> str:
        return f"{self.unit_id}.outlet.F_{c}"

    def _v_T_in(self)  -> str: return f"{self.unit_id}.inlet.T"
    def _v_P_in(self)  -> str: return f"{self.unit_id}.inlet.P"
    def _v_T_out(self) -> str: return f"{self.unit_id}.outlet.T"
    def _v_P_out(self) -> str: return f"{self.unit_id}.outlet.P"
    def _v_Q(self)     -> str: return f"{self.unit_id}.Q_duty_kW"

    def variables(self) -> List[str]:
        ins  = [self._v_in(c)  for c in self.components]
        outs = [self._v_out(c) for c in self.components]
        return ins + [self._v_T_in(), self._v_P_in()] \
             + outs + [self._v_T_out(), self._v_P_out(), self._v_Q()]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for c in self.components:
            bds[self._v_in(c)]  = (0.0, p.feed_max)
            bds[self._v_out(c)] = (0.0, p.feed_max)
        bds[self._v_T_in()]  = (p.T_min, p.T_max)
        bds[self._v_P_in()]  = (p.P_min, p.P_max)
        # T_out pinned by residual; give it a tight bound to help the LP.
        bds[self._v_T_out()] = (max(p.T_min, p.T_out_K - 1e-3),
                                  min(p.T_max, p.T_out_K + 1e-3))
        bds[self._v_P_out()] = (p.P_min, p.P_max)
        bds[self._v_Q()] = (0.0, p.Q_max_kW)   # cooling only (Q ≥ 0)
        return bds

    # ── Residuals ─────────────────────────────────────────────────────────────

    def _enthalpy_kW(self, T: float, x: Dict[str, float], tag: str) -> float:
        """Σ F_i · h_i(T) / 1000  [kW].  Only Shomate-known species contribute."""
        try:
            from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, SHOMATE
            _known = set(SHOMATE.keys())
            total = 0.0
            for c in self.components:
                if c in _known:
                    F = x.get(f"{self.unit_id}.{tag}.F_{c}", 0.0)
                    total += F * enthalpy_J_mol(c, T)
            return total / 1000.0
        except Exception:
            return 0.0

    def _cp_mix_kW_per_K(self, T: float, x: Dict[str, float], tag: str) -> float:
        """Σ F_i · Cp_i(T) / 1000  [kW/K]."""
        try:
            from pse_ecosystem.models.properties.ideal_gas import cp_J_mol_K, SHOMATE
            _known = set(SHOMATE.keys())
            total = 0.0
            for c in self.components:
                if c in _known:
                    F = x.get(f"{self.unit_id}.{tag}.F_{c}", 0.0)
                    total += F * cp_J_mol_K(c, T)
            return total / 1000.0
        except Exception:
            return 0.0

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        N = len(self.components)
        res = np.zeros(N + 3, dtype=float)
        T_in  = x.get(self._v_T_in(),  500.0)
        T_out = x.get(self._v_T_out(), self.params.T_out_K)
        Q     = x.get(self._v_Q(),     0.0)
        P_in  = x.get(self._v_P_in(),  101325.0)
        P_out = x.get(self._v_P_out(), 101325.0)

        # Mass conservation [N]
        for i, c in enumerate(self.components):
            res[i] = x.get(self._v_out(c), 0.0) - x.get(self._v_in(c), 0.0)

        # T_out pinned [1]
        res[N] = T_out - self.params.T_out_K

        # Pressure pass-through [1]
        res[N + 1] = P_out - P_in

        # Energy balance [1]:  Q = H_in - H_out  (cooling removes heat)
        H_in  = self._enthalpy_kW(T_in,  x, "inlet")
        H_out = self._enthalpy_kW(T_out, x, "outlet")
        res[N + 2] = Q - (H_in - H_out)

        return res

    # ── Objective (cooling-water cost) ────────────────────────────────────────

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        """Cooling water utility cost [USD/yr].

        Cost = Q_duty_kW × (3600 s/h × op_hours × 1e-6 GJ/kJ)
               × cooling_water_price_USD_per_GJ × (op_hours / 8000)
        Simplified: coefficient on Q_duty_kW [kW] → USD/yr when multiplied
        by the LP solve (which uses unit operating hours).

        Coefficient: price_per_GJ × 3.6e-3 [GJ per kW·h] × 8000 [h/yr]
        """
        p = self.params
        # Convert: USD/GJ × 3.6e-3 GJ/(kW·h) × 8000 h/yr = USD/(kW·yr)
        coeff_USD_per_kW_yr = p.cooling_water_price_USD_per_GJ * 3.6e-3 * 8000.0
        return {self._v_Q(): coeff_USD_per_kW_yr}

    # ── CAPEX ─────────────────────────────────────────────────────────────────

    def capex(self, x: Dict[str, float]) -> float:
        """SSLW shell-and-tube HX purchase cost [USD, CE500 basis].

        Area estimated from Q_duty / (U × ΔLMTD) with conservative defaults:
        U = 500 W/m²/K (gas-liquid heat exchanger), ΔLMTD = T_in - T_out.
        """
        try:
            from pse_ecosystem.models.costing.sslw_costing import hx_purchase_cost_USD
            Q_kW  = max(x.get(self._v_Q(), 0.0), 0.1)      # kW
            T_in  = x.get(self._v_T_in(), 500.0)
            T_out = self.params.T_out_K
            dT    = max(T_in - T_out, 5.0)                   # K; minimum 5 K
            U_W_m2_K = 500.0                                  # W/m²/K (gas cooler)
            A_m2  = Q_kW * 1000.0 / (U_W_m2_K * dT)         # m²
            return hx_purchase_cost_USD(A_m2)
        except Exception:
            return 0.0

    # ── Analytical Jacobian (partially analytical for mass/pressure rows) ──────

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Semi-analytical Jacobian.

        Mass balance and T_out/P_out rows are exact linear.
        Energy balance row uses analytical ∂Q/∂T_in = Cp_mix(T_in) and
        ∂Q/∂F_i = [h_i(T_in) - h_i(T_out)] / 1000, with the rest from FD.
        """
        variables = self.variables()
        n = len(variables)
        vidx = {v: i for i, v in enumerate(variables)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)
        f0 = np.asarray(self.residual(x0_dict), dtype=float)
        N = len(self.components)
        m = f0.size

        J = np.zeros((m, n), dtype=float)

        # ── Mass balance rows (exact) ────────────────────────────────────────
        for i, c in enumerate(self.components):
            J[i, vidx[self._v_out(c)]] =  1.0
            J[i, vidx[self._v_in(c)]]  = -1.0

        # ── T_out pin (exact): ∂(T_out - T_param)/∂T_out = 1 ──────────────
        J[N, vidx[self._v_T_out()]] = 1.0

        # ── Pressure pass-through (exact) ───────────────────────────────────
        J[N + 1, vidx[self._v_P_out()]] =  1.0
        J[N + 1, vidx[self._v_P_in()]]  = -1.0

        # ── Energy balance (analytical derivatives) ──────────────────────────
        T_in  = x0_dict.get(self._v_T_in(),  500.0)
        T_out = self.params.T_out_K
        # ∂Q/∂Q_duty = 1
        J[N + 2, vidx[self._v_Q()]] = 1.0
        # ∂Q/∂T_in = -Cp_mix(T_in)/1000 * (-1) → positive  (more T_in → more cooling)
        Cp_in = self._cp_mix_kW_per_K(T_in, x0_dict, "inlet")
        J[N + 2, vidx[self._v_T_in()]] = -Cp_in
        # ∂Q/∂F_i = -[h_i(T_in) - h_i(T_out)] / 1000  for each component
        try:
            from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol, SHOMATE
            _known = set(SHOMATE.keys())
            for c in self.components:
                if c in _known:
                    dh = (enthalpy_J_mol(c, T_in) - enthalpy_J_mol(c, T_out)) / 1000.0
                    J[N + 2, vidx[self._v_in(c)]] = -dh
        except Exception:
            pass

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

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        T_in  = x.get(self._v_T_in(), 0.0)
        T_out = x.get(self._v_T_out(), self.params.T_out_K)
        Q     = x.get(self._v_Q(), 0.0)
        total_out = sum(x.get(self._v_out(c), 0.0) for c in self.components)
        dT = max(T_in - T_out, 1e-3)
        ua = Q / dT if dT > 0 else 0.0
        return {
            f"{uid}.T_out_K":        T_out,
            f"{uid}.T_in_K":         T_in,
            f"{uid}.Q_duty_kW":      Q,
            f"{uid}.total_flow_out":  total_out,
            f"{uid}.cooling_UA_kW_K": ua,
        }
