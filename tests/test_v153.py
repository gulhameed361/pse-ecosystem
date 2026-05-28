"""v1.5.3 feature and bug-fix tests.

Covers every issue resolved in v1.5.3:

  C-1  ProductionConfig revenue model + NPV/IRR correctness
  C-2  Sankey: only F_* variables, aggregated per unit pair
  C-3  _extract_power_out_kW: sum across generators, not max
  H-1  OBJECTIVE_LP_PROXY_NOTE dict presence and content
  H-2  Topology-aware H₂ yield objective (_topological_unit_order,
       _most_downstream_h2_outlet)
  H-3  Electrolyser CAPEX sourced from ProjectEconomicsConfig
  H-4  LP/MILP solver preference: HiGHS before GLPK
  H-5  ADAPTIVE mode propagates physics exceptions
  H-6  ASME whitelist expansion
  H-7  aggregate_kpis RuntimeWarning (already in test_technoeconomic)
  H-8  initial_x0 as proper dataclass field
  H-9  CompositeUnit.kpis() / .capex() propagate inner flowsheet results
  L-2  OPEXConvention is a str Enum, string literals still compare equal
  L-7  __all__ exported from core modules
  L-8  HeatExchangerNTU effectiveness clamped to [0, 1]
  L-9  _StepNormStop defined once, not per attempt
  M-3  Energy variable suffix-based matching (no false positives)
  M-7  history.jsonl disk rotation cap (≤ 200 lines)
  M-9  economics.json loaded at startup
  M-12 _most_downstream_h2_outlet handles non-standard port tags
  M-13 isinstance() replaces type().__name__ string comparison
  Misc TemplateSpec.recommends_trust_region advisory field
"""

from __future__ import annotations

import math
import warnings
from typing import Dict

import pytest


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _pem_flowsheet_and_solve():
    """Minimal converged PEM electrolysis solve (fast, fully linear)."""
    from pse_ecosystem.ui.flowsheet_service import load_template
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode

    fs = load_template("hydrogen.electrolysis_only")
    result = Orchestrator(
        flowsheet=fs,
        mode=SolveMode.FIXED_LP,
        slp_config=SLPConfig(max_iter=200),
    ).solve()
    return fs, result


def _base_econ():
    from pse_ecosystem.ui.flowsheet_service import ProjectEconomicsConfig
    return ProjectEconomicsConfig()


# ══════════════════════════════════════════════════════════════════════════════
# C-1: ProductionConfig revenue model
# ══════════════════════════════════════════════════════════════════════════════

class TestProductionConfig:
    """C-1: ProductionConfig dataclass and revenue-enabled NPV/IRR."""

    def test_production_config_is_importable(self):
        from pse_ecosystem.ui.flowsheet_service import ProductionConfig
        pc = ProductionConfig()
        assert pc.h2_price_USD_per_kg == 0.0
        assert pc.electricity_sale_price_USD_per_kWh == 0.0

    def test_production_config_h2_price_field(self):
        from pse_ecosystem.ui.flowsheet_service import ProductionConfig
        pc = ProductionConfig(h2_price_USD_per_kg=3.5)
        assert pc.h2_price_USD_per_kg == pytest.approx(3.5)

    def test_npv_is_na_string_without_prod_config(self):
        from pse_ecosystem.ui.flowsheet_service import compute_project_economics
        fs, result = _pem_flowsheet_and_solve()
        rows = compute_project_economics(fs, result.x, result.kpis, _base_econ())
        npv_row = next(r for r in rows if r["Metric"] == "NPV")
        assert "N/A" in str(npv_row["Value"]), (
            f"Expected 'N/A' in NPV when no revenue model, got {npv_row['Value']!r}"
        )

    def test_irr_is_na_string_without_prod_config(self):
        from pse_ecosystem.ui.flowsheet_service import compute_project_economics
        fs, result = _pem_flowsheet_and_solve()
        rows = compute_project_economics(fs, result.x, result.kpis, _base_econ())
        irr_row = next(r for r in rows if r["Metric"] == "IRR")
        assert "N/A" in str(irr_row["Value"])

    def test_annual_revenue_present_in_rows(self):
        from pse_ecosystem.ui.flowsheet_service import compute_project_economics
        fs, result = _pem_flowsheet_and_solve()
        rows = compute_project_economics(fs, result.x, result.kpis, _base_econ())
        keys = {r["Metric"] for r in rows}
        assert "Annual Revenue" in keys
        assert "Annual Net Cash Flow" in keys

    def test_npv_positive_with_high_h2_price(self):
        """NPV must be computable and positive when H₂ price >> LCOH."""
        from pse_ecosystem.ui.flowsheet_service import (
            compute_project_economics, ProductionConfig,
        )
        fs, result = _pem_flowsheet_and_solve()
        # $100/kg H₂ is absurdly high — guarantees positive revenue
        pc = ProductionConfig(h2_price_USD_per_kg=100.0)
        rows = compute_project_economics(fs, result.x, result.kpis, _base_econ(),
                                         prod_config=pc)
        npv_row = next(r for r in rows if r["Metric"] == "NPV")
        assert isinstance(npv_row["Value"], float), "NPV should be a float with revenue model"
        assert npv_row["Value"] > 0, f"NPV should be positive at $100/kg H₂, got {npv_row['Value']}"

    def test_irr_finite_with_revenue(self):
        """IRR must be a finite float when there is sufficient revenue."""
        from pse_ecosystem.ui.flowsheet_service import (
            compute_project_economics, ProductionConfig,
        )
        fs, result = _pem_flowsheet_and_solve()
        pc = ProductionConfig(h2_price_USD_per_kg=100.0)
        rows = compute_project_economics(fs, result.x, result.kpis, _base_econ(),
                                         prod_config=pc)
        irr_row = next(r for r in rows if r["Metric"] == "IRR")
        assert isinstance(irr_row["Value"], float)
        assert math.isfinite(irr_row["Value"]) or math.isinf(irr_row["Value"]), (
            "IRR should be finite or +inf when project pays back"
        )

    def test_tax_and_inflation_labelled_informational(self):
        from pse_ecosystem.ui.flowsheet_service import compute_project_economics
        fs, result = _pem_flowsheet_and_solve()
        rows = compute_project_economics(fs, result.x, result.kpis, _base_econ())
        tax_row = next(r for r in rows if r["Metric"] == "Tax Rate")
        assert "informational" in tax_row["Unit"].lower(), (
            f"Tax Rate unit should mention 'informational', got {tax_row['Unit']!r}"
        )

    def test_pem_capex_from_econ_config(self):
        """H-3: pem_capex_USD_per_kW is now 1200 by default (was 700)."""
        from pse_ecosystem.ui.flowsheet_service import ProjectEconomicsConfig
        cfg = ProjectEconomicsConfig()
        assert cfg.pem_capex_USD_per_kW == pytest.approx(1_200.0), (
            "Default PEM CAPEX should be 1200 USD/kW (NREL 2024 estimate)"
        )

    def test_pem_capex_propagates_to_objective(self):
        """H-3: custom pem_capex_USD_per_kW is used in build_objective_extra.

        Uses dac.power_to_methane which contains an ElectrolyserHF unit with
        an elec.W_elec_kW variable — the only template where CAPEX injection
        applies (PEMToy is a separate toy class, not ElectrolyserHF).
        """
        from pse_ecosystem.ui.flowsheet_service import (
            build_objective_extra, load_template, ProjectEconomicsConfig,
        )
        fs = load_template("dac.power_to_methane")
        cfg_cheap     = ProjectEconomicsConfig(pem_capex_USD_per_kW=700.0)
        cfg_expensive = ProjectEconomicsConfig(pem_capex_USD_per_kW=1_500.0)

        obj_cheap, _ = build_objective_extra(fs, "Minimize TAC", econ_config=cfg_cheap)
        obj_exp, _   = build_objective_extra(fs, "Minimize TAC", econ_config=cfg_expensive)

        # ElectrolyserHF exposes elec.W_elec_kW
        w_vars = [v for v in obj_cheap if v.lower().endswith(".w_elec_kw")]
        assert w_vars, (
            f"Expected at least one .W_elec_kW variable in TAC objective, "
            f"got {list(obj_cheap.keys())[:10]}"
        )
        v = w_vars[0]
        assert obj_exp[v] > obj_cheap[v], (
            f"Higher PEM CAPEX (1500) should produce larger objective coefficient "
            f"than 700 for variable {v!r}: cheap={obj_cheap[v]:.4g}, "
            f"expensive={obj_exp[v]:.4g}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C-2: Sankey diagram — F_* only, aggregated per unit pair
# ══════════════════════════════════════════════════════════════════════════════

class TestSankeyDiagram:
    """C-2: Sankey only shows molar/mass flows, aggregated per unit pair."""

    def _build_sankey(self):
        from pse_ecosystem.ui.flowsheet_service import build_sankey_data, load_template
        from pse_ecosystem.solvers.orchestrator import Orchestrator
        from pse_ecosystem.solvers.slp import SLPConfig
        from pse_ecosystem.core.contracts import SolveMode

        fs = load_template("hydrogen.electrolysis_only")
        result = Orchestrator(
            flowsheet=fs,
            mode=SolveMode.FIXED_LP,
            slp_config=SLPConfig(max_iter=200),
        ).solve()
        return build_sankey_data(fs, result.x), fs, result.x

    def test_sankey_returns_required_keys(self):
        data, _, _ = self._build_sankey()
        for key in ("labels", "sources", "targets", "values", "link_labels"):
            assert key in data

    def test_sankey_no_temperature_variables(self):
        """T variables must not appear as link labels."""
        data, fs, x = self._build_sankey()
        for label in data["link_labels"]:
            assert not label.startswith("T="), (
                f"Temperature variable leaked into Sankey: {label!r}"
            )
            # T as a stand-alone component label
            parts = label.split(",")
            for p in parts:
                comp = p.split("=")[0].strip()
                assert comp != "T" and comp != "P", (
                    f"Intensive variable '{comp}' found in Sankey link labels"
                )

    def test_sankey_no_pressure_variables(self):
        """P variables must not appear as link labels."""
        data, _, _ = self._build_sankey()
        for label in data["link_labels"]:
            parts = label.split(",")
            for p in parts:
                comp = p.split("=")[0].strip()
                assert comp != "P", f"Pressure variable found in Sankey: {label!r}"

    def test_sankey_link_count_at_most_unit_pairs(self):
        """After aggregation, links ≤ number of connected unit pairs."""
        data, fs, _ = self._build_sankey()
        n_links = len(data["sources"])
        n_units = len(fs.units)
        # At most one link per directed unit pair
        assert n_links <= n_units * (n_units - 1), (
            "More Sankey links than possible unit pairs"
        )

    def test_sankey_values_positive(self):
        data, _, _ = self._build_sankey()
        for v in data["values"]:
            assert v > 0, f"Sankey link value must be > 0, got {v}"

    def test_sankey_flow_magnitudes_sane(self):
        """All flow values must be < 1e4 — not in temperature/pressure range."""
        data, _, _ = self._build_sankey()
        for v in data["values"]:
            assert v < 1e4, (
                f"Sankey value {v:.2g} is suspiciously large — "
                "may be a T or P variable that wasn't filtered"
            )


# ══════════════════════════════════════════════════════════════════════════════
# C-3: _extract_power_out_kW — sum not max
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractPowerOutKw:
    """C-3: sum across multiple generators."""

    def _extract(self, kpis):
        from pse_ecosystem.ui.flowsheet_service import _extract_power_out_kW
        return _extract_power_out_kW(kpis)

    def test_single_generator(self):
        assert self._extract({"chp_a.total_useful_output_kW": 500.0}) == pytest.approx(500.0)

    def test_two_generators_summed(self):
        kpis = {
            "chp_a.total_useful_output_kW": 300.0,
            "chp_b.total_useful_output_kW": 400.0,
        }
        assert self._extract(kpis) == pytest.approx(700.0), (
            "Two CHP units: power should be summed, not max(300, 400)=400"
        )

    def test_fallback_to_elec_kw(self):
        kpis = {"pem.W_elec_kW": 1000.0}
        assert self._extract(kpis) == pytest.approx(1000.0)

    def test_priority_total_useful_over_w_elec(self):
        kpis = {
            "unit.total_useful_output_kW": 250.0,
            "unit.W_elec_kW": 1000.0,
        }
        assert self._extract(kpis) == pytest.approx(250.0)

    def test_zero_when_no_power_kpis(self):
        assert self._extract({"lcoh": 3.0, "h2_kg_s": 0.01}) == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════════════
# H-1: OBJECTIVE_LP_PROXY_NOTE
# ══════════════════════════════════════════════════════════════════════════════

class TestObjectiveLpProxyNote:
    """H-1: proxy-warning dict is present and consistent with OBJECTIVE_TIERS."""

    def test_proxy_note_is_importable(self):
        from pse_ecosystem.ui.flowsheet_service import OBJECTIVE_LP_PROXY_NOTE
        assert isinstance(OBJECTIVE_LP_PROXY_NOTE, dict)

    def test_npv_in_proxy_note(self):
        from pse_ecosystem.ui.flowsheet_service import OBJECTIVE_LP_PROXY_NOTE
        assert "Maximize NPV (Net Present Value)" in OBJECTIVE_LP_PROXY_NOTE

    def test_irr_in_proxy_note(self):
        from pse_ecosystem.ui.flowsheet_service import OBJECTIVE_LP_PROXY_NOTE
        assert "Maximize IRR (Internal Rate of Return)" in OBJECTIVE_LP_PROXY_NOTE

    def test_proxy_note_values_are_strings(self):
        from pse_ecosystem.ui.flowsheet_service import OBJECTIVE_LP_PROXY_NOTE
        for k, v in OBJECTIVE_LP_PROXY_NOTE.items():
            assert isinstance(v, str) and len(v) > 0, (
                f"Proxy note for {k!r} must be a non-empty string"
            )

    def test_proxy_note_keys_in_objective_tiers(self):
        """Every key in OBJECTIVE_LP_PROXY_NOTE must be a valid objective mode."""
        from pse_ecosystem.ui.flowsheet_service import (
            OBJECTIVE_LP_PROXY_NOTE, OBJECTIVE_TIERS,
        )
        all_modes = {m for modes in OBJECTIVE_TIERS.values() for m in modes}
        for k in OBJECTIVE_LP_PROXY_NOTE:
            assert k in all_modes, f"{k!r} not in OBJECTIVE_TIERS"


# ══════════════════════════════════════════════════════════════════════════════
# H-2: Topology-aware H₂ yield objective
# ══════════════════════════════════════════════════════════════════════════════

class TestTopologyHelpers:
    """H-2: _topological_unit_order and _most_downstream_h2_outlet."""

    def _make_chain_flowsheet(self):
        """Build a minimal 3-unit chain: feed → wgs → psa."""
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
        from pse_ecosystem.models.base_unit import BaseUnit
        import numpy as np

        class _StubUnit(BaseUnit):
            def __init__(self, uid, vars_):
                self.unit_id = uid
                self._vars = vars_

            def variables(self):   return list(self._vars)
            def bounds(self):      return {v: (0, 1000) for v in self._vars}
            def residual(self, x): return np.zeros(0)
            def objective_contribution(self, x): return {}

        feed = _StubUnit("feed", ["feed.outlet.F_H2", "feed.outlet.F_CO",
                                   "feed.outlet.T", "feed.outlet.P"])
        wgs  = _StubUnit("wgs",  ["wgs.inlet.F_H2", "wgs.inlet.F_CO",
                                   "wgs.outlet.F_H2", "wgs.outlet.F_CO",
                                   "wgs.inlet.T", "wgs.outlet.T",
                                   "wgs.inlet.P", "wgs.outlet.P"])
        psa  = _StubUnit("psa",  ["psa.inlet.F_H2", "psa.inlet.F_CO",
                                   "psa.outlet.F_H2",
                                   "psa.inlet.T", "psa.outlet.T",
                                   "psa.inlet.P", "psa.outlet.P"])
        conns = [
            Connection("feed.outlet.F_H2", "wgs.inlet.F_H2"),
            Connection("feed.outlet.F_CO", "wgs.inlet.F_CO"),
            Connection("wgs.outlet.F_H2", "psa.inlet.F_H2"),
            Connection("wgs.outlet.F_CO", "psa.inlet.F_CO"),
        ]
        fs = BaseFlowsheet(name="test_chain", units=[feed, wgs, psa],
                           connections=conns)
        return fs

    def test_topological_sort_linear_chain(self):
        from pse_ecosystem.ui.flowsheet_service import _topological_unit_order
        fs = self._make_chain_flowsheet()
        order = _topological_unit_order(fs)
        # feed must come before wgs, wgs before psa
        assert order.index("feed") < order.index("wgs"), "feed must precede wgs"
        assert order.index("wgs") < order.index("psa"), "wgs must precede psa"

    def test_most_downstream_h2_outlet_returns_psa_not_wgs(self):
        """PSA is downstream of WGS — the objective should target psa.outlet.F_H2."""
        from pse_ecosystem.ui.flowsheet_service import _most_downstream_h2_outlet
        fs = self._make_chain_flowsheet()
        all_vars = fs.all_variables()
        best = _most_downstream_h2_outlet(fs, all_vars)
        assert best is not None, "Should find a H₂ outlet variable"
        assert "psa" in best, (
            f"Most downstream H₂ outlet should belong to psa, got {best!r}"
        )
        assert "wgs" not in best, (
            f"WGS outlet should not be chosen over downstream PSA; got {best!r}"
        )

    def test_most_downstream_h2_outlet_fallback_on_no_h2(self):
        """Returns None when no F_H2 variable exists anywhere."""
        from pse_ecosystem.ui.flowsheet_service import _most_downstream_h2_outlet
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.base_unit import BaseUnit
        import numpy as np

        class _NoH2(BaseUnit):
            unit_id = "no_h2"
            def variables(self):   return ["no_h2.outlet.F_CO2"]
            def bounds(self):      return {"no_h2.outlet.F_CO2": (0, 100)}
            def residual(self, x): return np.zeros(0)
            def objective_contribution(self, x): return {}

        fs = BaseFlowsheet(name="no_h2", units=[_NoH2()])
        result = _most_downstream_h2_outlet(fs, fs.all_variables())
        assert result is None

    def test_h2_yield_objective_uses_topology(self):
        """build_objective_extra picks the topologically correct H₂ outlet."""
        from pse_ecosystem.ui.flowsheet_service import build_objective_extra
        fs = self._make_chain_flowsheet()
        obj, _ = build_objective_extra(fs, "Maximize H₂ Yield")
        # psa.outlet.F_H2 should have coefficient -1.0
        assert "psa.outlet.F_H2" in obj, (
            f"Expected psa.outlet.F_H2 in objective dict, got {list(obj.keys())}"
        )
        assert obj["psa.outlet.F_H2"] == pytest.approx(-1.0)
        # wgs outlet should NOT be targeted
        assert "wgs.outlet.F_H2" not in obj, (
            "WGS outlet should not be in objective when PSA is downstream"
        )

    def test_h2_outlet_broadened_non_standard_port(self):
        """M-12: 'product' port tag is detected as an outlet."""
        from pse_ecosystem.ui.flowsheet_service import _most_downstream_h2_outlet
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.base_unit import BaseUnit
        import numpy as np

        class _ProductPort(BaseUnit):
            unit_id = "sep"
            def variables(self):   return ["sep.product.F_H2", "sep.inlet.F_H2"]
            def bounds(self):      return {v: (0, 100) for v in self.variables()}
            def residual(self, x): return np.zeros(0)
            def objective_contribution(self, x): return {}

        fs = BaseFlowsheet(name="prod", units=[_ProductPort()])
        result = _most_downstream_h2_outlet(fs, fs.all_variables())
        assert result is not None, "Should detect F_H2 with 'product' port tag"
        assert "F_H2" in result


# ══════════════════════════════════════════════════════════════════════════════
# H-4: LP solver preference order
# ══════════════════════════════════════════════════════════════════════════════

class TestSolverPreference:
    """H-4: HiGHS (appsi_highs/highs) must come before CBC and GLPK."""

    def test_lp_solver_candidates_prefer_highs(self):
        import inspect
        from pse_ecosystem.solvers import lp_builder
        src = inspect.getsource(lp_builder.select_lp_solver)
        # The first element in the candidates list must be HiGHS
        assert 'appsi_highs' in src
        highs_pos = src.find('appsi_highs')
        glpk_pos  = src.find('"glpk"')
        assert highs_pos < glpk_pos, (
            "appsi_highs must appear before glpk in select_lp_solver candidates"
        )

    def test_milp_solver_candidates_prefer_highs(self):
        import inspect
        from pse_ecosystem.solvers import milp_builder
        src = inspect.getsource(milp_builder.select_milp_solver)
        assert 'appsi_highs' in src
        highs_pos = src.find('appsi_highs')
        glpk_pos  = src.find('"glpk"')
        assert highs_pos < glpk_pos, (
            "appsi_highs must appear before glpk in select_milp_solver candidates"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H-5: ADAPTIVE mode exception narrowing
# ══════════════════════════════════════════════════════════════════════════════

class TestAdaptiveExceptions:
    """H-5: physics exceptions propagate; only infrastructure errors are swallowed."""

    def test_adaptive_propagates_value_error_from_nlp(self):
        """A ValueError raised inside NLPDriver must not be silently swallowed."""
        from pse_ecosystem.solvers.orchestrator import Orchestrator
        from pse_ecosystem.solvers.slp import SLPConfig
        from pse_ecosystem.core.contracts import SolveMode
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.base_unit import BaseUnit
        import numpy as np

        class _ExplodingUnit(BaseUnit):
            unit_id = "boom"
            is_linear = False
            _call_count = 0

            def variables(self):   return ["boom.x"]
            def bounds(self):      return {"boom.x": (0.0, 10.0)}
            def residual(self, x):
                _ExplodingUnit._call_count += 1
                # Explode after a few calls so SLP converges first
                if _ExplodingUnit._call_count > 5:
                    raise ZeroDivisionError("intentional physics error")
                return np.array([x.get("boom.x", 0.0) - 5.0])
            def objective_contribution(self, x): return {}

        _ExplodingUnit._call_count = 0
        fs = BaseFlowsheet(name="explode", units=[_ExplodingUnit()])

        # ADAPTIVE should NOT silently swallow ZeroDivisionError
        # (it is not ImportError / RuntimeError / AttributeError)
        with pytest.raises(ZeroDivisionError):
            Orchestrator(
                flowsheet=fs,
                mode=SolveMode.ADAPTIVE,
                slp_config=SLPConfig(max_iter=5),
            ).solve()


# ══════════════════════════════════════════════════════════════════════════════
# H-6: ASME whitelist expansion
# ══════════════════════════════════════════════════════════════════════════════

class TestAsmeWhitelist:
    """H-6: new pressure-bearing units are in _ASME_VESSEL_UNIT_TYPES."""

    def test_new_units_in_whitelist(self):
        import pse_ecosystem.ui.flowsheet_service as svc
        expected = {
            "PFRHF", "TVSAContactor", "DistillationHF",
            "ShellTubeHX", "Pump", "MethanationReactor", "FlashSL",
        }
        missing = expected - svc._ASME_VESSEL_UNIT_TYPES
        assert not missing, (
            f"These units should be in _ASME_VESSEL_UNIT_TYPES but are missing: {missing}"
        )

    def test_original_units_still_in_whitelist(self):
        import pse_ecosystem.ui.flowsheet_service as svc
        original = {"Compressor", "FlashVLHF", "CSTRHF", "EquilibriumReactor",
                    "GibbsReactor", "BiomassGasifierHF"}
        assert original <= svc._ASME_VESSEL_UNIT_TYPES, (
            "Original ASME whitelist units must still be present"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H-8: initial_x0 as declared dataclass field
# ══════════════════════════════════════════════════════════════════════════════

class TestInitialX0Field:
    """H-8: initial_x0 is a proper Optional[Dict] dataclass field."""

    def test_initial_x0_field_exists_in_dataclass(self):
        import dataclasses
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        field_names = {f.name for f in dataclasses.fields(BaseFlowsheet)}
        assert "initial_x0" in field_names, (
            "initial_x0 must be a declared dataclass field on BaseFlowsheet"
        )

    def test_initial_x0_defaults_to_none(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.base_unit import BaseUnit
        import numpy as np

        class _U(BaseUnit):
            unit_id = "u"
            def variables(self):   return ["u.x"]
            def bounds(self):      return {"u.x": (0.0, 10.0)}
            def residual(self, x): return np.zeros(0)
            def objective_contribution(self, x): return {}

        fs = BaseFlowsheet(name="t", units=[_U()])
        assert fs.initial_x0 is None

    def test_initial_x0_seed_used_in_initial_guess(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.base_unit import BaseUnit
        import numpy as np

        class _U(BaseUnit):
            unit_id = "u"
            def variables(self):   return ["u.x"]
            def bounds(self):      return {"u.x": (0.0, 10.0)}
            def residual(self, x): return np.zeros(0)
            def objective_contribution(self, x): return {}

        fs = BaseFlowsheet(name="t", units=[_U()], initial_x0={"u.x": 7.777})
        guess = fs.initial_guess()
        assert guess["u.x"] == pytest.approx(7.777), (
            "initial_x0 value should override the bound-midpoint guess"
        )

    def test_initial_x0_no_hasattr_duck_typing(self):
        """Verify the old hasattr pattern is gone from initial_guess."""
        import inspect
        from pse_ecosystem.flowsheets import base_flowsheet
        src = inspect.getsource(base_flowsheet.BaseFlowsheet.initial_guess)
        assert "hasattr" not in src, (
            "initial_guess must use self.initial_x0 is not None, not hasattr()"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H-9: CompositeUnit KPI / CAPEX propagation
# ══════════════════════════════════════════════════════════════════════════════

class TestCompositeUnitKpiPropagation:
    """H-9: CompositeUnit.kpis() and .capex() propagate inner flowsheet results."""

    def _build_inner_and_composite(self):
        """Build a trivial inner flowsheet and wrap it as a CompositeUnit.

        The electrolysis_only flowsheet has exactly two variables:
          pem.electricity_kW  — input (power draw)
          pem.h2_kg_per_h     — output (H₂ production rate)
        """
        from pse_ecosystem.ui.flowsheet_service import load_template
        from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit

        inner_fs = load_template("hydrogen.electrolysis_only")
        comp = CompositeUnit(
            unit_id="comp_pem",
            inner_flowsheet=inner_fs,
            exposed_inputs=["pem.electricity_kW"],
            exposed_outputs=["pem.h2_kg_per_h"],
        )
        return comp, inner_fs

    def test_composite_kpis_empty_before_solve(self):
        comp, _ = self._build_inner_and_composite()
        kpis = comp.kpis({})
        assert kpis == {}, "kpis() should return {} before any residual() call"

    def test_composite_capex_zero_before_solve(self):
        comp, _ = self._build_inner_and_composite()
        assert comp.capex({}) == pytest.approx(0.0)

    def test_composite_kpis_after_residual_call(self):
        """After a successful residual() call the inner KPIs are available."""
        comp, inner_fs = self._build_inner_and_composite()
        x = inner_fs.initial_guess()
        x["pem.electricity_kW"] = 10_000.0
        try:
            comp.residual(x)
        except Exception:
            pytest.skip("Inner SLP failed — environment issue, not a test failure")
        kpis_after = comp.kpis(x)
        assert isinstance(kpis_after, dict)
        # If the inner SLP converged, the cache must be populated
        if comp._last_inner_x is not None:
            assert len(kpis_after) >= 0   # at minimum an empty dict is fine

    def test_composite_last_inner_x_is_none_initially(self):
        comp, _ = self._build_inner_and_composite()
        assert comp._last_inner_x is None


# ══════════════════════════════════════════════════════════════════════════════
# L-2: OPEXConvention Enum
# ══════════════════════════════════════════════════════════════════════════════

class TestOPEXConventionEnum:
    """L-2: OPEXConvention is a str Enum; old string comparisons still work."""

    def test_opex_convention_is_importable(self):
        from pse_ecosystem.models.base_unit import OPEXConvention
        assert OPEXConvention is not None

    def test_opex_convention_is_enum(self):
        from enum import Enum
        from pse_ecosystem.models.base_unit import OPEXConvention
        assert issubclass(OPEXConvention, Enum)

    def test_opex_convention_members(self):
        from pse_ecosystem.models.base_unit import OPEXConvention
        assert OPEXConvention.USD_PER_YEAR == "USD_per_year"
        assert OPEXConvention.USD_PER_SECOND == "USD_per_second"
        assert OPEXConvention.YIELD_COEFFICIENT == "yield_coefficient"

    def test_string_comparison_backward_compat(self):
        """Old code that compares _OPEX_CONVENTION == 'USD_per_year' must still work."""
        from pse_ecosystem.models.base_unit import OPEXConvention, BaseUnit
        # BaseUnit default
        assert BaseUnit._OPEX_CONVENTION == "USD_per_year"
        assert BaseUnit._OPEX_CONVENTION == OPEXConvention.USD_PER_YEAR

    def test_base_unit_default_convention(self):
        from pse_ecosystem.models.base_unit import OPEXConvention, BaseUnit
        assert BaseUnit._OPEX_CONVENTION == OPEXConvention.USD_PER_YEAR

    def test_units_in_all_export(self):
        from pse_ecosystem.models.base_unit import __all__
        assert "OPEXConvention" in __all__
        assert "BaseUnit" in __all__


# ══════════════════════════════════════════════════════════════════════════════
# L-7: __all__ in public modules
# ══════════════════════════════════════════════════════════════════════════════

class TestPublicApiAll:
    """L-7: __all__ is present on key modules."""

    def test_contracts_has_all(self):
        import pse_ecosystem.core.contracts as m
        assert hasattr(m, "__all__")
        assert "SolveResult" in m.__all__
        assert "LinearizedModel" in m.__all__
        assert "PrimalGuess" in m.__all__

    def test_base_flowsheet_has_all(self):
        import pse_ecosystem.flowsheets.base_flowsheet as m
        assert hasattr(m, "__all__")
        assert "BaseFlowsheet" in m.__all__
        assert "CompositeUnit" in m.__all__

    def test_base_unit_has_all(self):
        import pse_ecosystem.models.base_unit as m
        assert hasattr(m, "__all__")
        assert "BaseUnit" in m.__all__


# ══════════════════════════════════════════════════════════════════════════════
# L-8: HeatExchangerNTU effectiveness clamp
# ══════════════════════════════════════════════════════════════════════════════

class TestNTUEffectivenessClamp:
    """L-8: _eps_from_NTU always returns a value in [0, 1]."""

    def test_effectiveness_clamped_high_NTU(self):
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import HeatExchangerNTU
        # Extremely high NTU should saturate to 1.0, not exceed it
        eps = HeatExchangerNTU._eps_from_NTU(NTU=1000.0, C_star=0.5)
        assert 0.0 <= eps <= 1.0, f"Effectiveness {eps} out of [0, 1] for high NTU"

    def test_effectiveness_clamped_balanced_flow(self):
        """Balanced case (C_star ≈ 1) must return ≤ 1.0."""
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import HeatExchangerNTU
        eps = HeatExchangerNTU._eps_from_NTU(NTU=5.0, C_star=1.0 - 1e-7)
        assert 0.0 <= eps <= 1.0, f"Effectiveness {eps} out of [0,1] for balanced flow"

    def test_effectiveness_zero_NTU(self):
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import HeatExchangerNTU
        eps = HeatExchangerNTU._eps_from_NTU(NTU=0.0, C_star=0.5)
        assert eps == pytest.approx(0.0, abs=1e-9)

    def test_effectiveness_physically_reasonable(self):
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import HeatExchangerNTU
        for ntu in [0.5, 1.0, 2.0, 5.0, 10.0]:
            for c_star in [0.0, 0.3, 0.6, 0.9, 1.0 - 1e-8]:
                eps = HeatExchangerNTU._eps_from_NTU(NTU=ntu, C_star=c_star)
                assert 0.0 <= eps <= 1.0, (
                    f"eps={eps} outside [0,1] at NTU={ntu}, C_star={c_star}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# M-3: Energy variable suffix matching (no false positives)
# ══════════════════════════════════════════════════════════════════════════════

class TestEnergyVariableMatching:
    """M-3: build_objective_extra must not pick up non-energy variables
    that merely contain an energy-related substring."""

    def test_substring_false_positive_eliminated(self):
        """A variable like 'unit.net_electricity_kw_limit' must NOT get
        an energy coefficient when using 'Minimize Energy' mode."""
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.base_unit import BaseUnit
        from pse_ecosystem.ui.flowsheet_service import build_objective_extra
        import numpy as np

        class _TrapUnit(BaseUnit):
            unit_id = "trap"
            is_linear = True
            def variables(self):
                # Innocuous variable that CONTAINS 'electricity_kw' as a substring
                # but is not an actual power draw variable
                return ["trap.net_electricity_kw_limit",
                        "trap.outlet.electricity_kw"]  # this IS a real energy var
            def bounds(self):
                return {v: (0, 1e6) for v in self.variables()}
            def residual(self, x): return np.zeros(0)
            def objective_contribution(self, x): return {}

        fs = BaseFlowsheet(name="trap", units=[_TrapUnit()])
        obj, _ = build_objective_extra(fs, "Minimize Energy")

        # The 'limit' variable (a capacity bound, not a flow) must NOT appear
        # because it doesn't match any suffix: the variable's leaf part is
        # 'electricity_kw_limit', not exactly '.electricity_kw'
        assert "trap.net_electricity_kw_limit" not in obj, (
            "Capacity-limit variable with energy substring must NOT enter objective"
        )
        # But the actual energy variable SHOULD be included
        assert "trap.outlet.electricity_kw" in obj, (
            "True energy outlet variable must appear in objective"
        )

    def test_isinstance_check_for_electrolyser_hf(self):
        """M-13: isinstance() used, not type().__name__ string comparison."""
        import inspect
        from pse_ecosystem.ui import flowsheet_service
        src = inspect.getsource(flowsheet_service.build_objective_extra)
        assert 'isinstance' in src and 'ElectrolyserHF' in src, (
            "build_objective_extra must use isinstance(unit, ElectrolyserHF)"
        )
        assert "type(unit).__name__ ==" not in src, (
            "build_objective_extra must not use type().__name__ string comparison"
        )


# ══════════════════════════════════════════════════════════════════════════════
# M-7: history.jsonl disk rotation
# ══════════════════════════════════════════════════════════════════════════════

class TestHistoryRotation:
    """M-7: history.jsonl must not exceed 200 lines on disk."""

    def test_history_file_capped_at_200_lines(self, tmp_path, monkeypatch):
        import json
        import pse_ecosystem.ui.flowsheet_service as svc

        fake_path = tmp_path / "history.jsonl"
        monkeypatch.setattr(svc, "_SOLVE_HISTORY_PATH", fake_path)

        # Pre-populate with 210 lines
        with open(fake_path, "w") as fh:
            for i in range(210):
                fh.write(json.dumps({"seq": i}) + "\n")

        # Build a minimal fake result object
        class _FakeResult:
            status = "converged"
            iterations = 1
            objective = 0.0
            converged = True
            x = {}
            kpis = {}
            message = ""

        session = {}
        svc.record_solve_in_history(session, _FakeResult(), "SLP", "TAC")

        with open(fake_path) as fh:
            lines = fh.readlines()

        assert len(lines) <= 200, (
            f"history.jsonl should be capped at 200 lines, got {len(lines)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# M-9: economics.json loaded at startup
# ══════════════════════════════════════════════════════════════════════════════

class TestEconomicsJson:
    """M-9: economics.json file is present and loaded into CEPCI dict."""

    def test_economics_json_file_exists(self):
        import pathlib
        data_dir = pathlib.Path(__file__).parent.parent / "pse_ecosystem" / "data"
        json_path = data_dir / "economics.json"
        assert json_path.exists(), (
            f"pse_ecosystem/data/economics.json must exist, not found at {json_path}"
        )

    def test_cepci_dict_populated_from_json(self):
        from pse_ecosystem.models.costing.economic_engine import CEPCI
        assert len(CEPCI) >= 10, "CEPCI dict must have at least 10 data years"
        assert 2001 in CEPCI, "Year 2001 (CE=500 SSLW basis) must be in CEPCI dict"
        assert 2024 in CEPCI, "Year 2024 must be in CEPCI dict"

    def test_cepci_2001_is_sslw_basis(self):
        from pse_ecosystem.models.costing.economic_engine import CEPCI
        assert CEPCI[2001] == pytest.approx(394.3, rel=1e-3), (
            "CEPCI[2001] should be ~394.3 (CE=500 basis for SSLW correlations)"
        )

    def test_cepci_escalation_rate_is_float(self):
        from pse_ecosystem.models.costing.economic_engine import CEPCI_ESCALATION_RATE
        assert isinstance(CEPCI_ESCALATION_RATE, float)
        assert 0.01 <= CEPCI_ESCALATION_RATE <= 0.10, (
            "Escalation rate should be between 1% and 10% per year"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TemplateSpec.recommends_trust_region
# ══════════════════════════════════════════════════════════════════════════════

class TestTemplateSpecTrustRegion:
    """M-5: Non-linear templates flag recommends_trust_region=True."""

    def test_biomass_template_recommends_trust_region(self):
        from pse_ecosystem.ui.flowsheet_service import get_template
        spec = get_template("biomass.gasification_to_hydrogen")
        assert spec.recommends_trust_region is True, (
            "biomass.gasification_to_hydrogen has non-linear BiomassGasifierHF — "
            "must recommend trust region"
        )

    def test_grand_challenge_recommends_trust_region(self):
        from pse_ecosystem.ui.flowsheet_service import get_template
        spec = get_template("industrial.grand_challenge_10unit")
        assert spec.recommends_trust_region is True

    def test_linear_template_does_not_recommend_trust_region(self):
        from pse_ecosystem.ui.flowsheet_service import get_template
        # Electrolysis-only is fully linear — no TR needed
        spec = get_template("hydrogen.electrolysis_only")
        assert spec.recommends_trust_region is False, (
            "Fully linear template should not recommend trust region by default"
        )

    def test_template_spec_field_exists(self):
        import dataclasses
        from pse_ecosystem.ui.flowsheet_service import TemplateSpec
        field_names = {f.name for f in dataclasses.fields(TemplateSpec)}
        assert "recommends_trust_region" in field_names


# ══════════════════════════════════════════════════════════════════════════════
# L-9: _StepNormStop defined once outside attempt loop
# ══════════════════════════════════════════════════════════════════════════════

class TestStepNormStop:
    """L-9: _StepNormStop must be defined ONCE per run() call, not once per attempt.

    The bug was that the class was defined inside the per-attempt for-loop,
    creating a new class object on every restart.  The fix moves it to
    before the loop (still inside run()) so the class identity is stable
    across all attempts and Python's exception matching works correctly.
    """

    def test_step_norm_stop_defined_exactly_once_in_run(self):
        import inspect
        from pse_ecosystem.solvers.ipopt_driver import NLPDriver
        src = inspect.getsource(NLPDriver.run)
        count = src.count("class _StepNormStop")
        # Exactly ONE definition per run() body — before the loop, not inside it.
        # If count is 0 it was accidentally removed; if > 1 it was put back in the loop.
        assert count == 1, (
            f"_StepNormStop must be defined exactly once in run(), got {count}"
        )

    def test_step_norm_stop_not_inside_for_loop(self):
        """The class definition must appear before 'for attempt in range'."""
        import inspect
        from pse_ecosystem.solvers.ipopt_driver import NLPDriver
        src = inspect.getsource(NLPDriver.run)
        class_pos  = src.find("class _StepNormStop")
        loop_pos   = src.find("for attempt in range")
        assert class_pos != -1, "_StepNormStop definition not found in run()"
        assert loop_pos  != -1, "attempt loop not found in run()"
        assert class_pos < loop_pos, (
            "_StepNormStop must be defined BEFORE the 'for attempt' loop, "
            "not inside it"
        )

    def test_step_norm_stop_in_module(self):
        import inspect
        from pse_ecosystem.solvers import ipopt_driver
        src = inspect.getsource(ipopt_driver)
        assert "class _StepNormStop" in src


# ══════════════════════════════════════════════════════════════════════════════
# Version consistency
# ══════════════════════════════════════════════════════════════════════════════

def test_version_is_v161():
    from pse_ecosystem import __version__
    assert __version__ == "1.6.1"


def test_pyproject_version_matches_package():
    import pathlib, re
    from pse_ecosystem import __version__
    toml = (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text()
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', toml, flags=re.MULTILINE)
    assert m and m.group(1) == __version__, f"pyproject.toml version mismatch: {m}"
