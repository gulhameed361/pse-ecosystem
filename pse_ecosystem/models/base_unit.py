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
from enum import Enum
from typing import Dict, List, Tuple

__all__ = ["BaseUnit", "OPEXConvention"]

import numpy as np

from pse_ecosystem.core.contracts import (
    LinearizedModel,
    PortCompatibilityError,
    PrimalGuess,
    StreamPort,
    UnitResponse,
)


class OPEXConvention(str, Enum):
    """Governs how ``objective_contribution()`` coefficients map to USD/yr.

    Inheriting from ``str`` keeps the enum values equal to their string
    literals so existing comparisons such as ``== "USD_per_year"`` still work.
    """

    USD_PER_YEAR = "USD_per_year"
    """Coefficient × variable_value is already in USD/yr.  This is the default
    and covers units that embed ``electricity_price × operating_hours`` in
    their objective coefficient (e.g. PEMToy, ElectrolyserHF)."""

    USD_PER_SECOND = "USD_per_second"
    """Coefficient × variable_value is USD/s (rate basis).
    ``opex_per_year()`` multiplies by ``3600 × operating_hours`` to annualise.
    Used by units whose decision variable is a mass or molar flow rate and
    whose coefficient is a per-unit utility price (e.g. BiomassGasifierHF)."""

    YIELD_COEFFICIENT = "yield_coefficient"
    """Coefficient is an LP yield/penalty, not an operating cost.
    ``opex_per_year()`` returns 0 for these units (e.g. H2SeparatorPSA
    where ``−1.0`` on the H₂ outlet flow maximises recovery)."""


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

    #: OPEX convention governing how ``objective_contribution()`` coefficients
    #: translate to annual operating cost.  See :class:`OPEXConvention` for
    #: full semantics.  Subclasses override at class level:
    #:   ``_OPEX_CONVENTION = OPEXConvention.USD_PER_SECOND``
    #: String literals ("USD_per_year" etc.) remain accepted for
    #: backwards-compatibility because ``OPEXConvention`` inherits ``str``.
    _OPEX_CONVENTION: OPEXConvention = OPEXConvention.USD_PER_YEAR

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

    def opex_per_year(self, x: Dict[str, float],
                       operating_hours: float = 8000.0) -> float:
        """Annual operating cost in USD/yr at operating point x.

        Default implementation sums ``objective_contribution * x`` and converts
        based on the unit's ``_OPEX_CONVENTION`` class attribute:

        * ``"USD_per_year"`` (default): the sum IS already USD/yr (the
          objective_contribution coefficients embed × operating_hours).
        * ``"USD_per_second"``: multiply by ``3600 × operating_hours``.
        * ``"yield_coefficient"``: return 0 (the coefficient is a yield/penalty
          for the LP objective, not an operating cost).

        Override only when OPEX needs a fundamentally different structure
        (e.g., piecewise tariffs or non-linear utility curves).
        """
        if self._OPEX_CONVENTION == "yield_coefficient":
            return 0.0
        raw = sum(
            coeff * x.get(v, 0.0)
            for v, coeff in self.objective_contribution(x).items()
        )
        if self._OPEX_CONVENTION == "USD_per_second":
            return raw * 3600.0 * operating_hours
        return raw

    def control_hooks(self) -> Dict[str, str]:
        """Optional control pairing: {controlled_var: manipulated_var}.

        Returns an empty dict by default.  Informational only — not consumed
        by any solver path.  Override to declare pairing for documentation or
        future control-loop integration.
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
            # v1.4.0 audit L5: when |x_val| is sub-micro the multiplicative
            # scaling collapses below the unit-bound floor and the perturbed
            # x_val ± step can cross a variable lower bound (typically 0 for
            # flows). Use absolute |x_val| scaling AND ensure the step is
            # bounded above by 0.1·|x_val| once x_val grows past micro-scale
            # so we never overshoot the bound by more than 10 %.
            step = max(_DEFAULT_FD_STEP * max(1.0, abs(x_val)), _MIN_FD_STEP)
            if abs(x_val) > 1.0:
                step = min(step, 0.1 * abs(x_val))

            x_plus = dict(x0_dict)
            x_plus[name] = x_val + step
            f_plus = np.asarray(self.residual(x_plus), dtype=float).reshape(-1)

            x_minus = dict(x0_dict)
            x_minus[name] = x_val - step
            f_minus = np.asarray(self.residual(x_minus), dtype=float).reshape(-1)

            J[:, j] = (f_plus - f_minus) / (2.0 * step)

        return J
