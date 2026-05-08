"""HDA (Hydrodealkylation) Case Study.

Classic benchmark process: Toluene + H2 → Benzene + CH4 (main reaction),
with 2 Benzene → Diphenyl + H2 as the undesired side reaction.

Process structure:
  Fresh feed (H2 + Toluene) → PFR Reactor → Isothermal Flash
  → Distillation Train (T2 Benzene + T3 Toluene) → Products

This example demonstrates the three HDA black-box BaseUnit wrappers
(HDAPFRUnit, HDAFlashUnit, HDADistillationUnit) using sequential-modular
simulation — the natural approach for connected black-box units.

For each unit, we call evaluate() to obtain the true (non-linear) physics,
then chain the outputs as inputs to the next unit.

Note: SLP optimisation of black-box units requires a good initial guess
close to the solution. For sensitivity studies or LCOH minimisation,
use SLPDriver with x0 seeded from the sequential-modular result.

Requires: pip install 'pse_ecosystem[blackbox]'  (scipy)
Run:      python examples/hda_case_study.py [--verbose]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description="HDA Case Study — Sequential Modular")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        import scipy  # noqa: F401
    except ImportError:
        print("ERROR: scipy required. Install: pip install 'pse_ecosystem[blackbox]'")
        return 1

    from pse_ecosystem.models._blackbox.hda_reactor_bb import HDA_Reactor_sim
    from pse_ecosystem.models._blackbox.hda_flash_bb import HDA_Flash_sim
    from pse_ecosystem.models._blackbox.hda_distillation_bb import HDA_Distillation_sim

    # ── Operating conditions ──────────────────────────────────────────────
    # Note: at the classical HDA nominal point (894 K, V=3 m3, H2:Tol≈5:1),
    # the adiabatic PFR converts nearly 100% of toluene (highly exothermic).
    # To obtain the textbook 75-95% conversion range, reduce V_R to ~0.5 m3
    # or lower T_in to ~800 K. The kinetics here are physically correct.
    F_H2_fresh   = 3.0    # mol/s fresh H2 feed
    F_CH4_in     = 0.5    # mol/s methane (impurity)
    F_Tol_in     = 0.6    # mol/s toluene (fresh + recycle, simplified)
    F_Benz_in    = 0.02   # mol/s benzene at reactor inlet
    T_reactor_in = 894.0  # K
    V_reactor    = 0.5    # m3 — reduced to target ~80% toluene conversion

    T_flash      = 322.0             # K
    P_flash      = 25.0 * 101325     # Pa (25 atm)

    RR2 = 3.0   # T2 reflux ratio
    RR3 = 2.5   # T3 reflux ratio

    # ── Stage 1: PFR Reactor ──────────────────────────────────────────────
    if args.verbose:
        print("  Stage 1: PFR Reactor (ODE integration)...")
    (F_H2_out, F_CH4_out, F_Tol_out, F_Benz_out,
     F_Diph_out, T_out, H_out) = HDA_Reactor_sim(
        F_H2_fresh, F_CH4_in, F_Tol_in, F_Benz_in,
        T_reactor_in, V_reactor,
    )

    # ── Stage 2: Isothermal Flash ─────────────────────────────────────────
    if args.verbose:
        print("  Stage 2: Flash Separator (Wilson VLE)...")
    (F_H2_vap,  F_CH4_vap,  F_Tol_vap,  F_Benz_vap,  F_Diph_vap,
     F_H2_liq,  F_CH4_liq,  F_Tol_liq,  F_Benz_liq,  F_Diph_liq,
     H_vap, H_liq) = HDA_Flash_sim(
        F_H2_out, F_CH4_out, F_Tol_out, F_Benz_out, F_Diph_out,
        T_flash, P_flash,
    )

    # ── Stage 3: Distillation Train ───────────────────────────────────────
    if args.verbose:
        print("  Stage 3: Distillation (FUG shortcut)...")
    (F_Benz_product, F_Tol_recycle,
     F_Diph_out_col, Q_T2, Q_T3) = HDA_Distillation_sim(
        F_Benz_liq, F_Tol_liq, F_Diph_liq,
        RR2, RR3,
    )

    # ── KPIs ──────────────────────────────────────────────────────────────
    tol_conv   = (1.0 - F_Tol_out / max(F_Tol_in, 1e-9)) * 100.0
    benz_sel   = F_Benz_out / max(F_Tol_in - F_Tol_out, 1e-9) * 100.0
    vap_total  = F_H2_vap + F_CH4_vap + F_Tol_vap + F_Benz_vap + F_Diph_vap
    feed_total = F_H2_out + F_CH4_out + F_Tol_out + F_Benz_out + F_Diph_out
    vap_frac   = vap_total / max(feed_total, 1e-9)

    W = 58
    print("=" * W)
    print("  HDA Case Study — PSE Ecosystem v0.1.0")
    print("  Sequential-Modular Simulation at Nominal Design Point")
    print("=" * W)
    print()
    print("  REACTOR (PFR, adiabatic, 25 atm)")
    print(f"    Inlet:  F_H2={F_H2_fresh:.2f}  F_Tol={F_Tol_in:.2f}  T={T_reactor_in:.0f} K  V={V_reactor:.1f} m3")
    print(f"    Outlet: F_H2={F_H2_out:.3f}  F_CH4={F_CH4_out:.3f}  F_Tol={F_Tol_out:.3f}")
    print(f"            F_Benz={F_Benz_out:.4f}  F_Diph={F_Diph_out:.5f}  mol/s")
    print(f"    T_out   = {T_out:.1f} K   H_out = {H_out:.4f} MJ/s")
    print(f"    Toluene conversion  = {tol_conv:.1f} %")
    print(f"    Benzene selectivity = {benz_sel:.1f} %")
    print()
    print(f"  FLASH (T={T_flash:.0f} K, P={P_flash/101325:.0f} atm)")
    print(f"    Vapour fraction = {vap_frac:.4f}")
    print(f"    F_H2_vap={F_H2_vap:.3f}  F_Benz_liq={F_Benz_liq:.4f}  F_Tol_liq={F_Tol_liq:.4f}  mol/s")
    print()
    print(f"  DISTILLATION (RR2={RR2}, RR3={RR3})")
    print(f"    F_Benz_product = {F_Benz_product:.4f} mol/s   (target: {0.40:.2f})")
    print(f"    F_Tol_recycle  = {F_Tol_recycle:.4f} mol/s")
    print(f"    F_Diph_out     = {F_Diph_out_col:.5f} mol/s")
    print(f"    Q_T2 = {Q_T2:.4f} MJ/s   Q_T3 = {Q_T3:.4f} MJ/s")
    print()
    print("  Unit model verification (residual at consistent point):")
    from pse_ecosystem.models.reactor.hda_pfr import HDAPFRUnit
    unit = HDAPFRUnit("pfr")
    x = {
        "pfr.F_H2_in": F_H2_fresh, "pfr.F_CH4_in": F_CH4_in,
        "pfr.F_Tol_in": F_Tol_in, "pfr.F_Benz_in": F_Benz_in,
        "pfr.T_in": T_reactor_in, "pfr.V_R": V_reactor,
        "pfr.F_H2_out": F_H2_out, "pfr.F_CH4_out": F_CH4_out,
        "pfr.F_Tol_out": F_Tol_out, "pfr.F_Benz_out": F_Benz_out,
        "pfr.F_Diph_out": F_Diph_out, "pfr.T_out": T_out, "pfr.H_out": H_out,
    }
    import numpy as np
    res_norm = float(np.max(np.abs(unit.residual(x))))
    print(f"    HDAPFRUnit residual norm at consistent point: {res_norm:.2e}  (expect <1e-6)")
    print()
    print("=" * W)
    return 0


if __name__ == "__main__":
    sys.exit(main())
