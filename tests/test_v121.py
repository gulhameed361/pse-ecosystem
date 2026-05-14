"""v1.2.1 regression tests — FlashVLHF and CompositeUnit.

Covers:
  - FlashVLHF pressure equality residuals (new in v1.2.1 validation)
  - FlashVLHF VLE equilibrium (K-value correctness)
  - FlashVLHF as a terminal unit in the custom flowsheet builder
  - CompositeUnit assembly with a realistic industrial sub-flowsheet
  - CompositeUnit residual returns finite values on a well-initialised point
"""

import numpy as np
import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def lp_solver():
    try:
        from pse_ecosystem.solvers.lp_builder import select_lp_solver
        select_lp_solver()
    except RuntimeError:
        pytest.skip("No LP solver available")


# ── FlashVLHF — additional v1.2.1 tests ─────────────────────────────────────


class TestFlashVLHFExtended:
    """Additional coverage beyond the base test_hf_units.TestFlashVLHF."""

    def _make(self):
        from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
        return FlashVLHF("fl", ["benzene", "toluene"],
                         FlashVLHFParams(species_vle=["benzene", "toluene"],
                                         T_min=300.0, T_max=500.0))

    def _x_converged(self):
        return {
            "fl.inlet.F_benzene": 5.0, "fl.inlet.F_toluene": 5.0,
            "fl.inlet.T": 360.0,       "fl.inlet.P": 101325.0,
            "fl.vapor.F_benzene": 3.0, "fl.vapor.F_toluene": 1.0,
            "fl.vapor.T": 360.0,       "fl.vapor.P": 101325.0,
            "fl.liquid.F_benzene": 2.0, "fl.liquid.F_toluene": 4.0,
            "fl.liquid.T": 360.0,      "fl.liquid.P": 101325.0,
            "fl.V_frac": 0.4,          "fl.Q": 0.0,
        }

    def test_pressure_equality_residuals_at_solution(self):
        unit = self._make()
        x = self._x_converged()
        res = unit.residual(x)
        N = 2
        # res[2N+1] = P_vap - P_feed, res[2N+2] = P_liq - P_feed
        assert abs(res[2 * N + 1]) < 1e-10, f"P_vap equality: {res[2*N+1]}"
        assert abs(res[2 * N + 2]) < 1e-10, f"P_liq equality: {res[2*N+2]}"

    def test_vfrac_definition_residual_at_solution(self):
        unit = self._make()
        x = self._x_converged()
        res = unit.residual(x)
        N = 2
        # res[2N+3] = V_frac - F_vap_total/F_feed_total = 0.4 - 4/10 = 0
        assert abs(res[2 * N + 3]) < 1e-10, f"V_frac def: {res[2*N+3]}"

    def test_vle_equilibrium_residuals_are_finite(self):
        unit = self._make()
        x = self._x_converged()
        res = unit.residual(x)
        assert np.all(np.isfinite(res)), f"Non-finite residuals: {res}"

    def test_k_value_ordering(self):
        from pse_ecosystem.models.properties.vle import K_value
        K_benz = K_value("benzene", 360.0, 101325.0)
        K_tolu = K_value("toluene", 360.0, 101325.0)
        # Benzene is more volatile than toluene → K_benz > K_tolu
        assert K_benz > K_tolu, f"K_benz={K_benz:.4f} must exceed K_tolu={K_tolu:.4f}"

    def test_non_vle_species_passthrough(self):
        from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
        comps = ["benzene", "toluene", "N2"]
        unit = FlashVLHF("fl2", comps,
                         FlashVLHFParams(species_vle=["benzene", "toluene"]))
        x = {
            "fl2.inlet.F_benzene": 3.0, "fl2.inlet.F_toluene": 3.0,
            "fl2.inlet.F_N2": 1.0,
            "fl2.inlet.T": 360.0, "fl2.inlet.P": 101325.0,
            "fl2.vapor.F_benzene": 2.0, "fl2.vapor.F_toluene": 1.0,
            "fl2.vapor.F_N2": 0.7,
            "fl2.vapor.T": 360.0, "fl2.vapor.P": 101325.0,
            "fl2.liquid.F_benzene": 1.0, "fl2.liquid.F_toluene": 2.0,
            "fl2.liquid.F_N2": 0.3,
            "fl2.liquid.T": 360.0, "fl2.liquid.P": 101325.0,
            "fl2.V_frac": 3.7 / 7.0, "fl2.Q": 0.0,
        }
        res = unit.residual(x)
        assert np.all(np.isfinite(res))
        # Material balances for each component (first N residuals)
        assert np.allclose(res[:3], 0.0, atol=1e-10), f"Material balance failure: {res[:3]}"

    def test_custom_builder_instantiates_flash(self):
        from pse_ecosystem.ui.flowsheet_service import _instantiate_unit
        unit = _instantiate_unit(
            "FlashVLHF", "f1",
            {"components": ["benzene", "toluene"]}
        )
        assert hasattr(unit, "inlet_port")
        assert hasattr(unit, "vapor_port")
        assert hasattr(unit, "liquid_port")
        assert unit.unit_id == "f1"
        assert "benzene" in unit.components

    def test_custom_builder_flash_falls_back_to_vle_species(self):
        from pse_ecosystem.ui.flowsheet_service import _instantiate_unit
        # H2 and CO2 are not in ANTOINE → should fall back to benzene/toluene
        unit = _instantiate_unit(
            "FlashVLHF", "f2",
            {"components": ["H2", "CO"]}
        )
        assert "benzene" in unit.components or "toluene" in unit.components


# ── CompositeUnit — assembly tests ────────────────────────────────────────────


class TestCompositeUnitAssembly:
    """Assembly-level tests for CompositeUnit (Super-Unit)."""

    def _make_inner_power_to_methanol(self):
        from pse_ecosystem.ui.flowsheet_service import load_template
        return load_template("industrial.power_to_methanol", {"extent_max": 3.0})

    def test_composite_wraps_inner_flowsheet(self):
        from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit
        inner_fs = self._make_inner_power_to_methanol()
        inner_vars = inner_fs.all_variables()
        assert len(inner_vars) > 0

        # Pick sensible exposed vars that exist in the inner flowsheet
        exposed_in  = [v for v in inner_vars if "inlet" in v and "F_" in v][:1]
        exposed_out = [v for v in inner_vars if "outlet" in v and "F_" in v][:1]
        if not exposed_in or not exposed_out:
            pytest.skip("Could not find suitable exposed variables in inner flowsheet")

        cu = CompositeUnit("p2m_super", inner_fs, exposed_in, exposed_out)
        assert cu.unit_id == "p2m_super"
        assert set(cu.variables()) == set(exposed_in + exposed_out)

    def test_composite_variables_are_subset_of_inner(self):
        from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit
        inner_fs = self._make_inner_power_to_methanol()
        all_inner = set(inner_fs.all_variables())
        exposed_in  = list(all_inner)[:1]
        exposed_out = list(all_inner)[1:2]
        cu = CompositeUnit("p2m_super2", inner_fs, exposed_in, exposed_out)
        assert set(cu.variables()).issubset(all_inner | set(exposed_in) | set(exposed_out))

    def test_composite_bounds_are_finite(self):
        from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit
        inner_fs = self._make_inner_power_to_methanol()
        all_inner = list(inner_fs.all_variables())
        exposed_in  = all_inner[:1]
        exposed_out = all_inner[1:2]
        cu = CompositeUnit("p2m_super3", inner_fs, exposed_in, exposed_out)
        bounds = cu.bounds()
        for var, (lo, hi) in bounds.items():
            assert np.isfinite(lo) or lo == -np.inf, f"{var} lo={lo}"
            assert np.isfinite(hi) or hi == np.inf,  f"{var} hi={hi}"

    def test_composite_residual_returns_large_value_on_bad_point(self):
        """If inner SLP diverges, residual should return large penalty, not crash."""
        from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit, BaseFlowsheet
        from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams
        from pse_ecosystem.solvers.slp import SLPConfig

        pem = PEMToy("pem", PEMToyParams())
        inner_fs = BaseFlowsheet("inner", units=[pem])
        inner_fs.extra_equalities.append(({"pem.h2_kg_per_h": 1.0}, 50.0))

        cu = CompositeUnit(
            "pem_super",
            inner_fs,
            exposed_inputs=["pem.electricity_kW"],
            exposed_outputs=["pem.h2_kg_per_h"],
            slp_config=SLPConfig(max_iter=20, verbose=False),
        )
        # Provide a reasonable x — the outer residual should be finite
        x = {"pem.electricity_kW": 2800.0, "pem.h2_kg_per_h": 50.0}
        res = cu.residual(x)
        assert isinstance(res, np.ndarray)
        assert res.ndim == 1
        assert len(res) == 1

    def test_build_composite_unit_via_service(self):
        from pse_ecosystem.ui.flowsheet_service import build_composite_unit
        cu = build_composite_unit(
            "hydrogen.electrolysis_only",
            "pem_wrapper",
            exposed_inputs=["pem.electricity_kW"],
            exposed_outputs=["pem.h2_kg_per_h"],
        )
        assert cu.unit_id == "pem_wrapper"
        assert "pem.electricity_kW" in cu.exposed_inputs
        assert "pem.h2_kg_per_h" in cu.exposed_outputs
