"""Parity metrics — MAPE / RMSE / R² for predicted-vs-measured data.

Used to quantify how well a PSE Ecosystem flowsheet matches reference
data (Aspen, plant measurements, NIST). Returns a :class:`ParityResult`
that the UI's Validation page renders as a parity scatter + per-variable
breakdown table.

Three metrics per variable:

* **MAPE** — Mean Absolute Percentage Error = mean(|m − p| / |m|) × 100
* **RMSE** — Root Mean Square Error = √(mean((m − p)²))
* **R²**   — Coefficient of determination = 1 − Σ(m−p)² / Σ(m−m̄)²

For multi-variable runs the per-variable metrics are aggregated into a
single ``overall_mape_pct`` (mean of per-variable MAPE, mass-weighted
optional) and ``worst_variable`` (variable with the largest MAPE).

No pandas / plotly dependency; the scatter-data helper returns plain
``dict[str, list]`` that any UI layer (Streamlit, Dash, custom HTML)
can consume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Result containers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VariableMetrics:
    name: str
    n_points: int
    mape_pct: float
    rmse: float
    r_squared: float
    mean_measured: float
    mean_predicted: float
    max_abs_error: float


@dataclass
class ParityResult:
    per_variable: Dict[str, VariableMetrics] = field(default_factory=dict)
    overall_mape_pct: float = 0.0
    overall_rmse: float = 0.0
    worst_variable: str = ""
    n_variables: int = 0

    def mape_threshold_passed(self, threshold_pct: float) -> bool:
        """``True`` if every variable's MAPE is below ``threshold_pct``."""
        if not self.per_variable:
            return False
        return all(
            v.mape_pct <= threshold_pct for v in self.per_variable.values()
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "overall_mape_pct": self.overall_mape_pct,
            "overall_rmse": self.overall_rmse,
            "worst_variable": self.worst_variable,
            "n_variables": self.n_variables,
            "per_variable": {
                name: {
                    "n_points": m.n_points,
                    "mape_pct": m.mape_pct,
                    "rmse": m.rmse,
                    "r_squared": m.r_squared,
                    "mean_measured": m.mean_measured,
                    "mean_predicted": m.mean_predicted,
                    "max_abs_error": m.max_abs_error,
                }
                for name, m in self.per_variable.items()
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# Metric kernels
# ─────────────────────────────────────────────────────────────────────────────


def _mape(measured: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean Absolute Percentage Error [%]. Skips m=0 to avoid div-by-zero."""
    pairs = [
        (m, p) for m, p in zip(measured, predicted)
        if abs(m) > 1e-12
    ]
    if not pairs:
        return float("nan")
    return 100.0 * sum(abs(m - p) / abs(m) for m, p in pairs) / len(pairs)


def _rmse(measured: Sequence[float], predicted: Sequence[float]) -> float:
    if not measured:
        return float("nan")
    n = len(measured)
    sq_err = sum((m - p) ** 2 for m, p in zip(measured, predicted))
    return math.sqrt(sq_err / n)


def _r_squared(
    measured: Sequence[float], predicted: Sequence[float]
) -> float:
    if not measured:
        return float("nan")
    m_mean = sum(measured) / len(measured)
    ss_res = sum((m - p) ** 2 for m, p in zip(measured, predicted))
    ss_tot = sum((m - m_mean) ** 2 for m in measured)
    if ss_tot < 1e-30:
        return float("nan")
    return 1.0 - ss_res / ss_tot


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def compute_metrics(
    measured: Mapping[str, Sequence[float]],
    predicted: Mapping[str, Sequence[float]],
) -> ParityResult:
    """Compute parity metrics for every variable in ``measured`` ∩ ``predicted``.

    Parameters
    ----------
    measured, predicted : ``{var_name: list_of_values}``. The keys define
                          which variables to compare; values must be the
                          same length per key.

    Returns
    -------
    :class:`ParityResult` populated with per-variable metrics and overall
    aggregates. Variables in ``measured`` but missing from ``predicted``
    are silently skipped (a soft-fail mode that lets the user see what
    matched without aborting on partial datasets).
    """
    result = ParityResult()
    common_vars = sorted(set(measured.keys()) & set(predicted.keys()))
    if not common_vars:
        return result

    mape_sum = 0.0
    rmse_sum_sq = 0.0
    worst_mape = -1.0
    worst_var = ""
    valid_count = 0

    for name in common_vars:
        m_vals = list(measured[name])
        p_vals = list(predicted[name])
        if len(m_vals) != len(p_vals) or not m_vals:
            continue
        mape = _mape(m_vals, p_vals)
        rmse = _rmse(m_vals, p_vals)
        r2 = _r_squared(m_vals, p_vals)
        max_err = max(abs(m - p) for m, p in zip(m_vals, p_vals))
        mean_m = sum(m_vals) / len(m_vals)
        mean_p = sum(p_vals) / len(p_vals)
        result.per_variable[name] = VariableMetrics(
            name=name, n_points=len(m_vals),
            mape_pct=mape, rmse=rmse, r_squared=r2,
            mean_measured=mean_m, mean_predicted=mean_p,
            max_abs_error=max_err,
        )
        if not math.isnan(mape):
            mape_sum += mape
            rmse_sum_sq += rmse ** 2
            valid_count += 1
            if mape > worst_mape:
                worst_mape = mape
                worst_var = name

    if valid_count > 0:
        result.overall_mape_pct = mape_sum / valid_count
        result.overall_rmse = math.sqrt(rmse_sum_sq / valid_count)
        result.worst_variable = worst_var
        result.n_variables = valid_count
    return result


def scatter_data(
    measured: Mapping[str, Sequence[float]],
    predicted: Mapping[str, Sequence[float]],
) -> Dict[str, List[float]]:
    """Flatten measured/predicted pairs to a single (x, y) series for a
    parity scatter plot.

    Returns
    -------
    ``{"measured": [...], "predicted": [...], "variable": [...]}`` —
    the ``variable`` parallel array tags each point with its variable
    name so the UI can colour-code by series.
    """
    out: Dict[str, List[float]] = {
        "measured": [], "predicted": [], "variable": [],
    }
    for name in sorted(set(measured.keys()) & set(predicted.keys())):
        m_vals = list(measured[name])
        p_vals = list(predicted[name])
        if len(m_vals) != len(p_vals):
            continue
        for m, p in zip(m_vals, p_vals):
            out["measured"].append(float(m))
            out["predicted"].append(float(p))
            out["variable"].append(name)
    return out


__all__ = [
    "VariableMetrics",
    "ParityResult",
    "compute_metrics",
    "scatter_data",
]
