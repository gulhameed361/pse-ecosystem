"""Post-solve engineering safety margins.

Computes vessel-wall thickness (ASME Sec VIII Div 1 UG-27), pressure
margins, and flammability warnings for every unit in a flowsheet after
the LP / NLP solve completes. Pure post-solve — never enters the
residual or LP objective.

The :data:`_ASME_VESSEL_UNIT_TYPES` frozenset gates which units get
included in the ASME check; extend it whenever a new vessel-type unit
ships in Layer 3.

Extracted from ``flowsheet_service.py`` in v1.6.1 P.1.6 — see
``docs/PLAN_v1_6_1.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from pse_ecosystem.ui.port_resolver import _primary_inlet, _primary_outlet
# SafetyMarginRow dataclass still lives in ``flowsheet_service`` because
# the LP-objective machinery there constructs it directly. Its definition
# appears in ``flowsheet_service.py`` *before* the safety_bridge re-export
# block, so this import resolves cleanly during the package boot
# sequence — no circular dependency in practice.
from pse_ecosystem.ui.flowsheet_service import SafetyMarginRow  # noqa: E402


# ── Post-solve safety margins ─────────────────────────────────────────────────

# Units considered pressure vessels for ASME sizing (by Python class name).
# Extend this set when adding new vessel-type units to Layer 3.
_ASME_VESSEL_UNIT_TYPES: frozenset = frozenset({
    # Original set (v1.5.x)
    "Compressor",
    "FlashVLHF",
    "CSTRHF",
    "EquilibriumReactor",
    "GibbsReactor",
    "BiomassGasifierHF",
    # Extended (v1.5.3): additional pressure-bearing units
    "PFRHF",
    "TVSAContactor",
    "DistillationHF",
    "ShellTubeHX",
    "Pump",
    "MethanationReactor",
    "FlashSL",
})

# ASME minimum wall thickness below which a WARNING is raised [m]
_ASME_WARNING_THICKNESS_M: float = 0.003  # 3 mm practical minimum

# Pressure margin fraction below which a WARNING is raised
_PRESSURE_WARNING_MARGIN: float = 0.05  # 5 % of design pressure

# Flammability margin below which a WARNING is raised [vol%]
_FLAMM_WARNING_MARGIN_VOL_PCT: float = 2.0


def _extract_vessel_radius(unit) -> Tuple[float, str]:
    """Four-tier cascade for inner vessel radius [m].

    Returns (radius_m, source_label) where source_label is one of
    "params", "volume_derived", or "default".
    """
    import math as _math

    # Tier 1: explicit vessel_radius_m attribute on params dataclass
    params = getattr(unit, "params", None)
    if params is not None:
        r = getattr(params, "vessel_radius_m", None)
        if r is not None and r > 0.0:
            return float(r), "params"

    # Tier 2: explicit instance attribute
    r = getattr(unit, "vessel_radius_m", None)
    if r is not None and r > 0.0:
        return float(r), "params"

    # Tier 3: derive from volume_m3 (cylindrical vessel, L/D = 4)
    volume_m3 = None
    if params is not None:
        volume_m3 = getattr(params, "volume_m3", None)
    if volume_m3 is None:
        volume_m3 = getattr(unit, "volume_m3", None)
    if volume_m3 is not None and volume_m3 > 0.0:
        # V = π r² L with L/D = 4 → L = 8r → V = 8π r³ → r = (V / (8π))^(1/3)
        r = (float(volume_m3) / (8.0 * _math.pi)) ** (1.0 / 3.0)
        return r, "volume_derived"

    # Tier 4: conservative default
    return 0.5, "default"


def compute_safety_margins(
    flowsheet,
    solution_x: Dict[str, float],
    design_pressure_factor: float = 1.1,
    allowable_stress_Pa: float = 138_000_000.0,
    joint_efficiency: float = 1.0,
) -> List[SafetyMarginRow]:
    """Compute ASME and flammability safety margins for pressure-containing units.

    POST-SOLVE ONLY.  This function must never be called during LP/NLP
    optimisation.  It is called by the UI after a ``SolveResult`` is returned.

    Parameters
    ----------
    flowsheet :
        Assembled ``BaseFlowsheet`` (same object passed to the Orchestrator).
    solution_x :
        ``SolveResult.x`` — the converged solution dict.
    design_pressure_factor :
        P_design = P_operating × factor (default 1.1 = 10 % engineering margin).
    allowable_stress_Pa :
        ASME allowable stress for shell material [Pa].
    joint_efficiency :
        ASME weld joint efficiency [-].

    Returns
    -------
    List[SafetyMarginRow]
        One or more rows per pressure-containing unit; empty list if none match.

    Layer boundary
    --------------
    Imports ``safety_checks`` from ``models/safety/`` (Layer 3 → Layer 1 bridge,
    permitted only from this module per the single-gateway rule).
    """
    from pse_ecosystem.models.safety.safety_checks import (
        asme_minimum_wall_thickness,
        flammability_margins,
        operating_pressure_margin,
    )

    rows: List[SafetyMarginRow] = []

    for unit in flowsheet.units:
        unit_type = type(unit).__name__
        uid = unit.unit_id

        if unit_type not in _ASME_VESSEL_UNIT_TYPES:
            continue

        # ── Extract operating pressure ────────────────────────────────────────
        # Try outlet pressure first (post-compression), then inlet, then fallback.
        P_operating: Optional[float] = None
        for p_key in (f"{uid}.outlet.P", f"{uid}.inlet.P"):
            val = solution_x.get(p_key)
            if val is not None and val > 0.0:
                P_operating = float(val)
                break

        if P_operating is None:
            # Search solution_x for any pressure variable belonging to this unit
            p_vals = [
                v for k, v in solution_x.items()
                if k.startswith(uid + ".") and k.endswith(".P") and v > 0.0
            ]
            P_operating = max(p_vals) if p_vals else None

        if P_operating is None:
            continue  # no pressure variable found; skip unit

        P_design = P_operating * design_pressure_factor

        # ── ASME wall thickness ───────────────────────────────────────────────
        radius_m, radius_source = _extract_vessel_radius(unit)
        try:
            t_min = asme_minimum_wall_thickness(
                P_operating, radius_m, allowable_stress_Pa, joint_efficiency
            )
            if t_min < _ASME_WARNING_THICKNESS_M:
                status = "WARNING"
            else:
                status = "OK"
            rows.append(SafetyMarginRow(
                unit_id=uid,
                unit_type=unit_type,
                check_type="ASME_wall_thickness",
                value=t_min,
                limit=_ASME_WARNING_THICKNESS_M,
                status=status,
                detail=(
                    f"t_min = {t_min*1000:.2f} mm at P = {P_operating/1e5:.1f} bar, "
                    f"R = {radius_m*1000:.0f} mm ({radius_source})"
                ),
                radius_source=radius_source,
            ))
        except ValueError:
            rows.append(SafetyMarginRow(
                unit_id=uid,
                unit_type=unit_type,
                check_type="ASME_wall_thickness",
                value=float("nan"),
                limit=_ASME_WARNING_THICKNESS_M,
                status="VIOLATION",
                detail=f"ASME UG-27(c)(1) not applicable: P = {P_operating/1e5:.1f} bar "
                       f"exceeds formula validity (P/(S·E) ≥ 0.385). Use Div. 2 rules.",
                radius_source=radius_source,
            ))

        # ── Operating pressure margin ─────────────────────────────────────────
        try:
            margin = operating_pressure_margin(P_operating, P_design)
            # By construction P_design = P_operating * factor, so margin = 1 - 1/factor
            # This will always be (factor - 1)/factor ≈ 0.091 for factor=1.1.
            # The check is meaningful when the user supplies a custom P_design_Pa override.
            if margin < _PRESSURE_WARNING_MARGIN:
                p_status = "WARNING"
            elif margin < 0.0:
                p_status = "VIOLATION"
            else:
                p_status = "OK"
            rows.append(SafetyMarginRow(
                unit_id=uid,
                unit_type=unit_type,
                check_type="pressure_margin",
                value=margin,
                limit=_PRESSURE_WARNING_MARGIN,
                status=p_status,
                detail=(
                    f"P_op = {P_operating/1e5:.2f} bar, "
                    f"P_design = {P_design/1e5:.2f} bar, "
                    f"margin = {margin*100:.1f} %"
                ),
            ))
        except ValueError:
            pass

        # ── Flammability check ────────────────────────────────────────────────
        components = getattr(unit, "components", None) or getattr(
            getattr(unit, "params", None), "components", None
        )
        if not components:
            continue

        # Build a rough composition dict from outlet molar flows
        flow_vars = {
            sp: solution_x.get(f"{uid}.outlet.F_{sp}", 0.0)
            for sp in components
        }
        total_flow = sum(flow_vars.values())
        if total_flow <= 0.0:
            # Try inlet
            flow_vars = {
                sp: solution_x.get(f"{uid}.inlet.F_{sp}", 0.0)
                for sp in components
            }
            total_flow = sum(flow_vars.values())

        if total_flow <= 0.0:
            continue

        comp_fracs = {sp: f / total_flow for sp, f in flow_vars.items()}

        try:
            fm = flammability_margins(comp_fracs)
        except ValueError:
            continue  # no flammable species in this unit's component set

        margin_to_lfl = fm["margin_to_LFL_vol_pct"]
        if margin_to_lfl < 0.0:
            f_status = "VIOLATION"
        elif margin_to_lfl < _FLAMM_WARNING_MARGIN_VOL_PCT:
            f_status = "WARNING"
        else:
            f_status = "OK"

        rows.append(SafetyMarginRow(
            unit_id=uid,
            unit_type=unit_type,
            check_type="flammability",
            value=margin_to_lfl,
            limit=_FLAMM_WARNING_MARGIN_VOL_PCT,
            status=f_status,
            detail=(
                f"LFL_mix = {fm['LFL_vol_pct']:.1f} vol%, "
                f"UFL_mix = {fm['UFL_vol_pct']:.1f} vol%, "
                f"flammable content = {fm['mixture_flammable_fraction']*100:.1f} vol% "
                f"({', '.join(fm['flammable_species'])})"
            ),
        ))

    return rows
