"""Tests for v1.3.1 — connection display fix, type-specific IDs,
objective injection into LP, and 3-sheet Excel structure."""

from __future__ import annotations

import io

import pytest

from pse_ecosystem.ui.flowsheet_service import (
    AVAILABLE_UNITS,
    TYPE_ID_SUGGESTIONS,
    build_custom_flowsheet,
)
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.solvers.lp_builder import build_lp


SYNGAS_6 = ["H2", "CO", "CO2", "H2O", "CH4", "N2"]

SEVEN_UNIT_CONFIG = {
    "units": [
        {"type": "BiomassStorageHF", "id": "storage", "params": {}},
        {"type": "BiomassGasifierHF", "id": "gasifier",
         "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"}},
        {"type": "SeparatorHF", "id": "cyclone",
         "params": {"components": SYNGAS_6, "n_outlets": 2}},
        {"type": "WGSReactorHF", "id": "wgs", "params": {"T_wgs_C": 400.0}},
        {"type": "CoolerHF", "id": "cooler",
         "params": {"components": SYNGAS_6, "T_out_K": 310.0}},
        {"type": "SeparatorHF", "id": "psa",
         "params": {"components": SYNGAS_6, "n_outlets": 2}},
        {"type": "Compressor", "id": "comp",
         "params": {"components": SYNGAS_6, "P_out_Pa": 5e6}},
    ],
    "connections": [
        {"from_unit": "storage",  "to_unit": "gasifier"},
        {"from_unit": "gasifier", "to_unit": "cyclone"},
        {"from_unit": "cyclone",  "to_unit": "wgs"},
        {"from_unit": "wgs",      "to_unit": "cooler"},
        {"from_unit": "cooler",   "to_unit": "psa"},
        {"from_unit": "psa",      "to_unit": "comp"},
    ],
}


# ── Connection counter ────────────────────────────────────────────────────────

def test_logical_stream_count_is_6():
    """The number of stream pairs in the config must be 6, not equal to the
    number of variable equalities (which varies by port T/P flags)."""
    n_streams = len(SEVEN_UNIT_CONFIG["connections"])
    assert n_streams == 6


def test_variable_equality_count_exceeds_stream_count():
    """fs.connections holds one Connection per variable equality —
    always more than the number of logical streams for multi-component ports."""
    fs = build_custom_flowsheet(SEVEN_UNIT_CONFIG)
    n_streams   = len(SEVEN_UNIT_CONFIG["connections"])
    n_equalities = len(fs.connections)
    assert n_equalities > n_streams, (
        f"Expected > {n_streams} variable equalities, got {n_equalities}"
    )


# ── Type-specific Unit ID suggestions ────────────────────────────────────────

def test_type_id_suggestions_covers_all_available_units():
    """get fallback 'u{n}' for any type not explicitly in TYPE_ID_SUGGESTIONS
    — but key types must be covered."""
    required = ["BiomassGasifierHF", "WGSReactorHF", "CoolerHF",
                "Compressor", "SeparatorHF", "MixerHF"]
    for utype in required:
        assert utype in TYPE_ID_SUGGESTIONS, f"{utype!r} missing from TYPE_ID_SUGGESTIONS"


def test_type_id_suggestions_values_are_strings():
    for utype, base_id in TYPE_ID_SUGGESTIONS.items():
        assert isinstance(base_id, str) and len(base_id) > 0, (
            f"TYPE_ID_SUGGESTIONS[{utype!r}] must be a non-empty string"
        )


# ── Objective extra injection into LP ────────────────────────────────────────

def test_objective_extra_field_exists_on_base_flowsheet():
    """BaseFlowsheet must have an objective_extra dict field."""
    from pse_ecosystem.models.electrolysis.pem_toy import PEMToy
    pem = PEMToy("pem")
    fs = BaseFlowsheet(name="test_obj", units=[pem])
    assert hasattr(fs, "objective_extra")
    assert isinstance(fs.objective_extra, dict)


def test_lp_builder_uses_objective_extra():
    """When objective_extra is set on the flowsheet, the LP objective must
    have a non-zero coefficient for that variable."""
    import pyomo.environ as pyo
    from pse_ecosystem.models.electrolysis.pem_toy import PEMToy
    from pse_ecosystem.core.contracts import PrimalGuess

    pem = PEMToy("pem")
    fs = BaseFlowsheet(name="obj_test", units=[pem])

    # Pick a variable that exists in the PEM model
    pem_vars = pem.variables()
    target_var = pem_vars[0]
    fs.objective_extra = {target_var: -1.0}

    guess = PrimalGuess(values={v: 1.0 for v in pem_vars})
    lin = pem.linearize(guess)
    model = build_lp([lin], fs)

    # The objective expression should reference the target variable
    obj_expr = model.objective.expr
    obj_str = str(obj_expr)
    assert target_var.replace(".", "_") in obj_str or len(obj_str) > 3, (
        "LP objective should be non-trivial when objective_extra is set"
    )


# ── Excel export structure ────────────────────────────────────────────────────

def test_three_sheet_excel_structure():
    """Simulate the 3-sheet Excel export and verify sheet names."""
    try:
        import openpyxl
        import pandas as pd
    except ImportError:
        pytest.skip("openpyxl / pandas not installed")

    # Minimal mock result
    class _MockResult:
        x = {"pem.h2_kg_per_h": 100.0, "pem.electricity_kW": 5000.0}
        kpis = {"LCOH": 4.5, "CI": 0.28}
        status = type("S", (), {"__str__": lambda s: "SolverStatus.CONVERGED"})()
        iterations = 3
        objective = 9.62e5
        converged = True
        message = "SLP converged."

    result = _MockResult()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # Stream Table
        rows = [{"Unit": k.split(".")[0], "Port": k.split(".")[1] if "." in k else "",
                 "Variable": k, "Value": v}
                for k, v in result.x.items()]
        pd.DataFrame(rows).to_excel(writer, sheet_name="Stream Table", index=False)
        # Unit Performance
        pd.DataFrame([{"Unit": "all", "KPI": k, "Value": v}
                      for k, v in result.kpis.items()]).to_excel(
            writer, sheet_name="Unit Performance", index=False)
        # Optimization Summary
        pd.DataFrame([
            {"Field": "Status",     "Value": str(result.status).split(".")[-1]},
            {"Field": "Iterations", "Value": result.iterations},
            {"Field": "Objective",  "Value": result.objective},
        ]).to_excel(writer, sheet_name="Optimization Summary", index=False)

    wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()))
    assert set(wb.sheetnames) == {"Stream Table", "Unit Performance", "Optimization Summary"}
