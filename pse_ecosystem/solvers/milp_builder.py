"""Pyomo MILP assembly for Mode 2 (technology choice).

v0 strategy
-----------
Each "candidate technology" is associated with a unit and a binary variable
``y_i ∈ {0, 1}``. When ``y_i = 0``, the unit's flow variables are forced to
zero via big-M coupling. When ``y_i = 1``, the unit operates with its
linearised constraints.

If every active candidate unit is linear (``is_exact=True``), the MILP solves
in a single shot. If a non-linear unit is selected, the Orchestrator falls
back to a sequential MILP→SLP decomposition: solve the linearised MILP, fix
the binary selection, and run the SLP loop on the resulting fixed-topology
flowsheet. This is intentionally simple for v0; OA / Benders / Branch-and-Cut
hooks come later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pyomo.environ as pyo

from pse_ecosystem.core.contracts import LinearizedModel
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.solvers.lp_builder import _bound_pair, _PYOMO_INF


@dataclass
class TechnologyChoice:
    """One binary technology candidate.

    ``big_M`` must dominate any feasible flow magnitude on every variable in
    ``flow_variables``; otherwise the y=0 branch silently clips the binary
    selection. The default of 1e9 covers all industrial-scale flowsheets we
    ship templates for (mass flows ≤ 1e3 kg/s, pressures ≤ 1e8 Pa, power
    ≤ 1e8 W). Lower it only when the variable bounds are known and tight,
    or when the LP relaxation becomes ill-conditioned at large M.
    """

    name: str
    unit_id: str
    flow_variables: List[str]
    big_M: float = 1e9
    fixed_cost: float = 0.0
    """Linear cost added to the objective when ``y = 1`` (e.g. annualised CAPEX)."""


def build_milp(
    linearizations: Iterable[LinearizedModel],
    flowsheet: BaseFlowsheet,
    technology_choices: List[TechnologyChoice],
    *,
    minimum_one_active: bool = True,
) -> pyo.ConcreteModel:
    """Build a Pyomo ConcreteModel MILP from linearisations + technology choices."""
    linearizations = list(linearizations)
    model = pyo.ConcreteModel(name=f"MILP::{flowsheet.name}")

    # ── Continuous variables (same as LP) ─────────────────────────────────
    all_vars = flowsheet.all_variables()
    bounds = flowsheet.aggregated_bounds()
    for lin in linearizations:
        for v, (lo, hi) in lin.bounds.items():
            if v in bounds:
                bounds[v] = (max(bounds[v][0], lo), min(bounds[v][1], hi))
            else:
                bounds[v] = (lo, hi)

    def _var_bounds(_m, name: str):  # pragma: no cover
        return _bound_pair(*bounds.get(name, (-_PYOMO_INF, _PYOMO_INF)))

    model.VARS = pyo.Set(initialize=all_vars, ordered=True)
    model.x = pyo.Var(model.VARS, bounds=_var_bounds, initialize=0.0)

    # ── Binary technology variables ───────────────────────────────────────
    tech_names = [t.name for t in technology_choices]
    model.TECHS = pyo.Set(initialize=tech_names, ordered=True)
    model.y = pyo.Var(model.TECHS, within=pyo.Binary)

    # Big-M coupling: x_v ≤ M · y for every flow variable owned by tech t.
    model.bigM_upper = pyo.ConstraintList()
    model.bigM_lower = pyo.ConstraintList()
    for tech in technology_choices:
        for v in tech.flow_variables:
            if v not in model.x:
                continue
            model.bigM_upper.add(model.x[v] <= tech.big_M * model.y[tech.name])
            model.bigM_lower.add(model.x[v] >= -tech.big_M * model.y[tech.name])

    if minimum_one_active and tech_names:
        model.at_least_one = pyo.Constraint(
            expr=sum(model.y[t] for t in tech_names) >= 1
        )

    # Map unit_id → (tech_name, big_M) so we can relax residual rows on the
    # technology binary. A unit not gated by any tech keeps its rows as
    # hard equalities.
    gating: Dict[str, tuple[str, float]] = {}
    for tech in technology_choices:
        gating[tech.unit_id] = (tech.name, float(tech.big_M))

    # ── Per-unit linearised equalities (big-M relaxed when gated) ────────
    import warnings as _warn
    model.unit_constraints = pyo.ConstraintList()
    model.unit_relax_lo = pyo.ConstraintList()
    model.unit_relax_hi = pyo.ConstraintList()
    for lin in linearizations:
        if lin.f0.size == 0:
            continue
        rhs_vec = lin.J @ lin.x0 - lin.f0
        gate = gating.get(lin.unit_id)
        for row_idx in range(lin.J.shape[0]):
            row = lin.J[row_idx, :]
            nonzero = np.flatnonzero(np.abs(row) > 0.0)
            if nonzero.size == 0:
                if abs(rhs_vec[row_idx]) > 1e-9:
                    if gate is None:
                        raise ValueError(
                            f"Unit '{lin.unit_id}' row {row_idx} infeasible."
                        )
                    # v1.4.0 audit N7 — gated units with a non-zero RHS on a
                    # zero Jacobian row were silently relaxed away under the
                    # y=0 branch. Surface a warning so the operator knows
                    # the linearisation has a structural issue at this point.
                    _warn.warn(
                        f"MILP gated unit {lin.unit_id!r} row {row_idx} has "
                        f"zero Jacobian but non-zero residual "
                        f"({rhs_vec[row_idx]:.3g}). Row is being relaxed away "
                        f"in the y=0 branch — verify the linearisation "
                        f"point is feasible for this technology.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                continue
            expr = sum(
                float(row[j]) * model.x[lin.variables[j]] for j in nonzero
            )
            rhs = float(rhs_vec[row_idx])
            if gate is None:
                model.unit_constraints.add(expr == rhs)
            else:
                tech_name, residual_M = gate
                # Sized so the constraint is fully slack when y = 0 — covers
                # any residual the linearisation could produce inside the
                # variable bounds.
                # v1.4.0 audit N6 — also incorporate the actual aggregated
                # bound widths on each non-zero column, so structural
                # variables with wide ranges (e.g. P ∈ [0, 1e8]) cannot
                # blow the row past the technology big-M.
                _bound_contrib = 0.0
                for j in nonzero:
                    v_name = lin.variables[j]
                    v_lo, v_hi = bounds.get(v_name, (0.0, residual_M))
                    v_lo = v_lo if v_lo > -_PYOMO_INF else 0.0
                    v_hi = v_hi if v_hi <  _PYOMO_INF else residual_M
                    _bound_contrib += abs(row[j]) * max(abs(v_lo), abs(v_hi))
                row_M = max(
                    residual_M,
                    abs(rhs) + _bound_contrib,
                    abs(rhs) + float(np.sum(np.abs(row)) * residual_M),
                    1.0,
                )
                model.unit_relax_hi.add(
                    expr - rhs <= row_M * (1 - model.y[tech_name])
                )
                model.unit_relax_lo.add(
                    expr - rhs >= -row_M * (1 - model.y[tech_name])
                )

    # ── Connections + extras (same as LP) ─────────────────────────────────
    model.connection_constraints = pyo.ConstraintList()
    for conn in flowsheet.connections:
        model.connection_constraints.add(model.x[conn.var_a] == model.x[conn.var_b])

    model.extra_constraints = pyo.ConstraintList()
    for coeffs, rhs in flowsheet.extra_equalities:
        expr = sum(float(c) * model.x[v] for v, c in coeffs.items())
        model.extra_constraints.add(expr == float(rhs))

    # ── Objective ─────────────────────────────────────────────────────────
    obj_terms: Dict[str, float] = {}
    for lin in linearizations:
        for v, c in lin.objective_terms.items():
            obj_terms[v] = obj_terms.get(v, 0.0) + float(c)

    expr = sum(c * model.x[v] for v, c in obj_terms.items()) if obj_terms else 0.0
    expr = expr + sum(t.fixed_cost * model.y[t.name] for t in technology_choices)
    model.objective = pyo.Objective(expr=expr, sense=pyo.minimize)

    model._objective_terms = obj_terms
    model._all_vars = list(all_vars)
    model._tech_names = tech_names
    return model


def extract_milp_solution(model: pyo.ConcreteModel) -> tuple[Dict[str, float], Dict[str, bool]]:
    x = {v: float(pyo.value(model.x[v])) for v in model._all_vars}
    y = {t: bool(round(float(pyo.value(model.y[t])))) for t in model._tech_names}
    return x, y


def select_milp_solver(preferred: Optional[str] = None) -> pyo.SolverFactory:
    candidates = [preferred] if preferred else ["appsi_highs", "highs", "cbc", "glpk"]
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
        "No MILP solver available. Install CBC, GLPK, or HiGHS "
        "(`pip install highspy`)."
    )
