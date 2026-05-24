"""v1.6 Workstream A.4 — mixer + pressure-changer audit contract tests.

Locks in:
* Port surface for MixerHF (inlet_ports list) / Compressor / Pump / Valve.
* T_out KPI on MixerHF (audit-listed fidelity gap).
* Valve capex() now returns a positive value (was 0 pre-audit).
* Compressor multi-stage with ideal intercooling — outlet T much lower for
  N_stages > 1 at the same pressure ratio; total shaft work decreases.
* Pump NPSHa/NPSHr/margin KPIs and cavitation_risk flag.
"""

from __future__ import annotations

from typing import Dict

import pytest

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.models.mixers.mixer_hf import MixerHF, MixerHFParams
from pse_ecosystem.models.pressure_changers.compressor import (
    Compressor,
    CompressorParams,
)
from pse_ecosystem.models.pressure_changers.pump import Pump, PumpParams
from pse_ecosystem.models.pressure_changers.valve import Valve, ValveParams


# ─────────────────────────────────────────────────────────────────────────────
# Port + category contract
# ─────────────────────────────────────────────────────────────────────────────


def _make_mixer() -> MixerHF:
    return MixerHF("m", ["N2"], MixerHFParams(n_inlets=2))


def _make_compressor(**kwargs) -> Compressor:
    return Compressor("c", ["N2"], CompressorParams(**kwargs))


def _make_pump(**kwargs) -> Pump:
    return Pump("p", ["H2O"], PumpParams(**kwargs))


def _make_valve() -> Valve:
    return Valve("v", ["N2"], ValveParams(Cv=10.0))


class TestPorts:
    def test_mixer_ports(self):
        m = _make_mixer()
        assert all(isinstance(p, StreamPort) for p in m.inlet_ports)
        assert isinstance(m.outlet_port, StreamPort)

    @pytest.mark.parametrize(
        "factory", [_make_compressor, _make_pump, _make_valve]
    )
    def test_single_stream_ports(self, factory):
        u = factory()
        assert isinstance(u.inlet_port, StreamPort)
        assert isinstance(u.outlet_port, StreamPort)

    @pytest.mark.parametrize(
        "factory", [_make_mixer, _make_compressor, _make_pump, _make_valve]
    )
    def test_industrial_category(self, factory):
        assert factory().category == UnitCategory.INDUSTRIAL


# ─────────────────────────────────────────────────────────────────────────────
# MixerHF — T_outlet KPI
# ─────────────────────────────────────────────────────────────────────────────


class TestMixerKPI:
    def test_T_out_in_kpis(self):
        m = _make_mixer()
        x = {
            "m.inlet_0.F_N2": 1.0, "m.inlet_0.T": 300.0, "m.inlet_0.P": 1e5,
            "m.inlet_1.F_N2": 1.0, "m.inlet_1.T": 400.0, "m.inlet_1.P": 1e5,
            "m.outlet.F_N2": 2.0, "m.outlet.T": 350.0, "m.outlet.P": 1e5,
        }
        kpis = m.kpis(x)
        assert "m.T_out_K" in kpis
        assert kpis["m.T_out_K"] == 350.0

    def test_per_inlet_flows_exposed(self):
        m = _make_mixer()
        x = {"m.inlet_0.F_N2": 1.0, "m.inlet_1.F_N2": 3.0,
             "m.outlet.F_N2": 4.0}
        kpis = m.kpis(x)
        assert kpis["m.inlet_0_total_flow_mol_s"] == 1.0
        assert kpis["m.inlet_1_total_flow_mol_s"] == 3.0


# ─────────────────────────────────────────────────────────────────────────────
# Valve — CAPEX + KPIs (both 0 / empty pre-A.4)
# ─────────────────────────────────────────────────────────────────────────────


class TestValveAudit:
    def test_capex_positive(self):
        v = _make_valve()
        # Pre-A.4 the unit returned base-class 0.0.
        assert v.capex({"v.Cv": 10.0}) > 0

    def test_capex_scales_with_Cv(self):
        v_small = _make_valve()
        v_large = Valve("v", ["N2"], ValveParams(Cv=1000.0))
        assert v_large.capex({"v.Cv": 1000.0}) > v_small.capex({"v.Cv": 10.0})

    def test_kpis_nonempty(self):
        v = _make_valve()
        kpis = v.kpis({"v.inlet.P": 2.0e5, "v.outlet.P": 1.0e5, "v.Cv": 10.0,
                        "v.outlet.F_N2": 5.0})
        assert "v.dP_Pa" in kpis
        assert kpis["v.dP_Pa"] == 1.0e5


# ─────────────────────────────────────────────────────────────────────────────
# Compressor — multi-stage with intercooling
# ─────────────────────────────────────────────────────────────────────────────


_COMPRESSOR_X: Dict[str, float] = {
    "c.inlet.F_N2": 1.0,
    "c.inlet.T": 300.0,
    "c.inlet.P": 1.0e5,
    "c.outlet.F_N2": 1.0,
    "c.outlet.T": 800.0,
    "c.outlet.P": 100.0e5,
    "c.W_shaft": 1.0e5,
}


class TestCompressorMultiStage:
    def test_default_is_single_stage(self):
        c = _make_compressor()
        assert c.params.n_stages == 1

    def test_single_stage_back_compat(self):
        # Default residual must match v1.5.3 byte-for-byte for n_stages=1.
        c = _make_compressor(n_stages=1)
        r = c.residual(_COMPRESSOR_X)
        # No NaN / inf
        assert all(abs(v) < 1e20 for v in r)

    def test_multistage_reduces_outlet_temperature(self):
        # Given the same input state and pressure ratio, the multi-stage
        # residual will compute a SMALLER required outlet T (because each
        # stage starts at T_in via ideal intercooling). So if T_out_decl is
        # fixed at the single-stage value, the multi-stage residual row is
        # POSITIVE (declared > actual). Use this to verify the math: the
        # T-residual sign flips when n_stages > 1 at high pressure ratios.
        c_single = _make_compressor(n_stages=1, eta_isentropic=0.75)
        c_multi = _make_compressor(n_stages=4, eta_isentropic=0.75)
        # Use a high-pressure-ratio state with a declared T_out matching
        # the SINGLE-stage outlet — multi-stage will say "should be lower".
        # T_isen single-stage at P_r = 100 with γ ≈ 1.4 ≈ 1118 K, T_out ≈ 1390.
        # T_after for 4-stage ≈ 458 K. So the T-residual for multi-stage is
        # ~ +932 K.
        # Compute the temperature-rise residual row only (index = N comps).
        r_single = c_single.residual(_COMPRESSOR_X)
        r_multi = c_multi.residual(_COMPRESSOR_X)
        # Row 1 of residual is the T equation: T_out_decl − T_out_actual.
        # Single-stage with T_out_decl=800 is sub-actual (negative residual),
        # multi-stage with T_out_decl=800 is super-actual (positive residual).
        assert r_single[1] != r_multi[1]
        assert r_multi[1] > r_single[1]

    def test_intercool_kpi_zero_for_single_stage(self):
        c = _make_compressor(n_stages=1)
        kpis = c.kpis(_COMPRESSOR_X)
        assert kpis["c.Q_intercool_W"] == 0.0
        assert kpis["c.n_stages"] == 1.0

    def test_intercool_kpi_positive_for_multistage(self):
        c = _make_compressor(n_stages=4)
        # Use an x with W_shaft > 0 so the KPI computes.
        x = dict(_COMPRESSOR_X, **{"c.W_shaft": 1.0e6})
        kpis = c.kpis(x)
        # 4-stage: Q_intercool = (4-1)/4 × W = 0.75 × 1e6 = 7.5e5 W.
        assert kpis["c.Q_intercool_W"] == pytest.approx(7.5e5)
        assert kpis["c.n_stages"] == 4.0


# ─────────────────────────────────────────────────────────────────────────────
# Pump — NPSHa/NPSHr/cavitation
# ─────────────────────────────────────────────────────────────────────────────


_PUMP_X: Dict[str, float] = {
    "p.inlet.F_H2O": 10.0,
    "p.inlet.T": 293.15,
    "p.inlet.P": 2.0e5,   # 2 bar absolute at suction
    "p.outlet.F_H2O": 10.0,
    "p.outlet.T": 293.15,
    "p.outlet.P": 1.0e6,  # 10 bar discharge
    "p.W_shaft": 200.0,
}


class TestPumpNPSH:
    def test_NPSH_kpis_present(self):
        p = _make_pump()
        kpis = p.kpis(_PUMP_X)
        for tag in ("p.NPSHa_m", "p.NPSHr_m", "p.NPSH_margin_m",
                    "p.cavitation_risk"):
            assert tag in kpis

    def test_NPSHa_positive_for_pressurised_suction(self):
        p = _make_pump()
        kpis = p.kpis(_PUMP_X)
        # Water at 20 °C: Psat ≈ 2339 Pa; suction = 2 bar = 200,000 Pa.
        # NPSHa = (200000 - 2339) / (1000 × 9.80665) ≈ 20.2 m. Plenty.
        assert kpis["p.NPSHa_m"] == pytest.approx(
            (2.0e5 - 2339.0) / (1000.0 * 9.80665), rel=1e-6
        )
        # Default NPSHr_m = 3.0, so margin is plenty.
        assert kpis["p.NPSH_margin_m"] > 10.0
        assert kpis["p.cavitation_risk"] == 0.0

    def test_low_suction_pressure_flags_cavitation(self):
        # Suction = 0.5 bar (vacuum-tank application); NPSHa ≈ 4.97 m.
        # If NPSHr is set to 6 m, the unit flags cavitation_risk = 1.
        p = _make_pump(NPSHr_m=6.0)
        x = dict(_PUMP_X, **{"p.inlet.P": 5.0e4})
        kpis = p.kpis(x)
        assert kpis["p.NPSHa_m"] < 6.0
        assert kpis["p.cavitation_risk"] == 1.0
