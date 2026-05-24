"""Process dynamics — DAE simulation + perturbation generators.

Used post-solve to study transient response. The Layer 2 solver remains
steady-state-only; dynamics layer on top via :class:`DynamicSimulator`,
which calls each unit's :meth:`BaseUnit.dynamic_residuals` hook.

Sub-modules
-----------
* ``dae_solver``   — ``DynamicSimulator`` wrapping ``scipy.solve_ivp``
* ``perturbation`` — ``Perturbation`` dataclass for step / ramp / pulse /
                     sinusoidal disturbances on input variables
"""
