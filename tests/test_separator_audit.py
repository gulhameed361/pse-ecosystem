"""v1.6 Workstream A.3 — separator audit contract tests.

Locks in:
* Port surface (StreamPort presence + category) for all four separators.
* SeparatorHF split-fraction validation: shape mismatch, negative splits,
  rows not summing to 1 all raise ValueError at construction time.
* CAPEX positive for FlashVLHF and FlashSL (both previously returned 0).
* KPIs non-empty for FlashSL.
* DistillationHF retains SCREENING classification (audit A.0 enforced).
"""

from __future__ import annotations

from typing import Dict

import pytest

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.models.separators.distillation_hf import (
    DistillationHF,
    DistillationHFParams,
)
from pse_ecosystem.models.separators.flash_sl import FlashSL, FlashSLParams
from pse_ecosystem.models.separators.flash_vl_hf import (
    FlashVLHF,
    FlashVLHFParams,
)
from pse_ecosystem.models.separators.separator_hf import (
    SeparatorHF,
    SeparatorHFParams,
)


# ─────────────────────────────────────────────────────────────────────────────
# SeparatorHF split-fraction validation (audit A.3 hardening)
# ─────────────────────────────────────────────────────────────────────────────


class TestSeparatorValidation:
    def test_default_equal_split_is_valid(self):
        # Equal-split default must always pass validation.
        unit = SeparatorHF("s", ["A", "B"], SeparatorHFParams(n_outlets=2))
        assert unit._sf.shape == (2, 2)

    def test_valid_user_splits(self):
        SeparatorHF(
            "s", ["A", "B"],
            SeparatorHFParams(
                n_outlets=2,
                split_fractions=[[0.7, 0.3], [0.4, 0.6]],
            ),
        )

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match=r"shape \(2, 2\)"):
            SeparatorHF(
                "s", ["A", "B"],
                SeparatorHFParams(
                    n_outlets=2,
                    split_fractions=[[1.0, 0.0]],  # only 1 row
                ),
            )

    def test_negative_split_raises(self):
        with pytest.raises(ValueError, match="negative values"):
            SeparatorHF(
                "s", ["A", "B"],
                SeparatorHFParams(
                    n_outlets=2,
                    split_fractions=[[0.7, 0.3], [1.2, -0.2]],
                ),
            )

    def test_row_sum_not_one_raises(self):
        with pytest.raises(ValueError, match="sum to 1"):
            SeparatorHF(
                "s", ["A", "B"],
                SeparatorHFParams(
                    n_outlets=2,
                    split_fractions=[[0.7, 0.3], [0.4, 0.5]],  # row 1 sums to 0.9
                ),
            )

    def test_row_sum_at_tolerance_accepted(self):
        # 1e-10 deviation must be tolerated (floating-point noise).
        SeparatorHF(
            "s", ["A", "B"],
            SeparatorHFParams(
                n_outlets=2,
                split_fractions=[[0.5, 0.5], [0.5 + 1e-10, 0.5 - 1e-10]],
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Port + category contract
# ─────────────────────────────────────────────────────────────────────────────


def _make_separator() -> SeparatorHF:
    return SeparatorHF("s", ["A", "B"], SeparatorHFParams(n_outlets=2))


def _make_flash() -> FlashVLHF:
    comps = ["benzene", "toluene"]
    return FlashVLHF("f", comps, FlashVLHFParams(species_vle=comps))


def _make_flash_sl() -> FlashSL:
    return FlashSL(
        "fsl",
        FlashSLParams(
            species=["NaCl"],
            MW_kg_per_mol={"NaCl": 0.0585},
            S_ref={"NaCl": 6.0e3},
            dH_sol={"NaCl": 3000.0},
        ),
    )


def _make_distillation() -> DistillationHF:
    comps = ["benzene", "toluene"]
    return DistillationHF(
        "d", comps,
        DistillationHFParams(
            species_vle=comps, lk="benzene", hk="toluene",
        ),
    )


class TestSeparatorPorts:
    def test_separator_inlet_port(self):
        assert isinstance(_make_separator().inlet_port, StreamPort)

    def test_separator_outlet_ports_list(self):
        unit = _make_separator()
        assert isinstance(unit.outlet_ports, list)
        assert all(isinstance(p, StreamPort) for p in unit.outlet_ports)

    def test_flash_vl_ports(self):
        f = _make_flash()
        assert isinstance(f.inlet_port, StreamPort)
        assert isinstance(f.vapor_port, StreamPort)
        assert isinstance(f.liquid_port, StreamPort)

    def test_flash_sl_ports(self):
        f = _make_flash_sl()
        for tag in ("solid_in_port", "solvent_in_port",
                    "solution_port", "solid_out_port"):
            assert isinstance(getattr(f, tag), StreamPort)


class TestSeparatorCategories:
    def test_separator_is_industrial(self):
        assert _make_separator().category == UnitCategory.INDUSTRIAL

    def test_flash_vl_is_industrial(self):
        assert _make_flash().category == UnitCategory.INDUSTRIAL

    def test_flash_sl_is_industrial(self):
        assert _make_flash_sl().category == UnitCategory.INDUSTRIAL

    def test_distillation_remains_screening(self):
        # A.0 classified shortcut FUG as SCREENING; the audit must preserve it.
        assert _make_distillation().category == UnitCategory.SCREENING


# ─────────────────────────────────────────────────────────────────────────────
# CAPEX + KPI gaps closed in A.3
# ─────────────────────────────────────────────────────────────────────────────


_FEED_FLASH: Dict[str, float] = {
    "f.inlet.F_benzene": 0.5, "f.inlet.F_toluene": 0.5,
    "f.inlet.T": 370.0, "f.inlet.P": 101325.0,
    "f.vapor.F_benzene": 0.3, "f.vapor.F_toluene": 0.2,
    "f.liquid.F_benzene": 0.2, "f.liquid.F_toluene": 0.3,
    "f.vapor.T": 370.0, "f.vapor.P": 101325.0,
    "f.liquid.T": 370.0, "f.liquid.P": 101325.0,
    "f.V_frac": 0.5, "f.Q": 0.0,
}

_FEED_FSL: Dict[str, float] = {
    "fsl.solid_in.F_NaCl": 0.5,  # kg/s
    "fsl.solid_in.T": 300.0,
    "fsl.solvent_in.F_solvent": 10.0,  # kg/s
    "fsl.solvent_in.T": 300.0,
    "fsl.solution.F_NaCl": 0.005,
    "fsl.solution.T": 300.0,
    "fsl.solid_out.F_NaCl": 0.001,
    "fsl.V_sol_m3_s": 0.01,
}


class TestSeparatorCAPEX:
    def test_separator_capex_positive(self):
        unit = _make_separator()
        x = {
            "s.inlet.F_A": 0.5, "s.inlet.F_B": 0.5,
            "s.inlet.T": 400.0, "s.inlet.P": 101325.0,
        }
        assert unit.capex(x) > 0

    def test_flash_capex_positive(self):
        # Pre-A.3 the FlashVLHF unit returned 0 (base-class default).
        assert _make_flash().capex(_FEED_FLASH) > 0

    def test_flash_sl_capex_positive(self):
        # Pre-A.3 the FlashSL unit returned 0 (base-class default).
        assert _make_flash_sl().capex(_FEED_FSL) > 0


class TestSeparatorKPIs:
    def test_separator_kpis_nonempty(self):
        unit = _make_separator()
        kpis = unit.kpis({"s.inlet.F_A": 1.0, "s.outlet_0.F_A": 0.5})
        assert len(kpis) >= 1

    def test_flash_kpis_nonempty(self):
        assert len(_make_flash().kpis(_FEED_FLASH)) >= 1

    def test_flash_sl_kpis_nonempty(self):
        # Pre-A.3 FlashSL had no kpis() — base-class default returned empty.
        assert len(_make_flash_sl().kpis(_FEED_FSL)) >= 1
