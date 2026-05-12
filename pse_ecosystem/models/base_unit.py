"""Layer 3 base class.

Every unit model in the Knowledge Layer subclasses :class:`BaseUnit`. The
base class enforces the Layer-3 side of the Handshake Protocol defined in
``pse_ecosystem.core.contracts``:

    * ``variables()``               — what variables this unit references.
    * ``bounds()``                  — variable bounds.
    * ``residual(x)``               — *required*. f(x) at the candidate point.
    * ``objective_contribution(x)`` — per-variable linear cost coefficients.
    * ``kpis(x)``                   — optional; returns named KPI values.
    * ``linearize(guess)``          — supplied by the base class via finite
      differences. Subclasses with analytical Jacobians override it.

A unit author writing a toy model only has to implement ``residual``,
``bounds``, ``objective_contribution`` and ``variables`` (plus optionally
``kpis``). They get a fully working ``LinearizedModel`` for free, which means
the SLP driver in Layer 2 can already run against them.

Layer 2 must never import this module — it talks to units exclusively through
``LinearizedModel`` and ``UnitResponse``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import (
    LinearizedModel,
    PortCompatibilityError,
    PrimalGuess,
    StreamPort,
    UnitResponse,
)


_DEFAULT_FD_STEP = 1e-6
_MIN_FD_STEP = 1e-9


class BaseUnit(ABC):
    """Abstract base for every unit model in the Knowledge Layer."""

    #: Stable identifier used in LinearizedModel and UnitResponse.
    unit_id: str = "unit"

    #: Class-level hint. When True, the base ``linearize`` returns
    #: ``is_exact=True`` and the SLP driver short-circuits.
    is_linear: bool = False

    #: Optional unit-supplied trust-region radius (in variable units).
    trust_region: float | None = None

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def variables(self) -> List[str]:
        """Return the canonical ordering of variable names this unit references."""

    @abstractmethod
    def bounds(self) -> Dict[str, Tuple[float, float]]:
        """Return per-variable ``(lower, upper)`` bounds."""

    @abstractmethod
    def residual(self, x: Dict[str, float]) -> np.ndarray:
        """Evaluate the unit's residual f(x). Shape ``(m,)``; m may be 0."""

    @abstractmethod
    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        """Linear cost coefficient per variable. Used by the global objective."""

    # ── Optional hooks ────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        """Optional KPI calculations. Default: empty."""
        return {}

    def kpi_gradients(self, x: Dict[str, float]) -> Dict[str, np.ndarray]:
        """Optional analytical KPI gradients. Default: empty (no sensitivity report)."""
        return {}

    def capex(self, x: Dict[str, float]) -> float:
        """Capital expenditure estimate in USD (purchase cost, CE500 basis).

        Reported as a KPI only — never enters the LP objective.  Override
        in units that have SSLW or custom costing.
        """
        return 0.0

    def opex_per_year(self, x: Dict[str, float]) -> float:
        """Annual operating cost in USD/yr at operating point x.

        Default implementation sums ``objective_contribution * x``, which
        already encodes price × throughput for flow variables.  Override
        when OPEX has a more complex structure.
        """
        return sum(
            coeff * x.get(v, 0.0)
            for v, coeff in self.objective_contribution(x).items()
        )

    def control_hooks(self) -> Dict[str, str]:
        """Optional control pairing: {controlled_var: manipulated_var}.

        Returns an empty dict by default.  For display and documentation
        only in v0.2 — not consumed by any solver path.
        """
        return {}

    # ── Port validation ───────────────────────────────────────────────────

    @staticmethod
    def validate_connection(port_a: StreamPort, port_b: StreamPort) -> None:
        """Raise ``PortCompatibilityError`` if port_a and port_b cannot be wired.

        Called automatically by ``BaseFlowsheet.connect()``. Unit authors may
        also call it directly when building manual connections.
        """
        if port_a.phase != "any" and port_b.phase != "any":
            if port_a.phase != port_b.phase:
                raise PortCompatibilityError(
                    f"Phase mismatch: '{port_a.unit_id}.{port_a.tag}' "
                    f"({port_a.phase}) → '{port_b.unit_id}.{port_b.tag}' "
                    f"({port_b.phase}). Use phase='any' to skip checking."
                )
        if port_a.species and port_b.species and port_a.species != port_b.species:
            raise PortCompatibilityError(
                f"Species mismatch: '{port_a.unit_id}.{port_a.tag}' carries "
                f"{set(port_a.species)} but '{port_b.unit_id}.{port_b.tag}' "
                f"expects {set(port_b.species)}."
            )

    # ── Default implementations (override only when you can do better) ────

    def evaluate(self, x: Dict[str, float]) -> UnitResponse:
        """Evaluate the *true* (non-linear) physics. Used for residual checks."""
        residual = np.asarray(self.residual(x), dtype=float).reshape(-1)
        outputs = {name: x.get(name, 0.0) for name in self.variables()}
        kpis = self.kpis(x)
        feasible = bool(np.all(np.isfinite(residual)))
        return UnitResponse(
            unit_id=self.unit_id,
            outputs=outputs,
            kpis=kpis,
            residual=residual,
            feasible=feasible,
        )

    def linearize(self, guess: PrimalGuess) -> LinearizedModel:
        """Return a Taylor-series approximation of f around ``guess``.

        The default implementation uses a central finite-difference scheme.
        Subclasses with analytical or AD Jacobians should override this — the
        contract is the same, so nothing in Layer 2 changes.
        """
        variables = self.variables()
        x0_dict = {v: guess.values.get(v, 0.0) for v in variables}
        x0 = np.array([x0_dict[v] for v in variables], dtype=float)

        f0 = np.asarray(self.residual(x0_dict), dtype=float).reshape(-1)
        m = f0.size
        n = len(variables)

        if m == 0:
            J = np.zeros((0, n), dtype=float)
        else:
            J = self._finite_difference_jacobian(x0_dict, variables, f0)

        return LinearizedModel(
            unit_id=self.unit_id,
            variables=variables,
            x0=x0,
            f0=f0,
            J=J,
            bounds=self.bounds(),
            objective_terms=self.objective_contribution(x0_dict),
            is_exact=self.is_linear,
            trust_region=self.trust_region,
            kpi_gradients=self.kpi_gradients(x0_dict),
        )

    def get_linearization(self, x_current: Dict[str, float]) -> "LinearizedModel":
        """Preferred public alias for :meth:`linearize`.

        Accepts a plain ``Dict[str, float]`` instead of a ``PrimalGuess``
        wrapper.  New HF units call this; existing units keep ``linearize()``.
        """
        guess = PrimalGuess(values=x_current, iteration=0)
        return self.linearize(guess)

    # ── Internals ─────────────────────────────────────────────────────────

    def _finite_difference_jacobian(
        self,
        x0_dict: Dict[str, float],
        variables: List[str],
        f0: np.ndarray,
    ) -> np.ndarray:
        """Central differences with a step scaled to the variable magnitude."""
        m = f0.size
        n = len(variables)
        J = np.zeros((m, n), dtype=float)

        for j, name in enumerate(variables):
            x_val = x0_dict[name]
            step = max(_DEFAULT_FD_STEP * max(1.0, abs(x_val)), _MIN_FD_STEP)

            x_plus = dict(x0_dict)
            x_plus[name] = x_val + step
            f_plus = np.asarray(self.residual(x_plus), dtype=float).reshape(-1)

            x_minus = dict(x0_dict)
            x_minus[name] = x_val - step
            f_minus = np.asarray(self.residual(x_minus), dtype=float).reshape(-1)

            J[:, j] = (f_plus - f_minus) / (2.0 * step)

        return J
