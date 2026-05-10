"""Small flowsheet: Feed → CSTR HF → Flash V/L HF → [Vapor, Liquid].

Use case: single-reaction process where a liquid-phase or gas-phase reaction
product is separated by flash (e.g., simplified methanol synthesis loop).

Factory
-------
make_adiabatic_cstr_flash(components, reactions, species_vle,
                           cstr_params, flash_params) -> BaseFlowsheet
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig
from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams


def make_adiabatic_cstr_flash(
    components: List[str],
    reactions: List[ReactionConfig],
    species_vle: List[str],
    cstr_params: Optional[CSTRHFParams] = None,
    flash_params: Optional[FlashVLHFParams] = None,
) -> BaseFlowsheet:
    """Create an adiabatic CSTR → Flash V/L flowsheet.

    Parameters
    ----------
    components : Component list (shared by both units).
    reactions : List of ``ReactionConfig`` objects for the CSTR.
    species_vle : Components that participate in VLE (must be in Antoine DB).
    cstr_params : Optional ``CSTRHFParams`` override.
    flash_params : Optional ``FlashVLHFParams`` override.

    Returns
    -------
    BaseFlowsheet with CSTR outlet wired to Flash inlet.
    """
    if cstr_params is None:
        cstr_params = CSTRHFParams(reactions=reactions, volume_m3=1.0)
    else:
        cstr_params.reactions = reactions

    if flash_params is None:
        flash_params = FlashVLHFParams(species_vle=species_vle)

    cstr  = CSTRHF("cstr",  components, cstr_params)
    flash = FlashVLHF("flash", components, flash_params)

    fs = BaseFlowsheet(
        name="small.adiabatic_cstr_flash",
        units=[cstr, flash],
    )
    fs.connect(cstr.outlet_port, flash.inlet_port, description="CSTR outlet → Flash feed")
    return fs
