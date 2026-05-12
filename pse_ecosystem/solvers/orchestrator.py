"""Top-level solver dispatcher.

The Orchestrator is the entry point Layer 1 calls into. It picks one of two
strategies based on the user-selected :class:`SolveMode`:

    ``FIXED_LP``      — fixed flowsheet topology. Delegates to
                        :class:`SLPDriver`, which short-circuits to a single
                        LP solve when every unit is linear and otherwise
                        runs the Successive-Linearization loop.

    ``FLEXIBLE_MILP`` — technology choice via binaries. Solves a Pyomo MILP
                        built from linearisations evaluated at the initial
                        guess. If any selected unit is non-linear, the
                        Orchestrator then refines operations via SLP on the
                        topology fixed by the MILP solution
                        (sequential MILP → SLP decomposition).

The Orchestrator is the highest layer-2 component and the one piece of
Layer 2 that needs to know about both LP and MILP paths. It still does not
know any physics — it talks to units only through ``LinearizedModel`` and
``UnitResponse``.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Dict, List, Optional

import pyomo.environ as pyo

from pse_ecosystem.core.contracts import (
    PrimalGuess,
    SolveMode,
    SolveResult,
    SolverStatus,
)
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.solvers.milp_builder import (
    TechnologyChoice,
    build_milp,
    extract_milp_solution,
    select_milp_solver,
)
from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver


class Orchestrator:
    """Mode 1 / Mode 2 dispatcher.

    Parameters
    ----------
    flowsheet:
        The :class:`BaseFlowsheet` to solve.
    mode:
        :data:`SolveMode.FIXED_LP` or :data:`SolveMode.FLEXIBLE_MILP`.
    slp_config:
        SLP tuning. Used both for Mode 1 and the SLP refinement step of
        Mode 2.
    technology_choices:
        Required for ``FLEXIBLE_MILP``. Each entry binds a binary technology
        decision to a unit and its flow variables.
    """

    def __init__(
        self,
        flowsheet: BaseFlowsheet,
        mode: SolveMode,
        *,
        slp_config: Optional[SLPConfig] = None,
        technology_choices: Optional[List[TechnologyChoice]] = None,
    ):
        self.flowsheet = flowsheet
        self.mode = mode
        self.slp_config = slp_config or SLPConfig()
        self.technology_choices = technology_choices or []

        if mode == SolveMode.FLEXIBLE_MILP and not self.technology_choices:
            raise ValueError(
                "FLEXIBLE_MILP requires technology_choices defining the "
                "binary candidates."
            )

    # ── Entry point ─────────────────────────────────────────────────────────

    def solve(self) -> SolveResult:
        if self.mode == SolveMode.FIXED_LP:
            return self._solve_fixed()
        if self.mode == SolveMode.FLEXIBLE_MILP:
            return self._solve_flexible()
        if self.mode == SolveMode.NLP_IPOPT:
            return self._solve_nlp()
        if self.mode == SolveMode.TRUST_REGION:
            return self._solve_trust_region()
        if self.mode == SolveMode.ADAPTIVE:
            return self._solve_adaptive()
        raise ValueError(f"Unknown mode {self.mode!r}")

    # ── Mode 1: Fixed topology ─────────────────────────────────────────────

    def _solve_fixed(self) -> SolveResult:
        driver = SLPDriver(self.flowsheet, self.slp_config)
        return driver.run()

    # ── Mode 2: Flexible technology choice ─────────────────────────────────

    def _solve_flexible(self) -> SolveResult:
        x0 = self.flowsheet.initial_guess()
        guess = PrimalGuess(values=x0, iteration=0)
        linearizations = [u.linearize(guess) for u in self.flowsheet.units]

        model = build_milp(
            linearizations,
            self.flowsheet,
            self.technology_choices,
        )
        solver = select_milp_solver(self.slp_config.solver_name)
        results = solver.solve(model, tee=False)
        term = self._milp_termination(results)
        if term != SolverStatus.CONVERGED:
            return SolveResult(
                status=term,
                mode=SolveMode.FLEXIBLE_MILP,
                iterations=1,
                message=f"MILP returned {term.value}.",
            )

        x_milp, y_milp = extract_milp_solution(model)
        milp_obj = float(pyo.value(model.objective))

        # Identify which units are *active* under the MILP selection.
        active_unit_ids = self._active_unit_ids(y_milp)
        active_units = [u for u in self.flowsheet.units if u.unit_id in active_unit_ids]

        # If the active mix is all-linear we are already optimal — return.
        if all(getattr(u, "is_linear", False) for u in active_units):
            return SolveResult(
                status=SolverStatus.CONVERGED,
                mode=SolveMode.FLEXIBLE_MILP,
                x=x_milp,
                kpis=self._aggregate_kpis(x_milp),
                iterations=1,
                objective=milp_obj,
                technology_selection=y_milp,
                message="MILP solved as a single shot (all selected units linear).",
            )

        # Otherwise run SLP on the topology fixed by the MILP.
        refined_flowsheet = self._fix_topology(y_milp)
        slp_config = replace(self.slp_config)  # shallow copy
        driver = SLPDriver(refined_flowsheet, slp_config)
        slp_result = driver.run(x0=x_milp)

        # Re-tag the result with Mode 2 metadata.
        slp_result.mode = SolveMode.FLEXIBLE_MILP
        slp_result.technology_selection = y_milp
        if slp_result.status == SolverStatus.CONVERGED:
            slp_result.message = (
                "MILP selected technology mix; SLP refined operations to "
                "convergence on the fixed topology."
            )
        return slp_result

    # ── Mode 3: Full NLP via scipy (exposed as NLP_IPOPT) ─────────────────

    def _solve_nlp(self) -> SolveResult:
        from pse_ecosystem.solvers.ipopt_driver import NLPDriver

        driver = NLPDriver(self.flowsheet, config=self.slp_config)
        return driver.run()

    # ── Mode 4: Trust-Region Filter/Funnel ────────────────────────────────

    def _solve_trust_region(self) -> SolveResult:
        from pse_ecosystem.solvers.trust_region_driver import TrustRegionDriver, TRFConfig

        cfg = TRFConfig(
            max_iter=self.slp_config.max_iter,
            eps_x=self.slp_config.eps_x,
            eps_f=self.slp_config.eps_f,
            eps_kpi=self.slp_config.eps_kpi,
            verbose=self.slp_config.verbose,
            solver_name=self.slp_config.solver_name,
        )
        driver = TrustRegionDriver(self.flowsheet, config=cfg, slp_config=self.slp_config)
        return driver.run()

    # ── Mode adaptive: SLP → NLP → TRF cascade ────────────────────────────

    def _solve_adaptive(self) -> SolveResult:
        # Stage 1: SLP (fast, LP-based)
        slp_result = self._solve_fixed()
        if slp_result.converged:
            return slp_result

        # Stage 2: NLP (scipy L-BFGS-B; warm-starts from SLP solution)
        try:
            from pse_ecosystem.solvers.ipopt_driver import NLPDriver

            driver = NLPDriver(self.flowsheet, config=self.slp_config)
            x_warm = slp_result.x if slp_result.x else None
            nlp_result = driver.run(x0=x_warm)
            nlp_result.message = f"[ADAPTIVE stage 2/3] {nlp_result.message}"
            if nlp_result.converged:
                return nlp_result
        except Exception:  # noqa: BLE001
            pass  # NLP unavailable — proceed directly to TRF

        # Stage 3: Trust-Region (most robust — uses filter globalization)
        from pse_ecosystem.solvers.trust_region_driver import TrustRegionDriver, TRFConfig

        cfg = TRFConfig(
            max_iter=self.slp_config.max_iter,
            eps_x=self.slp_config.eps_x,
            eps_f=self.slp_config.eps_f,
            eps_kpi=self.slp_config.eps_kpi,
            verbose=self.slp_config.verbose,
            solver_name=self.slp_config.solver_name,
        )
        x_warm = slp_result.x if slp_result.x else None
        trf_driver = TrustRegionDriver(
            self.flowsheet, config=cfg, slp_config=self.slp_config
        )
        trf_result = trf_driver.run(x0=x_warm)
        trf_result.message = f"[ADAPTIVE stage 3/3] {trf_result.message}"
        return trf_result

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _active_unit_ids(self, y: Dict[str, bool]) -> set[str]:
        active: set[str] = set()
        for tech in self.technology_choices:
            if y.get(tech.name, False):
                active.add(tech.unit_id)
        # Units that aren't gated by any technology choice are always active.
        gated_ids = {t.unit_id for t in self.technology_choices}
        for u in self.flowsheet.units:
            if u.unit_id not in gated_ids:
                active.add(u.unit_id)
        return active

    def _fix_topology(self, y: Dict[str, bool]) -> BaseFlowsheet:
        """Clone the flowsheet, forcing flow variables of inactive techs to 0."""
        clone = copy.copy(self.flowsheet)
        clone.extra_bounds = dict(self.flowsheet.extra_bounds)
        for tech in self.technology_choices:
            if not y.get(tech.name, False):
                for v in tech.flow_variables:
                    clone.extra_bounds[v] = (0.0, 0.0)
        return clone

    def _aggregate_kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        kpis: Dict[str, float] = {}
        for u in self.flowsheet.units:
            for k, v in u.kpis(x).items():
                kpis[k] = kpis.get(k, 0.0) + float(v)
        return kpis

    @staticmethod
    def _milp_termination(pyomo_results) -> SolverStatus:
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
