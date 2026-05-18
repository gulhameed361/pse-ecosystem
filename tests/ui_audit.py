"""
PSE Ecosystem — UI Audit
=========================
Validates the Layer-1 Streamlit infrastructure introduced in v0.3.0:

    1. flowsheet_service.py imports cleanly without triggering Streamlit
    2. list_templates() returns all expected entries
    3. All industrial + hydrogen templates: load + solve → CONVERGED
    4. KPIs are non-NaN after solve; solution dict is non-empty
    5. Layer boundary: app_streamlit.py contains no direct models.* imports
    6. Layer boundary: flowsheet_service.py not imported by solvers/

Run with the project venv::

    python tests/ui_audit.py [--verbose]

No pytest required.  Exit 0 = all green.  Exit 1 = one or more failures.
"""

from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

import numpy as np

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# Force UTF-8 for box-drawing chars on Windows cp1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


# ── Minimal test harness (same pattern as system_audit.py) ────────────────────

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
    pass_n = sum(1 for r in _results if r.passed)
    skip_n = sum(1 for r in _results if r.skipped)
    fail_n = sum(1 for r in _results if not r.passed)
    total  = len(_results)

    print("\n" + "=" * 60)
    print("PSE Ecosystem — UI Audit")
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


# ── Tests ─────────────────────────────────────────────────────────────────────

@test("Service / flowsheet_service importable without Streamlit")
def _():
    import pse_ecosystem.ui.flowsheet_service as svc  # noqa: F401
    return "import OK"


@test("Service / list_templates() returns >= 11 entries")
def _():
    from pse_ecosystem.ui.flowsheet_service import list_templates
    ts = list_templates()
    assert len(ts) >= 11, f"Expected >= 11 templates, got {len(ts)}"
    # v1.3.0+ category names switched from the original 4-tier scheme to
    # 8-tier industrial-sector labels. Allow either family so this audit
    # script keeps working across the v1.2.x → v1.4.x transition.
    _KNOWN = {
        "Small", "Hydrogen", "Industrial", "Custom",
        "Hydrogen Production", "Biomass Processing", "Power Generation",
        "Petrochemicals", "Carbon Capture & Utilization",
        "Other Industrial", "Other Industrial Processes",
    }
    for t in ts:
        assert t.key, "TemplateSpec.key is empty"
        assert t.display_name, "TemplateSpec.display_name is empty"
        assert t.category in _KNOWN, f"Unknown category: {t.category}"
    return f"{len(ts)} templates registered"


@test("Service / load_template raises ValueError for unknown key")
def _():
    from pse_ecosystem.ui.flowsheet_service import load_template
    try:
        load_template("nonexistent.key", {})
        raise AssertionError("Should have raised KeyError or ValueError")
    except (KeyError, ValueError):
        pass
    return "ValueError raised correctly"


# ── Template solve tests ──────────────────────────────────────────────────────

def _solve_template(key: str, params: dict = None, max_iter: int = 60) -> str:
    """Helper: load + solve one template, return a summary string."""
    from pse_ecosystem.ui.flowsheet_service import load_template
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus

    fs = load_template(key, params or {})
    cfg = SLPConfig(max_iter=max_iter, verbose=False)
    result = Orchestrator(fs, SolveMode.FIXED_LP, slp_config=cfg).solve()

    assert result.status == SolverStatus.CONVERGED, (
        f"Template '{key}' did not converge: {result.status} — {result.message}"
    )
    assert result.x, f"Template '{key}': solution dict is empty"
    for k, v in result.kpis.items():
        assert not (v != v), f"Template '{key}': KPI '{k}' is NaN"  # NaN check

    return (
        f"CONVERGED in {result.iterations} iter | "
        f"{len(result.x)} vars | kpis: {list(result.kpis.keys())[:3]}"
    )


@test("Template / hydrogen.electrolysis_only converges")
def _():
    return _solve_template("hydrogen.electrolysis_only", {"h2_demand_kg_per_h": 120.0})


@test("Template / industrial.green_hydrogen converges")
def _():
    return _solve_template("industrial.green_hydrogen", {"h2_demand_kg_per_h": 80.0})


@test("Template / industrial.power_to_methanol converges")
def _():
    return _solve_template("industrial.power_to_methanol")


@test("Template / industrial.gasification_to_power converges")
def _():
    return _solve_template("industrial.gasification_to_power", max_iter=80)


@test("Template / small.cstr_flash loads (solve optional)")
def _():
    from pse_ecosystem.ui.flowsheet_service import load_template
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus

    fs = load_template("small.cstr_flash", {})
    assert fs is not None, "small.cstr_flash returned None"
    assert len(fs.units) == 2, f"Expected 2 units, got {len(fs.units)}"

    cfg = SLPConfig(max_iter=60, verbose=False)
    result = Orchestrator(fs, SolveMode.FIXED_LP, slp_config=cfg).solve()
    # Convergence is best-effort for this template (complex non-linear unit).
    return f"status={result.status.name}, iter={result.iterations}"


@test("Template / small.mixer_settler loads")
def _():
    from pse_ecosystem.ui.flowsheet_service import load_template
    fs = load_template("small.mixer_settler", {})
    assert len(fs.units) == 2
    return f"units={[u.unit_id for u in fs.units]}"


@test("Template / small.distillation loads")
def _():
    from pse_ecosystem.ui.flowsheet_service import load_template
    fs = load_template("small.distillation", {})
    assert len(fs.units) == 1
    return f"units={[u.unit_id for u in fs.units]}"


@test("Template / small.compression_train loads")
def _():
    from pse_ecosystem.ui.flowsheet_service import load_template
    fs = load_template("small.compression_train", {})
    assert len(fs.units) == 3
    return f"units={[u.unit_id for u in fs.units]}"


@test("MILP / hydrogen.electrolysis_or_gasification loads MILP tuple")
def _():
    try:
        from pse_ecosystem.solvers.milp_builder import select_milp_solver
        select_milp_solver()
    except RuntimeError as exc:
        skip(f"No MILP solver: {exc}")

    from pse_ecosystem.ui.flowsheet_service import load_template_with_choices
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus

    fs, choices = load_template_with_choices(
        "hydrogen.electrolysis_or_gasification", {"h2_demand_kg_per_h": 100.0}
    )
    assert choices, "technology_choices list is empty"
    cfg = SLPConfig(max_iter=30, verbose=False)
    result = Orchestrator(
        fs, SolveMode.FLEXIBLE_MILP,
        slp_config=cfg, technology_choices=choices,
    ).solve()
    assert result.status == SolverStatus.CONVERGED
    return f"CONVERGED | selected={result.technology_selection}"


# ── Layer boundary checks ─────────────────────────────────────────────────────

@test("Layer / app_streamlit.py has no direct models.* import")
def _():
    import re
    app_path = _ROOT / "pse_ecosystem" / "ui" / "app_streamlit.py"
    text = app_path.read_text(encoding="utf-8")
    # Match only actual import lines (start of line, optional leading whitespace).
    # This avoids false positives from docstring text.
    forbidden_patterns = [
        r"^\s*from pse_ecosystem\.models",
        r"^\s*import pse_ecosystem\.models",
        r"^\s*from pse_ecosystem\.flowsheets",
        r"^\s*import pse_ecosystem\.flowsheets",
    ]
    violations = []
    for pat in forbidden_patterns:
        matches = re.findall(pat, text, re.MULTILINE)
        violations.extend(matches)
    assert not violations, f"Forbidden imports found: {violations}"
    return "no Layer-3 imports in app_streamlit.py"


@test("Layer / flowsheet_service.py not imported by solvers/")
def _():
    solvers_dir = _ROOT / "pse_ecosystem" / "solvers"
    for py_file in solvers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "flowsheet_service" in text:
            raise AssertionError(
                f"solvers/{py_file.name} imports flowsheet_service (Layer-1 in Layer-2)"
            )
    return "flowsheet_service not referenced in solvers/"


@test("Layer / solvers/ contains no concrete model imports (regression)")
def _():
    import re
    solvers_dir = _ROOT / "pse_ecosystem" / "solvers"
    forbidden_patterns = [
        r"^\s*from pse_ecosystem\.models",
        r"^\s*import pse_ecosystem\.models",
    ]
    violations = []
    for py_file in solvers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            matches = re.findall(pat, text, re.MULTILINE)
            if matches:
                violations.append(f"{py_file.name}: {matches}")
    assert not violations, f"Layer-3 imports in solvers/: {violations}"
    return "solvers/ layer boundary intact"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_all()
    sys.exit(print_report())
