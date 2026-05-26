"""Isentropic compressor (ideal gas).

Physics
-------
Isentropic outlet temperature:
    T_out_isen = T_in * (P_out/P_in)^((γ-1)/γ)

Actual outlet temperature with isentropic efficiency η:
    T_out = T_in + (T_out_isen - T_in) / η

Shaft work:
    W_shaft = F_in * Cp_mix(T_avg) * (T_out - T_in)   [W]

Ports
-----
inlet  : StreamPort  (F_i_in, T_in, P_in)
outlet : StreamPort  (F_i_out, T_out, P_out)

Additional variables
---------------------
W_shaft  : shaft power consumed [W] (positive = work input)

Residuals (N + 3 equations)
-----------------------------
  Material  : F_i_out - F_i_in = 0                               [N]
  Temp      : T_out - (T_in + (T_in*(r_P^θ) - T_in) / η) = 0   [1]
  Work      : W_shaft - F_total * Cp_mix * (T_out - T_in) = 0   [1]
  Pressure  : (treated as degree of freedom — P_out is a free var) [0]
  P_outlet  : P_out - P_out_spec = 0 if P_out_spec given,        [1]
              else P_out is a free variable within bounds

where r_P = P_out/P_in, θ = (γ-1)/γ
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import (
    cp_J_mol_K, dcp_dT_J_mol_K2, mixture_cp_J_mol_K, gamma, SHOMATE,
)

_R_GAS = 8.314462
_KNOWN = set(SHOMATE.keys())


@dataclass
class CompressorParams:
    eta_isentropic: float = 0.75   # isentropic efficiency [-]
    P_out_Pa: Optional[float] = None  # if None, P_out is a free variable
    feed_max: float = 1e4          # mol/s
    T_min: float = 250.0
    T_max: float = 1500.0
    P_min: float = 1e4
    P_max: float = 1e8
    W_max: float = 1e9             # W
    gamma_fixed: Optional[float] = None  # if None, computed from species
    electricity_price_USD_per_kWh: float = 0.05   # for OPEX calculation
    operating_hours_per_year: float = 8_000.0
    n_stages: int = 1
    """Number of compression stages with ideal intercooling between them.
    ``n_stages = 1`` (default) preserves the v1.5.3 single-stage model.
    With N stages and equal pressure ratio per stage r_s = r_total^(1/N),
    each stage operates from ``T_intercool_K`` (or T_in for the first stage
    if ``T_intercool_K`` is None) to T_in × (1 + (r_s^θ − 1)/η). Total shaft
    work is N × per-stage work; intercooler duty (N − 1) × W_per_stage is
    exposed as a KPI for sizing the inter-stage HX train."""
    T_intercool_K: Optional[float] = None
    """Temperature [K] to which the gas is cooled between stages. When
    ``None`` the intercooling target is T_in (so multi-stage with ideal
    intercooling). Set to a higher value to model partial intercooling."""


class Compressor(BaseUnit):
    """Isentropic gas compressor with efficiency correction."""

    is_linear = False
    # v1.6.1 P.5b — coefficient embeds ``electricity_price × hours``.
    _OPEX_CONVENTION = "USD_per_year"

    def __init__(self, unit_id: str, components: List[str], params: Optional[CompressorParams] = None):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params or CompressorParams()
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
        if p.P_out_Pa is not None:
            bds[self._v_P_out()] = (p.P_out_Pa, p.P_out_Pa)
        else:
            bds[self._v_P_out()] = (p.P_min, p.P_max)
        bds[self._v_W()] = (0.0, p.W_max)
        return bds

    def _gamma(self, x: Dict[str, float]) -> float:
        if self.params.gamma_fixed is not None:
            return self.params.gamma_fixed
        flows = {c: x.get(self._v_F_in(c), 0.0) for c in self.components if c in _KNOWN}
        total = sum(flows.values())
        if total < 1e-12:
            return 1.4

        # Two-stage estimate of T_avg so γ stays accurate at large pressure
        # ratios. Pre-v1.4.0 we read T_out directly from x, which on the very
        # first SLP iteration defaulted to ~400 K regardless of the true
        # isentropic outlet (~1200 K at P_r ≈ 50). Audit H7.
        T_in = x.get(self._v_T_in(), 298.0)
        P_in = max(x.get(self._v_P_in(), 101325.0), 1e-3)
        P_out_guess = max(x.get(self._v_P_out(), P_in), 1e-3)
        # Stage 1: assume γ = 1.4 to bootstrap the isentropic T_out.
        theta_0 = (1.4 - 1.0) / 1.4
        T_out_est = T_in * (P_out_guess / P_in) ** theta_0
        T_avg = 0.5 * (T_in + T_out_est)
        Cp_mix = mixture_cp_J_mol_K(flows, T_avg, basis="molar_flow")
        return Cp_mix / (Cp_mix - _R_GAS) if Cp_mix > _R_GAS else 1.4

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(N + 3, dtype=float)

        T_in  = x.get(self._v_T_in(), 298.15)
        P_in  = max(x.get(self._v_P_in(), 101325.0), 1e-3)
        T_out = x.get(self._v_T_out(), 400.0)
        P_out = max(x.get(self._v_P_out(), 300000.0), 1e-3)
        W     = x.get(self._v_W(), 0.0)

        F_in_total = sum(x.get(self._v_F_in(c), 0.0) for c in comps)

        # Material balances [N]
        for i, c in enumerate(comps):
            res[i] = x.get(self._v_F_out(c), 0.0) - x.get(self._v_F_in(c), 0.0)

        # Isentropic temperature rise [1]
        # Multi-stage with ideal intercooling: each stage has equal pressure
        # ratio r_s = (P_out/P_in)^(1/N) and starts at T_intercool (or T_in
        # for stage 1 if T_intercool_K is None). The unit reports the
        # FINAL-stage outlet temperature; intermediate stages are not
        # exposed as variables — they're integrated into the work / Q_int
        # KPIs analytically.
        g = self._gamma(x)
        theta = (g - 1.0) / g
        N_stages = max(self.params.n_stages, 1)
        r_total = P_out / P_in
        r_stage = r_total ** (1.0 / N_stages)
        eta = self.params.eta_isentropic
        T_inter = self.params.T_intercool_K if self.params.T_intercool_K else T_in
        # Each stage starts at T_inter, ends at T_after_stage:
        T_after_stage = T_inter + (T_inter * r_stage ** theta - T_inter) / eta
        # The final stage starts at T_inter and outputs T_out_actual:
        T_out_actual = T_after_stage
        res[N] = T_out - T_out_actual

        # Shaft work [1]
        flows_in = {c: x.get(self._v_F_in(c), 0.0) for c in comps if c in _KNOWN}
        Cp_mix = mixture_cp_J_mol_K(flows_in, 0.5 * (T_inter + T_out), basis="molar_flow")
        # Work per stage = F · Cp · (T_after_stage − T_inter); total = N × that.
        # Equivalent to F · Cp · (T_out − T_in) for single-stage (N=1, T_inter=T_in).
        W_per_stage = max(F_in_total, 0.0) * Cp_mix * (T_after_stage - T_inter)
        W_calc = N_stages * W_per_stage
        res[N + 1] = W - W_calc

        # Pressure (P_out specified or free; if specified → bounds handle it, residual is 0)
        if self.params.P_out_Pa is not None:
            res[N + 2] = P_out - self.params.P_out_Pa
        else:
            res[N + 2] = 0.0  # P_out is a free variable; no additional residual

        return res

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Closed-form Jacobian for the (N + 3) residuals.

        Implemented when ``params.gamma_fixed`` is set (the recommended
        path for parametric studies — γ is a slow function of T and
        composition, ~1.30–1.40 across the operating envelope). When
        ``gamma_fixed is None`` we fall back to the base-class FD scheme,
        because differentiating through ``_gamma()``'s bootstrap step
        (T_avg ← T_in*(P_out/P_in)^0.4/1.4 → Cp_mix(T_avg) → γ) is
        intricate and gives only a few-percent γ swing per iter.

        Rows::

            i in 0..N-1: r_i = F_out_i − F_in_i           (linear)
            N:           r = T_out − T_after_stage
            N+1:         r = W − N · F_total · Cp_mix · (T_after − T_inter)
            N+2:         r = P_out − P_out_spec (or 0)

        Validated against the central-difference reference in
        ``tests/test_analytical_jacobians.py::TestCompressorAnalyticalJacobian``
        at 1e-4 rel / 1e-3 abs (relaxed by an order of magnitude vs
        CSTRHF because the work residual involves three chained Cp(T)
        evaluations at ~500 K and accumulated roundoff is larger).
        """
        variables = self.variables()
        n = len(variables)
        vidx = {v: i for i, v in enumerate(variables)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)
        f0 = np.asarray(self.residual(x0_dict), dtype=float).reshape(-1)

        N = len(self.components)
        m = f0.size  # = N + 3
        J = np.zeros((m, n), dtype=float)

        # ── Material rows: trivial ─────────────────────────────────────────
        for i, c in enumerate(self.components):
            J[i, vidx[self._v_F_in(c)]] = -1.0
            J[i, vidx[self._v_F_out(c)]] = +1.0

        # Pressure-spec row: trivial
        if self.params.P_out_Pa is not None:
            J[N + 2, vidx[self._v_P_out()]] = 1.0

        if self.params.gamma_fixed is None:
            # Fall back to FD for the two non-linear rows (T row, W row).
            # We still get analytical entries for the linear rows; the FD
            # cost dominates either way, so this is a no-op for speed but
            # makes the linearize() override unambiguous in scope.
            J_fd = self._finite_difference_jacobian(x0_dict, variables, f0)
            J[N, :] = J_fd[N, :]
            J[N + 1, :] = J_fd[N + 1, :]
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
                kpi_gradients=self.kpi_gradients(x0_dict),
            )

        # ── Analytical path (gamma_fixed available) ────────────────────────
        g = self.params.gamma_fixed
        theta = (g - 1.0) / g
        eta = self.params.eta_isentropic
        N_st = max(self.params.n_stages, 1)

        T_in = x0_dict.get(self._v_T_in(), 298.15)
        T_out = x0_dict.get(self._v_T_out(), 400.0)
        P_in = max(x0_dict.get(self._v_P_in(), 101325.0), 1e-3)
        P_out = max(x0_dict.get(self._v_P_out(), 3.0e5), 1e-3)
        T_inter_const = self.params.T_intercool_K
        T_inter = T_inter_const if T_inter_const is not None else T_in
        T_inter_tracks_T_in = T_inter_const is None

        r_total = P_out / P_in
        r_stage = r_total ** (1.0 / N_st)
        r_stage_theta = r_stage ** theta
        T_after = T_inter + (T_inter * r_stage_theta - T_inter) / eta
        # = T_inter * (1 + (r_stage^θ − 1)/η)

        flows_in_total = sum(x0_dict.get(self._v_F_in(c), 0.0) for c in self.components)
        flows_in = {c: x0_dict.get(self._v_F_in(c), 0.0) for c in self.components if c in _KNOWN}
        T_avg = 0.5 * (T_inter + T_out)
        Cp_per_species = {c: cp_J_mol_K(c, T_avg) for c in flows_in}
        dCp_per_species = {c: dcp_dT_J_mol_K2(c, T_avg) for c in flows_in}
        # F_total*Cp_mix = Σ F_i * Cp_i — convenient since flows_in only
        # uses species with SHOMATE coefficients.
        F_Cp = sum(flows_in[c] * Cp_per_species[c] for c in flows_in)
        F_dCp = sum(flows_in[c] * dCp_per_species[c] for c in flows_in)

        # ── Row N: T row r = T_out − T_after_stage ─────────────────────────
        J[N, vidx[self._v_T_out()]] = 1.0
        # ∂T_after/∂P_in = T_inter * θ * r_stage^θ / r_stage * ∂r_stage/∂P_in / η ...
        # Simpler: T_after − T_inter = T_inter*(r_stage^θ − 1)/η.
        # And r_stage^θ = r_total^(θ/N_st) = (P_out/P_in)^(θ/N_st).
        # Let φ = θ/N_st. r_stage^θ = (P_out/P_in)^φ.
        phi = theta / N_st
        # d/dP_in[(P_out/P_in)^φ] = φ * (P_out/P_in)^φ * (-1/P_in) = -φ * r_stage^θ / P_in
        dT_after_dPin = T_inter * (-phi * r_stage_theta / P_in) / eta
        dT_after_dPout = T_inter * (+phi * r_stage_theta / P_out) / eta
        J[N, vidx[self._v_P_in()]]  = -dT_after_dPin
        J[N, vidx[self._v_P_out()]] = -dT_after_dPout
        if T_inter_tracks_T_in:
            # T_inter = T_in, so T_after = T_in * (1 + (r_stage^θ − 1)/η)
            # dT_after/dT_in = 1 + (r_stage^θ − 1)/η
            dT_after_dTin = 1.0 + (r_stage_theta - 1.0) / eta
            J[N, vidx[self._v_T_in()]] = -dT_after_dTin

        # ── Row N+1: W row r = W − N · F_Cp · (T_after − T_inter) ──────────
        dT_kick = T_after - T_inter  # = T_inter*(r_stage^θ − 1)/η
        J[N + 1, vidx[self._v_W()]] = 1.0
        # ∂(F_Cp)/∂F_in_c = Cp_c(T_avg)
        for c in flows_in:
            J[N + 1, vidx[self._v_F_in(c)]] = -N_st * Cp_per_species[c] * dT_kick
        # ∂(F_Cp)/∂T_in (via T_avg if T_inter tracks T_in): T_avg = 0.5(T_inter + T_out).
        # If T_inter = T_in, dT_avg/dT_in = 0.5. dF_Cp/dT_avg = F_dCp.
        # ∂T_after/∂T_in done above.
        # ∂(T_after - T_inter)/∂T_in (T_inter=T_in): d(T_after)/dT_in − 1
        #   = (1 + (r_stage^θ − 1)/η) − 1 = (r_stage^θ − 1)/η
        if T_inter_tracks_T_in:
            d_dT_kick_dTin = (r_stage_theta - 1.0) / eta
            d_F_Cp_dTin = 0.5 * F_dCp  # via T_avg
            J[N + 1, vidx[self._v_T_in()]] = -N_st * (
                d_F_Cp_dTin * dT_kick + F_Cp * d_dT_kick_dTin
            )
        # ∂T_avg/∂T_out = 0.5 → ∂F_Cp/∂T_out = 0.5 * F_dCp
        d_F_Cp_dTout = 0.5 * F_dCp
        J[N + 1, vidx[self._v_T_out()]] = -N_st * d_F_Cp_dTout * dT_kick
        # ∂dT_kick/∂P_in, ∂P_out via dT_after as above
        J[N + 1, vidx[self._v_P_in()]]  = -N_st * F_Cp * dT_after_dPin
        J[N + 1, vidx[self._v_P_out()]] = -N_st * F_Cp * dT_after_dPout

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
            kpi_gradients=self.kpi_gradients(x0_dict),
        )

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        """Electricity cost contribution [USD/yr] for the shaft work draw."""
        p = self.params
        # W_shaft is in W; convert to kW: divide by 1000.
        # Annual electricity cost = (W_shaft / 1000) × price × hours
        coeff_USD_per_W_yr = p.electricity_price_USD_per_kWh * p.operating_hours_per_year / 1000.0
        return {self._v_W(): coeff_USD_per_W_yr}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        W = x.get(self._v_W(), 0.0)
        T_in  = x.get(self._v_T_in(), 298.0)
        T_out = x.get(self._v_T_out(), 400.0)
        P_in  = max(x.get(self._v_P_in(), 101325.0), 1.0)
        P_out = max(x.get(self._v_P_out(), 500000.0), 1.0)
        from pse_ecosystem.models.costing.sslw_costing import compressor_purchase_cost_USD
        N_stages = max(self.params.n_stages, 1)
        # Intercooler total duty: with ideal intercooling between stages,
        # each interstage cooler removes W_per_stage of heat (returning the
        # gas to T_intercool). Total Q_intercool = (N − 1) × W_per_stage =
        # (N − 1) × W_total / N. Zero for single-stage; non-zero only when
        # the user has explicitly requested multi-stage compression.
        Q_intercool_W = (N_stages - 1) * W / N_stages if N_stages > 1 else 0.0
        return {
            f"{uid}.W_shaft_W":               W,
            f"{uid}.W_shaft_kW":              W / 1000.0,
            f"{uid}.T_out_K":                 T_out,
            f"{uid}.compression_ratio":       P_out / P_in,
            f"{uid}.n_stages":                float(N_stages),
            f"{uid}.Q_intercool_W":           Q_intercool_W,
            f"{uid}.isentropic_efficiency_pct": self.params.eta_isentropic * 100.0,
            f"{uid}.capex_USD":               compressor_purchase_cost_USD(W),
            f"{uid}.opex_USD_per_yr":         self.opex_per_year(x),
        }

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import compressor_purchase_cost_USD
        return compressor_purchase_cost_USD(x.get(self._v_W(), 0.0))

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required shaft work, stage count from r_stage ≤ 4 heuristic, and
        a *surge margin* estimate at the current compression ratio.

        Surge limit: industrial centrifugal compressors hit surge around
        50-60% of design flow. The margin we report is the polytropic head
        margin: (T_after − T_in) / (T_choke − T_in), assuming the compressor
        is sized for ~30 K margin to the choke point at the design flow.
        """
        P_in = max(x.get(self._v_P_in(), 1.0e5), 1.0)
        P_out = max(x.get(self._v_P_out(), 5.0e5), 1.0)
        r_total = P_out / P_in
        T_in = x.get(self._v_T_in(), 300.0)
        T_out = x.get(self._v_T_out(), 400.0)
        # Stage-count recommendation: r_stage ≤ 4 keeps each stage's outlet
        # T below the metallurgical limit on common alloys.
        n_stages_rec = max(
            int(math.ceil(math.log(r_total) / math.log(4.0))), 1
        )
        W = x.get(self._v_W(), 0.0)
        # Discharge T margin: compare actual ΔT vs choke ΔT (≈ 180 K for
        # typical industrial machines). Negative ⇒ too hot, oversized stages.
        dT_actual = T_out - T_in
        surge_margin_K = 180.0 - dT_actual
        return {
            "W_shaft_required_W": W,
            "compression_ratio": r_total,
            "n_stages_recommended": float(n_stages_rec),
            "n_stages_specified": float(self.params.n_stages),
            "discharge_T_K": T_out,
            "surge_margin_K": surge_margin_K,
        }
