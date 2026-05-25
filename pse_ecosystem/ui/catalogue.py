"""Unit catalogue + Industrial Mode persona filter.

Owns the three pieces the Custom Builder + persona-aware unit picker need:

* ``AVAILABLE_UNITS`` — label → human description map for every shippable
  unit, in the order they appear in the UI picker.
* ``UNIT_CATEGORIES`` — semantic grouping (Reactors / Separators / HX /
  Power / Mixing / Pressure changers / Utilities / Feed-Product / Biomass)
  used to populate the Custom Builder's dropdown sections.
* ``available_units_for_persona`` / ``unit_categories_for_persona`` —
  v1.6 Workstream G.1 persona filter. Reads each unit's
  :attr:`BaseUnit.category` at runtime so Industrial Mode hides
  ``DIDACTIC`` and ``LEGACY`` units (and optionally ``SCREENING``).

Extracted from ``flowsheet_service.py`` in v1.6.1 P.1.3 — see
``docs/PLAN_v1_6_1.md``.

Design note
-----------
``_unit_class_for_label`` performs **lazy class resolution** — the imports
live inside each branch so a UI-only deployment (no model layer)
still loads the module cleanly. The resolution table tracks every entry
of ``AVAILABLE_UNITS``; new units must be added in both places.
"""

from __future__ import annotations

from typing import Dict, List


AVAILABLE_UNITS: Dict[str, str] = {
    # Feed / Product
    "PEMToy":                "Electrolyser — linear (LCOH + Carbon Intensity KPIs)",
    "GasifierToy":           "Gasifier toy — non-linear (LCOH + Carbon Intensity KPIs)",
    # Biomass chain
    "BiomassStorageHF":      "Biomass dryer/storage — linear, solid feedstock",
    "BiomassGasifierHF":     "Biomass gasifier — non-linear equilibrium, 6-species syngas",
    "WGSReactorHF":          "Water-Gas Shift reactor — non-linear equilibrium, analytical J",
    # Reactors
    "StoichiometricReactor": "Stoichiometric reactor — linear (exact analytical J)",
    "MethanationReactor":    "Sabatier methanation — non-linear equilibrium, analytical J",
    "EquilibriumReactor":    "Equilibrium reactor — van't Hoff Keq (default WGS reaction)",
    "GibbsReactor":          "Isothermal Gibbs-energy-minimising reactor",
    # Separation / DAC
    "SeparatorHF":           "Separator — split fractions, linear",
    "TVSAContactor":         "TVSA DAC contactor — linear, analytical J (415 ppm CO2 feed)",
    "H2SeparatorPSA":        "PSA hydrogen separator — linear, configurable H₂ recovery",
    "DistillationHF":        "Distillation column — Fenske/Underwood (light/heavy key)",
    # Heat Exchange
    "HeatExchangerNTU":      "Heat exchanger NTU — non-linear (counter-current)",
    "ShellTubeHX":           "Shell-and-tube HX — corrected LMTD (1-2 pass)",
    "CoolerHF":              "Single-stream gas cooler — linear, fixed T_out parameter",
    # Power / CHP
    "ElectrolyserHF":        "PEM/AEL electrolyser — linear, port-based, analytical J",
    "CHPUnit":               "Combined Heat & Power — linear, analytical J (H2/CO/CH4 fuel)",
    # Separation / VLE
    "FlashVLHF":             "Rigorous V/L flash — Antoine K-values + Rachford-Rice (non-linear, terminal unit)",
    # Mixing
    "MixerHF":               "Multi-stream mixer — non-linear (energy balance)",
    # Pressure Changers
    "Compressor":            "Isentropic compressor — non-linear",
    "Pump":                  "Liquid pump — non-linear, isentropic efficiency",
    "Valve":                 "Throttle valve — isenthalpic, smoothed Cv·√(dP)",
    # v1.6 Workstream B — 10 new industrial-grade units
    "ExpanderHF":            "Turbo-expander — power-recovery turbine (negative-OPEX credit)",
    "MultistageCompressorHF": "N-stage compressor with intercoolers + knockout drums",
    "DecanterHF":            "Liquid-liquid decanter — partition-coefficient phase split",
    "SteamDrumHF":           "Saturated steam drum — utility steam balance (NIST water)",
    "FiredHeaterHF":         "Fired heater / furnace — combustion + flue gas + NOx",
    "PackedColumnHF":        "Packed absorber / stripper — Colburn NTU·HTU method",
    "MembraneModuleHF":      "Multi-component permeation module — cross-flow",
    "BatchReactorHF":        "Batch reactor — Arrhenius kinetics over cycle time",
    "TrayColumnHF":          "Rigorous MESH column — property-package K-values",
    "CrystallizerHF":        "Cooling / evaporative crystalliser — van't Hoff solubility",
}


UNIT_CATEGORIES: Dict[str, List[str]] = {
    "Feed/Product":       ["PEMToy", "GasifierToy"],
    "Biomass":            ["BiomassStorageHF", "BiomassGasifierHF", "WGSReactorHF"],
    "Reactors":           ["StoichiometricReactor", "MethanationReactor",
                           "EquilibriumReactor", "GibbsReactor",
                           "BatchReactorHF"],
    "Separation/DAC":     ["SeparatorHF", "FlashVLHF", "TVSAContactor",
                           "H2SeparatorPSA", "DistillationHF",
                           "DecanterHF", "PackedColumnHF", "TrayColumnHF",
                           "MembraneModuleHF", "CrystallizerHF"],
    "Heat Exchange":      ["HeatExchangerNTU", "ShellTubeHX", "CoolerHF",
                           "FiredHeaterHF"],
    "Power/CHP":          ["ElectrolyserHF", "CHPUnit"],
    "Utilities":          ["SteamDrumHF"],
    "Mixing":             ["MixerHF"],
    "Pressure Changers":  ["Compressor", "Pump", "Valve",
                           "ExpanderHF", "MultistageCompressorHF"],
}


# ─────────────────────────────────────────────────────────────────────────────
# v1.6 Workstream G — Industrial Mode unit filter
# ─────────────────────────────────────────────────────────────────────────────


def _unit_class_for_label(label: str):
    """Resolve a UI label to its actual unit class so we can read
    :attr:`BaseUnit.category`. Returns ``None`` if the class is unavailable
    (which leaves the unit visible — failing soft is preferable to silently
    hiding units after an internal refactor)."""
    # Lazy imports so a UI-only deployment without the model layer still
    # loads this module.
    try:
        if label == "PEMToy":
            from pse_ecosystem.models.electrolysis.pem_toy import PEMToy
            return PEMToy
        if label == "GasifierToy":
            from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy
            return GasifierToy
        if label == "BiomassStorageHF":
            from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
            return BiomassStorageHF
        if label == "BiomassGasifierHF":
            from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
            return BiomassGasifierHF
        if label == "WGSReactorHF":
            from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
            return WGSReactorHF
        if label == "StoichiometricReactor":
            from pse_ecosystem.models.reactors.stoichiometric_reactor import StoichiometricReactor
            return StoichiometricReactor
        if label == "MethanationReactor":
            from pse_ecosystem.models.dac.methanation_reactor import MethanationReactor
            return MethanationReactor
        if label == "EquilibriumReactor":
            from pse_ecosystem.models.reactors.equilibrium_reactor import EquilibriumReactor
            return EquilibriumReactor
        if label == "GibbsReactor":
            from pse_ecosystem.models.reactors.gibbs_reactor import GibbsReactor
            return GibbsReactor
        if label == "BatchReactorHF":
            from pse_ecosystem.models.reactors.batch_reactor import BatchReactorHF
            return BatchReactorHF
        if label == "SeparatorHF":
            from pse_ecosystem.models.separators.separator_hf import SeparatorHF
            return SeparatorHF
        if label == "FlashVLHF":
            from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF
            return FlashVLHF
        if label == "TVSAContactor":
            from pse_ecosystem.models.dac.tvsa_contactor import TVSAContactor
            return TVSAContactor
        if label == "H2SeparatorPSA":
            from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
            return H2SeparatorPSA
        if label == "DistillationHF":
            from pse_ecosystem.models.separators.distillation_hf import DistillationHF
            return DistillationHF
        if label == "DecanterHF":
            from pse_ecosystem.models.separators.decanter import DecanterHF
            return DecanterHF
        if label == "PackedColumnHF":
            from pse_ecosystem.models.separators.packed_column import PackedColumnHF
            return PackedColumnHF
        if label == "TrayColumnHF":
            from pse_ecosystem.models.separators.tray_column import TrayColumnHF
            return TrayColumnHF
        if label == "MembraneModuleHF":
            from pse_ecosystem.models.separators.membrane_module import MembraneModuleHF
            return MembraneModuleHF
        if label == "CrystallizerHF":
            from pse_ecosystem.models.separators.crystallizer import CrystallizerHF
            return CrystallizerHF
        if label == "HeatExchangerNTU":
            from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import HeatExchangerNTU
            return HeatExchangerNTU
        if label == "ShellTubeHX":
            from pse_ecosystem.models.heat_exchangers.shell_tube import ShellTubeHX
            return ShellTubeHX
        if label == "CoolerHF":
            from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
            return CoolerHF
        if label == "FiredHeaterHF":
            from pse_ecosystem.models.heat_exchangers.fired_heater import FiredHeaterHF
            return FiredHeaterHF
        if label == "ElectrolyserHF":
            from pse_ecosystem.models.dac.electrolyser_hf import ElectrolyserHF
            return ElectrolyserHF
        if label == "CHPUnit":
            from pse_ecosystem.models.power.chp_unit import CHPUnit
            return CHPUnit
        if label == "SteamDrumHF":
            from pse_ecosystem.models.utilities.steam_drum import SteamDrumHF
            return SteamDrumHF
        if label == "MixerHF":
            from pse_ecosystem.models.mixers.mixer_hf import MixerHF
            return MixerHF
        if label == "Compressor":
            from pse_ecosystem.models.pressure_changers.compressor import Compressor
            return Compressor
        if label == "Pump":
            from pse_ecosystem.models.pressure_changers.pump import Pump
            return Pump
        if label == "Valve":
            from pse_ecosystem.models.pressure_changers.valve import Valve
            return Valve
        if label == "ExpanderHF":
            from pse_ecosystem.models.pressure_changers.expander import ExpanderHF
            return ExpanderHF
        if label == "MultistageCompressorHF":
            from pse_ecosystem.models.pressure_changers.multistage_compressor import MultistageCompressorHF
            return MultistageCompressorHF
    except Exception:  # noqa: BLE001
        return None
    return None


def available_units_for_persona(
    persona: str = "Academic",
    show_screening: bool = True,
) -> Dict[str, str]:
    """Return a filtered ``AVAILABLE_UNITS`` dict for the given persona.

    * ``Industrial`` persona hides :class:`UnitCategory.DIDACTIC` and
      :class:`UnitCategory.LEGACY` units. ``show_screening = False`` also
      hides :class:`UnitCategory.SCREENING` (the shortcut-FUG distillation
      column) so users only see industrial-design-ready units.
    * ``Academic`` persona (default) shows every unit — preserves
      v1.5.x behaviour for teaching contexts.

    Units whose class can't be resolved (UI-only deployments without the
    model layer, or experimental units not yet wired through this helper)
    fail soft: they remain visible. The category attribute is read at
    runtime from ``BaseUnit.category``, so re-tagging a unit propagates
    to the UI without changing this function.
    """
    from pse_ecosystem.models.base_unit import UnitCategory

    if persona != "Industrial":
        return dict(AVAILABLE_UNITS)

    out: Dict[str, str] = {}
    hidden = {UnitCategory.DIDACTIC, UnitCategory.LEGACY}
    if not show_screening:
        hidden.add(UnitCategory.SCREENING)
    for label, desc in AVAILABLE_UNITS.items():
        cls = _unit_class_for_label(label)
        if cls is None:
            out[label] = desc  # fail-soft: keep visible
            continue
        cat = getattr(cls, "category", UnitCategory.INDUSTRIAL)
        if cat not in hidden:
            out[label] = desc
    return out


def unit_categories_for_persona(persona: str = "Academic") -> Dict[str, List[str]]:
    """Filter ``UNIT_CATEGORIES`` the same way as ``available_units_for_persona``.

    Returns a fresh dict — never mutates the module-level ``UNIT_CATEGORIES``.
    Categories that become empty after filtering are dropped from the
    output so the UI's unit-picker dropdown doesn't show empty sections.
    """
    visible = set(available_units_for_persona(persona).keys())
    out: Dict[str, List[str]] = {}
    for grp, labels in UNIT_CATEGORIES.items():
        kept = [lbl for lbl in labels if lbl in visible]
        if kept:
            out[grp] = kept
    return out


__all__ = [
    "AVAILABLE_UNITS",
    "UNIT_CATEGORIES",
    "_unit_class_for_label",
    "available_units_for_persona",
    "unit_categories_for_persona",
]
