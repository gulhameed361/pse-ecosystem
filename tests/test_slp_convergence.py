"""End-to-end SLP convergence checks + layer-boundary enforcement."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import pse_ecosystem.solvers as solvers_pkg
from pse_ecosystem.core.contracts import SolveMode, SolverStatus
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
    make_electrolysis_only,
    make_electrolysis_or_gasification,
)
from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
from pse_ecosystem.solvers.lp_builder import select_lp_solver
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver


@pytest.fixture(scope="module")
def lp_solver():
    try:
        return select_lp_solver()
    except RuntimeError as exc:
        pytest.skip(f"No LP solver available: {exc}")


def test_mode1_pem_short_circuits_to_single_lp(lp_solver):
    """A flowsheet of only-linear units must converge in exactly one iteration."""
    flowsheet = make_electrolysis_only(h2_demand_kg_per_h=120.0)
    orch = Orchestrator(flowsheet=flowsheet, mode=SolveMode.FIXED_LP)
    result = orch.solve()

    assert result.status == SolverStatus.CONVERGED
    assert result.iterations == 1
    assert result.x["pem.h2_kg_per_h"] == pytest.approx(120.0, abs=1e-6)


def test_slp_converges_on_nonlinear_gasifier(lp_solver):
    """SLP on the toy gasifier converges within a small number of iterations."""
    gas = GasifierToy(unit_id="gasifier")
    flowsheet = BaseFlowsheet(
        name="gasifier_only",
        units=[gas],
        connections=[],
        objective_kpi="annual_cost",
    )
    flowsheet.extra_equalities.append(
        ({gas.v_h2: 1.0}, 200.0)  # demand = 200 kg/h
    )

    cfg = SLPConfig(max_iter=20, eps_x=1e-5, eps_f=1e-4, eps_kpi=1e-4)
    driver = SLPDriver(flowsheet, cfg)
    result = driver.run()

    assert result.status == SolverStatus.CONVERGED
    assert result.iterations <= 10
    # Validate that h2 ≈ a·feed - b·feed² holds at the converged point.
    feed = result.x[gas.v_feed]
    h2 = result.x[gas.v_h2]
    expected_h2 = gas.params.a * feed - gas.params.b * feed * feed
    assert h2 == pytest.approx(expected_h2, abs=1e-3)


def test_mode2_milp_picks_a_technology(lp_solver):
    """The MILP must pick at least one technology and meet demand."""
    pytest.importorskip("pyomo")
    try:
        from pse_ecosystem.solvers.milp_builder import select_milp_solver
        select_milp_solver()
    except RuntimeError as exc:
        pytest.skip(f"No MILP solver available: {exc}")

    flowsheet, choices = make_electrolysis_or_gasification(h2_demand_kg_per_h=80.0)
    orch = Orchestrator(
        flowsheet=flowsheet,
        mode=SolveMode.FLEXIBLE_MILP,
        technology_choices=choices,
    )
    result = orch.solve()

    assert result.status == SolverStatus.CONVERGED
    assert any(result.technology_selection.values())
    total_h2 = result.x.get("pem.h2_kg_per_h", 0.0) + result.x.get(
        "gasifier.h2_kg_per_h", 0.0
    )
    assert total_h2 == pytest.approx(80.0, abs=1e-3)


# ── Architectural boundary check ──────────────────────────────────────────────


_FORBIDDEN_IMPORTS = (
    "pse_ecosystem.models.electrolysis",
    "pse_ecosystem.models.gasification",
    "pse_ecosystem.models.reactors",
    "pse_ecosystem.models.separators",
    "pse_ecosystem.models.heat_exchangers",
    "pse_ecosystem.models.pressure_changers",
    "pse_ecosystem.models.mixers",
    "pse_ecosystem.models.costing",
    "pse_ecosystem.models.properties",
)


def test_solvers_do_not_import_concrete_unit_modules():
    """Layer 2 (solvers/) must talk to units only through the abstract contract.

    Direct imports of any concrete unit module from inside ``solvers/`` would
    break the layer boundary, so we scan the source for forbidden import
    statements. (Transitive imports of the abstract :class:`BaseUnit` via the
    flowsheet container are intentionally allowed — that's part of the
    contract surface.)
    """
    solvers_dir = Path(solvers_pkg.__file__).parent
    offenders = []
    for py_file in solvers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_IMPORTS:
            if forbidden in text:
                offenders.append(f"{py_file.name} imports {forbidden}")
    assert not offenders, "Layer-boundary violation:\n  " + "\n  ".join(offenders)
