"""End-to-end demo: solve the toy hydrogen flowsheet under both modes.

Usage
-----
    python examples/electrolysis_v0.py --mode 1
    python examples/electrolysis_v0.py --mode 2 --demand 80
"""

from __future__ import annotations

import argparse
import sys
from pprint import pprint

from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
    make_electrolysis_only,
    make_electrolysis_or_gasification,
)
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--mode", type=int, choices=[1, 2], default=1)
    p.add_argument("--demand", type=float, default=100.0, help="kg H2 / h")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.mode == 1:
        flowsheet = make_electrolysis_only(h2_demand_kg_per_h=args.demand)
        orch = Orchestrator(
            flowsheet=flowsheet,
            mode=SolveMode.FIXED_LP,
            slp_config=SLPConfig(verbose=args.verbose),
        )
    else:
        flowsheet, choices = make_electrolysis_or_gasification(
            h2_demand_kg_per_h=args.demand,
        )
        orch = Orchestrator(
            flowsheet=flowsheet,
            mode=SolveMode.FLEXIBLE_MILP,
            technology_choices=choices,
            slp_config=SLPConfig(verbose=args.verbose),
        )

    result = orch.solve()

    print(f"\n-- Result ({result.mode.value}) " + "-" * 30)
    print(f"status       : {result.status.value}")
    print(f"iterations   : {result.iterations}")
    print(f"objective    : {result.objective:.4g}")
    if result.technology_selection:
        print("tech choice  :")
        pprint(result.technology_selection, indent=2)
    print("variables    :")
    pprint({k: round(v, 4) for k, v in result.x.items()}, indent=2)
    print("KPIs         :")
    pprint({k: round(v, 4) if isinstance(v, float) else v for k, v in result.kpis.items()}, indent=2)
    print(f"message      : {result.message}")
    return 0 if result.converged else 1


if __name__ == "__main__":
    sys.exit(main())
