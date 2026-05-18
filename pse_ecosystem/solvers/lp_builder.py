"""Pyomo LP assembly from a list of LinearizedModel + flowsheet topology.

Stateless. Layer 2's only window into Layer 3 is the ``LinearizedModel``
records this builder consumes — it has zero awareness of unit physics.

The LP rows constructed for each ``LinearizedModel`` come from rearranging
the Taylor expansion::

    f0 + J · (x - x0) = 0
    ⇒  J · x = J · x0 - f0

so each constraint row is::

    Σ_j J[r, j] · x[var_j] == ( J[r, :] @ x0 - f0[r] )

Connections, flowsheet-level equalities and bounds are then layered on top.
A trust-region box constraint ``|x_v - x_anchor_v| ≤ Δ`` is added when
``trust_region`` is provided.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np
import pyomo.environ as pyo

from pse_ecosystem.core.contracts import LinearizedModel
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet


_PYOMO_INF = 1e20


def _bound_pair(lo: float, hi: float) -> tuple[Optional[float], Optional[float]]:
    pyomo_lo = None if lo <= -_PYOMO_INF else float(lo)
    pyomo_hi = None if hi >= _PYOMO_INF else float(hi)
    return pyomo_lo, pyomo_hi


def build_lp(
    linearizations: Iterable[LinearizedModel],
    flowsheet: BaseFlowsheet,
    *,
    x_anchor: Optional[Dict[str, float]] = None,
    tr_multiplier: float = 0.0,
) -> pyo.ConcreteModel:
    """Build a Pyomo ``ConcreteModel`` LP from per-unit linearisations.

    Parameters
    ----------
    linearizations:
        One :class:`LinearizedModel` per unit (or per active unit, in MILP
        contexts where some units are switched off upstream).
    flowsheet:
        Provides connections, flowsheet-level equalities and bound overrides.
    x_anchor:
        Reference point for any trust-region constraints. Required when
        ``tr_multiplier > 0`` and at least one unit supplies a
        ``trust_region`` hint.
    tr_multiplier:
        Driver-level scale applied to every unit-supplied ``trust_region``
        radius. ``0.0`` (default) disables trust regions entirely; the SLP
        driver passes its current ``Δ`` here when it wants TR active.
    """

    linearizations = list(linearizations)
    model = pyo.ConcreteModel(name=f"LP::{flowsheet.name}")

    # v1.4.0 audit N11 — pre-solve self-check on flowsheet-level extras.
    # Surfaces typos in extra_equalities / extra_bounds / objective_extra
    # with a helpful error before Pyomo's opaque KeyError fires.
    if hasattr(flowsheet, "validate"):
        flowsheet.validate()

    # ── Collect variables and bounds ──────────────────────────────────────
    all_vars = flowsheet.all_variables()
    bounds = flowsheet.aggregated_bounds()

    # Per-unit bounds may also tighten the global picture.
    for lin in linearizations:
        for v, (lo, hi) in lin.bounds.items():
            if v in bounds:
                merged_lo = max(bounds[v][0], lo)
                merged_hi = min(bounds[v][1], hi)
                # v1.4.0 audit N1 — flag the inverted-bounds case explicitly
                # instead of letting Pyomo silently report infeasibility.
                if merged_lo > merged_hi:
                    raise ValueError(
                        f"Conflicting bounds for variable {v!r}: "
                        f"flowsheet/aggregated bound {bounds[v]} vs. unit "
                        f"{lin.unit_id!r} bound ({lo}, {hi}). Result of "
                        f"tightest-wins merge is ({merged_lo}, {merged_hi}) "
                        f"which is empty — fix one of the two declarations."
                    )
                bounds[v] = (merged_lo, merged_hi)
            else:
                if lo > hi:
                    raise ValueError(
                        f"Unit {lin.unit_id!r} declares inverted bounds for "
                        f"{v!r}: ({lo}, {hi}). Lower must be ≤ upper."
                    )
                bounds[v] = (lo, hi)

    def _var_init(_m, name: str):  # pragma: no cover - trivial closure
        if x_anchor and name in x_anchor:
            return x_anchor[name]
        lo, hi = bounds.get(name, (-_PYOMO_INF, _PYOMO_INF))
        if lo > -_PYOMO_INF and hi < _PYOMO_INF:
            return 0.5 * (lo + hi)
        return 0.0

    def _var_bounds(_m, name: str):  # pragma: no cover - trivial closure
        return _bound_pair(*bounds.get(name, (-_PYOMO_INF, _PYOMO_INF)))

    model.VARS = pyo.Set(initialize=all_vars, ordered=True)
    model.x = pyo.Var(model.VARS, bounds=_var_bounds, initialize=_var_init)

    # ── Per-unit linearised equalities ────────────────────────────────────
    model.unit_constraints = pyo.ConstraintList()
    for lin in linearizations:
        if lin.f0.size == 0:
            continue
        rhs_vec = lin.J @ lin.x0 - lin.f0  # shape (m,)
        for row_idx in range(lin.J.shape[0]):
            row = lin.J[row_idx, :]
            nonzero = np.flatnonzero(np.abs(row) > 0.0)
            if nonzero.size == 0:
                # Degenerate row: f0 must already be ~0 for feasibility.
                if abs(rhs_vec[row_idx]) > 1e-9:
                    raise ValueError(
                        f"Unit '{lin.unit_id}' row {row_idx} is structurally "
                        "infeasible (zero Jacobian row, non-zero residual)."
                    )
                continue
            expr = sum(
                float(row[j]) * model.x[lin.variables[j]] for j in nonzero
            )
            model.unit_constraints.add(expr == float(rhs_vec[row_idx]))

    # ── Connection equalities ─────────────────────────────────────────────
    model.connection_constraints = pyo.ConstraintList()
    for conn in flowsheet.connections:
        model.connection_constraints.add(
            model.x[conn.var_a] == model.x[conn.var_b]
        )

    # ── Flowsheet-level extra linear equalities ───────────────────────────
    model.extra_constraints = pyo.ConstraintList()
    for coeffs, rhs in flowsheet.extra_equalities:
        expr = sum(float(c) * model.x[v] for v, c in coeffs.items())
        model.extra_constraints.add(expr == float(rhs))

    # ── Trust region (per-unit, driven by each LinearizedModel.trust_region) ──
    if tr_multiplier > 0.0 and x_anchor is not None:
        model.trust_region_lo = pyo.ConstraintList()
        model.trust_region_hi = pyo.ConstraintList()
        for lin in linearizations:
            if lin.trust_region is None:
                continue
            radius = float(lin.trust_region) * float(tr_multiplier)
            for v in lin.variables:
                if v in x_anchor:
                    anchor = x_anchor[v]
                else:
                    # v1.4.0 audit N8 — pre-fix fallback was `x_anchor.get(v, 0.0)`,
                    # which anchored missing variables at 0. For pressures
                    # bounded at (1e4, 1e7) Pa this collapses the TR box to a
                    # region that is far outside feasibility. Use the
                    # variable's bound midpoint as a sane fallback.
                    lo, hi = bounds.get(v, (-_PYOMO_INF, _PYOMO_INF))
                    if lo > -_PYOMO_INF and hi < _PYOMO_INF:
                        anchor = 0.5 * (lo + hi)
                    else:
                        anchor = 0.0
                model.trust_region_lo.add(model.x[v] >= anchor - radius)
                model.trust_region_hi.add(model.x[v] <= anchor + radius)

    # ── Objective ─────────────────────────────────────────────────────────
    obj_terms: Dict[str, float] = {}

    if not getattr(flowsheet, "force_feasibility", False):
        # Collect per-unit linear OPEX contributions (feedstock cost, electricity, etc.)
        for lin in linearizations:
            for v, c in lin.objective_terms.items():
                obj_terms[v] = obj_terms.get(v, 0.0) + float(c)

        # Merge flowsheet-level objective overrides (objective_extra).
        for v, c in getattr(flowsheet, "objective_extra", {}).items():
            if v in model.x:
                obj_terms[v] = obj_terms.get(v, 0.0) + float(c)

    model.objective = pyo.Objective(
        expr=sum(c * model.x[v] for v, c in obj_terms.items()) if obj_terms else 0.0,
        sense=pyo.minimize,
    )

    # Stash metadata the SLP driver may want.
    model._objective_terms = obj_terms
    model._all_vars = list(all_vars)
    return model


def extract_solution(model: pyo.ConcreteModel) -> Dict[str, float]:
    """Pull variable values out of a solved Pyomo model."""
    return {v: float(pyo.value(model.x[v])) for v in model._all_vars}


def select_lp_solver(preferred: Optional[str] = None) -> pyo.SolverFactory:
    """Pick the first available LP solver (override with ``preferred``)."""
    candidates = [preferred] if preferred else ["glpk", "cbc", "appsi_highs", "highs"]
    for name in candidates:
        if not name:
            continue
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return solver
        except Exception:  # pragma: no cover - defensive
            continue
    raise RuntimeError(
        "No LP solver available. Install GLPK, CBC, or HiGHS "
        "(`pip install highspy`)."
    )
