"""Regression tests for the v1.6.1 deep-audit fixes.

Each test guards a specific defect found in the platform audit:

- A1  TRF trust-region toggle: tr_multiplier=0.0 must omit the trust-region box.
- A2  Equilibrium-reactor inner Newton converges to the true Keq (the inner
      Jacobian baseline used a sum instead of the reaction product).
- A3  capex() and design_sizing() must price/size off the *same* vessel volume
      (both now use the module gas constant; previously 8.314 vs 8.314462).
- A5  Funnel switching condition must actually use the ``alpha`` exponent on θ_k
      (alpha was a dead parameter before the fix).
"""
from __future__ import annotations

import numpy as np
import pytest

from pse_ecosystem.models.reactors.equilibrium_reactor import (
    EquilibriumReactor,
    EquilReactorParams,
)
from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig


def _wgs_reactor() -> EquilibriumReactor:
    """Water-gas-shift equilibrium reactor: CO + H2O <=> CO2 + H2."""
    rxn = ReactionConfig(
        stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
        k0=1.0, Ea_J_per_mol=0.0,
        reaction_orders={"CO": 1.0, "H2O": 1.0},
        delta_H_J_per_mol=-41100.0,
    )
    params = EquilReactorParams(reactions=[rxn], Keq_ref=[3.5], T_ref_K=1100.0)
    return EquilibriumReactor("eq_rxn", ["CO", "H2O", "CO2", "H2", "N2"], params)


# ── A2: inner Newton reaches equilibrium ──────────────────────────────────────
def test_equilibrium_inner_solve_satisfies_keq():
    r = _wgs_reactor()
    # Seed a little product so the Newton inner solve starts with a non-zero
    # equilibrium-product Jacobian (xi=0 with zero products is a degenerate start).
    F_in = np.array([10.0, 10.0, 2.0, 2.0, 5.0])  # CO, H2O, CO2, H2, N2
    T = 1100.0

    xi = r._inner_solve(F_in, T)
    F_out = np.maximum(F_in + r._nu @ xi, 1e-12)
    x = F_out / F_out.sum()

    nu = r._nu[:, 0]
    prod = 1.0
    for i in range(len(r.components)):
        if nu[i] != 0.0:
            prod *= float(x[i]) ** nu[i]

    Keq = r._Keq(0, T)
    # The converged composition must satisfy the equilibrium relation Π x_i^ν = Keq.
    assert prod == pytest.approx(Keq, rel=2e-2)


# ── A3: capex and design_sizing share one vessel volume ───────────────────────
def test_equilibrium_reactor_capex_and_design_volume_consistent():
    from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD

    r = _wgs_reactor()
    x = {r._v_F_in(c): f for c, f in zip(r.components, [10.0, 10.0, 0.0, 0.0, 5.0])}
    x[r._v_T_in()] = 1100.0
    x[r._v_P_in()] = 2.0e5

    design = r.design_sizing(x)
    # capex() must be priced off the exact volume design_sizing() reports.
    expected = vessel_purchase_cost_USD(design["V_required_m3"])
    assert r.capex(x) == pytest.approx(expected, rel=1e-9)


# ── A5: funnel switching condition uses the alpha exponent ─────────────────────
def test_funnel_switching_uses_alpha_exponent():
    from pse_ecosystem.solvers.trf.funnel import Funnel

    theta_old = 0.5
    mu_s = 0.1

    # alpha=2 → threshold = mu_s * theta_old**2 = 0.1 * 0.25 = 0.025
    f2 = Funnel(
        phi_init=1.0, f_best_init=10.0, phi_min=1e-6,
        kappa_f=0.5, kappa_r=1.1, alpha=2.0, beta=0.8, mu_s=mu_s, eta=1e-4,
    )
    assert f2._switching(10.0, 9.97, theta_old) is True    # Δf=0.03 ≥ 0.025
    assert f2._switching(10.0, 9.99, theta_old) is False   # Δf=0.01 < 0.025

    # alpha=1 → threshold = mu_s * theta_old = 0.1 * 0.5 = 0.05 (different from above)
    f1 = Funnel(
        phi_init=1.0, f_best_init=10.0, phi_min=1e-6,
        kappa_f=0.5, kappa_r=1.1, alpha=1.0, beta=0.8, mu_s=mu_s, eta=1e-4,
    )
    assert f1._switching(10.0, 9.97, theta_old) is False   # Δf=0.03 < 0.05
    assert f1._switching(10.0, 9.94, theta_old) is True    # Δf=0.06 ≥ 0.05
    # Same Δf=0.03 flips between True (alpha=2) and False (alpha=1): alpha is live.


# ── A1: TRF driver must pass tr_multiplier=0.0 when the trust region is off ────
def test_trf_driver_passes_zero_tr_multiplier_when_disabled(monkeypatch):
    import pse_ecosystem.solvers.trust_region_driver as trf_mod
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.solvers.trust_region_driver import TRFConfig, TrustRegionDriver

    captured = {}
    real_build_lp = trf_mod.build_lp

    def spy(*args, **kwargs):
        captured["tr_multiplier"] = kwargs.get("tr_multiplier")
        return real_build_lp(*args, **kwargs)

    monkeypatch.setattr(trf_mod, "build_lp", spy)

    gas = GasifierToy(unit_id="gasifier")
    fs = BaseFlowsheet(
        name="trf_toggle", units=[gas], connections=[], objective_kpi="annual_cost"
    )
    fs.extra_equalities.append(({gas.v_h2: 1.0}, 200.0))

    driver = TrustRegionDriver(
        fs,
        config=TRFConfig(max_iter=1),
        slp_config=SLPConfig(use_trust_region=False, max_iter=1),
    )
    try:
        driver.run()
    except Exception:  # noqa: BLE001 — we only assert what build_lp received
        pass

    # The bug passed `delta` regardless; the fix passes 0.0, which build_lp
    # treats as "no trust-region box".
    assert captured.get("tr_multiplier") == 0.0
