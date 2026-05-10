"""
PSE Ecosystem — UI ↔ Backend Sync Audit
========================================
Verifies that UI-supplied parameters produce mathematically correct solver
outputs.  Each check loads a template via the service bridge (as the UI
would), runs the solve, and asserts specific numerical relationships.

Run with the project venv::

    python tests/ui_backend_sync.py [--verbose]

No pytest required.  Exit 0 = all green.  Exit 1 = one or more failures.
"""

from __future__ import annotations

import math
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

import numpy as np

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


# ── Test harness ──────────────────────────────────────────────────────────────

@dataclass
class _Result:
    name: str
    passed: bool
    skipped: bool = False
    elapsed_s: float = 0.0
    detail: str = ""
    tb: str = ""


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


def approx(a: float, b: float, label: str, rtol: float = 1e-3) -> None:
    if abs(a - b) > rtol * max(abs(b), 1e-12):
        raise AssertionError(
            f"{label}: expected {b:.6g}, got {a:.6g}  "
            f"(|rel err| = {abs(a - b) / max(abs(b), 1e-12):.3g} > {rtol})"
        )


def run_all() -> None:
    for name, fn in _registry:
        t0 = time.perf_counter()
        try:
            detail = fn() or ""
            _results.append(_Result(
                name=name, passed=True,
                elapsed_s=time.perf_counter() - t0, detail=str(detail)
            ))
        except _Skip as exc:
            _results.append(_Result(
                name=name, passed=True, skipped=True,
                elapsed_s=time.perf_counter() - t0, detail=str(exc)
            ))
        except Exception as exc:
            _results.append(_Result(
                name=name, passed=False,
                elapsed_s=time.perf_counter() - t0,
                detail=str(exc),
                tb=traceback.format_exc() if VERBOSE else "",
            ))


def print_report() -> int:
    pass_n = sum(1 for r in _results if r.passed and not r.skipped)
    skip_n = sum(1 for r in _results if r.skipped)
    fail_n = sum(1 for r in _results if not r.passed)
    total  = len(_results)

    print("\n" + "=" * 60)
    print("PSE Ecosystem — UI Backend Sync Audit")
    print("=" * 60)
    for r in _results:
        icon = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        ms   = f"{r.elapsed_s * 1000:.0f}ms"
        print(f"  [{icon}] {r.name}  ({ms})")
        if r.detail and (VERBOSE or not r.passed):
            for line in r.detail.splitlines():
                print(f"         {line}")
        if r.tb:
            for line in r.tb.splitlines():
                print(f"         {line}")
    print("-" * 60)
    print(f"  {pass_n} passed  {skip_n} skipped  {fail_n} failed  /  {total} total")
    print("=" * 60)
    return 0 if fail_n == 0 else 1


# ── Helper ────────────────────────────────────────────────────────────────────

def _solve(key: str, params: dict = None, max_iter: int = 60):
    from pse_ecosystem.ui.flowsheet_service import load_template
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus

    fs = load_template(key, params or {})
    r  = Orchestrator(fs, SolveMode.FIXED_LP,
                      slp_config=SLPConfig(max_iter=max_iter, verbose=False)).solve()
    assert r.status == SolverStatus.CONVERGED, (
        f"Template '{key}' did not converge: {r.status} — {r.message}"
    )
    return r


# ── Checks ────────────────────────────────────────────────────────────────────

@test("PEM / demand equality: h2_kg_per_h matches UI input")
def _():
    demand = 120.0
    r = _solve("hydrogen.electrolysis_only", {"h2_demand_kg_per_h": demand})
    h2 = r.x["pem.h2_kg_per_h"]
    approx(h2, demand, "pem.h2_kg_per_h", rtol=1e-4)
    return f"h2={h2:.4f} kg/h (target {demand})"


@test("PEM / LCOH formula: (capex + opex) / annual_h2")
def _():
    params = {
        "h2_demand_kg_per_h": 100.0,
        "pem.electricity_price_per_kWh": 0.05,
        "pem.capex_annual_per_kW": 100.0,
        "pem.capacity_kW": 10_000.0,
        "pem.eta_kg_per_kWh": 0.018,
    }
    r = _solve("hydrogen.electrolysis_only", params)
    kpis = r.kpis
    annual_h2   = kpis["pem.annual_h2_kg"]
    annual_opex = kpis["pem.annual_opex_GBP"]
    annual_capex = kpis["pem.annual_capex_GBP"]
    lcoh_reported = kpis["pem.LCOH_GBP_per_kg"]
    lcoh_expected = (annual_capex + annual_opex) / annual_h2
    approx(lcoh_reported, lcoh_expected, "LCOH formula", rtol=1e-6)
    return f"LCOH={lcoh_reported:.4f} £/kg H2"


@test("PEM / Carbon Intensity: CI = grid_CI * electricity * hours / annual_h2")
def _():
    grid_ci = 0.233
    params = {
        "h2_demand_kg_per_h": 100.0,
        "pem.grid_carbon_intensity_kg_CO2_per_kWh": grid_ci,
        "pem.eta_kg_per_kWh": 0.018,
    }
    r = _solve("hydrogen.electrolysis_only", params)
    kpis = r.kpis
    ci_reported  = kpis["pem.CI_kg_CO2_per_kg_H2"]
    electricity  = r.x["pem.electricity_kW"]
    hours        = 8000.0
    annual_h2    = kpis["pem.annual_h2_kg"]
    ci_expected  = grid_ci * electricity * hours / annual_h2
    approx(ci_reported, ci_expected, "CI formula", rtol=1e-6)
    return f"CI={ci_reported:.4f} kg CO2/kg H2"


@test("P2M / stoichiometry closure: methanol out ≈ CO2 in (mole balance)")
def _():
    r = _solve("industrial.power_to_methanol", {"extent_max": 3.0})
    # CO2 feed is 3 mol/s; stoich says 1 mol CO2 → 1 mol methanol
    # With split fraction 95% liquid: methanol liquid ≈ 0.95 * 3.0 = 2.85 mol/s
    meoh_liquid = r.x.get("sep.outlet_1.F_methanol", float("nan"))
    approx(meoh_liquid, 3.0 * 0.95, "methanol liquid (95% split)", rtol=0.02)
    return f"methanol liquid = {meoh_liquid:.4f} mol/s"


@test("G2P / compressor outlet pressure matches P_out_Pa param")
def _():
    p_target = 500_000.0
    r = _solve("industrial.gasification_to_power", {"comp.P_out_Pa": p_target})
    p_out = r.x.get("comp.outlet.P", float("nan"))
    approx(p_out, p_target, "comp.outlet.P", rtol=1e-4)
    return f"P_out = {p_out:.0f} Pa"


@test("G2P / dry-reforming stoich: CO_out = 2 * extent, H2_out = 2 * extent")
def _():
    extent = 4.0
    r = _solve("industrial.gasification_to_power", {"extent_max": extent})
    co_out = r.x.get("gasifier.outlet.F_CO",  float("nan"))
    h2_out = r.x.get("gasifier.outlet.F_H2",  float("nan"))
    approx(co_out, 2 * extent, "CO_out = 2*xi", rtol=1e-4)
    approx(h2_out, 2 * extent, "H2_out = 2*xi", rtol=1e-4)
    return f"CO={co_out:.2f}, H2={h2_out:.2f} mol/s (xi={extent})"


@test("Syngas / Carbon Intensity is non-NaN and < 1 kg CO2/kg H2")
def _():
    r = _solve("industrial.syngas_production",
               {"h2_demand_kg_per_h": 200.0,
                "gasifier.biomass_carbon_intensity_kg_CO2_per_kg": 0.03})
    ci = r.kpis.get("gasifier.CI_kg_CO2_per_kg_H2", float("nan"))
    assert not math.isnan(ci), "CI is NaN"
    assert ci < 1.0, f"CI = {ci:.3f} ≥ 1.0 (unexpectedly high for biomass)"
    return f"CI = {ci:.4f} kg CO2/kg H2"


@test("Custom / build_custom_flowsheet returns valid BaseFlowsheet")
def _():
    from pse_ecosystem.ui.flowsheet_service import build_custom_flowsheet
    config = {
        "units": [
            {"type": "PEMToy", "id": "pem", "params": {}},
            {"type": "MixerHF", "id": "buf", "params": {"components": ["H2", "H2O"]}},
        ],
        "connections": [
            {"from_unit": "pem", "to_unit": "buf"},
        ],
    }
    fs = build_custom_flowsheet(config)
    assert fs is not None
    assert len(fs.units) == 2
    unit_ids = [u.unit_id for u in fs.units]
    assert "pem" in unit_ids and "buf" in unit_ids
    return f"units={unit_ids}, connections={len(fs.connections)}"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_all()
    sys.exit(print_report())
