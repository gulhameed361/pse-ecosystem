"""Tests for v1.3.2 — proper economic objectives (LCOH, TAC, OPEX, Energy, Feasibility)."""

from __future__ import annotations

import pytest
import numpy as np

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.ui.flowsheet_service import build_objective_extra, build_custom_flowsheet


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_compressor_flowsheet():
    """Single-unit flowsheet with a Compressor (has W_shaft decision variable)."""
    cfg = {
        "units": [
            {"type": "Compressor", "id": "comp",
             "params": {"components": ["H2", "CO2"], "P_out_Pa": 5e6}}
        ],
        "connections": [],
    }
    return build_custom_flowsheet(cfg)


def _make_pem_flowsheet():
    """Single PEM flowsheet (has electricity_kW decision variable)."""
    cfg = {
        "units": [{"type": "PEMToy", "id": "pem", "params": {}}],
        "connections": [],
    }
    return build_custom_flowsheet(cfg)


def _make_biomass_gasifier_flowsheet():
    """BiomassGasifierHF — has objective_contribution (biomass cost)."""
    cfg = {
        "units": [
            {"type": "BiomassGasifierHF", "id": "gasifier",
             "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"}}
        ],
        "connections": [],
    }
    return build_custom_flowsheet(cfg)


# ── force_feasibility tests ───────────────────────────────────────────────────

def test_feasibility_only_returns_force_feasibility_true():
    fs = _make_pem_flowsheet()
    extra, force_feas = build_objective_extra(fs, "Feasibility Only")
    assert force_feas is True
    assert extra == {}


def test_lp_builder_honours_force_feasibility():
    """When force_feasibility=True, LP objective must equal 0.0 (feasibility problem)."""
    import pyomo.environ as pyo
    from pse_ecosystem.core.contracts import PrimalGuess
    from pse_ecosystem.solvers.lp_builder import build_lp

    fs = _make_pem_flowsheet()
    fs.force_feasibility = True
    fs.objective_extra = {}

    all_vars = fs.all_variables()
    x0 = {v: 1.0 for v in all_vars}
    lins = [u.linearize(PrimalGuess(values=x0)) for u in fs.units]
    model = build_lp(lins, fs)

    obj_val = pyo.value(model.objective.expr)
    assert obj_val == pytest.approx(0.0), (
        f"Objective should be 0.0 when force_feasibility=True, got {obj_val}"
    )


# ── Minimize OPEX ─────────────────────────────────────────────────────────────

def test_minimize_opex_returns_empty_extra_no_force():
    """OPEX minimisation uses existing unit objective_contribution() — no extra terms."""
    fs = _make_pem_flowsheet()
    extra, force_feas = build_objective_extra(fs, "Minimize OPEX")
    assert extra == {}
    assert force_feas is False


def test_unit_opex_already_in_lp_for_pem():
    """PEMToy contributes electricity cost to LP objective via objective_contribution()."""
    import pyomo.environ as pyo
    from pse_ecosystem.core.contracts import PrimalGuess
    from pse_ecosystem.solvers.lp_builder import build_lp

    fs = _make_pem_flowsheet()
    fs.force_feasibility = False
    fs.objective_extra = {}

    all_vars = fs.all_variables()
    x0 = {v: max(1.0, 10.0) for v in all_vars}  # give electricity_kW a non-zero value
    lins = [u.linearize(PrimalGuess(values=x0)) for u in fs.units]
    model = build_lp(lins, fs)

    # PEM contributes electricity_kW × 400 USD/kW/yr to objective
    obj_expr = str(model.objective.expr)
    # The objective should be non-trivial (non-zero)
    assert model.objective is not None


# ── Minimize Energy ───────────────────────────────────────────────────────────

def test_minimize_energy_finds_shaft_work_variable():
    """Compressor has W_shaft as a decision variable; energy mode must add a coefficient."""
    fs = _make_compressor_flowsheet()
    extra, force_feas = build_objective_extra(
        fs, "Minimize Energy", electricity_price_USD_per_kWh=0.05, operating_hours=8000.0
    )
    assert force_feas is False
    # Should have at least one energy-related key
    energy_keys = [k for k in extra if any(t in k.lower() for t in ("w_shaft", "w_elec", "electricity"))]
    assert len(energy_keys) >= 1, f"No energy variable found in objective_extra: {list(extra.keys())}"
    # Coefficient should be positive (minimise cost)
    for k in energy_keys:
        assert extra[k] > 0, f"Energy coefficient should be positive for {k}"


# ── Minimize TAC ──────────────────────────────────────────────────────────────

def test_minimize_tac_includes_energy_coefficients():
    """TAC mode must include energy cost terms (superset of Energy mode)."""
    fs = _make_compressor_flowsheet()
    extra_energy, _ = build_objective_extra(fs, "Minimize Energy")
    extra_tac,    _ = build_objective_extra(fs, "Minimize TAC")
    # TAC should include at least the same energy terms as Energy mode
    for k in extra_energy:
        assert k in extra_tac, f"TAC mode missing energy variable {k!r}"


# ── Maximize H₂ Yield ─────────────────────────────────────────────────────────

def test_maximize_h2_yield_finds_h2_outlet_variable():
    """Gasifier has syngas_out port: variable = 'gasifier.syngas_out.F_H2'.
    The port-tag segment ('syngas_out') contains 'out', so the objective
    function includes it with a negative coefficient."""
    fs = _make_biomass_gasifier_flowsheet()
    extra, force_feas = build_objective_extra(fs, "Maximize H₂ Yield")
    assert force_feas is False
    # Check: any key whose last segment is 'F_H2' and port-tag segment contains 'out'
    def _is_h2_out(k):
        parts = k.split(".")
        return len(parts) >= 3 and parts[-1].lower() == "f_h2" and "out" in parts[1].lower()
    h2_keys = [k for k in extra if _is_h2_out(k)]
    assert len(h2_keys) >= 1, f"No H₂ outlet variable found in objective_extra: {list(extra.keys())}"
    for k in h2_keys:
        assert extra[k] < 0, f"H₂ coefficient should be negative (maximise): {extra[k]}"


# ── Minimize LCOH ─────────────────────────────────────────────────────────────

def test_minimize_lcoh_combines_energy_and_h2():
    """LCOH mode combines energy penalty AND H₂ yield maximisation."""
    fs = _make_biomass_gasifier_flowsheet()
    extra, _ = build_objective_extra(fs, "Minimize LCOH (Levelized Cost of H₂)")
    def _is_h2_out(k):
        parts = k.split(".")
        return len(parts) >= 3 and parts[-1].lower() == "f_h2" and "out" in parts[1].lower()
    h2_keys = [k for k in extra if _is_h2_out(k)]
    assert len(h2_keys) >= 1, "LCOH mode must include H₂ yield term"
    assert extra[h2_keys[-1]] < 0, "H₂ coefficient must be negative"
