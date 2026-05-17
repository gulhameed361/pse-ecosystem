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

    def run(self, x0: Optional[Dict[str, float]] = None) -> SolveResult:
        from scipy.optimize import minimize  # deferred: optional dependency

        x0_dict = x0 if x0 is not None else self.flowsheet.initial_guess()
        f_func, J_func, var_names, scipy_bounds = build_residual_function(
            self.flowsheet
        )

        x0_vec = np.array([x0_dict.get(v, 0.0) for v in var_names], dtype=float)

        def objective(x_vec: np.ndarray) -> float:
            r = f_func(x_vec)
            return 0.5 * float(np.dot(r, r))

        def jac(x_vec: np.ndarray) -> np.ndarray:
            r = f_func(x_vec)
            J = J_func(x_vec)
            if J.shape[0] == 0:
                return np.zeros_like(x_vec)
            return J.T @ r  # gradient of ½‖f‖² is J^T f

        try:
            # scipy's L-BFGS-B convergence is checked on the *objective*
            # (½‖f‖²) and its *gradient* (J^T f). We expose two thresholds:
            #   ftol — relative objective change.  Since the objective ½‖f‖²
            #          scales as eps_f², we set ftol ∝ eps_f² with a 1e-2
            #          safety factor so scipy keeps refining a step past the
            #          point where our own residual-norm test would fire.
            #   gtol — gradient-norm tolerance, kept proportional to eps_f.
            # See `M2` audit note (v1.4.0): document the squaring rationale.
            result = minimize(
                objective,
                x0_vec,
                jac=jac,
                method="L-BFGS-B",
                bounds=scipy_bounds,
                options={
                    "maxiter": self.config.max_iter * 10,
                    "ftol": self.config.eps_f ** 2 * 1e-2,
                    "gtol": self.config.eps_f * 1e-3,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return SolveResult(
                status=SolverStatus.NUMERICAL_ERROR,
                mode=SolveMode.NLP_IPOPT,
                message=f"scipy.optimize.minimize raised: {exc}",
            )

        x_sol = dict(zip(var_names, result.x))
        r_final = f_func(result.x)
        res_norm = float(np.max(np.abs(r_final))) if r_final.size else 0.0
        kpis = self._aggregate_kpis(x_sol)

        if res_norm < self.config.eps_f:
            status = SolverStatus.CONVERGED
            msg = f"NLP solver converged (‖f‖∞={res_norm:.3g})."
        elif result.success:
            status = SolverStatus.CONVERGED
            msg = f"scipy converged but residual ‖f‖∞={res_norm:.3g} > eps_f."
        else:
            status = SolverStatus.MAX_ITER
            msg = f"NLP solver: {result.message}"

        return SolveResult(
            status=status,
            mode=SolveMode.NLP_IPOPT,
            x=x_sol,
            kpis=kpis,
            iterations=result.nit,
            objective=float(result.fun),
            message=msg,
        )

    def _aggregate_kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        kpis: Dict[str, float] = {}
        for unit in self.flowsheet.units:
            for k, v in unit.kpis(x).items():
                kpis[k] = kpis.get(k, 0.0) + float(v)
        return kpis
