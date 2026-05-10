"""Power-to-Methanol: CO2 + 3H2 → methanol + H2O, then split-fraction separation.

Topology
--------
    Feed (CO2 + H2) → StoichiometricReactor ("rxr") → SeparatorHF ("sep")
                                                          │         │
                                                       Gas out  Liquid out
                                                     (CO2/H2)  (methanol/water)

Stoichiometry
-------------
    CO2 + 3 H2  →  CH3OH  +  H2O
    ν(CO2) = -1,  ν(H2) = -3,  ν(methanol) = +1,  ν(water) = +1

Separator design rationale
---------------------------
The StoichiometricReactor is a linear unit; a full rigorous VLE (FlashVLHF)
would require methanol/water Antoine data and a good initial guess far from
the midpoint of bounds.  For a reliable one-click demo we use SeparatorHF
(linear, split-fraction model) with physically motivated fractions:

    Component   Vapour fraction   Liquid fraction
    ---------   ---------------   ---------------
    CO2           0.98              0.02  (non-condensable gas at 320 K / 5 bar)
    H2            0.99              0.01  (non-condensable gas)
    methanol      0.05              0.95  (liquid product, K ≈ 0.07 at 320 K)
    water         0.02              0.98  (liquid product, K ≈ 0.03 at 320 K)

Both units are linear → the flowsheet short-circuits to a single LP solve.

Species naming note
--------------------
Follows the ANTOINE database convention in ``vle.py``: ``"methanol"`` and
``"water"`` (not ``"CH3OH"`` / ``"H2O"``).
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.reactors.stoichiometric_reactor import (
    StoichiometricReactor,
    StoichiometricParams,
)
from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams


_COMPONENTS_DEFAULT = ["CO2", "H2", "methanol", "water"]

_STOICH: dict = {
    "CO2":      [-1.0],
    "H2":       [-3.0],
    "methanol":  [1.0],
    "water":     [1.0],
}

# Split fractions: [component_index][outlet_index]
# outlet 0 = vapour, outlet 1 = liquid
_SPLIT_FRACTIONS = [
    [0.98, 0.02],   # CO2  → mostly vapour
    [0.99, 0.01],   # H2   → mostly vapour
    [0.05, 0.95],   # methanol → mostly liquid
    [0.02, 0.98],   # water    → mostly liquid
]

# Feed: 3 mol/s CO2 + 9 mol/s H2 at 320 K, 5 bar (within Antoine valid range)
_FEED_T_K  = 320.0
_FEED_P_PA = 500_000.0
_FEED_CO2  = 3.0   # mol/s
_FEED_H2   = 9.0   # mol/s


def make_power_to_methanol(
    components: Optional[List[str]] = None,
    extent_max: float = 3.0,
    split_fractions: Optional[List[List[float]]] = None,
) -> BaseFlowsheet:
    """Create a Power-to-Methanol flowsheet.

    Parameters
    ----------
    components:
        Component list shared by reactor and separator. Defaults to
        ``["CO2", "H2", "methanol", "water"]``.
    extent_max:
        Upper bound on reaction extent [mol/s]. Matches stoichiometric CO2
        feed (3 mol/s) by default.
    split_fractions:
        Override the vapour/liquid split fractions. Shape: [N_comp × 2].
    """
    if components is None:
        components = list(_COMPONENTS_DEFAULT)
    if split_fractions is None:
        split_fractions = [list(row) for row in _SPLIT_FRACTIONS]

    stoich_params = StoichiometricParams(
        stoichiometry={c: _STOICH.get(c, [0.0]) for c in components},
        xi_max=[extent_max],
        feed_max=50.0,
    )
    sep_params = SeparatorHFParams(
        n_outlets=2,
        split_fractions=split_fractions,
        feed_max=50.0,
        T_min=250.0,
        T_max=500.0,
        P_min=1e4,
        P_max=2e6,
    )

    rxr = StoichiometricReactor("rxr", components, stoich_params)
    sep = SeparatorHF("sep", components, sep_params)

    fs = BaseFlowsheet(name="industrial.power_to_methanol", units=[rxr, sep])
    fs.connect(rxr.outlet_port, sep.inlet_port, description="Reactor → Separator")

    # Pin reactor feed composition and conditions
    fs.extra_bounds["rxr.inlet.F_CO2"]      = (_FEED_CO2, _FEED_CO2)
    fs.extra_bounds["rxr.inlet.F_H2"]       = (_FEED_H2,  _FEED_H2)
    fs.extra_bounds["rxr.inlet.F_methanol"] = (0.0, 0.0)
    fs.extra_bounds["rxr.inlet.F_water"]    = (0.0, 0.0)
    fs.extra_bounds["rxr.inlet.T"]          = (_FEED_T_K, _FEED_T_K)
    fs.extra_bounds["rxr.inlet.P"]          = (_FEED_P_PA, _FEED_P_PA)

    # Force maximum conversion — without an explicit cost objective the LP
    # defaults to xi=0 (lower bound). Pin extent to the CO2 feed limit.
    fs.extra_equalities.append(({"rxr.xi_0": 1.0}, _FEED_CO2))

    fs.objective_kpi = "methanol_yield"
    return fs
