"""v1.6 Workstream A.2 — heat-exchanger audit contract tests.

Validates:
* Each HX exposes ``hot_inlet_port`` / ``hot_outlet_port`` /
  ``cold_inlet_port`` / ``cold_outlet_port`` StreamPorts (CoolerHF uses
  ``inlet_port`` / ``outlet_port`` instead since it's single-stream).
* Each HX returns positive ``capex()`` and a non-empty ``kpis()``.
* Fouling resistance (``R_f_tube``, ``R_f_shell``) reduces effective U /
  inflates inferred area — the v1.6 fidelity gap closed in A.2.
* v1.5.3 numerics preserved with default zero-fouling parameters.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pytest

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF, CoolerHFParams
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


# ─────────────────────────────────────────────────────────────────────────────
# Constructors
# ─────────────────────────────────────────────────────────────────────────────


def _make_ntu(**kwargs) -> HeatExchangerNTU:
    p = HeatExchangerNTUParams(**kwargs)
    return HeatExchangerNTU("hx", ["N2"], ["H2O"], p)


def _make_shell(**kwargs) -> ShellTubeHX:
    p = ShellTubeParams(**kwargs)
    return ShellTubeHX("hx", ["N2"], ["H2O"], p)


def _make_1d(**kwargs) -> HeatExchanger1D:
    p = HeatExchanger1DParams(**kwargs)
    return HeatExchanger1D("hx", ["N2"], ["H2O"], p)


def _make_cooler(**kwargs) -> CoolerHF:
    p = CoolerHFParams(**kwargs)
    return CoolerHF("c", ["N2"], p)


_HX_X: Dict[str, float] = {
    "hx.hot_in.F_N2": 10.0, "hx.hot_in.T": 600.0, "hx.hot_in.P": 1.0e5,
    "hx.hot_out.F_N2": 10.0, "hx.hot_out.T": 450.0, "hx.hot_out.P": 1.0e5,
    "hx.cold_in.F_H2O": 5.0, "hx.cold_in.T": 300.0, "hx.cold_in.P": 1.0e5,
    "hx.cold_out.F_H2O": 5.0, "hx.cold_out.T": 380.0, "hx.cold_out.P": 1.0e5,
    "hx.Q": 1.0e4,
    "hx.effectiveness": 0.5,
    "hx.NTU": 1.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# Port + category contract
# ─────────────────────────────────────────────────────────────────────────────


class TestHXPortContract:
    @pytest.mark.parametrize("factory", [_make_ntu, _make_shell, _make_1d])
    def test_dual_stream_ports(self, factory):
        hx = factory()
        for tag in ("hot_inlet_port", "hot_outlet_port",
                    "cold_inlet_port", "cold_outlet_port"):
            port = getattr(hx, tag, None)
            assert isinstance(port, StreamPort), f"{tag} missing on {type(hx).__name__}"

    def test_cooler_single_stream_ports(self):
        c = _make_cooler()
        assert isinstance(c.inlet_port, StreamPort)
        assert isinstance(c.outlet_port, StreamPort)

    @pytest.mark.parametrize(
        "factory", [_make_ntu, _make_shell, _make_1d, _make_cooler]
    )
    def test_industrial_category(self, factory):
        assert factory().category == UnitCategory.INDUSTRIAL


# ─────────────────────────────────────────────────────────────────────────────
# CAPEX + KPI contract (HeatExchanger1D was missing kpis() pre-A.2)
# ─────────────────────────────────────────────────────────────────────────────


class TestHXCapexKPIs:
    @pytest.mark.parametrize("factory", [_make_ntu, _make_shell, _make_1d])
    def test_capex_positive(self, factory):
        assert factory().capex(_HX_X) > 0

    @pytest.mark.parametrize("factory", [_make_ntu, _make_shell, _make_1d])
    def test_kpis_nonempty(self, factory):
        kpis = factory().kpis(_HX_X)
        assert len(kpis) >= 1
        # All KPI values must be numeric and finite.
        for k, v in kpis.items():
            assert isinstance(v, (int, float)), f"non-numeric KPI {k}={v}"


# ─────────────────────────────────────────────────────────────────────────────
# Fouling fidelity — closed in A.2
# ─────────────────────────────────────────────────────────────────────────────


class TestFouling:
    def test_shell_tube_default_zero_fouling_matches_v153(self):
        # Default R_f = 0 → U_effective equals U_W_per_m2_K.
        p = ShellTubeParams(U_W_per_m2_K=500.0)
        assert p.U_effective_W_per_m2_K() == pytest.approx(500.0)

    def test_shell_tube_fouling_reduces_U(self):
        # Both fouling resistances together drop U from 500 to ~333.
        p = ShellTubeParams(
            U_W_per_m2_K=500.0,
            R_f_tube_m2K_per_W=0.001,
            R_f_shell_m2K_per_W=0.0,
        )
        assert p.U_effective_W_per_m2_K() < 500.0
        # 1/(1/500 + 0.001) = 1/0.003 = 333.33
        assert p.U_effective_W_per_m2_K() == pytest.approx(1.0 / (1 / 500.0 + 0.001))

    def test_1d_fouling_reduces_U(self):
        p_clean = HeatExchanger1DParams(U_W_per_m2_K=500.0)
        p_foul = HeatExchanger1DParams(
            U_W_per_m2_K=500.0, R_f_tube_m2K_per_W=0.0005
        )
        assert p_foul.U_effective_W_per_m2_K() < p_clean.U_effective_W_per_m2_K()

    def test_ntu_fouling_inflates_area(self):
        # Area = UA × (1/U_clean + R_f).  Default zero-fouling = UA/U_clean.
        p_clean = HeatExchangerNTUParams(
            UA_W_per_K=1000.0, U_clean_W_per_m2_K=500.0
        )
        p_foul = HeatExchangerNTUParams(
            UA_W_per_K=1000.0, U_clean_W_per_m2_K=500.0,
            R_f_tube_m2K_per_W=0.001, R_f_shell_m2K_per_W=0.001,
        )
        A_clean = p_clean.heat_transfer_area_m2()
        A_foul = p_foul.heat_transfer_area_m2()
        assert A_clean == pytest.approx(2.0)        # 1000 / 500
        assert A_foul == pytest.approx(1000.0 * (1 / 500.0 + 0.002))
        assert A_foul > A_clean


# ─────────────────────────────────────────────────────────────────────────────
# Operating-point Q sensitivity (audit — fouling actually bites in residual)
# ─────────────────────────────────────────────────────────────────────────────


class TestFoulingBitesResidual:
    def test_shell_tube_Q_residual_changes_with_fouling(self):
        hx_clean = _make_shell(U_W_per_m2_K=500.0, A_m2=10.0)
        hx_foul = _make_shell(
            U_W_per_m2_K=500.0, A_m2=10.0,
            R_f_tube_m2K_per_W=0.002, R_f_shell_m2K_per_W=0.002,
        )
        # Same operating state — the Q = U·A·F·LMTD residual differs because
        # the fouled exchanger uses a smaller U_effective.
        r_clean = hx_clean.residual(_HX_X)
        r_foul = hx_foul.residual(_HX_X)
        # Row 2 of the residual is the heat-transfer correlation. Differ.
        assert abs(r_clean[2] - r_foul[2]) > 1e-3
