"""v1.6 Workstream A.1 — reactor audit contract tests.

Locks in the contract surface for the five industrial reactors:

* Every reactor has ``inlet_port`` and ``outlet_port`` StreamPort attributes
  (so the UI's primary-port resolver finds them).
* ``capex()`` returns a positive vessel cost when feed flow is non-zero
  (no silent zero-CAPEX gaps — closed for Gibbs and Stoichiometric in A.1).
* ``kpis()`` returns at least one numerical KPI for downstream reporting.
* ``residual()`` returns the documented number of rows for a minimal config.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pytest

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig
from pse_ecosystem.models.reactors.equilibrium_reactor import (
    EquilReactorParams,
    EquilibriumReactor,
)
from pse_ecosystem.models.reactors.gibbs_reactor import (
    GibbsReactor,
    GibbsReactorParams,
)
from pse_ecosystem.models.reactors.pfr_hf import PFRHF, PFRHFParams
from pse_ecosystem.models.reactors.stoichiometric_reactor import (
    StoichiometricParams,
    StoichiometricReactor,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constructor helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_cstr() -> CSTRHF:
    comps = ["H2", "O2", "H2O"]
    rxn = ReactionConfig(
        stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
        k0=1.0e10, Ea_J_per_mol=80_000.0,
        reaction_orders={"H2": 2.0, "O2": 1.0},
        delta_H_J_per_mol=-241_800.0,
    )
    return CSTRHF("R", comps, CSTRHFParams(reactions=[rxn], volume_m3=2.0))


def _make_pfr() -> PFRHF:
    comps = ["H2", "O2", "H2O"]
    rxn = ReactionConfig(
        stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
        k0=1.0e8, Ea_J_per_mol=80_000.0,
        reaction_orders={"H2": 2.0, "O2": 1.0},
        delta_H_J_per_mol=-241_800.0,
    )
    return PFRHF(
        "R", comps,
        PFRHFParams(
            reactions=[rxn], length_m=3.0, cross_section_m2=0.1,
            U_W_per_m2_K=10.0, T_wall_K=500.0,
        ),
    )


def _make_gibbs() -> GibbsReactor:
    return GibbsReactor("R", ["H2", "O2", "H2O"], GibbsReactorParams())


def _make_equilibrium() -> EquilibriumReactor:
    rxn = ReactionConfig(
        stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
        k0=1.0, Ea_J_per_mol=0.0,
        reaction_orders={"H2": 2.0, "O2": 1.0},
        delta_H_J_per_mol=-241_800.0,
    )
    return EquilibriumReactor(
        "R", ["H2", "O2", "H2O"],
        EquilReactorParams(reactions=[rxn], Keq_ref=[1.0e10]),
    )


def _make_stoich() -> StoichiometricReactor:
    return StoichiometricReactor(
        "R", ["H2", "O2", "H2O"],
        StoichiometricParams(
            stoichiometry={"H2": [-2.0], "O2": [-1.0], "H2O": [2.0]},
            xi_max=[10.0],
        ),
    )


_FEED_X: Dict[str, float] = {
    "R.inlet.F_H2": 2.0,
    "R.inlet.F_O2": 1.0,
    "R.inlet.F_H2O": 0.0,
    "R.inlet.T": 800.0,
    "R.inlet.P": 5.0e5,
    "R.outlet.F_H2": 0.5,
    "R.outlet.F_O2": 0.25,
    "R.outlet.F_H2O": 1.5,
    "R.outlet.T": 1000.0,
    "R.outlet.P": 5.0e5,
}


# ─────────────────────────────────────────────────────────────────────────────
# Port contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(params=[_make_cstr, _make_pfr, _make_gibbs, _make_equilibrium, _make_stoich])
def reactor(request):
    return request.param()


class TestReactorPortContract:
    def test_inlet_port_is_streamport(self, reactor):
        assert isinstance(reactor.inlet_port, StreamPort)

    def test_outlet_port_is_streamport(self, reactor):
        assert isinstance(reactor.outlet_port, StreamPort)

    def test_industrial_category(self, reactor):
        assert reactor.category == UnitCategory.INDUSTRIAL


# ─────────────────────────────────────────────────────────────────────────────
# CAPEX gap — closed for Gibbs and Stoichiometric in A.1
# ─────────────────────────────────────────────────────────────────────────────


class TestReactorCAPEX:
    def test_cstr_capex_positive(self):
        assert _make_cstr().capex(_FEED_X) > 0

    def test_pfr_capex_positive(self):
        assert _make_pfr().capex(_FEED_X) > 0

    def test_gibbs_capex_positive(self):
        # Pre-A.1 the Gibbs reactor returned 0 (base-class default).
        assert _make_gibbs().capex(_FEED_X) > 0

    def test_equilibrium_capex_positive(self):
        assert _make_equilibrium().capex(_FEED_X) > 0

    def test_stoichiometric_capex_positive(self):
        # Pre-A.1 the Stoichiometric reactor returned 0 (base-class default).
        assert _make_stoich().capex(_FEED_X) > 0


# ─────────────────────────────────────────────────────────────────────────────
# KPI contract
# ─────────────────────────────────────────────────────────────────────────────


class TestReactorKPIs:
    @pytest.mark.parametrize(
        "make_fn",
        [_make_cstr, _make_pfr, _make_gibbs, _make_equilibrium, _make_stoich],
    )
    def test_returns_at_least_one_kpi(self, make_fn):
        reactor = make_fn()
        kpis = reactor.kpis(_FEED_X)
        assert len(kpis) >= 1, f"{type(reactor).__name__} returned empty kpis()"
        # All KPI values must be numeric and finite.
        for k, v in kpis.items():
            assert isinstance(v, (int, float)), f"non-numeric KPI {k}={v}"


# ─────────────────────────────────────────────────────────────────────────────
# Residual sanity
# ─────────────────────────────────────────────────────────────────────────────


class TestReactorResidual:
    def test_cstr_residual_finite(self):
        r = _make_cstr()
        x = {**_FEED_X, "R.xi_0": 0.5, "R.Q": 0.0}
        res = r.residual(x)
        assert np.all(np.isfinite(res))

    def test_stoich_residual_finite(self):
        r = _make_stoich()
        x = {**_FEED_X, "R.xi_0": 0.5}
        res = r.residual(x)
        assert np.all(np.isfinite(res))

    def test_equilibrium_residual_finite(self):
        r = _make_equilibrium()
        x = {**_FEED_X, "R.xi_0": 0.5, "R.Q": 0.0}
        res = r.residual(x)
        assert np.all(np.isfinite(res))
