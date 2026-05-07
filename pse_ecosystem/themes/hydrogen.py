"""Hydrogen theme — metadata and default flowsheet factories.

Themes are pure configuration: they map application names to flowsheet
factories. The solver layer never touches this module — themes are part of
Layer 1.
"""

from __future__ import annotations

from pse_ecosystem.core.registry import (
    ApplicationSpec,
    ThemeSpec,
    register_theme,
)
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
    make_electrolysis_only,
    make_electrolysis_or_gasification,
)


HYDROGEN_THEME = ThemeSpec(
    name="hydrogen",
    description="Hydrogen production (electrolysis, gasification).",
    applications={
        "electrolysis_only": ApplicationSpec(
            name="electrolysis_only",
            description="Mode 1 demonstrator: meet H2 demand via a single PEM stack.",
            flowsheet_factory=make_electrolysis_only,
        ),
        "electrolysis_or_gasification": ApplicationSpec(
            name="electrolysis_or_gasification",
            description=(
                "Mode 2 demonstrator: choose between PEM electrolysis and "
                "biomass gasification (or a mix) at minimum cost."
            ),
            flowsheet_factory=make_electrolysis_or_gasification,
        ),
    },
)


register_theme(HYDROGEN_THEME)
