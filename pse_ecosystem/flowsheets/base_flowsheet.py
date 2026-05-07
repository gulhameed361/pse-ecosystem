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

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

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
        """Midpoint of bounds (with sane fallbacks for unbounded variables)."""
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
        return guess
