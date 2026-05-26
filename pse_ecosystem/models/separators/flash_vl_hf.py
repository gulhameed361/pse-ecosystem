"""High-fidelity vapour-liquid flash (V/L).

K-values come from a :class:`PropertyPackage` (default ``IdealGasPackage``,
which preserves the v1.5.3 Antoine/Raoult behaviour byte-for-byte). Setting
``params.property_package`` to a PR/SRK or NRTL/Wilson/UNIQUAC instance
swaps the K-value formulation transparently — the residual equations and
energy balance reuse the package's :meth:`K_iteration` and :meth:`enthalpy`
hooks, so the unit topology is property-agnostic.

Physics correction vs. FlashToy
---------------------------------
FlashToy uses constant K-values independent of T and P.  This unit uses
K_i(T, P, x) from the property package, which is the correct formulation
for VLE and supports the full ladder of ideal-gas / cubic-EOS / activity
models added in the v1.6 thermo workstream.

Ports
-----
inlet   : StreamPort  (F_i_feed, T_feed, P_feed)
vapor   : StreamPort  (F_i_vap, T_vap, P_vap)
liquid  : StreamPort  (F_i_liq, T_liq, P_liq)

Additional variables
---------------------
V_frac  : vapour mole fraction [-]
Q       : heat duty [W]  (positive = heat added)

Residuals (2N + 4 equations)
------------------------------
  Material  :  F_i_feed - F_i_vap - F_i_liq = 0         [N]
  VLE       :  y_i - K_i(T_vap, P_vap, x) * x_i = 0     [N]
               where y_i = F_i_vap / Σ_j F_j_vap
                     x_i = F_i_liq / Σ_j F_j_liq
  Energy    :  Q + H_feed - H_vap - H_liq = 0            [1]
  Pressure  :  P_vap - P_feed = 0, P_liq - P_feed = 0   [2]
  V_frac def:  V_frac - Σ F_i_vap / Σ F_i_feed = 0      [1]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

import math as _math

from pse_ecosystem.core.contracts import LinearizedModel, PrimalGuess, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.properties.ideal_gas import (
    cp_J_mol_K, enthalpy_J_mol, SHOMATE,
)
from pse_ecosystem.models.properties.property_package import (
    IdealGasPackage,
    PropertyPackage,
)
from pse_ecosystem.models.properties.vle import ANTOINE, K_value, rachford_rice

_KNOWN = set(SHOMATE.keys())
_SMALL = 1e-12  # floor to avoid division by zero


@dataclass
class FlashVLHFParams:
    species_vle: List[str]   # species that participate in VLE (must be in ANTOINE)
    feed_max: float = 1e4   # mol/s
    T_min: float = 250.0
    T_max: float = 550.0
    P_min: float = 1e3
    P_max: float = 1e7
    Q_max: float = 1e9      # W
    property_package: Optional[PropertyPackage] = None
    """Optional property package supplying K-values via
    :meth:`PropertyPackage.K_iteration`. When ``None`` the unit auto-builds an
    :class:`IdealGasPackage` over ``species_vle`` to preserve the v1.5.3
    Antoine/Raoult numerics. Pass an instance of ``PengRobinsonPackage`` /
    ``NRTLPackage`` / ``UNIQUACPackage`` / etc. to upgrade the K-value model
    transparently — no other code in the unit changes."""


class FlashVLHF(BaseUnit):
    """V/L flash with property-package K-values and Rachford-Rice."""

    is_linear = False

    def __init__(self, unit_id: str, components: List[str], params: FlashVLHFParams):
        self.unit_id = unit_id
        self.components = list(components)
        self.params = params
        self.inlet_port = StreamPort(unit_id, "inlet", components)
        self.vapor_port = StreamPort(unit_id, "vapor", components)
        self.liquid_port = StreamPort(unit_id, "liquid", components)
        # Resolve the property package once at construction. The ideal-gas
        # auto-build is filtered to species that have Antoine coefficients so
        # the package's own validation doesn't reject the call (non-VLE
        # species — e.g. permanent gases — are handled via the K = 1 fallback
        # below).
        if params.property_package is None:
            vle_species = [c for c in params.species_vle if c in ANTOINE]
            self._package: Optional[PropertyPackage] = (
                IdealGasPackage(vle_species) if vle_species else None
            )
        else:
            self._package = params.property_package
        self._package_index = (
            {sp: i for i, sp in enumerate(self._package.species)}
            if self._package is not None
            else {}
        )

    def _v_F(self, tag: str, c: str) -> str: return f"{self.unit_id}.{tag}.F_{c}"
    def _v_T(self, tag: str) -> str: return f"{self.unit_id}.{tag}.T"
    def _v_P(self, tag: str) -> str: return f"{self.unit_id}.{tag}.P"
    def _v_Vfrac(self) -> str: return f"{self.unit_id}.V_frac"
    def _v_Q(self) -> str: return f"{self.unit_id}.Q"

    def variables(self) -> List[str]:
        vlist = []
        for tag in ("inlet", "vapor", "liquid"):
            for c in self.components:
                vlist.append(self._v_F(tag, c))
            vlist += [self._v_T(tag), self._v_P(tag)]
        vlist += [self._v_Vfrac(), self._v_Q()]
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for tag in ("inlet", "vapor", "liquid"):
            for c in self.components:
                bds[self._v_F(tag, c)] = (0.0, p.feed_max)
            bds[self._v_T(tag)] = (p.T_min, p.T_max)
            bds[self._v_P(tag)] = (p.P_min, p.P_max)
        bds[self._v_Vfrac()] = (0.0, 1.0)
        bds[self._v_Q()] = (-p.Q_max, p.Q_max)
        return bds

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        comps = self.components
        N = len(comps)
        res = np.zeros(2 * N + 4, dtype=float)

        F_feed = np.array([x.get(self._v_F("inlet", c), 0.0) for c in comps])
        F_vap  = np.array([x.get(self._v_F("vapor",  c), 0.0) for c in comps])
        F_liq  = np.array([x.get(self._v_F("liquid", c), 0.0) for c in comps])

        T_feed = x.get(self._v_T("inlet"), 350.0)
        T_vap  = x.get(self._v_T("vapor"), 350.0)
        T_liq  = x.get(self._v_T("liquid"), 350.0)
        P_feed = x.get(self._v_P("inlet"), 101325.0)
        P_vap  = x.get(self._v_P("vapor"), 101325.0)
        P_liq  = x.get(self._v_P("liquid"), 101325.0)
        Q      = x.get(self._v_Q(), 0.0)
        V_frac = x.get(self._v_Vfrac(), 0.5)

        # Soft-clamp phase totals away from zero so y / xi stay bounded near
        # single-phase boundaries. Pre-v1.4.0 the floor was at _SMALL (1e-12)
        # which let mole fractions explode to 1e12 when one phase vanished
        # and the LP saw a near-singular Jacobian column. Lift the floor
        # to 1e-6 — accurate where the flash is two-phase, stable when it
        # is not. Audit M4.
        _PHASE_FLOOR = max(_SMALL, 1.0e-6)
        F_vap_total = max(float(F_vap.sum()), _PHASE_FLOOR)
        F_liq_total = max(float(F_liq.sum()), _PHASE_FLOOR)
        F_feed_total = max(float(F_feed.sum()), _SMALL)

        y = F_vap / F_vap_total  # vapour mole fractions
        xi = F_liq / F_liq_total  # liquid mole fractions

        # Material balances [N]
        res[:N] = F_feed - F_vap - F_liq

        # VLE: y_i = K_i(T_vap, P_vap, x) * x_i  [N]
        # When a property package is configured, the K-vector for its species
        # comes from package.K_iteration. Species outside the package — e.g.
        # permanent gases that don't participate in VLE — default to K = 1
        # (equal split), matching v1.5.3 behaviour.
        K_vec = np.ones(N, dtype=float)
        if self._package is not None:
            pkg_species = self._package.species
            # Build liquid mole fractions in package order.
            pkg_idx = self._package_index
            pkg_xi = np.array(
                [
                    xi[comps.index(sp)] if sp in comps else 0.0
                    for sp in pkg_species
                ]
            )
            pkg_y = np.array(
                [
                    y[comps.index(sp)] if sp in comps else 0.0
                    for sp in pkg_species
                ]
            )
            # Normalise inside the package's species set so K_iteration sees
            # consistent compositions (Σ x_i = 1 over package species).
            sx = pkg_xi.sum()
            sy = pkg_y.sum()
            if sx > 0:
                pkg_xi = pkg_xi / sx
            if sy > 0:
                pkg_y = pkg_y / sy
            try:
                K_pkg = self._package.K_iteration(T_vap, P_vap, pkg_xi, pkg_y)
            except Exception:
                # Fall back to legacy Antoine K to avoid hard-failure inside
                # the solver loop on a transient out-of-range evaluation.
                K_pkg = np.array(
                    [
                        K_value(sp, T_vap, P_vap) if sp in ANTOINE else 1.0
                        for sp in pkg_species
                    ]
                )
            for i, c in enumerate(comps):
                if c in pkg_idx:
                    K_vec[i] = float(K_pkg[pkg_idx[c]])
                # else: K_vec[i] stays at 1.0 (non-VLE species)
        else:
            # No package available (no Antoine-eligible species). Preserve
            # legacy fallback: K = 1 for everything → unit is essentially a
            # tee. Tested via the existing v1.5.3 regression suite.
            pass

        for i in range(N):
            res[N + i] = y[i] - K_vec[i] * xi[i]

        # Energy balance [1]
        H_feed = sum(F_feed[i] * enthalpy_J_mol(c, T_feed) for i, c in enumerate(comps) if c in _KNOWN)
        H_vap  = sum(F_vap[i]  * enthalpy_J_mol(c, T_vap)  for i, c in enumerate(comps) if c in _KNOWN)
        H_liq  = sum(F_liq[i]  * enthalpy_J_mol(c, T_liq)  for i, c in enumerate(comps) if c in _KNOWN)
        res[2 * N] = Q + H_feed - H_vap - H_liq

        # Pressure equalities [2]
        res[2 * N + 1] = P_vap - P_feed
        res[2 * N + 2] = P_liq - P_feed

        # Vapour fraction definition [1]
        res[2 * N + 3] = V_frac - F_vap_total / F_feed_total

        return res

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Closed-form Jacobian for the (2N + 4) residuals.

        Analytical path is exercised when the property package is
        :class:`IdealGasPackage` (the default — Antoine/Raoult, no
        composition dependence on ``K``). For non-ideal packages
        (``PengRobinsonPackage``, ``NRTLPackage``, ``UNIQUACPackage``)
        the VLE rows fall back to FD because ``K_i`` depends on the
        liquid mole fractions via fugacity / activity coefficients —
        these K-derivatives are owned by the package and not yet
        exposed uniformly. v1.7's property-package refactor adds
        ``dK_dT``, ``dK_dP``, ``dK_dx`` hooks that this routine will
        then chain through.

        Rows::

            i in 0..N-1: F_feed_i − F_vap_i − F_liq_i        (linear)
            N..2N-1:     y_i − K_i(T_vap, P_vap) · x_i
            2N:          Q + H_feed − H_vap − H_liq
            2N+1:        P_vap − P_feed
            2N+2:        P_liq − P_feed
            2N+3:        V_frac − F_vap_total / F_feed_total

        Validated in ``tests/test_analytical_jacobians.py::TestFlashVLAnalyticalJacobian``
        at 1e-4 rel / 1e-3 abs.
        """
        variables = self.variables()
        n = len(variables)
        vidx = {v: i for i, v in enumerate(variables)}
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)
        f0 = np.asarray(self.residual(x0_dict), dtype=float).reshape(-1)
        N = len(self.components)
        m = f0.size  # = 2N + 4
        J = np.zeros((m, n), dtype=float)

        # ── Material rows: trivial ─────────────────────────────────────────
        for i, c in enumerate(self.components):
            J[i, vidx[self._v_F("inlet", c)]] = +1.0
            J[i, vidx[self._v_F("vapor", c)]] = -1.0
            J[i, vidx[self._v_F("liquid", c)]] = -1.0

        # ── Pressure rows: trivial ─────────────────────────────────────────
        J[2 * N + 1, vidx[self._v_P("vapor")]] = +1.0
        J[2 * N + 1, vidx[self._v_P("inlet")]] = -1.0
        J[2 * N + 2, vidx[self._v_P("liquid")]] = +1.0
        J[2 * N + 2, vidx[self._v_P("inlet")]] = -1.0

        # ── Vfrac row ──────────────────────────────────────────────────────
        F_vap_total = sum(x0_dict.get(self._v_F("vapor", c), 0.0) for c in self.components)
        F_feed_total = sum(x0_dict.get(self._v_F("inlet", c), 0.0) for c in self.components)
        _PHASE_FLOOR = max(_SMALL, 1.0e-6)
        F_vap_safe = max(F_vap_total, _PHASE_FLOOR)
        F_feed_safe = max(F_feed_total, _SMALL)
        F_liq_safe = max(
            sum(x0_dict.get(self._v_F("liquid", c), 0.0) for c in self.components),
            _PHASE_FLOOR,
        )
        J[2 * N + 3, vidx[self._v_Vfrac()]] = 1.0
        for c in self.components:
            J[2 * N + 3, vidx[self._v_F("vapor", c)]] = -1.0 / F_feed_safe
            J[2 * N + 3, vidx[self._v_F("inlet", c)]] = F_vap_total / (F_feed_safe ** 2)

        # ── Energy row ─────────────────────────────────────────────────────
        T_feed = x0_dict.get(self._v_T("inlet"), 350.0)
        T_vap = x0_dict.get(self._v_T("vapor"), 350.0)
        T_liq = x0_dict.get(self._v_T("liquid"), 350.0)
        J[2 * N, vidx[self._v_Q()]] = 1.0
        Cp_feed_total = 0.0
        Cp_vap_total = 0.0
        Cp_liq_total = 0.0
        for c in self.components:
            if c not in _KNOWN:
                continue
            J[2 * N, vidx[self._v_F("inlet", c)]] = +enthalpy_J_mol(c, T_feed)
            J[2 * N, vidx[self._v_F("vapor", c)]] = -enthalpy_J_mol(c, T_vap)
            J[2 * N, vidx[self._v_F("liquid", c)]] = -enthalpy_J_mol(c, T_liq)
            Cp_feed_total += x0_dict.get(self._v_F("inlet", c), 0.0) * cp_J_mol_K(c, T_feed)
            Cp_vap_total += x0_dict.get(self._v_F("vapor", c), 0.0) * cp_J_mol_K(c, T_vap)
            Cp_liq_total += x0_dict.get(self._v_F("liquid", c), 0.0) * cp_J_mol_K(c, T_liq)
        J[2 * N, vidx[self._v_T("inlet")]] = +Cp_feed_total
        J[2 * N, vidx[self._v_T("vapor")]] = -Cp_vap_total
        J[2 * N, vidx[self._v_T("liquid")]] = -Cp_liq_total

        # ── VLE rows (analytical only for IdealGasPackage; else FD) ────────
        use_analytical_vle = isinstance(self._package, IdealGasPackage) or self._package is None
        P_vap = max(x0_dict.get(self._v_P("vapor"), 101325.0), 1e-3)

        if use_analytical_vle:
            # K_i = P_sat_i(T_vap) / P_vap if Antoine known, else 1.
            # dK_i/dT_vap = K_i * ln(10) * B_i / (T_C + C_i)²
            # dK_i/dP_vap = -K_i / P_vap
            T_C = T_vap - 273.15
            K_vec = np.ones(N, dtype=float)
            dK_dT = np.zeros(N, dtype=float)
            dK_dP = np.zeros(N, dtype=float)
            for i, c in enumerate(self.components):
                if c in ANTOINE:
                    K_i = K_value(c, T_vap, P_vap)
                    K_vec[i] = K_i
                    p = ANTOINE[c]
                    dK_dT[i] = K_i * _math.log(10.0) * p["B"] / ((T_C + p["C"]) ** 2)
                    dK_dP[i] = -K_i / P_vap
                # else K_i = 1, dK_dT = dK_dP = 0
            for i, c in enumerate(self.components):
                F_vap_i = x0_dict.get(self._v_F("vapor", c), 0.0)
                F_liq_i = x0_dict.get(self._v_F("liquid", c), 0.0)
                y_i = F_vap_i / F_vap_safe
                x_i = F_liq_i / F_liq_safe
                # ∂(y_i)/∂F_vap_j = (δ_ij − y_i)/F_vap_total
                for j, c2 in enumerate(self.components):
                    y_j_factor = (1.0 if i == j else 0.0) - y_i
                    J[N + i, vidx[self._v_F("vapor", c2)]] = y_j_factor / F_vap_safe
                    x_j_factor = (1.0 if i == j else 0.0) - x_i
                    J[N + i, vidx[self._v_F("liquid", c2)]] = -K_vec[i] * x_j_factor / F_liq_safe
                J[N + i, vidx[self._v_T("vapor")]] = -dK_dT[i] * x_i
                J[N + i, vidx[self._v_P("vapor")]] = -dK_dP[i] * x_i
        else:
            J_fd = self._finite_difference_jacobian(x0_dict, variables, f0)
            J[N : 2 * N, :] = J_fd[N : 2 * N, :]

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
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        """Flash drum purchase cost [USD, CE500 basis].

        v1.6 audit A.3: pre-audit the unit returned the base-class 0.0,
        which silently zero-rated flash drums in TEA. Sized from feed flow
        × τ = 30 s (typical flash drum holdup) at the feed state.
        """
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD

        F_total = sum(
            max(x.get(self._v_F("inlet", c), 0.0), 0.0)
            for c in self.components
        )
        T = max(x.get(self._v_T("inlet"), 350.0), 273.0)
        P = max(x.get(self._v_P("inlet"), 101325.0), 1.0)
        Q_vol = max(F_total, 0.01) * 8.314462 * T / P
        # 30 s holdup is a standard flash-drum heuristic (Towler & Sinnott
        # Ch. 17). The 0.1 m³ floor avoids zero-cost on toy / unused units.
        volume_m3 = max(Q_vol * 30.0, 0.1)
        return vessel_purchase_cost_USD(volume_m3)

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        V_frac = x.get(self._v_Vfrac(), float("nan"))
        F_vap_total = sum(x.get(self._v_F("vapor", c), 0.0) for c in self.components)
        F_liq_total = sum(x.get(self._v_F("liquid", c), 0.0) for c in self.components)
        return {
            "V_frac": V_frac,
            "vapor_flow_mol_s": F_vap_total,
            "liquid_flow_mol_s": F_liq_total,
            "Q_W": x.get(self._v_Q(), 0.0),
        }

    def design_sizing(self, x: Dict[str, float]) -> Dict[str, float]:
        """Required flash-drum volume + L/D from 30 s vapor-holdup heuristic
        (Towler-Sinnott Ch.17). L/D = 3 for vertical flash drums."""
        import math as _math

        F_total = sum(
            max(x.get(self._v_F("inlet", c), 0.0), 0.0)
            for c in self.components
        )
        T = max(x.get(self._v_T("inlet"), 350.0), 273.0)
        P = max(x.get(self._v_P("inlet"), 101325.0), 1.0)
        Q_vol = max(F_total, 0.01) * 8.314462 * T / P
        tau_s = 30.0
        V_req = max(Q_vol * tau_s, 0.1)
        L_over_D = 3.0
        # V = π·D²·L/4 = π·D³·(L/D)/4  ⇒  D = (4V/(π·L/D))^(1/3)
        D = (4.0 * V_req / (_math.pi * L_over_D)) ** (1.0 / 3.0)
        return {
            "V_required_m3": V_req,
            "residence_time_s": tau_s,
            "L_over_D": L_over_D,
            "diameter_m": D,
            "length_m": L_over_D * D,
        }
