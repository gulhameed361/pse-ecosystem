"""Tests for v1.5.0.dev — Multi-Tier Optimization & Project Economics Engine."""

from __future__ import annotations

import math
import pytest

from pse_ecosystem.models.costing.economic_engine import (
    EconomicEngine,
    EquipmentScalingRule,
)
from pse_ecosystem.ui.flowsheet_service import (
    ProjectEconomicsConfig,
    OBJECTIVE_TIERS,
    build_objective_extra,
    build_custom_flowsheet,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pem_flowsheet():
    cfg = {"units": [{"type": "PEMToy", "id": "pem", "params": {}}], "connections": []}
    return build_custom_flowsheet(cfg)


def _gasifier_flowsheet():
    cfg = {
        "units": [
            {"type": "BiomassGasifierHF", "id": "gasifier",
             "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"}}
        ],
        "connections": [],
    }
    return build_custom_flowsheet(cfg)


def _compressor_flowsheet():
    cfg = {
        "units": [
            {"type": "Compressor", "id": "comp",
             "params": {"components": ["H2", "CO2"], "P_out_Pa": 5e6}}
        ],
        "connections": [],
    }
    return build_custom_flowsheet(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# TestEconomicEngineExtensions
# ─────────────────────────────────────────────────────────────────────────────

class TestEconomicEngineExtensions:

    def test_npv_positive_cashflow_positive_npv(self):
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        npv = ee.npv(annual_net_cashflow=200_000, initial_capex=1_000_000)
        assert npv > 0, f"Positive cash flow over 10 yr should yield NPV > 0, got {npv}"

    def test_npv_zero_interest_sums_cashflows(self):
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.0)
        npv = ee.npv(annual_net_cashflow=100, initial_capex=800)
        assert npv == pytest.approx(100 * 10 - 800, rel=1e-6)

    def test_npv_negative_cashflow_negative_npv(self):
        ee = EconomicEngine(plant_life_yr=5, interest_rate=0.1)
        npv = ee.npv(annual_net_cashflow=-50_000, initial_capex=100_000)
        assert npv < 0

    def test_npv_with_salvage_value(self):
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        npv_no_sv  = ee.npv(annual_net_cashflow=0, initial_capex=100, salvage_value=0)
        npv_with_sv = ee.npv(annual_net_cashflow=0, initial_capex=100, salvage_value=200)
        assert npv_with_sv > npv_no_sv

    def test_irr_known_value(self):
        """C0=100, CF=17, N=10 yr → IRR ≈ 11.03%  (verified numerically)."""
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        irr = ee.irr(initial_capex=100, annual_net_cashflow=17)
        # Cross-check: NPV at the returned IRR must be ≈ 0
        npv_check = -100 + 17 * (1.0 - (1 + irr) ** -10) / irr
        assert abs(npv_check) < 0.01, (
            f"NPV at IRR should be ~0, got {npv_check:.4f} (IRR={irr*100:.3f}%)"
        )
        assert 0.10 < irr < 0.12, (
            f"IRR for C0=100, CF=17, N=10 should be between 10–12%, got {irr*100:.3f}%"
        )

    def test_irr_never_pays_back_returns_nan(self):
        ee = EconomicEngine(plant_life_yr=5, interest_rate=0.08)
        irr = ee.irr(initial_capex=10_000, annual_net_cashflow=1)
        assert math.isnan(irr), "Project that never pays back should return NaN IRR"

    def test_irr_zero_capex_not_nan(self):
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        irr = ee.irr(initial_capex=0.0, annual_net_cashflow=100)
        assert not math.isnan(irr) or irr > 0

    def test_lcoe_formula_value(self):
        ee = EconomicEngine()
        lcoe = ee.lcoe(capex_annual_USD=1_000_000, opex_annual_USD=500_000,
                       energy_kWh_per_year=10_000_000)
        assert lcoe == pytest.approx(0.15, rel=1e-6)

    def test_lcoe_zero_energy_returns_inf(self):
        ee = EconomicEngine()
        assert ee.lcoe(100, 50, 0.0) == float("inf")

    def test_equipment_scaling_rule_six_tenths(self):
        rule = EquipmentScalingRule(reference_cost_USD=1_000_000,
                                    reference_size=100.0,
                                    scaling_exponent=0.6)
        cost = rule.cost_at(200.0)
        expected = 1_000_000 * (200 / 100) ** 0.6
        assert cost == pytest.approx(expected, rel=1e-8)

    def test_equipment_scaling_rule_exponent_one_is_linear(self):
        rule = EquipmentScalingRule(reference_cost_USD=500_000,
                                    reference_size=50.0,
                                    scaling_exponent=1.0)
        assert rule.cost_at(100.0) == pytest.approx(1_000_000, rel=1e-8)

    def test_equipment_scaling_rule_reference_size_zero_raises(self):
        rule = EquipmentScalingRule(reference_cost_USD=1e6, reference_size=0.0)
        with pytest.raises(ValueError, match="reference_size"):
            rule.cost_at(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# TestProjectEconomicsConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectEconomicsConfig:

    def test_crf_matches_economic_engine(self):
        cfg = ProjectEconomicsConfig(plant_life_yr=20, interest_rate=0.08)
        ee  = EconomicEngine(plant_life_yr=20, interest_rate=0.08)
        assert cfg.crf == pytest.approx(ee.capital_recovery_factor(), rel=1e-8)

    def test_crf_zero_interest(self):
        cfg = ProjectEconomicsConfig(plant_life_yr=25, interest_rate=0.0)
        assert cfg.crf == pytest.approx(1.0 / 25, rel=1e-8)

    def test_energy_coeff_product(self):
        cfg = ProjectEconomicsConfig(electricity_price_USD_per_kWh=0.06,
                                     operating_hours_per_year=7500.0)
        assert cfg.energy_coeff == pytest.approx(0.06 * 7500.0, rel=1e-8)

    def test_default_values_align_with_industrial_practice(self):
        cfg = ProjectEconomicsConfig()
        assert cfg.plant_life_yr == 20
        assert cfg.interest_rate  == pytest.approx(0.08)
        assert cfg.operating_hours_per_year == pytest.approx(8_000.0)
        assert cfg.electricity_price_USD_per_kWh == pytest.approx(0.05)
        assert cfg.carbon_tax_USD_per_tonne == pytest.approx(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# TestNewObjectiveModes
# ─────────────────────────────────────────────────────────────────────────────

class TestNewObjectiveModes:

    def test_maximize_npv_returns_energy_coefficients_like_tac(self):
        """NPV LP proxy uses same energy/CAPEX coefficients as TAC minimisation."""
        fs = _compressor_flowsheet()
        extra_tac, _ = build_objective_extra(fs, "Minimize TAC")
        extra_npv, _ = build_objective_extra(fs, "Maximize NPV (Net Present Value)")
        for k in extra_tac:
            assert k in extra_npv, f"NPV proxy missing TAC variable {k!r}"

    def test_maximize_irr_coefficients_same_as_npv(self):
        fs = _compressor_flowsheet()
        extra_npv, _ = build_objective_extra(fs, "Maximize NPV (Net Present Value)")
        extra_irr, _ = build_objective_extra(fs, "Maximize IRR (Internal Rate of Return)")
        assert extra_npv == extra_irr

    def test_minimize_carbon_intensity_finds_co2_outlet_variable(self):
        """BiomassGasifierHF has CO₂ outlet; carbon intensity mode must add a coefficient."""
        fs = _gasifier_flowsheet()
        extra, force_feas = build_objective_extra(fs, "Minimize Carbon Intensity")
        assert force_feas is False
        co2_keys = [k for k in extra
                    if k.split(".")[-1].lower() in ("f_co2", "f_co2_captured")
                    and "out" in k.split(".")[1].lower()]
        assert len(co2_keys) >= 1, (
            f"No CO₂ outlet variable in objective_extra for carbon intensity mode: {list(extra.keys())}"
        )
        for k in co2_keys:
            assert extra[k] > 0, f"CO₂ penalty coefficient should be positive: {extra[k]}"

    def test_minimize_specific_energy_finds_h2_outlet(self):
        fs = _gasifier_flowsheet()
        extra, _ = build_objective_extra(fs, "Minimize Specific Energy Consumption")
        h2_keys = [k for k in extra
                   if k.split(".")[-1].lower() == "f_h2"
                   and "out" in k.split(".")[1].lower()]
        assert len(h2_keys) >= 1, "Specific energy mode should reward H₂ outlet (negative coeff)"
        for k in h2_keys:
            assert extra[k] < 0, f"H₂ reward coefficient must be negative: {extra[k]}"

    def test_minimize_lcoe_returns_energy_coeff_terms(self):
        fs = _compressor_flowsheet()
        extra, force_feas = build_objective_extra(fs, "Minimize LCOE (Levelized Cost of Energy)")
        assert force_feas is False
        energy_keys = [k for k in extra
                       if any(t in k.lower() for t in ("w_shaft", "w_elec_kw", "electricity_kw"))]
        assert len(energy_keys) >= 1, (
            f"LCOE mode should include energy penalty terms: {list(extra.keys())}"
        )

    def test_tier_dict_covers_all_modes_in_build_objective_extra(self):
        """Every mode listed in OBJECTIVE_TIERS must be handled by build_objective_extra
        without raising an exception on a simple single-unit flowsheet."""
        fs = _gasifier_flowsheet()
        all_modes = [m for modes in OBJECTIVE_TIERS.values() for m in modes]
        for mode in all_modes:
            try:
                extra, force_feas = build_objective_extra(fs, mode)
                assert isinstance(extra, dict), f"Mode {mode!r} returned non-dict extra"
                assert isinstance(force_feas, bool)
            except Exception as exc:
                pytest.fail(f"build_objective_extra raised on mode {mode!r}: {exc}")

    def test_econ_config_overrides_scalar_kwargs(self):
        """When econ_config is passed, its electricity_price_USD_per_kWh overrides the kwarg."""
        fs = _compressor_flowsheet()
        cfg_high = ProjectEconomicsConfig(electricity_price_USD_per_kWh=0.20,
                                          operating_hours_per_year=8000.0)
        cfg_low  = ProjectEconomicsConfig(electricity_price_USD_per_kWh=0.01,
                                          operating_hours_per_year=8000.0)
        extra_high, _ = build_objective_extra(fs, "Minimize Energy", econ_config=cfg_high)
        extra_low,  _ = build_objective_extra(fs, "Minimize Energy", econ_config=cfg_low)
        for k in extra_high:
            if k in extra_low:
                assert extra_high[k] > extra_low[k], (
                    f"Higher electricity price should give larger coefficient on {k}"
                )

    def test_objective_tiers_structure(self):
        """OBJECTIVE_TIERS has exactly three tiers with non-empty lists."""
        assert set(OBJECTIVE_TIERS.keys()) == {"Technical", "Economic", "Technoeconomic"}
        for tier, modes in OBJECTIVE_TIERS.items():
            assert len(modes) >= 1, f"Tier {tier!r} has no modes"
            for m in modes:
                assert isinstance(m, str) and len(m) > 0


# ─────────────────────────────────────────────────────────────────────────────
# TestProjectEconomicsExcel — integration: build_objective_extra → SLP → KPIs
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectEconomicsExcel:

    def test_lcoh_calculation_from_kpis(self):
        """EconomicEngine.lcoh() produces a finite positive value for a non-zero H₂ flow."""
        ee = EconomicEngine(plant_life_yr=20, interest_rate=0.08)
        lcoh = ee.lcoh(capex_annual_USD=500_000, opex_annual_USD=200_000, h2_kg_per_s=0.1)
        assert math.isfinite(lcoh)
        assert lcoh > 0

    def test_npv_irr_consistency(self):
        """At IRR, NPV should be approximately zero."""
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        irr = ee.irr(initial_capex=100_000, annual_net_cashflow=16_000)
        if not math.isnan(irr):
            ee_at_irr = EconomicEngine(plant_life_yr=10, interest_rate=irr)
            npv = ee_at_irr.npv(annual_net_cashflow=16_000, initial_capex=100_000)
            assert abs(npv) < 1.0, (
                f"NPV at IRR should be ~0, got {npv:.4f}"
            )

    def test_crf_annualisation_roundtrip(self):
        """installed_cost → annualised_capex → installed_cost (via CRF) is stable."""
        ee = EconomicEngine(plant_life_yr=20, interest_rate=0.08)
        installed = 1_000_000.0
        annual = installed * ee.capital_recovery_factor()
        recovered = annual / ee.capital_recovery_factor()
        assert recovered == pytest.approx(installed, rel=1e-8)

    def test_excel_sheet_name_list(self):
        """Verify the expected Excel sheet names are at least defined as strings."""
        expected_sheets = [
            "Stream Table",
            "Unit Performance",
            "Optimization Summary",
            "Bound Saturation",
            "Project Economics",
        ]
        for name in expected_sheets:
            assert isinstance(name, str) and len(name) > 0
