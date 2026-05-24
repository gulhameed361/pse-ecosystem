"""Tests for the v1.6 activity-coefficient models (NRTL / Wilson / UNIQUAC).

Covers:
* Math primitives — γ → 1 at pure-component limit, γ → 1 with zero
  interaction parameters, infinite-dilution NRTL hand-checked.
* Binary parameter tables — registration, direction symmetry, default
  warnings on missing pairs.
* High-level packages — factory routing, K-value sanity (γ Psat / P),
  constructor validation (missing Antoine / r,q raises), modified-Raoult
  pure-component reduction (γ=1 ⇒ K = Psat/P).
* Cross-model consistency — at ideal limit, NRTL / Wilson / UNIQUAC all
  collapse to ideal Raoult.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pse_ecosystem.models.properties import (
    NRTLPackage,
    PHASE_VAPOR,
    UNIQUACPackage,
    WilsonPackage,
    get_property_package,
)
from pse_ecosystem.models.properties import activity_models as am
from pse_ecosystem.models.properties import vle as _vle


# ─────────────────────────────────────────────────────────────────────────────
# Math primitives
# ─────────────────────────────────────────────────────────────────────────────


class TestNRTLMath:
    def test_pure_component_limit(self):
        # Any species at x = [1, 0, ..., 0] must give γ = 1.
        N = 3
        x = np.array([1.0, 0.0, 0.0])
        tau = np.random.default_rng(0).normal(size=(N, N))
        np.fill_diagonal(tau, 0.0)
        G = np.exp(-0.3 * tau)
        np.fill_diagonal(G, 1.0)
        ln_g = am.nrtl_ln_gamma(x, tau, G)
        assert abs(ln_g[0]) < 1e-12

    def test_zero_interaction_gives_unity(self):
        # τ_ij = 0 for all i,j (perfectly ideal) ⇒ γ = 1 for every species
        N = 3
        x = np.array([0.3, 0.5, 0.2])
        tau = np.zeros((N, N))
        G = np.ones((N, N))
        ln_g = am.nrtl_ln_gamma(x, tau, G)
        assert np.allclose(ln_g, 0.0, atol=1e-12)

    def test_infinite_dilution_binary(self):
        """Binary NRTL at x_1 → 0: ln γ_1∞ = τ_21 + τ_12 · exp(−α·τ_12)."""
        tau = np.array([[0.0, 1.5], [-0.3, 0.0]])  # τ_12 = 1.5, τ_21 = -0.3
        alpha = 0.3
        G = np.exp(-alpha * tau)
        np.fill_diagonal(G, 1.0)
        x = np.array([1e-8, 1.0 - 1e-8])
        ln_g = am.nrtl_ln_gamma(x, tau, G)
        expected = -0.3 + 1.5 * math.exp(-alpha * 1.5)
        assert abs(ln_g[0] - expected) < 1e-5


class TestWilsonMath:
    def test_pure_component_limit(self):
        x = np.array([1.0, 0.0])
        Lam = np.array([[1.0, 0.4], [0.7, 1.0]])
        ln_g = am.wilson_ln_gamma(x, Lam)
        assert abs(ln_g[0]) < 1e-12

    def test_unit_lambda_gives_unity(self):
        x = np.array([0.3, 0.7])
        Lam = np.ones((2, 2))
        ln_g = am.wilson_ln_gamma(x, Lam)
        assert np.allclose(ln_g, 0.0, atol=1e-12)


class TestUNIQUACMath:
    def test_pure_component_limit_when_rq_match(self):
        # Pure-component limit: x = [1, 0]. Even with non-trivial τ the γ
        # value must collapse to 1 because the other species' contribution
        # weight vanishes.
        x = np.array([1.0, 0.0])
        r = np.array([1.5, 2.0])
        q = np.array([1.4, 1.8])
        tau = np.array([[1.0, 0.7], [1.2, 1.0]])
        ln_g = am.uniquac_ln_gamma(x, r, q, tau)
        assert abs(ln_g[0]) < 1e-12

    def test_identical_species_gives_unity(self):
        # If r_i = r_j and q_i = q_j and τ_ij = 1, both γ = 1.
        x = np.array([0.4, 0.6])
        r = np.array([2.0, 2.0])
        q = np.array([1.7, 1.7])
        tau = np.ones((2, 2))
        ln_g = am.uniquac_ln_gamma(x, r, q, tau)
        assert np.allclose(ln_g, 0.0, atol=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# Binary parameter tables
# ─────────────────────────────────────────────────────────────────────────────


class TestBinaryTables:
    def test_nrtl_lookup_symmetric(self):
        # ethanol-water is pre-populated. Look up both directions.
        ab = am.get_nrtl_pair("ethanol", "water")
        ba = am.get_nrtl_pair("water", "ethanol")
        assert ab is not None and ba is not None
        # A_a→b in (eth, water) order must equal A_b→a in reverse-order tuple.
        assert ab[0] == ba[1] and ab[1] == ba[0]
        assert ab[2] == ba[2]  # same α

    def test_uniquac_lookup_symmetric(self):
        ab = am.get_uniquac_pair("ethanol", "water")
        ba = am.get_uniquac_pair("water", "ethanol")
        assert ab is not None and ba is not None
        assert ab[0] == ba[1] and ab[1] == ba[0]

    def test_wilson_lookup_symmetric(self):
        ab = am.get_wilson_pair("ethanol", "water")
        ba = am.get_wilson_pair("water", "ethanol")
        assert ab is not None and ba is not None
        # ab = (a_eth→water, b_eth→water, a_water→eth, b_water→eth)
        # ba = (a_water→eth, b_water→eth, a_eth→water, b_eth→water)
        assert ab[0] == ba[2] and ab[1] == ba[3]

    def test_unknown_pair_returns_none(self):
        assert am.get_nrtl_pair("ethanol", "n-heptane") is None
        assert am.get_uniquac_pair("benzene", "water") is None

    def test_register_runtime(self):
        pair = am.NRTLPair(A_ab_K=10.0, A_ba_K=-20.0, alpha=0.4, source="test")
        am.register_nrtl_pair("dummyA", "dummyB", pair)
        try:
            ab = am.get_nrtl_pair("dummyA", "dummyB")
            ba = am.get_nrtl_pair("dummyB", "dummyA")
            assert ab == (10.0, -20.0, 0.4)
            assert ba == (-20.0, 10.0, 0.4)
        finally:
            am._NRTL.pop(("dummyA", "dummyB"), None)


# ─────────────────────────────────────────────────────────────────────────────
# Factory / constructor validation
# ─────────────────────────────────────────────────────────────────────────────


class TestFactory:
    def test_get_nrtl(self):
        pkg = get_property_package("nrtl", ["ethanol", "water"])
        assert isinstance(pkg, NRTLPackage)
        assert pkg.method_name == "nrtl"

    def test_get_wilson(self):
        pkg = get_property_package("wilson", ["ethanol", "water"])
        assert isinstance(pkg, WilsonPackage)

    def test_get_uniquac(self):
        pkg = get_property_package("uniquac", ["ethanol", "water"])
        assert isinstance(pkg, UNIQUACPackage)


class TestConstructorValidation:
    def test_nrtl_requires_antoine(self):
        # CH4 has Antoine; N2 does not. Activity models reject non-condensables.
        with pytest.raises(ValueError, match="Antoine"):
            NRTLPackage(["methanol", "N2"])

    def test_uniquac_requires_rq(self):
        # CH4 has Antoine but no UNIQUAC r/q in the registry.
        with pytest.raises(ValueError, match="r, q"):
            UNIQUACPackage(["methanol", "CH4"])

    def test_wilson_warns_on_missing_pair(self):
        # benzene-water is not pre-populated → expect a UserWarning.
        with pytest.warns(UserWarning, match="Wilson parameters missing"):
            WilsonPackage(["benzene", "water"])


# ─────────────────────────────────────────────────────────────────────────────
# K-value behaviour (modified Raoult)
# ─────────────────────────────────────────────────────────────────────────────


class TestKValueModifiedRaoult:
    def test_pure_component_K_equals_Psat_over_P(self):
        # x = [1, 0]: γ_1 = 1, so K_1 = Psat_1 / P.
        pkg = NRTLPackage(["ethanol", "water"])
        T, P = 350.0, 101325.0
        K = pkg.K_values(T, P, np.array([1.0, 0.0]))
        Psat_eth = pkg._psat("ethanol", T)
        assert abs(K[0] - Psat_eth / P) / (Psat_eth / P) < 1e-9

    def test_K_decreases_with_pressure(self):
        pkg = NRTLPackage(["ethanol", "water"])
        K_low = pkg.K_values(350.0, 50_000.0, np.array([0.5, 0.5]))
        K_high = pkg.K_values(350.0, 200_000.0, np.array([0.5, 0.5]))
        assert np.all(K_low > K_high)

    def test_ethanol_more_volatile_than_water(self):
        # At 78°C and 1 atm, K(ethanol) > K(water).
        pkg = NRTLPackage(["ethanol", "water"])
        K = pkg.K_values(351.5, 101325.0, np.array([0.5, 0.5]))
        assert K[0] > K[1]


class TestActivityCoefficientReduction:
    def test_nrtl_pure_component_gamma_one(self):
        pkg = NRTLPackage(["ethanol", "water"])
        g = pkg.activity_coefficients(350.0, np.array([1.0, 0.0]))
        assert abs(g[0] - 1.0) < 1e-12

    def test_wilson_pure_component_gamma_one(self):
        pkg = WilsonPackage(["ethanol", "water"])
        g = pkg.activity_coefficients(350.0, np.array([1.0, 0.0]))
        assert abs(g[0] - 1.0) < 1e-12

    def test_uniquac_pure_component_gamma_one(self):
        pkg = UNIQUACPackage(["ethanol", "water"])
        g = pkg.activity_coefficients(350.0, np.array([1.0, 0.0]))
        assert abs(g[0] - 1.0) < 1e-12

    def test_ethanol_water_gamma_realistic(self):
        # At 25°C in dilute ethanol, γ_eth should be substantially above 1
        # (positive deviation from Raoult — the classic minimum-boiling azeotrope
        # system). Order-of-magnitude check only.
        pkg = NRTLPackage(["ethanol", "water"])
        g = pkg.activity_coefficients(298.15, np.array([0.01, 0.99]))
        assert g[0] > 2.0


class TestDensityFallback:
    def test_vapor_density_ideal_gas(self):
        pkg = NRTLPackage(["ethanol", "water"])
        rho = pkg.density(400.0, 1.0e5, np.array([0.5, 0.5]), PHASE_VAPOR)
        assert abs(rho - 1.0e5 / (8.314462 * 400.0)) / rho < 1e-9

    def test_liquid_density_raises(self):
        pkg = NRTLPackage(["ethanol", "water"])
        with pytest.raises(NotImplementedError, match="liquid"):
            pkg.density(350.0, 1.0e5, np.array([0.5, 0.5]), phase="liquid")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-model consistency
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossModelIdealLimit:
    """All three models must collapse to ideal Raoult when their interaction
    parameters are zero / unity (γ = 1 for every composition)."""

    def test_nrtl_ideal_limit(self):
        # Construct an NRTLPackage with all parameters explicitly zero.
        params = {
            ("benzene", "toluene"): am.NRTLPair(0.0, 0.0, alpha=0.3),
        }
        pkg = NRTLPackage(["benzene", "toluene"], params=params)
        g = pkg.activity_coefficients(380.0, np.array([0.3, 0.7]))
        assert np.allclose(g, 1.0, atol=1e-9)

    def test_wilson_ideal_limit(self):
        params = {
            ("benzene", "toluene"): am.WilsonPair(
                a_ab=0.0, b_ab_K=0.0, a_ba=0.0, b_ba_K=0.0
            ),
        }
        pkg = WilsonPackage(["benzene", "toluene"], params=params)
        g = pkg.activity_coefficients(380.0, np.array([0.3, 0.7]))
        assert np.allclose(g, 1.0, atol=1e-9)

    def test_uniquac_ideal_limit_matched_rq(self):
        # When all r and q are equal and interaction A = 0, UNIQUAC γ = 1.
        params = {("benzene", "toluene"): am.UNIQUACPair(0.0, 0.0)}
        pkg = UNIQUACPackage(["benzene", "toluene"], params=params)
        # Override r and q so they match (eliminates combinatorial contribution)
        pkg._r = np.array([3.0, 3.0])
        pkg._q = np.array([2.5, 2.5])
        g = pkg.activity_coefficients(380.0, np.array([0.3, 0.7]))
        assert np.allclose(g, 1.0, atol=1e-9)
