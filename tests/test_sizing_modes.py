"""v1.6 Workstream D — equipment-sizing-mode contract tests.

Locks in:
* SizingMode enum (RATING / DESIGN / PERFORMANCE_CHECK) on BaseUnit.
* Default sizing_mode = RATING (preserves v1.5.3 behaviour).
* design_sizing() returns the documented keys for each unit shape:
    - Vessels (CSTR / Equilibrium / Gibbs / Stoichiometric / Flash):
      V_required_m3, residence_time_s, L_over_D, diameter_m, length_m
    - HX (NTU / Shell-Tube / 1D): A_required_m2, LMTD_K, dT_min_K
    - Pump: head_required_m, W_shaft_required_W, NPSH_margin_m
    - Compressor: W_shaft_required_W, n_stages_recommended, surge_margin_K
    - Tray column: column_height_m, column_diameter_m, downcomer load
    - Packed column: column_height_m, NTU, HTU_m
* Base-class no-op default: every other unit returns an empty dict.
"""

from __future__ import annotations

from typing import Dict

import pytest

from pse_ecosystem.models.base_unit import BaseUnit, SizingMode
from pse_ecosystem.models.heat_exchangers.heat_exchanger_1d import (
    HeatExchanger1D,
    HeatExchanger1DParams,
)
from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import (
    HeatExchangerNTU,
    HeatExchangerNTUParams,
)
from pse_ecosystem.models.heat_exchangers.shell_tube import (
    ShellTubeHX,
    ShellTubeParams,
)
from pse_ecosystem.models.pressure_changers.compressor import (
    Compressor,
    CompressorParams,
)
from pse_ecosystem.models.pressure_changers.pump import Pump, PumpParams
from pse_ecosystem.models.reactors.cstr_hf import (
    CSTRHF,
    CSTRHFParams,
    ReactionConfig,
)
from pse_ecosystem.models.reactors.equilibrium_reactor import (
    EquilReactorParams,
    EquilibriumReactor,
)
from pse_ecosystem.models.reactors.gibbs_reactor import (
    GibbsReactor,
    GibbsReactorParams,
)
from pse_ecosystem.models.reactors.stoichiometric_reactor import (
    StoichiometricParams,
    StoichiometricReactor,
)
from pse_ecosystem.models.separators.flash_vl_hf import (
    FlashVLHF,
    FlashVLHFParams,
)
from pse_ecosystem.models.separators.packed_column import (
    PackedColumnHF,
    PackedColumnHFParams,
)
from pse_ecosystem.models.separators.tray_column import (
    TrayColumnHF,
    TrayColumnHFParams,
)


# ─────────────────────────────────────────────────────────────────────────────
# Framework
# ─────────────────────────────────────────────────────────────────────────────


class TestSizingFramework:
    def test_enum_values(self):
        assert SizingMode.RATING.value == "rating"
        assert SizingMode.DESIGN.value == "design"
        assert SizingMode.PERFORMANCE_CHECK.value == "check"

    def test_default_sizing_mode_is_rating(self):
        assert BaseUnit.sizing_mode == SizingMode.RATING

    def test_base_design_sizing_default_is_empty(self):
        # An ad-hoc unit without an override should return empty.
        class Toy(BaseUnit):
            unit_id = "t"
            def variables(self): return []
            def bounds(self): return {}
            def residual(self, x): import numpy as np; return np.zeros(0)
            def objective_contribution(self, x): return {}

        assert Toy().design_sizing({}) == {}


# ─────────────────────────────────────────────────────────────────────────────
# Vessel sizing — CSTR / Equilibrium / Gibbs / Stoichiometric / Flash
# ─────────────────────────────────────────────────────────────────────────────


def _vessel_state(uid: str) -> Dict[str, float]:
    return {
        f"{uid}.inlet.F_H2": 1.0, f"{uid}.inlet.F_O2": 0.5,
        f"{uid}.inlet.F_H2O": 0.0,
        f"{uid}.inlet.T": 500.0, f"{uid}.inlet.P": 5.0e5,
        f"{uid}.outlet.F_H2": 0.2, f"{uid}.outlet.F_O2": 0.1,
        f"{uid}.outlet.F_H2O": 0.8,
        f"{uid}.outlet.T": 800.0, f"{uid}.outlet.P": 5.0e5,
    }


_VESSEL_KEYS = {
    "V_required_m3", "residence_time_s", "L_over_D",
    "diameter_m", "length_m",
}


class TestVesselSizing:
    def test_cstr_keys(self):
        rxn = ReactionConfig(
            stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
            k0=1e6, Ea_J_per_mol=80_000.0,
            reaction_orders={"H2": 2.0, "O2": 1.0},
        )
        u = CSTRHF("R", ["H2", "O2", "H2O"], CSTRHFParams(reactions=[rxn]))
        out = u.design_sizing(_vessel_state("R"))
        assert _VESSEL_KEYS <= set(out)
        assert out["V_required_m3"] > 0
        assert out["L_over_D"] == 2.0

    def test_equilibrium_keys(self):
        from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
        rxn = ReactionConfig(
            stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
            k0=1.0, Ea_J_per_mol=0.0,
            reaction_orders={"H2": 2.0, "O2": 1.0},
        )
        u = EquilibriumReactor(
            "R", ["H2", "O2", "H2O"],
            EquilReactorParams(reactions=[rxn], Keq_ref=[1e10]),
        )
        out = u.design_sizing(_vessel_state("R"))
        assert _VESSEL_KEYS <= set(out)
        assert out["V_required_m3"] > 0

    def test_gibbs_keys(self):
        u = GibbsReactor("R", ["H2", "O2", "H2O"], GibbsReactorParams())
        out = u.design_sizing(_vessel_state("R"))
        assert _VESSEL_KEYS <= set(out)

    def test_stoichiometric_keys(self):
        u = StoichiometricReactor(
            "R", ["H2", "O2", "H2O"],
            StoichiometricParams(
                stoichiometry={"H2": [-2.0], "O2": [-1.0], "H2O": [2.0]},
            ),
        )
        out = u.design_sizing(_vessel_state("R"))
        assert _VESSEL_KEYS <= set(out)

    def test_flash_keys(self):
        comps = ["benzene", "toluene"]
        u = FlashVLHF("f", comps, FlashVLHFParams(species_vle=comps))
        state = {
            "f.inlet.F_benzene": 0.5, "f.inlet.F_toluene": 0.5,
            "f.inlet.T": 370.0, "f.inlet.P": 101325.0,
        }
        out = u.design_sizing(state)
        assert _VESSEL_KEYS <= set(out)
        # Flash uses L/D = 3 (vertical drum heuristic)
        assert out["L_over_D"] == 3.0


# ─────────────────────────────────────────────────────────────────────────────
# HX sizing — NTU / Shell-Tube / 1D
# ─────────────────────────────────────────────────────────────────────────────


_HX_STATE = {
    "hx.hot_in.F_N2": 10.0, "hx.hot_in.T": 600.0, "hx.hot_in.P": 1.0e5,
    "hx.hot_out.F_N2": 10.0, "hx.hot_out.T": 450.0, "hx.hot_out.P": 1.0e5,
    "hx.cold_in.F_H2O": 5.0, "hx.cold_in.T": 300.0, "hx.cold_in.P": 1.0e5,
    "hx.cold_out.F_H2O": 5.0, "hx.cold_out.T": 380.0, "hx.cold_out.P": 1.0e5,
    "hx.Q": 5.0e4,
    "hx.effectiveness": 0.5, "hx.NTU": 2.0,
}


class TestHXSizing:
    def test_ntu_keys(self):
        u = HeatExchangerNTU("hx", ["N2"], ["H2O"], HeatExchangerNTUParams())
        out = u.design_sizing(_HX_STATE)
        assert "A_required_m2" in out and out["A_required_m2"] > 0
        assert "dT_min_K" in out

    def test_shell_tube_keys(self):
        u = ShellTubeHX("hx", ["N2"], ["H2O"], ShellTubeParams())
        out = u.design_sizing(_HX_STATE)
        for k in ("A_required_m2", "U_effective_W_per_m2_K",
                  "LMTD_K", "F_factor", "dT_min_K"):
            assert k in out
        assert out["A_required_m2"] > 0

    def test_1d_keys(self):
        u = HeatExchanger1D("hx", ["N2"], ["H2O"], HeatExchanger1DParams())
        out = u.design_sizing(_HX_STATE)
        for k in ("A_required_m2", "U_effective_W_per_m2_K",
                  "LMTD_K", "dT_min_K"):
            assert k in out

    def test_fouling_inflates_A_required(self):
        u_clean = ShellTubeHX("hx", ["N2"], ["H2O"], ShellTubeParams())
        u_foul = ShellTubeHX(
            "hx", ["N2"], ["H2O"],
            ShellTubeParams(
                R_f_tube_m2K_per_W=0.001, R_f_shell_m2K_per_W=0.001,
            ),
        )
        assert (
            u_foul.design_sizing(_HX_STATE)["A_required_m2"]
            > u_clean.design_sizing(_HX_STATE)["A_required_m2"]
        )


# ─────────────────────────────────────────────────────────────────────────────
# Turbomachinery — Pump + Compressor
# ─────────────────────────────────────────────────────────────────────────────


class TestPumpSizing:
    def test_keys(self):
        u = Pump("p", ["H2O"], PumpParams())
        state = {
            "p.inlet.F_H2O": 10.0, "p.inlet.T": 293.15, "p.inlet.P": 2.0e5,
            "p.outlet.F_H2O": 10.0, "p.outlet.T": 293.15, "p.outlet.P": 1.0e6,
            "p.W_shaft": 200.0,
        }
        out = u.design_sizing(state)
        for k in ("head_required_m", "W_shaft_required_W",
                  "V_flow_m3_per_s", "NPSHa_m", "NPSHr_m", "NPSH_margin_m"):
            assert k in out
        assert out["head_required_m"] > 0
        # NPSH margin positive at 2 bar suction (Psat = 2339 Pa, NPSHr = 3 m)
        assert out["NPSH_margin_m"] > 0


class TestCompressorSizing:
    def test_keys(self):
        u = Compressor("c", ["N2"], CompressorParams())
        state = {
            "c.inlet.F_N2": 1.0, "c.inlet.T": 300.0, "c.inlet.P": 1.0e5,
            "c.outlet.F_N2": 1.0, "c.outlet.T": 500.0, "c.outlet.P": 50.0e5,
            "c.W_shaft": 1.0e5,
        }
        out = u.design_sizing(state)
        for k in ("W_shaft_required_W", "compression_ratio",
                  "n_stages_recommended", "n_stages_specified",
                  "discharge_T_K", "surge_margin_K"):
            assert k in out
        # r_total = 50 → n_stages_rec = ceil(log(50)/log(4)) = ceil(2.82) = 3
        assert out["n_stages_recommended"] == 3.0


# ─────────────────────────────────────────────────────────────────────────────
# Columns — Tray + Packed
# ─────────────────────────────────────────────────────────────────────────────


class TestColumnSizing:
    def test_tray_column_keys(self):
        comps = ["benzene", "toluene"]
        u = TrayColumnHF(
            "tc", comps,
            TrayColumnHFParams(
                light_key="benzene", heavy_key="toluene",
                species_vle=comps,
            ),
        )
        state = {
            "tc.feed.F_benzene": 0.5, "tc.feed.F_toluene": 0.5,
            "tc.feed.T": 360.0, "tc.feed.P": 101325.0,
            "tc.distillate.F_benzene": 0.495,
            "tc.distillate.F_toluene": 0.005,
            "tc.distillate.T": 353.0,
            "tc.bottoms.F_benzene": 0.005,
            "tc.bottoms.F_toluene": 0.495,
            "tc.bottoms.T": 384.0,
            "tc.N_stages_theoretical": 12.0,
        }
        out = u.design_sizing(state)
        for k in ("N_stages_theoretical", "N_stages_real",
                  "column_height_m", "column_diameter_m",
                  "tray_spacing_m", "downcomer_load_m3_per_s"):
            assert k in out

    def test_packed_column_keys(self):
        u = PackedColumnHF(
            "pc",
            gas_components=["CO2", "N2"],
            liquid_components=["CO2", "H2O"],
            params=PackedColumnHFParams(solute="CO2"),
        )
        state = {
            "pc.gas_in.F_CO2": 0.1, "pc.gas_in.F_N2": 0.9,
            "pc.NTU": 4.0, "pc.Z_m": 2.4,
        }
        out = u.design_sizing(state)
        for k in ("column_height_m", "NTU", "HTU_m",
                  "column_diameter_m_required", "column_diameter_m_specified"):
            assert k in out
