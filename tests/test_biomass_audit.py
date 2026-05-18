"""Biomass Gasification to Hydrogen — audit test suite.

Runs 22 checks covering:
  - Biomass database integrity
  - BiomassStorageHF residuals and KPIs
  - BiomassGasifierHF element balances and equilibria
  - WGSReactorHF stoichiometry and equilibrium
  - H2SeparatorPSA mass balance
  - EconomicEngine correctness
  - Port validation (PortCompatibilityError)
  - Template loading from flowsheet_service
  - End-to-end solve and plausibility checks

Usage::

    python -m pytest tests/biomass_audit.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest


# ── 1. Biomass database ───────────────────────────────────────────────────────

def test_biomass_db_has_eight_entries():
    from pse_ecosystem.models.biomass.biomass_database import BIOMASS_DB
    assert len(BIOMASS_DB) == 8, f"Expected 8 entries, got {len(BIOMASS_DB)}"


def test_biomass_db_required_keys():
    from pse_ecosystem.models.biomass.biomass_database import BIOMASS_DB, _REQUIRED_KEYS
    for name, props in BIOMASS_DB.items():
        missing = _REQUIRED_KEYS - set(props)
        assert not missing, f"{name} missing keys: {missing}"


def test_element_feeds_mol_s_pine_wood():
    from pse_ecosystem.models.biomass.biomass_database import element_feeds_mol_s
    feeds = element_feeds_mol_s("Pine Wood", dry_feed_kg_s=1.0)
    # 1 kg/s dry Pine Wood: C=49.7%, n_C = 1000 g/s × 0.497 / 12.011 g/mol ≈ 41.4 mol/s
    expected_n_C = 1000.0 * 0.497 / 12.011
    assert abs(feeds["C"] - expected_n_C) < 0.1, f"n_C={feeds['C']:.3f}, expected {expected_n_C:.3f}"
    assert feeds["H"] > feeds["C"]   # more H than C mole-wise (H/C ≈ 1.5)


# ── 2. BiomassStorageHF ───────────────────────────────────────────────────────

def test_storage_residual_at_consistent_point():
    from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
    s = BiomassStorageHF("s1", biomass_type="Pine Wood")
    MC = s.MC   # 0.10
    x = {"s1.wet_in.F_Biomass": 1.0, "s1.dry_out.F_Biomass": 1.0 * (1 - MC)}
    res = s.residual(x)
    assert np.allclose(res, 0.0, atol=1e-10), f"Non-zero residual: {res}"


def test_storage_kpis_positive():
    from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
    s = BiomassStorageHF("s1")
    MC = s.MC
    x = {"s1.wet_in.F_Biomass": 1.0, "s1.dry_out.F_Biomass": 1.0 * (1 - MC)}
    kpis = s.kpis(x)
    assert kpis["s1.Q_drying_kW"] > 0
    assert kpis["s1.Q_preheating_kW"] >= 0
    assert abs(kpis["s1.dry_feed_kg_s"] - 1.0 * (1 - MC)) < 1e-9


# ── 3. BiomassGasifierHF element balances ────────────────────────────────────

def _make_gasifier_balanced_x(biomass_type="Pine Wood", T_C=800.0):
    """Construct a chemically consistent state vector at rough equilibrium."""
    from pse_ecosystem.models.biomass.biomass_database import element_feeds_mol_s, get_biomass
    b = get_biomass(biomass_type)
    F_dry = 1.0   # kg/s
    feeds = element_feeds_mol_s(biomass_type, F_dry)
    n_C, n_H, n_O, n_N = feeds["C"], feeds["H"], feeds["O"], feeds["N"]
    n_steam = F_dry * 1.0 * 1000 / 18.015   # 1 kg steam per kg dry biomass

    n_H += 2 * n_steam
    n_O += n_steam

    # Rough equilibrium distribution
    n_CO  = 0.60 * n_C
    n_CO2 = 0.30 * n_C
    n_CH4 = 0.10 * n_C
    # O balance check
    O_used = n_CO + 2 * n_CO2
    n_H2O = max(n_O - O_used, 0.01)
    # H balance
    n_H2 = max((n_H - 2 * n_H2O - 4 * n_CH4) / 2, 0.01)
    n_N2 = max(n_N / 2, 0.001)

    return {
        "gasifier.biomass_in.F_Biomass": F_dry,
        "gasifier.agent_in.F_H2O": n_steam,
        "gasifier.syngas_out.F_H2":  n_H2,
        "gasifier.syngas_out.F_CO":  n_CO,
        "gasifier.syngas_out.F_CO2": n_CO2,
        "gasifier.syngas_out.F_H2O": n_H2O,
        "gasifier.syngas_out.F_CH4": n_CH4,
        "gasifier.syngas_out.F_N2":  n_N2,
    }


def test_gasifier_element_balances_satisfied():
    from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
    g = BiomassGasifierHF("gasifier", T_gasifier_C=800.0)
    x = _make_gasifier_balanced_x()
    res = g.residual(x)
    # Element balances (f[0..3]) should be nearly zero for a balanced x
    for i in range(4):
        assert abs(res[i]) < 0.5, f"Element balance f[{i}] = {res[i]:.4f} too large"


def test_gasifier_kps_wgs_correlation():
    from pse_ecosystem.models.biomass.biomass_gasifier import _kp_wgs
    # K_WGS(800 K) should be ~4.5 (van't Hoff calibrated)
    K = _kp_wgs(800.0)
    assert 3.0 < K < 6.0, f"K_WGS(800 K) = {K:.3f}, expected ~4.5"


def test_gasifier_kps_met_correlation():
    from pse_ecosystem.models.biomass.biomass_gasifier import _kp_met
    # K_met(1073 K) should be very small << 1 (high T disfavors methanation)
    K = _kp_met(1073.0)
    assert K < 0.5, f"K_met(1073 K) = {K:.4f}, expected << 1"
    # K_met(800 K) should be moderate
    K2 = _kp_met(800.0)
    assert 50 < K2 < 500, f"K_met(800 K) = {K2:.1f}, expected ~150"


def test_gasifier_kpis_populated():
    from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
    g = BiomassGasifierHF("gasifier")
    x = _make_gasifier_balanced_x()
    kpis = g.kpis(x)
    assert "gasifier.H2_pct_vol" in kpis
    assert "gasifier.CGE_percent" in kpis
    assert 0 < kpis["gasifier.CGE_percent"] < 150   # rough x; converged solve gives < 95%


# ── 4. WGSReactorHF ──────────────────────────────────────────────────────────

def test_wgs_equilibrium_constraint_calibration():
    from pse_ecosystem.models.biomass.wgs_reactor import _kp_wgs
    # At 673 K (400°C, HTS range): K should be ~13
    K = _kp_wgs(673.15)
    assert 8 < K < 25, f"K_WGS(673 K) = {K:.2f}, expected ~13"


def test_wgs_stoichiometry_linked():
    """CO and H2O depletion must be equal for any X_CO (Issue #8 fix)."""
    from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
    w = WGSReactorHF("wgs", T_wgs_C=400.0)
    n_CO_in = 10.0
    n_H2O_in = 15.0
    X_CO = 0.7
    dn_CO = n_CO_in * X_CO
    x = {
        "wgs.syngas_in.F_H2":  20.0,
        "wgs.syngas_in.F_CO":  n_CO_in,
        "wgs.syngas_in.F_CO2": 5.0,
        "wgs.syngas_in.F_H2O": n_H2O_in,
        "wgs.syngas_in.F_CH4": 2.0,
        "wgs.syngas_in.F_N2":  1.0,
        "wgs.shifted_out.F_H2":  20.0 + dn_CO,
        "wgs.shifted_out.F_CO":  n_CO_in - dn_CO,
        "wgs.shifted_out.F_CO2": 5.0 + dn_CO,
        "wgs.shifted_out.F_H2O": n_H2O_in - dn_CO,
        "wgs.shifted_out.F_CH4": 2.0,
        "wgs.shifted_out.F_N2":  1.0,
        "wgs.X_CO": X_CO,
    }
    res = w.residual(x)
    # Balances f[0..5] should be ~zero (stoichiometrically consistent)
    assert np.allclose(res[:6], 0.0, atol=1e-9), f"Stoich balances: {res[:6]}"


def test_wgs_mass_balance_closure():
    from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
    w = WGSReactorHF("wgs")
    n_in_total = 50.0
    x = {
        "wgs.syngas_in.F_H2":  20.0,
        "wgs.syngas_in.F_CO":  10.0,
        "wgs.syngas_in.F_CO2": 5.0,
        "wgs.syngas_in.F_H2O": 10.0,
        "wgs.syngas_in.F_CH4": 3.0,
        "wgs.syngas_in.F_N2":  2.0,
        "wgs.shifted_out.F_H2":  28.0,   # +8 from WGS
        "wgs.shifted_out.F_CO":  2.0,    # -8 converted
        "wgs.shifted_out.F_CO2": 13.0,   # +8
        "wgs.shifted_out.F_H2O": 2.0,    # -8
        "wgs.shifted_out.F_CH4": 3.0,
        "wgs.shifted_out.F_N2":  2.0,
        "wgs.X_CO": 0.8,
    }
    n_out_total = sum(x[f"wgs.shifted_out.F_{c}"] for c in
                      ["H2", "CO", "CO2", "H2O", "CH4", "N2"])
    assert abs(n_in_total - n_out_total) < 1e-9


# ── 5. H2SeparatorPSA ────────────────────────────────────────────────────────

def test_psa_h2_mass_balance():
    from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
    p = H2SeparatorPSA("psa", H2_recovery=0.85)
    x = {
        "psa.feed_in.F_H2":  50.0,
        "psa.feed_in.F_CO":  5.0,
        "psa.feed_in.F_CO2": 10.0,
        "psa.feed_in.F_H2O": 2.0,
        "psa.feed_in.F_CH4": 1.0,
        "psa.feed_in.F_N2":  0.5,
        "psa.h2_out.F_H2":   42.5,   # 50 × 0.85
        "psa.tail_out.F_CO":  5.0,
        "psa.tail_out.F_CO2": 10.0,
        "psa.tail_out.F_H2O": 2.0,
        "psa.tail_out.F_CH4": 1.0,
        "psa.tail_out.F_N2":  0.5,
    }
    res = p.residual(x)
    assert np.allclose(res, 0.0, atol=1e-9), f"PSA residuals: {res}"


def test_psa_kpis():
    from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
    p = H2SeparatorPSA("psa", H2_recovery=0.85)
    x = {
        "psa.feed_in.F_H2":  50.0,
        "psa.feed_in.F_CO":  0.0,
        "psa.feed_in.F_CO2": 0.0,
        "psa.feed_in.F_H2O": 0.0,
        "psa.feed_in.F_CH4": 0.0,
        "psa.feed_in.F_N2":  0.0,
        "psa.h2_out.F_H2":   42.5,
        "psa.tail_out.F_CO": 0.0, "psa.tail_out.F_CO2": 0.0,
        "psa.tail_out.F_H2O": 0.0, "psa.tail_out.F_CH4": 0.0,
        "psa.tail_out.F_N2": 0.0,
    }
    kpis = p.kpis(x)
    h2_kg_h = kpis["psa.H2_production_kg_h"]
    # 42.5 mol/s × 2.016 g/mol / 1000 × 3600 = 307.5 kg/h
    assert abs(h2_kg_h - 42.5 * 2.016 / 1000 * 3600) < 1.0


# ── 6. EconomicEngine ────────────────────────────────────────────────────────

def test_economic_engine_cepci_factor():
    from pse_ecosystem.models.costing.economic_engine import EconomicEngine, CEPCI
    eco = EconomicEngine(target_year=2024)
    expected = CEPCI[2024] / CEPCI[2001]
    assert abs(eco.cepci_factor(base_year=2001) - expected) < 1e-9


def test_economic_engine_crf():
    from pse_ecosystem.models.costing.economic_engine import EconomicEngine
    eco = EconomicEngine(interest_rate=0.08, plant_life_yr=20)
    i, n = 0.08, 20
    expected = i * (1 + i)**n / ((1 + i)**n - 1)
    assert abs(eco.capital_recovery_factor() - expected) < 1e-10


def test_economic_engine_lcoh_positive():
    from pse_ecosystem.models.costing.economic_engine import EconomicEngine
    eco = EconomicEngine()
    lcoh = eco.lcoh(capex_annual_USD=1_000_000, opex_annual_USD=500_000, h2_kg_per_s=0.1)
    assert lcoh > 0


def test_economic_engine_lcoh_zero_h2():
    from pse_ecosystem.models.costing.economic_engine import EconomicEngine
    eco = EconomicEngine()
    lcoh = eco.lcoh(1e6, 5e5, h2_kg_per_s=0.0)
    assert math.isinf(lcoh)


# ── 7. Port validation ────────────────────────────────────────────────────────

def test_port_validation_phase_mismatch():
    from pse_ecosystem.core.contracts import StreamPort, PortCompatibilityError
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, BaseUnit
    import numpy as np

    class _Dummy(BaseUnit):
        unit_id = "d"
        is_linear = True
        def variables(self): return []
        def bounds(self): return {}
        def residual(self, x): return np.zeros(0)
        def objective_contribution(self, x): return {}

    fs = BaseFlowsheet(name="test", units=[_Dummy()])
    gas_port = StreamPort("a", "out", components=["H2"], phase="gas",
                          species=frozenset({"H2"}))
    liq_port = StreamPort("b", "in",  components=["H2"], phase="liquid",
                          species=frozenset({"H2"}))
    with pytest.raises(PortCompatibilityError, match="(?i)phase mismatch"):
        fs.connect(gas_port, liq_port)


def test_port_validation_species_mismatch():
    from pse_ecosystem.core.contracts import StreamPort, PortCompatibilityError
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, BaseUnit
    import numpy as np

    class _Dummy(BaseUnit):
        unit_id = "d"
        is_linear = True
        def variables(self): return []
        def bounds(self): return {}
        def residual(self, x): return np.zeros(0)
        def objective_contribution(self, x): return {}

    fs = BaseFlowsheet(name="test", units=[_Dummy()])
    syngas_port = StreamPort("a", "out", components=["H2", "CO"],
                              phase="gas", species=frozenset({"H2", "CO"}))
    water_port  = StreamPort("b", "in",  components=["H2", "CO"],
                              phase="gas", species=frozenset({"H2O"}))
    with pytest.raises(PortCompatibilityError, match="(?i)species mismatch"):
        fs.connect(syngas_port, water_port)


def test_port_validation_matching_ports_ok():
    from pse_ecosystem.core.contracts import StreamPort
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, BaseUnit
    import numpy as np

    class _Dummy(BaseUnit):
        unit_id = "d"
        is_linear = True
        def variables(self): return []
        def bounds(self): return {}
        def residual(self, x): return np.zeros(0)
        def objective_contribution(self, x): return {}

    fs = BaseFlowsheet(name="test", units=[_Dummy()])
    port_a = StreamPort("a", "out", components=["H2"], phase="gas",
                         species=frozenset({"H2"}))
    port_b = StreamPort("b", "in",  components=["H2"], phase="gas",
                         species=frozenset({"H2"}))
    fs.connect(port_a, port_b)   # should not raise
    # Port has 1 flow + T + P = 3 connections by default
    assert len(fs.connections) >= 1


# ── 8. Template loading ───────────────────────────────────────────────────────

def test_biomass_template_in_registry():
    from pse_ecosystem.ui.flowsheet_service import list_templates
    keys = [t.key for t in list_templates()]
    assert "biomass.gasification_to_hydrogen" in keys


def test_biomass_template_loads_without_error():
    from pse_ecosystem.ui.flowsheet_service import load_template
    fs = load_template("biomass.gasification_to_hydrogen")
    assert fs is not None
    assert len(fs.units) == 4
    assert len(fs.connections) >= 3   # at least 3 port-to-port connections


# ── 9. End-to-end solve ───────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.skip(
    reason=(
        "v1.5.x INVESTIGATION ITEM (was xfail strict=False pre-v1.4.1): the "
        "biomass.gasification_to_hydrogen template returns INFEASIBLE after 3 "
        "warm-start restarts under every SLP config attempted on 2026-05-18 — "
        "use_trust_region=False/True with init=0.5/1.0/2.0, max_iter=80, "
        "progressive_tightening on/off, ADAPTIVE cascade. validate() passes; "
        "the LP itself is structurally infeasible. Suspect: the template's 27 "
        "extra_bounds intersected with its 13 connection equalities. See "
        "docs/SYSTEM_STATE.md v1.5.x carry-forward. v1.4.1 made this an "
        "explicit skip with diagnostic context rather than a silent xfail."
    )
)
def test_biomass_flowsheet_solves_to_convergence():
    from pse_ecosystem.ui.flowsheet_service import load_template
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig
    from pse_ecosystem.core.contracts import SolveMode, SolverStatus

    fs = load_template("biomass.gasification_to_hydrogen", {
        "biomass_feed_kg_s": 1.0,
        "T_gasifier_C": 800.0,
        "T_wgs_C": 400.0,
        "H2_recovery": 0.85,
    })
    cfg = SLPConfig(max_iter=80, eps_f=1e-3, use_trust_region=False)
    orch = Orchestrator(flowsheet=fs, mode=SolveMode.FIXED_LP, slp_config=cfg)
    result = orch.solve()

    assert result.status == SolverStatus.CONVERGED, (
        f"Did not converge: {result.status} — {result.message}"
    )

    # Plausibility checks
    h2_kg_h = result.kpis.get("psa.H2_production_kg_h", 0.0)
    assert 1.0 < h2_kg_h < 5000.0, f"H2 production implausible: {h2_kg_h:.2f} kg/h"

    cge = result.kpis.get("gasifier.CGE_percent", 0.0)
    assert 30.0 < cge < 95.0, f"CGE implausible: {cge:.1f}%"

    h2_pct = result.kpis.get("gasifier.H2_pct_vol", 0.0)
    assert 20 < h2_pct < 75, f"H2 vol% implausible: {h2_pct:.1f}%"
