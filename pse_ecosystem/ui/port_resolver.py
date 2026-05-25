"""Primary-port resolver — UI bridge between heterogeneous unit port
attributes and the flat ``inlet/outlet`` convention the Custom Builder
expects.

Each PSE Ecosystem unit names its primary inlet and outlet StreamPort
slightly differently — ``inlet_port`` for plain reactors, ``hot_inlet_port``
for two-stream HX, ``biomass_in_port`` for the gasifier, and so on. The
Custom Builder needs a single ``primary_inlet(unit) → StreamPort`` /
``primary_outlet(unit) → StreamPort`` lookup that handles every shape.

Resolution order (preferred → fallback):

1. ``_primary_inlet_port`` / ``_primary_outlet_port`` attribute or property
   set explicitly by the unit author (canonical — v1.4.0+).
2. Named-attribute table (``_INLET_NAMED`` / ``_OUTLET_NAMED``) — legacy
   fallback for v1.3 / v1.4 units that didn't declare the canonical
   property yet.
3. List-of-ports attribute (``inlet_ports`` / ``outlet_ports``) for units
   with N-ary streams (MixerHF, SeparatorHF) — returns the first entry.
4. ``None`` for flat-variable units (TVSAContactor, ElectrolyserHF) that
   don't expose StreamPort objects.

Extracted from ``flowsheet_service.py`` in v1.6.1 P.1.2 — see
``docs/PLAN_v1_6_1.md``.
"""

from __future__ import annotations

from typing import Any


_OUTLET_NAMED: tuple = (
    "outlet_port",       # StoichiometricReactor, Compressor, Pump, Valve, MixerHF
    "hot_outlet_port",   # HeatExchangerNTU (process hot side)
    "syngas_out_port",   # BiomassGasifierHF
    "shifted_out_port",  # WGSReactorHF
    "h2_out_port",       # H2SeparatorPSA
    "dry_out_port",      # BiomassStorageHF
    "vapor_port",        # FlashVLHF (primary vapour outlet)
)
_OUTLET_LISTS: tuple = ("outlet_ports",)   # SeparatorHF

_INLET_NAMED: tuple = (
    "inlet_port",        # StoichiometricReactor, SeparatorHF, Compressor, FlashVLHF
    "hot_inlet_port",    # HeatExchangerNTU
    "syngas_in_port",    # WGSReactorHF
    "feed_in_port",      # H2SeparatorPSA
    "biomass_in_port",   # BiomassGasifierHF
    "wet_in_port",       # BiomassStorageHF
)
_INLET_LISTS: tuple = ("inlet_ports",)     # MixerHF


def primary_outlet(unit: Any):
    """Return the unit's primary outlet StreamPort, or ``None`` for
    flat-variable units.

    Checks the canonical ``_primary_outlet_port`` property first (set on
    all units with non-standard port names), then falls back to the legacy
    name list and finally to list-shaped port collections.
    """
    p = getattr(unit, "_primary_outlet_port", None)
    if p is not None:
        return p
    for name in _OUTLET_NAMED:
        p = getattr(unit, name, None)
        if p is not None:
            return p
    for name in _OUTLET_LISTS:
        lst = getattr(unit, name, None)
        if lst:
            return lst[0]
    return None


def primary_inlet(unit: Any):
    """Return the unit's primary inlet StreamPort, or ``None`` for
    flat-variable units. Same fallback chain as :func:`primary_outlet`."""
    p = getattr(unit, "_primary_inlet_port", None)
    if p is not None:
        return p
    for name in _INLET_NAMED:
        p = getattr(unit, name, None)
        if p is not None:
            return p
    for name in _INLET_LISTS:
        lst = getattr(unit, name, None)
        if lst:
            return lst[0]
    return None


# Module-level underscore aliases preserved for callers that still import
# the v1.6 names from ``flowsheet_service`` (re-exported via the facade).
_primary_outlet = primary_outlet
_primary_inlet = primary_inlet


__all__ = [
    "primary_inlet",
    "primary_outlet",
    "_primary_inlet",
    "_primary_outlet",
    "_INLET_NAMED",
    "_OUTLET_NAMED",
    "_INLET_LISTS",
    "_OUTLET_LISTS",
]
