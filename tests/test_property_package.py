"""Tests for the v1.6 property-package framework.

Covers:
* Factory / registry — defaults, case-insensitivity, reserved-key stubs.
* IdealGasPackage wrappers match the underlying ``ideal_gas`` / ``vle``
  functions byte-for-byte (zero-regression guarantee).
* Abstract-method enforcement on :class:`PropertyPackage`.
* Composition normalisation: unnormalised flows in, mole fractions out.
* Default :meth:`bubble_T` / :meth:`dew_T` solvers match :mod:`vle`.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pse_ecosystem.models.properties import (
    IdealGasPackage,
    PHASE_LIQUID,
    PHASE_VAPOR,
    PropertyPackage,
    available_methods,
    get_property_package,
    register_package,
)
from pse_ecosystem.models.properties import ideal_gas as _ig
from pse_ecosystem.models.properties import vle as _vle


# ─────────────────────────────────────────────────────────────────────────────
# Factory / registry
# ─────────────────────────────────────────────────────────────────────────────


class TestFactory:
    def test_default_method_is_ideal_gas(self):
        pkg = get_property_package(None, ["H2", "N2"])
        assert isinstance(pkg, IdealGasPackage)
        assert pkg.method_name == "ideal_gas"

    def test_empty_string_defaults_to_ideal_gas(self):
        pkg = get_property_package("", ["H2", "N2"])
        assert isinstance(pkg, IdealGasPackage)

    def test_case_insensitive(self):
        for key in ("ideal_gas", "Ideal_Gas", "IDEAL_GAS", "  ideal_gas  "):
            pkg = get_property_package(key, ["H2"])
            assert isinstance(pkg, IdealGasPackage)

    def test_unknown_method_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown property method"):
            get_property_package("not_a_real_method", ["H2"])

    @pytest.mark.parametrize("method", ["pr_nrtl"])
    def test_reserved_methods_raise_not_implemented(self, method):
        with pytest.raises(NotImplementedError, match="reserved for v1.6"):
            get_property_package(method, ["H2", "CH4"])

    def test_available_methods_contains_concrete_and_reserved(self):
        methods = available_methods()
        # Concrete in C.2 + C.3 + C.4
        for concrete in (
            "ideal_gas", "peng_robinson", "srk", "nrtl", "wilson", "uniquac"
        ):
            assert concrete in methods
        # Reserved stub for the hybrid PR-NRTL method (future release).
        assert "pr_nrtl" in methods

    def test_register_custom_package(self):
        class DummyPkg(IdealGasPackage):
            method_name = "dummy_test"

        register_package("dummy_test", DummyPkg)
        try:
            pkg = get_property_package("dummy_test", ["H2"])
            assert isinstance(pkg, DummyPkg)
        finally:
            # Clean up so other tests don't see this method.
            from pse_ecosystem.models.properties import property_package as pp

            pp._REGISTRY.pop("dummy_test", None)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────────────


class TestAbstractBase:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            PropertyPackage(["H2"])

    def test_empty_species_raises(self):
        with pytest.raises(ValueError, match="at least one species"):
            IdealGasPackage([])


# ─────────────────────────────────────────────────────────────────────────────
# IdealGasPackage — initialisation
# ─────────────────────────────────────────────────────────────────────────────


class TestIdealGasInit:
    def test_species_index_maps(self):
        pkg = IdealGasPackage(["H2", "N2", "CH4"])
        assert pkg.species == ["H2", "N2", "CH4"]
        assert pkg._index == {"H2": 0, "N2": 1, "CH4": 2}

    def test_eos_only_species_raises(self):
        # Argon has Tc/Pc/ω for cubic EOS but no Shomate and no Antoine, so
        # IdealGasPackage has no way to compute anything for it and must
        # refuse it at construction time.
        with pytest.raises(ValueError, match="Shomate or Antoine"):
            IdealGasPackage(["Ar"])

    def test_repr_includes_method_and_species(self):
        pkg = IdealGasPackage(["H2", "N2"])
        r = repr(pkg)
        assert "ideal_gas" in r and "H2" in r and "N2" in r


# ─────────────────────────────────────────────────────────────────────────────
# IdealGasPackage — K_values
# ─────────────────────────────────────────────────────────────────────────────


class TestIdealGasKValues:
    def test_matches_underlying_K_value(self):
        pkg = IdealGasPackage(["benzene", "toluene"])
        Ks = pkg.K_values(370.0, 101325.0)
        assert Ks[0] == _vle.K_value("benzene", 370.0, 101325.0)
        assert Ks[1] == _vle.K_value("toluene", 370.0, 101325.0)

    def test_length_matches_species(self):
        pkg = IdealGasPackage(["H2", "N2", "CH4", "H2O"])
        Ks = pkg.K_values(400.0, 101325.0)
        assert Ks.shape == (4,)

    def test_non_condensable_K_is_large(self):
        # H2 has no Antoine entry in the v1.5.3 dict (we wired CO2/H2/methane
        # in the registry though — verify via membership)
        pkg = IdealGasPackage(["benzene", "N2"])
        Ks = pkg.K_values(370.0, 101325.0)
        # N2 has no Antoine entry → should be the 1e6 sentinel
        if "N2" not in _vle.ANTOINE:
            assert Ks[1] == 1.0e6

    def test_K_decreases_with_pressure(self):
        pkg = IdealGasPackage(["benzene"])
        K_low = pkg.K_values(370.0, 50_000.0)
        K_high = pkg.K_values(370.0, 200_000.0)
        assert K_low[0] > K_high[0]


# ─────────────────────────────────────────────────────────────────────────────
# IdealGasPackage — enthalpy / Cp / density
# ─────────────────────────────────────────────────────────────────────────────


class TestIdealGasEnthalpy:
    def test_matches_mixture_enthalpy(self):
        pkg = IdealGasPackage(["H2", "N2"])
        z = np.array([0.25, 0.75])
        h_pkg = pkg.enthalpy(500.0, z)
        h_ref = _ig.mixture_enthalpy_J_mol({"H2": 0.25, "N2": 0.75}, 500.0)
        assert abs(h_pkg - h_ref) < 1e-9

    def test_combustion_water_298(self):
        """H2 + ½ O2 → H2O at 298 K: ΔH ≈ −241826 J/mol (within 500 J)."""
        pkg = IdealGasPackage(["H2O", "H2", "O2"])
        z_h2o = np.array([1.0, 0.0, 0.0])
        z_h2 = np.array([0.0, 1.0, 0.0])
        z_o2 = np.array([0.0, 0.0, 1.0])
        h_h2o = pkg.enthalpy(298.15, z_h2o)
        h_h2 = pkg.enthalpy(298.15, z_h2)
        h_o2 = pkg.enthalpy(298.15, z_o2)
        dH = h_h2o - h_h2 - 0.5 * h_o2
        assert abs(dH - (-241826.0)) < 500.0

    def test_enthalpy_increases_with_temperature(self):
        pkg = IdealGasPackage(["N2"])
        z = np.array([1.0])
        assert pkg.enthalpy(1000.0, z) > pkg.enthalpy(300.0, z)


class TestIdealGasCp:
    def test_matches_mixture_cp(self):
        pkg = IdealGasPackage(["H2", "N2"])
        z = np.array([0.25, 0.75])
        cp_pkg = pkg.Cp(500.0, z)
        cp_ref = _ig.mixture_cp_J_mol_K({"H2": 0.25, "N2": 0.75}, 500.0)
        assert abs(cp_pkg - cp_ref) < 1e-9

    def test_pure_component_cp(self):
        pkg = IdealGasPackage(["CO2"])
        z = np.array([1.0])
        assert abs(pkg.Cp(1000.0, z) - _ig.cp_J_mol_K("CO2", 1000.0)) < 1e-9


class TestIdealGasDensity:
    def test_ideal_gas_law(self):
        pkg = IdealGasPackage(["N2"])
        z = np.array([1.0])
        rho = pkg.density(300.0, 101325.0, z, phase=PHASE_VAPOR)
        expected = 101325.0 / (8.314462 * 300.0)
        assert abs(rho - expected) / expected < 1e-9

    def test_density_inversely_proportional_to_T(self):
        pkg = IdealGasPackage(["N2"])
        z = np.array([1.0])
        rho_lo = pkg.density(300.0, 101325.0, z)
        rho_hi = pkg.density(600.0, 101325.0, z)
        assert abs(rho_lo / rho_hi - 2.0) < 1e-9

    def test_liquid_phase_raises(self):
        pkg = IdealGasPackage(["H2O"])
        z = np.array([1.0])
        with pytest.raises(NotImplementedError, match="liquid"):
            pkg.density(300.0, 101325.0, z, phase=PHASE_LIQUID)


# ─────────────────────────────────────────────────────────────────────────────
# Composition normalisation
# ─────────────────────────────────────────────────────────────────────────────


class TestCompositionNormalisation:
    def test_unnormalised_flows_match_mole_fractions(self):
        pkg = IdealGasPackage(["H2", "N2"])
        z_frac = np.array([0.25, 0.75])
        z_flow = np.array([1.0, 3.0])  # same composition, scaled ×4
        assert abs(pkg.Cp(500.0, z_frac) - pkg.Cp(500.0, z_flow)) < 1e-9
        assert abs(pkg.enthalpy(500.0, z_frac) - pkg.enthalpy(500.0, z_flow)) < 1e-9

    def test_zero_flow_returns_zero(self):
        pkg = IdealGasPackage(["H2", "N2"])
        z = np.array([0.0, 0.0])
        assert pkg.Cp(500.0, z) == 0.0
        assert pkg.enthalpy(500.0, z) == 0.0

    def test_wrong_shape_raises(self):
        pkg = IdealGasPackage(["H2", "N2"])
        with pytest.raises(ValueError, match="shape"):
            pkg.Cp(500.0, np.array([0.5, 0.3, 0.2]))

    def test_molecular_weights(self):
        pkg = IdealGasPackage(["H2", "N2", "CO2"])
        mw = pkg.molecular_weights()
        assert mw[0] == _ig.MW["H2"]
        assert mw[1] == _ig.MW["N2"]
        assert mw[2] == _ig.MW["CO2"]


# ─────────────────────────────────────────────────────────────────────────────
# bubble_T / dew_T defaults
# ─────────────────────────────────────────────────────────────────────────────


class TestVLEDefaults:
    def test_bubble_T_matches_vle(self):
        pkg = IdealGasPackage(["benzene", "toluene"])
        z = np.array([0.5, 0.5])
        T_pkg = pkg.bubble_T(101325.0, z, T_guess=370.0)
        T_ref = _vle.bubble_T(z, 101325.0, ["benzene", "toluene"], T_guess=370.0)
        assert not math.isnan(T_pkg) and not math.isnan(T_ref)
        assert abs(T_pkg - T_ref) < 1e-3

    def test_dew_T_matches_vle(self):
        pkg = IdealGasPackage(["benzene", "toluene"])
        y = np.array([0.5, 0.5])
        T_pkg = pkg.dew_T(101325.0, y, T_guess=380.0)
        T_ref = _vle.dew_T(y, 101325.0, ["benzene", "toluene"], T_guess=380.0)
        assert not math.isnan(T_pkg) and not math.isnan(T_ref)
        assert abs(T_pkg - T_ref) < 1e-3

    def test_dew_above_bubble(self):
        pkg = IdealGasPackage(["benzene", "toluene"])
        z = np.array([0.5, 0.5])
        T_b = pkg.bubble_T(101325.0, z, T_guess=370.0)
        T_d = pkg.dew_T(101325.0, z, T_guess=380.0)
        assert T_d >= T_b
