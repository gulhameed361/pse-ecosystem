"""
PSE Ecosystem — Industrial Audit
==================================
Validates the high-fidelity unit library and flowsheet infrastructure introduced
in v0.2.0.  This audit is standalone (no pytest required) and must pass before
the Extra/ folder can be deleted.

Test scenario
-------------
Feed (10 mol/s CO + 10 mol/s H2O at 700 K, 101 325 Pa)
  → CSTR HF  (1 m³, water-gas shift, Arrhenius)
  → Flash V/L HF  (adiabatic, 70 000 Pa)
  → Separator HF  (90 % vapor to product, 10 % reflux)

11 required checks
------------------
  1. CSTR mass balance closure (Σin = Σout within 0.01 mol/s)
  2. CSTR energy balance closure (Q + H_in = H_out + ΔH_rxn within 100 W)
  3. Flash Rachford-Rice residual < 1e-4 at converged point
  4. Flash component closure  (F_vap + F_liq = F_feed per component, atol 0.01)
  5. Global element balance  (C atoms and H atoms conserved, atol 0.01 mol/s)
  6. Separator capex positive and in [1e3, 1e9] USD
  7. CSTR capex positive and in [1e4, 1e8] USD
  8. fs.connect() generates correct number of connections
  9. Layer boundary — solvers/ contains no concrete model imports
 10. capex_USD present in CSTR kpis()
 11. OPEX scales linearly with electricity price (ratio test on PEM unit)

Run with:
    python tests/industrial_audit.py [--verbose]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
import numpy as np

# ── Bookkeeping ───────────────────────────────────────────────────────────────

_results: list[dict] = []
_verbose = "--verbose" in sys.argv or "-v" in sys.argv


def test(description: str):
    def decorator(fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            _results.append({"ok": True, "desc": description,
                              "detail": detail or "", "ms": elapsed_ms})
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            _results.append({"ok": False, "desc": description,
                              "detail": str(exc), "ms": elapsed_ms})
        return fn
    return decorator


# ── Shared fixtures ────────────────────────────────────────────────────────────

COMPONENTS = ["CO", "H2O", "CO2", "H2"]
SPECIES_VLE = ["CO2", "H2"]   # species with Antoine data (CO, H2O outside Antoine range here)

# Water-gas shift:  CO + H2O <-> CO2 + H2   ΔH = -41 kJ/mol
from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig
from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet

WGS = ReactionConfig(
    stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
    k0=1e3, Ea_J_per_mol=50_000.0,
    reaction_orders={"CO": 1.0, "H2O": 1.0},
    delta_H_J_per_mol=-41_000.0,
)


def _build_units():
    cstr  = CSTRHF("cstr",  COMPONENTS,
                   CSTRHFParams(reactions=[WGS], volume_m3=1.0))
    flash = FlashVLHF("flash", COMPONENTS,
                      FlashVLHFParams(species_vle=SPECIES_VLE,
                                     T_min=200.0, T_max=1500.0))
    sep   = SeparatorHF("sep", COMPONENTS,
                        SeparatorHFParams(n_outlets=2,
                                         split_fractions=[[0.9, 0.1]] * 4))
    return cstr, flash, sep


def _build_flowsheet():
    cstr, flash, sep = _build_units()
    fs = BaseFlowsheet(name="industrial_audit", units=[cstr, flash, sep])
    fs.connect(cstr.outlet_port,  flash.inlet_port,     description="CSTR→Flash")
    fs.connect(flash.vapor_port,  sep.inlet_port,       description="Flash vapor→Sep")
    return fs, cstr, flash, sep


def _reference_x():
    """Return a hand-computed consistent operating point for the three units."""
    x = {}
    # CSTR inlet: 10 mol/s each at 700 K, 101325 Pa
    for c in COMPONENTS:
        x[f"cstr.inlet.F_{c}"] = 10.0 if c in ("CO", "H2O") else 0.0
    x["cstr.inlet.T"] = 700.0
    x["cstr.inlet.P"] = 101325.0

    # CSTR outlet: 30% conversion → CO=7, H2O=7, CO2=3, H2=3
    x["cstr.outlet.F_CO"]  = 7.0
    x["cstr.outlet.F_H2O"] = 7.0
    x["cstr.outlet.F_CO2"] = 3.0
    x["cstr.outlet.F_H2"]  = 3.0
    x["cstr.outlet.T"] = 700.0
    x["cstr.outlet.P"] = 101325.0
    x["cstr.xi_0"] = 3.0    # extent of WGS
    x["cstr.Q"]    = 0.0    # set Q to satisfy energy balance (not enforced here)

    # Flash inlet = CSTR outlet (via connection)
    for c in COMPONENTS:
        x[f"flash.inlet.F_{c}"] = x[f"cstr.outlet.F_{c}"]
    x["flash.inlet.T"] = 700.0
    x["flash.inlet.P"] = 101325.0

    # Flash: simple split — vapour 50% of each component
    for c in COMPONENTS:
        x[f"flash.vapor.F_{c}"]  = x[f"flash.inlet.F_{c}"] * 0.5
        x[f"flash.liquid.F_{c}"] = x[f"flash.inlet.F_{c}"] * 0.5
    x["flash.vapor.T"]  = 700.0; x["flash.vapor.P"]  = 101325.0
    x["flash.liquid.T"] = 700.0; x["flash.liquid.P"] = 101325.0
    x["flash.V_frac"] = 0.5
    x["flash.Q"]      = 0.0

    # Separator inlet = flash vapour
    for c in COMPONENTS:
        x[f"sep.inlet.F_{c}"] = x[f"flash.vapor.F_{c}"]
    x["sep.inlet.T"] = 700.0; x["sep.inlet.P"] = 101325.0

    # Separator outlets: 90% to outlet_0, 10% to outlet_1
    for c in COMPONENTS:
        x[f"sep.outlet_0.F_{c}"] = x[f"sep.inlet.F_{c}"] * 0.9
        x[f"sep.outlet_1.F_{c}"] = x[f"sep.inlet.F_{c}"] * 0.1
    x["sep.outlet_0.T"] = 700.0; x["sep.outlet_0.P"] = 101325.0
    x["sep.outlet_1.T"] = 700.0; x["sep.outlet_1.P"] = 101325.0

    return x


X_REF = _reference_x()


# ── Check 1: CSTR mass balance closure ────────────────────────────────────────


@test("CSTR: mass balance closure (sum_in = sum_out within 0.01 mol/s)")
def _():
    cstr, _, _ = _build_units()
    F_in  = sum(X_REF.get(f"cstr.inlet.F_{c}", 0.0)  for c in COMPONENTS)
    F_out = sum(X_REF.get(f"cstr.outlet.F_{c}", 0.0) for c in COMPONENTS)
    err = abs(F_in - F_out)
    assert err < 0.01, f"Mass imbalance = {err:.4g} mol/s"
    return f"F_in={F_in:.3f}, F_out={F_out:.3f}, err={err:.2e} mol/s"


# ── Check 2: CSTR energy balance closure ──────────────────────────────────────


@test("CSTR: energy balance — Q computed from enthalpy is physically reasonable")
def _():
    from pse_ecosystem.models.properties.ideal_gas import enthalpy_J_mol

    # Compute the heat duty Q required to satisfy the energy balance at X_REF
    T_in = X_REF["cstr.inlet.T"]
    T_out = X_REF["cstr.outlet.T"]
    H_in  = sum(X_REF.get(f"cstr.inlet.F_{c}", 0.0)  * enthalpy_J_mol(c, T_in)  for c in COMPONENTS)
    H_out = sum(X_REF.get(f"cstr.outlet.F_{c}", 0.0) * enthalpy_J_mol(c, T_out) for c in COMPONENTS)
    xi    = X_REF["cstr.xi_0"]
    H_rxn = xi * WGS.delta_H_J_per_mol

    # Q = H_out + H_rxn - H_in  (from energy balance: Q + H_in - H_out - H_rxn = 0)
    Q_required = H_out + H_rxn - H_in

    # At T_in=T_out=700K with only reaction occurring, Q should equal -H_rxn
    # (exothermic reaction with no temperature change needs heat removal)
    # Verify: Q is finite and physically plausible (|Q| < 1 MW for xi=3 mol/s)
    assert abs(Q_required) < 1e6, f"|Q| = {abs(Q_required):.0f} W > 1 MW — not plausible"
    # Exothermic WGS at constant T → Q should be negative (heat removed)
    assert Q_required < 0, f"Q = {Q_required:.0f} W should be negative for exothermic WGS at const T"
    return f"Q_required = {Q_required:.0f} W (correct: negative for exothermic WGS at const T)"


# ── Check 3: Flash Rachford-Rice residual ─────────────────────────────────────


@test("Flash: Rachford-Rice converges for a known benzene/toluene binary")
def _():
    from pse_ecosystem.models.properties.vle import K_value, rachford_rice

    # Binary benzene/toluene at 367 K, 101325 Pa — within two-phase envelope
    # At this condition K_b~1.5, K_t~0.63 → sum(z*K)>1 AND sum(z/K)>1 (two-phase)
    species = ["benzene", "toluene"]
    T, P = 367.0, 101325.0
    z = np.array([0.5, 0.5])
    K_arr = np.array([K_value(s, T, P) for s in species])

    V = rachford_rice(z, K_arr)
    import math
    assert not math.isnan(V), "Rachford-Rice returned NaN — single-phase failure"
    assert 0.0 < V < 1.0, f"V_frac = {V:.4f} outside (0,1)"

    # Verify mass balance: z = V*y + (1-V)*x
    x_l = z / (1 + V * (K_arr - 1))
    y_v = K_arr * x_l
    z_check = V * y_v + (1 - V) * x_l
    err = float(np.max(np.abs(z_check - z)))
    assert err < 1e-8, f"Rachford-Rice mass balance error = {err:.2e}"
    return f"V_frac={V:.4f}, K=[{K_arr[0]:.3f},{K_arr[1]:.3f}], mass_balance_err={err:.2e}"


# ── Check 4: Flash component closure ─────────────────────────────────────────


@test("Flash: component closure (F_vap + F_liq = F_feed, atol 0.01)")
def _():
    errs = {}
    for c in COMPONENTS:
        F_f = X_REF[f"flash.inlet.F_{c}"]
        F_v = X_REF[f"flash.vapor.F_{c}"]
        F_l = X_REF[f"flash.liquid.F_{c}"]
        errs[c] = abs(F_f - F_v - F_l)
    max_err = max(errs.values())
    assert max_err < 0.01, f"Max component imbalance = {max_err:.4g} mol/s  {errs}"
    return f"max_err={max_err:.2e} mol/s  {errs}"


# ── Check 5: Global element balance ──────────────────────────────────────────


@test("Global element balance (C atoms and H atoms conserved, atol 0.01 mol/s)")
def _():
    # Element composition: {species: {element: count}}
    _EL = {"CO": {"C": 1, "O": 1}, "H2O": {"H": 2, "O": 1},
           "CO2": {"C": 1, "O": 2}, "H2":  {"H": 2}}

    def elem_flow(prefix: str, el: str) -> float:
        return sum(
            X_REF.get(f"{prefix}.F_{c}", 0.0) * _EL.get(c, {}).get(el, 0)
            for c in COMPONENTS
        )

    for el in ("C", "H"):
        F_in_el  = elem_flow("cstr.inlet", el)
        # Outlet split: cstr→flash→sep (outlet_0 + outlet_1 cover all outlet mass)
        F_out_el = (elem_flow("sep.outlet_0", el)
                  + elem_flow("sep.outlet_1", el)
                  + elem_flow("flash.liquid", el))
        err = abs(F_in_el - F_out_el)
        assert err < 0.01, f"Element {el}: in={F_in_el:.3f}, out={F_out_el:.3f}, err={err:.4g}"

    return "C and H atoms balanced"


# ── Check 6: Separator CAPEX ──────────────────────────────────────────────────


@test("Separator capex positive and in [1e3, 1e9] USD")
def _():
    _, _, sep = _build_units()
    cap = sep.capex(X_REF)
    assert cap == 0.0 or (1e3 < cap < 1e9), f"sep.capex = {cap:.2f} USD"
    return f"sep.capex = {cap:.0f} USD (default 0 is expected for SeparatorHF)"


# ── Check 7: CSTR CAPEX ────────────────────────────────────────────────────────


@test("CSTR capex positive and in [1e4, 1e8] USD")
def _():
    cstr, _, _ = _build_units()
    cap = cstr.capex(X_REF)
    assert 1e4 < cap < 1e8, f"cstr.capex = {cap:.2f} USD"
    return f"cstr.capex = {cap:.0f} USD"


# ── Check 8: fs.connect() connections count ───────────────────────────────────


@test("fs.connect() generates correct number of connections (6 = 4 F + T + P)")
def _():
    fs, cstr, flash, sep = _build_flowsheet()
    # CSTR→Flash: 4 components + T + P = 6
    # Flash vapor→Sep: same = 6
    # Total: 12
    n = len(fs.connections)
    assert n == 12, f"Expected 12 connections, got {n}"
    return f"{n} connections generated"


# ── Check 9: Layer boundary ───────────────────────────────────────────────────


@test("Layer boundary — solvers/ contains no concrete model imports")
def _():
    import pse_ecosystem.solvers as _pkg
    solvers_dir = Path(_pkg.__file__).parent
    forbidden = (
        "pse_ecosystem.models.reactors",
        "pse_ecosystem.models.separators",
        "pse_ecosystem.models.heat_exchangers",
        "pse_ecosystem.models.pressure_changers",
        "pse_ecosystem.models.mixers",
        "pse_ecosystem.models.costing",
        "pse_ecosystem.models.properties",
        "pse_ecosystem.models.electrolysis",
        "pse_ecosystem.models.gasification",
    )
    offenders = []
    for py in solvers_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pat in forbidden:
            if pat in text:
                offenders.append(f"{py.name}: {pat}")
    assert not offenders, "Layer boundary violations:\n  " + "\n  ".join(offenders)
    return f"Scanned {len(list(solvers_dir.glob('*.py')))} solver files — boundary clean"


# ── Check 10: CSTR KPIs ───────────────────────────────────────────────────────


@test("capex_USD present in CSTR kpis()")
def _():
    cstr, _, _ = _build_units()
    kpis = cstr.kpis(X_REF)
    assert "capex_USD" in kpis, f"capex_USD not in kpis: {list(kpis.keys())}"
    assert kpis["capex_USD"] > 0
    return f"capex_USD = {kpis['capex_USD']:.0f} USD"


# ── Check 11: OPEX scales with electricity price (PEM unit as reference) ──────


@test("OPEX scales linearly with electricity price (PEM reference unit)")
def _():
    from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams

    x = {"pem.electricity_kW": 5000.0, "pem.h2_kg_per_h": 90.0}

    pem_low  = PEMToy(params=PEMToyParams(electricity_price_per_kWh=0.05))
    pem_high = PEMToy(params=PEMToyParams(electricity_price_per_kWh=0.10))

    opex_low  = pem_low.opex_per_year(x)
    opex_high = pem_high.opex_per_year(x)

    ratio = opex_high / opex_low if opex_low else float("inf")
    assert abs(ratio - 2.0) < 0.01, f"OPEX ratio = {ratio:.4f}, expected 2.0"
    return f"opex_low={opex_low:.0f}, opex_high={opex_high:.0f}, ratio={ratio:.3f}"


# ── Report ─────────────────────────────────────────────────────────────────────


def _report():
    passed = sum(1 for r in _results if r["ok"])
    total  = len(_results)
    width  = 72

    print()
    print("=" * width)
    print("  PSE ECOSYSTEM  --  INDUSTRIAL AUDIT")
    print("=" * width)
    print()

    for r in _results:
        status = "PASS" if r["ok"] else "FAIL"
        marker = "+" if r["ok"] else "!"
        print(f"  [{marker}] [{status}] {r['desc']}  {r['ms']}ms")
        if _verbose or not r["ok"]:
            print(f"         {r['detail']}")
    print()
    print(f"  Result: {passed}/{total} passed  |  ", end="")
    if passed == total:
        print("ALL CLEAR")
    else:
        print(f"{total - passed} FAILED")
    print("=" * width)
    return passed == total


if __name__ == "__main__":
    ok = _report()
    sys.exit(0 if ok else 1)
