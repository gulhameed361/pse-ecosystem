"""HAZOP node generator — walks flowsheet topology to enumerate study
nodes and applies the standard guideword × parameter matrix.

A HAZOP (Hazard and Operability Study) divides the plant into *nodes* —
sections of equipment that share a common design intent — and brainstorms
*deviations* by applying *guidewords* to each *parameter*:

* Guidewords: NO, MORE, LESS, AS WELL AS, PART OF, REVERSE, OTHER THAN
* Parameters: flow, pressure, temperature, level, composition, reaction,
              phase, time, contamination, instrumentation

This module emits the cartesian-product matrix as a starting checklist;
it does **not** replace expert HAZOP facilitation. The output is a JSON-
serialisable list of nodes that a HAZOP team can import into their
preferred software (PHA-Pro, e!Sankey, custom Excel) for manual review.

Each node corresponds to one unit in the flowsheet. The unit's category
(``INDUSTRIAL`` / ``DIDACTIC`` / ``LEGACY``) controls whether it appears
in the output: ``DIDACTIC`` and ``LEGACY`` units are skipped because
they don't represent real plant items.

Reference: IEC 61882:2016 — Hazard and operability studies (HAZOP studies).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


_GUIDEWORDS: Tuple[str, ...] = (
    "NO", "MORE", "LESS", "AS WELL AS",
    "PART OF", "REVERSE", "OTHER THAN",
)

_PARAMETERS: Tuple[str, ...] = (
    "flow", "pressure", "temperature", "level",
    "composition", "reaction", "phase", "contamination",
)

# Parameters that apply only to certain unit shapes — skips the matrix
# rows that don't make sense (e.g. "level" on a mixer).
_PARAMETER_APPLICABILITY: Dict[str, Tuple[str, ...]] = {
    "mixer": ("flow", "pressure", "temperature", "composition", "contamination"),
    "reactor": ("flow", "pressure", "temperature", "composition", "reaction"),
    "hx": ("flow", "pressure", "temperature"),
    "separator": ("flow", "pressure", "temperature", "level", "composition", "phase"),
    "pump": ("flow", "pressure"),
    "compressor": ("flow", "pressure", "temperature"),
    "valve": ("flow", "pressure"),
    "generic": _PARAMETERS,
}


def _shape_for_unit(unit: Any) -> str:
    """Infer the HAZOP-relevant shape category from the unit's class name."""
    name = type(unit).__name__.lower()
    if "mixer" in name:
        return "mixer"
    if any(
        k in name
        for k in ("reactor", "gasifier", "methanation", "cstr", "pfr", "wgs")
    ):
        return "reactor"
    if any(k in name for k in ("hx", "heat", "cooler", "boiler", "fired")):
        return "hx"
    if any(k in name for k in ("flash", "separator", "column", "decanter",
                                "crystallizer", "drum", "contactor", "membrane")):
        return "separator"
    if "pump" in name:
        return "pump"
    if "compressor" in name or "expander" in name:
        return "compressor"
    if "valve" in name:
        return "valve"
    return "generic"


@dataclass(frozen=True)
class HAZOPDeviation:
    guideword: str
    parameter: str
    description: str


@dataclass
class HAZOPNode:
    unit_id: str
    unit_type: str
    category: str
    shape: str
    deviations: List[HAZOPDeviation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "category": self.category,
            "shape": self.shape,
            "deviations": [
                {"guideword": d.guideword, "parameter": d.parameter,
                 "description": d.description}
                for d in self.deviations
            ],
        }


def _describe(guideword: str, parameter: str) -> str:
    """One-line consequence-prompt for a (guideword, parameter) pair."""
    return f"{guideword} {parameter} — investigate causes and consequences."


def generate_nodes(flowsheet: Any) -> List[HAZOPNode]:
    """Walk ``flowsheet.units`` and emit a HAZOP node per industrial unit.

    Filters out ``DIDACTIC`` and ``LEGACY`` units automatically — they
    have no real plant counterpart to study.
    """
    nodes: List[HAZOPNode] = []
    for unit in getattr(flowsheet, "units", []):
        cat_value = getattr(getattr(unit, "category", None), "value", "industrial")
        if cat_value in ("didactic", "legacy"):
            continue
        shape = _shape_for_unit(unit)
        applicable = _PARAMETER_APPLICABILITY.get(shape, _PARAMETERS)
        deviations: List[HAZOPDeviation] = []
        for guideword in _GUIDEWORDS:
            for parameter in applicable:
                deviations.append(
                    HAZOPDeviation(
                        guideword=guideword,
                        parameter=parameter,
                        description=_describe(guideword, parameter),
                    )
                )
        nodes.append(
            HAZOPNode(
                unit_id=getattr(unit, "unit_id", "?"),
                unit_type=type(unit).__name__,
                category=cat_value,
                shape=shape,
                deviations=deviations,
            )
        )
    return nodes


def export_nodes_to_dict(flowsheet: Any) -> List[Dict[str, Any]]:
    """Wrap :func:`generate_nodes` so JSON / Excel exporters can consume."""
    return [n.to_dict() for n in generate_nodes(flowsheet)]


__all__ = [
    "HAZOPDeviation",
    "HAZOPNode",
    "generate_nodes",
    "export_nodes_to_dict",
]
