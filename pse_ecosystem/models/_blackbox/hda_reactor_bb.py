"""HDA Plug-Flow Reactor black-box simulator (BB1).

Kinetics-corrected version. A2 = 3.160e4 mol/(m3 s atm2)
(corrected from erroneous 3.160e9 in original formulation).

Public API
----------
HDA_Reactor_sim(F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in, T_in, V_R)
    -> (F_H2_out, F_CH4_out, F_Tol_out, F_Benz_out, F_Diph_out, T_out, H_out)

Source: Douglas (1988), Eason & Biegler (2016), AIChE J. 62(9):3124-3136.
"""

import numpy as np
from scipy.integrate import solve_ivp

# ── Kinetic parameters ────────────────────────────────────────────────────────

A1  = 5.987e4    # pre-exponential R1 [mol/(m3 s atm2)]
A2  = 3.160e4    # pre-exponential R2 [mol/(m3 s atm2)]  CORRECTED from 3.160e9
Ea1 = 1.256e5    # activation energy R1 [J/mol]
Ea2 = 1.674e5    # activation energy R2 [J/mol]
dHr1 = -1.717e5  # heat of reaction R1 [J/mol]
dHr2 = -1.046e5  # heat of reaction R2 [J/mol]

P_sys_atm = 25.0  # system pressure [atm]
R_gas     = 8.314 # [J/(mol K)]

Cp = {'H2': 29.1, 'CH4': 35.7, 'Tol': 103.7, 'Benz': 82.4, 'Diph': 165.0}
Hf = {'H2': 0.0, 'CH4': -74850.0, 'Tol': 50170.0, 'Benz': 82930.0, 'Diph': 182000.0}
T_ref = 298.15


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stream_enthalpy(F_dict, T):
    H = sum(F * (Hf[c] + Cp[c] * (T - T_ref)) for c, F in F_dict.items())
    return H * 1e-6  # J/s -> MJ/s


def _pfr_odes(V, y):
    F_H2, F_CH4, F_Tol, F_Benz, F_Diph, T = y
    F_H2   = max(F_H2,   1e-12)
    F_CH4  = max(F_CH4,  1e-12)
    F_Tol  = max(F_Tol,  1e-12)
    F_Benz = max(F_Benz, 1e-12)
    F_Diph = max(F_Diph, 1e-12)
    T      = max(T, 300.0)
    F_total = F_H2 + F_CH4 + F_Tol + F_Benz + F_Diph
    P_H2   = (F_H2   / F_total) * P_sys_atm
    P_Tol  = (F_Tol  / F_total) * P_sys_atm
    P_Benz = (F_Benz / F_total) * P_sys_atm
    r1 = A1 * np.exp(-Ea1 / (R_gas * T)) * P_Tol  * P_H2
    r2 = A2 * np.exp(-Ea2 / (R_gas * T)) * P_Benz ** 2
    dF_H2   = -r1 + r2
    dF_CH4  =  r1
    dF_Tol  = -r1
    dF_Benz =  r1 - 2.0 * r2
    dF_Diph =  r2
    FCp = (F_H2  * Cp['H2']  + F_CH4 * Cp['CH4'] +
           F_Tol * Cp['Tol'] + F_Benz * Cp['Benz'] +
           F_Diph * Cp['Diph'])
    dT = -(r1 * dHr1 + r2 * dHr2) / max(FCp, 1e-10)
    return [dF_H2, dF_CH4, dF_Tol, dF_Benz, dF_Diph, dT]


# ── Public simulator ──────────────────────────────────────────────────────────

def HDA_Reactor_sim(F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in, T_in, V_R):
    """Simulate HDA adiabatic PFR. Returns 7-tuple (mol/s, mol/s, ..., K, MJ/s)."""
    y0 = [
        max(float(F_H2_in),   1e-10),
        max(float(F_CH4_in),  1e-10),
        max(float(F_Tol_in),  1e-10),
        max(float(F_Benz_in), 1e-10),
        1e-10,
        float(T_in),
    ]
    sol = solve_ivp(
        _pfr_odes,
        t_span=(0.0, float(V_R)),
        y0=y0,
        method='LSODA',
        rtol=1e-4,
        atol=1e-6,
        max_step=float(V_R) / 5.0,
    )
    if not sol.success:
        F_H2_out   = float(F_H2_in)  * 0.99
        F_CH4_out  = float(F_CH4_in) + 0.001
        F_Tol_out  = float(F_Tol_in) * 0.99
        F_Benz_out = max(float(F_Benz_in), 0.001)
        F_Diph_out = 1e-8
        T_out      = float(T_in) + 5.0
    else:
        F_H2_out, F_CH4_out, F_Tol_out, F_Benz_out, F_Diph_out, T_out = sol.y[:, -1]
        F_H2_out   = max(float(F_H2_out),   0.0)
        F_CH4_out  = max(float(F_CH4_out),  0.0)
        F_Tol_out  = max(float(F_Tol_out),  0.0)
        F_Benz_out = max(float(F_Benz_out), 0.0)
        F_Diph_out = max(float(F_Diph_out), 0.0)
        T_out      = float(T_out)

    H_out = _stream_enthalpy(
        {'H2': F_H2_out, 'CH4': F_CH4_out, 'Tol': F_Tol_out,
         'Benz': F_Benz_out, 'Diph': F_Diph_out}, T_out
    )
    return (F_H2_out, F_CH4_out, F_Tol_out, F_Benz_out, F_Diph_out, T_out, H_out)
