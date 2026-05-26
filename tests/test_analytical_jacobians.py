"""v1.6.1 P.4 — analytical Jacobian parity tests.

Each test constructs a representative operating point for a unit that
ships an analytical ``linearize()`` override (v1.6.1 P.4 onwards), then
asserts the analytical Jacobian matches the central-difference reference
within a strict tolerance.

Coverage as of P.4 final commit:
* `CSTRHF` — material balance + Arrhenius rate + energy + pressure rows.
* `HeatExchangerNTU` — 5-residual ε-NTU + Shomate dCp/dT chain.
* `ShellTubeHX` — LMTD-based duty + energy balances.
* `Compressor` — γ-driven isentropic + power balance.
* `FlashVLHF` — K-value VLE + component balance + total balance.
"""

from __future__ import annotations

import pytest

from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import (
    HeatExchangerNTU, HeatExchangerNTUParams,
)
from pse_ecosystem.models.heat_exchangers.shell_tube import (
    ShellTubeHX, ShellTubeParams,
)
from pse_ecosystem.models.pressure_changers.compressor import (
    Compressor, CompressorParams,
)
from pse_ecosystem.models.separators.flash_vl_hf import (
    FlashVLHF, FlashVLHFParams,
)
from pse_ecosystem.models.reactors.cstr_hf import (
    CSTRHF,
    CSTRHFParams,
    ReactionConfig,
)
from tests._jacobian_parity import assert_jacobian_matches_fd


# ─────────────────────────────────────────────────────────────────────────────
# CSTRHF — exothermic H2 + 0.5 O2 → H2O
# ─────────────────────────────────────────────────────────────────────────────


def _make_cstr() -> CSTRHF:
    rxn = ReactionConfig(
        stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
        k0=1.0e6,
        Ea_J_per_mol=80_000.0,
        reaction_orders={"H2": 2.0, "O2": 1.0},
        delta_H_J_per_mol=-241_800.0,
    )
    return CSTRHF(
        "R",
        ["H2", "O2", "H2O"],
        CSTRHFParams(reactions=[rxn], volume_m3=2.0),
    )


def _cstr_state():
    return {
        "R.inlet.F_H2": 2.0, "R.inlet.F_O2": 1.0, "R.inlet.F_H2O": 0.0,
        "R.inlet.T": 600.0, "R.inlet.P": 5.0e5,
        "R.outlet.F_H2": 0.4, "R.outlet.F_O2": 0.2, "R.outlet.F_H2O": 1.6,
        "R.outlet.T": 800.0, "R.outlet.P": 5.0e5,
        "R.xi_0": 0.8, "R.Q": -5.0e3,
    }


class TestCSTRHFAnalyticalJacobian:
    def test_jacobian_matches_fd_at_typical_operating_point(self):
        unit = _make_cstr()
        assert_jacobian_matches_fd(unit, _cstr_state(), rtol=1e-5, atol=1e-6)

    def test_jacobian_matches_fd_at_low_conversion(self):
        unit = _make_cstr()
        x = _cstr_state()
        x.update({"R.outlet.F_H2": 1.8, "R.outlet.F_O2": 0.9, "R.outlet.F_H2O": 0.2,
                   "R.outlet.T": 620.0, "R.xi_0": 0.1})
        assert_jacobian_matches_fd(unit, x, rtol=1e-5, atol=1e-6)

    def test_jacobian_matches_fd_auto_delta_H(self):
        """Reaction with delta_H_J_per_mol=0 → Shomate-derived ΔH(T).
        The analytical Jacobian must include the d(ΔH)/dT_out chain-rule
        term that this code path activates."""
        rxn = ReactionConfig(
            stoichiometry={"H2": -2.0, "O2": -1.0, "H2O": 2.0},
            k0=1.0e6,
            Ea_J_per_mol=80_000.0,
            reaction_orders={"H2": 2.0, "O2": 1.0},
            delta_H_J_per_mol=0.0,  # → Shomate ΔH(T)
        )
        unit = CSTRHF(
            "R", ["H2", "O2", "H2O"],
            CSTRHFParams(reactions=[rxn], volume_m3=2.0),
        )
        assert_jacobian_matches_fd(unit, _cstr_state(), rtol=1e-5, atol=1e-6)

    def test_is_exact_flag_false(self):
        """CSTRHF residual is non-linear (Arrhenius), so the analytical
        Jacobian must NOT claim is_exact=True — the SLP driver depends on
        this to keep iterating."""
        from pse_ecosystem.core.contracts import PrimalGuess
        unit = _make_cstr()
        lin = unit.linearize(PrimalGuess(values=_cstr_state(), iteration=0))
        assert not lin.is_exact

    def test_linear_rows_exactly_linear(self):
        """Mass balance + pressure rows should have entries identical to
        the analytical {-1, +1, -nu} pattern. Verify by inspection."""
        from pse_ecosystem.core.contracts import PrimalGuess
        unit = _make_cstr()
        lin = unit.linearize(PrimalGuess(values=_cstr_state(), iteration=0))
        vidx = {v: i for i, v in enumerate(lin.variables)}
        # Material balance for H2 (row 0): ∂/∂F_in_H2 = -1, ∂/∂F_out_H2 = +1,
        # ∂/∂xi_0 = -ν_H2,0 = +2 (H2 consumed: -2 → -(-2) = +2)
        assert lin.J[0, vidx["R.inlet.F_H2"]] == pytest.approx(-1.0)
        assert lin.J[0, vidx["R.outlet.F_H2"]] == pytest.approx(+1.0)
        assert lin.J[0, vidx["R.xi_0"]] == pytest.approx(+2.0)
        # Pressure row (last): ∂/∂P_out = +1, ∂/∂P_in = -1
        assert lin.J[-1, vidx["R.outlet.P"]] == pytest.approx(+1.0)
        assert lin.J[-1, vidx["R.inlet.P"]] == pytest.approx(-1.0)


# ─────────────────────────────────────────────────────────────────────────────
# HeatExchangerNTU — counter-current air / water cooler
# ─────────────────────────────────────────────────────────────────────────────


def _make_hx_ntu() -> HeatExchangerNTU:
    return HeatExchangerNTU(
        "HX",
        hot_components=["N2"],
        cold_components=["H2O"],
        params=HeatExchangerNTUParams(UA_W_per_K=2000.0),
    )


def _hx_ntu_state():
    return {
        "HX.hot_in.F_N2": 10.0, "HX.hot_in.T": 700.0, "HX.hot_in.P": 2.0e5,
        "HX.hot_out.F_N2": 10.0, "HX.hot_out.T": 500.0, "HX.hot_out.P": 2.0e5,
        "HX.cold_in.F_H2O": 8.0, "HX.cold_in.T": 350.0, "HX.cold_in.P": 1.5e5,
        "HX.cold_out.F_H2O": 8.0, "HX.cold_out.T": 500.0, "HX.cold_out.P": 1.5e5,
        "HX.Q": 6.0e4, "HX.effectiveness": 0.6, "HX.NTU": 2.5,
    }


class TestHXNTUAnalyticalJacobian:
    def test_jacobian_matches_fd_hot_is_cmin(self):
        unit = _make_hx_ntu()
        assert_jacobian_matches_fd(unit, _hx_ntu_state(), rtol=1e-4, atol=1e-3)

    def test_jacobian_matches_fd_cold_is_cmin(self):
        unit = _make_hx_ntu()
        x = _hx_ntu_state()
        # Swap flows so the cold side becomes C_min:
        x["HX.hot_in.F_N2"] = 20.0
        x["HX.hot_out.F_N2"] = 20.0
        x["HX.cold_in.F_H2O"] = 1.0
        x["HX.cold_out.F_H2O"] = 1.0
        x["HX.cold_out.T"] = 700.0  # cold side heats up more
        assert_jacobian_matches_fd(unit, x, rtol=1e-4, atol=1e-3)

    def test_is_exact_flag_false(self):
        """ε-NTU is nonlinear in NTU and C* — must not claim is_exact."""
        from pse_ecosystem.core.contracts import PrimalGuess
        unit = _make_hx_ntu()
        lin = unit.linearize(PrimalGuess(values=_hx_ntu_state(), iteration=0))
        assert not lin.is_exact


# ─────────────────────────────────────────────────────────────────────────────
# Compressor — single- and multi-stage isentropic
# ─────────────────────────────────────────────────────────────────────────────


def _make_compressor(n_stages: int = 1, T_intercool_K=None) -> Compressor:
    return Compressor(
        "K",
        ["N2", "H2"],
        CompressorParams(
            eta_isentropic=0.78,
            gamma_fixed=1.40,
            n_stages=n_stages,
            T_intercool_K=T_intercool_K,
            P_out_Pa=None,
        ),
    )


def _compressor_state(P_in=1.0e5, P_out=5.0e5, T_in=298.15, T_out=460.0):
    return {
        "K.inlet.F_N2": 8.0, "K.inlet.F_H2": 2.0,
        "K.inlet.T": T_in, "K.inlet.P": P_in,
        "K.outlet.F_N2": 8.0, "K.outlet.F_H2": 2.0,
        "K.outlet.T": T_out, "K.outlet.P": P_out,
        "K.W_shaft": 8.0e4,
    }


class TestCompressorAnalyticalJacobian:
    def test_jacobian_matches_fd_single_stage(self):
        unit = _make_compressor(n_stages=1)
        assert_jacobian_matches_fd(unit, _compressor_state(), rtol=1e-4, atol=1e-3)

    def test_jacobian_matches_fd_three_stages_intercooled(self):
        unit = _make_compressor(n_stages=3, T_intercool_K=313.15)
        x = _compressor_state(P_out=20.0e5, T_out=520.0)
        assert_jacobian_matches_fd(unit, x, rtol=1e-4, atol=1e-3)

    def test_is_exact_flag_false(self):
        from pse_ecosystem.core.contracts import PrimalGuess
        unit = _make_compressor(n_stages=1)
        lin = unit.linearize(PrimalGuess(values=_compressor_state(), iteration=0))
        assert not lin.is_exact

    def test_falls_back_to_fd_when_gamma_not_fixed(self):
        """gamma_fixed=None → use FD; the fallback path returns is_exact=False
        and J that matches FD exactly (trivially, since it IS FD)."""
        unit = Compressor(
            "K", ["N2", "H2"],
            CompressorParams(eta_isentropic=0.78, gamma_fixed=None, P_out_Pa=None),
        )
        assert_jacobian_matches_fd(unit, _compressor_state(), rtol=1e-8, atol=1e-10)


# ─────────────────────────────────────────────────────────────────────────────
# ShellTubeHX — LMTD + F-factor with closed-form rows 0/1/3 + numeric F/LMTD
# ─────────────────────────────────────────────────────────────────────────────


def _make_shell_tube() -> ShellTubeHX:
    return ShellTubeHX(
        "ST",
        hot_components=["N2"],
        cold_components=["H2O"],
        params=ShellTubeParams(U_W_per_m2_K=500.0, A_m2=12.0),
    )


def _shell_tube_state():
    return {
        "ST.hot_in.F_N2": 8.0,  "ST.hot_in.T": 700.0, "ST.hot_in.P": 2.0e5,
        "ST.hot_out.F_N2": 8.0, "ST.hot_out.T": 480.0, "ST.hot_out.P": 2.0e5,
        "ST.cold_in.F_H2O": 6.0, "ST.cold_in.T": 350.0, "ST.cold_in.P": 1.5e5,
        "ST.cold_out.F_H2O": 6.0, "ST.cold_out.T": 470.0, "ST.cold_out.P": 1.5e5,
        "ST.Q": 7.5e4,
    }


class TestShellTubeAnalyticalJacobian:
    def test_jacobian_matches_fd_at_typical_point(self):
        unit = _make_shell_tube()
        assert_jacobian_matches_fd(unit, _shell_tube_state(), rtol=1e-4, atol=1e-3)

    def test_jacobian_matches_fd_at_low_approach(self):
        unit = _make_shell_tube()
        x = _shell_tube_state()
        x["ST.hot_out.T"] = 510.0  # tighten the approach
        x["ST.cold_out.T"] = 490.0
        assert_jacobian_matches_fd(unit, x, rtol=1e-4, atol=1e-3)

    def test_is_exact_flag_false(self):
        from pse_ecosystem.core.contracts import PrimalGuess
        unit = _make_shell_tube()
        lin = unit.linearize(PrimalGuess(values=_shell_tube_state(), iteration=0))
        assert not lin.is_exact


# ─────────────────────────────────────────────────────────────────────────────
# FlashVLHF — Antoine/Raoult K-values + energy balance
# ─────────────────────────────────────────────────────────────────────────────


def _make_flash_vl() -> FlashVLHF:
    return FlashVLHF(
        "FL", ["H2O", "ethanol"],
        FlashVLHFParams(species_vle=["H2O", "ethanol"]),
    )


def _flash_state():
    return {
        "FL.inlet.F_H2O": 5.0, "FL.inlet.F_ethanol": 5.0,
        "FL.inlet.T": 360.0, "FL.inlet.P": 1.013e5,
        "FL.vapor.F_H2O": 1.5, "FL.vapor.F_ethanol": 3.5,
        "FL.vapor.T": 360.0, "FL.vapor.P": 1.013e5,
        "FL.liquid.F_H2O": 3.5, "FL.liquid.F_ethanol": 1.5,
        "FL.liquid.T": 360.0, "FL.liquid.P": 1.013e5,
        "FL.V_frac": 0.5, "FL.Q": 0.0,
    }


class TestFlashVLAnalyticalJacobian:
    def test_jacobian_matches_fd_ideal_gas(self):
        unit = _make_flash_vl()
        assert_jacobian_matches_fd(unit, _flash_state(), rtol=1e-4, atol=1e-3)

    def test_jacobian_matches_fd_high_vapour_fraction(self):
        unit = _make_flash_vl()
        x = _flash_state()
        x.update({
            "FL.vapor.F_H2O": 4.0, "FL.vapor.F_ethanol": 4.5,
            "FL.liquid.F_H2O": 1.0, "FL.liquid.F_ethanol": 0.5,
            "FL.V_frac": 0.85, "FL.vapor.T": 370.0, "FL.liquid.T": 370.0,
        })
        assert_jacobian_matches_fd(unit, x, rtol=1e-4, atol=1e-3)

    def test_is_exact_flag_false(self):
        from pse_ecosystem.core.contracts import PrimalGuess
        unit = _make_flash_vl()
        lin = unit.linearize(PrimalGuess(values=_flash_state(), iteration=0))
        assert not lin.is_exact
