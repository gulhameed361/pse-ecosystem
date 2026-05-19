"""Cross-layer data contracts.

This module defines every piece of data that flows between Layer 2 (decision /
solver) and Layer 3 (knowledge / unit models). Both layers import from here, but
neither layer is allowed to import from the other. That asymmetry is what keeps
the architecture honest:

    Layer 2 (solvers/) ─┐
                        ├──> core/contracts.py
    Layer 3 (models/)  ─┘

If you find yourself wanting to add solver-specific or physics-specific code to
this file, you are about to break a layer boundary. Stop and reconsider.

The Handshake Protocol consists of three datatypes:

* ``PrimalGuess``     — sent L2 → L3 each SLP iteration.
* ``LinearizedModel`` — returned L3 → L2; the Taylor-series approximation Layer
  2 will turn into LP rows.
* ``UnitResponse``    — returned L3 → L2 when Layer 2 asks the unit to evaluate
  the *true* (non-linear) physics, used for residual checking and KPI reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# Stream Ports
# ──────────────────────────────────────────────────────────────────────────────


class PortCompatibilityError(ValueError):
    """Raised when two ports cannot be connected due to mismatched phase or species."""


@dataclass
class StreamPort:
    """Name-generator for a process stream — holds no values, only produces
    flat variable strings scoped to the owning unit_id.

    Variable order (canonical): F_<comp>... , T (if has_T), P (if has_P).
    This is intentionally a thin wrapper so the LP builder sees only the
    familiar flat string names it has always handled.

    Usage::

        port = StreamPort("cstr", "outlet", components=["A", "B"], has_T=True, has_P=True)
        port.variable_names()
        # → ["cstr.outlet.F_A", "cstr.outlet.F_B", "cstr.outlet.T", "cstr.outlet.P"]

        fs.connect(cstr.outlet_port, flash.inlet_port)

    Port Validation
    ---------------
    ``phase``   : Physical phase of the stream ("gas", "liquid", "solid_dry",
                  "mixed", or "any" to skip phase checking).
    ``species``  : Frozenset of component names expected on this port.  An empty
                  frozenset means unconstrained (validation skipped).  When both
                  ports declare non-empty species sets, they must match exactly.
    """

    unit_id: str
    tag: str  # e.g. "inlet", "outlet", "vapor", "liquid"
    components: List[str] = field(default_factory=list)
    has_T: bool = True
    has_P: bool = True
    phase: str = "gas"
    species: frozenset = frozenset()

    def variable_names(self) -> List[str]:
        names = [f"{self.unit_id}.{self.tag}.F_{c}" for c in self.components]
        if self.has_T:
            names.append(f"{self.unit_id}.{self.tag}.T")
        if self.has_P:
            names.append(f"{self.unit_id}.{self.tag}.P")
        return names

    def T(self) -> str:
        return f"{self.unit_id}.{self.tag}.T"

    def P(self) -> str:
        return f"{self.unit_id}.{self.tag}.P"

    def F(self, component: str) -> str:
        return f"{self.unit_id}.{self.tag}.F_{component}"


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class SolveMode(str, Enum):
    """User-selected mode from Layer 1."""

    FIXED_LP = "mode_1"
    """Fixed flowsheet topology. Solved as LP, or via SLP if any unit is non-linear."""

    FLEXIBLE_MILP = "mode_2"
    """Technology choice via binary variables. Outer MILP wrapping operations."""

    NLP_IPOPT = "mode_3"
    """Full NLP solve.

    NAMING NOTE (v1.5.0.dev-AUDIT2 L2-1): the enum is named ``NLP_IPOPT`` for
    backwards compatibility with v1.0–v1.4 callers, but the current
    implementation (``solvers/ipopt_driver.py::NLPDriver``) uses
    ``scipy.optimize.minimize`` with L-BFGS-B and a Gauss-Newton gradient
    derived from each unit's linearisation. To switch to real IPOPT would
    require rewriting every Layer-3 residual in Pyomo expression syntax —
    out of scope for v1.5.  The alias ``NLP_SCIPY`` is the preferred name
    going forward; ``NLP_IPOPT`` is retained as a non-deprecated alias for
    semver compatibility.
    """

    NLP_SCIPY = "mode_3"
    """Alias for NLP_IPOPT — the canonical name reflecting the actual scipy
    L-BFGS-B backend used by NLPDriver. Both enums resolve to the same value."""

    TRUST_REGION = "mode_4"
    """Trust-Region Filter/Funnel driver (Eason & Biegler 2016). Most robust fallback."""

    ADAPTIVE = "adaptive"
    """Cascade: SLP → IPOPT → Trust-Region, escalating on convergence failure."""


class SolverStatus(str, Enum):
    CONVERGED = "converged"
    MAX_ITER = "max_iter"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    NUMERICAL_ERROR = "numerical_error"


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 → Layer 3
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PrimalGuess:
    """The current operating point Layer 2 wants linearised.

    Variable names are the canonical handle. Layer 2 doesn't need to know
    anything about a variable beyond its name and current value; the unit owns
    its own internal interpretation.
    """

    values: Dict[str, float]
    iteration: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: float = 0.0) -> float:
        return self.values.get(name, default)

    def vector(self, variables: List[str]) -> np.ndarray:
        """Return values aligned to a given variable ordering."""
        return np.array([self.values.get(v, 0.0) for v in variables], dtype=float)


# ──────────────────────────────────────────────────────────────────────────────
# Layer 3 → Layer 2
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class LinearizedModel:
    """Taylor-series linearisation of a unit's residual at ``x0``.

    The LP rows Layer 2 will build are::

        f0 + J · (x - x0)  =  0           (equality residuals)
        lb_v ≤ x_v ≤ ub_v                  (per-variable bounds)
        ‖x - x0‖_∞ ≤ trust_region          (when set)

    Plus a per-variable cost contribution given by ``objective_terms``.

    Attributes
    ----------
    unit_id:
        Stable identifier for the source unit. Used by lp_builder for
        constraint naming and diagnostics.
    variables:
        Column ordering for ``x0`` and ``J``. Names must match the global
        variable namespace defined by the flowsheet.
    x0:
        Linearisation point, shape ``(n,)``.
    f0:
        Residual values at ``x0``, shape ``(m,)``. ``m`` may be zero (a unit
        that contributes only bounds and a cost coefficient).
    J:
        Jacobian ∂f/∂x at ``x0``, shape ``(m, n)``.
    bounds:
        Per-variable ``(lower, upper)`` bounds. ``-inf`` / ``+inf`` allowed.
    objective_terms:
        Per-variable linear coefficient contributing to the global objective
        (e.g. CAPEX per kW of installed PEM capacity).
    is_exact:
        ``True`` when the unit is genuinely linear and the linearisation is
        independent of ``x0``. Lets the SLP driver short-circuit re-evaluation.
    trust_region:
        Optional unit-supplied trust-region radius (in variable units). Use
        when the unit knows its model is only valid in a neighbourhood.
    kpi_gradients:
        Per-KPI ∂KPI/∂x at ``x0``. Used by Layer 2 to expose KPI sensitivities
        in the post-solve report; never required for solving.
    """

    unit_id: str
    variables: List[str]
    x0: np.ndarray
    f0: np.ndarray
    J: np.ndarray
    bounds: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    objective_terms: Dict[str, float] = field(default_factory=dict)
    is_exact: bool = False
    trust_region: Optional[float] = None
    kpi_gradients: Dict[str, np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.variables)
        if self.x0.shape != (n,):
            raise ValueError(
                f"x0 shape {self.x0.shape} incompatible with {n} variables"
            )
        if self.J.size == 0:
            self.J = np.zeros((0, n), dtype=float)
        if self.J.ndim != 2 or self.J.shape[1] != n:
            raise ValueError(
                f"J shape {self.J.shape} incompatible with {n} variables"
            )
        if self.f0.shape != (self.J.shape[0],):
            raise ValueError(
                f"f0 shape {self.f0.shape} incompatible with J rows {self.J.shape[0]}"
            )

    def predicted_residual(self, x: Dict[str, float]) -> np.ndarray:
        """Evaluate f0 + J · (x - x0) for a candidate x dict."""
        x_vec = np.array([x.get(v, 0.0) for v in self.variables], dtype=float)
        return self.f0 + self.J @ (x_vec - self.x0)


@dataclass
class UnitResponse:
    """Result of evaluating a unit's *true* (non-linear) physics at a point."""

    unit_id: str
    outputs: Dict[str, float] = field(default_factory=dict)
    kpis: Dict[str, float] = field(default_factory=dict)
    residual: np.ndarray = field(default_factory=lambda: np.zeros(0))
    feasible: bool = True
    diagnostics: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Solver result
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class SolveResult:
    """Final answer returned by the Orchestrator to Layer 1."""

    status: SolverStatus
    mode: SolveMode
    x: Dict[str, float] = field(default_factory=dict)
    kpis: Dict[str, float] = field(default_factory=dict)
    iterations: int = 0
    objective: float = float("nan")
    technology_selection: Dict[str, bool] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    message: str = ""
    bound_active: List[str] = field(default_factory=list)
    """Variable names whose solution value sits at (or within tol of) a
    non-fixed bound. Excludes intentionally fixed variables (lb == ub) such
    as targeted outlet temperatures or pinned feed rates. A non-empty list
    at CONVERGED is a STRONG signal that the physics may be overridden by a
    default bound (e.g. CoolerHFParams.feed_max=1000) — inspect each entry
    before trusting the KPIs. Populated by the SLP driver."""

    @property
    def converged(self) -> bool:
        return self.status == SolverStatus.CONVERGED
