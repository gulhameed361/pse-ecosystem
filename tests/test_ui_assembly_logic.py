"""Tests for Custom Flowsheet UI assembly logic.

Validates that build_custom_flowsheet() correctly:
- Instantiates all 4 new unit types (BiomassStorageHF, BiomassGasifierHF,
  WGSReactorHF, CoolerHF) registered in AVAILABLE_UNITS.
- Applies the flow-only fallback when T/P port variable counts differ.
- Produces >= 6 connections for the 7-unit biomass workshop chain.
- v1.6.1 P.6: the Custom Builder page module calls
  ``available_units_for_persona`` rather than ``AVAILABLE_UNITS`` directly,
  so the unit picker filters by persona.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from pse_ecosystem.core.contracts import PrimalGuess
from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF, CoolerHFParams
from pse_ecosystem.ui.flowsheet_service import AVAILABLE_UNITS, build_custom_flowsheet


# ─────────────────────────────────────────────────────────────────────────────
# v1.6.1 P.6 — persona filter wired into the Custom Builder
# ─────────────────────────────────────────────────────────────────────────────


_FLOWSHEET_BUILDER_SRC = (
    Path(__file__).resolve().parent.parent
    / "pse_ecosystem" / "ui" / "pages" / "flowsheet_builder.py"
).read_text(encoding="utf-8")


class TestPersonaFilterWired:
    def test_available_units_for_persona_imported(self):
        """The page module must import the persona-aware helper, not
        just AVAILABLE_UNITS, so the picker filters by persona."""
        assert "available_units_for_persona" in _FLOWSHEET_BUILDER_SRC

    def test_unit_categories_for_persona_imported(self):
        """The category dropdown is also persona-filtered (empty groups
        like Feed/Product in Industrial mode are pruned)."""
        assert "unit_categories_for_persona" in _FLOWSHEET_BUILDER_SRC

    def test_persona_session_state_consulted(self):
        """The picker reads ``st.session_state['user_persona']`` to pick
        the active filter."""
        assert re.search(
            r"st\.session_state\.get\(\s*['\"]user_persona['\"]",
            _FLOWSHEET_BUILDER_SRC,
        ), "Custom Builder doesn't consult user_persona session-state."

    def test_category_badge_table_present(self):
        """A category badge is shown next to each unit type so users
        understand why DIDACTIC / LEGACY units are hidden."""
        for badge in ("INDUSTRIAL", "SCREENING", "DIDACTIC", "LEGACY"):
            assert badge in _FLOWSHEET_BUILDER_SRC, (
                f"Category badge {badge!r} missing from Custom Builder."
            )

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
    """v1.5.3: CoolerHF now has T/P ports, Q_duty energy balance, is non-linear."""

    def _make(self, comps=None) -> CoolerHF:
        comps = comps or SYNGAS_6
        return CoolerHF("cooler", comps, CoolerHFParams(T_out_K=310.0))

    def _full_x(self, unit, T_in=600.0, T_out=310.0, P=101325.0, F=2.5):
        """Build a physically consistent state dict."""
        x = {}
        for c in unit.components:
            x[f"cooler.inlet.F_{c}"] = F
            x[f"cooler.outlet.F_{c}"] = F
        x["cooler.inlet.T"] = T_in
        x["cooler.outlet.T"] = T_out
        x["cooler.inlet.P"] = P
        x["cooler.outlet.P"] = P
        # Q_duty set to something; residual will show how far off we are
        x["cooler.Q_duty_kW"] = 0.0
        return x

    def test_residual_shape(self):
        """v1.5.3: residual shape is N+3 (mass×N + T_out pin + P pass + energy)."""
        unit = self._make()
        x = self._full_x(unit)
        res = unit.residual(x)
        assert res.shape == (len(SYNGAS_6) + 3,)

    def test_residual_mass_conservation(self):
        """First N residuals are the mass conservation rows (inlet = outlet)."""
        unit = self._make()
        x = self._full_x(unit)
        res = unit.residual(x)
        N = len(SYNGAS_6)
        np.testing.assert_allclose(res[:N], 0.0, atol=1e-10)

    def test_residual_t_out_pin(self):
        """Row N: T_out pinned at T_out_K=310."""
        unit = self._make()
        x = self._full_x(unit, T_out=310.0)
        res = unit.residual(x)
        N = len(SYNGAS_6)
        assert res[N] == pytest.approx(0.0, abs=1e-10)

    def test_residual_t_out_pin_violation(self):
        """Row N non-zero when T_out ≠ T_out_K."""
        unit = self._make()
        x = self._full_x(unit, T_out=400.0)
        res = unit.residual(x)
        N = len(SYNGAS_6)
        assert abs(res[N]) > 0.1  # 400 - 310 = 90 K off

    def test_is_nonlinear(self):
        """v1.5.3: CoolerHF is now non-linear due to energy balance."""
        assert CoolerHF.is_linear is False

    def test_linearize_not_exact(self):
        """Semi-analytical linearize; is_exact=False because T_in is non-linear."""
        unit = self._make()
        vals = {v: 1.0 for v in unit.variables()}
        vals["cooler.inlet.T"] = 600.0
        vals["cooler.outlet.T"] = 310.0
        guess = PrimalGuess(values=vals)
        lin = unit.linearize(guess)
        assert lin.is_exact is False
        N = len(SYNGAS_6)
        assert lin.J.shape == (N + 3, len(unit.variables()))

    def test_kpis_return_t_out_from_solution(self):
        """v1.5.3: T_out_K KPI reads from solution variable, not params."""
        unit = self._make()
        x = self._full_x(unit, T_out=310.0)
        kpis = unit.kpis(x)
        assert "cooler.T_out_K" in kpis
        assert kpis["cooler.T_out_K"] == pytest.approx(310.0, abs=1.0)

    def test_kpis_include_q_duty(self):
        """v1.5.3: Q_duty_kW must appear in KPIs."""
        unit = self._make()
        x = self._full_x(unit)
        kpis = unit.kpis(x)
        assert "cooler.Q_duty_kW" in kpis

    def test_ports_have_t_and_p(self):
        """v1.5.3: CoolerHF now has T and P on both ports."""
        unit = self._make()
        assert unit.inlet_port.has_T is True
        assert unit.inlet_port.has_P is True
        assert unit.outlet_port.has_T is True
        assert unit.outlet_port.has_P is True

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


def test_7_unit_chain_exact_equality_count(seven_unit_fs):
    """v1.5.3: 35 port-variable equalities (was 33).

    The +2 come from CoolerHF gaining T/P ports: the cooler → psa (SeparatorHF)
    connection is now a full-port match (8 equalities vs 6 before). The
    wgs → cooler connection is still flow-only (WGS has no T/P) so the
    count there stays at 6.

    Breakdown:
      storage→gasifier :  1 (biomass flow)
      gasifier→cyclone :  6 (syngas flows, padded — gasifier no T/P)
      cyclone→wgs      :  6 (syngas flows, padded — WGS no T/P)
      wgs→cooler       :  6 (syngas flows, padded — WGS no T/P)
      cooler→psa       :  8 (6 flows + T + P — both have T/P now)
      psa→comp         :  8 (6 flows + T + P — both have T/P)
      Total            : 35
    """
    assert len(seven_unit_fs.connections) == 35, (
        f"Expected 35 port-variable equalities, got {len(seven_unit_fs.connections)}. "
        f"Warnings: {seven_unit_fs._conn_warnings}"
    )


def test_7_unit_chain_no_fatal_warnings(seven_unit_fs):
    fatal = [w for w in seven_unit_fs._conn_warnings
             if "mismatch" in w.lower() or "skipped" in w.lower()]
    assert fatal == [], f"Fatal connection warnings found: {fatal}"


# ── Zero-fill padder tests ─────────────────────────────────────────────────────

def test_zero_fill_padder_connects_matched_species():
    """Storage (1 comp: Biomass) → SeparatorHF (6 comps) triggers padder.
    Matched species are connected; unmatched inlet species are zero-filled."""
    cfg = {
        "units": [
            {"type": "BiomassStorageHF", "id": "storage", "params": {}},
            {
                "type": "SeparatorHF", "id": "cyclone",
                "params": {"components": SYNGAS_6, "n_outlets": 2},
            },
        ],
        "connections": [{"from_unit": "storage", "to_unit": "cyclone"}],
    }
    fs = build_custom_flowsheet(cfg)
    # No connection is skipped — padder must have fired.
    skipped = [w for w in fs._conn_warnings if "skipped" in w.lower()]
    assert skipped == [], f"Connection skipped instead of padded: {skipped}"
    # Biomass doesn't match any syngas species → 0 connections, 6 zero-fills.
    padded_warns = [w for w in fs._conn_warnings if "padded" in w.lower()]
    assert padded_warns, "Expected at least one 'padded' warning from zero-fill path"
    # All 6 inlet F_ vars should be pinned to 0 via extra_equalities.
    assert len(fs.extra_equalities) == 6, (
        f"Expected 6 zero-fill equalities, got {len(fs.extra_equalities)}"
    )


def test_zero_fill_padder_plotly_layout_no_key_collision():
    """PSE_PLOTLY_TEMPLATE['layout'] must not contain keys that collide with
    explicit update_layout() kwargs in _page_scenario_manager."""
    from pse_ecosystem.ui.flowsheet_service import PSE_PLOTLY_TEMPLATE
    layout = PSE_PLOTLY_TEMPLATE["layout"]
    collision_keys = {"barmode", "yaxis2"}
    # 'yaxis' IS in the template but is stripped via _sc_layout; verify it's there so
    # the collision-strip logic stays necessary and correct.
    assert "yaxis" in layout, "Template lost 'yaxis' key — strip logic is stale"
    assert not collision_keys & set(layout), (
        f"Template gained a key that collides with scenario chart: {collision_keys & set(layout)}"
    )
