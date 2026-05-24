"""Vessel depressuring — orifice-flow blowdown calculations.

Computes the time-history of pressure, temperature, and mass-out during a
controlled blowdown through a fixed orifice or restriction (PSV in the
open position, blowdown valve, manual vent).

Critical (choked) vs sub-critical flow regimes are handled separately:

* **Choked** (P_back / P1 ≤ P_critical_ratio): flow rate depends only on
  upstream conditions; downstream pressure is irrelevant.
* **Sub-critical** (P_back / P1 > critical): flow rate depends on the
  pressure ratio through the standard isentropic-nozzle equation.

For v1.6 the depressuring is **isothermal** — the Joule-Thomson cooling
from rapid expansion is ignored. This is a screening-grade assumption
suitable for blowdown-time estimates; for cold-temperature-risk studies
(brittle fracture during blowdown), use a dedicated tool with full
isentropic-cooling integration.

Reference: API 521 §5.20 (Vapour depressuring); Mahgerefteh & Saha (1999),
*Chem Eng Sci* 54.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

_R_GAS = 8.314462


def critical_pressure_ratio(gamma: float) -> float:
    """P_back/P1 below which flow is choked. ≈ 0.528 for γ=1.4."""
    return (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))


def choked_mass_flux(
    P_up_Pa: float,
    T_up_K: float,
    MW_kg_per_mol: float,
    gamma: float,
    C_d: float = 0.85,
) -> float:
    """Mass flux through a choked orifice [kg/s/m²].

        G_choked = C_d · P_up · √(γ · M / (R · T_up) · (2/(γ+1))^((γ+1)/(γ-1)))
    """
    exp = (gamma + 1.0) / (gamma - 1.0)
    psi = (2.0 / (gamma + 1.0)) ** exp
    return C_d * P_up_Pa * math.sqrt(
        gamma * MW_kg_per_mol / (_R_GAS * max(T_up_K, 1.0)) * psi
    )


def subcritical_mass_flux(
    P_up_Pa: float,
    P_down_Pa: float,
    T_up_K: float,
    MW_kg_per_mol: float,
    gamma: float,
    C_d: float = 0.85,
) -> float:
    """Mass flux through a sub-critical orifice [kg/s/m²].

        G_sub = C_d · P_up · √(2γ·M / ((γ−1)·R·T) ·
                              [(P_d/P_up)^(2/γ) − (P_d/P_up)^((γ+1)/γ)])
    """
    r = max(P_down_Pa / max(P_up_Pa, 1e-9), 1e-9)
    inner = (r ** (2.0 / gamma)) - (r ** ((gamma + 1.0) / gamma))
    if inner <= 0:
        return 0.0
    coef = (
        2.0 * gamma * MW_kg_per_mol
        / ((gamma - 1.0) * _R_GAS * max(T_up_K, 1.0))
    )
    return C_d * P_up_Pa * math.sqrt(coef * inner)


def mass_flux(
    P_up_Pa: float,
    P_down_Pa: float,
    T_up_K: float,
    MW_kg_per_mol: float,
    gamma: float,
    C_d: float = 0.85,
) -> float:
    """Auto-select choked vs sub-critical mass flux [kg/s/m²]."""
    r_crit = critical_pressure_ratio(gamma)
    if (P_down_Pa / max(P_up_Pa, 1e-9)) <= r_crit:
        return choked_mass_flux(P_up_Pa, T_up_K, MW_kg_per_mol, gamma, C_d)
    return subcritical_mass_flux(
        P_up_Pa, P_down_Pa, T_up_K, MW_kg_per_mol, gamma, C_d,
    )


@dataclass(frozen=True)
class DepressurState:
    t_s: float
    P_Pa: float
    T_K: float
    m_remaining_kg: float
    G_kg_per_s: float


def depressuring_schedule(
    V_vessel_m3: float,
    A_orifice_m2: float,
    P_initial_Pa: float,
    P_back_Pa: float,
    T_K: float,
    MW_kg_per_mol: float,
    gamma: float,
    C_d: float = 0.85,
    P_target_Pa: float = 0.0,
    dt_s: float = 5.0,
    t_max_s: float = 3600.0,
) -> List[DepressurState]:
    """Forward-Euler isothermal blowdown integration.

    Returns a list of ``DepressurState`` snapshots at uniform ``dt_s``
    intervals up to whichever comes first: P_target_Pa reached or
    t_max_s elapsed.

    Algorithm
    ---------
    Ideal gas: n = P·V/(R·T); m = n·M.
    dm/dt = − G(P, T) · A_orifice  → choked or sub-critical per ratio.
    dP/dt = −m_dot · R · T / (V · M) at isothermal.

    For P_target_Pa = 0, the integration stops when P falls below 2 × P_back
    (sub-critical flow becomes negligible).
    """
    P = P_initial_Pa
    schedule: List[DepressurState] = []
    n_max = int(t_max_s / dt_s) + 1
    P_stop = max(P_target_Pa, 1.1 * P_back_Pa)
    for k in range(n_max):
        t = k * dt_s
        m_total = P * V_vessel_m3 * MW_kg_per_mol / (_R_GAS * max(T_K, 1.0))
        G = mass_flux(P, P_back_Pa, T_K, MW_kg_per_mol, gamma, C_d)
        schedule.append(
            DepressurState(
                t_s=t, P_Pa=P, T_K=T_K, m_remaining_kg=m_total, G_kg_per_s=G,
            )
        )
        if P <= P_stop:
            break
        # dP/dt via isothermal ideal-gas relation
        dP_dt = -G * A_orifice_m2 * _R_GAS * T_K / (V_vessel_m3 * MW_kg_per_mol)
        P = max(P + dP_dt * dt_s, P_back_Pa)
    return schedule


def blowdown_time_s(
    V_vessel_m3: float,
    A_orifice_m2: float,
    P_initial_Pa: float,
    P_back_Pa: float,
    T_K: float,
    MW_kg_per_mol: float,
    gamma: float,
    C_d: float = 0.85,
    P_target_Pa: float = 0.0,
    dt_s: float = 5.0,
    t_max_s: float = 3600.0,
) -> float:
    """Time [s] to depressurise from P_initial to P_target (or 2·P_back).

    Wraps :func:`depressuring_schedule` and returns the elapsed time at
    the last state.
    """
    sched = depressuring_schedule(
        V_vessel_m3, A_orifice_m2, P_initial_Pa, P_back_Pa, T_K,
        MW_kg_per_mol, gamma, C_d, P_target_Pa, dt_s, t_max_s,
    )
    return sched[-1].t_s if sched else 0.0


__all__ = [
    "DepressurState",
    "critical_pressure_ratio",
    "choked_mass_flux",
    "subcritical_mass_flux",
    "mass_flux",
    "depressuring_schedule",
    "blowdown_time_s",
]
