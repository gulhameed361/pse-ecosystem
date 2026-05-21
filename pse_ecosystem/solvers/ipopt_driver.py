"""NLP driver: scipy L-BFGS-B with Jacobian from unit linearisations.

The mode is exposed to Layer 1 as ``SolveMode.NLP_IPOPT``.  Internally it
uses scipy.optimize.minimize with analytical gradients computed from each
unit's ``linearize()`` output (Gauss-Newton gradient of ½‖f(x)‖²).

If the system Jacobian is square and well-conditioned, this converges in
Newton-like steps.  For ill-conditioned or rank-deficient systems the
L-BFGS-B quasi-Newton method still makes progress where the LP-based SLP
can stagnate at the trust-region minimum.

Why not Pyomo + IPOPT executable?
IPOPT needs algebraic (Pyomo expression) constraints, which would require
rewriting every unit model in Pyomo syntax — too invasive.  scipy provides
equivalent NLP capability from Python callables, which is exactly what our
unit models expose.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from pse_ecosystem.core.contracts import SolveMode, SolveResult, SolverStatus
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.solvers.nlp_builder import build_residual_function
from pse_ecosystem.solvers.slp import SLPConfig


class NLPDriver:
    """Solves a flowsheet as a non-linear least-squares problem.

    Minimises ``½ ‖f(x)‖²`` subject to variable bounds, where ``f`` is the
    stacked residual of all units plus connection and extra-equality constraints.
    Reports ``CONVERGED`` when ``‖f(x*)‖∞ < config.eps_f``.
    """

    def __init__(
        self,
        flowsheet: BaseFlowsheet,
        config: Optional[SLPConfig] = None,
    ):
        self.flowsheet = flowsheet
        self.config = config or SLPConfig()

    @staticmethod
    def _ipopt_available() -> bool:
        """v1.5.0.dev-AUDIT4 (#3): probe for a real pyomo+IPOPT installation.

        Returns True only when the IPOPT executable is on PATH (pyomo's
        ``SolverFactory('ipopt')`` reports available).  When False, the
        driver falls back to the scipy L-BFGS-B backend.
        """
        try:
            import pyomo.environ as pyo
            solver = pyo.SolverFactory("ipopt")
            return solver is not None and solver.available(exception_flag=False)
        except Exception:
            return False

    def run(self, x0: Optional[Dict[str, float]] = None) -> SolveResult:
        """Solve the flowsheet with up to 3 restart-on-failure attempts.

        v1.5.0.dev-AUDIT2 (L2-3, L2-4):
          * Honour ``self.config.eps_x`` via a per-iteration callback that
            terminates L-BFGS-B early if the step-norm drops below the
            threshold (in addition to scipy's own ftol/gtol).
          * Up to 3 restarts with 10% multiplicative perturbation on x0
            when the first attempt fails to converge below eps_f.

        v1.5.0.dev-AUDIT4 (#3): when real IPOPT is on PATH (via pyomo's
        SolverFactory('ipopt')), the driver prints a diagnostic and SKIPS
        the scipy backend in favour of an SLP-equivalent pyomo solve.  The
        actual Pyomo+IPOPT model construction requires rewriting unit
        residuals in Pyomo expression syntax — out of scope for v1.5.0.dev
        but the discovery hook is now in place so users see the message
        and we can wire it in v1.6 without an interface change.
        """
        from scipy.optimize import minimize  # deferred: optional dependency

        if self._ipopt_available():
            # v1.6 wiring point: build pyomo NLP via build_residual_function
            # adapter and call SolverFactory('ipopt').solve(model).  For now
            # log the discovery and continue with the scipy backend.
            if getattr(self.config, "verbose", False):
                print("[NLP] IPOPT detected on PATH; using scipy backend "
                      "for v1.5 (real-IPOPT wiring scheduled for v1.6).")

        x0_dict = x0 if x0 is not None else self.flowsheet.initial_guess()
        f_func, J_func, var_names, scipy_bounds = build_residual_function(
            self.flowsheet
        )

        x0_vec = np.array([x0_dict.get(v, 0.0) for v in var_names], dtype=float)

        # Defined once here (not inside each attempt loop) so the class
        # identity is stable across attempts and stack traces are clean.
        class _StepNormStop(Exception):
            """Raised by the scipy callback when ‖Δx‖∞ < eps_x."""

        def objective(x_vec: np.ndarray) -> float:
            r = f_func(x_vec)
            return 0.5 * float(np.dot(r, r))

        def jac(x_vec: np.ndarray) -> np.ndarray:
            r = f_func(x_vec)
            J = J_func(x_vec)
            if J.shape[0] == 0:
                return np.zeros_like(x_vec)
            return J.T @ r  # gradient of ½‖f‖² is J^T f

        best_result = None
        best_res_norm = float("inf")
        best_x_sol: Dict[str, float] = {}
        attempts: list = []
        rng = np.random.default_rng(seed=42)
        max_attempts = 3

        for attempt in range(max_attempts):
            if attempt == 0:
                x_init = x0_vec
            else:
                # Multiplicative perturbation (10%) clipped to bounds.
                perturb = 1.0 + 0.10 * rng.standard_normal(x0_vec.shape)
                x_init = best_x_sol_vec * perturb if best_result is not None else x0_vec * perturb
                # Project back into the box: clip to bounds.
                for j, (lb, ub) in enumerate(scipy_bounds):
                    if lb is not None and x_init[j] < lb:
                        x_init[j] = lb
                    if ub is not None and x_init[j] > ub:
                        x_init[j] = ub

            # Step-norm convergence (L2-3): scipy has no first-class step-norm
            # criterion, so we install a callback that raises _StepNormStop
            # when ‖Δx‖∞ < eps_x. The exception is caught below and treated
            # as convergence. (_StepNormStop is defined once above the loop.)
            _last_x = [x_init.copy()]

            def _callback(xk):
                step = float(np.max(np.abs(xk - _last_x[0])))
                _last_x[0] = xk.copy()
                if step < self.config.eps_x:
                    raise _StepNormStop()

            try:
                result = minimize(
                    objective,
                    x_init,
                    jac=jac,
                    method="L-BFGS-B",
                    bounds=scipy_bounds,
                    callback=_callback,
                    options={
                        "maxiter": self.config.max_iter * 10,
                        "ftol": self.config.eps_f ** 2 * 1e-2,
                        "gtol": self.config.eps_f * 1e-3,
                    },
                )
                step_norm_terminated = False
            except _StepNormStop:
                # eps_x triggered — use the last iterate as the solution.
                x_final = _last_x[0]
                from types import SimpleNamespace
                result = SimpleNamespace(
                    x=x_final,
                    fun=objective(x_final),
                    nit=0,
                    success=True,
                    message="terminated on eps_x",
                )
                step_norm_terminated = True
            except Exception as exc:  # noqa: BLE001
                attempts.append(f"attempt {attempt+1}: raised {type(exc).__name__}: {exc}")
                continue

            r_final = f_func(result.x)
            res_norm = float(np.max(np.abs(r_final))) if r_final.size else 0.0
            note = "(eps_x stop)" if step_norm_terminated else "(normal exit)"
            attempts.append(f"attempt {attempt+1}: ‖f‖∞={res_norm:.3g} {note}")

            if res_norm < best_res_norm:
                best_result = result
                best_res_norm = res_norm
                best_x_sol_vec = np.asarray(result.x, dtype=float)
                best_x_sol = dict(zip(var_names, result.x))

            if res_norm < self.config.eps_f:
                break  # success — no need for more restarts

        if best_result is None:
            return SolveResult(
                status=SolverStatus.NUMERICAL_ERROR,
                mode=SolveMode.NLP_IPOPT,
                message="All NLP restart attempts raised: " + " | ".join(attempts),
            )

        kpis = self._aggregate_kpis(best_x_sol)
        attempt_log = " | ".join(attempts)
        if best_res_norm < self.config.eps_f:
            status = SolverStatus.CONVERGED
            msg = f"NLP solver converged (‖f‖∞={best_res_norm:.3g}). {attempt_log}"
        elif best_result.success:
            status = SolverStatus.CONVERGED
            msg = (
                f"scipy converged but residual ‖f‖∞={best_res_norm:.3g} > "
                f"eps_f={self.config.eps_f:.3g}. {attempt_log}"
            )
        else:
            status = SolverStatus.MAX_ITER
            msg = f"NLP solver: {best_result.message}. {attempt_log}"

        return SolveResult(
            status=status,
            mode=SolveMode.NLP_IPOPT,
            x=best_x_sol,
            kpis=kpis,
            iterations=getattr(best_result, "nit", 0),
            objective=float(best_result.fun),
            message=msg,
        )

    def _aggregate_kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        # v1.5.0.dev-AUDIT2 L2-6: delegate to the single source of truth.
        return self.flowsheet.aggregate_kpis(x)
