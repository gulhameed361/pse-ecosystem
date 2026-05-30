"""Dynamic simulator — ODE/DAE integrator over a flowsheet.

The Layer 2 solver computes the steady-state algebraic solution; this
module integrates a *transient response* on top of it. Each unit
contributes its time-derivatives via :meth:`BaseUnit.dynamic_residuals`;
units without dynamics return an empty dict and are skipped.

Wrap-up around ``scipy.integrate.solve_ivp`` (BDF / Radau backends, both
suitable for stiff DAEs). Event detection is supported via the
:class:`SimEvent` callback, which lets the user trigger setpoint changes,
relief-valve opens, or pump trips at a specified time or condition.

Limitations for v1.6
--------------------
* The simulator operates **post-steady-state**: it expects the algebraic
  state ``x_state`` to be already converged and uses it as the
  initial condition. Re-solving the steady-state algebraic block at
  every Newton step would require coupling to the Layer 2 LP, which is
  out of scope for v1.6.
* Composition / temperature dynamics on units that don't implement
  ``dynamic_residuals`` are held constant during the transient.

Usage
-----
::

    sim = DynamicSimulator(flowsheet, x_state)
    sim.add_perturbation("feed.F_H2", Perturbation.step(t0=10.0, magnitude=0.5))
    sim.integrate(t_span=(0.0, 600.0), dt_output=5.0)
    df = sim.results_as_dict()   # {var: [values vs time]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import warnings

import numpy as np

from pse_ecosystem.models.base_unit import BaseUnit

_SOLVER_BACKENDS = ("BDF", "Radau", "LSODA", "RK45")


@dataclass
class SimEvent:
    """User-defined event that fires at a specified simulation time or
    condition. The ``action`` callable receives the current ``(t, y_dict,
    x_state)`` and may mutate ``x_state`` to apply the event (open a relief
    valve, drop a feed rate, etc.). Events are evaluated at every
    ``dt_output`` interval — sub-step detection is left to a future
    refinement of this module."""

    name: str
    trigger_t_s: Optional[float] = None
    """Absolute simulation time at which the event fires. ``None`` = use
    ``predicate`` instead of a time gate."""
    predicate: Optional[Callable[[float, Dict[str, float]], bool]] = None
    """Optional condition ``(t, y_dict) → bool``. The event fires the first
    iteration the predicate returns True."""
    action: Callable[[float, Dict[str, float], Dict[str, float]], None] = (
        lambda t, y, x: None
    )
    """Callback invoked when the event fires. May mutate the in-place
    ``x_state`` dict supplied as the third argument."""
    _fired: bool = field(default=False, init=False)


@dataclass
class SimResult:
    t_s: np.ndarray
    y_history: Dict[str, np.ndarray]
    fired_events: List[str] = field(default_factory=list)
    converged: bool = True
    message: str = "OK"


class DynamicSimulator:
    """Integrate a flowsheet's :meth:`dynamic_residuals` block over time."""

    def __init__(
        self,
        units: List[BaseUnit],
        x_state: Dict[str, float],
        method: str = "BDF",
    ):
        if method not in _SOLVER_BACKENDS:
            raise ValueError(
                f"Unknown solver method {method!r}. "
                f"Available: {_SOLVER_BACKENDS}"
            )
        self.units = list(units)
        self.x_state: Dict[str, float] = dict(x_state)
        self.method = method
        self._events: List[SimEvent] = []
        self._perturbations: List[Tuple[str, Any]] = []
        # Discover the union of dynamic state variables across all units.
        self._state_vars: List[str] = self._discover_state_vars()

    def _discover_state_vars(self) -> List[str]:
        """Collect every state variable name returned by any unit at t=0."""
        seen: List[str] = []
        for u in self.units:
            try:
                derivs = u.dynamic_residuals(0.0, {}, self.x_state)
            except (ValueError, ArithmeticError, KeyError, TypeError, IndexError) as exc:
                warnings.warn(
                    f"dynamic_residuals failed during state discovery for unit "
                    f"{getattr(u, 'unit_id', u)!r}; treating it as non-dynamic: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                derivs = {}
            for k in derivs:
                if k not in seen:
                    seen.append(k)
        return seen

    # ── User-facing perturbation / event registration ───────────────────
    def add_event(self, event: SimEvent) -> None:
        self._events.append(event)

    def add_perturbation(self, var_name: str, perturbation: Any) -> None:
        """Register a time-varying override on an algebraic input variable.

        ``perturbation`` must be a :class:`pse_ecosystem.dynamics.Perturbation`
        instance (or any callable ``t → value``). The simulator updates
        ``x_state[var_name]`` to the perturbation's value at each output
        step before computing dy/dt.
        """
        self._perturbations.append((var_name, perturbation))

    # ── Integration ─────────────────────────────────────────────────────
    def _apply_perturbations(self, t: float) -> None:
        for var, pert in self._perturbations:
            if callable(pert):
                self.x_state[var] = float(pert(t))
            elif hasattr(pert, "value_at"):
                self.x_state[var] = float(pert.value_at(t))

    def _check_events(self, t: float, y_dict: Dict[str, float]) -> List[str]:
        fired_now: List[str] = []
        for ev in self._events:
            if ev._fired:
                continue
            should_fire = False
            if ev.trigger_t_s is not None and t >= ev.trigger_t_s:
                should_fire = True
            elif ev.predicate is not None and ev.predicate(t, y_dict):
                should_fire = True
            if should_fire:
                ev.action(t, y_dict, self.x_state)
                ev._fired = True
                fired_now.append(ev.name)
        return fired_now

    def _y_to_dict(self, y_arr: np.ndarray) -> Dict[str, float]:
        return {name: float(y_arr[i]) for i, name in enumerate(self._state_vars)}

    def _aggregate_derivatives(
        self, t: float, y_arr: np.ndarray
    ) -> np.ndarray:
        """Sum dy/dt contributions from every unit for one time-step."""
        y_dict = self._y_to_dict(y_arr)
        self._apply_perturbations(t)
        dy = np.zeros(len(self._state_vars))
        for u in self.units:
            try:
                contribs = u.dynamic_residuals(t, y_dict, self.x_state)
            except (ValueError, ArithmeticError, KeyError, TypeError, IndexError) as exc:
                warnings.warn(
                    f"dynamic_residuals failed for unit "
                    f"{getattr(u, 'unit_id', u)!r} at t={t:.4g}; skipping: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            for k, v in contribs.items():
                if k in self._state_vars:
                    idx = self._state_vars.index(k)
                    dy[idx] += v
        return dy

    def integrate(
        self,
        t_span: Tuple[float, float],
        y0: Optional[Dict[str, float]] = None,
        dt_output: float = 1.0,
        rtol: float = 1e-6,
        atol: float = 1e-9,
    ) -> SimResult:
        """Integrate from ``t_span[0]`` to ``t_span[1]`` with output
        snapshots every ``dt_output`` seconds.

        Empty-state shortcut: when no unit contributes dynamic_residuals,
        return a single-point ``SimResult`` with the initial state — this
        keeps existing steady-state-only flowsheets working without
        scipy.solve_ivp churn.
        """
        if not self._state_vars:
            return SimResult(
                t_s=np.array([t_span[0]]),
                y_history={},
                converged=True,
                message="No dynamic states — steady-state only",
            )

        from scipy.integrate import solve_ivp

        y0_dict = y0 or {}
        y0_arr = np.array(
            [y0_dict.get(name, 0.0) for name in self._state_vars],
            dtype=float,
        )
        t_eval = np.arange(t_span[0], t_span[1] + dt_output, dt_output)
        fired: List[str] = []

        # Wrap dy/dt and re-check events at every solver step.
        def rhs(t, y):
            fired.extend(self._check_events(t, self._y_to_dict(y)))
            return self._aggregate_derivatives(t, y)

        sol = solve_ivp(
            rhs, t_span, y0_arr, method=self.method,
            t_eval=t_eval, rtol=rtol, atol=atol,
        )
        y_history = {
            name: sol.y[i].copy() for i, name in enumerate(self._state_vars)
        }
        return SimResult(
            t_s=sol.t.copy(),
            y_history=y_history,
            fired_events=fired,
            converged=bool(sol.success),
            message=sol.message,
        )

    def results_as_dict(self, result: SimResult) -> Dict[str, List[float]]:
        """Flatten a :class:`SimResult` to ``{var: list_of_values}``."""
        out: Dict[str, List[float]] = {"t_s": result.t_s.tolist()}
        for k, v in result.y_history.items():
            out[k] = v.tolist()
        return out


__all__ = ["SimEvent", "SimResult", "DynamicSimulator"]
