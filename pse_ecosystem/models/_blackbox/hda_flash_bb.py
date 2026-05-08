"""HDA Flash Separator black-box simulator (BB2).

Wilson K-value VLE with Rachford-Rice flash equation.

Public API
----------
HDA_Flash_sim(F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in, F_Diph_in, T_FL, P_FL)
    -> 12-tuple: (F_H2_vap..F_Diph_vap, F_H2_liq..F_Diph_liq, H_vap, H_liq)

Source: Wilson (1969), Rachford & Rice (1952).
"""

import numpy as np
from scipy.optimize import brentq

COMPS = ['H2', 'CH4', 'Tol', 'Benz', 'Diph']

Tc = {'H2': 33.2, 'CH4': 190.6, 'Tol': 591.8, 'Benz': 562.2, 'Diph': 789.0}
Pc = {'H2': 1.297e6, 'CH4': 4.600e6, 'Tol': 4.109e6, 'Benz': 4.898e6, 'Diph': 3.990e6}
omega = {'H2': -0.216, 'CH4': 0.011, 'Tol': 0.263, 'Benz': 0.212, 'Diph': 0.438}
Cp  = {'H2': 29.1, 'CH4': 35.7, 'Tol': 103.7, 'Benz': 82.4, 'Diph': 165.0}
Hf  = {'H2': 0.0, 'CH4': -74850.0, 'Tol': 50170.0, 'Benz': 82930.0, 'Diph': 182000.0}
T_ref = 298.15


def _wilson_K(T, P):
    return {c: (Pc[c] / P) * np.exp(5.373 * (1.0 + omega[c]) * (1.0 - Tc[c] / T))
            for c in COMPS}


def _rachford_rice(psi, z, K):
    return sum(z[c] * (K[c] - 1.0) / (1.0 + psi * (K[c] - 1.0)) for c in COMPS)


def _solve_flash(z, K):
    psi_min = max(1.0 / (1.0 - max(K.values())) + 1e-8, 1e-8)
    psi_max = min(1.0 / (1.0 - min(K.values())) - 1e-8, 1.0 - 1e-8)
    if _rachford_rice(1e-8, z, K) <= 0.0:
        return 0.0
    if _rachford_rice(1.0 - 1e-8, z, K) >= 0.0:
        return 1.0
    try:
        return brentq(_rachford_rice, psi_min, psi_max,
                      args=(z, K), xtol=1e-10, rtol=1e-10, maxiter=200)
    except ValueError:
        return brentq(_rachford_rice, 1e-8, 1.0 - 1e-8,
                      args=(z, K), xtol=1e-8, rtol=1e-8, maxiter=200)


def _stream_enthalpy(F_dict, T):
    return sum(F * (Hf[c] + Cp[c] * (T - T_ref)) for c, F in F_dict.items()) * 1e-6


def HDA_Flash_sim(F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in, F_Diph_in, T_FL, P_FL):
    """Simulate isothermal flash. Returns 12-tuple (flowrates [mol/s], enthalpies [MJ/s])."""
    F_in = {c: max(float(v), 1e-12)
            for c, v in zip(COMPS, [F_H2_in, F_CH4_in, F_Tol_in, F_Benz_in, F_Diph_in])}
    T_FL = float(T_FL)
    P_FL = float(P_FL)
    F_total = sum(F_in.values())
    z = {c: F_in[c] / F_total for c in COMPS}
    K = _wilson_K(T_FL, P_FL)
    psi = np.clip(_solve_flash(z, K), 0.0, 1.0)
    y, x = {}, {}
    for c in COMPS:
        denom = 1.0 + psi * (K[c] - 1.0)
        y[c] = z[c] * K[c] / denom
        x[c] = z[c] / denom
    y_sum, x_sum = sum(y.values()), sum(x.values())
    y = {c: y[c] / y_sum for c in COMPS}
    x = {c: x[c] / x_sum for c in COMPS}
    V = psi * F_total
    L = (1.0 - psi) * F_total
    F_vap = {c: y[c] * V for c in COMPS}
    F_liq = {c: x[c] * L for c in COMPS}
    return (
        float(F_vap['H2']),   float(F_vap['CH4']),  float(F_vap['Tol']),
        float(F_vap['Benz']), float(F_vap['Diph']),
        float(F_liq['H2']),   float(F_liq['CH4']),  float(F_liq['Tol']),
        float(F_liq['Benz']), float(F_liq['Diph']),
        float(_stream_enthalpy(F_vap, T_FL)),
        float(_stream_enthalpy(F_liq, T_FL)),
    )
