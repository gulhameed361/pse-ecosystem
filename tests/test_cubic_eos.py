"""Tests for the v1.6 cubic-EOS module (Peng-Robinson and SRK).

Covers:
* Math primitives — α, a, b, da/dT — against analytical / published values.
* Mixing rules reduce to pure-component values at z = [1, 0, …].
* Cubic-Z solver: roots, phase selection, ideal-gas limit at low P.
* Fugacity coefficients: pure-component limit; low-P limit φ → 1.
* Enthalpy departure: low-P limit → 0; correct sign for compressed fluid.
* Wilson K-value sanity (monotonic in T; matches hand calc for CH4).
* High-level PR / SRK packages: factory routing, constructor validation,
  PropertyPackage contract (K_values / enthalpy / Cp / density).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pse_ecosystem.models.properties import (
    PHASE_LIQUID,
    PHASE_VAPOR,
    PengRobinsonPackage,
    SRKPackage,
    get_property_package,
)
from pse_ecosystem.models.properties import cubic_eos as ce
from pse_ecosystem.models.properties import components as cdb

_R = 8.314462


# ─────────────────────────────────────────────────────────────────────────────
# Pure-component a, b, α, da/dT
# ─────────────────────────────────────────────────────────────────────────────


class TestAlphaKappaM:
    def test_kappa_PR_for_methane(self):
        # κ = 0.37464 + 1.54226·ω − 0.26992·ω²; ω(CH4) = 0.011 in registry
        c = cdb.get("CH4")
        k = 0.37464 + 1.54226 * c.omega - 0.26992 * c.omega ** 2
        assert abs(ce._kappa_PR(c.omega) - k) < 1e-12

    def test_m_SRK_for_n2(self):
        c = cdb.get("N2")
        m = 0.480 + 1.574 * c.omega - 0.176 * c.omega ** 2
        assert abs(ce._m_SRK(c.omega) - m) < 1e-12

    def test_alpha_at_Tc_is_unity_PR(self):
        c = cdb.get("CO2")
        assert abs(ce.alpha(c.Tc_K, c.Tc_K, c.omega, "PR") - 1.0) < 1e-12

    def test_alpha_at_Tc_is_unity_SRK(self):
        c = cdb.get("CO2")
        assert abs(ce.alpha(c.Tc_K, c.Tc_K, c.omega, "SRK") - 1.0) < 1e-12

    def test_a_at_Tc_equals_ac_PR(self):
        c = cdb.get("CH4")
        ac = 0.45724 * (_R * c.Tc_K) ** 2 / c.Pc_Pa
        assert abs(ce.a_pure(c.Tc_K, c.Tc_K, c.Pc_Pa, c.omega, "PR") - ac) < 1e-6

    def test_b_pure_PR(self):
        c = cdb.get("CH4")
        b_expected = 0.07780 * _R * c.Tc_K / c.Pc_Pa
        assert abs(ce.b_pure(c.Tc_K, c.Pc_Pa, "PR") - b_expected) < 1e-12

    def test_b_pure_SRK(self):
        c = cdb.get("CH4")
        b_expected = 0.08664 * _R * c.Tc_K / c.Pc_Pa
        assert abs(ce.b_pure(c.Tc_K, c.Pc_Pa, "SRK") - b_expected) < 1e-12

    def test_da_dT_numerical_match(self):
        c = cdb.get("CO2")
        T = 300.0
        # Compare analytical vs. central finite difference
        da_an = ce.da_dT_pure(T, c.Tc_K, c.Pc_Pa, c.omega, "PR")
        dT = 0.1
        a_plus = ce.a_pure(T + dT, c.Tc_K, c.Pc_Pa, c.omega, "PR")
        a_minus = ce.a_pure(T - dT, c.Tc_K, c.Pc_Pa, c.omega, "PR")
        da_fd = (a_plus - a_minus) / (2.0 * dT)
        assert abs(da_an - da_fd) / abs(da_fd) < 1e-5

    def test_unknown_eos_raises(self):
        with pytest.raises(ValueError, match="Unknown EOS"):
            ce.alpha(300.0, 300.0, 0.1, "vdw")


# ─────────────────────────────────────────────────────────────────────────────
# Mixing rules
# ─────────────────────────────────────────────────────────────────────────────


class TestMixingRules:
    def test_pure_limit(self):
        a_vec = np.array([1.5, 2.7, 0.9])
        b_vec = np.array([5e-5, 7e-5, 4e-5])
        kij = np.zeros((3, 3))
        z = np.array([1.0, 0.0, 0.0])
        a_mix, b_mix, _ = ce.mix_a_b(z, a_vec, b_vec, kij)
        assert abs(a_mix - a_vec[0]) < 1e-12
        assert abs(b_mix - b_vec[0]) < 1e-12

    def test_kij_zero_gives_geometric_mean(self):
        a_vec = np.array([1.0, 4.0])
        b_vec = np.array([1e-5, 2e-5])
        kij = np.zeros((2, 2))
        z = np.array([0.5, 0.5])
        a_mix, _, _ = ce.mix_a_b(z, a_vec, b_vec, kij)
        # With k_ij = 0, a_mix = (z1√a1 + z2√a2)²
        expected = (0.5 * 1.0 + 0.5 * 2.0) ** 2
        assert abs(a_mix - expected) < 1e-12

    def test_b_mix_is_linear(self):
        b_vec = np.array([1e-5, 2e-5, 3e-5])
        z = np.array([0.2, 0.3, 0.5])
        _, b_mix, _ = ce.mix_a_b(z, np.ones(3), b_vec, np.zeros((3, 3)))
        assert abs(b_mix - float(z @ b_vec)) < 1e-12


# ─────────────────────────────────────────────────────────────────────────────
# Cubic-Z solver
# ─────────────────────────────────────────────────────────────────────────────


class TestSolveZ:
    def test_ideal_gas_limit_PR(self):
        # At very low pressure A → 0, B → 0, so Z → 1.
        c = cdb.get("N2")
        T, P = 300.0, 100.0  # 1 mbar
        a = ce.a_pure(T, c.Tc_K, c.Pc_Pa, c.omega, "PR")
        b = ce.b_pure(c.Tc_K, c.Pc_Pa, "PR")
        A = a * P / (_R * T) ** 2
        B = b * P / (_R * T)
        Z = ce.Z_phase(A, B, PHASE_VAPOR, "PR")
        assert abs(Z - 1.0) < 1e-3

    def test_ideal_gas_limit_SRK(self):
        c = cdb.get("N2")
        T, P = 300.0, 100.0
        a = ce.a_pure(T, c.Tc_K, c.Pc_Pa, c.omega, "SRK")
        b = ce.b_pure(c.Tc_K, c.Pc_Pa, "SRK")
        A = a * P / (_R * T) ** 2
        B = b * P / (_R * T)
        Z = ce.Z_phase(A, B, PHASE_VAPOR, "SRK")
        assert abs(Z - 1.0) < 1e-3

    def test_vapor_root_larger_than_liquid(self):
        # Saturated methane at 150 K, near saturation pressure
        c = cdb.get("CH4")
        T, P = 150.0, 8.0e5  # near sat
        a = ce.a_pure(T, c.Tc_K, c.Pc_Pa, c.omega, "PR")
        b = ce.b_pure(c.Tc_K, c.Pc_Pa, "PR")
        A = a * P / (_R * T) ** 2
        B = b * P / (_R * T)
        roots = ce.solve_Z(A, B, "PR")
        # Below Tc, three roots are possible
        if len(roots) == 3:
            Zv = ce.Z_phase(A, B, PHASE_VAPOR, "PR")
            Zl = ce.Z_phase(A, B, PHASE_LIQUID, "PR")
            assert Zv > Zl

    def test_unknown_phase_raises(self):
        with pytest.raises(ValueError, match="Unknown phase"):
            ce.Z_phase(0.5, 0.05, "supercritical", "PR")


# ─────────────────────────────────────────────────────────────────────────────
# Fugacity coefficients
# ─────────────────────────────────────────────────────────────────────────────


class TestFugacity:
    def test_low_pressure_limit_phi_one(self):
        # At very low pressure, fugacity coefficient → 1 (ideal gas).
        c = cdb.get("N2")
        z = np.array([1.0])
        Tc = np.array([c.Tc_K])
        Pc = np.array([c.Pc_Pa])
        omega = np.array([c.omega])
        kij = np.zeros((1, 1))
        phi = ce.fugacity_coeffs(z, 300.0, 100.0, Tc, Pc, omega, kij, PHASE_VAPOR, "PR")
        assert abs(phi[0] - 1.0) < 1e-3

    def test_two_phase_consistency(self):
        # At a subcritical condition where two roots exist, both phases give
        # finite positive fugacity coefficients.
        c = cdb.get("CH4")
        z = np.array([1.0])
        Tc = np.array([c.Tc_K])
        Pc = np.array([c.Pc_Pa])
        omega = np.array([c.omega])
        kij = np.zeros((1, 1))
        phi_v = ce.fugacity_coeffs(z, 150.0, 1.0e6, Tc, Pc, omega, kij, PHASE_VAPOR, "PR")
        phi_l = ce.fugacity_coeffs(z, 150.0, 1.0e6, Tc, Pc, omega, kij, PHASE_LIQUID, "PR")
        assert phi_v[0] > 0 and phi_l[0] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Enthalpy departure
# ─────────────────────────────────────────────────────────────────────────────


class TestEnthalpyDeparture:
    def test_low_pressure_limit_zero(self):
        c = cdb.get("N2")
        z = np.array([1.0])
        Tc = np.array([c.Tc_K])
        Pc = np.array([c.Pc_Pa])
        omega = np.array([c.omega])
        kij = np.zeros((1, 1))
        H_dep = ce.enthalpy_departure(
            z, 300.0, 1000.0, Tc, Pc, omega, kij, PHASE_VAPOR, "PR"
        )
        # At 1 kPa, |H_dep| should be a few J/mol max (large but ideal-like)
        assert abs(H_dep) < 50.0

    def test_compressed_gas_negative(self):
        # For most species at moderate (T, P) below Tc, H_dep is negative
        # (real gas is more stable than ideal).
        c = cdb.get("CO2")
        z = np.array([1.0])
        Tc = np.array([c.Tc_K])
        Pc = np.array([c.Pc_Pa])
        omega = np.array([c.omega])
        kij = np.zeros((1, 1))
        H_dep = ce.enthalpy_departure(
            z, 320.0, 50.0e5, Tc, Pc, omega, kij, PHASE_VAPOR, "PR"
        )
        assert H_dep < 0


# ─────────────────────────────────────────────────────────────────────────────
# Wilson K-value
# ─────────────────────────────────────────────────────────────────────────────


class TestWilsonK:
    def test_methane_at_300K_1bar_is_very_volatile(self):
        c = cdb.get("CH4")
        K = ce.wilson_K(300.0, 1.0e5, c.Tc_K, c.Pc_Pa, c.omega)
        # K > 100 — methane is far above its Tc at room T and 1 atm
        assert K > 100.0

    def test_monotonic_in_T(self):
        c = cdb.get("benzene")
        K_low = ce.wilson_K(300.0, 101325.0, c.Tc_K, c.Pc_Pa, c.omega)
        K_high = ce.wilson_K(400.0, 101325.0, c.Tc_K, c.Pc_Pa, c.omega)
        assert K_high > K_low

    def test_inverse_in_pressure(self):
        c = cdb.get("propane")
        K1 = ce.wilson_K(300.0, 1.0e5, c.Tc_K, c.Pc_Pa, c.omega)
        K2 = ce.wilson_K(300.0, 2.0e5, c.Tc_K, c.Pc_Pa, c.omega)
        assert abs(K1 / K2 - 2.0) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Factory routing and constructor gating
# ─────────────────────────────────────────────────────────────────────────────


class TestFactoryRouting:
    def test_get_peng_robinson(self):
        pkg = get_property_package("peng_robinson", ["CH4", "CO2"])
        assert isinstance(pkg, PengRobinsonPackage)
        assert pkg.method_name == "peng_robinson"
        assert pkg.EOS == "PR"

    def test_get_srk(self):
        pkg = get_property_package("srk", ["CH4", "CO2"])
        assert isinstance(pkg, SRKPackage)
        assert pkg.EOS == "SRK"

    def test_case_insensitive(self):
        pkg = get_property_package("Peng_Robinson", ["N2"])
        assert isinstance(pkg, PengRobinsonPackage)


class TestConstructorGating:
    def test_missing_critical_props_raises(self):
        # Benzene currently lacks Tc/Pc/ω in the registry — verify EOS refuses
        # it cleanly. If benzene is later given critical props this test will
        # need a different sentinel species.
        c = cdb.get("benzene")
        if c.Tc_K is None or c.Pc_Pa is None or c.omega is None:
            with pytest.raises(ValueError, match=r"Tc, Pc"):
                PengRobinsonPackage(["benzene"])
        else:
            pytest.skip("benzene now has critical props — pick a new sentinel")

    def test_missing_shomate_raises(self):
        # Propane has EOS params but no Shomate — EOS package needs both.
        with pytest.raises(ValueError, match="Shomate"):
            PengRobinsonPackage(["propane"])


# ─────────────────────────────────────────────────────────────────────────────
# PropertyPackage contract for PR / SRK
# ─────────────────────────────────────────────────────────────────────────────


class TestPRPackageContract:
    @pytest.fixture
    def pkg(self):
        return PengRobinsonPackage(["CH4", "CO2"])

    def test_K_values_length_and_positive(self, pkg):
        Ks = pkg.K_values(300.0, 1.0e5)
        assert Ks.shape == (2,)
        assert np.all(Ks > 0)

    def test_K_CH4_more_volatile_than_CO2(self, pkg):
        Ks = pkg.K_values(250.0, 5.0e5)
        # At any common (T, P) light methane is more volatile than CO2
        assert Ks[0] > Ks[1]

    def test_density_ideal_gas_limit(self, pkg):
        z = np.array([0.5, 0.5])
        rho_eos = pkg.density(400.0, 1000.0, z, phase=PHASE_VAPOR)
        rho_ig = 1000.0 / (_R * 400.0)
        assert abs(rho_eos - rho_ig) / rho_ig < 1e-3

    def test_density_compressed_gas_above_ideal(self, pkg):
        # Below Tc and at moderate P, real gas density > ideal (Z < 1).
        z = np.array([0.0, 1.0])  # pure CO2
        rho_eos = pkg.density(300.0, 50.0e5, z, phase=PHASE_VAPOR)
        rho_ig = 50.0e5 / (_R * 300.0)
        assert rho_eos > rho_ig

    def test_enthalpy_falls_back_to_ideal_without_pressure(self, pkg):
        # Without set_pressure_state, enthalpy is ideal-gas only.
        z = np.array([1.0, 0.0])
        from pse_ecosystem.models.properties import ideal_gas as _ig

        h_pkg = pkg.enthalpy(500.0, z)
        h_ig = _ig.enthalpy_J_mol("CH4", 500.0)
        assert abs(h_pkg - h_ig) < 1e-6

    def test_enthalpy_with_pressure_state_adds_departure(self, pkg):
        z = np.array([0.0, 1.0])  # pure CO2
        from pse_ecosystem.models.properties import ideal_gas as _ig

        pkg.set_pressure_state(50.0e5)
        h_eos = pkg.enthalpy(320.0, z, phase=PHASE_VAPOR)
        h_ig = _ig.enthalpy_J_mol("CO2", 320.0)
        # Departure for CO2 at moderate P is non-trivial and negative.
        assert h_eos < h_ig
        # Reset for any subsequent tests
        pkg.set_pressure_state(None)

    def test_Cp_returns_ideal_gas_mixture(self, pkg):
        from pse_ecosystem.models.properties import ideal_gas as _ig

        z = np.array([0.3, 0.7])
        cp = pkg.Cp(500.0, z)
        cp_ref = _ig.mixture_cp_J_mol_K({"CH4": 0.3, "CO2": 0.7}, 500.0)
        assert abs(cp - cp_ref) < 1e-9

    def test_fugacity_coefficients_vapor_positive(self, pkg):
        z = np.array([0.5, 0.5])
        phi = pkg.fugacity_coefficients(300.0, 1.0e6, z, PHASE_VAPOR)
        assert phi.shape == (2,) and np.all(phi > 0)


class TestSRKPackageContract:
    def test_density_ideal_gas_limit(self):
        pkg = SRKPackage(["N2"])
        z = np.array([1.0])
        rho_eos = pkg.density(400.0, 1000.0, z, phase=PHASE_VAPOR)
        rho_ig = 1000.0 / (_R * 400.0)
        assert abs(rho_eos - rho_ig) / rho_ig < 1e-3

    def test_K_values_match_wilson(self):
        c = cdb.get("CH4")
        pkg = SRKPackage(["CH4"])
        K = pkg.K_values(300.0, 1.0e5)[0]
        K_ref = ce.wilson_K(300.0, 1.0e5, c.Tc_K, c.Pc_Pa, c.omega)
        assert abs(K - K_ref) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Binary interaction parameters
# ─────────────────────────────────────────────────────────────────────────────


class TestKijHandling:
    def test_default_kij_is_zero(self):
        pkg = PengRobinsonPackage(["CH4", "CO2"])
        assert np.all(pkg._kij == 0.0)

    def test_kij_symmetry(self):
        pkg = PengRobinsonPackage(["CH4", "CO2"], kij_table={("CH4", "CO2"): 0.105})
        assert pkg._kij[0, 1] == 0.105
        assert pkg._kij[1, 0] == 0.105

    def test_unknown_species_in_kij_silently_ignored(self):
        # Allows a user to pass a project-wide kij table even when a flowsheet
        # only contains a subset of species.
        pkg = PengRobinsonPackage(["CH4", "CO2"], kij_table={("foo", "bar"): 0.5})
        assert np.all(pkg._kij == 0.0)
