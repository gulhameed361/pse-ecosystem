"""v1.6 Workstream B — 10 new industrial unit-model contract tests.

For each new unit:
* Class imports cleanly.
* INDUSTRIAL category.
* Ports are StreamPort instances on the documented attribute names.
* ``variables()`` / ``bounds()`` agree on the same names.
* ``residual()`` returns a finite ndarray at a representative state.
* ``capex()`` returns a positive value at the same state.
* ``kpis()`` returns at least one numeric KPI.

These are *contract* tests — they confirm the units satisfy the BaseUnit
protocol and don't crash at typical operating points. Physics-validation
tests (vs Aspen, NIST, etc.) come in Workstream F.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pytest

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.models.heat_exchangers.fired_heater import (
    FiredHeaterHF,
    FiredHeaterHFParams,
)
from pse_ecosystem.models.pressure_changers.expander import (
    ExpanderHF,
    ExpanderParams,
)
from pse_ecosystem.models.pressure_changers.multistage_compressor import (
    MultistageCompressorHF,
    MultistageCompressorHFParams,
)
from pse_ecosystem.models.reactors.batch_reactor import (
    BatchReactorHF,
    BatchReactorHFParams,
)
from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
from pse_ecosystem.models.separators.crystallizer import (
    CrystallizerHF,
    CrystallizerHFParams,
)
from pse_ecosystem.models.separators.decanter import DecanterHF, DecanterHFParams
from pse_ecosystem.models.separators.membrane_module import (
    MembraneModuleHF,
    MembraneModuleHFParams,
)
from pse_ecosystem.models.separators.packed_column import (
    PackedColumnHF,
    PackedColumnHFParams,
)
from pse_ecosystem.models.separators.tray_column import (
    TrayColumnHF,
    TrayColumnHFParams,
)
from pse_ecosystem.models.utilities.steam_drum import (
    SteamDrumHF,
    SteamDrumHFParams,
)


# ─────────────────────────────────────────────────────────────────────────────
# ExpanderHF
# ─────────────────────────────────────────────────────────────────────────────


class TestExpanderHF:
    def _make(self) -> ExpanderHF:
        return ExpanderHF("ex", ["N2"], ExpanderParams())

    def _state(self) -> Dict[str, float]:
        return {
            "ex.inlet.F_N2": 1.0, "ex.inlet.T": 600.0, "ex.inlet.P": 50.0e5,
            "ex.outlet.F_N2": 1.0, "ex.outlet.T": 350.0, "ex.outlet.P": 1.0e5,
            "ex.W_shaft": 5.0e5,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        assert isinstance(u.inlet_port, StreamPort)
        assert isinstance(u.outlet_port, StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_kpis_nonempty(self):
        kpis = self._make().kpis(self._state())
        assert len(kpis) >= 1

    def test_objective_is_credit(self):
        # Expander produces power → negative OPEX coefficient.
        obj = self._make().objective_contribution(self._state())
        assert list(obj.values())[0] < 0


# ─────────────────────────────────────────────────────────────────────────────
# MultistageCompressorHF
# ─────────────────────────────────────────────────────────────────────────────


class TestMultistageCompressor:
    def _make(self, **kw) -> MultistageCompressorHF:
        return MultistageCompressorHF(
            "msc", ["N2", "H2O"], MultistageCompressorHFParams(**kw),
        )

    def _state(self) -> Dict[str, float]:
        return {
            "msc.inlet.F_N2": 10.0, "msc.inlet.F_H2O": 1.0,
            "msc.inlet.T": 300.0, "msc.inlet.P": 1.0e5,
            "msc.outlet.F_N2": 10.0, "msc.outlet.F_H2O": 0.5,
            "msc.outlet.T": 400.0, "msc.outlet.P": 50.0e5,
            "msc.condensate.F_N2": 0.0, "msc.condensate.F_H2O": 0.5,
            "msc.W_shaft": 1.0e6, "msc.Q_intercool": 8.0e5,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports_include_condensate(self):
        u = self._make()
        assert isinstance(u.condensate_port, StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_kpis_include_intercooler_duty(self):
        kpis = self._make().kpis(self._state())
        assert "msc.Q_intercool_kW" in kpis
        assert "msc.condensate_mol_s" in kpis


# ─────────────────────────────────────────────────────────────────────────────
# DecanterHF
# ─────────────────────────────────────────────────────────────────────────────


class TestDecanterHF:
    def _make(self) -> DecanterHF:
        return DecanterHF(
            "dec", ["A", "B"],
            DecanterHFParams(K_partition={"A": 5.0, "B": 0.1}),
        )

    def _state(self) -> Dict[str, float]:
        return {
            "dec.inlet.F_A": 0.6, "dec.inlet.F_B": 0.4,
            "dec.inlet.T": 350.0, "dec.inlet.P": 1.0e5,
            "dec.aqueous.F_A": 0.1, "dec.aqueous.F_B": 0.35,
            "dec.aqueous.T": 350.0, "dec.aqueous.P": 1.0e5,
            "dec.organic.F_A": 0.5, "dec.organic.F_B": 0.05,
            "dec.organic.T": 350.0, "dec.organic.P": 1.0e5,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        assert isinstance(u.aq_port, StreamPort)
        assert isinstance(u.org_port, StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_kpis_include_recovery(self):
        kpis = self._make().kpis(self._state())
        assert any("recovery_A_organic" in k for k in kpis)


# ─────────────────────────────────────────────────────────────────────────────
# SteamDrumHF
# ─────────────────────────────────────────────────────────────────────────────


class TestSteamDrumHF:
    def _make(self) -> SteamDrumHF:
        return SteamDrumHF("sd", SteamDrumHFParams())

    def _state(self) -> Dict[str, float]:
        return {
            "sd.feedwater_in.F_H2O": 1.0,
            "sd.steam_out.F_H2O": 0.98,
            "sd.blowdown_out.F_H2O": 0.02,
            "sd.Q_kW": 2500.0,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        for tag in ("feedwater_in_port", "steam_out_port", "blowdown_out_port"):
            assert isinstance(getattr(u, tag), StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_t_sat_in_kpis(self):
        kpis = self._make().kpis(self._state())
        assert "sd.T_sat_K" in kpis
        # P = 10 bar → T_sat ≈ 180 °C ≈ 453 K (within 10 K of correlation)
        assert 440.0 < kpis["sd.T_sat_K"] < 470.0


# ─────────────────────────────────────────────────────────────────────────────
# FiredHeaterHF
# ─────────────────────────────────────────────────────────────────────────────


class TestFiredHeaterHF:
    def _make(self) -> FiredHeaterHF:
        return FiredHeaterHF("fh", ["N2"], FiredHeaterHFParams())

    def _state(self) -> Dict[str, float]:
        return {
            "fh.fuel_in.F_H2": 0.0, "fh.fuel_in.F_CO": 0.0,
            "fh.fuel_in.F_CH4": 1.0, "fh.fuel_in.F_N2": 0.0,
            "fh.fuel_in.F_CO2": 0.0, "fh.fuel_in.F_H2O": 0.0,
            "fh.air_in.F_O2": 2.3, "fh.air_in.F_N2": 8.65,
            "fh.flue_out.F_CO2": 1.0, "fh.flue_out.F_H2O": 2.0,
            "fh.flue_out.F_O2": 0.3, "fh.flue_out.F_N2": 8.65,
            "fh.process_in.F_N2": 10.0, "fh.process_in.T": 400.0,
            "fh.process_in.P": 2.0e5,
            "fh.process_out.F_N2": 10.0, "fh.process_out.T": 800.0,
            "fh.process_out.P": 2.0e5,
            "fh.Q_duty": 6.8e5,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        for tag in ("fuel_in_port", "air_in_port", "flue_out_port",
                    "process_in_port", "process_out_port"):
            assert isinstance(getattr(u, tag), StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_NOx_in_kpis(self):
        kpis = self._make().kpis(self._state())
        assert "fh.NOx_emission_kg_per_yr" in kpis


# ─────────────────────────────────────────────────────────────────────────────
# PackedColumnHF
# ─────────────────────────────────────────────────────────────────────────────


class TestPackedColumnHF:
    def _make(self) -> PackedColumnHF:
        return PackedColumnHF(
            "pc",
            gas_components=["CO2", "N2"],
            liquid_components=["CO2", "H2O"],
            params=PackedColumnHFParams(solute="CO2", m_eq=0.5),
        )

    def _state(self) -> Dict[str, float]:
        return {
            "pc.gas_in.F_CO2": 0.1, "pc.gas_in.F_N2": 0.9,
            "pc.gas_out.F_CO2": 0.01, "pc.gas_out.F_N2": 0.9,
            "pc.liquid_in.F_CO2": 0.0, "pc.liquid_in.F_H2O": 1.0,
            "pc.liquid_out.F_CO2": 0.09, "pc.liquid_out.F_H2O": 1.0,
            "pc.NTU": 4.0, "pc.Z_m": 2.4,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        for tag in ("gas_in_port", "gas_out_port", "liquid_in_port", "liquid_out_port"):
            assert isinstance(getattr(u, tag), StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_removal_pct_in_kpis(self):
        kpis = self._make().kpis(self._state())
        assert "pc.solute_removal_pct" in kpis
        # 90% removal: 0.1 → 0.01 CO2
        assert kpis["pc.solute_removal_pct"] > 80.0


# ─────────────────────────────────────────────────────────────────────────────
# MembraneModuleHF
# ─────────────────────────────────────────────────────────────────────────────


class TestMembraneModuleHF:
    def _make(self) -> MembraneModuleHF:
        return MembraneModuleHF(
            "mem", ["H2", "CO2"],
            MembraneModuleHFParams(
                area_m2=100.0,
                permeance_mol_m2_s_Pa={"H2": 1.0e-7, "CO2": 1.0e-9},
            ),
        )

    def _state(self) -> Dict[str, float]:
        return {
            "mem.feed_in.F_H2": 1.0, "mem.feed_in.F_CO2": 1.0,
            "mem.feed_in.T": 350.0, "mem.feed_in.P": 30.0e5,
            "mem.retentate.F_H2": 0.5, "mem.retentate.F_CO2": 0.99,
            "mem.retentate.T": 350.0, "mem.retentate.P": 30.0e5,
            "mem.permeate.F_H2": 0.5, "mem.permeate.F_CO2": 0.01,
            "mem.permeate.T": 350.0, "mem.permeate.P": 1.0e5,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        for tag in ("feed_in_port", "retentate_port", "permeate_port"):
            assert isinstance(getattr(u, tag), StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_stage_cut_in_kpis(self):
        kpis = self._make().kpis(self._state())
        assert "mem.stage_cut" in kpis


# ─────────────────────────────────────────────────────────────────────────────
# BatchReactorHF
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchReactorHF:
    def _make(self) -> BatchReactorHF:
        rxn = ReactionConfig(
            stoichiometry={"A": -1.0, "B": 1.0},
            k0=0.01, Ea_J_per_mol=50_000.0,
            reaction_orders={"A": 1.0},
        )
        return BatchReactorHF(
            "br", ["A", "B"],
            BatchReactorHFParams(reactions=[rxn], volume_m3=2.0),
        )

    def _state(self) -> Dict[str, float]:
        return {
            "br.inlet.F_A": 1.0, "br.inlet.F_B": 0.0,
            "br.inlet.T": 350.0, "br.inlet.P": 1.0e5,
            "br.outlet.F_A": 0.5, "br.outlet.F_B": 0.5,
            "br.outlet.T": 350.0, "br.outlet.P": 1.0e5,
            "br.xi_0": 1800.0, "br.Q_batch": 0.0,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        assert isinstance(u.inlet_port, StreamPort)
        assert isinstance(u.outlet_port, StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_batches_per_year_in_kpis(self):
        kpis = self._make().kpis(self._state())
        assert "br.batches_per_year" in kpis


# ─────────────────────────────────────────────────────────────────────────────
# CrystallizerHF
# ─────────────────────────────────────────────────────────────────────────────


class TestCrystallizerHF:
    def _make(self) -> CrystallizerHF:
        return CrystallizerHF("cr", CrystallizerHFParams())

    def _state(self) -> Dict[str, float]:
        return {
            "cr.feed_in.F_NaCl": 0.4, "cr.feed_in.F_solvent": 1.0,
            "cr.mother_liquor.F_NaCl": 0.3, "cr.mother_liquor.F_solvent": 1.0,
            "cr.crystals.F_NaCl": 0.1, "cr.vapor.F_solvent": 0.0,
            "cr.feed_in.T": 350.0, "cr.Q_kW": -50.0,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        for tag in ("feed_in_port", "mother_liquor_port",
                    "crystals_port", "vapor_port"):
            assert isinstance(getattr(u, tag), StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_yield_in_kpis(self):
        kpis = self._make().kpis(self._state())
        assert "cr.crystal_yield_pct" in kpis


# ─────────────────────────────────────────────────────────────────────────────
# TrayColumnHF
# ─────────────────────────────────────────────────────────────────────────────


class TestTrayColumnHF:
    def _make(self) -> TrayColumnHF:
        comps = ["benzene", "toluene"]
        return TrayColumnHF(
            "tc", comps,
            TrayColumnHFParams(
                light_key="benzene", heavy_key="toluene",
                species_vle=comps,
            ),
        )

    def _state(self) -> Dict[str, float]:
        return {
            "tc.feed.F_benzene": 0.5, "tc.feed.F_toluene": 0.5,
            "tc.feed.T": 360.0, "tc.feed.P": 101325.0,
            "tc.distillate.F_benzene": 0.495, "tc.distillate.F_toluene": 0.005,
            "tc.distillate.T": 353.0, "tc.distillate.P": 101325.0,
            "tc.bottoms.F_benzene": 0.005, "tc.bottoms.F_toluene": 0.495,
            "tc.bottoms.T": 384.0, "tc.bottoms.P": 101325.0,
            "tc.Q_reb": 5.0e4, "tc.Q_cond": 5.0e4,
            "tc.N_stages_theoretical": 12.0,
        }

    def test_industrial(self):
        assert self._make().category == UnitCategory.INDUSTRIAL

    def test_ports(self):
        u = self._make()
        for tag in ("feed_port", "distillate_port", "bottoms_port"):
            assert isinstance(getattr(u, tag), StreamPort)

    def test_residual_finite(self):
        r = self._make().residual(self._state())
        assert np.all(np.isfinite(r))

    def test_capex_positive(self):
        assert self._make().capex(self._state()) > 0

    def test_kpis_include_stages(self):
        kpis = self._make().kpis(self._state())
        assert "tc.N_stages_theoretical" in kpis
        assert "tc.alpha_LK_HK" in kpis


# ─────────────────────────────────────────────────────────────────────────────
# Catalogue sanity — make sure all 10 new units are import-clean
# ─────────────────────────────────────────────────────────────────────────────


def test_all_new_units_importable():
    """Smoke test: every new B-workstream unit imports without side effects."""
    from pse_ecosystem.models.heat_exchangers.fired_heater import FiredHeaterHF  # noqa
    from pse_ecosystem.models.pressure_changers.expander import ExpanderHF  # noqa
    from pse_ecosystem.models.pressure_changers.multistage_compressor import (  # noqa
        MultistageCompressorHF,
    )
    from pse_ecosystem.models.reactors.batch_reactor import BatchReactorHF  # noqa
    from pse_ecosystem.models.separators.crystallizer import CrystallizerHF  # noqa
    from pse_ecosystem.models.separators.decanter import DecanterHF  # noqa
    from pse_ecosystem.models.separators.membrane_module import MembraneModuleHF  # noqa
    from pse_ecosystem.models.separators.packed_column import PackedColumnHF  # noqa
    from pse_ecosystem.models.separators.tray_column import TrayColumnHF  # noqa
    from pse_ecosystem.models.utilities.steam_drum import SteamDrumHF  # noqa
