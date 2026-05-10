"""Small flowsheet: Feed → Distillation HF → [Distillate, Bottoms].

Use case: FUG shortcut column for binary or multicomponent separation.

Factory
-------
make_distillation_column(components, lk, hk, species_vle,
                          dist_params) -> BaseFlowsheet
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.separators.distillation_hf import DistillationHF, DistillationHFParams


def make_distillation_column(
    components: List[str],
    lk: str,
    hk: str,
    species_vle: Optional[List[str]] = None,
    dist_params: Optional[DistillationHFParams] = None,
) -> BaseFlowsheet:
    """Create a single FUG distillation column flowsheet.

    Parameters
    ----------
    components  : Component names (benzene, toluene, etc.).
    lk          : Light key component name.
    hk          : Heavy key component name.
    species_vle : Species with Antoine K-value data.  Defaults to all components.
    dist_params : Optional ``DistillationHFParams`` override.
    """
    if species_vle is None:
        species_vle = list(components)

    if dist_params is None:
        dist_params = DistillationHFParams(
            species_vle=species_vle,
            lk=lk,
            hk=hk,
        )

    dist = DistillationHF("dist", components, dist_params)

    fs = BaseFlowsheet(
        name="small.distillation_column",
        units=[dist],
    )
    return fs
