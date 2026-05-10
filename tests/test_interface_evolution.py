"""Phase 1 tests — StreamPort, fs.connect(), BaseUnit additions."""

import pytest

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams


# ── StreamPort ────────────────────────────────────────────────────────────────


def test_stream_port_variable_names_order():
    port = StreamPort("r1", "outlet", components=["A", "B"], has_T=True, has_P=True)
    names = port.variable_names()
    assert names == ["r1.outlet.F_A", "r1.outlet.F_B", "r1.outlet.T", "r1.outlet.P"]


def test_stream_port_no_TP():
    port = StreamPort("m1", "inlet", components=["H2", "N2"], has_T=False, has_P=False)
    names = port.variable_names()
    assert names == ["m1.inlet.F_H2", "m1.inlet.F_N2"]


def test_stream_port_accessors():
    port = StreamPort("cstr", "outlet", components=["A", "B"])
    assert port.T() == "cstr.outlet.T"
    assert port.P() == "cstr.outlet.P"
    assert port.F("A") == "cstr.outlet.F_A"
    assert port.F("B") == "cstr.outlet.F_B"


def test_stream_port_empty_components():
    port = StreamPort("valve", "outlet", components=[], has_T=True, has_P=True)
    assert port.variable_names() == ["valve.outlet.T", "valve.outlet.P"]


# ── fs.connect() ──────────────────────────────────────────────────────────────


def _make_pem_flowsheet():
    pem = PEMToy(params=PEMToyParams())
    return BaseFlowsheet(name="test", units=[pem], connections=[])


def test_fs_connect_generates_connections():
    fs = _make_pem_flowsheet()
    port_a = StreamPort("cstr", "outlet", components=["A", "B"])
    port_b = StreamPort("flash", "inlet", components=["A", "B"])

    assert len(fs.connections) == 0
    fs.connect(port_a, port_b, description="test link")

    assert len(fs.connections) == 4  # F_A, F_B, T, P
    assert fs.connections[0].var_a == "cstr.outlet.F_A"
    assert fs.connections[0].var_b == "flash.inlet.F_A"
    assert fs.connections[2].var_a == "cstr.outlet.T"
    assert fs.connections[3].var_a == "cstr.outlet.P"


def test_fs_connect_description_propagated():
    fs = _make_pem_flowsheet()
    port_a = StreamPort("u1", "out", components=["X"])
    port_b = StreamPort("u2", "in", components=["X"])
    fs.connect(port_a, port_b, description="reactor feed")
    assert all(c.description == "reactor feed" for c in fs.connections)


def test_fs_connect_mismatched_ports_raises():
    fs = _make_pem_flowsheet()
    port_a = StreamPort("u1", "out", components=["A", "B"])  # 4 vars
    port_b = StreamPort("u2", "in", components=["A"])        # 3 vars
    with pytest.raises(ValueError, match="Ports must match"):
        fs.connect(port_a, port_b)


def test_fs_connect_multiple_calls_accumulate():
    fs = _make_pem_flowsheet()
    port_a = StreamPort("u1", "out", components=["A"])
    port_b = StreamPort("u2", "in", components=["A"])
    port_c = StreamPort("u2", "out", components=["B"])
    port_d = StreamPort("u3", "in", components=["B"])
    fs.connect(port_a, port_b)
    fs.connect(port_c, port_d)
    assert len(fs.connections) == 6  # 3 + 3


# ── BaseUnit new optional methods ─────────────────────────────────────────────


def test_capex_default_returns_zero():
    pem = PEMToy(params=PEMToyParams())
    x = {"pem.electricity_kW": 5000.0, "pem.h2_kg_per_h": 90.0}
    assert pem.capex(x) == 0.0


def test_opex_per_year_default_sums_objective():
    pem = PEMToy(params=PEMToyParams(electricity_price_per_kWh=0.05, operating_hours_per_year=8760))
    x = {"pem.electricity_kW": 1000.0, "pem.h2_kg_per_h": 18.0}
    opex = pem.opex_per_year(x)
    obj = pem.objective_contribution(x)
    expected = sum(c * x.get(v, 0.0) for v, c in obj.items())
    assert abs(opex - expected) < 1e-6


def test_control_hooks_default_empty():
    pem = PEMToy(params=PEMToyParams())
    assert pem.control_hooks() == {}


def test_get_linearization_matches_linearize():
    from pse_ecosystem.core.contracts import PrimalGuess

    pem = PEMToy(params=PEMToyParams())
    x = {"pem.electricity_kW": 5000.0, "pem.h2_kg_per_h": 90.0}
    lm_alias = pem.get_linearization(x)
    lm_direct = pem.linearize(PrimalGuess(values=x, iteration=0))

    import numpy as np
    assert lm_alias.unit_id == lm_direct.unit_id
    assert lm_alias.variables == lm_direct.variables
    assert lm_alias.is_exact == lm_direct.is_exact
    assert abs(lm_alias.f0 - lm_direct.f0).max() < 1e-10


def test_all_baseline_audit_checks_still_pass():
    """Regression: Phase 1 changes must not break any existing unit interface."""
    from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy, GasifierToyParams

    gas = GasifierToy(params=GasifierToyParams())
    x = {"gasifier.feed_kg_per_h": 2000.0, "gasifier.h2_kg_per_h": 200.0,
         "gasifier.steam_kg_per_h": 500.0}
    # get_linearization must return correctly shaped LinearizedModel
    lm = gas.get_linearization(x)
    assert lm.J.shape[1] == len(gas.variables())
    assert lm.J.shape[0] == len(gas.residual(x))
    assert lm.unit_id == "gasifier"
    # capex/opex/control_hooks available on existing units
    assert gas.capex(x) == 0.0
    assert isinstance(gas.control_hooks(), dict)
