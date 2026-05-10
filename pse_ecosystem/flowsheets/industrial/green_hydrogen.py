"""Green Hydrogen Hub: PEM electrolyser + H2 buffer mixer.

Topology
--------
    [Grid / Renewable]
         │  electricity_kW
         ▼
       PEMToy ("pem")
         │  h2_kg_per_h  ──→ extra_equality wires to MixerHF inlet
         ▼
      MixerHF ("buffer")   ← optional secondary H2 stream (inlet_1 zeroed)
         │
         ▼
      H2 buffer outlet

Note on port impedance
-----------------------
PEMToy uses flat variable names (``pem.electricity_kW``, ``pem.h2_kg_per_h``)
while MixerHF uses StreamPort-style names (``buffer.inlet_0.F_H2`` etc.).
These are bridged via ``extra_equalities`` — no ``fs.connect()`` call is used
between the two units.  The H2 demand equality is also imposed via
``extra_equalities``.
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams
from pse_ecosystem.models.mixers.mixer_hf import MixerHF, MixerHFParams


_COMPONENTS = ["H2", "H2O"]


def make_green_hydrogen_hub(
    h2_demand_kg_per_h: float = 100.0,
    pem_params: Optional[PEMToyParams] = None,
) -> BaseFlowsheet:
    """Create a Green Hydrogen Hub flowsheet.

    Parameters
    ----------
    h2_demand_kg_per_h:
        H2 output target [kg/h]. Enforced as an equality on ``pem.h2_kg_per_h``.
    pem_params:
        Optional override for the PEM electrolyser parameters.
    """
    pem = PEMToy("pem", params=pem_params)
    buf = MixerHF(
        "buffer",
        components=_COMPONENTS,
        params=MixerHFParams(n_inlets=2, feed_max=1e4, T_min=270.0, T_max=400.0),
    )

    fs = BaseFlowsheet(name="industrial.green_hydrogen", units=[pem, buf])

    # Bridge: pem.h2_kg_per_h → buffer.inlet_0.F_H2
    # Units differ in mol/s vs kg/h; H2 MW = 2.016 g/mol, 1 kg/h = 1000/3600 g/s
    # F_H2 [mol/s] = h2_kg_per_h [kg/h] * 1000/3600 / 2.016
    # Coefficient on pem side: 1000/(3600*2.016) ≈ 0.13812
    h2_mw = 2.016  # g/mol
    kg_h_to_mol_s = 1000.0 / (3600.0 * h2_mw)
    fs.extra_equalities.append(
        ({"pem.h2_kg_per_h": kg_h_to_mol_s, "buffer.inlet_0.F_H2": -1.0}, 0.0)
    )

    # Secondary inlet (inlet_1) set to zero flow — no secondary H2 source
    for c in _COMPONENTS:
        fs.extra_bounds[f"buffer.inlet_1.F_{c}"] = (0.0, 0.0)
    fs.extra_bounds["buffer.inlet_1.T"] = (298.15, 298.15)
    fs.extra_bounds["buffer.inlet_1.P"] = (101325.0, 101325.0)

    # Demand equality: pem.h2_kg_per_h == h2_demand_kg_per_h
    fs.extra_equalities.append(
        ({"pem.h2_kg_per_h": 1.0}, h2_demand_kg_per_h)
    )

    fs.objective_kpi = "LCOH"
    return fs
