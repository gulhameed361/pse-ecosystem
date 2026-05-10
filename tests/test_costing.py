"""Phase 4 tests — SSLW costing module."""

import pytest
from pse_ecosystem.models.costing.sslw_costing import (
    hx_purchase_cost_USD,
    vessel_purchase_cost_USD,
    cstr_purchase_cost_USD,
    compressor_purchase_cost_USD,
    pump_purchase_cost_USD,
    turbine_purchase_cost_USD,
    annualized_capex,
)


class TestHXCost:
    def test_utube_100m2_reasonable(self):
        cost = hx_purchase_cost_USD(100.0, hx_type="Utube", material="SS")
        # Expect roughly $50k–$500k for 100 m² SS U-tube at CE500 basis
        assert 1e4 < cost < 1e7

    def test_material_ss_more_expensive_than_cs(self):
        cs = hx_purchase_cost_USD(50.0, material="CS")
        ss = hx_purchase_cost_USD(50.0, material="SS")
        assert ss > cs

    def test_larger_area_costs_more(self):
        c1 = hx_purchase_cost_USD(10.0)
        c2 = hx_purchase_cost_USD(100.0)
        assert c2 > c1

    def test_all_hx_types_positive(self):
        for hx_type in ("floating_head", "fixed_head", "Utube", "kettle_vap"):
            cost = hx_purchase_cost_USD(50.0, hx_type=hx_type)
            assert cost > 0, f"{hx_type} cost should be positive"


class TestVesselCost:
    def test_1m3_vessel_reasonable(self):
        cost = vessel_purchase_cost_USD(1.0)
        assert 1e3 < cost < 1e6

    def test_larger_vessel_costs_more(self):
        c1 = vessel_purchase_cost_USD(1.0)
        c2 = vessel_purchase_cost_USD(10.0)
        assert c2 > c1

    def test_ss_more_expensive(self):
        cs = vessel_purchase_cost_USD(5.0, material="CS")
        ss = vessel_purchase_cost_USD(5.0, material="SS")
        assert ss > cs

    def test_cstr_cost_alias(self):
        assert cstr_purchase_cost_USD(5.0) == vessel_purchase_cost_USD(5.0)


class TestCompressorCost:
    def test_100kW_compressor(self):
        cost = compressor_purchase_cost_USD(100_000.0)
        assert 1e4 < cost < 1e7

    def test_higher_power_costs_more(self):
        c1 = compressor_purchase_cost_USD(50_000.0)
        c2 = compressor_purchase_cost_USD(500_000.0)
        assert c2 > c1

    def test_different_types_all_positive(self):
        for comp_type in ("Centrifugal", "Reciprocating", "Screw"):
            cost = compressor_purchase_cost_USD(100_000.0, comp_type=comp_type)
            assert cost > 0


class TestPumpCost:
    def test_10kW_pump(self):
        cost = pump_purchase_cost_USD(10_000.0)
        assert cost > 0
        assert cost < 1e6


class TestTurbineCost:
    def test_1MW_turbine(self):
        cost = turbine_purchase_cost_USD(1_000_000.0)
        assert cost > 0


class TestAnnualizedCapex:
    def test_basic_escalation(self):
        c = annualized_capex(100_000.0, lang_factor=5.0, crf=0.10, cepci_now=800.0)
        # installed = 100k * 5 * (800/500) = 800k
        # annual = 800k * 0.10 = 80k
        assert abs(c - 80_000.0) < 1.0

    def test_higher_cepci_gives_higher_cost(self):
        c1 = annualized_capex(100_000.0, cepci_now=600.0)
        c2 = annualized_capex(100_000.0, cepci_now=900.0)
        assert c2 > c1

    def test_result_in_plausible_range(self):
        c = annualized_capex(100_000.0)
        assert 5_000.0 < c < 500_000.0


class TestLayerCompliance:
    def test_sslw_does_not_import_pyomo(self):
        """SSLW module must be Pyomo-free."""
        import importlib, sys
        # Ensure the module is loaded
        import pse_ecosystem.models.costing.sslw_costing
        # Check that pyomo is not in its dependencies
        module = sys.modules.get("pse_ecosystem.models.costing.sslw_costing")
        if module is not None:
            source_file = getattr(module, "__file__", "") or ""
            with open(source_file, "r", encoding="utf-8") as f:
                source = f.read()
            assert "import pyomo" not in source
            assert "from pyomo" not in source
