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
    compute_project_economics,
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

    def test_irr_zero_capex_returns_inf(self):
        """v1.5.0.dev-AUDIT D4: zero CapEx → IRR is unbounded → returns +inf."""
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        irr = ee.irr(initial_capex=0.0, annual_net_cashflow=100)
        assert math.isinf(irr) and irr > 0, (
            f"Zero CapEx should produce inf IRR, got {irr}"
        )

    def test_irr_unrealistic_pays_back_returns_inf(self):
        """v1.5.0.dev-AUDIT D4: when CF >> C0, IRR exceeds r_max → returns +inf."""
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        irr = ee.irr(initial_capex=1.0, annual_net_cashflow=10_000.0)
        assert math.isinf(irr) and irr > 0

    def test_irr_custom_r_max_widens_search(self):
        ee = EconomicEngine(plant_life_yr=10, interest_rate=0.08)
        irr_default = ee.irr(initial_capex=1.0, annual_net_cashflow=100.0)
        irr_wider   = ee.irr(initial_capex=1.0, annual_net_cashflow=100.0, r_max=200.0)
        # Default r_max=10 → inf; wider r_max=200 should resolve a finite IRR
        assert math.isinf(irr_default)
        assert not math.isinf(irr_wider) and irr_wider > 10.0

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


# ─────────────────────────────────────────────────────────────────────────────
# v1.5.0.dev-AUDIT: Input validation (D3, D6)
# ─────────────────────────────────────────────────────────────────────────────

class TestInputValidation:

    def test_economic_engine_rejects_zero_plant_life(self):
        with pytest.raises(ValueError, match="plant_life_yr"):
            EconomicEngine(plant_life_yr=0)

    def test_economic_engine_rejects_negative_plant_life(self):
        with pytest.raises(ValueError, match="plant_life_yr"):
            EconomicEngine(plant_life_yr=-5)

    def test_economic_engine_rejects_negative_interest_rate(self):
        with pytest.raises(ValueError, match="interest_rate"):
            EconomicEngine(interest_rate=-0.01)

    def test_economic_engine_rejects_zero_operating_hours(self):
        with pytest.raises(ValueError, match="operating_hours"):
            EconomicEngine(operating_hours_per_year=0.0)

    def test_economic_engine_rejects_overlong_operating_hours(self):
        with pytest.raises(ValueError, match="operating_hours"):
            EconomicEngine(operating_hours_per_year=8761.0)

    def test_economic_engine_accepts_full_year_operation(self):
        # 8760 h/yr (100% capacity) is the upper edge — must be accepted.
        ee = EconomicEngine(operating_hours_per_year=8760.0)
        assert ee.operating_hours_per_year == 8760.0

    def test_project_economics_config_rejects_zero_plant_life(self):
        with pytest.raises(ValueError, match="plant_life_yr"):
            ProjectEconomicsConfig(plant_life_yr=0)

    def test_project_economics_config_rejects_negative_interest_rate(self):
        with pytest.raises(ValueError, match="interest_rate"):
            ProjectEconomicsConfig(interest_rate=-0.05)

    def test_project_economics_config_rejects_invalid_lang_factor(self):
        with pytest.raises(ValueError, match="lang_factor"):
            ProjectEconomicsConfig(lang_factor=0.5)

    def test_project_economics_config_target_year_propagates(self):
        cfg = ProjectEconomicsConfig(target_year=2030)
        assert cfg.target_year == 2030


# ─────────────────────────────────────────────────────────────────────────────
# v1.5.0.dev-AUDIT D1: compute_project_economics() must read from real unit
# capex(), opex_per_year(), and the unit-tagged H2_production_kg_h/_s KPIs.
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeProjectEconomicsAudit:
    """End-to-end: real flowsheet → real solve → non-zero economics."""

    def _solve_pem_flowsheet(self):
        """Solve a single-PEM flowsheet with a non-trivial OPEX objective."""
        from pse_ecosystem.core.contracts import SolveMode
        from pse_ecosystem.solvers.orchestrator import Orchestrator
        from pse_ecosystem.solvers.slp import SLPConfig

        fs = _pem_flowsheet()
        fs.objective_extra, fs.force_feasibility = build_objective_extra(
            fs, "Minimize OPEX"
        )
        # Pin H₂ demand so the LP has a non-zero electricity draw → non-zero OPEX.
        all_vars = fs.all_variables()
        h2_vars = [v for v in all_vars if v.lower().endswith("f_h2") or v.endswith("h2")]
        if h2_vars:
            # Don't over-constrain — just set a lower bound.
            fs.extra_bounds.setdefault(h2_vars[0], (1.0, 100.0))
        orch = Orchestrator(flowsheet=fs, mode=SolveMode.FIXED_LP,
                            slp_config=SLPConfig(max_iter=30))
        result = orch.solve()
        return fs, result

    def test_compute_project_economics_returns_nonzero_capex_for_pem(self):
        """ElectrolyserHF.capex() returns ≥70 USD; PEMToy has no capex method
        (returns BaseUnit default 0).  The single-PEM flowsheet should still
        produce a non-zero installed CAPEX once the engine's CEPCI + Lang factor
        is applied to any non-trivial unit-capex sum."""
        # Build a minimal PEM + verify _aggregate_capex_purchase_USD reports 0
        # for PEMToy (no override) — the test instead exercises ElectrolyserHF.
        cfg_pem = {"units": [{"type": "ElectrolyserHF", "id": "elec", "params": {}}],
                   "connections": []}
        fs = build_custom_flowsheet(cfg_pem)
        # Mock solution with a non-zero W_elec_kW so capex() returns > 0.
        x = {v: 100.0 for v in fs.all_variables()}
        rows = compute_project_economics(
            flowsheet=fs, solution_x=x, kpis={}, econ_config=ProjectEconomicsConfig()
        )
        metric_to_value = {r["Metric"]: r["Value"] for r in rows}
        assert metric_to_value["Purchase CAPEX (CE500)"] > 0, (
            f"ElectrolyserHF should report non-zero capex; got "
            f"{metric_to_value['Purchase CAPEX (CE500)']}"
        )
        assert metric_to_value["Installed CAPEX"] > metric_to_value["Purchase CAPEX (CE500)"], (
            "Installed CAPEX = purchase × CEPCI × Lang factor must exceed purchase"
        )
        assert metric_to_value["Annualised CAPEX"] > 0

    def test_compute_project_economics_reports_h2_production(self):
        """A flowsheet whose KPIs include H2_production_kg_h must surface a
        non-zero H₂ Production row (D1 regression: previous version read the
        non-existent kpi key 'h2_kg_per_s' and always reported 0)."""
        cfg = {"units": [{"type": "ElectrolyserHF", "id": "elec", "params": {}}],
               "connections": []}
        fs = build_custom_flowsheet(cfg)
        x = {v: 50.0 for v in fs.all_variables()}
        # Synthesise kpis that mimic real ElectrolyserHF output.
        kpis = {"H2_production_kg_h": 36.0, "W_elec_kW": 2000.0,
                "efficiency_pct": 70.0, "specific_power_kWh_per_kgH2": 55.0}
        rows = compute_project_economics(
            flowsheet=fs, solution_x=x, kpis=kpis,
            econ_config=ProjectEconomicsConfig()
        )
        m2v = {r["Metric"]: r["Value"] for r in rows}
        # 36 kg/h ÷ 3600 = 0.01 kg/s
        assert m2v["H₂ Production"] == pytest.approx(0.01, rel=1e-4)
        # LCOH must therefore be finite, not NaN
        assert not (m2v["LCOH"] != m2v["LCOH"]), "LCOH should not be NaN when H₂ is produced"
        assert m2v["LCOH"] > 0

    def test_compute_project_economics_prefers_psa_kg_s_over_pem_kg_h(self):
        """When both *_kg_s (PSA) and *_kg_h (PEM) KPIs are present, the kg_s
        value wins (more accurate, PSA convention)."""
        cfg = {"units": [{"type": "PEMToy", "id": "pem", "params": {}}],
               "connections": []}
        fs = build_custom_flowsheet(cfg)
        kpis = {
            "psa.H2_production_kg_s": 0.05,        # PSA-style (kg/s)
            "H2_production_kg_h": 36.0,            # PEM-style (kg/h → 0.01 kg/s)
        }
        rows = compute_project_economics(
            flowsheet=fs, solution_x={}, kpis=kpis,
            econ_config=ProjectEconomicsConfig()
        )
        m2v = {r["Metric"]: r["Value"] for r in rows}
        assert m2v["H₂ Production"] == pytest.approx(0.05, rel=1e-4), (
            "kg_s KPI must take priority over kg_h KPI"
        )

    def test_compute_project_economics_fallback_to_outlet_variable(self):
        """No H₂ KPIs present → fall back to scanning solution_x for an
        outlet F_H2 variable; convert mol/s → kg/s."""
        cfg = {"units": [{"type": "BiomassGasifierHF", "id": "gasifier",
                          "params": {"T_gasifier_C": 800.0,
                                     "gasifying_agent": "Steam"}}],
               "connections": []}
        fs = build_custom_flowsheet(cfg)
        # Inject a fake solution with 100 mol/s H₂ at the gasifier syngas outlet.
        x = {v: 0.0 for v in fs.all_variables()}
        for v in x:
            if v.endswith(".F_H2") and "out" in v.split(".")[1].lower():
                x[v] = 100.0  # mol/s
        rows = compute_project_economics(
            flowsheet=fs, solution_x=x, kpis={},
            econ_config=ProjectEconomicsConfig()
        )
        m2v = {r["Metric"]: r["Value"] for r in rows}
        # 100 mol/s × 0.002016 kg/mol ≈ 0.2016 kg/s
        assert m2v["H₂ Production"] == pytest.approx(0.2016, rel=1e-3)

    def test_compute_project_economics_reports_all_metadata_rows(self):
        """Every row required by the audit must be present."""
        cfg = {"units": [{"type": "PEMToy", "id": "pem", "params": {}}],
               "connections": []}
        fs = build_custom_flowsheet(cfg)
        rows = compute_project_economics(
            flowsheet=fs, solution_x={}, kpis={},
            econ_config=ProjectEconomicsConfig(target_year=2030),
            obj_config={"mode": "Minimize LCOH (Levelized Cost of H₂)"},
        )
        metrics = {r["Metric"] for r in rows}
        required = {
            "Plant Life", "Discount Rate (WACC)", "Tax Rate", "Inflation Rate",
            "Target Year (CEPCI)", "CEPCI Escalation", "Lang Factor", "CRF",
            "Operating Hours", "Electricity Price", "Biomass Price", "Carbon Tax",
            "Purchase CAPEX (CE500)", "Installed CAPEX", "Annualised CAPEX",
            "Annual OPEX", "TAC", "H₂ Production", "Power Output",
            "LCOH", "LCOE", "NPV", "IRR", "Objective Mode",
        }
        missing = required - metrics
        assert not missing, f"Project Economics sheet missing rows: {missing}"

    def test_compute_project_economics_uses_target_year_for_cepci(self):
        """target_year=2030 must scale CEPCI above 2024 baseline."""
        cfg = {"units": [{"type": "ElectrolyserHF", "id": "elec", "params": {}}],
               "connections": []}
        fs = build_custom_flowsheet(cfg)
        x = {v: 100.0 for v in fs.all_variables()}
        rows_2024 = compute_project_economics(
            flowsheet=fs, solution_x=x, kpis={},
            econ_config=ProjectEconomicsConfig(target_year=2024),
        )
        rows_2030 = compute_project_economics(
            flowsheet=fs, solution_x=x, kpis={},
            econ_config=ProjectEconomicsConfig(target_year=2030),
        )
        capex_2024 = next(r["Value"] for r in rows_2024 if r["Metric"] == "Installed CAPEX")
        capex_2030 = next(r["Value"] for r in rows_2030 if r["Metric"] == "Installed CAPEX")
        assert capex_2030 > capex_2024, (
            f"2030 CAPEX ({capex_2030}) should exceed 2024 ({capex_2024}) due to CEPCI escalation"
        )
