"""Toy hydrogen-from-electrolysis flowsheet.

Two factory functions:

* :func:`make_electrolysis_only` — Mode-1 LP demonstrator. A single PEM unit
  meeting a fixed hourly hydrogen demand.

* :func:`make_electrolysis_or_gasification` — Mode-2 MILP demonstrator. Both
  a PEM electrolyser and a toy gasifier are available; the binary technology
  decision picks one (or both) to meet demand at minimum cost.
"""

from __future__ import annotations

from typing import List, Tuple

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams
from pse_ecosystem.models.gasification.gasifier_toy import (
    GasifierToy,
    GasifierToyParams,
)
# v1.6.1 P.5a — TechnologyChoice was relocated to ``core.contracts``
# (the shared cross-layer module) to close the only top-level L3 → L2
# import leak. The milp_builder still re-exports it for legacy callers.
from pse_ecosystem.core.contracts import TechnologyChoice


def make_electrolysis_only(
    h2_demand_kg_per_h: float = 100.0,
    pem_params: PEMToyParams | None = None,
) -> BaseFlowsheet:
    """Single-PEM flowsheet meeting a fixed H2 demand."""
    pem = PEMToy(unit_id="pem", params=pem_params)
    flowsheet = BaseFlowsheet(
        name="hydrogen.electrolysis_only",
        units=[pem],
        connections=[],
        objective_kpi="annual_cost",
    )
    # Demand: pem.h2_kg_per_h == demand
    flowsheet.extra_equalities.append(
        ({pem.v_h2: 1.0}, h2_demand_kg_per_h)
    )
    return flowsheet


def make_electrolysis_or_gasification(
    h2_demand_kg_per_h: float = 100.0,
    pem_params: PEMToyParams | None = None,
    gas_params: GasifierToyParams | None = None,
) -> Tuple[BaseFlowsheet, List[TechnologyChoice]]:
    """Mode-2 MILP demonstrator. Returns (flowsheet, technology_choices)."""
    pem = PEMToy(unit_id="pem", params=pem_params)
    gas = GasifierToy(unit_id="gasifier", params=gas_params)

    flowsheet = BaseFlowsheet(
        name="hydrogen.electrolysis_or_gasification",
        units=[pem, gas],
        connections=[],
        objective_kpi="annual_cost",
    )
    flowsheet.extra_equalities.append(
        ({pem.v_h2: 1.0, gas.v_h2: 1.0}, h2_demand_kg_per_h)
    )

    pem_capex_annual = pem.params.capex_annual_per_kW * pem.params.capacity_kW

    technology_choices = [
        TechnologyChoice(
            name="pick_pem",
            unit_id=pem.unit_id,
            flow_variables=[pem.v_electricity, pem.v_h2],
            big_M=max(
                pem.params.capacity_kW,
                pem.params.eta_kg_per_kWh * pem.params.capacity_kW,
            ),
            fixed_cost=pem_capex_annual,
        ),
        TechnologyChoice(
            name="pick_gasifier",
            unit_id=gas.unit_id,
            flow_variables=[gas.v_feed, gas.v_h2, gas.v_steam],
            big_M=gas.params.feed_max_kg_per_h,
            fixed_cost=gas.params.capex_annual_GBP,
        ),
    ]
    return flowsheet, technology_choices
