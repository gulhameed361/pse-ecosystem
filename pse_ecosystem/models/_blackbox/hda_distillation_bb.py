"""HDA Distillation Train black-box simulator (BB3).

FUG shortcut (Fenske-Underwood-Gilliland) for two-column aromatics train.

Public API
----------
HDA_Distillation_sim(F_Benz_in, F_Tol_in, F_Diph_in, RR2, RR3)
    -> (F_Benz_product, F_Tol_recycle, F_Diph_out, Q_T2, Q_T3)

Source: Seader & Henley (2011), Douglas (1988).
"""

import numpy as np
# scipy import deferred to the public sim function so the module can be
# imported by environments without the `blackbox` extra. v1.4.0 audit H8.

COMPS_AROM = ['Benz', 'Tol', 'Diph']
Tc    = {'Benz': 562.2, 'Tol': 591.8, 'Diph': 789.0}
Pc    = {'Benz': 4.898e6, 'Tol': 4.109e6, 'Diph': 3.990e6}
omega = {'Benz': 0.212,   'Tol': 0.263,   'Diph': 0.438}
lambda_avg = {'T2': 32000.0, 'T3': 40000.0}
P_col = {'T2': 1.2 * 101325, 'T3': 1.0 * 101325}
T_col = {'T2': 365.0, 'T3': 420.0}
REC_MIN, REC_MAX = 1e-6, 1.0 - 1e-6


def _wilson_K_col(comp, T, P):
    return (Pc[comp] / P) * np.exp(5.373 * (1.0 + omega[comp]) * (1.0 - Tc[comp] / T))


def _rel_volatility(comps, T, P, heavy_key):
    K = {c: _wilson_K_col(c, T, P) for c in comps}
    K_hk = K[heavy_key]
    return {c: K[c] / K_hk for c in comps}


def _fenske(alpha_lk, x_lk_D, x_hk_D, x_lk_B, x_hk_B):
    ratio_D = max(x_lk_D, REC_MIN) / max(x_hk_D, REC_MIN)
    ratio_B = max(x_hk_B, REC_MIN) / max(x_lk_B, REC_MIN)
    return max(np.log(ratio_D * ratio_B) / np.log(max(alpha_lk, 1.001)), 1.0)


def _underwood(alpha, z_feed, q, comps):
    from scipy.optimize import brentq  # deferred — v1.4.0 audit H8
    alpha_lk = max(alpha[c] for c in comps)
    alpha_hk = min(alpha[c] for c in comps)
    eps = 1e-6
    def uw_eq(theta):
        return sum(alpha[c] * z_feed[c] / (alpha[c] - theta) for c in comps) - (1.0 - q)
    try:
        if uw_eq(alpha_hk + eps) * uw_eq(alpha_lk - eps) > 0:
            return 1.2
        theta = brentq(uw_eq, alpha_hk + eps, alpha_lk - eps,
                       xtol=1e-8, rtol=1e-8, maxiter=200)
    except (ValueError, RuntimeError):
        return 1.2
    return max(float(sum(alpha[c] * z_feed[c] / (alpha[c] - theta) for c in comps) - 1.0), 0.5)


def _gilliland(N_min, RR, RR_min):
    RR = max(RR, RR_min * 1.05)
    X = np.clip((RR - RR_min) / (RR + 1.0), 1e-6, 1.0 - 1e-6)
    Y = np.clip(1.0 - np.exp(((1.0 + 54.4*X)/(11.0 + 117.2*X)) * ((X - 1.0)/np.sqrt(X))),
                0.0, 1.0 - 1e-6)
    return max((N_min + Y) / (1.0 - Y), N_min + 1.0)


def _fug_column(F_feed, comps, light_key, heavy_key, rec_lk, rec_hk,
                RR, col_key, T_op, P_op):
    F_total = sum(F_feed.values())
    if F_total < 1e-10:
        zero = {c: 0.0 for c in comps}
        return zero, zero, 1.0, 1.0, 0.0
    z = {c: F_feed[c] / F_total for c in comps}
    alpha = _rel_volatility(comps, T_op, P_op, heavy_key)
    alpha_lk = alpha[light_key]
    F_dist = {light_key: rec_lk * F_feed[light_key],
              heavy_key: (1.0 - rec_hk) * F_feed[heavy_key]}
    F_bot  = {light_key: (1.0 - rec_lk) * F_feed[light_key],
              heavy_key: rec_hk * F_feed[heavy_key]}
    for c in comps:
        if c in (light_key, heavy_key):
            continue
        alpha_c = alpha[c]
        if alpha_c >= alpha_lk:
            F_dist[c] = F_feed[c] * REC_MAX
            F_bot[c]  = F_feed[c] * REC_MIN
        elif alpha_c <= 1.0:
            F_dist[c] = F_feed[c] * REC_MIN
            F_bot[c]  = F_feed[c] * REC_MAX
        else:
            frac = np.clip((alpha_c - 1.0) / (alpha_lk - 1.0), REC_MIN, REC_MAX)
            F_dist[c] = F_feed[c] * frac
            F_bot[c]  = F_feed[c] * (1.0 - frac)
    D = sum(F_dist.values())
    B = sum(F_bot.values())
    if D < 1e-10 or B < 1e-10:
        return F_dist, F_bot, 2.0, 1.0, (RR + 1.0) * max(D, 1e-10) * lambda_avg[col_key] * 1e-6
    x_lk_D = F_dist[light_key] / D
    x_hk_D = F_dist[heavy_key] / D
    x_lk_B = F_bot[light_key]  / B
    x_hk_B = F_bot[heavy_key]  / B
    N_min   = _fenske(alpha_lk, x_lk_D, x_hk_D, x_lk_B, x_hk_B)
    RR_min  = _underwood(alpha, z, q=1.0, comps=comps)
    N_stages = _gilliland(N_min, RR, RR_min)
    Q_col   = (RR + 1.0) * D * lambda_avg[col_key] * 1e-6
    return F_dist, F_bot, N_stages, RR_min, float(Q_col)


def HDA_Distillation_sim(F_Benz_in, F_Tol_in, F_Diph_in, RR2, RR3):
    """Simulate two-column HDA distillation train. Returns 5-tuple."""
    F_Benz_in = max(float(F_Benz_in), 1e-10)
    F_Tol_in  = max(float(F_Tol_in),  1e-10)
    F_Diph_in = max(float(F_Diph_in), 1e-10)
    RR2 = max(float(RR2), 1.05)
    RR3 = max(float(RR3), 1.05)

    feed_T2 = {'Benz': F_Benz_in, 'Tol': F_Tol_in, 'Diph': F_Diph_in}
    F_dist_T2, F_bot_T2, _, _, Q_T2 = _fug_column(
        feed_T2, COMPS_AROM, 'Benz', 'Tol', 0.997, 0.995,
        RR2, 'T2', T_col['T2'], P_col['T2'])

    feed_T3 = {c: F_bot_T2.get(c, 1e-10) for c in COMPS_AROM}
    F_dist_T3, F_bot_T3, _, _, Q_T3 = _fug_column(
        feed_T3, COMPS_AROM, 'Tol', 'Diph', 0.995, 0.999,
        RR3, 'T3', T_col['T3'], P_col['T3'])

    return (
        float(F_dist_T2['Benz']),
        float(F_dist_T3['Tol']),
        float(F_bot_T3['Diph']),
        float(Q_T2),
        float(Q_T3),
    )
