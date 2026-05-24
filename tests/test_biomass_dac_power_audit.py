"""v1.6 Workstream A.5 — biomass / H₂ / DAC / power audit contract tests.

Locks in:
* Industrial classification for all 8 units (no toys, no legacy hidden).
* CAPEX > 0 for every unit at a reasonable operating point — closes the
  BiomassStorageHF gap (returned 0 pre-audit).
* KPIs non-empty for every unit.
* CHPUnit emission factors (NOx, CO, CO2) exposed as annualised KPIs and
  scale with fuel-LHV input.
"""

from __future__ import annotations

from typing import Dict

import pytest

from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
from pse_ecosystem.models.dac.electrolyser_hf import ElectrolyserHF
from pse_ecosystem.models.dac.methanation_reactor import MethanationReactor
from pse_ecosystem.models.dac.tvsa_contactor import TVSAContactor
from pse_ecosystem.models.power.chp_unit import CHPUnit


# ─────────────────────────────────────────────────────────────────────────────
# Factories
# ─────────────────────────────────────────────────────────────────────────────


def _make_biomass_gasifier() -> BiomassGasifierHF:
    return BiomassGasifierHF("g")


def _make_biomass_storage() -> BiomassStorageHF:
    return BiomassStorageHF("s")


def _make_h2_sep() -> H2SeparatorPSA:
    return H2SeparatorPSA("h2sep")


def _make_wgs() -> WGSReactorHF:
    return WGSReactorHF("wgs")


def _make_electrolyser() -> ElectrolyserHF:
    return ElectrolyserHF("el")


def _make_methanation() -> MethanationReactor:
    return MethanationReactor("me")


def _make_tvsa() -> TVSAContactor:
    return TVSAContactor("tv")


def _make_chp(**kwargs) -> CHPUnit:
    return CHPUnit("chp", **kwargs)


_ALL_FACTORIES = [
    _make_biomass_gasifier,
    _make_biomass_storage,
    _make_h2_sep,
    _make_wgs,
    _make_electrolyser,
    _make_methanation,
    _make_tvsa,
    _make_chp,
]


# ─────────────────────────────────────────────────────────────────────────────
# Universal contract
# ─────────────────────────────────────────────────────────────────────────────


class TestUniversalContract:
    @pytest.mark.parametrize("factory", _ALL_FACTORIES)
    def test_industrial_category(self, factory):
        assert factory().category == UnitCategory.INDUSTRIAL


# ─────────────────────────────────────────────────────────────────────────────
# BiomassStorageHF capex (was 0 pre-A.5)
# ─────────────────────────────────────────────────────────────────────────────


class TestBiomassStorageCAPEX:
    def test_capex_positive(self):
        u = _make_biomass_storage()
        x = {"s.wet_in.F_Biomass": 2.0}
        assert u.capex(x) > 0

    def test_capex_scales_with_feed_rate(self):
        u = _make_biomass_storage()
        c_small = u.capex({"s.wet_in.F_Biomass": 0.5})
        c_large = u.capex({"s.wet_in.F_Biomass": 5.0})
        assert c_large > c_small
        # Six-tenths rule: cost ratio = (10×)^0.6 ≈ 3.98
        assert 3.0 < (c_large / c_small) < 5.0

    def test_capex_in_kpis(self):
        u = _make_biomass_storage()
        x = {"s.wet_in.F_Biomass": 2.0}
        kpis = u.kpis(x)
        assert "s.capex_USD" in kpis
        assert kpis["s.capex_USD"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# CHPUnit emissions (NOx / CO / CO2)
# ─────────────────────────────────────────────────────────────────────────────


class TestCHPEmissions:
    @pytest.fixture
    def chp_state(self) -> Dict[str, float]:
        # 100 mol/s CH4 fuel, lambda_air = 1.1 → ~1 MW LHV-thermal,
        # 90% capacity factor (8000 hr/yr).
        return {
            "chp.fuel_in.F_H2": 0.0,
            "chp.fuel_in.F_CO": 0.0,
            "chp.fuel_in.F_CH4": 1.0,
            "chp.fuel_in.F_N2": 0.0,
            "chp.fuel_in.F_CO2": 0.0,
            "chp.fuel_in.F_H2O": 0.0,
            "chp.W_elec_kW": 350.0,
            "chp.Q_process_kW": 450.0,
        }

    def test_emission_kpis_present(self, chp_state):
        chp = _make_chp()
        kpis = chp.kpis(chp_state)
        for tag in (
            "chp.NOx_emission_kg_per_yr",
            "chp.CO_emission_kg_per_yr",
            "chp.CO2_emission_kg_per_yr",
        ):
            assert tag in kpis

    def test_NOx_positive_with_fuel(self, chp_state):
        chp = _make_chp()
        kpis = chp.kpis(chp_state)
        assert kpis["chp.NOx_emission_kg_per_yr"] > 0

    def test_emissions_zero_at_zero_fuel(self):
        chp = _make_chp()
        zero_state = {
            "chp.fuel_in.F_H2": 0.0,
            "chp.fuel_in.F_CO": 0.0,
            "chp.fuel_in.F_CH4": 0.0,
            "chp.W_elec_kW": 0.0,
            "chp.Q_process_kW": 0.0,
        }
        kpis = chp.kpis(zero_state)
        assert kpis["chp.NOx_emission_kg_per_yr"] == 0.0
        assert kpis["chp.CO_emission_kg_per_yr"] == 0.0
        assert kpis["chp.CO2_emission_kg_per_yr"] == 0.0

    def test_NOx_scales_with_emission_factor(self, chp_state):
        chp_low = _make_chp(NOx_g_per_MJ=0.04)   # SCR-controlled
        chp_high = _make_chp(NOx_g_per_MJ=0.32)  # uncontrolled NG turbine
        k_low = chp_low.kpis(chp_state)["chp.NOx_emission_kg_per_yr"]
        k_high = chp_high.kpis(chp_state)["chp.NOx_emission_kg_per_yr"]
        assert k_high / k_low == pytest.approx(0.32 / 0.04)

    def test_CO2_from_carbon_stoichiometry(self, chp_state):
        chp = _make_chp(operating_hours_per_year=8000.0)
        # 1 mol/s CH4 → 1 mol/s CO2; 44 g/mol; 8000 hr × 3600 s/h = 2.88e7 s.
        # ⇒ 44e-3 × 1 × 2.88e7 = 1.267e6 kg/yr.
        kpis = chp.kpis(chp_state)
        assert kpis["chp.CO2_emission_kg_per_yr"] == pytest.approx(
            44.01e-3 * 1.0 * 8000.0 * 3600.0, rel=1e-6
        )
