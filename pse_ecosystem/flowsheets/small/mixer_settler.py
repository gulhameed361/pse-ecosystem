"""Small flowsheet: [Feed1, Feed2] → Mixer HF → Separator HF → [Product1, Product2].

Use case: blending two process streams then splitting by component.

Factory
-------
make_mixer_settler(components, split_fractions,
                   mixer_params, sep_params) -> BaseFlowsheet
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.mixers.mixer_hf import MixerHF, MixerHFParams
from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams


def make_mixer_settler(
    components: List[str],
    split_fractions: Optional[List[List[float]]] = None,
    mixer_params: Optional[MixerHFParams] = None,
    sep_params: Optional[SeparatorHFParams] = None,
) -> BaseFlowsheet:
    """Create a 2-inlet Mixer → 2-outlet Separator flowsheet.

    Parameters
    ----------
    components      : Component names shared by all units.
    split_fractions : [N_comp × 2] split fractions for the separator.
                      Defaults to 50/50 split for each component.
    """
    if mixer_params is None:
        mixer_params = MixerHFParams(n_inlets=2)
    if sep_params is None:
        sep_params = SeparatorHFParams(n_outlets=2, split_fractions=split_fractions)
    else:
        if split_fractions is not None:
            sep_params.split_fractions = split_fractions

    mixer = MixerHF("mixer", components, mixer_params)
    sep   = SeparatorHF("sep",   components, sep_params)

    fs = BaseFlowsheet(
        name="small.mixer_settler",
        units=[mixer, sep],
    )
    fs.connect(mixer.outlet_port, sep.inlet_port, description="Mixer outlet → Separator inlet")
    return fs
