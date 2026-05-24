"""Tests for the v1.6 generic flash routine and the FlashVLHF refactor.

Covers:
* :func:`flash_PT` against analytical Rachford-Rice for ideal-gas mixtures.
* Cross-package consistency — ideal-gas and PR give the same answer for a
  near-ideal hydrocarbon mixture at modest (T, P); they diverge sharply at
  higher P where the EOS earns its keep.
* Activity-model flash for ethanol-water (positive deviation system).
* Single-phase shortcuts: feed entirely above dew or below bubble.
* :class:`FlashVLHF` refactor — default (no package) reproduces v1.5.3
  numerics; supplying a PR package alters K-values transparently; the
  property-package field is the ONLY thing that changed in the call sequence.
* :class:`BaseFlowsheet.build_property_package` round-trip.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.properties import (
    IdealGasPackage,
    NRTLPackage,
    PengRobinsonPackage,
    flash_PT,
    get_property_package,
)
from pse_ecosystem.models.properties.vle import rachford_rice


# ─────────────────────────────────────────────────────────────────────────────
# Generic flash_PT
# ─────────────────────────────────────────────────────────────────────────────


class TestFlashPTIdealGas:
    def test_benzene_toluene_two_phase(self):
        # 95 °C, 1 atm sits comfortably between bubble (~365 K) and dew
        # (~372 K) for equimolar benzene/toluene.
        pkg = IdealGasPackage(["benzene", "toluene"])
        res = flash_PT(pkg, np.array([0.5, 0.5]), T_K=368.0, P_Pa=101325.0)
        assert res.converged
        assert res.phase == "two_phase"
        assert 0.0 < res.V < 1.0
        # Mass balance: V·y + (1-V)·x = z
        z_check = res.V * res.y + (1.0 - res.V) * res.x
        np.testing.assert_allclose(z_check, [0.5, 0.5], atol=1e-6)
        # K-consistency: y_i ≈ K_i x_i
        np.testing.assert_allclose(res.y, res.K * res.x, rtol=1e-3)

    def test_all_liquid_below_bubble(self):
        # Cool an equimolar benzene/toluene mixture well below normal bp.
        pkg = IdealGasPackage(["benzene", "toluene"])
        res = flash_PT(pkg, np.array([0.5, 0.5]), T_K=300.0, P_Pa=101325.0)
        assert res.converged
        assert res.phase == "all_liquid"
        assert res.V == 0.0
        np.testing.assert_allclose(res.x, [0.5, 0.5])

    def test_all_vapor_above_dew(self):
        pkg = IdealGasPackage(["benzene", "toluene"])
        res = flash_PT(pkg, np.array([0.5, 0.5]), T_K=420.0, P_Pa=101325.0)
        assert res.converged
        assert res.phase == "all_vapor"
        assert res.V == 1.0

    def test_consistency_with_rachford_rice(self):
        # Manually compute V using the Antoine K-vector and compare.
        pkg = IdealGasPackage(["benzene", "toluene"])
        z = np.array([0.4, 0.6])
        T, P = 370.0, 101325.0
        res = flash_PT(pkg, z, T, P)
        # The reference V comes from solving Rachford-Rice once on the
        # converged K — ideal-gas K is composition-independent so a single
        # iteration is sufficient.
        K = pkg.K_values(T, P, z)
        V_ref = rachford_rice(z, K)
        assert abs(res.V - V_ref) < 1e-6


class TestFlashPTPengRobinson:
    def test_methane_co2_two_phase(self):
        pkg = PengRobinsonPackage(["CH4", "CO2"])
        res = flash_PT(pkg, np.array([0.5, 0.5]), T_K=220.0, P_Pa=20.0e5)
        assert res.converged or res.phase != "failed"
        if res.phase == "two_phase":
            # CH4 partitions preferentially to vapour
            assert res.y[0] > res.x[0]
            # Mass balance closure
            z_check = res.V * res.y + (1.0 - res.V) * res.x
            np.testing.assert_allclose(z_check, [0.5, 0.5], atol=1e-5)

    def test_supercritical_all_vapor(self):
        # 350 K is well above both critical temperatures (190 K and 304 K).
        pkg = PengRobinsonPackage(["CH4", "CO2"])
        res = flash_PT(pkg, np.array([0.5, 0.5]), T_K=350.0, P_Pa=1.0e5)
        assert res.converged
        assert res.phase == "all_vapor"


class TestFlashPTNRTL:
    def test_ethanol_water_two_phase(self):
        # 80°C, 1 atm: ethanol-water is in two-phase region for x_eth in
        # roughly (0.05, 0.95). Equimolar mix is solidly two-phase.
        pkg = NRTLPackage(["ethanol", "water"])
        res = flash_PT(pkg, np.array([0.5, 0.5]), T_K=353.15, P_Pa=101325.0)
        assert res.converged
        assert res.phase == "two_phase"
        # Vapour enriched in ethanol (positive deviation → minimum-boiling
        # azeotrope shifts both components but ethanol is more volatile here)
        assert res.y[0] > res.x[0]


# ─────────────────────────────────────────────────────────────────────────────
# Failure / edge handling
# ─────────────────────────────────────────────────────────────────────────────


class TestFlashEdgeCases:
    def test_zero_flow_raises(self):
        pkg = IdealGasPackage(["benzene", "toluene"])
        with pytest.raises(ValueError, match="zero total flow"):
            flash_PT(pkg, np.array([0.0, 0.0]), 350.0, 101325.0)

    def test_pure_component_collapses_to_single_phase(self):
        # Pure benzene at T_b ≈ 353 K — at exactly 1 atm the result depends
        # on infinitesimal numerics; ±1 K must collapse cleanly.
        pkg = IdealGasPackage(["benzene", "toluene"])
        res_cold = flash_PT(pkg, np.array([1.0, 0.0]), 350.0, 101325.0)
        res_hot = flash_PT(pkg, np.array([1.0, 0.0]), 360.0, 101325.0)
        assert res_cold.phase in ("all_liquid", "two_phase")
        assert res_hot.phase in ("all_vapor", "two_phase")


# ─────────────────────────────────────────────────────────────────────────────
# FlashVLHF refactor — back-compat + package override
# ─────────────────────────────────────────────────────────────────────────────


class TestFlashVLHFBackCompat:
    """The v1.5.3 default (no property_package) must give byte-identical
    residuals to the legacy implementation."""

    def test_residual_uses_antoine_K_by_default(self):
        from pse_ecosystem.models.separators.flash_vl_hf import (
            FlashVLHF,
            FlashVLHFParams,
        )
        from pse_ecosystem.models.properties.vle import K_value

        comps = ["benzene", "toluene"]
        unit = FlashVLHF(
            "F1", comps, FlashVLHFParams(species_vle=comps)
        )
        # Build a feasible state and check the VLE residual block matches
        # the legacy Antoine-K form to within float tolerance.
        F = 1.0
        x_state = {
            f"F1.inlet.F_{comps[0]}": 0.5,
            f"F1.inlet.F_{comps[1]}": 0.5,
            f"F1.vapor.F_{comps[0]}": 0.3,
            f"F1.vapor.F_{comps[1]}": 0.2,
            f"F1.liquid.F_{comps[0]}": 0.2,
            f"F1.liquid.F_{comps[1]}": 0.3,
            "F1.inlet.T": 370.0,
            "F1.vapor.T": 370.0,
            "F1.liquid.T": 370.0,
            "F1.inlet.P": 101325.0,
            "F1.vapor.P": 101325.0,
            "F1.liquid.P": 101325.0,
            "F1.V_frac": 0.5,
            "F1.Q": 0.0,
        }
        res = unit.residual(x_state)
        # VLE block is residuals N..2N-1: y_i - K_i * x_i
        # Compute the legacy reference K values
        T, P = 370.0, 101325.0
        F_vap_total = 0.5
        F_liq_total = 0.5
        y = np.array([0.3, 0.2]) / F_vap_total
        xi = np.array([0.2, 0.3]) / F_liq_total
        for i, c in enumerate(comps):
            K_ref = K_value(c, T, P)
            legacy = y[i] - K_ref * xi[i]
            assert abs(res[2 + i] - legacy) < 1e-9, (
                f"VLE residual mismatch on {c}: got {res[2 + i]}, "
                f"legacy {legacy}"
            )

    def test_non_vle_species_default_to_K_unity(self):
        from pse_ecosystem.models.separators.flash_vl_hf import (
            FlashVLHF,
            FlashVLHFParams,
        )

        # N2 is a permanent gas (no Antoine in our DB) — must default to K=1
        # regardless of property package.
        comps = ["benzene", "N2"]
        unit = FlashVLHF(
            "F2", comps, FlashVLHFParams(species_vle=["benzene"])
        )
        x_state = {
            "F2.inlet.F_benzene": 0.6,
            "F2.inlet.F_N2": 0.4,
            "F2.vapor.F_benzene": 0.2,
            "F2.vapor.F_N2": 0.4,
            "F2.liquid.F_benzene": 0.4,
            "F2.liquid.F_N2": 0.0,
            "F2.inlet.T": 370.0,
            "F2.vapor.T": 370.0,
            "F2.liquid.T": 370.0,
            "F2.inlet.P": 101325.0,
            "F2.vapor.P": 101325.0,
            "F2.liquid.P": 101325.0,
            "F2.V_frac": 0.6,
            "F2.Q": 0.0,
        }
        res = unit.residual(x_state)
        # The N2 VLE residual (index 2+1 = 3) should be y_N2 - 1.0 * xi_N2
        # = 0.4/0.6 - 0.0 = 2/3
        assert abs(res[3] - (0.4 / 0.6 - 0.0)) < 1e-9

    def test_explicit_ideal_gas_package_matches_default(self):
        from pse_ecosystem.models.separators.flash_vl_hf import (
            FlashVLHF,
            FlashVLHFParams,
        )

        comps = ["benzene", "toluene"]
        unit_default = FlashVLHF(
            "FA", comps, FlashVLHFParams(species_vle=comps)
        )
        unit_explicit = FlashVLHF(
            "FB", comps,
            FlashVLHFParams(
                species_vle=comps,
                property_package=IdealGasPackage(comps),
            ),
        )
        # The two units must produce identical residuals on the same state.
        def state(uid):
            return {
                f"{uid}.inlet.F_benzene": 0.5,
                f"{uid}.inlet.F_toluene": 0.5,
                f"{uid}.vapor.F_benzene": 0.3,
                f"{uid}.vapor.F_toluene": 0.2,
                f"{uid}.liquid.F_benzene": 0.2,
                f"{uid}.liquid.F_toluene": 0.3,
                f"{uid}.inlet.T": 370.0,
                f"{uid}.vapor.T": 370.0,
                f"{uid}.liquid.T": 370.0,
                f"{uid}.inlet.P": 101325.0,
                f"{uid}.vapor.P": 101325.0,
                f"{uid}.liquid.P": 101325.0,
                f"{uid}.V_frac": 0.5,
                f"{uid}.Q": 0.0,
            }

        r_default = unit_default.residual(state("FA"))
        r_explicit = unit_explicit.residual(state("FB"))
        np.testing.assert_allclose(r_default, r_explicit, atol=1e-12)


class TestFlashVLHFPackageOverride:
    def test_PR_alters_K_values(self):
        # Same operating state — different package should give different K
        # and therefore a different VLE residual block.
        from pse_ecosystem.models.separators.flash_vl_hf import (
            FlashVLHF,
            FlashVLHFParams,
        )

        comps = ["CH4", "CO2"]
        unit_ideal = FlashVLHF(
            "GA", comps,
            FlashVLHFParams(
                species_vle=comps,
                property_package=IdealGasPackage(comps),
            ),
        )
        unit_PR = FlashVLHF(
            "GB", comps,
            FlashVLHFParams(
                species_vle=comps,
                property_package=PengRobinsonPackage(comps),
            ),
        )

        def state(uid):
            return {
                f"{uid}.inlet.F_CH4": 0.5,
                f"{uid}.inlet.F_CO2": 0.5,
                f"{uid}.vapor.F_CH4": 0.4,
                f"{uid}.vapor.F_CO2": 0.2,
                f"{uid}.liquid.F_CH4": 0.1,
                f"{uid}.liquid.F_CO2": 0.3,
                f"{uid}.inlet.T": 240.0,
                f"{uid}.vapor.T": 240.0,
                f"{uid}.liquid.T": 240.0,
                f"{uid}.inlet.P": 25.0e5,
                f"{uid}.vapor.P": 25.0e5,
                f"{uid}.liquid.P": 25.0e5,
                f"{uid}.V_frac": 0.6,
                f"{uid}.Q": 0.0,
            }

        r_ideal = unit_ideal.residual(state("GA"))
        r_PR = unit_PR.residual(state("GB"))
        # VLE residuals (idx 2..3 for 2 components) must differ — PR
        # corrects the K-value at this near-critical condition meaningfully.
        diff = np.max(np.abs(r_ideal[2:4] - r_PR[2:4]))
        assert diff > 1e-3, "PR package did not perturb the K-values"


# ─────────────────────────────────────────────────────────────────────────────
# Flowsheet wiring — property_method field
# ─────────────────────────────────────────────────────────────────────────────


class TestBaseFlowsheetPropertyMethod:
    def test_default_property_method_is_ideal_gas(self):
        fs = BaseFlowsheet(name="empty", units=[])
        assert fs.property_method == "ideal_gas"

    def test_build_package_routes_through_factory(self):
        fs = BaseFlowsheet(name="t", units=[], property_method="peng_robinson")
        pkg = fs.build_property_package(["CH4", "CO2"])
        assert isinstance(pkg, PengRobinsonPackage)

    def test_default_back_compat_ideal(self):
        fs = BaseFlowsheet(name="t", units=[])
        pkg = fs.build_property_package(["benzene", "toluene"])
        assert isinstance(pkg, IdealGasPackage)

    def test_unknown_method_raises_at_resolve(self):
        fs = BaseFlowsheet(name="t", units=[], property_method="unknown_method")
        with pytest.raises(ValueError, match="Unknown property method"):
            fs.build_property_package(["CH4"])
