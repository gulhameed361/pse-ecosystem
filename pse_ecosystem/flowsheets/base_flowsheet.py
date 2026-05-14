"""Flowsheet container: units + stream connectivity + objective KPI.

A flowsheet groups a set of :class:`BaseUnit` instances and the equality
constraints that wire them together (e.g. ``pem.h2_out == storage.h2_in``).
It does *not* know about optimisation — it is consumed by Layer 2 builders.

Variable naming convention: unit authors should prefix their variable names
with the unit's ``unit_id`` so that the global namespace stays unambiguous.
Two PEM stacks named ``pem_a`` and ``pem_b`` therefore expose disjoint
variables ``pem_a.electricity_kW`` and ``pem_b.electricity_kW`` and the
flowsheet decides whether they share a feed via an explicit connection.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import PortCompatibilityError, StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class Connection:
    """An equality constraint ``var_a == var_b`` between two flowsheet variables."""

    var_a: str
    var_b: str
    description: str = ""


@dataclass
class BaseFlowsheet:
    name: str
    units: List[BaseUnit]
    connections: List[Connection] = field(default_factory=list)
    objective_kpi: str = "LCOH"
    """The KPI minimised by the global objective. Variables contributing are
    aggregated from every unit's ``objective_contribution``."""

    extra_bounds: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    """Flowsheet-level bound overrides (intersected with unit bounds)."""

    extra_equalities: List[Tuple[Dict[str, float], float]] = field(default_factory=list)
    """Linear equality constraints ``Σ a_i x_i == b`` that don't belong to any
    single unit (e.g. a hydrogen-demand balance summed across producers)."""

    recycle_streams: List[str] = field(default_factory=list)
    """Variable names that participate in recycle loops.  Metadata only —
    the solver never reads this field.  Declare recycle tear streams in
    :class:`~pse_ecosystem.solvers.slp.TearStreamConfig` instead."""

    # ── Port connectivity ────────────────────────────────────────────────────

    def connect(
        self,
        port_a: StreamPort,
        port_b: StreamPort,
        description: str = "",
    ) -> None:
        """Wire an outlet port to an inlet port.

        Generates one :class:`Connection` per shared variable (matched by
        canonical position in ``variable_names()``).  Both ports must have
        identical component lists and T/P flags.

        Raises ``ValueError`` if the port variable counts differ.
        """
        BaseUnit.validate_connection(port_a, port_b)

        a_names = port_a.variable_names()
        b_names = port_b.variable_names()
        if len(a_names) != len(b_names):
            raise ValueError(
                f"connect(): port '{port_a.tag}' on '{port_a.unit_id}' has "
                f"{len(a_names)} variables but port '{port_b.tag}' on "
                f"'{port_b.unit_id}' has {len(b_names)}. Ports must match."
            )
        for va, vb in zip(a_names, b_names):
            self.connections.append(
                Connection(var_a=va, var_b=vb, description=description)
            )

    # ── Topology helpers ────────────────────────────────────────────────────

    def all_variables(self) -> List[str]:
        """Union of every variable referenced by any unit, deduplicated."""
        seen: Dict[str, None] = {}
        for u in self.units:
            for v in u.variables():
                seen[v] = None
        for conn in self.connections:
            seen.setdefault(conn.var_a, None)
            seen.setdefault(conn.var_b, None)
        for coeffs, _ in self.extra_equalities:
            for v in coeffs:
                seen.setdefault(v, None)
        return list(seen)

    def aggregated_bounds(self) -> Dict[str, Tuple[float, float]]:
        """Intersect per-unit bounds with flowsheet-level overrides."""
        out: Dict[str, Tuple[float, float]] = {}
        for u in self.units:
            for v, (lo, hi) in u.bounds().items():
                if v in out:
                    out[v] = (max(out[v][0], lo), min(out[v][1], hi))
                else:
                    out[v] = (lo, hi)
        for v, (lo, hi) in self.extra_bounds.items():
            if v in out:
                out[v] = (max(out[v][0], lo), min(out[v][1], hi))
            else:
                out[v] = (lo, hi)
        return out

    def is_fully_linear(self) -> bool:
        """``True`` iff every unit advertises ``is_linear=True``."""
        return all(getattr(u, "is_linear", False) for u in self.units)

    # ── Convenience for the SLP driver ──────────────────────────────────────

    def initial_guess(self) -> Dict[str, float]:
        """Midpoint of bounds (with sane fallbacks for unbounded variables).

        If ``self.initial_x0`` is set, those values override the midpoint for
        the named variables, providing a heuristic warm-start.
        """
        guess: Dict[str, float] = {}
        for v, (lo, hi) in self.aggregated_bounds().items():
            if lo > -1e18 and hi < 1e18:
                guess[v] = 0.5 * (lo + hi)
            elif lo > -1e18:
                guess[v] = lo + 1.0
            elif hi < 1e18:
                guess[v] = hi - 1.0
            else:
                guess[v] = 0.0
        for v in self.all_variables():
            guess.setdefault(v, 0.0)
        if hasattr(self, "initial_x0"):
            for v, val in self.initial_x0.items():
                if v in guess:
                    guess[v] = float(val)
        return guess


# ── CompositeUnit ─────────────────────────────────────────────────────────────


class CompositeUnit(BaseUnit):
    """Wrap a :class:`BaseFlowsheet` as a single :class:`BaseUnit`.

    This enables hierarchical flowsheet composition: a sub-process (e.g.
    a heat-exchange network or a gas-cleaning train) can be exposed to a
    parent flowsheet as if it were an atomic unit.  The parent sees only
    ``exposed_inputs`` and ``exposed_outputs``; the internal structure is
    hidden.

    Circular-import note
    --------------------
    ``CompositeUnit`` lives in ``flowsheets/`` (Layer 3) but needs to call
    ``SLPDriver`` from ``solvers/`` (Layer 2).  The import is deferred to
    inside :meth:`residual` so that it only executes at call time, after
    both modules are fully loaded.  This intentional cross-layer call is
    the *only* sanctioned exception to the "Layer 2 must not import Layer 3"
    rule — here the direction is reversed (Layer 3 calling Layer 2 to solve
    an inner sub-problem), which is architecturally sound for hierarchical
    decomposition.

    Parameters
    ----------
    unit_id:
        Name prefix for the composite unit's exposed variables.
    inner_flowsheet:
        The sub-process ``BaseFlowsheet`` to solve internally.
    exposed_inputs:
        Variable names (from ``inner_flowsheet``) that the parent flowsheet
        will drive.  These become *inputs* to the composite unit.
    exposed_outputs:
        Variable names (from ``inner_flowsheet``) whose values the composite
        unit reports to the parent.  Each generates one residual equation:
        ``outer_var - inner_solution[v] = 0``.
    slp_config:
        Optional :class:`~pse_ecosystem.solvers.slp.SLPConfig` for the inner
        SLP solve.  Defaults to ``SLPConfig(max_iter=30, verbose=False)``.
    """

    is_linear = False

    def __init__(
        self,
        unit_id: str,
        inner_flowsheet: "BaseFlowsheet",
        exposed_inputs: List[str],
        exposed_outputs: List[str],
        slp_config=None,
    ):
        self.unit_id = unit_id
        self.inner_flowsheet = inner_flowsheet
        self.exposed_inputs = list(exposed_inputs)
        self.exposed_outputs = list(exposed_outputs)
        self._slp_config = slp_config

    def variables(self) -> List[str]:
        return self.exposed_inputs + self.exposed_outputs

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        all_bounds = self.inner_flowsheet.aggregated_bounds()
        return {v: all_bounds[v] for v in self.variables() if v in all_bounds}

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        # Deferred import to break the flowsheets ↔ solvers circular dependency.
        from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver  # noqa: PLC0415

        # Build a clone of the inner flowsheet with the exposed inputs pinned.
        clone = copy.copy(self.inner_flowsheet)
        clone.extra_bounds = dict(self.inner_flowsheet.extra_bounds)
        for v in self.exposed_inputs:
            val = float(x.get(v, 0.0))
            clone.extra_bounds[v] = (val, val)

        cfg = self._slp_config or SLPConfig(max_iter=30, verbose=False)
        driver = SLPDriver(clone, cfg)

        x0 = clone.initial_guess()
        # Seed the initial guess from the outer solution for exposed vars.
        for v in self.exposed_inputs + self.exposed_outputs:
            if v in x:
                x0[v] = float(x[v])

        result = driver.run(x0=x0)
        if not result.converged:
            # Return a large residual so the outer SLP sees infeasibility.
            return np.full(len(self.exposed_outputs), 1e6, dtype=float)

        return np.array(
            [float(x.get(v, 0.0)) - float(result.x.get(v, 0.0))
             for v in self.exposed_outputs],
            dtype=float,
        )

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}
