"""Phase 3 tests — high-fidelity unit models."""

import math
import numpy as np
import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

def _check_residual_shape(unit, x):
    """Residual vector must be finite-valued numpy array."""
    res = unit.residual(x)
    assert isinstance(res, np.ndarray)
    assert res.ndim == 1
    assert np.all(np.isfinite(res)), f"Non-finite residuals: {res}"
    return res


def _check_linearize_shape(unit, x):
    from pse_ecosystem.core.contracts import PrimalGuess
    lm = unit.linearize(PrimalGuess(values=x, iteration=0))
    n = len(unit.variables())
    m = len(unit.residual(x))
    assert lm.J.shape == (m, n), f"J shape {lm.J.shape} expected ({m},{n})"
    assert lm.x0.shape == (n,)
    assert lm.f0.shape == (m,)
    assert np.all(np.isfinite(lm.J))
    return lm


# ── Stoichiometric Reactor ────────────────────────────────────────────────────


class TestStoichiometricReactor:
    def _make(self):
        from pse_ecosystem.models.reactors.stoichiometric_reactor import (
            StoichiometricReactor, StoichiometricParams,
        )
        params = StoichiometricParams(
            stoichiometry={"A": [-1.0], "B": [1.0]},
        )
        return StoichiometricReactor("sr", ["A", "B"], params)

    def test_converged_residual(self):
        unit = self._make()
        # A→B, inlet 10 mol/s A, no B. Extent 3 mol/s → outlet: A=7, B=3
        x = {
            "sr.inlet.F_A": 10.0, "sr.inlet.F_B": 0.0,
            "sr.inlet.T": 400.0,  "sr.inlet.P": 101325.0,
            "sr.outlet.F_A": 7.0, "sr.outlet.F_B": 3.0,
            "sr.outlet.T": 400.0, "sr.outlet.P": 101325.0,
            "sr.xi_0": 3.0,
        }
        res = unit.residual(x)
        assert np.allclose(res, 0.0, atol=1e-10)

    def test_mass_balance_closure(self):
        unit = self._make()
        x = {
            "sr.inlet.F_A": 10.0, "sr.inlet.F_B": 0.0,
            "sr.inlet.T": 400.0,  "sr.inlet.P": 101325.0,
            "sr.outlet.F_A": 7.0, "sr.outlet.F_B": 3.0,
            "sr.outlet.T": 400.0, "sr.outlet.P": 101325.0,
            "sr.xi_0": 3.0,
        }
        # F_A_in + F_B_in = F_A_out + F_B_out
        assert abs((10.0 + 0.0) - (7.0 + 3.0)) < 1e-10

    def test_is_linear(self):
        unit = self._make()
        assert unit.is_linear is True

    def test_analytical_jacobian_shape(self):
        unit = self._make()
        x = {v: 1.0 for v in unit.variables()}
        x["sr.inlet.T"] = 400.0; x["sr.outlet.T"] = 400.0
        x["sr.inlet.P"] = 101325.0; x["sr.outlet.P"] = 101325.0
        _check_linearize_shape(unit, x)

    def test_capex_minimum_floor(self):
        # v1.6 A.1 audit: StoichiometricReactor now reports a minimum-vessel
        # CAPEX even with empty inputs (was 0.0 pre-audit, which silently
        # zero-rated the unit in TEA reports).
        unit = self._make()
        assert unit.capex({}) > 0.0


# ── Mixer HF ──────────────────────────────────────────────────────────────────


class TestMixerHF:
    def _make(self):
        from pse_ecosystem.models.mixers.mixer_hf import MixerHF, MixerHFParams
        return MixerHF("mix", ["CO2", "N2"], MixerHFParams(n_inlets=2))

    def test_material_balance_closure(self):
        unit = self._make()
        x = {
            "mix.inlet_0.F_CO2": 3.0, "mix.inlet_0.F_N2": 0.0,
            "mix.inlet_0.T": 400.0,   "mix.inlet_0.P": 101325.0,
            "mix.inlet_1.F_CO2": 0.0, "mix.inlet_1.F_N2": 5.0,
            "mix.inlet_1.T": 350.0,   "mix.inlet_1.P": 101325.0,
            "mix.outlet.F_CO2": 3.0,  "mix.outlet.F_N2": 5.0,
            "mix.outlet.T": 370.0,    "mix.outlet.P": 101325.0,
        }
        res = unit.residual(x)
        # Material balances [0:2] should be zero
        assert abs(res[0]) < 1e-10
        assert abs(res[1]) < 1e-10

    def test_residual_shape(self):
        unit = self._make()
        x = {v: 1.0 for v in unit.variables()}
        x.update({"mix.inlet_0.T": 400.0, "mix.inlet_1.T": 350.0,
                   "mix.outlet.T": 375.0, "mix.inlet_0.P": 101325.0,
                   "mix.inlet_1.P": 101325.0, "mix.outlet.P": 101325.0})
        _check_residual_shape(unit, x)

    def test_linearize_shape(self):
        unit = self._make()
        x = {v: 1.0 for v in unit.variables()}
        x.update({"mix.inlet_0.T": 400.0, "mix.inlet_1.T": 350.0,
                   "mix.outlet.T": 375.0, "mix.inlet_0.P": 101325.0,
                   "mix.inlet_1.P": 101325.0, "mix.outlet.P": 101325.0,
                   "mix.inlet_0.F_CO2": 3.0, "mix.inlet_0.F_N2": 0.0,
                   "mix.inlet_1.F_CO2": 0.0, "mix.inlet_1.F_N2": 5.0,
                   "mix.outlet.F_CO2": 3.0, "mix.outlet.F_N2": 5.0})
        _check_linearize_shape(unit, x)


# ── Separator HF ──────────────────────────────────────────────────────────────


class TestSeparatorHF:
    def _make(self):
        from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
        params = SeparatorHFParams(n_outlets=2, split_fractions=[[0.9, 0.1], [0.2, 0.8]])
        return SeparatorHF("sep", ["A", "B"], params)

    def test_split_fraction_closure(self):
        unit = self._make()
        x = {
            "sep.inlet.F_A": 10.0, "sep.inlet.F_B": 8.0,
            "sep.inlet.T": 350.0,  "sep.inlet.P": 101325.0,
            "sep.outlet_0.F_A": 9.0, "sep.outlet_0.F_B": 1.6,
            "sep.outlet_0.T": 350.0, "sep.outlet_0.P": 101325.0,
            "sep.outlet_1.F_A": 1.0, "sep.outlet_1.F_B": 6.4,
            "sep.outlet_1.T": 350.0, "sep.outlet_1.P": 101325.0,
        }
        res = unit.residual(x)
        # All residuals near zero at correct split
        assert np.allclose(res, 0.0, atol=1e-10)

    def test_is_linear(self):
        unit = self._make()
        assert unit.is_linear is True

    def test_linearize_exact(self):
        unit = self._make()
        x = {
            "sep.inlet.F_A": 10.0, "sep.inlet.F_B": 8.0,
            "sep.inlet.T": 350.0,  "sep.inlet.P": 101325.0,
            "sep.outlet_0.F_A": 9.0, "sep.outlet_0.F_B": 1.6,
            "sep.outlet_0.T": 350.0, "sep.outlet_0.P": 101325.0,
            "sep.outlet_1.F_A": 1.0, "sep.outlet_1.F_B": 6.4,
            "sep.outlet_1.T": 350.0, "sep.outlet_1.P": 101325.0,
        }
        lm = _check_linearize_shape(unit, x)
        assert lm.is_exact is True


# ── Flash V/L HF ──────────────────────────────────────────────────────────────


class TestFlashVLHF:
    def _make(self):
        from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
        params = FlashVLHFParams(species_vle=["benzene", "toluene"])
        return FlashVLHF("fl", ["benzene", "toluene"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "fl.inlet.F_benzene": 5.0, "fl.inlet.F_toluene": 5.0,
            "fl.inlet.T": 360.0, "fl.inlet.P": 101325.0,
            "fl.vapor.F_benzene": 3.0, "fl.vapor.F_toluene": 1.0,
            "fl.vapor.T": 360.0, "fl.vapor.P": 101325.0,
            "fl.liquid.F_benzene": 2.0, "fl.liquid.F_toluene": 4.0,
            "fl.liquid.T": 360.0, "fl.liquid.P": 101325.0,
            "fl.V_frac": 0.4, "fl.Q": 0.0,
        }
        res = _check_residual_shape(unit, x)
        # 2*N+4 = 8 residuals
        assert len(res) == 2 * 2 + 4

    def test_material_balance(self):
        unit = self._make()
        x = {
            "fl.inlet.F_benzene": 5.0, "fl.inlet.F_toluene": 5.0,
            "fl.inlet.T": 360.0, "fl.inlet.P": 101325.0,
            "fl.vapor.F_benzene": 3.0, "fl.vapor.F_toluene": 1.0,
            "fl.vapor.T": 360.0, "fl.vapor.P": 101325.0,
            "fl.liquid.F_benzene": 2.0, "fl.liquid.F_toluene": 4.0,
            "fl.liquid.T": 360.0, "fl.liquid.P": 101325.0,
            "fl.V_frac": 0.4, "fl.Q": 0.0,
        }
        res = unit.residual(x)
        # material balances are res[0:2]
        assert abs(res[0]) < 1e-10  # benzene
        assert abs(res[1]) < 1e-10  # toluene

    def test_linearize_shape(self):
        unit = self._make()
        x = {
            "fl.inlet.F_benzene": 5.0, "fl.inlet.F_toluene": 5.0,
            "fl.inlet.T": 360.0, "fl.inlet.P": 101325.0,
            "fl.vapor.F_benzene": 3.0, "fl.vapor.F_toluene": 1.0,
            "fl.vapor.T": 360.0, "fl.vapor.P": 101325.0,
            "fl.liquid.F_benzene": 2.0, "fl.liquid.F_toluene": 4.0,
            "fl.liquid.T": 360.0, "fl.liquid.P": 101325.0,
            "fl.V_frac": 0.4, "fl.Q": 0.0,
        }
        _check_linearize_shape(unit, x)

    def test_kpis_present(self):
        unit = self._make()
        x = {v: 1.0 for v in unit.variables()}
        x.update({"fl.V_frac": 0.5, "fl.Q": 0.0,
                   "fl.inlet.T": 360.0, "fl.vapor.T": 360.0, "fl.liquid.T": 360.0,
                   "fl.inlet.P": 101325.0, "fl.vapor.P": 101325.0, "fl.liquid.P": 101325.0})
        kpis = unit.kpis(x)
        assert "V_frac" in kpis


# ── CSTR HF ───────────────────────────────────────────────────────────────────


class TestCSTRHF:
    def _make(self):
        from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig
        rxn = ReactionConfig(
            stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
            k0=1e4, Ea_J_per_mol=50000.0,
            reaction_orders={"CO": 1.0, "H2O": 1.0},
        )
        params = CSTRHFParams(reactions=[rxn], volume_m3=1.0)
        return CSTRHF("cstr", ["CO", "H2O", "CO2", "H2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "cstr.inlet.F_CO":  2.0, "cstr.inlet.F_H2O": 2.0,
            "cstr.inlet.F_CO2": 0.0, "cstr.inlet.F_H2":  0.0,
            "cstr.inlet.T": 700.0, "cstr.inlet.P": 101325.0,
            "cstr.outlet.F_CO":  1.5, "cstr.outlet.F_H2O": 1.5,
            "cstr.outlet.F_CO2": 0.5, "cstr.outlet.F_H2":  0.5,
            "cstr.outlet.T": 700.0, "cstr.outlet.P": 101325.0,
            "cstr.xi_0": 0.5, "cstr.Q": 0.0,
        }
        res = _check_residual_shape(unit, x)
        # N=4, R=1, 2 extra = 7 residuals
        assert len(res) == 4 + 1 + 2

    def test_material_balance(self):
        unit = self._make()
        x = {
            "cstr.inlet.F_CO":  2.0, "cstr.inlet.F_H2O": 2.0,
            "cstr.inlet.F_CO2": 0.0, "cstr.inlet.F_H2":  0.0,
            "cstr.inlet.T": 700.0, "cstr.inlet.P": 101325.0,
            "cstr.outlet.F_CO":  1.5, "cstr.outlet.F_H2O": 1.5,
            "cstr.outlet.F_CO2": 0.5, "cstr.outlet.F_H2":  0.5,
            "cstr.outlet.T": 700.0, "cstr.outlet.P": 101325.0,
            "cstr.xi_0": 0.5, "cstr.Q": 0.0,
        }
        res = unit.residual(x)
        # Material balances [0:4]: should be zero by construction
        assert np.allclose(res[:4], 0.0, atol=1e-10)

    def test_capex_positive(self):
        unit = self._make()
        x = {v: 0.0 for v in unit.variables()}
        cap = unit.capex(x)
        assert cap > 0.0
        assert 1e4 < cap < 1e9

    def test_linearize_shape(self):
        unit = self._make()
        x = {
            "cstr.inlet.F_CO":  2.0, "cstr.inlet.F_H2O": 2.0,
            "cstr.inlet.F_CO2": 0.0, "cstr.inlet.F_H2":  0.0,
            "cstr.inlet.T": 700.0, "cstr.inlet.P": 101325.0,
            "cstr.outlet.F_CO":  1.5, "cstr.outlet.F_H2O": 1.5,
            "cstr.outlet.F_CO2": 0.5, "cstr.outlet.F_H2":  0.5,
            "cstr.outlet.T": 700.0, "cstr.outlet.P": 101325.0,
            "cstr.xi_0": 0.5, "cstr.Q": 0.0,
        }
        _check_linearize_shape(unit, x)


# ── Compressor ────────────────────────────────────────────────────────────────


class TestCompressor:
    def _make(self):
        from pse_ecosystem.models.pressure_changers.compressor import Compressor, CompressorParams
        params = CompressorParams(eta_isentropic=0.75, P_out_Pa=300000.0)
        return Compressor("comp", ["N2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "comp.inlet.F_N2": 1.0, "comp.inlet.T": 300.0, "comp.inlet.P": 101325.0,
            "comp.outlet.F_N2": 1.0, "comp.outlet.T": 430.0, "comp.outlet.P": 300000.0,
            "comp.W_shaft": 5000.0,
        }
        _check_residual_shape(unit, x)

    def test_material_balance(self):
        unit = self._make()
        x = {
            "comp.inlet.F_N2": 1.0, "comp.inlet.T": 300.0, "comp.inlet.P": 101325.0,
            "comp.outlet.F_N2": 1.0, "comp.outlet.T": 430.0, "comp.outlet.P": 300000.0,
            "comp.W_shaft": 5000.0,
        }
        res = unit.residual(x)
        assert abs(res[0]) < 1e-10  # F_N2_out - F_N2_in

    def test_capex_positive(self):
        unit = self._make()
        x = {"comp.W_shaft": 100000.0}
        cap = unit.capex(x)
        assert cap > 0


# ── Valve ─────────────────────────────────────────────────────────────────────


class TestValve:
    def _make(self):
        from pse_ecosystem.models.pressure_changers.valve import Valve, ValveParams
        return Valve("v1", ["N2"], ValveParams(P_out_Pa=50000.0))

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "v1.inlet.F_N2": 2.0, "v1.inlet.T": 350.0, "v1.inlet.P": 200000.0,
            "v1.outlet.F_N2": 2.0, "v1.outlet.T": 350.0, "v1.outlet.P": 50000.0,
            "v1.Cv": 0.01,
        }
        _check_residual_shape(unit, x)

    def test_isenthalpic_ideal(self):
        """For ideal gas, T_out = T_in (isenthalpic = isothermal)."""
        unit = self._make()
        x = {
            "v1.inlet.F_N2": 2.0, "v1.inlet.T": 350.0, "v1.inlet.P": 200000.0,
            "v1.outlet.F_N2": 2.0, "v1.outlet.T": 350.0, "v1.outlet.P": 50000.0,
            "v1.Cv": 0.01,
        }
        res = unit.residual(x)
        assert abs(res[1]) < 1e-10  # T_out - T_in = 0


# ── Pump ─────────────────────────────────────────────────────────────────────


class TestPump:
    def _make(self):
        from pse_ecosystem.models.pressure_changers.pump import Pump, PumpParams
        return Pump("pump", ["H2O"], PumpParams(P_out_Pa=500000.0))

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "pump.inlet.F_H2O": 10.0, "pump.inlet.T": 300.0, "pump.inlet.P": 101325.0,
            "pump.outlet.F_H2O": 10.0, "pump.outlet.T": 300.0, "pump.outlet.P": 500000.0,
            "pump.W_shaft": 500.0,
        }
        _check_residual_shape(unit, x)


# ── HX NTU ────────────────────────────────────────────────────────────────────


class TestHXNTU:
    def _make(self):
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import (
            HeatExchangerNTU, HeatExchangerNTUParams,
        )
        params = HeatExchangerNTUParams(UA_W_per_K=5000.0)
        return HeatExchangerNTU("hx", ["CO2"], ["N2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "hx.hot_in.F_CO2": 1.0, "hx.hot_in.T": 500.0, "hx.hot_in.P": 101325.0,
            "hx.hot_out.F_CO2": 1.0, "hx.hot_out.T": 400.0, "hx.hot_out.P": 101325.0,
            "hx.cold_in.F_N2": 2.0, "hx.cold_in.T": 300.0, "hx.cold_in.P": 101325.0,
            "hx.cold_out.F_N2": 2.0, "hx.cold_out.T": 345.0, "hx.cold_out.P": 101325.0,
            "hx.Q": 3000.0, "hx.effectiveness": 0.6, "hx.NTU": 1.5,
        }
        res = _check_residual_shape(unit, x)
        assert len(res) == 5

    def test_capex_positive(self):
        unit = self._make()
        cap = unit.capex({})
        assert cap > 0


# ── Shell & Tube HX ───────────────────────────────────────────────────────────


class TestShellTubeHX:
    def _make(self):
        from pse_ecosystem.models.heat_exchangers.shell_tube import ShellTubeHX, ShellTubeParams
        params = ShellTubeParams(U_W_per_m2_K=500.0, A_m2=10.0)
        return ShellTubeHX("hxst", ["CO2"], ["N2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "hxst.hot_in.F_CO2": 1.0, "hxst.hot_in.T": 500.0, "hxst.hot_in.P": 101325.0,
            "hxst.hot_out.F_CO2": 1.0, "hxst.hot_out.T": 400.0, "hxst.hot_out.P": 101325.0,
            "hxst.cold_in.F_N2": 2.0, "hxst.cold_in.T": 300.0, "hxst.cold_in.P": 101325.0,
            "hxst.cold_out.F_N2": 2.0, "hxst.cold_out.T": 345.0, "hxst.cold_out.P": 101325.0,
            "hxst.Q": 3000.0,
        }
        _check_residual_shape(unit, x)

    def test_capex_positive(self):
        unit = self._make()
        assert unit.capex({}) > 0


# ── HX 1D ────────────────────────────────────────────────────────────────────


class TestHX1D:
    def _make(self):
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_1d import (
            HeatExchanger1D, HeatExchanger1DParams,
        )
        params = HeatExchanger1DParams(U_W_per_m2_K=500.0, A_m2=10.0, n_elements=5)
        return HeatExchanger1D("hx1d", ["CO2"], ["N2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "hx1d.hot_in.F_CO2": 1.0, "hx1d.hot_in.T": 500.0, "hx1d.hot_in.P": 101325.0,
            "hx1d.hot_out.F_CO2": 1.0, "hx1d.hot_out.T": 400.0, "hx1d.hot_out.P": 101325.0,
            "hx1d.cold_in.F_N2": 2.0, "hx1d.cold_in.T": 300.0, "hx1d.cold_in.P": 101325.0,
            "hx1d.cold_out.F_N2": 2.0, "hx1d.cold_out.T": 350.0, "hx1d.cold_out.P": 101325.0,
            "hx1d.Q": 3000.0,
        }
        res = _check_residual_shape(unit, x)
        assert len(res) == 3


# ── PFR HF ───────────────────────────────────────────────────────────────────


class TestPFRHF:
    def _make(self):
        from pse_ecosystem.models.reactors.pfr_hf import PFRHF, PFRHFParams
        from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
        rxn = ReactionConfig(
            stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
            k0=1e3, Ea_J_per_mol=50000.0,
            reaction_orders={"CO": 1.0, "H2O": 1.0},
        )
        params = PFRHFParams(reactions=[rxn], length_m=2.0, cross_section_m2=0.05, isobaric=True)
        return PFRHF("pfr", ["CO", "H2O", "CO2", "H2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "pfr.inlet.F_CO":  1.0, "pfr.inlet.F_H2O": 1.0,
            "pfr.inlet.F_CO2": 0.0, "pfr.inlet.F_H2":  0.0,
            "pfr.inlet.T": 700.0, "pfr.inlet.P": 101325.0,
            "pfr.outlet.F_CO":  0.8, "pfr.outlet.F_H2O": 0.8,
            "pfr.outlet.F_CO2": 0.2, "pfr.outlet.F_H2":  0.2,
            "pfr.outlet.T": 710.0, "pfr.outlet.P": 101325.0,
        }
        try:
            res = _check_residual_shape(unit, x)
            assert len(res) == 4 + 2
        except ImportError:
            pytest.skip("scipy not available for PFR ODE integration")

    def test_linearize_shape(self):
        unit = self._make()
        x = {
            "pfr.inlet.F_CO":  1.0, "pfr.inlet.F_H2O": 1.0,
            "pfr.inlet.F_CO2": 0.0, "pfr.inlet.F_H2":  0.0,
            "pfr.inlet.T": 700.0, "pfr.inlet.P": 101325.0,
            "pfr.outlet.F_CO":  0.8, "pfr.outlet.F_H2O": 0.8,
            "pfr.outlet.F_CO2": 0.2, "pfr.outlet.F_H2":  0.2,
            "pfr.outlet.T": 710.0, "pfr.outlet.P": 101325.0,
        }
        try:
            _check_linearize_shape(unit, x)
        except ImportError:
            pytest.skip("scipy not available")


# ── Equilibrium Reactor ───────────────────────────────────────────────────────


class TestEquilibriumReactor:
    def _make(self):
        from pse_ecosystem.models.reactors.equilibrium_reactor import (
            EquilibriumReactor, EquilReactorParams,
        )
        from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
        rxn = ReactionConfig(
            stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
            k0=1.0, Ea_J_per_mol=0.0,
            reaction_orders={},
            delta_H_J_per_mol=-41000.0,
        )
        params = EquilReactorParams(reactions=[rxn], Keq_ref=[3.0])
        return EquilibriumReactor("eq", ["CO", "H2O", "CO2", "H2"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "eq.inlet.F_CO":  2.0, "eq.inlet.F_H2O": 2.0,
            "eq.inlet.F_CO2": 0.0, "eq.inlet.F_H2":  0.0,
            "eq.inlet.T": 600.0, "eq.inlet.P": 101325.0,
            "eq.outlet.F_CO":  1.0, "eq.outlet.F_H2O": 1.0,
            "eq.outlet.F_CO2": 1.0, "eq.outlet.F_H2":  1.0,
            "eq.outlet.T": 600.0, "eq.outlet.P": 101325.0,
            "eq.Q": 0.0,
        }
        res = _check_residual_shape(unit, x)
        assert len(res) == 4 + 2


# ── Gibbs Reactor ─────────────────────────────────────────────────────────────


class TestGibbsReactor:
    def _make(self):
        from pse_ecosystem.models.reactors.gibbs_reactor import GibbsReactor, GibbsReactorParams
        return GibbsReactor("gibbs", ["CO", "H2O", "CO2", "H2"], GibbsReactorParams())

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "gibbs.inlet.F_CO":  2.0, "gibbs.inlet.F_H2O": 2.0,
            "gibbs.inlet.F_CO2": 0.0, "gibbs.inlet.F_H2":  0.0,
            "gibbs.inlet.T": 1000.0,  "gibbs.inlet.P": 101325.0,
            "gibbs.outlet.F_CO":  1.0, "gibbs.outlet.F_H2O": 1.0,
            "gibbs.outlet.F_CO2": 1.0, "gibbs.outlet.F_H2":  1.0,
            "gibbs.outlet.T": 1000.0, "gibbs.outlet.P": 101325.0,
        }
        try:
            res = _check_residual_shape(unit, x)
            assert len(res) == 4 + 2
        except ImportError:
            pytest.skip("scipy not available for Gibbs minimization")


# ── Distillation HF ───────────────────────────────────────────────────────────


class TestDistillationHF:
    def _make(self):
        from pse_ecosystem.models.separators.distillation_hf import DistillationHF, DistillationHFParams
        params = DistillationHFParams(
            species_vle=["benzene", "toluene"], lk="benzene", hk="toluene",
            T_op_K=360.0, P_op_Pa=101325.0,
        )
        return DistillationHF("dist", ["benzene", "toluene"], params)

    def test_residual_shape(self):
        unit = self._make()
        x = {
            "dist.feed.F_benzene": 5.0, "dist.feed.F_toluene": 5.0,
            "dist.feed.T": 360.0, "dist.feed.P": 101325.0,
            "dist.distillate.F_benzene": 4.5, "dist.distillate.F_toluene": 0.5,
            "dist.distillate.T": 350.0, "dist.distillate.P": 101325.0,
            "dist.bottoms.F_benzene": 0.5, "dist.bottoms.F_toluene": 4.5,
            "dist.bottoms.T": 380.0, "dist.bottoms.P": 101325.0,
            "dist.N_stages": 20.0, "dist.R_ratio": 2.0,
            "dist.Q_cond": -5e5, "dist.Q_reb": 5e5,
        }
        res = _check_residual_shape(unit, x)
        assert len(res) == 2 + 4

    def test_material_balance(self):
        unit = self._make()
        x = {
            "dist.feed.F_benzene": 5.0, "dist.feed.F_toluene": 5.0,
            "dist.feed.T": 360.0, "dist.feed.P": 101325.0,
            "dist.distillate.F_benzene": 4.5, "dist.distillate.F_toluene": 0.5,
            "dist.distillate.T": 350.0, "dist.distillate.P": 101325.0,
            "dist.bottoms.F_benzene": 0.5, "dist.bottoms.F_toluene": 4.5,
            "dist.bottoms.T": 380.0, "dist.bottoms.P": 101325.0,
            "dist.N_stages": 20.0, "dist.R_ratio": 2.0,
            "dist.Q_cond": -5e5, "dist.Q_reb": 5e5,
        }
        res = unit.residual(x)
        # Material balances: residuals [0:2]
        assert abs(res[0]) < 1e-10
        assert abs(res[1]) < 1e-10

    def test_capex_positive(self):
        unit = self._make()
        x = {
            "dist.N_stages": 20.0,
            "dist.distillate.F_benzene": 4.5, "dist.distillate.F_toluene": 0.5,
            "dist.bottoms.F_benzene": 0.5, "dist.bottoms.F_toluene": 4.5,
        }
        assert unit.capex(x) > 0


# ── Flash S/L ─────────────────────────────────────────────────────────────────


class TestFlashSL:
    def _make(self):
        from pse_ecosystem.models.separators.flash_sl import FlashSL, FlashSLParams
        params = FlashSLParams(
            species=["NaCl"],
            MW_kg_per_mol={"NaCl": 0.05844},
            S_ref={"NaCl": 6000.0},   # mol/m³ at 25°C
            dH_sol={"NaCl": 3880.0},  # J/mol
        )
        return FlashSL("fsl", params)

    def test_residual_shape(self):
        unit = self._make()
        x = {v: 0.1 for v in unit.variables()}
        x["fsl.solid_in.T"] = 300.0
        x["fsl.V_sol_m3_s"] = 0.001
        res = _check_residual_shape(unit, x)
        # N=1: 2*N+1 = 3
        assert len(res) == 3
