"""Layer-1 entry-point stub for v0.

Exposes a minimal CLI so the architecture is exercised end-to-end without
shipping a real UI yet. A future Streamlit or FastAPI front-end will sit
above this module and call the same Orchestrator the CLI does.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig

# Importing the theme triggers registry-side-effects so themes are discoverable.
import pse_ecosystem.themes.hydrogen  # noqa: F401
from pse_ecosystem.core.registry import get_theme, list_themes


def _parse_mode(value: str) -> SolveMode:
    value = value.lower()
    if value in ("1", "mode_1", "fixed", "fixed_lp"):
        return SolveMode.FIXED_LP
    if value in ("2", "mode_2", "flexible", "flexible_milp"):
        return SolveMode.FLEXIBLE_MILP
    raise argparse.ArgumentTypeError(f"unknown mode: {value!r}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pse-ecosystem",
        description="PSE Ecosystem v0 entry-point stub.",
    )
    parser.add_argument("--theme", default="hydrogen", choices=list_themes())
    parser.add_argument(
        "--application",
        default="electrolysis_only",
        help="Application name within the theme.",
    )
    parser.add_argument(
        "--mode",
        type=_parse_mode,
        default=SolveMode.FIXED_LP,
        help="Solver mode: 1 (fixed LP) or 2 (flexible MILP).",
    )
    parser.add_argument(
        "--demand",
        type=float,
        default=100.0,
        help="Hydrogen demand (kg/h).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    theme = get_theme(args.theme)
    if args.application not in theme.applications:
        parser.error(
            f"Unknown application {args.application!r} for theme {args.theme!r}. "
            f"Available: {list(theme.applications)}"
        )
    app = theme.applications[args.application]

    factory_result = app.flowsheet_factory(h2_demand_kg_per_h=args.demand)
    if isinstance(factory_result, tuple):
        flowsheet, technology_choices = factory_result
    else:
        flowsheet, technology_choices = factory_result, None

    orchestrator = Orchestrator(
        flowsheet=flowsheet,
        mode=args.mode,
        slp_config=SLPConfig(verbose=args.verbose),
        technology_choices=technology_choices,
    )
    result = orchestrator.solve()

    payload = {
        "status": result.status.value,
        "mode": result.mode.value,
        "iterations": result.iterations,
        "objective": result.objective,
        "x": result.x,
        "kpis": result.kpis,
        "technology_selection": result.technology_selection,
        "message": result.message,
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0 if result.converged else 1


if __name__ == "__main__":
    sys.exit(main())
