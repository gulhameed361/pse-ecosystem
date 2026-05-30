"""Trust-Region Filter/Funnel driver (Eason & Biegler 2016; Hameed et al. 2021).

Wraps the SLP LP-subproblem loop with Filter or Funnel step acceptance in
place of the raw rho-threshold used by SLPDriver.  More robust for problems
where the predicted/actual decrease ratio is noisy or the linearisation
error is large (highly non-linear models).

Algorithm sketch
----------------
For each iteration k:
1.  Linearise all units at x_k (same as SLP).
2.  Solve LP subproblem with trust region Δ.
3.  Evaluate TRUE residuals at x_trial → infeasibility h_trial.
4.  Check filter/funnel acceptance:
    - Filter: (h_trial, f_trial) not dominated by any filter entry.
    - Funnel: h_trial ≤ β·φ_k  OR  f-type Armijo condition.
5.  If accepted: update x_k, add (h, f) to filter/funnel, update Δ via ρ.
6.  If rejected: shrink Δ; if Δ ≤ Δ_min, run feasibility restoration via NLP.
7.  Convergence: ‖x_{k+1} - x_k‖∞ < eps_x AND h < eps_f AND dkpi < eps_kpi.

The Filter and Funnel classes live in ``pse_ecosystem.solvers.trf`` (copied
from the PSE Ecosystem Extra/ folder).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pyomo.environ as pyo

from pse_ecosystem.core.contracts import (
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
from pse_ecosystem.solvers.slp import SLPConfig
from pse_ecosystem.solvers.trf.filter import Filter, FilterElement
from pse_ecosystem.solvers.trf.funnel import Funnel


@dataclass
class TRFConfig:
    """Tuning parameters for the Trust-Region Filter/Funnel driver."""

    max_iter: int = 60
    eps_x: float = 1e-4
    eps_f: float = 1e-4
    eps_kpi: float = 1e-3

    delta_init: float = 1.0
    delta_min: float = 1e-3
    delta_max: float = 1e3

    eta1: float = 0.1   # rho threshold to shrink Δ
    eta2: float = 0.75  # rho threshold to grow Δ
    gamma1: float = 0.5  # Δ shrink factor
    gamma2: float = 2.0  # Δ grow factor

    maximum_feasibility: float = 1e4
    """h_max for filter acceptance: steps with h > this are always rejected."""

    use_funnel: bool = False
    """If True, use Funnel instead of Filter globalization."""

    funnel_beta: float = 0.8
    funnel_kappa_f: float = 0.5
    funnel_kappa_r: float = 1.1
    funnel_alpha: float = 2.0   # switching exponent on θ_k (Wächter–Biegler)
    funnel_mu_s: float = 1e-2
    funnel_eta: float = 1e-4

    solver_name: Optional[str] = None
    verbose: bool = False


class TrustRegionDriver:
    """Filter/Funnel-globalised SLP for highly non-linear or ill-scaled flowsheets."""

    def __init__(
        self,
        flowsheet: BaseFlowsheet,
        config: Optional[TRFConfig] = None,
        slp_config: Optional[SLPConfig] = None,
    ):
        self.flowsheet = flowsheet
        self.config = config or TRFConfig()
        self.slp_config = slp_config or SLPConfig()
        self._solver = select_lp_solver(self.config.solver_name)

    def run(self, x0: Optional[Dict[str, float]] = None) -> SolveResult:
        cfg = self.config
        x_k = dict(x0) if x0 is not None else self.flowsheet.initial_guess()
        delta = cfg.delta_init
        history = []

        # Initialise Filter or Funnel
        f0_vec = self._concat_residuals(x_k)
        h0 = float(np.sum(np.abs(f0_vec))) if f0_vec.size else 0.0
        obj0 = self._objective_value(x_k)

        if cfg.use_funnel:
            globalization: object = Funnel(
                phi_init=max(h0, 1.0),
                f_best_init=obj0,
                phi_min=cfg.delta_min,
                kappa_f=cfg.funnel_kappa_f,
                kappa_r=cfg.funnel_kappa_r,
                alpha=cfg.funnel_alpha,
                beta=cfg.funnel_beta,
                mu_s=cfg.funnel_mu_s,
                eta=cfg.funnel_eta,
            )
        else:
            globalization = Filter()
            fe0 = FilterElement(objective=obj0, feasible=h0)
            globalization.addToFilter(fe0)

        prev_kpi = float("inf")
        last_objective = float("nan")
        last_lp_obj: Optional[float] = None

        for k in range(cfg.max_iter):
            guess = PrimalGuess(values=x_k, iteration=k)
            linearizations = [u.linearize(guess) for u in self.flowsheet.units]

            tr_mult = delta if self.slp_config.use_trust_region else 0.0
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
                term = SolverStatus.INFEASIBLE

            if term == SolverStatus.INFEASIBLE:
                delta = max(delta * cfg.gamma1, cfg.delta_min)
                if cfg.verbose:
                    print(f"[TRF] iter {k}: LP infeasible, Δ→{delta:.3g}")
                if delta <= cfg.delta_min + 1e-15:
                    return self._feasibility_restore(x_k, k, history, last_objective)
                continue
            elif term != SolverStatus.CONVERGED:
                return SolveResult(
                    status=term,
                    mode=SolveMode.TRUST_REGION,
                    x=x_k,
                    iterations=k,
                    history=history,
                    message=f"LP solver returned {term.value} at iteration {k}.",
                )

            x_trial = extract_solution(model)
            lp_obj = float(pyo.value(model.objective))

            # Evaluate TRUE residuals at trial point
            f_trial = self._concat_residuals(x_trial)
            h_trial = float(np.sum(np.abs(f_trial))) if f_trial.size else 0.0
            obj_trial = self._objective_value(x_trial)

            # Global step acceptance
            step_accepted = self._check_acceptance(
                globalization, cfg,
                h_old=h0, h_new=h_trial,
                f_old=obj0, f_new=obj_trial,
                delta=delta,
            )

            # Trust-region update via rho — predicted vs actual reduction measured
            # against the SAME linearised model m_k.  Predicted reduction is
            # m_k(x_k) - m_k(x_trial) = obj0 - lp_obj (the LP objective is the
            # linearisation about x_k, so it equals obj0 at the anchor to first
            # order); actual reduction is the true-objective decrease obj0 - obj_trial.
            predicted = obj0 - lp_obj
            actual = obj0 - obj_trial
            rho = actual / predicted if abs(predicted) > 1e-12 else 1.0

            # Capture step magnitude BEFORE assigning x_k = x_trial below; the
            # convergence guard at the end of the loop depends on it.
            taken_step_norm = self._inf_norm_diff(x_trial, x_k)

            if step_accepted:
                # Update filter/funnel with new point
                self._accept_update(globalization, cfg, h_trial, obj_trial,
                                    h_old=h0, f_old=obj0, delta=delta)
                x_k = x_trial
                h0 = h_trial
                obj0 = obj_trial

                # Eason & Biegler 2016 §3.2 trust-region schedule:
                #   ρ ≥ η₂        → grow Δ  (linearisation is excellent)
                #   η₁ ≤ ρ < η₂  → keep Δ  (linearisation is acceptable)
                #   ρ < η₁        → shrink Δ (linearisation is poor; step accepted
                #                              on filter grounds only)
                if rho >= cfg.eta2:
                    delta = min(delta * cfg.gamma2, cfg.delta_max)
                elif rho < cfg.eta1:
                    delta = max(delta * cfg.gamma1, cfg.delta_min)
            else:
                # Rejected: shrink trust region
                delta = max(delta * cfg.gamma1, cfg.delta_min)
                if cfg.verbose:
                    print(f"[TRF] iter {k}: step rejected (h={h_trial:.3g}), Δ→{delta:.3g}")
                if delta <= cfg.delta_min + 1e-15:
                    return self._feasibility_restore(x_k, k, history, last_objective)

            true_kpi = self._kpi_value(x_k)
            # Convergence is only meaningful for an accepted step; for a
            # rejected step force step_norm = +inf so the test below cannot
            # fire spuriously.
            step_norm = taken_step_norm if step_accepted else float("inf")

            history.append({
                "iteration": k,
                "objective": lp_obj,
                "step_norm": step_norm,
                "h": h_trial,
                "kpi": true_kpi,
                "trust_region": delta,
                "accepted": step_accepted,
            })

            if cfg.verbose:
                print(
                    f"[TRF] iter {k}: obj={lp_obj:.6g} h={h_trial:.3g} "
                    f"Δ={delta:.3g} {'ACC' if step_accepted else 'REJ'}"
                )

            dkpi = abs(true_kpi - prev_kpi) / max(1.0, abs(prev_kpi))
            if (
                step_accepted
                and step_norm < cfg.eps_x
                and h_trial < cfg.eps_f
                and dkpi < cfg.eps_kpi
            ):
                return SolveResult(
                    status=SolverStatus.CONVERGED,
                    mode=SolveMode.TRUST_REGION,
                    x=x_k,
                    kpis=self._aggregate_kpis(x_k),
                    iterations=k + 1,
                    objective=lp_obj,
                    history=history,
                    message="Trust-Region Filter converged.",
                )

            prev_kpi = true_kpi
            last_lp_obj = lp_obj
            last_objective = lp_obj

        return SolveResult(
            status=SolverStatus.MAX_ITER,
            mode=SolveMode.TRUST_REGION,
            x=x_k,
            kpis=self._aggregate_kpis(x_k),
            iterations=cfg.max_iter,
            objective=last_objective,
            history=history,
            message="Trust-Region driver hit max_iter.",
        )

    # ── Helper: check acceptance for Filter or Funnel ─────────────────────

    @staticmethod
    def _check_acceptance(
        glob, cfg: TRFConfig,
        h_old: float, h_new: float,
        f_old: float, f_new: float,
        delta: float,
    ) -> bool:
        if cfg.use_funnel:
            status = glob.classify_step(
                theta_old=h_old, theta_new=h_new,
                f_old=f_old, f_new=f_new,
                delta=delta,
            )
            return status in ("f", "theta", "theta-relax")
        else:
            fe = FilterElement(objective=f_new, feasible=h_new)
            return glob.isAcceptable(fe, cfg.maximum_feasibility)

    @staticmethod
    def _accept_update(
        glob, cfg: TRFConfig,
        h_new: float, f_new: float,
        h_old: float, f_old: float,
        delta: float,
    ) -> None:
        if cfg.use_funnel:
            status = glob.classify_step(
                theta_old=h_old, theta_new=h_new,
                f_old=f_old, f_new=f_new,
                delta=delta,
            )
            if status == "f":
                glob.accept_f(h_new, f_new)
            else:
                glob.accept_theta(h_new)
        else:
            fe = FilterElement(objective=f_new, feasible=h_new)
            glob.addToFilter(fe)

    # ── Feasibility restoration via NLP driver ────────────────────────────

    def _feasibility_restore(
        self,
        x_k: Dict[str, float],
        k: int,
        history: list,
        last_obj: float,
    ) -> SolveResult:
        try:
            from pse_ecosystem.solvers.ipopt_driver import NLPDriver

            slp_cfg = SLPConfig(
                max_iter=self.config.max_iter,
                eps_f=self.config.eps_f,
                eps_x=self.config.eps_x,
                eps_kpi=self.config.eps_kpi,
            )
            driver = NLPDriver(self.flowsheet, config=slp_cfg)
            result = driver.run(x0=x_k)
            result.mode = SolveMode.TRUST_REGION
            result.iterations += k
            result.history = history + result.history
            if result.converged:
                result.message = (
                    "Feasibility restored via NLP after TRF trust-region exhaustion."
                )
            return result
        except (RuntimeError, ValueError, ArithmeticError) as exc:
            # v1.4.0 audit N30 — pre-fix this was a bare `except Exception:`
            # that swallowed every error type including KeyboardInterrupt
            # and AttributeError. Narrow to numerical / runtime errors so
            # genuine programming bugs still propagate.
            return SolveResult(
                status=SolverStatus.INFEASIBLE,
                mode=SolveMode.TRUST_REGION,
                x=x_k,
                kpis=self._aggregate_kpis(x_k),
                iterations=k,
                objective=last_obj,
                history=history,
                message=(
                    f"TRF hit minimum trust-region; feasibility restoration "
                    f"failed: {type(exc).__name__}: {exc}"
                ),
            )

    # ── Internals ─────────────────────────────────────────────────────────

    def _concat_residuals(self, x: Dict[str, float]) -> np.ndarray:
        chunks = []
        for unit in self.flowsheet.units:
            r = np.asarray(unit.residual(x), dtype=float).reshape(-1)
            chunks.append(r)
        return np.concatenate(chunks) if chunks else np.zeros(0)

    def _objective_value(self, x: Dict[str, float]) -> float:
        total = 0.0
        for unit in self.flowsheet.units:
            for v, c in unit.objective_contribution(x).items():
                total += float(c) * float(x.get(v, 0.0))
        return total

    def _kpi_value(self, x: Dict[str, float]) -> float:
        kpis = self._aggregate_kpis(x)
        kpi_name = self.flowsheet.objective_kpi
        return kpis.get(kpi_name, self._objective_value(x))

    def _aggregate_kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        # v1.5.0.dev-AUDIT2 L2-6: delegate to the single source of truth.
        return self.flowsheet.aggregate_kpis(x)

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
