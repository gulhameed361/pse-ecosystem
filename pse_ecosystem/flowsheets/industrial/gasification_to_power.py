"""Gasification-to-Power: biomass syngas production + compression.

Topology
--------
    Biomass feed (CH4 + CO2 proxy)
         │
         ▼
    StoichiometricReactor ("gasifier")   — linear stoichiometric dry reforming
         │ syngas (CO, H2, CO2, CH4, H2O)
         ▼
    Compressor ("comp")                  — pressurises syngas for combustion turbine

Design rationale
-----------------
* Biomass gasification is approximated as CH4 + CO2 → 2CO + 2H2 (dry reforming
  stoichiometry). This is a reasonable surrogate for high-temperature steam
  reforming / gasification producing a H2/CO syngas.
* Using StoichiometricReactor (linear, is_linear=True) instead of GibbsReactor
  (scipy SLSQP black-box) guarantees reliable LP convergence in the demo
  gallery.  For full equilibrium calculations, swap in GibbsReactor.
* A single Compressor (non-linear, FD Jacobian) suffices to show the SLP loop.
  The compressor inlet conditions are well-constrained by the reactor outlet,
  giving the SLP driver a good linearisation point on the first iteration.

Feed conditions
----------------
    CH4: 6 mol/s, CO2: 4 mol/s, CO/H2/H2O: 0 mol/s
    T = 800 K (post-gasification temperature)
    P = 101 325 Pa (atmospheric inlet to compressor)

Reaction stoichiometry
-----------------------
    CH4 + CO2  →  2 CO + 2 H2    (dry reforming)
    ν(CH4) = -1,  ν(CO2) = -1,  ν(CO) = +2,  ν(H2) = +2,  ν(H2O) = 0
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.reactors.stoichiometric_reactor import (
    StoichiometricReactor,
    StoichiometricParams,
)
from pse_ecosystem.models.pressure_changers.compressor import Compressor, CompressorParams


_COMPONENTS = ["CO", "H2", "CO2", "CH4", "H2O"]

_STOICH: dict = {
    "CO":  [2.0],
    "H2":  [2.0],
    "CO2": [-1.0],
    "CH4": [-1.0],
    "H2O": [0.0],
}

# Feed: 6 mol/s CH4 + 4 mol/s CO2 at 800 K (post-gasification) and 1 atm
_FEED_T_K  = 800.0
_FEED_P_PA = 101_325.0
_FEED_CH4  = 6.0   # mol/s
_FEED_CO2  = 4.0   # mol/s

# Compressor outlet: 5 bar (suitable for gas turbine entry)
_P_COMP_PA = 500_000.0

# Max reforming extent: limited by CO2 (4 mol/s is the limiting reactant)
_XI_MAX = 4.0  # mol/s — matches CO2 feed for full conversion


def make_gasification_to_power(
    components: Optional[List[str]] = None,
    extent_max: float = _XI_MAX,
    comp_params: Optional[CompressorParams] = None,
) -> BaseFlowsheet:
    """Create a Gasification-to-Power flowsheet.

    Parameters
    ----------
    components:
        Syngas component list. Defaults to ``["CO", "H2", "CO2", "CH4", "H2O"]``.
    extent_max:
        Upper bound on dry-reforming reaction extent [mol/s]. Default 5 mol/s
        (limited by CH4 feed of 6 mol/s).
    comp_params:
        Optional override for the Compressor parameters.
    """
    if components is None:
        components = list(_COMPONENTS)

    if comp_params is None:
        comp_params = CompressorParams(
            eta_isentropic=0.78,
            P_out_Pa=_P_COMP_PA,
            feed_max=30.0,
            T_min=300.0,
            T_max=2000.0,
            P_min=1e4,
            P_max=2e7,
        )

    stoich_params = StoichiometricParams(
        stoichiometry={c: _STOICH.get(c, [0.0]) for c in components},
        xi_max=[extent_max],
        feed_max=30.0,
    )

    gasifier = StoichiometricReactor("gasifier", components, stoich_params)
    comp     = Compressor("comp",     components, comp_params)

    fs = BaseFlowsheet(name="industrial.gasification_to_power",
                       units=[gasifier, comp])

    fs.connect(gasifier.outlet_port, comp.inlet_port,
               description="Syngas → Compressor")

    # ── Pin gasifier feed ────────────────────────────────────────────────────
    fs.extra_bounds["gasifier.inlet.F_CO"]  = (0.0, 0.0)
    fs.extra_bounds["gasifier.inlet.F_H2"]  = (0.0, 0.0)
    fs.extra_bounds["gasifier.inlet.F_CO2"] = (_FEED_CO2, _FEED_CO2)
    fs.extra_bounds["gasifier.inlet.F_CH4"] = (_FEED_CH4, _FEED_CH4)
    fs.extra_bounds["gasifier.inlet.F_H2O"] = (0.0, 0.0)
    fs.extra_bounds["gasifier.inlet.T"]     = (_FEED_T_K, _FEED_T_K)
    fs.extra_bounds["gasifier.inlet.P"]     = (_FEED_P_PA, _FEED_P_PA)

    # Drive full CO2 conversion (LP with no cost objective defaults to xi→0)
    fs.extra_equalities.append(({"gasifier.xi_0": 1.0}, _FEED_CO2))

    # Seed compressor inlet near the expected operating point so the SLP
    # linearisation starts in a physically meaningful regime.
    # Without this, the LP builder uses (P_min+P_max)/2 ≈ 5 MPa for P_in,
    # producing a pressure ratio < 1 (expansion not compression).
    fs.extra_bounds["comp.inlet.T"] = (700.0, 900.0)    # near gasifier outlet T
    fs.extra_bounds["comp.inlet.P"] = (80_000.0, 130_000.0)  # near 1 atm

    fs.objective_kpi = "syngas_yield"
    return fs
