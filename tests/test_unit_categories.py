"""Tests for the v1.6 UnitCategory classification.

Locks in the category attribute on every existing unit so a future refactor
that drops the field on a subclass — or accidentally re-tags an industrial
unit as didactic — fails CI.
"""

from __future__ import annotations

import pytest

from pse_ecosystem.models.base_unit import BaseUnit, UnitCategory


def test_enum_values():
    assert UnitCategory.INDUSTRIAL.value == "industrial"
    assert UnitCategory.SCREENING.value == "screening"
    assert UnitCategory.DIDACTIC.value == "didactic"
    assert UnitCategory.LEGACY.value == "legacy"


def test_string_comparison_works():
    """UnitCategory inherits ``str`` so legacy string comparisons keep working."""
    assert UnitCategory.INDUSTRIAL == "industrial"
    assert UnitCategory.DIDACTIC == "didactic"


def test_base_default_is_industrial():
    assert BaseUnit.category == UnitCategory.INDUSTRIAL


# ─────────────────────────────────────────────────────────────────────────────
# DIDACTIC: toy units
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "import_path, class_name",
    [
        ("pse_ecosystem.models.reactor.cstr_toy", "CSTRToy"),
        ("pse_ecosystem.models.separator.flash_toy", "FlashToy"),
        ("pse_ecosystem.models.heat_exchanger.heat_exchanger_toy", "HeatExchangerToy"),
        ("pse_ecosystem.models.heat_exchanger.boiler_toy", "BoilerToy"),
        ("pse_ecosystem.models.mixer.ideal_mixer", "IdealMixer"),
        ("pse_ecosystem.models.gasification.gasifier_toy", "GasifierToy"),
        ("pse_ecosystem.models.electrolysis.pem_toy", "PEMToy"),
    ],
)
def test_toy_units_are_didactic(import_path, class_name):
    mod = __import__(import_path, fromlist=[class_name])
    cls = getattr(mod, class_name)
    assert cls.category == UnitCategory.DIDACTIC, (
        f"{class_name} should be DIDACTIC, got {cls.category}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SCREENING: shortcut models
# ─────────────────────────────────────────────────────────────────────────────


def test_distillation_hf_is_screening():
    from pse_ecosystem.models.separators.distillation_hf import DistillationHF

    assert DistillationHF.category == UnitCategory.SCREENING


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY: HDA black-box wrappers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "import_path, class_name",
    [
        ("pse_ecosystem.models.reactor.hda_pfr", "HDAPFRUnit"),
        ("pse_ecosystem.models.separator.hda_flash", "HDAFlashUnit"),
        ("pse_ecosystem.models.distillation.hda_column", "HDADistillationUnit"),
    ],
)
def test_hda_wrappers_are_legacy(import_path, class_name):
    mod = __import__(import_path, fromlist=[class_name])
    cls = getattr(mod, class_name)
    assert cls.category == UnitCategory.LEGACY


# ─────────────────────────────────────────────────────────────────────────────
# INDUSTRIAL: all HF / reactor / DAC / biomass / pressure-changer units
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "import_path, class_name",
    [
        ("pse_ecosystem.models.reactors.cstr_hf", "CSTRHF"),
        ("pse_ecosystem.models.reactors.pfr_hf", "PFRHF"),
        ("pse_ecosystem.models.reactors.gibbs_reactor", "GibbsReactor"),
        ("pse_ecosystem.models.reactors.equilibrium_reactor", "EquilibriumReactor"),
        ("pse_ecosystem.models.reactors.stoichiometric_reactor", "StoichiometricReactor"),
        ("pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu", "HeatExchangerNTU"),
        ("pse_ecosystem.models.heat_exchangers.shell_tube", "ShellTubeHX"),
        ("pse_ecosystem.models.heat_exchangers.heat_exchanger_1d", "HeatExchanger1D"),
        ("pse_ecosystem.models.heat_exchangers.cooler_hf", "CoolerHF"),
        ("pse_ecosystem.models.separators.flash_vl_hf", "FlashVLHF"),
        ("pse_ecosystem.models.separators.separator_hf", "SeparatorHF"),
        ("pse_ecosystem.models.separators.flash_sl", "FlashSL"),
        ("pse_ecosystem.models.mixers.mixer_hf", "MixerHF"),
        ("pse_ecosystem.models.pressure_changers.compressor", "Compressor"),
        ("pse_ecosystem.models.pressure_changers.pump", "Pump"),
        ("pse_ecosystem.models.pressure_changers.valve", "Valve"),
        ("pse_ecosystem.models.biomass.biomass_storage", "BiomassStorageHF"),
        ("pse_ecosystem.models.biomass.biomass_gasifier", "BiomassGasifierHF"),
        ("pse_ecosystem.models.biomass.wgs_reactor", "WGSReactorHF"),
        ("pse_ecosystem.models.biomass.h2_separator", "H2SeparatorPSA"),
        ("pse_ecosystem.models.dac.tvsa_contactor", "TVSAContactor"),
        ("pse_ecosystem.models.dac.electrolyser_hf", "ElectrolyserHF"),
        ("pse_ecosystem.models.dac.methanation_reactor", "MethanationReactor"),
        ("pse_ecosystem.models.power.chp_unit", "CHPUnit"),
    ],
)
def test_industrial_units_default(import_path, class_name):
    mod = __import__(import_path, fromlist=[class_name])
    cls = getattr(mod, class_name)
    assert cls.category == UnitCategory.INDUSTRIAL, (
        f"{class_name} should be INDUSTRIAL, got {cls.category}"
    )
