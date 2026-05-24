"""API 520 Part I + API 521 pressure-relief sizing.

This module sizes the orifice area of a pressure-relief valve (PSV) for the
three industrially-relevant relieving scenarios from API 521 §4–§5:

* **Fire case** — heat input from an external pool fire heats the wetted
  vessel surface; the relieving load is the vapour generated from the
  liquid contents.
* **Blocked-outlet gas** — upstream supply continues at full capacity;
  the relieving load equals the maximum inflow.
* **Thermal expansion (liquid)** — slow liquid heating with both outlets
  blocked; small relieving rate, small orifice.

Orifice-area equations come from API 520 Part I (8th ed., 2014):
* Vapor at choked flow:   A = W / (C · K_d · K_b · K_c · P1) · √(T · Z / M)
* Liquid:                 A = W / (K_d · K_w · K_v · K_c · √(2 · ρ · (P1 − P2)))

The default discharge coefficient ``K_d = 0.975`` matches a spring-operated
PSV in vapor service (API 520 Table 6). All inputs are SI units; outputs
are square metres. ASME Sec VIII set / accumulation rules are applied to
recommend the set-pressure and full-lift pressure given the vessel design
pressure.

References
----------
* API Standard 520, Part I — Sizing, Selection, and Installation of
  Pressure-Relieving Devices (8th ed., 2014).
* API Standard 521 — Pressure-Relieving and Depressuring Systems
  (6th ed., 2014).
* ASME Boiler & Pressure Vessel Code, Section VIII, Division 1, UG-125.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

_R_GAS = 8.314462  # J/mol/K


class ReliefScenario(str, Enum):
    """Three primary API 521 relieving scenarios."""

    FIRE = "fire"
    BLOCKED_OUTLET_GAS = "blocked_outlet_gas"
    THERMAL_EXPANSION = "thermal_expansion"


# ─────────────────────────────────────────────────────────────────────────────
# Coefficient helpers
# ─────────────────────────────────────────────────────────────────────────────


def C_coefficient(gamma: float) -> float:
    """API 520 Eq.3.4 coefficient ``C`` for the vapor-orifice formula.

    C = √(γ · (2/(γ+1))^((γ+1)/(γ-1)))

    Tabulated values for common gases:
    * γ = 1.40 (diatomic, air / N2): C = 0.677
    * γ = 1.30 (typical refrigerants): C = 0.660
    * γ = 1.20 (heavy hydrocarbons):  C = 0.643
    """
    exp = (gamma + 1.0) / (gamma - 1.0)
    return math.sqrt(gamma * (2.0 / (gamma + 1.0)) ** exp)


def critical_pressure_ratio(gamma: float) -> float:
    """Critical pressure ratio P_crit / P1 = (2/(γ+1))^(γ/(γ-1))."""
    return (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))


def is_choked(P1_Pa: float, P_back_Pa: float, gamma: float) -> bool:
    """True if the relief is in critical (choked) flow, i.e. P_back/P1 <
    critical_pressure_ratio. Most PSVs vent to atmosphere → P_back/P1 << 1."""
    return (P_back_Pa / max(P1_Pa, 1e-9)) < critical_pressure_ratio(gamma)


# ─────────────────────────────────────────────────────────────────────────────
# Orifice-area calculations (API 520 Part I)
# ─────────────────────────────────────────────────────────────────────────────


def orifice_area_vapor(
    W_kg_per_s: float,
    T_K: float,
    P1_Pa: float,
    MW_kg_per_mol: float,
    gamma: float,
    Z: float = 1.0,
    K_d: float = 0.975,
    K_b: float = 1.0,
    K_c: float = 1.0,
) -> float:
    """API 520 Eq.3.4 — orifice area [m²] for vapor at choked flow.

        A = W / (C · K_d · K_b · K_c · P1) · √(T · Z / M)

    Parameters
    ----------
    W_kg_per_s : Relieving mass flow rate [kg/s].
    T_K        : Relieving temperature [K].
    P1_Pa      : Relieving pressure (absolute) [Pa]. Typically 1.1 × P_set
                 (10 % accumulation for a single PSV per ASME UG-125).
    MW_kg_per_mol : Mean molecular weight [kg/mol].
    gamma      : Specific-heat ratio Cp/Cv at relieving conditions.
    Z          : Compressibility factor at (T, P1). 1.0 for ideal gas.
    K_d        : Discharge coefficient. 0.975 spring-op PSV, 0.62 rupture
                 disc. API 520 Table 6.
    K_b        : Back-pressure correction (0.6–1.0; 1.0 for atmospheric
                 discharge). API 520 Fig.A.6.
    K_c        : Combination correction (0.9 if a rupture disc precedes
                 the PSV; else 1.0). API 520 Table 8.
    """
    C = C_coefficient(gamma)
    denom = C * K_d * K_b * K_c * P1_Pa
    if denom <= 0:
        raise ValueError("Invalid PSV parameters — denominator non-positive")
    return W_kg_per_s / denom * math.sqrt(T_K * Z / max(MW_kg_per_mol, 1e-12))


def orifice_area_liquid(
    W_kg_per_s: float,
    rho_kg_per_m3: float,
    P1_Pa: float,
    P_back_Pa: float,
    K_d: float = 0.65,
    K_w: float = 1.0,
    K_v: float = 1.0,
    K_c: float = 1.0,
) -> float:
    """API 520 Eq.3.7 — orifice area [m²] for liquid service.

        A = W / (K_d · K_w · K_v · K_c · √(2 · ρ · ΔP))

    K_d for liquid service is 0.65 (conventional spring-op valve) per
    API 520 Table 6 — note the much lower value than vapor service.
    K_v is the viscosity correction (1.0 for water-like fluids).
    """
    dP = max(P1_Pa - P_back_Pa, 1.0)
    denom = K_d * K_w * K_v * K_c * math.sqrt(2.0 * rho_kg_per_m3 * dP)
    if denom <= 0:
        raise ValueError("Invalid PSV parameters — denominator non-positive")
    return W_kg_per_s / denom


# ─────────────────────────────────────────────────────────────────────────────
# API 521 §5.15 — Fire case
# ─────────────────────────────────────────────────────────────────────────────


def fire_case_heat_input_W(
    A_wetted_m2: float,
    F_environmental: float = 1.0,
    drainage_credit: bool = False,
) -> float:
    """API 521 Eq.5 — heat absorbed by a vessel exposed to an external
    pool fire [W].

        Q = 43_200 · F · A_wetted^0.82       (English units)
        Q = 21_000 · F · A_wetted^0.82       (SI, kW/m^1.64 — Eq.5b)
        Q [W] = 21_000 · F · A^0.82 · 1000

    ``F_environmental`` ranges 1.0 (bare vessel) down to 0.075 (drainage
    + water spray + insulation). The default conservatively assumes a
    bare vessel; set ``drainage_credit=True`` to drop F to 0.3.
    """
    if A_wetted_m2 <= 0:
        return 0.0
    F = 0.3 if drainage_credit else F_environmental
    return 21_000.0 * F * (A_wetted_m2 ** 0.82) * 1000.0  # W


def fire_case_relief_load_kg_per_s(
    A_wetted_m2: float,
    H_vap_J_per_kg: float = 2_260_000.0,
    F_environmental: float = 1.0,
    drainage_credit: bool = False,
) -> float:
    """Fire-case vapor generation rate [kg/s] = Q_fire / H_vap.

    Default H_vap = 2.26 MJ/kg (water at 100 °C). Use the actual fluid's
    latent heat for hydrocarbons (typical 350 kJ/kg for light HC).
    """
    Q = fire_case_heat_input_W(A_wetted_m2, F_environmental, drainage_credit)
    return Q / max(H_vap_J_per_kg, 1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# Set / full-lift pressure recommendations (ASME UG-125)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PressureRelieveSetpoints:
    P_set_Pa: float
    """Set pressure — PSV begins to open at this upstream pressure."""
    P_full_lift_Pa: float
    """Full-lift / accumulation pressure — PSV passes rated capacity."""
    P_back_max_Pa: float
    """Maximum allowable downstream back-pressure (10 % of set for
    conventional valves; 30–50 % for balanced bellows)."""


def recommended_setpoints(
    P_design_Pa: float,
    scenario: ReliefScenario = ReliefScenario.BLOCKED_OUTLET_GAS,
) -> PressureRelieveSetpoints:
    """ASME Sec VIII UG-125 set / full-lift pressure recommendations.

    For non-fire cases:
    * Single PSV: P_set ≤ P_design; full-lift at 1.10 × P_set (10 % accum.).
    * Multi-PSV: first valve at P_design; subsequent at 1.05 × P_design.

    For the fire case:
    * Full-lift allowed at 1.21 × P_design (21 % accumulation, UG-125(c)).

    Returns the set pressure equal to P_design (single-valve assumption)
    and the appropriate full-lift pressure for the scenario.
    """
    P_set = P_design_Pa
    if scenario == ReliefScenario.FIRE:
        P_full = 1.21 * P_design_Pa
    else:
        P_full = 1.10 * P_design_Pa
    # Conventional spring PSV: P_back_max ≤ 10 % × P_set absolute.
    P_back_max = 0.10 * P_set
    return PressureRelieveSetpoints(
        P_set_Pa=P_set, P_full_lift_Pa=P_full, P_back_max_Pa=P_back_max,
    )


# ─────────────────────────────────────────────────────────────────────────────
# All-in-one sizing convenience
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReliefSizingResult:
    scenario: ReliefScenario
    relief_load_kg_per_s: float
    orifice_area_m2: float
    setpoints: PressureRelieveSetpoints
    notes: str = ""


def size_psv_for_vessel(
    P_design_Pa: float,
    T_relief_K: float,
    A_wetted_m2: float = 0.0,
    blocked_inflow_kg_per_s: float = 0.0,
    MW_kg_per_mol: float = 0.029,
    gamma: float = 1.4,
    H_vap_J_per_kg: float = 350_000.0,
    Z: float = 1.0,
    K_d: float = 0.975,
    scenario: ReliefScenario = ReliefScenario.FIRE,
) -> ReliefSizingResult:
    """One-shot PSV sizing for a vessel under the chosen scenario.

    Defaults assume light-hydrocarbon vapour service (γ = 1.4, MW = 29
    g/mol, H_vap = 350 kJ/kg). For other fluids supply the actual values.
    """
    setpoints = recommended_setpoints(P_design_Pa, scenario)
    P_relieve = setpoints.P_full_lift_Pa

    if scenario == ReliefScenario.FIRE:
        W = fire_case_relief_load_kg_per_s(
            A_wetted_m2, H_vap_J_per_kg=H_vap_J_per_kg,
        )
        notes = (
            f"Fire case: Q_fire = {fire_case_heat_input_W(A_wetted_m2):.0f} W, "
            f"H_vap = {H_vap_J_per_kg / 1000:.0f} kJ/kg, "
            f"21 % accumulation allowed."
        )
    elif scenario == ReliefScenario.BLOCKED_OUTLET_GAS:
        W = blocked_inflow_kg_per_s
        notes = "Blocked-outlet: relief load = full upstream inflow rate."
    elif scenario == ReliefScenario.THERMAL_EXPANSION:
        # Small relief: 1 % of inflow (rule of thumb, API 521 §5.14)
        W = 0.01 * blocked_inflow_kg_per_s
        notes = "Thermal expansion: 1 % of inflow (API 521 §5.14)."
    else:
        raise ValueError(f"Unknown scenario {scenario}")

    A = orifice_area_vapor(
        W_kg_per_s=W,
        T_K=T_relief_K,
        P1_Pa=P_relieve,
        MW_kg_per_mol=MW_kg_per_mol,
        gamma=gamma,
        Z=Z,
        K_d=K_d,
    )
    return ReliefSizingResult(
        scenario=scenario,
        relief_load_kg_per_s=W,
        orifice_area_m2=A,
        setpoints=setpoints,
        notes=notes,
    )


__all__ = [
    "ReliefScenario",
    "PressureRelieveSetpoints",
    "ReliefSizingResult",
    "C_coefficient",
    "critical_pressure_ratio",
    "is_choked",
    "orifice_area_vapor",
    "orifice_area_liquid",
    "fire_case_heat_input_W",
    "fire_case_relief_load_kg_per_s",
    "recommended_setpoints",
    "size_psv_for_vessel",
]
