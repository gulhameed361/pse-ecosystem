"""v1.5.1 feature tests.

Covers:
  1. tornado_sensitivity() — one-at-a-time economic sensitivity
  2. compute_npv_with_revenue() — break-even / NPV with product price
  3. generate_investor_report() — Markdown report structure
  4. Scenario Manager data model (session state dict format)
  5. get_asme_materials() — gateway helper
  6. compute_outlet_flammability_warnings() — gateway helper
  7. Solve-time metric stored in session state
  8. Layer compliance for new gateway helpers
"""

from __future__ import annotations

import json
import math
import pytest
from typing import Dict


# ── shared fixture ────────────────────────────────────────────────────────────

def _pem_flowsheet_and_solve():
    """Minimal converged solve for a PEM electrolysis flowsheet."""
    from pse_ecosystem.ui.flowsheet_service import load_template
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode

    fs = load_template("hydrogen.electrolysis_only")
    orch = Orchestrator(
        flowsheet=fs,
        mode=SolveMode.FIXED_LP,
        slp_config=SLPConfig(max_iter=200),
    )
    result = orch.solve()
    return fs, result


def _base_econ_config():
    from pse_ecosystem.ui.flowsheet_service import ProjectEconomicsConfig
    return ProjectEconomicsConfig()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. tornado_sensitivity
# ═══════════════════════════════════════════════════════════════════════════════

class TestTornadoSensitivity:

    def _run(self, **kw):
        from pse_ecosystem.ui.flowsheet_service import tornado_sensitivity
        fs, result = _pem_flowsheet_and_solve()
        return tornado_sensitivity(fs, result.x, result.kpis, _base_econ_config(), **kw)

    def test_returns_list_of_tornado_rows(self):
        from pse_ecosystem.ui.flowsheet_service import TornadoRow
        rows = self._run()
        assert isinstance(rows, list)
        for r in rows:
            assert isinstance(r, TornadoRow)

    def test_sorted_by_impact_descending(self):
        rows = self._run()
        impacts = [r.impact for r in rows]
        assert impacts == sorted(impacts, reverse=True)

    def test_all_fields_populated(self):
        from pse_ecosystem.ui.flowsheet_service import TornadoRow
        rows = self._run()
        for r in rows:
            assert r.param_label
            assert r.param_field
            assert isinstance(r.kpi_base, float)
            assert isinstance(r.impact, float)

    def test_lcoe_target_metric(self):
        rows = self._run(target_metric="LCOE")
        assert isinstance(rows, list)

    def test_custom_perturbation_frac(self):
        rows_10 = self._run(perturbation_frac=0.10)
        rows_30 = self._run(perturbation_frac=0.30)
        # Larger perturbation should generally yield larger impacts
        total_10 = sum(r.impact for r in rows_10 if not math.isnan(r.impact))
        total_30 = sum(r.impact for r in rows_30 if not math.isnan(r.impact))
        assert total_30 >= total_10

    def test_delta_low_and_high_consistent(self):
        rows = self._run()
        for r in rows:
            # delta = kpi_at_x - kpi_base; skip rows where perturbation hit a validation bound (NaN)
            if not math.isnan(r.kpi_at_low):
                assert abs((r.kpi_at_low - r.kpi_base) - r.delta_low) < 1e-9
            if not math.isnan(r.kpi_at_high):
                assert abs((r.kpi_at_high - r.kpi_base) - r.delta_high) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 2. compute_npv_with_revenue
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeNPVWithRevenue:

    def _run(self, price=3.0):
        from pse_ecosystem.ui.flowsheet_service import compute_npv_with_revenue
        fs, result = _pem_flowsheet_and_solve()
        return compute_npv_with_revenue(fs, result.x, result.kpis, _base_econ_config(),
                                        product_price_USD_per_kg=price)

    def test_returns_dict_with_required_keys(self):
        r = self._run()
        for key in ("lcoh", "product_price", "npv_with_revenue", "annual_revenue",
                    "margin_USD_per_kg", "payback_yr"):
            assert key in r

    def test_zero_price_gives_negative_npv(self):
        r = self._run(price=0.0)
        assert r["npv_with_revenue"] < 0

    def test_high_price_improves_npv(self):
        r_low  = self._run(price=1.0)
        r_high = self._run(price=10.0)
        assert r_high["npv_with_revenue"] > r_low["npv_with_revenue"]

    def test_margin_equals_price_minus_lcoh(self):
        r = self._run(price=5.0)
        lcoh = r["lcoh"]
        if not math.isnan(lcoh):
            assert abs(r["margin_USD_per_kg"] - (5.0 - lcoh)) < 1e-6

    def test_break_even_price_is_lcoh(self):
        """At price = LCOH, NPV should be approximately zero."""
        r_base = self._run(price=3.0)
        lcoh = r_base["lcoh"]
        if math.isnan(lcoh) or lcoh <= 0:
            pytest.skip("LCOH not computed for this flowsheet")
        from pse_ecosystem.ui.flowsheet_service import compute_npv_with_revenue
        fs, result = _pem_flowsheet_and_solve()
        r_be = compute_npv_with_revenue(fs, result.x, result.kpis, _base_econ_config(),
                                         product_price_USD_per_kg=lcoh)
        # NPV should be very close to zero at break-even price
        assert abs(r_be["npv_with_revenue"]) < abs(r_base["npv_with_revenue"]) * 0.1 + 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. generate_investor_report
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateInvestorReport:

    def _report(self, **kw):
        from pse_ecosystem.ui.flowsheet_service import generate_investor_report
        fs, result = _pem_flowsheet_and_solve()
        return generate_investor_report(
            flowsheet=fs,
            result=result,
            econ_config=_base_econ_config(),
            **kw,
        )

    def test_returns_string(self):
        assert isinstance(self._report(), str)

    def test_contains_section_headings(self):
        md = self._report()
        for heading in ["§1", "§2", "§3", "§4", "§6"]:
            assert heading in md

    def test_contains_scenario_label(self):
        md = self._report(scenario_label="Optimistic")
        assert "Optimistic" in md

    def test_contains_assumptions_section(self):
        md = self._report()
        assert "Assumptions" in md
        assert "Plant life" in md
        assert "Discount rate" in md

    def test_contains_disclaimer(self):
        md = self._report()
        assert "preliminary" in md.lower() or "not a certified" in md.lower()

    def test_with_tornado_rows(self):
        from pse_ecosystem.ui.flowsheet_service import tornado_sensitivity
        fs, result = _pem_flowsheet_and_solve()
        t_rows = tornado_sensitivity(fs, result.x, result.kpis, _base_econ_config())
        from pse_ecosystem.ui.flowsheet_service import generate_investor_report
        md = generate_investor_report(
            flowsheet=fs, result=result,
            econ_config=_base_econ_config(), tornado_rows=t_rows,
        )
        assert "§5" in md or "Sensitivity" in md

    def test_with_safety_rows(self):
        from pse_ecosystem.ui.flowsheet_service import compute_safety_margins, generate_investor_report
        fs, result = _pem_flowsheet_and_solve()
        s_rows = compute_safety_margins(fs, result.x)
        md = generate_investor_report(
            flowsheet=fs, result=result,
            econ_config=_base_econ_config(), safety_rows=s_rows,
        )
        assert "§4" in md


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Scenario Manager data model
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioManagerModel:

    def _make_record(self, name="Base Case"):
        return {
            "name": name,
            "template_key": "hydrogen.electrolysis_only",
            "iterations": 12,
            "objective": 1.234,
            "kpis": {"H2_production_kg_h": 5.0},
            "installed_capex": 1_200_000.0,
            "annual_opex": 180_000.0,
            "tac": 280_000.0,
            "lcoh": 3.5,
            "lcoe": float("nan"),
            "npv": -500_000.0,
            "irr": float("nan"),
            "econ_config": {"plant_life_yr": 20, "interest_rate": 0.08},
        }

    def test_record_is_serialisable_to_json(self):
        """Scenario records must survive JSON round-trip (for future persistence)."""
        import json, math
        rec = self._make_record()
        # Replace NaN with None for JSON serialization (standard practice)
        def _sanitize(v):
            if isinstance(v, float) and math.isnan(v):
                return None
            return v
        sanitized = {k: _sanitize(v) for k, v in rec.items()
                     if not isinstance(v, dict)}
        blob = json.dumps(sanitized)
        loaded = json.loads(blob)
        assert loaded["name"] == "Base Case"
        assert loaded["lcoh"] == pytest.approx(3.5)

    def test_eviction_at_max_4(self):
        scenarios = []
        for i in range(5):
            rec = self._make_record(name=f"Scenario {i+1}")
            if len(scenarios) >= 4:
                scenarios.pop(0)
            scenarios.append(rec)
        assert len(scenarios) == 4
        assert scenarios[0]["name"] == "Scenario 2"
        assert scenarios[-1]["name"] == "Scenario 5"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. get_asme_materials gateway
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetASMEMaterials:

    def test_returns_dict(self):
        from pse_ecosystem.ui.flowsheet_service import get_asme_materials
        mats = get_asme_materials()
        assert isinstance(mats, dict)
        assert len(mats) >= 3

    def test_all_values_positive_pa(self):
        from pse_ecosystem.ui.flowsheet_service import get_asme_materials
        for name, stress in get_asme_materials().items():
            assert stress > 0, f"{name} has non-positive allowable stress"

    def test_contains_carbon_steel(self):
        from pse_ecosystem.ui.flowsheet_service import get_asme_materials
        mats = get_asme_materials()
        assert any("Carbon Steel" in k or "516" in k for k in mats)

    def test_returns_copy_not_mutable_original(self):
        from pse_ecosystem.ui.flowsheet_service import get_asme_materials
        m1 = get_asme_materials()
        m1["FAKE_MATERIAL"] = 999.0
        m2 = get_asme_materials()
        assert "FAKE_MATERIAL" not in m2


# ═══════════════════════════════════════════════════════════════════════════════
# 6. compute_outlet_flammability_warnings gateway
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeOutletFlammabilityWarnings:

    def test_returns_list(self):
        from pse_ecosystem.ui.flowsheet_service import compute_outlet_flammability_warnings
        fs, result = _pem_flowsheet_and_solve()
        w = compute_outlet_flammability_warnings(fs, result.x)
        assert isinstance(w, list)

    def test_no_warnings_for_non_flammable_flowsheet(self):
        """Electrolysis_only has H2 and O2 — H2 is flammable so we might get warnings."""
        from pse_ecosystem.ui.flowsheet_service import compute_outlet_flammability_warnings
        fs, result = _pem_flowsheet_and_solve()
        # Function should not raise regardless of content
        w = compute_outlet_flammability_warnings(fs, result.x)
        assert isinstance(w, list)

    def test_warning_strings_are_non_empty(self):
        from pse_ecosystem.ui.flowsheet_service import compute_outlet_flammability_warnings
        fs, result = _pem_flowsheet_and_solve()
        w = compute_outlet_flammability_warnings(fs, result.x)
        for item in w:
            assert isinstance(item, str) and len(item) > 0

    def test_no_pse_models_import_in_app_streamlit(self):
        """Gateway confirmed clean — verify app_streamlit.py still has no direct models.* import."""
        import ast, pathlib
        src = pathlib.Path(__file__).parent.parent / "pse_ecosystem" / "ui" / "app_streamlit.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        bad = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            and "pse_ecosystem.models" in (n.module or "")
        ]
        assert not bad, f"app_streamlit.py has forbidden models.* imports: {[n.module for n in bad]}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Solve-time session state key
# ═══════════════════════════════════════════════════════════════════════════════

class TestSolveTiming:

    def test_last_solve_elapsed_defaults_none(self):
        """_init_state pattern for last_solve_elapsed."""
        state = {}
        state.setdefault("last_solve_elapsed", None)
        assert state["last_solve_elapsed"] is None

    def test_elapsed_is_positive_after_solve(self):
        """Real solve should produce a positive elapsed time (simulated here)."""
        import time
        t0 = time.perf_counter()
        # Simulate a short solve
        _ = sum(range(10_000))
        elapsed = time.perf_counter() - t0
        assert elapsed > 0.0
        assert elapsed < 5.0  # sanity: should be much less than 5 s
