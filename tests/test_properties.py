"""Phase 2 tests — properties module (ideal_gas.py, vle.py)."""

import math
import numpy as np
import pytest

from pse_ecosystem.models.properties.ideal_gas import (
    cp_J_mol_K,
    enthalpy_J_mol,
    mixture_cp_J_mol_K,
    mixture_enthalpy_J_mol,
    gamma,
    H_REF_298,
    MW,
)
from pse_ecosystem.models.properties.vle import (
    K_value,
    rachford_rice,
    bubble_T,
    dew_T,
)


# ── ideal_gas.py ──────────────────────────────────────────────────────────────


class TestCp:
    def test_CO2_at_1000K_nist(self):
        """NIST WebBook: Cp(CO2, 1000 K) ≈ 54.33 J/mol/K (within 1%)."""
        cp = cp_J_mol_K("CO2", 1000.0)
        assert abs(cp - 54.33) / 54.33 < 0.01

    def test_H2O_at_500K_nist(self):
        """NIST WebBook: Cp(H2O, 500 K) ≈ 35.23 J/mol/K (within 1%)."""
        cp = cp_J_mol_K("H2O", 500.0)
        assert abs(cp - 35.23) / 35.23 < 0.01

    def test_N2_at_298K(self):
        """At 298 K Cp(N2) ≈ 29.1 J/mol/K (within 2%)."""
        cp = cp_J_mol_K("N2", 298.15)
        assert abs(cp - 29.1) / 29.1 < 0.02

    def test_all_species_positive(self):
        from pse_ecosystem.models.properties.ideal_gas import SHOMATE
        for sp in SHOMATE:
            assert cp_J_mol_K(sp, 500.0) > 0


class TestEnthalpy:
    def test_formation_enthalpy_CO2(self):
        """H_REF_298['CO2'] should be ≈ -393510 J/mol."""
        assert abs(H_REF_298["CO2"] - (-393510.0)) < 100.0  # within 100 J/mol

    def test_enthalpy_at_ref_temperature(self):
        """enthalpy_J_mol at T_ref = T_ref should equal H_f° (within 1 J)."""
        h = enthalpy_J_mol("H2", 298.15, T_ref_K=298.15)
        assert abs(h - H_REF_298["H2"]) < 1.0

    def test_enthalpy_increases_with_T(self):
        """Sensible heat is positive for T > T_ref."""
        h300 = enthalpy_J_mol("N2", 300.0)
        h1000 = enthalpy_J_mol("N2", 1000.0)
        assert h1000 > h300

    def test_h2o_combustion_enthalpy(self):
        """H2 + 0.5 O2 → H2O: ΔH_rxn at 298 K ≈ −241826 J/mol (within 500 J)."""
        dH = (
            enthalpy_J_mol("H2O", 298.15)
            - enthalpy_J_mol("H2", 298.15)
            - 0.5 * enthalpy_J_mol("O2", 298.15)
        )
        assert abs(dH - (-241826.0)) < 500.0


class TestMixture:
    def test_mixture_cp_pure_limit(self):
        """Mixture Cp with one species should equal pure Cp."""
        comp = {"CO2": 1.0}
        assert abs(mixture_cp_J_mol_K(comp, 800.0) - cp_J_mol_K("CO2", 800.0)) < 1e-6

    def test_mixture_cp_molar_flow_basis(self):
        """Molar flow basis: result = weighted average."""
        comp = {"H2": 1.0, "N2": 3.0}  # 25% H2, 75% N2
        cp_mix = mixture_cp_J_mol_K(comp, 500.0, basis="molar_flow")
        expected = 0.25 * cp_J_mol_K("H2", 500.0) + 0.75 * cp_J_mol_K("N2", 500.0)
        assert abs(cp_mix - expected) < 1e-6

    def test_gamma_reasonable(self):
        """γ for diatomics at 300 K should be between 1.3 and 1.45."""
        for sp in ["N2", "O2", "H2"]:
            g = gamma(sp, 300.0)
            assert 1.3 < g < 1.45, f"γ({sp}) = {g} out of expected range"


# ── vle.py ───────────────────────────────────────────────────────────────────


class TestKValue:
    def test_benzene_at_normal_bp(self):
        """At T_b = 353.15 K and 101325 Pa, K(benzene) ≈ 1.0 (within 3%)."""
        K = K_value("benzene", 353.15, 101325.0)
        assert abs(K - 1.0) < 0.03

    def test_water_at_100C_atm(self):
        """At 373.15 K and 101325 Pa, K(water) ≈ 1.0 (within 3%)."""
        K = K_value("water", 373.15, 101325.0)
        assert abs(K - 1.0) < 0.03

    def test_K_increases_with_T(self):
        """K-value should increase with temperature (more volatile at higher T)."""
        K1 = K_value("toluene", 380.0, 101325.0)
        K2 = K_value("toluene", 420.0, 101325.0)
        assert K2 > K1

    def test_K_decreases_with_P(self):
        """K-value should decrease with pressure."""
        K1 = K_value("benzene", 353.0, 50000.0)
        K2 = K_value("benzene", 353.0, 200000.0)
        assert K1 > K2


class TestRachfordRice:
    def test_equimolar_binary(self):
        """Binary, z=[0.5, 0.5], K=[2, 0.5]: analytical V=0.5."""
        z = np.array([0.5, 0.5])
        K = np.array([2.0, 0.5])
        V = rachford_rice(z, K)
        assert abs(V - 0.5) < 1e-8

    def test_mass_balance_closure(self):
        """y = x·K, z = V·y + (1-V)·x → z recovered exactly."""
        z = np.array([0.3, 0.4, 0.3])
        K = np.array([3.0, 1.5, 0.2])
        V = rachford_rice(z, K)
        assert not math.isnan(V)
        x = z / (1.0 + V * (K - 1.0))
        y = K * x
        z_check = V * y + (1.0 - V) * x
        np.testing.assert_allclose(z_check, z, atol=1e-10)

    def test_single_phase_returns_nan(self):
        """All K > 1 (all vapour): Rachford-Rice has no root in (0,1)."""
        z = np.array([0.5, 0.5])
        K = np.array([5.0, 3.0])  # both > 1
        V = rachford_rice(z, K)
        assert math.isnan(V)

    def test_V_in_open_interval(self):
        """Valid two-phase result must be strictly inside (0, 1)."""
        z = np.array([0.4, 0.3, 0.3])
        K = np.array([4.0, 1.2, 0.3])
        V = rachford_rice(z, K)
        assert not math.isnan(V)
        assert 0.0 < V < 1.0


class TestBubbleDewT:
    def test_bubble_T_benzene_toluene(self):
        """Benzene/toluene at 1 atm: bubble T roughly 360–380 K."""
        z = np.array([0.5, 0.5])
        T_b = bubble_T(z, 101325.0, ["benzene", "toluene"], T_guess=370.0)
        assert not math.isnan(T_b), "bubble_T failed to converge"
        assert 355.0 < T_b < 390.0

    def test_bubble_T_pure_matches_K_unity(self):
        """For pure benzene, bubble T must give K(benzene) ≈ 1."""
        z = np.array([1.0])
        T_b = bubble_T(z, 101325.0, ["benzene"], T_guess=360.0)
        assert not math.isnan(T_b)
        assert abs(K_value("benzene", T_b, 101325.0) - 1.0) < 0.01

    def test_dew_T_above_bubble_T(self):
        """For a two-component mixture, dew T > bubble T at same P."""
        z = np.array([0.5, 0.5])
        T_b = bubble_T(z, 101325.0, ["benzene", "toluene"], T_guess=370.0)
        T_d = dew_T(z, 101325.0, ["benzene", "toluene"], T_guess=380.0)
        assert not math.isnan(T_b) and not math.isnan(T_d)
        assert T_d >= T_b
