"""Syngas Production: toy gasifier → CO2 scrubber → syngas compressor.

Topology
--------
    Biomass/waste feed
         │
         ▼
    GasifierToy ("gasifier")       — non-linear toy gasifier (H2 + CO proxy)
         │  h2_kg_per_h
         ▼
    SeparatorHF ("scrubber")       — linear CO2 scrubber (split-fraction model)
         │  outlet_0 = clean syngas (H2-rich)
         │  outlet_1 = CO2 captured stream (removed)
         ▼
    [syngas product with Carbon Intensity KPI]

Differences from gasification_to_power
----------------------------------------
- Uses the GasifierToy (non-linear, tracks H2 yield and LCOH) rather than
  StoichiometricReactor, so Carbon Intensity KPI is available.
- SeparatorHF represents a simplified PSA / membrane scrubber rather than
  just pressurisation.
- No compressor — focus is on syngas quality rather than downstream pressure.
- Objective KPI is "syngas_yield" (kg H2/h).
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy, GasifierToyParams
from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams

# Scrubber split fractions: [H2 stream, CO2 capture stream]
# H2 passes through; CO2 is captured
_SPLIT_H2  = [0.98, 0.02]   # 98% H2 to clean syngas
_SPLIT_CO2 = [0.05, 0.95]   # 95% CO2 captured

# Default H2 production target
_H2_DEMAND_DEFAULT = 200.0  # kg/h


def make_syngas_production(
    h2_demand_kg_per_h: float = _H2_DEMAND_DEFAULT,
    gasifier_params: Optional[GasifierToyParams] = None,
    co2_capture_fraction: float = 0.95,
) -> BaseFlowsheet:
    """Create a Syngas Production flowsheet.

    Parameters
    ----------
    h2_demand_kg_per_h:
        Target H2 output [kg/h]. Enforced via extra_equality on gasifier.h2_kg_per_h.
    gasifier_params:
        Optional override for the toy gasifier parameters.
    co2_capture_fraction:
        Fraction of CO2-proxy stream directed to the capture outlet (0–1).
        Default 0.95 (95% CO2 removed, 5% passes through with syngas).
    """
    if gasifier_params is None:
        gasifier_params = GasifierToyParams()

    # Scrubber split: two "components" modelled as H2 and CO2-proxy
    # GasifierToy only exposes flat variables (not StreamPort), so the scrubber
    # is standalone — not connected via fs.connect() but wired via extra_equalities.
    # The scrubber acts as a post-processing annotation on the gasifier output.
    split_fractions = [
        [1.0 - co2_capture_fraction, co2_capture_fraction],   # CO2-proxy
        [0.98, 0.02],                                           # H2 (mostly clean)
    ]
    scrubber_params = SeparatorHFParams(
        n_outlets=2,
        split_fractions=split_fractions,
        feed_max=1e4,
        T_min=200.0, T_max=600.0,
        P_min=1e3, P_max=1e7,
    )

    gasifier = GasifierToy("gasifier", gasifier_params)
    scrubber = SeparatorHF("scrubber", ["H2_syngas", "CO2_proxy"], scrubber_params)

    fs = BaseFlowsheet(
        name="industrial.syngas_production",
        units=[gasifier, scrubber],
    )

    # Demand equality: gasifier must meet H2 target
    fs.extra_equalities.append(
        ({gasifier.v_h2: 1.0}, h2_demand_kg_per_h)
    )

    # Wire gasifier H2 output → scrubber H2_syngas inlet
    # (flat-variable bridge via extra_equality, same pattern as green_hydrogen.py)
    fs.extra_equalities.append(
        ({gasifier.v_h2: 1.0, "scrubber.inlet.F_H2_syngas": -1.0}, 0.0)
    )

    # CO2-proxy inlet is a fixed fraction of feed (simplified: proportional to steam)
    # Pin CO2_proxy inlet to 10% of H2 demand as a rough CO2-to-H2 ratio
    fs.extra_equalities.append(
        ({"scrubber.inlet.F_CO2_proxy": 1.0},
         h2_demand_kg_per_h * 0.1)
    )

    # Pin scrubber operating conditions
    fs.extra_bounds["scrubber.inlet.T"] = (300.0, 300.0)
    fs.extra_bounds["scrubber.inlet.P"] = (101325.0, 101325.0)

    fs.objective_kpi = "syngas_yield"
    return fs
