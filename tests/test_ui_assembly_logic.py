"""Tests for Custom Flowsheet UI assembly logic.

Validates that build_custom_flowsheet() correctly:
- Instantiates all 4 new unit types (BiomassStorageHF, BiomassGasifierHF,
  WGSReactorHF, CoolerHF) registered in AVAILABLE_UNITS.
- Applies the flow-only fallback when T/P port variable counts differ.
- Produces >= 6 connections for the 7-unit biomass workshop chain.
"""

from __future__ import annotations

import numpy as np
import pytest

from pse_ecosystem.core.contracts import PrimalGuess
from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF, CoolerHFParams
from pse_ecosystem.ui.flowsheet_service import AVAILABLE_UNITS, build_custom_flowsheet

SYNGAS_6 = ["H2", "CO", "CO2", "H2O", "CH4", "N2"]

SEVEN_UNIT_CONFIG = {
    "units": [
        {"type": "BiomassStorageHF", "id": "storage", "params": {}},
        {
            "type": "BiomassGasifierHF",
            "id": "gasifier",
            "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"},
        },
        {
            "type": "SeparatorHF",
            "id": "cyclone",
            "params": {"components": SYNGAS_6, "n_outlets": 2},
        },
        {"type": "WGSReactorHF", "id": "wgs", "params": {"T_wgs_C": 400.0}},
        {
            "type": "CoolerHF",
            "id": "cooler",
            "params": {"components": SYNGAS_6, "T_out_K": 310.0},
        },
        {
            "type": "SeparatorHF",
            "id": "psa",
            "params": {"components": SYNGAS_6, "n_outlets": 2},
        },
        {
            "type": "Compressor",
            "id": "comp",
            "params": {"components": SYNGAS_6, "P_out_Pa": 5e6},
        },
    ],
    "connections": [
        {"from_unit": "storage",  "to_unit": "gasifier"},
        {"from_unit": "gasifier", "to_unit": "cyclone"},
        {"from_unit": "cyclone",  "to_unit": "wgs"},
        {"from_unit": "wgs",      "to_unit": "cooler"},
        {"from_unit": "cooler",   "to_unit": "psa"},
        {"from_unit": "psa",      "to_unit": "comp"},
    ],
}


# ── CoolerHF unit tests ───────────────────────────────────────────────────────

class TestCoolerHF:
    def _make(self, comps=None) -> CoolerHF:
        comps = comps or SYNGAS_6
        return CoolerHF("cooler", comps, CoolerHFParams(T_out_K=310.0))

    def test_residual_shape(self):
        unit = self._make()
        x = {f"cooler.inlet.F_{c}": 1.0 for c in SYNGAS_6}
        x.update({f"cooler.outlet.F_{c}": 1.0 for c in SYNGAS_6})
        res = unit.residual(x)
        assert res.shape == (len(SYNGAS_6),)

    def test_residual_zero_at_steady_state(self):
        unit = self._make()
        x = {f"cooler.inlet.F_{c}": 2.5 for c in SYNGAS_6}
        x.update({f"cooler.outlet.F_{c}": 2.5 for c in SYNGAS_6})
        np.testing.assert_allclose(unit.residual(x), 0.0, atol=1e-12)

    def test_is_linear(self):
        assert CoolerHF.is_linear is True

    def test_linearize_exact(self):
        unit = self._make()
        vals = {v: 1.0 for v in unit.variables()}
        guess = PrimalGuess(values=vals)
        lin = unit.linearize(guess)
        assert lin.is_exact is True
        assert lin.J.shape == (len(SYNGAS_6), 2 * len(SYNGAS_6))

    def test_kpis_return_t_out(self):
        unit = self._make()
        x = {v: 1.0 for v in unit.variables()}
        kpis = unit.kpis(x)
        assert kpis["cooler.T_out_K"] == pytest.approx(310.0)

    def test_ports_named_inlet_outlet(self):
        unit = self._make()
        assert hasattr(unit, "inlet_port")
        assert hasattr(unit, "outlet_port")


# ── AVAILABLE_UNITS registration tests ───────────────────────────────────────

class TestNewUnitRegistration:
    @pytest.mark.parametrize("utype", [
        "BiomassStorageHF", "BiomassGasifierHF", "WGSReactorHF", "CoolerHF",
    ])
    def test_unit_in_available_units(self, utype):
        assert utype in AVAILABLE_UNITS

    def test_biomass_storage_instantiates(self):
        cfg = {
            "units": [{"type": "BiomassStorageHF", "id": "s", "params": {}}],
            "connections": [],
        }
        fs = build_custom_flowsheet(cfg)
        assert len(fs.units) == 1

    def test_biomass_gasifier_instantiates(self):
        cfg = {
            "units": [
                {"type": "BiomassGasifierHF", "id": "g",
                 "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"}}
            ],
            "connections": [],
        }
        fs = build_custom_flowsheet(cfg)
        assert len(fs.units) == 1

    def test_wgs_reactor_instantiates(self):
        cfg = {
            "units": [{"type": "WGSReactorHF", "id": "w", "params": {"T_wgs_C": 400.0}}],
            "connections": [],
        }
        fs = build_custom_flowsheet(cfg)
        assert len(fs.units) == 1

    def test_cooler_hf_instantiates_via_service(self):
        cfg = {
            "units": [
                {"type": "CoolerHF", "id": "c",
                 "params": {"components": SYNGAS_6, "T_out_K": 350.0}}
            ],
            "connections": [],
        }
        fs = build_custom_flowsheet(cfg)
        assert len(fs.units) == 1


# ── Flow-only fallback test ───────────────────────────────────────────────────

def test_flow_only_fallback_creates_connections():
    """WGS (no T/P) → SeparatorHF (has T/P by default) would raise ValueError
    inside fs.connect(); the fallback must still wire the 6 F_ variables."""
    cfg = {
        "units": [
            {"type": "WGSReactorHF", "id": "wgs", "params": {"T_wgs_C": 400.0}},
            {"type": "SeparatorHF",  "id": "sep",
             "params": {"components": SYNGAS_6, "n_outlets": 2}},
        ],
        "connections": [{"from_unit": "wgs", "to_unit": "sep"}],
    }
    fs = build_custom_flowsheet(cfg)
    assert len(fs.connections) > 0, (
        "Flow-only fallback failed: 0 connections created for WGS→SeparatorHF link. "
        f"Warnings: {fs._conn_warnings}"
    )


# ── 7-unit chain integration tests ───────────────────────────────────────────

@pytest.fixture(scope="module")
def seven_unit_fs():
    return build_custom_flowsheet(SEVEN_UNIT_CONFIG)


def test_7_unit_chain_unit_count(seven_unit_fs):
    assert len(seven_unit_fs.units) == 7


def test_7_unit_chain_connection_count(seven_unit_fs):
    assert len(seven_unit_fs.connections) >= 6, (
        f"Expected >= 6 connections, got {len(seven_unit_fs.connections)}. "
        f"Warnings: {seven_unit_fs._conn_warnings}"
    )


def test_7_unit_chain_no_fatal_warnings(seven_unit_fs):
    fatal = [w for w in seven_unit_fs._conn_warnings
             if "mismatch" in w.lower() or "skipped" in w.lower()]
    assert fatal == [], f"Fatal connection warnings found: {fatal}"
