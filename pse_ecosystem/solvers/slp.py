"""Successive Linearization driver.

Layer 2's iterative bridge between LP solvers and non-linear unit models.
The full algorithm is described in ``docs/ARCHITECTURE.md``; the short
version is::

    for k in 0 .. max_iter-1:
        ask each unit for its LinearizedModel at x_k        # Layer 3 round
        build & solve a Pyomo LP using those linearisations # Layer 2 round
        evaluate the TRUE residual using each unit again    # Layer 3 round
        check convergence; if not, update trust region; loop

The driver never imports any concrete unit module — it only touches units
through the abstract ``linearize`` / ``evaluate`` methods that live on the
contract surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pyomo.environ as pyo

from pse_ecosystem.core.contracts import (
    LinearizedModel,
    PrimalGuess,
    SolveMode,
    SolveResult,
    SolverStatus,
)
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.solvers.lp_builder import (
    build_lp,
    extract_solution,
    select_lp_solver,
)


@dataclass
class TearStreamConfig:
    """Wegstein-accelerated tear stream for recycle loops.

    Declare one entry per recycle connection.  The SLP driver applies the
    Wegstein update after each LP solve, damping the step on the torn variable
    to improve convergence of recycle loops.

    Parameters
    ----------
    var_name:
        Name of the variable being torn (e.g. ``"reactor.F_Tol_in"``).
        This is the recycle *destination* — the variable whose value is
        iterated until it matches the upstream source.
    connected_to:
        Name of the upstream variable that feeds the torn stream.
        Used for convergence reporting only; the LP enforces the connection
        via a ``Connection`` equality in the flowsheet.
    q_min, q_max:
        Wegstein damping bounds.  ``q = 0`` is direct substitution (fast but
        may oscillate); ``q < 0`` is over-relaxation.  Default ``[-5, 0]``
        allows mild acceleration.
    """
    var_name: str
    connected_to: str = ""
    q_min: float = -5.0
    q_max: float = 0.0
    _x_prev: float = field(default=0.0, repr=False)
    _g_prev: float = field(default=0.0, repr=False)
    _initialised: bool = field(default=False, repr=False)


@dataclass
class SLPConfig:
    """Tuning knobs for the SLP loop.

    Trust regions are unit-driven: each non-linear unit may set
    ``LinearizedModel.trust_region`` to its preferred radius (in variable
    units). The driver multiplies that radius by its own scalar
    ``Δ ∈ [trust_region_min, trust_region_max]``, which it adapts based on
    the actual-vs-predicted-decrease ratio. Setting
    ``use_trust_region=False`` disables the mechanism for both the driver
    and the LP builder, regardless of unit hints.
    """

    max_iter: int = 50
    eps_x: float = 1e-4
    """Relative step-norm tolerance: ‖x_{k+1} - x_k‖∞ / max(1, ‖x_k‖∞)."""
    eps_f: float = 1e-4
    """Absolute residual tolerance on the *true* non-linear residual."""
    eps_kpi: float = 1e-3
    """Relative tolerance on the KPI between successive iterations."""

    trust_region_init: float = 1.0
    """Starting multiplier on each unit's trust-region radius."""
    trust_region_min: float = 1e-2
    trust_region_max: float = 1e2
    rho_shrink: float = 0.25
    rho_grow: float = 0.75

    use_trust_region: bool = False
    """Default off; turn on when units supply meaningful TR hints and the
    flowsheet has aggressive non-linearities."""

    solver_name: Optional[str] = None
    """Pyomo solver factory name. ``None`` ⇒ first available LP solver."""

    verbose: bool = False

    tear_streams: List["TearStreamConfig"] = field(default_factory=list)
    """Wegstein-accelerated tear streams for recycle loops.  Leave empty
    (default) when the flowsheet has no recycle connections."""


@dataclass
class _IterationLog:
    iteration: int
    objective: float
    step_norm: float
    residual_norm: float
    kpi: float
    trust_region: float


class SLPDriver:
    """Drives the SLP loop against a fixed-topology flowsheet."""

    def __init__(self, flowsheet: BaseFlowsheet, config: Optional[SLPConfig] = None):
        self.flowsheet = flowsheet
        self.config = config or SLPConfig()
        self._solver = select_lp_solver(self.config.solver_name)

    # ── Public entry ──────────────────────────────────────────────────────

    def run(self, x0: Optional[Dict[str, float]] = None) -> SolveResult:
        # Reset Wegstein state so repeated run() calls start fresh.
        for ts in self.config.tear_streams:
            ts._initialised = False
            ts._x_prev = 0.0
            ts._g_prev = 0.0

        x_k = dict(x0) if x0 is not None else self.flowsheet.initial_guess()
        history: List[Dict[str, float]] = []

        delta = self.config.trust_region_init
        prev_kpi = float("inf")
        last_lp_obj: Optional[float] = None
        last_objective: float = float("nan")

        for k in range(self.config.max_iter):
            # ── Layer-3 round: linearise around x_k ───────────────────────
            guess = PrimalGuess(values=x_k, iteration=k)
            linearizations = [u.linearize(guess) for u in self.flowsheet.units]

            # Linear short-circuit on the very first iteration.
            if k == 0 and all(lin.is_exact for lin in linearizations):
                return self._solve_once(linearizations, x_k, single_shot=True)

            # ── Layer-2 round: build + solve LP ───────────────────────────
            tr_mult = delta if self.config.use_trust_region else 0.0
            model = build_lp(
                linearizations,
                self.flowsheet,
                x_anchor=x_k,
                tr_multiplier=tr_mult,
            )
            try:
                res = self._solver.solve(model, tee=False)
                term = self._termination(res)
            except RuntimeError:
                # Newer Pyomo+HiGHS appsi raises rather than returning a
                # status object when no feasible solution exists.
                term = SolverStatus.INFEASIBLE

            if term == SolverStatus.INFEASIBLE:
                # Trust region likely too tight — shrink and retry.
                delta = max(delta * 0.5, self.config.trust_region_min)
                if self.config.verbose:
                    print(f"[SLP] iter {k}: LP infeasible, shrinking Δ → {delta:.3g}")
                if delta <= self.config.trust_region_min + 1e-15:
                    return SolveResult(
                        status=SolverStatus.INFEASIBLE,
                        mode=SolveMode.FIXED_LP,
                        x=x_k,
                        kpis=self._aggregate_kpis(x_k),
                        iterations=k,
                        objective=last_objective,
                        history=[h for h in history],
                        message="LP infeasible at minimum trust-region radius.",
                    )
                continue
            elif term != SolverStatus.CONVERGED:
                return SolveResult(
                    status=term,
                    mode=SolveMode.FIXED_LP,
                    x=x_k,
                    iterations=k,
                    objective=last_objective,
                    history=history,
                    message=f"LP solver returned {term.value} at iteration {k}.",
                )

            x_kp1 = extract_solution(model)
            lp_obj = float(pyo.value(model.objective))

            # ── Wegstein tear-stream update (recycle acceleration) ────────
            for ts in self.config.tear_streams:
                g_new = float(x_kp1.get(ts.var_name, 0.0))
                if not ts._initialised:
                    ts._x_prev = float(x_k.get(ts.var_name, 0.0))
                    ts._g_prev = g_new
                    ts._initialised = True
                else:
                    dg = g_new - ts._g_prev
                    dx = g_new - ts._x_prev
                    if abs(dg - dx) > 1e-12:
                        q = np.clip(dg / (dg - dx), ts.q_min, ts.q_max)
                    else:
                        q = 0.0  # direct substitution
                    x_kp1[ts.var_name] = (1.0 - q) * g_new + q * ts._x_prev
                    ts._g_prev = g_new
                    ts._x_prev = x_kp1[ts.var_name]

            # ── Layer-3 round: evaluate the TRUE non-linear residual ──────
            true_residual = self._concat_residuals(x_kp1)
            true_kpi = self._objective_value(linearizations, x_kp1)

            step = self._inf_norm_diff(x_kp1, x_k)
            res_norm = (
                float(np.max(np.abs(true_residual))) if true_residual.size else 0.0
            )
            dkpi = abs(true_kpi - prev_kpi) / max(1.0, abs(prev_kpi))

            log_entry = _IterationLog(
                iteration=k,
                objective=lp_obj,
                step_norm=step,
                residual_norm=res_norm,
                kpi=true_kpi,
                trust_region=delta,
            )
            history.append(log_entry.__dict__)
            if self.config.verbose:
                print(
                    f"[SLP] iter {k}: obj={lp_obj:.6g} step={step:.3g} "
                    f"‖f‖={res_norm:.3g} Δ={delta:.3g}"
                )

            # ── Convergence test ─────────────────────────────────────────
            if (
                step < self.config.eps_x
                and res_norm < self.config.eps_f
                and dkpi < self.config.eps_kpi
            ):
                return SolveResult(
                    status=SolverStatus.CONVERGED,
                    mode=SolveMode.FIXED_LP,
                    x=x_kp1,
                    kpis=self._aggregate_kpis(x_kp1),
                    iterations=k + 1,
                    objective=lp_obj,
                    history=history,
                    message="SLP converged.",
                )

            # ── Trust-region update (predicted vs actual decrease) ───────
            if last_lp_obj is not None:
                predicted_decrease = last_lp_obj - lp_obj
                actual_decrease = prev_kpi - true_kpi
                if predicted_decrease > 1e-12:
                    rho = actual_decrease / predicted_decrease
                else:
                    rho = 1.0
                if rho < self.config.rho_shrink:
                    delta = max(delta * 0.5, self.config.trust_region_min)
                elif rho > self.config.rho_grow:
                    delta = min(delta * 2.0, self.config.trust_region_max)

            x_k = x_kp1
            prev_kpi = true_kpi
            last_lp_obj = lp_obj
            last_objective = lp_obj

        return SolveResult(
            status=SolverStatus.MAX_ITER,
            mode=SolveMode.FIXED_LP,
            x=x_k,
            kpis=self._aggregate_kpis(x_k),
            iterations=self.config.max_iter,
            objective=last_objective,
            history=history,
            message="SLP hit max_iter without converging.",
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _solve_once(
        self,
        linearizations: List[LinearizedModel],
        x_seed: Dict[str, float],
        *,
        single_shot: bool,
    ) -> SolveResult:
        """One-shot LP solve when every unit is exact (Mode-1 fast path)."""
        model = build_lp(linearizations, self.flowsheet, x_anchor=x_seed)
        try:
            res = self._solver.solve(model, tee=False)
            term = self._termination(res)
        except RuntimeError:
            term = SolverStatus.INFEASIBLE
        if term != SolverStatus.CONVERGED:
            return SolveResult(
                status=term,
                mode=SolveMode.FIXED_LP,
                iterations=1,
                message=f"LP returned {term.value}.",
            )
        x = extract_solution(model)
        obj = float(pyo.value(model.objective))
        return SolveResult(
            status=SolverStatus.CONVERGED,
            mode=SolveMode.FIXED_LP,
            x=x,
            kpis=self._aggregate_kpis(x),
            iterations=1,
            objective=obj,
            message="Linear flowsheet solved in a single LP iteration.",
        )

    def _concat_residuals(self, x: Dict[str, float]) -> np.ndarray:
        """Stack each unit's true (non-linear) residual into a single vector."""
        chunks = []
        for unit in self.flowsheet.units:
            r = np.asarray(unit.residual(x), dtype=float).reshape(-1)
            chunks.append(r)
        return np.concatenate(chunks) if chunks else np.zeros(0)

    def _aggregate_kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        kpis: Dict[str, float] = {}
        for unit in self.flowsheet.units:
            for k, v in unit.kpis(x).items():
                kpis[k] = kpis.get(k, 0.0) + float(v)
        return kpis

    @staticmethod
    def _objective_value(
        linearizations: List[LinearizedModel], x: Dict[str, float]
    ) -> float:
        total = 0.0
        for lin in linearizations:
            for v, c in lin.objective_terms.items():
                total += float(c) * float(x.get(v, 0.0))
        return total

    @staticmethod
    def _inf_norm_diff(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a:
            return 0.0
        keys = a.keys() | b.keys()
        diff = max(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)
        scale = max(1.0, max(abs(a.get(k, 0.0)) for k in keys))
        return diff / scale

    @staticmethod
    def _termination(pyomo_results) -> SolverStatus:
        from pyomo.opt import TerminationCondition as TC

        try:
            tc = pyomo_results.solver.termination_condition
        except AttributeError:
            return SolverStatus.NUMERICAL_ERROR
        if tc in (TC.optimal, TC.locallyOptimal, TC.feasible):
            return SolverStatus.CONVERGED
        if tc in (TC.infeasible, TC.infeasibleOrUnbounded):
            return SolverStatus.INFEASIBLE
        if tc == TC.unbounded:
            return SolverStatus.UNBOUNDED
        if tc == TC.maxIterations:
            return SolverStatus.MAX_ITER
        return SolverStatus.NUMERICAL_ERROR
