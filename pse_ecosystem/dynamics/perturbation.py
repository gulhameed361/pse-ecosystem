"""Perturbation generators for dynamic-simulation input variables.

Each :class:`Perturbation` produces ``v(t)`` for a single input variable
— feed flow, setpoint temperature, demand pressure — that the
:class:`DynamicSimulator` plays back during integration. Compose multiple
perturbations onto one variable by adding them (the ``__add__`` operator
returns a sum perturbation).

The four canonical shapes (Marlin Ch. 5):

* ``step(t0, magnitude, baseline)``      — instantaneous jump at t0
* ``ramp(t0, slope, baseline, t_end)``   — linear from t0 to t_end
* ``pulse(t0, duration, magnitude, baseline)`` — rectangular pulse
* ``sinusoid(amplitude, period, baseline, phase)`` — sustained oscillation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List


@dataclass
class Perturbation:
    """Time-varying value generator for a single input variable.

    Compose with ``+`` to overlay multiple shapes (e.g. step + sinusoid for
    a setpoint jolt followed by sustained disturbance).
    """

    func: Callable[[float], float]
    baseline: float = 0.0
    label: str = ""

    def value_at(self, t: float) -> float:
        return float(self.func(t)) + self.baseline

    def __call__(self, t: float) -> float:
        return self.value_at(t)

    def __add__(self, other: "Perturbation") -> "Perturbation":
        def summed(t: float, a=self, b=other) -> float:
            # Both ``a`` and ``b`` include their own baselines; sum
            # subtracts one baseline so the composed perturbation's
            # baseline is the sum.
            return a.func(t) + b.func(t)

        return Perturbation(
            func=summed,
            baseline=self.baseline + other.baseline,
            label=f"({self.label} + {other.label})" if self.label or other.label
                  else "",
        )

    # ── Canonical shapes (factory classmethods) ──────────────────────────

    @classmethod
    def step(
        cls, t0: float, magnitude: float, baseline: float = 0.0,
        label: str = "step",
    ) -> "Perturbation":
        """Δv at t = t0; magnitude held thereafter."""
        return cls(
            func=lambda t: magnitude if t >= t0 else 0.0,
            baseline=baseline, label=label,
        )

    @classmethod
    def ramp(
        cls, t0: float, slope: float, baseline: float = 0.0,
        t_end: float = float("inf"), label: str = "ramp",
    ) -> "Perturbation":
        """Linear ramp at ``slope`` per second from ``t0`` to ``t_end``."""
        def f(t: float) -> float:
            if t < t0:
                return 0.0
            if t > t_end:
                return slope * (t_end - t0)
            return slope * (t - t0)

        return cls(func=f, baseline=baseline, label=label)

    @classmethod
    def pulse(
        cls, t0: float, duration: float, magnitude: float,
        baseline: float = 0.0, label: str = "pulse",
    ) -> "Perturbation":
        """Rectangular pulse of height ``magnitude`` lasting ``duration``."""
        return cls(
            func=lambda t: magnitude if t0 <= t <= (t0 + duration) else 0.0,
            baseline=baseline, label=label,
        )

    @classmethod
    def sinusoid(
        cls, amplitude: float, period_s: float, baseline: float = 0.0,
        phase_rad: float = 0.0, label: str = "sinusoid",
    ) -> "Perturbation":
        """Sustained ``amplitude · sin(2π·t/period + phase)``."""
        omega = 2.0 * math.pi / max(period_s, 1e-9)
        return cls(
            func=lambda t: amplitude * math.sin(omega * t + phase_rad),
            baseline=baseline, label=label,
        )


__all__ = ["Perturbation"]
