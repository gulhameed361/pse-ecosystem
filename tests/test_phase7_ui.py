"""Tests for Phase 7 — UI ergonomics, progressive tightening, and Excel export."""

from __future__ import annotations

import pytest

from pse_ecosystem.ui.flowsheet_service import (
    AVAILABLE_UNITS,
    UNIT_PARAM_SPECS,
    ParamSpec,
    get_unit_param_specs,
)
from pse_ecosystem.solvers.slp import SLPConfig, _tighten


# ── ParamSpec / UNIT_PARAM_SPECS tests ───────────────────────────────────────

def test_unit_param_specs_coverage():
    """Every unit type in AVAILABLE_UNITS is queryable without error."""
    for utype in AVAILABLE_UNITS:
        specs = get_unit_param_specs(utype)
        assert isinstance(specs, list), f"get_unit_param_specs({utype!r}) must return a list"


def test_get_unit_param_specs_biomass_gasifier():
    specs = get_unit_param_specs("BiomassGasifierHF")
    assert len(specs) >= 2
    names = [s.name for s in specs]
    assert "T_gasifier_C" in names
    assert "gasifying_agent" in names


def test_param_spec_defaults_match_dtype():
    """ParamSpec.default must be consistent with the declared dtype."""
    for utype, specs in UNIT_PARAM_SPECS.items():
        for ps in specs:
            if ps.dtype == "float":
                assert isinstance(ps.default, (int, float)), (
                    f"{utype}/{ps.name}: dtype='float' but default={ps.default!r}"
                )
            elif ps.dtype == "int":
                assert isinstance(ps.default, int), (
                    f"{utype}/{ps.name}: dtype='int' but default={ps.default!r}"
                )
            elif ps.dtype == "select":
                assert isinstance(ps.default, str), (
                    f"{utype}/{ps.name}: dtype='select' but default={ps.default!r}"
                )
                assert ps.default in ps.options, (
                    f"{utype}/{ps.name}: default={ps.default!r} not in options={ps.options}"
                )


def test_param_spec_select_has_options():
    for utype, specs in UNIT_PARAM_SPECS.items():
        for ps in specs:
            if ps.dtype == "select":
                assert len(ps.options) >= 2, (
                    f"{utype}/{ps.name}: dtype='select' must have >= 2 options"
                )


# ── Progressive tightening tests ─────────────────────────────────────────────

def test_progressive_tightening_loosens_early():
    cfg = SLPConfig(max_iter=50, eps_x=1e-4, eps_f=1e-4, eps_kpi=1e-3,
                    progressive_tightening=True)
    ex, ef, ekpi = _tighten(cfg, k=0)
    assert ex == pytest.approx(cfg.eps_x * 100)
    assert ef == pytest.approx(cfg.eps_f * 100)
    assert ekpi == pytest.approx(cfg.eps_kpi * 10)


def test_progressive_tightening_intermediate():
    cfg = SLPConfig(max_iter=50, eps_x=1e-4, eps_f=1e-4, eps_kpi=1e-3,
                    progressive_tightening=True)
    ex, ef, ekpi = _tighten(cfg, k=15)  # 30% — phase 2
    assert ex == pytest.approx(cfg.eps_x * 10)
    assert ef == pytest.approx(cfg.eps_f * 10)


def test_progressive_tightening_standard_late():
    cfg = SLPConfig(max_iter=50, eps_x=1e-4, eps_f=1e-4, eps_kpi=1e-3,
                    progressive_tightening=True)
    ex, ef, ekpi = _tighten(cfg, k=49)  # 98% — phase 3
    assert ex == pytest.approx(cfg.eps_x)
    assert ef == pytest.approx(cfg.eps_f)
    assert ekpi == pytest.approx(cfg.eps_kpi)


def test_slp_config_progressive_tightening_default_false():
    cfg = SLPConfig()
    assert cfg.progressive_tightening is False
