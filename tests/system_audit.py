"""
PSE Ecosystem — System Health Audit
=====================================
Self-contained end-to-end proof that the three core features work right now:

    1. The Handshake   — PrimalGuess ↔ LinearizedModel ↔ UnitResponse protocol
    2. The SLP Loop    — convergence on non-linear units, short-circuit on linear ones
    3. The Hydrogen Theme — electrolysis and gasification routes meet demand profiles

Run with the project venv::

    python tests/system_audit.py [--verbose]

No pytest required.  Exit 0 = all green.  Exit 1 = one or more failures.
"""

from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

# Force UTF-8 output so box-drawing chars survive Windows cp1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


# ── Minimal test harness ──────────────────────────────────────────────────────

@dataclass
class _Result:
    name: str
    passed: bool
    skipped: bool = False
    elapsed_s: float = 0.0
    detail: str = ""
    traceback: str = ""


_registry: List[tuple] = []
_results: List[_Result] = []


def test(name: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _registry.append((name, fn))
        return fn
    return decorator


class _Skip(Exception):
    pass


def skip(reason: str) -> None:
    raise _Skip(reason)


def assert_approx(a: float, b: float, label: str, atol: float = 1e-3) -> None:
    if abs(a - b) > atol:
        raise AssertionError(
            f"{label}: expected ≈{b:.6g}, got {a:.6g}  (|diff|={abs(a - b):.3g} > {atol})"
        )


def run_all() -> None:
    for name, fn in _registry:
        t0 = time.perf_counter()
        try:
            detail = fn() or ""
            _results.append(_Result(name=name, passed=True,
                                    elapsed_s=time.perf_counter() - t0,
                                    detail=str(detail)))
        except _Skip as exc:
            _results.append(_Result(name=name, passed=False, skipped=True,
                                    elapsed_s=time.perf_counter() - t0,
                                    detail=str(exc)))
        except AssertionError as exc:
            _results.append(_Result(name=name, passed=False,
                                    elapsed_s=time.perf_counter() - t0,
                                    detail=str(exc),
                                    traceback=traceback.format_exc()))
        except Exception as exc:
            _results.append(_Result(name=name, passed=False,
                                    elapsed_s=time.perf_counter() - t0,
                                    detail=f"{type(exc).__name__}: {exc}",
                                    traceback=traceback.format_exc()))


def print_report() -> None:
    W = 72
    print()
    print("=" * W)
    print("  PSE ECOSYSTEM  —  HEALTH REPORT")
    print("=" * W)

    # Group by feature (everything before the first "/")
    features: dict[str, list[_Result]] = {}
    for r in _results:
        group = r.name.split("/")[0].strip()
        features.setdefault(group, []).append(r)

    total = len(_results)
    passed = sum(1 for r in _results if r.passed)
    skipped = sum(1 for r in _results if r.skipped)
    failed = total - passed - skipped

    for group, results in features.items():
        print(f"\n  +-- {group}")
        for r in results:
            label = r.name.split("/", 1)[1].strip() if "/" in r.name else r.name
            badge = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
            ms = f"{r.elapsed_s * 1000:.0f}ms"
            print(f"  |  [{badge}] {label:<44} {ms:>6}")
            if r.detail:
                print(f"  |         {r.detail}")
            if not r.passed and not r.skipped and VERBOSE and r.traceback:
                for line in r.traceback.splitlines():
                    print(f"  |         | {line}")
        print("  +" + "-" * (W - 3))

    print()
    verdict = "ALL CLEAR" if failed == 0 else f"  *** {failed} FAILURE(S) ***"
    print(f"  Result: {passed}/{total} passed  |  {skipped} skipped  |  {verdict}")
    print("=" * W)
    print()
    sys.exit(0 if failed == 0 else 1)


# =============================================================================
# ── Feature 1: The Handshake ──────────────────────────────────────────────────
# =============================================================================

@test("The Handshake / PEM: PrimalGuess → LinearizedModel (is_exact=True)")
def _():
    from pse_ecosystem.core.contracts import PrimalGuess
    from pse_ecosystem.models.electrolysis.pem_toy import PEMToy

    pem = PEMToy("pem")
    # Consistent point: h2 = eta * electricity = 0.018 * 5000 = 90
    guess = PrimalGuess(
        values={"pem.electricity_kW": 5000.0, "pem.h2_kg_per_h": 90.0},
        iteration=0,
    )
    lin = pem.linearize(guess)

    assert lin.is_exact, "PEM must advertise is_exact=True"
    assert lin.J.shape == (1, 2), f"J shape wrong: {lin.J.shape}"
    assert lin.f0.shape == (1,), f"f0 shape wrong: {lin.f0.shape}"
    # At consistent point f0 = h2 - eta*elec = 0
    assert_approx(lin.f0[0], 0.0, "f0 at consistent point", atol=1e-9)
    # predicted_residual at x0 must equal f0
    pred = lin.predicted_residual({"pem.electricity_kW": 5000.0, "pem.h2_kg_per_h": 90.0})
    assert_approx(pred[0], lin.f0[0], "predicted_residual(x0) == f0", atol=1e-9)
    return f"J=[{lin.J[0,0]:.4g}, {lin.J[0,1]:.4g}]  f0={lin.f0[0]:.3g}  is_exact={lin.is_exact}"


@test("The Handshake / Gasifier: PrimalGuess → LinearizedModel (is_exact=False)")
def _():
    from pse_ecosystem.core.contracts import PrimalGuess
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy

    gas = GasifierToy("gasifier")
    a, b, c = gas.params.a, gas.params.b, gas.params.c
    feed0 = 2000.0
    h2_0 = a * feed0 - b * feed0 ** 2   # consistent: 199.6
    steam0 = c * feed0                   # consistent: 1000.0

    guess = PrimalGuess(
        values={
            "gasifier.feed_kg_per_h": feed0,
            "gasifier.h2_kg_per_h": h2_0,
            "gasifier.steam_kg_per_h": steam0,
        },
        iteration=0,
    )
    lin = gas.linearize(guess)

    assert not lin.is_exact, "Gasifier must advertise is_exact=False"
    assert lin.J.shape == (2, 3), f"J shape wrong: {lin.J.shape}"
    assert lin.trust_region == 5000.0, f"Trust region wrong: {lin.trust_region}"
    # f0 at consistent point = 0 for both residuals
    assert_approx(lin.f0[0], 0.0, "residual[0] at consistent point", atol=1e-6)
    assert_approx(lin.f0[1], 0.0, "residual[1] at consistent point", atol=1e-6)
    # Analytical Jacobian row 0: [-a+2b*feed, 1, 0]
    expected_J00 = -a + 2.0 * b * feed0
    assert_approx(lin.J[0, 0], expected_J00, "J[0,0]", atol=1e-8)
    assert_approx(lin.J[0, 1], 1.0, "J[0,1]", atol=1e-8)
    assert_approx(lin.J[1, 0], -c, "J[1,0]", atol=1e-8)
    return f"J[0]=[{lin.J[0,0]:.4g}, {lin.J[0,1]:.4g}, {lin.J[0,2]:.4g}]  trust_region={lin.trust_region}"


@test("The Handshake / BaseUnit.evaluate() returns correct UnitResponse")
def _():
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy

    gas = GasifierToy("gasifier")
    a, b, c = gas.params.a, gas.params.b, gas.params.c
    feed = 3000.0
    x = {
        "gasifier.feed_kg_per_h": feed,
        "gasifier.h2_kg_per_h": 300.0,   # intentionally off-physics
        "gasifier.steam_kg_per_h": 1500.0,
    }
    resp = gas.evaluate(x)

    assert resp.unit_id == "gasifier"
    assert resp.residual.shape == (2,)
    # Residual[0] = h2 - (a*feed - b*feed²)
    expected_r0 = 300.0 - (a * feed - b * feed ** 2)
    assert_approx(resp.residual[0], expected_r0, "residual[0]", atol=1e-6)
    # Residual[1] = steam - c*feed = 1500 - 0.5*3000 = 0
    assert_approx(resp.residual[1], 0.0, "residual[1]", atol=1e-6)
    assert isinstance(resp.kpis, dict)
    assert "gasifier.LCOH_GBP_per_kg" in resp.kpis
    return f"residual={resp.residual}  feasible={resp.feasible}"


@test("The Handshake / Layer boundary: solvers/ contains no concrete unit imports")
def _():
    import pse_ecosystem.solvers as solvers_pkg

    forbidden = (
        "pse_ecosystem.models.electrolysis",
        "pse_ecosystem.models.gasification",
    )
    offenders = []
    solvers_dir = Path(solvers_pkg.__file__).parent
    solver_files = list(solvers_dir.glob("*.py"))
    for py_file in solver_files:
        text = py_file.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern in text:
                offenders.append(f"{py_file.name} → {pattern}")

    assert not offenders, f"Layer boundary violated:\n  " + "\n  ".join(offenders)
    return f"Scanned {len(solver_files)} solver files — boundary clean"


# =============================================================================
# ── Feature 2: The SLP Loop ───────────────────────────────────────────────────
# =============================================================================

def _require_lp_solver():
    from pse_ecosystem.solvers.lp_builder import select_lp_solver
    try:
        return select_lp_solver()
    except RuntimeError as exc:
        skip(f"No LP solver available ({exc})")


def _require_milp_solver():
    from pse_ecosystem.solvers.milp_builder import select_milp_solver
    try:
        return select_milp_solver()
    except RuntimeError as exc:
        skip(f"No MILP solver available ({exc})")


@test("SLP Loop / Linear short-circuit: PEM flowsheet converges in 1 iteration")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    demand = 120.0
    flowsheet = make_electrolysis_only(h2_demand_kg_per_h=demand)
    result = Orchestrator(flowsheet=flowsheet, mode=SolveMode.FIXED_LP).solve()

    assert result.status == SolverStatus.CONVERGED, f"Status: {result.status}"
    assert result.iterations == 1, (
        f"Linear flowsheet must short-circuit to 1 LP solve, got {result.iterations}"
    )
    h2 = result.x["pem.h2_kg_per_h"]
    assert_approx(h2, demand, "h2 meets demand", atol=1e-4)
    return f"iterations={result.iterations}  h2={h2:.4g} kg/h  (demand={demand})"


@test("SLP Loop / Iterative: gasifier forces multiple SLP iterations")
def _():
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    _require_lp_solver()
    demand = 200.0
    gas = GasifierToy("gasifier")
    flowsheet = BaseFlowsheet(
        name="gasifier_only", units=[gas], connections=[], objective_kpi="annual_cost"
    )
    flowsheet.extra_equalities.append(({gas.v_h2: 1.0}, demand))

    cfg = SLPConfig(max_iter=25, eps_x=1e-5, eps_f=1e-4, eps_kpi=1e-4, verbose=VERBOSE)
    result = SLPDriver(flowsheet, cfg).run()

    assert result.status == SolverStatus.CONVERGED, f"SLP did not converge: {result.message}"
    assert result.iterations >= 2, (
        f"Gasifier is non-linear — must iterate, got {result.iterations}"
    )
    assert result.iterations <= 15, f"Too many SLP iterations: {result.iterations}"

    # Physics check: h2 = a·feed - b·feed²
    feed = result.x[gas.v_feed]
    h2 = result.x[gas.v_h2]
    expected = gas.params.a * feed - gas.params.b * feed ** 2
    assert_approx(h2, expected, "physics residual: h2 = a·feed - b·feed²", atol=1e-3)
    assert_approx(h2, demand, "h2 meets demand", atol=1e-3)
    return f"iterations={result.iterations}  feed={feed:.1f} kg/h  h2={h2:.3f} kg/h"


@test("SLP Loop / Convergence history is populated with correct keys")
def _():
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    _require_lp_solver()
    gas = GasifierToy("g")
    flowsheet = BaseFlowsheet(name="t", units=[gas], connections=[], objective_kpi="annual_cost")
    flowsheet.extra_equalities.append(({gas.v_h2: 1.0}, 150.0))

    result = SLPDriver(flowsheet, SLPConfig(max_iter=25)).run()
    assert result.status == SolverStatus.CONVERGED

    assert len(result.history) > 0, "Iterative solve must populate history"
    required_keys = {"iteration", "objective", "step_norm", "residual_norm", "kpi"}
    missing = required_keys - result.history[0].keys()
    assert not missing, f"History entry missing keys: {missing}"

    # Residual norm should monotonically decrease (roughly) over the run
    norms = [h["residual_norm"] for h in result.history]
    assert norms[-1] < norms[0] + 1.0, "Residual norm must decrease over SLP iterations"
    return f"{len(result.history)} history entries  residual: {norms[0]:.3g} → {norms[-1]:.3g}"


@test("SLP Loop / Convergence from a deliberately bad initial guess")
def _():
    """Start far from the solution to prove the SLP loop actually navigates there."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    _require_lp_solver()
    demand = 300.0
    gas = GasifierToy("gasifier")
    flowsheet = BaseFlowsheet(name="bad_guess", units=[gas], connections=[], objective_kpi="annual_cost")
    flowsheet.extra_equalities.append(({gas.v_h2: 1.0}, demand))

    # Start at the maximum: feed=50000, h2=5000, steam=25000 — far from optimum
    x_bad = {
        gas.v_feed: 45_000.0,
        gas.v_h2: 4_500.0,
        gas.v_steam: 22_500.0,
    }
    cfg = SLPConfig(max_iter=30, eps_x=1e-5, eps_f=1e-4, eps_kpi=1e-4, verbose=VERBOSE)
    result = SLPDriver(flowsheet, cfg).run(x0=x_bad)

    assert result.status == SolverStatus.CONVERGED, (
        f"SLP failed to recover from bad initial guess: {result.message}"
    )
    h2 = result.x[gas.v_h2]
    assert_approx(h2, demand, "h2 meets demand from bad start", atol=0.01)
    return f"Converged in {result.iterations} iter from far-off start  h2={h2:.3f} kg/h"


# =============================================================================
# ── Feature 3: Hydrogen Theme — Electrolysis Route ────────────────────────────
# =============================================================================

@test("Hydrogen Theme / Electrolysis: demand profile [50, 100, 170] kg/h")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    summary = []
    for demand in [50.0, 100.0, 170.0]:
        flowsheet = make_electrolysis_only(h2_demand_kg_per_h=demand)
        result = Orchestrator(flowsheet=flowsheet, mode=SolveMode.FIXED_LP).solve()
        assert result.status == SolverStatus.CONVERGED, (
            f"demand={demand}: expected CONVERGED, got {result.status}"
        )
        h2 = result.x["pem.h2_kg_per_h"]
        assert_approx(h2, demand, f"demand={demand}", atol=1e-4)
        lcoh = result.kpis.get("pem.LCOH_GBP_per_kg", float("nan"))
        summary.append(f"{demand:.0f}→{lcoh:.3f}")
    return "LCOH £/kg: " + "  ".join(summary)


@test("Hydrogen Theme / Electrolysis: LCOH decreases with increasing throughput")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    lcoh_vals = []
    for demand in [50.0, 100.0, 150.0]:
        flowsheet = make_electrolysis_only(h2_demand_kg_per_h=demand)
        result = Orchestrator(flowsheet=flowsheet, mode=SolveMode.FIXED_LP).solve()
        assert result.status == SolverStatus.CONVERGED
        lcoh_vals.append(result.kpis["pem.LCOH_GBP_per_kg"])

    # Fixed CAPEX amortises over more kg at higher output → LCOH falls
    assert lcoh_vals[0] > lcoh_vals[1] > lcoh_vals[2], (
        f"LCOH should fall with scale, got {lcoh_vals}"
    )
    return f"[50,100,150] kg/h → LCOH {[f'{v:.3f}' for v in lcoh_vals]} £/kg  ✓ monotone"


@test("Hydrogen Theme / Electrolysis: infeasible demand (>PEM max) is caught")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    # PEM max h2 = eta * capacity = 0.018 * 10000 = 180 kg/h
    demand = 250.0
    flowsheet = make_electrolysis_only(h2_demand_kg_per_h=demand)
    result = Orchestrator(flowsheet=flowsheet, mode=SolveMode.FIXED_LP).solve()

    assert result.status == SolverStatus.INFEASIBLE, (
        f"Expected INFEASIBLE for demand={demand} kg/h (PEM max=180), got {result.status}"
    )
    return f"demand={demand} kg/h correctly returned status={result.status.value}"


@test("Hydrogen Theme / Electrolysis: η (efficiency) verified in solution")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    result = Orchestrator(
        flowsheet=make_electrolysis_only(h2_demand_kg_per_h=100.0),
        mode=SolveMode.FIXED_LP,
    ).solve()
    assert result.status == SolverStatus.CONVERGED

    h2 = result.x["pem.h2_kg_per_h"]
    elec = result.x["pem.electricity_kW"]
    eta_actual = h2 / elec
    assert_approx(eta_actual, 0.018, "η = h2/electricity", atol=1e-6)

    # KPI chain: annual_h2 = h2 * hours
    annual_h2 = result.kpis["pem.annual_h2_kg"]
    assert_approx(annual_h2, h2 * 8000.0, "annual_h2 = h2_rate × 8000 h/yr", atol=1e-3)
    return f"η={eta_actual:.5f} kg/kWh  annual_h2={annual_h2:.0f} kg"


# =============================================================================
# ── Feature 3: Hydrogen Theme — Gasification Route ───────────────────────────
# =============================================================================

@test("Hydrogen Theme / Gasification: SLP meets 300 kg/h demand")
def _():
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    _require_lp_solver()
    demand = 300.0
    gas = GasifierToy("gasifier")
    flowsheet = BaseFlowsheet(
        name="gasifier_standalone", units=[gas], connections=[], objective_kpi="annual_cost"
    )
    flowsheet.extra_equalities.append(({gas.v_h2: 1.0}, demand))

    result = SLPDriver(flowsheet, SLPConfig(max_iter=30, eps_x=1e-5, eps_f=1e-4)).run()
    assert result.status == SolverStatus.CONVERGED, f"{result.status}: {result.message}"

    h2 = result.x[gas.v_h2]
    assert_approx(h2, demand, "h2 meets demand", atol=0.01)

    feed = result.x[gas.v_feed]
    steam = result.x[gas.v_steam]
    # Steam balance must hold: steam = c * feed
    assert_approx(steam, gas.params.c * feed, "steam = c·feed", atol=1e-3)
    # Physics residual
    expected_h2 = gas.params.a * feed - gas.params.b * feed ** 2
    assert_approx(h2, expected_h2, "h2 = a·feed - b·feed²", atol=1e-3)

    lcoh = result.kpis.get("gasifier.LCOH_GBP_per_kg", float("nan"))
    return (
        f"iterations={result.iterations}  feed={feed:.1f} kg/h  "
        f"h2={h2:.2f} kg/h  LCOH={lcoh:.3f} £/kg"
    )


@test("Hydrogen Theme / Mode 2: MILP selects technology for demand=80 kg/h")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
        make_electrolysis_or_gasification,
    )
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    _require_milp_solver()

    demand = 80.0
    flowsheet, choices = make_electrolysis_or_gasification(h2_demand_kg_per_h=demand)
    result = Orchestrator(
        flowsheet=flowsheet,
        mode=SolveMode.FLEXIBLE_MILP,
        technology_choices=choices,
    ).solve()

    assert result.status == SolverStatus.CONVERGED, f"{result.status}: {result.message}"
    assert any(result.technology_selection.values()), (
        f"No technology selected: {result.technology_selection}"
    )
    total_h2 = (
        result.x.get("pem.h2_kg_per_h", 0.0)
        + result.x.get("gasifier.h2_kg_per_h", 0.0)
    )
    assert_approx(total_h2, demand, "total H2 meets demand", atol=0.01)
    chosen = [k for k, v in result.technology_selection.items() if v]
    return f"chose={chosen}  total_h2={total_h2:.3f} kg/h"


@test("Hydrogen Theme / Mode 2: gasifier forced on when demand exceeds PEM capacity")
def _():
    """PEM max = 0.018 × 10 000 = 180 kg/h.  Demand 200 kg/h → gasifier must activate."""
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
        make_electrolysis_or_gasification,
    )
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    _require_milp_solver()

    demand = 200.0  # > PEM max of 180 kg/h
    flowsheet, choices = make_electrolysis_or_gasification(h2_demand_kg_per_h=demand)
    result = Orchestrator(
        flowsheet=flowsheet,
        mode=SolveMode.FLEXIBLE_MILP,
        technology_choices=choices,
    ).solve()

    assert result.status == SolverStatus.CONVERGED, f"{result.status}: {result.message}"
    assert result.technology_selection.get("pick_gasifier", False), (
        f"Gasifier must activate when demand ({demand}) > PEM max (180): "
        f"{result.technology_selection}"
    )
    total_h2 = (
        result.x.get("pem.h2_kg_per_h", 0.0)
        + result.x.get("gasifier.h2_kg_per_h", 0.0)
    )
    assert_approx(total_h2, demand, "total H2 at supra-PEM demand", atol=0.05)
    return (
        f"selection={result.technology_selection}  "
        f"pem_h2={result.x.get('pem.h2_kg_per_h', 0.0):.2f}  "
        f"gas_h2={result.x.get('gasifier.h2_kg_per_h', 0.0):.2f} kg/h"
    )


# =============================================================================
# ── KPI Sanity ────────────────────────────────────────────────────────────────
# =============================================================================

@test("KPI Sanity / PEM LCOH is within plausible range (£/kg H2)")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.orchestrator import Orchestrator

    _require_lp_solver()
    result = Orchestrator(
        flowsheet=make_electrolysis_only(h2_demand_kg_per_h=100.0),
        mode=SolveMode.FIXED_LP,
    ).solve()
    assert result.status == SolverStatus.CONVERGED

    lcoh = result.kpis["pem.LCOH_GBP_per_kg"]
    annual_h2 = result.kpis["pem.annual_h2_kg"]
    annual_opex = result.kpis["pem.annual_opex_GBP"]
    annual_capex = result.kpis["pem.annual_capex_GBP"]

    assert 0.0 < lcoh < 200.0, f"LCOH={lcoh:.4g} is outside plausible range"
    assert annual_h2 > 0.0, "annual_h2 must be positive"
    assert annual_opex > 0.0, "annual_opex must be positive"
    assert annual_capex > 0.0, "annual_capex must be positive"
    # Cross-check: LCOH ≈ (capex + opex) / annual_h2
    lcoh_check = (annual_capex + annual_opex) / annual_h2
    assert_approx(lcoh, lcoh_check, "LCOH = (CAPEX+OPEX)/annual_h2", atol=1e-4)
    return (
        f"LCOH={lcoh:.4f} £/kg  capex={annual_capex:.0f}  "
        f"opex={annual_opex:.0f}  annual_h2={annual_h2:.0f} kg"
    )


@test("KPI Sanity / PEM vs Gasifier LCOH at same 100 kg/h demand")
def _():
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    _require_lp_solver()
    demand = 100.0

    pem_result = Orchestrator(
        flowsheet=make_electrolysis_only(h2_demand_kg_per_h=demand),
        mode=SolveMode.FIXED_LP,
    ).solve()
    assert pem_result.status == SolverStatus.CONVERGED
    pem_lcoh = pem_result.kpis["pem.LCOH_GBP_per_kg"]

    gas = GasifierToy("gasifier")
    fs = BaseFlowsheet(name="gas_kpi", units=[gas], connections=[], objective_kpi="annual_cost")
    fs.extra_equalities.append(({gas.v_h2: 1.0}, demand))
    gas_result = SLPDriver(fs, SLPConfig(max_iter=25)).run()
    assert gas_result.status == SolverStatus.CONVERGED
    gas_lcoh = gas_result.kpis["gasifier.LCOH_GBP_per_kg"]

    # Both must be finite and positive
    assert 0.0 < pem_lcoh < 500.0, f"PEM LCOH out of range: {pem_lcoh}"
    assert 0.0 < gas_lcoh < 500.0, f"Gasifier LCOH out of range: {gas_lcoh}"
    return (
        f"PEM={pem_lcoh:.3f} £/kg  vs  Gasifier={gas_lcoh:.3f} £/kg  "
        f"at {demand} kg/h"
    )


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    print()
    print("  Auditing PSE Ecosystem — running all checks...")
    print()
    run_all()
    print_report()
