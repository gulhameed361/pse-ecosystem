"""Kinetic parameter tuner — minimise parity error via scipy.optimize.

Wraps :func:`scipy.optimize.least_squares` to fit a small set of kinetic
parameters (Arrhenius A, Ea, reaction orders) so the flowsheet's
predictions match measured plant data. The pattern:

1. The user supplies a list of :class:`KineticParam` (each with bounds
   and an initial value) plus a *prediction function* that runs the
   flowsheet for a given parameter vector and returns the predicted
   variable values.
2. The tuner calls :func:`scipy.optimize.least_squares` with the
   residual ``(measured − predicted)`` per variable.
3. Returns a :class:`TuneResult` with the optimised parameter values,
   the before/after parity metrics, and convergence diagnostics.

This is **screening-grade** — full kinetic regression (uncertainty
quantification, profile likelihood, etc.) is out of scope for v1.6.
The default trust-region-reflective algorithm handles the simple
bounded-least-squares case adequately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Sequence

from pse_ecosystem.validation.parity import (
    ParityResult,
    compute_metrics,
)


@dataclass
class KineticParam:
    name: str
    """Display name (e.g. ``A_1``, ``Ea_2`` for reaction-1 pre-exponential
    or reaction-2 activation energy). Used in :class:`TuneResult.tuned`."""
    initial: float
    lower: float = 0.0
    upper: float = float("inf")
    log_scale: bool = False
    """If True, the tuner perturbs ln(param) instead of param — appropriate
    for Arrhenius pre-exponentials A which span many orders of magnitude."""


@dataclass
class TuneResult:
    tuned: Dict[str, float] = field(default_factory=dict)
    initial: Dict[str, float] = field(default_factory=dict)
    parity_before: ParityResult = field(default_factory=ParityResult)
    parity_after: ParityResult = field(default_factory=ParityResult)
    converged: bool = False
    n_iterations: int = 0
    message: str = ""


def tune_kinetics(
    params: List[KineticParam],
    measured: Mapping[str, Sequence[float]],
    predict_fn: Callable[[Dict[str, float]], Dict[str, Sequence[float]]],
    *,
    max_iter: int = 200,
    rtol: float = 1e-6,
) -> TuneResult:
    """Fit ``params`` so ``predict_fn(params) ≈ measured``.

    Parameters
    ----------
    params      : List of :class:`KineticParam` defining the search space.
    measured    : ``{var: list_of_values}`` measured reference data.
    predict_fn  : Callable mapping ``{param_name: value}`` to a dict
                  of predicted variable values (same keys as ``measured``).
                  This is the link to the flowsheet — typically wraps
                  ``flowsheet.solve()`` and extracts the relevant outputs.
    max_iter    : Maximum scipy iterations.
    rtol        : Tolerance on the objective.

    Returns
    -------
    :class:`TuneResult` with before/after parity metrics and converged
    parameter values.
    """
    import numpy as np
    from scipy.optimize import least_squares

    # Initial guess + bounds in tuner space (log if requested)
    x0 = []
    lo = []
    hi = []
    for p in params:
        v = p.initial
        if p.log_scale:
            x0.append(_safe_log(v))
            lo.append(_safe_log(max(p.lower, 1e-30)))
            hi.append(_safe_log(max(p.upper, p.initial * 1e6)))
        else:
            x0.append(v)
            lo.append(p.lower)
            hi.append(p.upper if p.upper != float("inf") else 1e12)

    common_vars = sorted(set(measured.keys()))

    def residual(x_vec: "np.ndarray") -> "np.ndarray":
        pdict = _vector_to_params(x_vec, params)
        try:
            pred = predict_fn(pdict)
        except Exception:  # noqa: BLE001
            # Solver crash → huge residual so optimiser backs off.
            return np.full(sum(len(measured[v]) for v in common_vars), 1e6)
        res: List[float] = []
        for v in common_vars:
            m_vals = list(measured.get(v, []))
            p_vals = list(pred.get(v, []))
            n = min(len(m_vals), len(p_vals))
            res.extend(m_vals[i] - p_vals[i] for i in range(n))
            # Pad missing with 0 so the residual length stays constant
            res.extend(0.0 for _ in range(len(m_vals) - n))
        return np.array(res, dtype=float)

    initial_pred = predict_fn(_vector_to_params(np.array(x0), params))
    parity_before = compute_metrics(measured, initial_pred)

    sol = least_squares(
        residual, x0=x0, bounds=(lo, hi),
        method="trf", max_nfev=max_iter, ftol=rtol, xtol=rtol,
    )
    tuned_dict = _vector_to_params(sol.x, params)
    tuned_pred = predict_fn(tuned_dict)
    parity_after = compute_metrics(measured, tuned_pred)

    return TuneResult(
        tuned=tuned_dict,
        initial={p.name: p.initial for p in params},
        parity_before=parity_before,
        parity_after=parity_after,
        converged=bool(sol.success),
        n_iterations=int(sol.nfev),
        message=str(sol.message),
    )


def _vector_to_params(
    x_vec: Sequence[float], params: List[KineticParam]
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for i, p in enumerate(params):
        if p.log_scale:
            out[p.name] = _safe_exp(x_vec[i])
        else:
            out[p.name] = float(x_vec[i])
    return out


def _safe_log(v: float) -> float:
    import math
    return math.log(max(v, 1e-30))


def _safe_exp(v: float) -> float:
    import math
    return math.exp(min(max(v, -700.0), 700.0))


__all__ = ["KineticParam", "TuneResult", "tune_kinetics"]
