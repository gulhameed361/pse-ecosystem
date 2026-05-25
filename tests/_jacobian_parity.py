"""v1.6.1 P.4 — analytical-vs-FD Jacobian parity helpers.

A unit that overrides :meth:`BaseUnit.linearize` to return an analytical
Jacobian must match the central-difference reference within 1e-6
relative tolerance at the test operating point. This helper computes
both, takes the elementwise maximum relative diff, and reports the
worst-offending row/column when it fails (so derivation bugs are
diagnosable from a single failure line).

Used by ``tests/test_analytical_jacobians.py`` to validate every
analytical Jacobian we ship in v1.6.1 P.4.
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from pse_ecosystem.core.contracts import PrimalGuess
from pse_ecosystem.models.base_unit import BaseUnit


def assert_jacobian_matches_fd(
    unit: BaseUnit,
    x_state: Dict[str, float],
    rtol: float = 1e-6,
    atol: float = 1e-8,
) -> None:
    """Assert that ``unit.linearize`` returns the same J as the base-class
    central-difference scheme, within ``rtol`` (relative) / ``atol``
    (absolute) per entry.

    Each unit's residual ``r(x)`` should produce identical Jacobians
    regardless of whether ``linearize`` is the FD default or the
    analytical override. A mismatch usually means the derivation has a
    sign error, a missing term, or a chain-rule slip in the analytical
    code.
    """
    variables = unit.variables()
    n = len(variables)

    # Analytical (or whatever the unit's linearize returns).
    guess = PrimalGuess(values=dict(x_state), iteration=0)
    lin = unit.linearize(guess)
    J_analytic = np.asarray(lin.J, dtype=float)
    assert J_analytic.shape[1] == n, (
        f"Analytical J has {J_analytic.shape[1]} columns, expected {n}"
    )

    # Reference: central-difference FD via the BaseUnit default scheme.
    f0 = np.asarray(unit.residual(dict(x_state)), dtype=float).reshape(-1)
    J_fd = BaseUnit._finite_difference_jacobian(
        unit, dict(x_state), variables, f0,
    )

    if J_analytic.shape != J_fd.shape:
        raise AssertionError(
            f"Shape mismatch: analytical {J_analytic.shape}, FD {J_fd.shape}"
        )

    diff = np.abs(J_analytic - J_fd)
    rel = diff / np.maximum(np.abs(J_fd), 1e-12)

    # Mask entries where both are essentially zero — those should pass
    # trivially regardless of rtol.
    almost_zero = (np.abs(J_analytic) < atol) & (np.abs(J_fd) < atol)
    rel = np.where(almost_zero, 0.0, rel)
    diff = np.where(almost_zero, 0.0, diff)

    worst = np.unravel_index(int(np.argmax(rel)), rel.shape)
    if rel[worst] > rtol and diff[worst] > atol:
        i, j = worst
        raise AssertionError(
            f"Analytical Jacobian disagrees with FD at row {i} "
            f"(residual eq.), column {j} (variable {variables[j]!r}): "
            f"analytical={J_analytic[i, j]:.6g}, FD={J_fd[i, j]:.6g}, "
            f"|diff|={diff[i, j]:.3g}, rel={rel[i, j]:.3g}"
        )


__all__ = ["assert_jacobian_matches_fd"]
