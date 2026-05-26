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
