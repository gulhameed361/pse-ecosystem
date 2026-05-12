"""Full NLP residual + Jacobian builder for the scipy-based NLP driver.

This module exposes the flowsheet as a differentiable (x → residual, Jacobian)
system that scipy.optimize can minimise.  Every unit's ``residual(x)`` and
``linearize(guess)`` are used in-place; no Pyomo model is built here.

Architecture note
-----------------
Layer 2 (this file) calls Layer 3 only through the Handshake Protocol
(``unit.residual``, ``unit.linearize``). No physics lives here.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import PrimalGuess
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet


def build_residual_function(
    flowsheet: BaseFlowsheet,
) -> Tuple[callable, callable, List[str], List[Tuple[float, float]]]:
    """Return ``(f, J_func, var_names, scipy_bounds)`` for the full NLP system.

    ``f(x_vec) → np.ndarray`` evaluates the stacked residual:
        [unit residuals ..., connection equalities ..., extra equalities ...]

    ``J_func(x_vec) → np.ndarray`` (shape ``(m, n)``) evaluates the full
    Jacobian using each unit's ``linearize()`` for unit rows, and exact
    analytical entries for connection / extra-equality rows.
    """
    var_names = flowsheet.all_variables()
    var_idx: Dict[str, int] = {v: i for i, v in enumerate(var_names)}
    n = len(var_names)

    agg_bounds = flowsheet.aggregated_bounds()
    scipy_bounds = [
        (agg_bounds.get(v, (-1e18, 1e18))[0],
         agg_bounds.get(v, (-1e18, 1e18))[1])
        for v in var_names
    ]
    # Clip huge bounds to scipy-friendly values
    scipy_bounds = [
        (max(lo, -1e18), min(hi, 1e18)) for lo, hi in scipy_bounds
    ]

    def f(x_vec: np.ndarray) -> np.ndarray:
        x_dict = dict(zip(var_names, x_vec))
        chunks: List[np.ndarray] = []
        for unit in flowsheet.units:
            r = np.asarray(unit.residual(x_dict), dtype=float).reshape(-1)
            chunks.append(r)
        for conn in flowsheet.connections:
            chunks.append(np.array([
                x_dict.get(conn.var_a, 0.0) - x_dict.get(conn.var_b, 0.0)
            ]))
        for coeffs, rhs in flowsheet.extra_equalities:
            val = sum(c * x_dict.get(v, 0.0) for v, c in coeffs.items()) - rhs
            chunks.append(np.array([val]))
        return np.concatenate(chunks) if chunks else np.zeros(0)

    def J_func(x_vec: np.ndarray) -> np.ndarray:
        x_dict = dict(zip(var_names, x_vec))
        guess = PrimalGuess(values=x_dict, iteration=0)
        rows: List[np.ndarray] = []
        for unit in flowsheet.units:
            lin = unit.linearize(guess)
            m_u = lin.J.shape[0]
            J_unit = np.zeros((m_u, n))
            for local_j, vname in enumerate(lin.variables):
                global_j = var_idx.get(vname)
                if global_j is not None:
                    J_unit[:, global_j] = lin.J[:, local_j]
            rows.append(J_unit)
        for conn in flowsheet.connections:
            row = np.zeros(n)
            ia = var_idx.get(conn.var_a)
            ib = var_idx.get(conn.var_b)
            if ia is not None:
                row[ia] = 1.0
            if ib is not None:
                row[ib] = -1.0
            rows.append(row.reshape(1, -1))
        for coeffs, _ in flowsheet.extra_equalities:
            row = np.zeros(n)
            for v, c in coeffs.items():
                idx = var_idx.get(v)
                if idx is not None:
                    row[idx] = float(c)
            rows.append(row.reshape(1, -1))
        if rows:
            return np.vstack(rows)
        return np.zeros((0, n))

    return f, J_func, var_names, scipy_bounds
