"""Flowsheet optimisation tests — v0.1.0 unit library + weather integration.

Covers:
  1. Multi-unit flowsheet (Mixer -> CSTR) connected via Connection
  2. HeatExchangerToy energy balance and effectiveness
  3. FlashToy component balance and K-value
  4. BoilerToy linear short-circuit
  5. Solar profile fetched for Surrey UK (pvlib)
  6. Weather-driven PEM cost optimisation at peak solar hour
  7. CompositeUnit wraps inner flowsheet, outer SLP solves
  8. HDAPFRUnit: reactor outputs are consistent with BB1 physics
  9. Wegstein TearStreamConfig declared (no-op on non-recycle flowsheet)
"""

from __future__ import annotations

import pytest
import numpy as np


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def lp_solver():
    from pse_ecosystem.solvers.lp_builder import select_lp_solver
    try:
        return select_lp_solver()
    except RuntimeError as exc:
        pytest.skip(f"No LP solver available: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Mixer -> CSTR connected via Connection
# ─────────────────────────────────────────────────────────────────────────────

def test_mixer_to_cstr_flowsheet(lp_solver):
    """IdealMixer outlet feeds a CSTRToy via a Connection equality."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
    from pse_ecosystem.models.mixer.ideal_mixer import IdealMixer
    from pse_ecosystem.models.reactor.cstr_toy import CSTRToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    mixer = IdealMixer("mix", n_inlets=2, components=("A",))
    cstr  = CSTRToy("cstr", k=0.5, F_total_nom=10.0)

    flowsheet = BaseFlowsheet(
        name="mixer_cstr",
        units=[mixer, cstr],
        connections=[Connection("mix.F_out_A", "cstr.F_A_in",
                                "mixer outlet to CSTR inlet")],
    )
    # Fix inlet flows: stream 0 = 5 mol/s, stream 1 = 3 mol/s
    flowsheet.extra_equalities.append(({"mix.F_in_0_A": 1.0}, 5.0))
    flowsheet.extra_equalities.append(({"mix.F_in_1_A": 1.0}, 3.0))
    # Fix reactor volume
    flowsheet.extra_equalities.append(({"cstr.V_reactor": 1.0}, 10.0))

    # Provide an initial guess near the solution — midpoint bounds are far off
    # when extra_equalities pin variables to small values (F≈8, V=10 vs midpoints 5e5, 250).
    x0 = {
        "mix.F_in_0_A": 5.0,  "mix.F_in_1_A": 3.0,  "mix.F_out_A": 8.0,
        "cstr.F_A_in":  8.0,  "cstr.F_A_out": 6.0,   "cstr.F_B_out": 2.0,
        "cstr.V_reactor": 10.0,
    }
    result = SLPDriver(flowsheet, SLPConfig(max_iter=50, eps_f=1e-3)).run(x0=x0)

    assert result.status == SolverStatus.CONVERGED, f"Status: {result.status} — {result.message}"
    # Mixer mass balance: F_out_A == 5 + 3 = 8
    assert result.x["mix.F_out_A"] == pytest.approx(8.0, abs=1e-2)
    assert result.x["cstr.F_A_in"] == pytest.approx(8.0, abs=1e-2)
    # CSTR physics: F_A_in - F_A_out - k*V*(F_A_out/F_total_nom) = 0
    F_Aout = result.x["cstr.F_A_out"]
    V      = result.x["cstr.V_reactor"]
    residual_check = 8.0 - F_Aout - 0.5 * V * (F_Aout / 10.0)
    assert abs(residual_check) < 0.05
    # B balance: F_B_out = k*V*(F_A_out/F_total_nom)
    F_Bout = result.x["cstr.F_B_out"]
    assert F_Bout == pytest.approx(8.0 - F_Aout, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: HeatExchangerToy — energy balance
# ─────────────────────────────────────────────────────────────────────────────

def test_heat_exchanger_energy_balance(lp_solver):
    """HX energy balance: Q == m_hot*Cp_hot*(T_hot_in - T_hot_out)."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.heat_exchanger.heat_exchanger_toy import HeatExchangerToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    hx = HeatExchangerToy("hx", params=None)

    fs = BaseFlowsheet("hx_only", units=[hx])
    # Pin two temperatures to give the system 2 DOF -> determined
    fs.extra_equalities.append(({"hx.T_hot_in":  1.0}, 380.0))
    fs.extra_equalities.append(({"hx.T_cold_in": 1.0}, 290.0))

    result = SLPDriver(fs, SLPConfig(max_iter=60, eps_f=1e-2)).run()

    assert result.status == SolverStatus.CONVERGED, f"Status: {result.status} — {result.message}"
    T_hi  = result.x["hx.T_hot_in"]
    T_ho  = result.x["hx.T_hot_out"]
    T_ci  = result.x["hx.T_cold_in"]
    T_co  = result.x["hx.T_cold_out"]
    Q     = result.x["hx.Q"]
    p     = hx.params

    # Hot-side energy balance
    assert Q == pytest.approx(p.m_hot * p.Cp_hot * (T_hi - T_ho), abs=Q * 0.01 + 1.0)
    # Cold-side energy balance
    assert Q == pytest.approx(p.m_cold * p.Cp_cold * (T_co - T_ci), abs=Q * 0.01 + 1.0)
    # Heat flows from hot to cold: T_ho < T_hi, T_co > T_ci
    assert T_ho < T_hi
    assert T_co > T_ci
    assert Q > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: FlashToy — component balance and K-value relation
# ─────────────────────────────────────────────────────────────────────────────

def test_flash_component_balance_and_kvalue(lp_solver):
    """Flash mole balance holds and y_A = K * x_A at convergence."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.separator.flash_toy import FlashToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    flash = FlashToy("flash", K_A_ref=3.0)  # A strongly favours vapour
    fs = BaseFlowsheet("flash_only", units=[flash])
    fs.extra_equalities.append(({"flash.F_in": 1.0}, 10.0))
    fs.extra_equalities.append(({"flash.z_A":  1.0}, 0.4))

    # Provide an initial guess near the solution.
    # At F_in=10, z_A=0.4, K=3: analytical solution is F_V=5, F_L=5, y_A=0.6, x_A=0.2
    x0 = {"flash.F_in": 10.0, "flash.z_A": 0.4,
          "flash.F_V": 5.0, "flash.F_L": 5.0,
          "flash.y_A": 0.6, "flash.x_A": 0.2}
    result = SLPDriver(fs, SLPConfig(max_iter=60, eps_f=1e-3)).run(x0=x0)

    assert result.status == SolverStatus.CONVERGED, f"Status: {result.status} — {result.message}"
    F_V = result.x["flash.F_V"]
    F_L = result.x["flash.F_L"]
    y_A = result.x["flash.y_A"]
    x_A = result.x["flash.x_A"]

    # Total mole balance
    assert F_V + F_L == pytest.approx(10.0, abs=0.05)
    # K-value: y_A = 3 * x_A
    assert y_A == pytest.approx(3.0 * x_A, abs=0.02)
    # A enriched in vapour (K > 1)
    assert y_A > x_A
    # Flows positive
    assert F_V > 0.0 and F_L > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: BoilerToy — linear unit, single LP iteration
# ─────────────────────────────────────────────────────────────────────────────

def test_boiler_toy_linear_shortcircuit(lp_solver):
    """BoilerToy is linear: SLP short-circuits to a single LP solve."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.heat_exchanger.boiler_toy import BoilerToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    boiler = BoilerToy("boiler")
    fs = BaseFlowsheet("boiler_only", units=[boiler])
    # Pin fuel flow: 10 kg/s
    fs.extra_equalities.append(({"boiler.F_fuel": 1.0}, 10.0))

    result = SLPDriver(fs, SLPConfig()).run()

    assert result.status == SolverStatus.CONVERGED
    assert result.iterations == 1, f"Linear unit must short-circuit; got {result.iterations}"

    p = boiler.params
    Q     = result.x["boiler.Q_out"]
    steam = result.x["boiler.F_steam"]
    assert Q == pytest.approx(p.eta * p.LHV * 10.0, abs=1.0)
    assert steam == pytest.approx(Q / p.h_steam, abs=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Solar profile — pvlib clearsky (skip if pvlib not installed)
# ─────────────────────────────────────────────────────────────────────────────

def test_solar_profile_shape_and_sign():
    """fetch_solar_profile returns 8760 non-negative values for a UK site."""
    pytest.importorskip("pvlib", reason="pvlib not installed")
    from pse_ecosystem.data.weather import SiteData, fetch_solar_profile

    site = SiteData(latitude=51.24, longitude=-0.59, altitude=50,
                    timezone="Europe/London", name="Surrey_UK")
    ghi = fetch_solar_profile(site, year=2023)

    assert ghi.shape == (8760,), f"Expected 8760 hourly values, got {ghi.shape}"
    assert ghi.min() >= 0.0, "GHI must be non-negative"
    assert ghi.max() > 100.0, "Peak GHI for UK should exceed 100 W/m2"
    # Summer midday should have positive GHI (June 21 ≈ hour 3636)
    assert ghi[3636] > 0.0, "June noon GHI should be positive for Surrey"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Weather-driven PEM cost optimisation
# ─────────────────────────────────────────────────────────────────────────────

def test_weather_driven_pem_optimisation(lp_solver):
    """Optimise PEM at the cheapest solar hour; electricity price < baseline."""
    pytest.importorskip("pvlib", reason="pvlib not installed")
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.data.weather import (
        SiteData,
        WeatherDrivenFlowsheet,
        electricity_price_from_solar,
        fetch_solar_profile,
        generate_demand_profile,
    )
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    site = SiteData(51.24, -0.59, 50, "Europe/London", "Surrey_UK")
    ghi    = fetch_solar_profile(site, 2023)
    prices = electricity_price_from_solar(ghi, base_price=0.10, solar_discount=0.05)

    # Sanity: prices clipped to [0.01, 0.15]
    assert prices.min() >= 0.01
    assert prices.max() <= 0.15

    # Build a weather-driven flowsheet container
    wdf = WeatherDrivenFlowsheet(
        name="solar_pem",
        base_flowsheet=make_electrolysis_only(100.0),
        solar_ghi=ghi,
        electricity_prices=prices,
        h2_demand=generate_demand_profile(50.0),
    )
    # Solve at cheapest solar hour
    solar_hour = int(np.argmax(ghi))
    fs = wdf.make_pem_snapshot_flowsheet(hour=solar_hour, h2_demand_override=50.0)
    result = SLPDriver(fs, SLPConfig(max_iter=10)).run()

    assert result.status == SolverStatus.CONVERGED
    assert result.x["pem.h2_kg_per_h"] == pytest.approx(50.0, abs=1e-3)
    # Price at peak solar hour must be below baseline
    assert float(prices[solar_hour]) < 0.10


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: CompositeUnit wraps HX flowsheet
# ─────────────────────────────────────────────────────────────────────────────

def test_composite_unit_wraps_heat_exchanger(lp_solver):
    """CompositeUnit: outer SLP drives T_hot_in; inner HX solves to convergence."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, CompositeUnit
    from pse_ecosystem.models.heat_exchanger.heat_exchanger_toy import HeatExchangerToy
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver

    hx = HeatExchangerToy("inner_hx")
    inner_fs = BaseFlowsheet("inner_hx_fs", units=[hx])
    inner_fs.extra_equalities.append(({"inner_hx.T_cold_in": 1.0}, 290.0))

    composite = CompositeUnit(
        unit_id="comp_hx",
        inner_flowsheet=inner_fs,
        exposed_inputs=["inner_hx.T_hot_in"],
        exposed_outputs=["inner_hx.T_hot_out", "inner_hx.Q"],
        slp_config=SLPConfig(max_iter=40, verbose=False),
    )

    outer_fs = BaseFlowsheet("outer_fs", units=[composite])
    outer_fs.extra_equalities.append(({"inner_hx.T_hot_in": 1.0}, 380.0))

    result = SLPDriver(outer_fs, SLPConfig(max_iter=20, eps_f=1e-2)).run()

    assert result.status == SolverStatus.CONVERGED, f"Status: {result.status} — {result.message}"
    T_hi  = result.x.get("inner_hx.T_hot_in",  0.0)
    T_ho  = result.x.get("inner_hx.T_hot_out", 0.0)
    Q     = result.x.get("inner_hx.Q",         0.0)
    assert T_ho < T_hi, f"Hot outlet {T_ho:.1f} K must be below inlet {T_hi:.1f} K"
    assert Q > 0.0, f"Heat duty must be positive, got {Q}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: HDAPFRUnit — black-box reactor physics
# ─────────────────────────────────────────────────────────────────────────────

def test_hda_pfr_unit_physics():
    """HDAPFRUnit.residual() == 0 when outputs equal HDA_Reactor_sim(inputs)."""
    from pse_ecosystem.models._blackbox.hda_reactor_bb import HDA_Reactor_sim
    from pse_ecosystem.models.reactor.hda_pfr import HDAPFRUnit

    unit = HDAPFRUnit("pfr")
    # Nominal HDA operating point
    inputs = dict(
        F_H2_in=3.0, F_CH4_in=0.5, F_Tol_in=0.6, F_Benz_in=0.02,
        T_in=894.0, V_R=3.0,
    )
    sim_out = HDA_Reactor_sim(**inputs)
    labels = ["F_H2_out", "F_CH4_out", "F_Tol_out", "F_Benz_out",
              "F_Diph_out", "T_out", "H_out"]
    x = {f"pfr.{k}": v for k, v in inputs.items()}
    x.update({f"pfr.{lbl}": float(val) for lbl, val in zip(labels, sim_out)})

    residual = unit.residual(x)
    assert residual.shape == (7,)
    # All residuals at consistent point should be (near) zero
    np.testing.assert_allclose(residual, 0.0, atol=1e-6)
    # Toluene conversion > 50% at nominal conditions
    kpis = unit.kpis(x)
    assert kpis["pfr.toluene_conversion"] > 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: TearStreamConfig can be declared without breaking existing SLP
# ─────────────────────────────────────────────────────────────────────────────

def test_tear_stream_config_is_harmless(lp_solver):
    """A TearStreamConfig on a non-recycle flowsheet must not break convergence."""
    from pse_ecosystem.core.contracts import SolverStatus
    from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only
    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver, TearStreamConfig

    fs = make_electrolysis_only(h2_demand_kg_per_h=100.0)
    cfg = SLPConfig(
        max_iter=10,
        tear_streams=[
            TearStreamConfig(var_name="pem.electricity_kW", connected_to="pem.electricity_kW")
        ],
    )
    result = SLPDriver(fs, cfg).run()

    assert result.status == SolverStatus.CONVERGED
    assert result.x["pem.h2_kg_per_h"] == pytest.approx(100.0, abs=1e-3)
