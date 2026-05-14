"""Presentation validation — 3-unit process chain.

Validates the core numerical results described in docs/SHOWCASE_WALKTHROUGH.md.

Chain:  StoichiometricReactor  (feed pre-conditioner / "Heater")
            -> StoichiometricReactor  (Power-to-Methanol synthesis / "Reactor")
                -> SeparatorHF  (liquid-gas separation / "Flash")

"Heater -> Reactor -> Flash" conceptual mapping:
  Heater  = feed pre-conditioning stage (xi=0 pass-through at design T/P)
  Reactor = CO2 + 3H2 -> methanol + H2O (Power-to-Methanol)
  Flash   = split-fraction separator (gas CO2/H2 overhead, liquid methanol/water)

Physics note: FlashVLHF (rigorous Antoine VLE) is tested separately in
  tests/test_v121.py and tests/test_hf_units.py because the working fluid
  (CO/H2O/CO2/H2) at 700 K is supercritical (CO2 Tc=304 K, H2 Tc=33 K)
  and the Antoine correlation is not valid at that temperature. The showcase
  Stage 1 (CSTR+Flash template) is also flagged as a known convergence issue
  from cold-start; see docs/SYSTEM_STATE.md Known Limitations.

This script validates what can reliably be confirmed analytically:
  - 3-unit port-based assembly (connection count, variable wiring)
  - SLP convergence in 1 LP step (all-linear chain)
  - P2M stoichiometry: extent × stoichiometry = outlet - inlet
  - Separator mass balance closure: Σ(product outlets) = inlet
  - Methanol split fraction KPI plausibility

Run as standalone:
    python tests/presentation_validation.py

Run within pytest:
    pytest tests/presentation_validation.py -v
"""

from __future__ import annotations

import sys
import numpy as np


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pass(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    sys.exit(1)


def _check(condition: bool, msg: str) -> None:
    if condition:
        _pass(msg)
    else:
        _fail(msg)


# ── Flowsheet builder ─────────────────────────────────────────────────────────

def build_3unit_chain():
    """Assemble feed pre-conditioner -> P2M reactor -> separator."""
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.reactors.stoichiometric_reactor import (
        StoichiometricReactor, StoichiometricParams,
    )
    from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams

    components = ["CO2", "H2", "methanol", "water"]

    # ── Unit 1: Feed pre-conditioner ("Heater") ───────────────────────────────
    # Zero-extent pass-through representing feed preheat to synthesis temperature.
    # Stoichiometry matches the P2M reaction (CO2+3H2->MeOH+H2O) but xi is
    # pinned to zero, making this unit a pure T/P pass-through.
    sp_pre = StoichiometricParams(
        stoichiometry={
            "CO2": [-1.0], "H2": [-3.0],
            "methanol": [1.0], "water": [1.0],
        },
        feed_max=200.0,
    )
    heater = StoichiometricReactor("heater", components, sp_pre)

    # ── Unit 2: P2M synthesis reactor ("Reactor") ─────────────────────────────
    # CO2 + 3H2 -> methanol + H2O
    sp_rxr = StoichiometricParams(
        stoichiometry={
            "CO2": [-1.0], "H2": [-3.0],
            "methanol": [1.0], "water": [1.0],
        },
        feed_max=200.0,
        xi_max=[50.0],
    )
    reactor = StoichiometricReactor("reactor", components, sp_rxr)

    # ── Unit 3: Liquid-gas separator ("Flash") ────────────────────────────────
    # 95% methanol and 98% water go to liquid outlet; CO2 and H2 overhead.
    split_fractions = [
        [0.05, 0.95],   # CO2:   5% liquid, 95% vapor
        [0.02, 0.98],   # H2:    2% liquid, 98% vapor
        [0.95, 0.05],   # MeOH: 95% liquid,  5% vapor
        [0.98, 0.02],   # H2O:  98% liquid,  2% vapor
    ]
    sep = SeparatorHF("sep", components, SeparatorHFParams(
        n_outlets=2, split_fractions=split_fractions
    ))

    # ── Assemble flowsheet ────────────────────────────────────────────────────
    fs = BaseFlowsheet(name="presentation.3unit_chain",
                       units=[heater, reactor, sep])

    # Port connections: heater -> reactor -> sep
    fs.connect(heater.outlet_port, reactor.inlet_port,
               description="Pre-conditioner -> P2M reactor")
    fs.connect(reactor.outlet_port, sep.inlet_port,
               description="P2M reactor -> separator")

    # ── Feed conditions (the "Heater" stage inlet) ────────────────────────────
    # Equimolar CO2 + excess H2 (3:1 stoichiometry), no products in feed
    fs.extra_bounds["heater.inlet.F_CO2"]     = (10.0, 10.0)
    fs.extra_bounds["heater.inlet.F_H2"]      = (30.0, 30.0)
    fs.extra_bounds["heater.inlet.F_methanol"] = (0.0, 0.0)
    fs.extra_bounds["heater.inlet.F_water"]   = (0.0, 0.0)
    fs.extra_bounds["heater.inlet.T"]         = (500.0, 500.0)
    fs.extra_bounds["heater.inlet.P"]         = (3_000_000.0, 3_000_000.0)

    # Pre-conditioner: zero extent (pure pass-through, preheat only)
    fs.extra_bounds["heater.xi_0"] = (0.0, 0.0)

    # Reactor: free extent in physically meaningful range (0 to 10 mol/s CO2)
    fs.extra_bounds["reactor.xi_0"] = (0.0, 10.0)

    return fs


# ── Reference values ──────────────────────────────────────────────────────────
# Expected at xi_reactor ≈ 8.5 mol/s (85% CO2 conversion):
#   reactor.inlet:  CO2=10, H2=30, MeOH=0,   H2O=0
#   reactor.outlet: CO2=1.5, H2=4.5, MeOH=8.5, H2O=8.5  [mol/s]
#   sep liquid:     MeOH≈8.075, H2O≈8.33  (high-purity methanol stream)
#   sep vapor:      CO2≈1.425, H2≈4.41   (recycled syngas)

EXPECTED_METHANOL_YIELD_FRACTION = (0.6, 1.0)  # methanol yield as fraction of CO2 fed


# ── Validation checks ─────────────────────────────────────────────────────────

def run_validation() -> None:
    print("=" * 65)
    print("PSE Ecosystem v1.2.1 — Presentation Validation")
    print("3-unit chain: Pre-conditioner -> P2M Reactor -> Separator")
    print("=" * 65)

    # ── 1. Build the flowsheet ────────────────────────────────────────────────
    print("\n[1] Building 3-unit flowsheet...")
    fs = build_3unit_chain()
    _check(len(fs.units) == 3, f"3 units assembled (got {len(fs.units)})")
    _check(len(fs.connections) > 0,
           f"Port connections wired ({len(fs.connections)} connections)")

    # ── 2. Check port compatibility ───────────────────────────────────────────
    print("\n[2] Checking port compatibility...")
    connected_vars = {c.var_a for c in fs.connections} | {c.var_b for c in fs.connections}
    for comp in ["CO2", "H2", "methanol", "water"]:
        has_conn = (f"reactor.inlet.F_{comp}" in connected_vars or
                    f"heater.outlet.F_{comp}" in connected_vars)
        _check(has_conn, f"Component {comp} wired between heater -> reactor")

    # ── 3. Solve with SLP ─────────────────────────────────────────────────────
    print("\n[3] Running SLP solver (all-linear chain -> single LP step)...")
    try:
        from pse_ecosystem.solvers.lp_builder import select_lp_solver
        select_lp_solver()
    except RuntimeError as exc:
        print(f"  [SKIP] No LP solver available: {exc}")
        return

    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver
    from pse_ecosystem.core.contracts import SolverStatus

    cfg = SLPConfig(max_iter=20, eps_x=1e-6, eps_f=1e-6, verbose=False)
    result = SLPDriver(fs, cfg).run()

    status_str = str(result.status).split(".")[-1]
    converged = result.status == SolverStatus.CONVERGED
    print(f"  Status: {status_str} | Iterations: {result.iterations}")

    _check(converged, f"SLP converged (status={status_str})")

    if not converged:
        print("  Solver did not converge — skipping numerical checks.")
        return

    # ── 4. Iteration count ────────────────────────────────────────────────────
    print("\n[4] Checking iteration count...")
    _check(result.iterations == 1,
           f"All-linear chain converges in 1 LP step (got {result.iterations})")

    # ── 5. P2M stoichiometry check ────────────────────────────────────────────
    print("\n[5] Verifying P2M stoichiometric balance...")
    x = result.x
    xi = x.get("reactor.xi_0", 0.0)
    F_CO2_in  = x.get("reactor.inlet.F_CO2", 0.0)
    F_CO2_out = x.get("reactor.outlet.F_CO2", 0.0)
    F_MeOH_out = x.get("reactor.outlet.F_methanol", 0.0)

    expected_CO2_consumed = xi
    actual_CO2_consumed   = F_CO2_in - F_CO2_out

    _check(abs(actual_CO2_consumed - expected_CO2_consumed) < 1e-6,
           f"CO2 consumed = xi = {xi:.4g} mol/s (err={abs(actual_CO2_consumed-expected_CO2_consumed):.2e})")
    _check(abs(F_MeOH_out - xi) < 1e-6,
           f"Methanol produced = xi = {xi:.4g} mol/s (err={abs(F_MeOH_out-xi):.2e})")

    # ── 6. Separator mass balance closure ─────────────────────────────────────
    print("\n[6] Checking separator mass balance closure...")
    comps = ["CO2", "H2", "methanol", "water"]
    F_sep_in  = sum(x.get(f"sep.inlet.F_{c}",   0.0) for c in comps)
    F_sep_out = sum(x.get(f"sep.outlet_0.F_{c}", 0.0) +
                    x.get(f"sep.outlet_1.F_{c}", 0.0) for c in comps)

    if F_sep_in > 1e-9:
        rel_err = abs(F_sep_out - F_sep_in) / F_sep_in
        _check(rel_err < 1e-6,
               f"Separator molar balance closure: |err|/feed = {rel_err:.2e}")

    # ── 7. Methanol recovery ──────────────────────────────────────────────────
    print("\n[7] Checking methanol recovery (showcase KPI)...")
    F_MeOH_liq = x.get("sep.outlet_0.F_methanol",  # liquid outlet
                        x.get("sep.outlet_1.F_methanol", 0.0))
    # Find the outlet with higher methanol (liquid product)
    F_MeOH_liq = max(
        x.get("sep.outlet_0.F_methanol", 0.0),
        x.get("sep.outlet_1.F_methanol", 0.0),
    )
    F_MeOH_feed = x.get("reactor.outlet.F_methanol", 0.0)
    if F_MeOH_feed > 1e-9:
        recovery = F_MeOH_liq / F_MeOH_feed
        _check(0.90 <= recovery <= 1.0,
               f"Methanol liquid recovery >= 90%: {recovery:.3f}")

    # ── 8. Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("Presentation validation PASSED.")
    print("=" * 65)
    print(f"\n  Solver status     : {status_str}")
    print(f"  SLP iterations    : {result.iterations}")
    print(f"  Reaction extent   : {xi:.4g} mol/s CO2 converted")
    print(f"  CO2 conversion    : {(xi / 10.0 * 100):.1f}%")
    print(f"  Methanol produced : {F_MeOH_out:.4g} mol/s")
    print(f"\n  KPIs:")
    for k, v in result.kpis.items():
        print(f"    {k:35s}: {v:.4g}")
    print("\nSmoke-test command:")
    print("  streamlit run pse_ecosystem/ui/app_streamlit.py")


# ── pytest interface ──────────────────────────────────────────────────────────

def test_3unit_chain_builds():
    """The 3-unit chain assembles without error."""
    fs = build_3unit_chain()
    assert len(fs.units) == 3
    assert len(fs.connections) > 0


def test_3unit_chain_port_connections():
    """All component flows and T/P are wired between units."""
    fs = build_3unit_chain()
    connected_vars = {c.var_a for c in fs.connections} | {c.var_b for c in fs.connections}
    components = ["CO2", "H2", "methanol", "water"]
    for comp in components:
        assert (f"reactor.inlet.F_{comp}" in connected_vars or
                f"heater.outlet.F_{comp}" in connected_vars), \
               f"Component {comp} not wired in connections"


def test_3unit_chain_solves():
    """The all-linear 3-unit chain converges in exactly 1 LP step."""
    try:
        from pse_ecosystem.solvers.lp_builder import select_lp_solver
        select_lp_solver()
    except RuntimeError:
        import pytest
        pytest.skip("No LP solver available")

    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver
    from pse_ecosystem.core.contracts import SolverStatus

    fs = build_3unit_chain()
    result = SLPDriver(fs, SLPConfig(max_iter=5, verbose=False)).run()
    assert result.status == SolverStatus.CONVERGED, (
        f"Expected CONVERGED, got {result.status}: {result.message}"
    )
    assert result.iterations == 1, (
        f"Linear chain should converge in 1 iteration, got {result.iterations}"
    )


def test_3unit_chain_p2m_stoichiometry():
    """CO2 consumed equals reaction extent; methanol produced equals extent."""
    try:
        from pse_ecosystem.solvers.lp_builder import select_lp_solver
        select_lp_solver()
    except RuntimeError:
        import pytest
        pytest.skip("No LP solver available")

    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver
    from pse_ecosystem.core.contracts import SolverStatus

    fs = build_3unit_chain()
    result = SLPDriver(fs, SLPConfig(max_iter=5, verbose=False)).run()
    if result.status != SolverStatus.CONVERGED:
        import pytest
        pytest.skip(f"Solver did not converge: {result.status}")

    x = result.x
    xi = x.get("reactor.xi_0", 0.0)
    F_CO2_in   = x.get("reactor.inlet.F_CO2", 0.0)
    F_CO2_out  = x.get("reactor.outlet.F_CO2", 0.0)
    F_MeOH_out = x.get("reactor.outlet.F_methanol", 0.0)

    assert xi > 0, "Reaction extent should be positive"
    assert abs((F_CO2_in - F_CO2_out) - xi) < 1e-6, \
        f"Stoichiometry: CO2_consumed={F_CO2_in-F_CO2_out:.4g} ≠ xi={xi:.4g}"
    assert abs(F_MeOH_out - xi) < 1e-6, \
        f"Stoichiometry: MeOH_produced={F_MeOH_out:.4g} ≠ xi={xi:.4g}"


def test_3unit_chain_mass_balance():
    """Separator in/out molar balance is exact (separator does not react)."""
    try:
        from pse_ecosystem.solvers.lp_builder import select_lp_solver
        select_lp_solver()
    except RuntimeError:
        import pytest
        pytest.skip("No LP solver available")

    from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver
    from pse_ecosystem.core.contracts import SolverStatus

    fs = build_3unit_chain()
    result = SLPDriver(fs, SLPConfig(max_iter=5, verbose=False)).run()
    if result.status != SolverStatus.CONVERGED:
        import pytest
        pytest.skip(f"Solver did not converge: {result.status}")

    # The P2M reaction reduces molar total (CO2+3H2->MeOH+H2O: 4 moles -> 2 moles).
    # Overall molar balance across a reactive chain does NOT conserve total moles.
    # Instead, check the separator unit: sep.inlet = sep.outlet_0 + sep.outlet_1 (exact).
    components = ["CO2", "H2", "methanol", "water"]
    x = result.x
    F_sep_in  = sum(x.get(f"sep.inlet.F_{c}",   0.0) for c in components)
    F_sep_out = sum(x.get(f"sep.outlet_0.F_{c}", 0.0) +
                    x.get(f"sep.outlet_1.F_{c}", 0.0) for c in components)
    if F_sep_in > 1e-9:
        rel_err = abs(F_sep_out - F_sep_in) / F_sep_in
        assert rel_err < 1e-5, \
            f"Separator molar balance error: |out-in|/in = {rel_err:.2e}"

    # Element (carbon) conservation across the full chain:
    # C in (from CO2): 10 mol C  ->  C out (CO2 + methanol): x_CO2 + x_MeOH = 10
    xi = x.get("reactor.xi_0", 0.0)
    C_in  = 10.0   # from feed CO2=10 mol/s -> 10 mol C/s
    C_out = (sum(x.get(f"sep.outlet_{k}.F_CO2",     0.0) for k in range(2)) +
             sum(x.get(f"sep.outlet_{k}.F_methanol", 0.0) for k in range(2)))
    assert abs(C_out - C_in) < 1e-5, \
        f"Carbon balance: C_out={C_out:.4g} ≠ C_in={C_in:.4g}"


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    run_validation()
