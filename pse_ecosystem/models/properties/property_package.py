"""Property-package framework — pluggable thermo models for Layer 3.

This module defines the abstract :class:`PropertyPackage` contract that every
property method (ideal-gas, Peng-Robinson, SRK, NRTL, ...) must satisfy, plus
a factory :func:`get_property_package` so flowsheets can select a method by
string key without importing concrete classes.

v1.6 ships with one concrete implementation, :class:`IdealGasPackage`, which
wraps the existing Shomate / Antoine functions for byte-identical backward
compatibility with v1.5.3 flowsheets. PR / SRK / NRTL / Wilson / UNIQUAC slots
are reserved in the registry and raise :class:`NotImplementedError` until the
corresponding implementations land (sub-tasks C.3 and C.4).

All vector quantities are indexed by ``self.species`` order. Compositions ``z``
may be mole fractions or unnormalised flows; the package normalises internally.

Unit conventions
----------------
* Temperature       — K
* Pressure          — Pa
* Enthalpy          — J/mol (includes standard enthalpy of formation)
* Heat capacity     — J/mol/K
* Density (molar)   — mol/m³
* Molecular weight  — g/mol  (kg/kmol)

The unit conventions match the existing ``ideal_gas`` / ``vle`` modules so that
the IdealGasPackage wrapper is a pure pass-through.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from pse_ecosystem.models.properties import components as _cdb
from pse_ecosystem.models.properties import ideal_gas as _ig
from pse_ecosystem.models.properties import vle as _vle

_R_GAS = 8.314462  # J/mol/K

# Phase tags — plain strings so they cross JSON / Excel cleanly.
PHASE_VAPOR = "vapor"
PHASE_LIQUID = "liquid"


# ── Abstract base ────────────────────────────────────────────────────────────


class PropertyPackage(ABC):
    """Abstract base class for thermo property packages.

    Subclasses must implement :meth:`K_values`, :meth:`enthalpy`, :meth:`Cp`,
    and :meth:`density`. Default :meth:`bubble_T` / :meth:`dew_T` solvers are
    provided on the base and only need overriding if the subclass has a faster
    closed-form route.
    """

    method_name: str = "abstract"

    def __init__(self, species: Sequence[str]) -> None:
        if not species:
            raise ValueError("PropertyPackage requires at least one species")
        self.species: List[str] = list(species)
        self._index: Dict[str, int] = {sp: i for i, sp in enumerate(self.species)}

    # ── helpers ──────────────────────────────────────────────────────────
    def _as_array(self, z) -> np.ndarray:
        """Normalise *z* to a unit-sum mole-fraction vector of the right length."""
        z = np.asarray(z, dtype=float)
        if z.shape != (len(self.species),):
            raise ValueError(
                f"composition array has shape {z.shape}, expected "
                f"({len(self.species)},) for species {self.species}"
            )
        total = float(z.sum())
        if total <= 0.0:
            return np.zeros_like(z)
        return z / total

    def _composition_dict(self, z: np.ndarray) -> Dict[str, float]:
        return {sp: float(zi) for sp, zi in zip(self.species, z)}

    def molecular_weights(self) -> np.ndarray:
        """Molecular weights [g/mol] in ``self.species`` order."""
        return np.array([_cdb.get(sp).MW for sp in self.species], dtype=float)

    # ── contract (must override) ─────────────────────────────────────────
    @abstractmethod
    def K_values(
        self, T_K: float, P_Pa: float, z: Optional[Sequence[float]] = None
    ) -> np.ndarray:
        """Vector of K-values K_i = y_i / x_i for every species.

        ``z`` is required for composition-dependent packages (PR, NRTL) and
        ignored by Raoult-law ideal-gas.
        """

    @abstractmethod
    def enthalpy(
        self,
        T_K: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
        T_ref_K: float = 298.15,
    ) -> float:
        """Molar enthalpy of the mixture at (T, z, phase) [J/mol]."""

    @abstractmethod
    def Cp(
        self, T_K: float, z: Sequence[float], phase: str = PHASE_VAPOR
    ) -> float:
        """Molar heat capacity of the mixture [J/mol/K]."""

    @abstractmethod
    def density(
        self,
        T_K: float,
        P_Pa: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
    ) -> float:
        """Molar density [mol/m³] at (T, P, z, phase)."""

    # ── Flash iteration hook ─────────────────────────────────────────────
    def K_iteration(
        self,
        T_K: float,
        P_Pa: float,
        x: Sequence[float],
        y: Sequence[float],
    ) -> np.ndarray:
        """Update K-values during a successive-substitution flash.

        Default implementation re-evaluates :meth:`K_values` at the *liquid*
        composition ``x`` — correct for ideal-gas Raoult and activity-model
        modified-Raoult (both use γ(T, x) or are composition-independent).
        Cubic-EOS packages override this to use K_i = φ_i^L(T, P, x) /
        φ_i^V(T, P, y), which is the rigorous fugacity-ratio definition.
        """
        return self.K_values(T_K, P_Pa, x)

    # ── VLE helpers (Newton on K_values) ─────────────────────────────────
    def bubble_T(
        self,
        P_Pa: float,
        z: Sequence[float],
        T_guess: float = 350.0,
        tol: float = 1e-6,
        max_iter: int = 50,
    ) -> float:
        """Bubble-point temperature [K] from Σ z_i K_i(T,P,z) = 1."""
        zarr = self._as_array(z)
        T = float(T_guess)
        for _ in range(max_iter):
            K = self.K_values(T, P_Pa, zarr)
            f = float(np.dot(zarr, K)) - 1.0
            if abs(f) < tol:
                return T
            K_plus = self.K_values(T + 0.5, P_Pa, zarr)
            dfdT = (float(np.dot(zarr, K_plus - K))) / 0.5
            if abs(dfdT) < 1e-15:
                break
            T -= f / dfdT
        return float("nan")

    def dew_T(
        self,
        P_Pa: float,
        y: Sequence[float],
        T_guess: float = 350.0,
        tol: float = 1e-6,
        max_iter: int = 50,
    ) -> float:
        """Dew-point temperature [K] from Σ y_i / K_i(T,P,y) = 1."""
        yarr = self._as_array(y)
        T = float(T_guess)
        for _ in range(max_iter):
            K = self.K_values(T, P_Pa, yarr)
            f = float(np.dot(yarr, 1.0 / K)) - 1.0
            if abs(f) < tol:
                return T
            K_plus = self.K_values(T + 0.5, P_Pa, yarr)
            dfdT = (float(np.dot(yarr, 1.0 / K_plus - 1.0 / K))) / 0.5
            if abs(dfdT) < 1e-15:
                break
            T -= f / dfdT
        return float("nan")

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(method={self.method_name!r}, "
            f"species={self.species!r})"
        )


# ── Concrete: ideal-gas / Raoult-Antoine ─────────────────────────────────────


class IdealGasPackage(PropertyPackage):
    """Ideal-gas vapour phase + Raoult-Antoine VLE.

    Wraps the existing Shomate / Antoine functions so v1.5.3 flowsheets get
    byte-identical numerics. Liquid-phase density and Cp are not modelled here
    — callers that need a liquid phase should select a cubic-EOS or activity
    model package instead.
    """

    method_name = "ideal_gas"

    def __init__(self, species: Sequence[str]) -> None:
        super().__init__(species)
        # A species is usable by the ideal-gas package if it has *either*
        # Shomate (for enthalpy/Cp) or Antoine (for K-values). v1.5.3 ships
        # mixtures with light gases (Shomate-only) and solvents (Antoine-only)
        # coexisting, so we accept either and let the call-site filter handle
        # missing data per dimension.
        missing = [
            sp
            for sp in self.species
            if sp not in _ig.SHOMATE and sp not in _vle.ANTOINE
        ]
        if missing:
            raise ValueError(
                f"IdealGasPackage requires either Shomate or Antoine "
                f"coefficients for every species; missing both for: "
                f"{missing}. Extend the component registry in "
                f"pse_ecosystem/models/properties/components.py or select a "
                f"cubic-EOS / activity-model package (PR/SRK/NRTL)."
            )

    def K_values(
        self, T_K: float, P_Pa: float, z: Optional[Sequence[float]] = None
    ) -> np.ndarray:
        Ks = np.empty(len(self.species), dtype=float)
        for i, sp in enumerate(self.species):
            if sp in _vle.ANTOINE:
                Ks[i] = _vle.K_value(sp, T_K, P_Pa)
            else:
                # Permanent gas / supercritical species — Antoine extrapolation
                # is meaningless. Return a large K so any flash routine treats
                # it as fully vapour at typical (T, P).
                Ks[i] = 1.0e6
        return Ks

    def enthalpy(
        self,
        T_K: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
        T_ref_K: float = 298.15,
    ) -> float:
        zarr = self._as_array(z)
        return _ig.mixture_enthalpy_J_mol(
            self._composition_dict(zarr), T_K, T_ref_K
        )

    def Cp(
        self, T_K: float, z: Sequence[float], phase: str = PHASE_VAPOR
    ) -> float:
        zarr = self._as_array(z)
        return _ig.mixture_cp_J_mol_K(self._composition_dict(zarr), T_K)

    def density(
        self,
        T_K: float,
        P_Pa: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
    ) -> float:
        if phase == PHASE_VAPOR:
            # ρ_molar = P / (R T); composition independent for ideal gas.
            return P_Pa / (_R_GAS * T_K)
        raise NotImplementedError(
            f"IdealGasPackage does not model the {phase!r} phase. "
            f"Select a cubic-EOS (peng_robinson, srk) or activity-model "
            f"(nrtl, wilson, uniquac) package for liquid-phase density."
        )


# ── Factory / registry ───────────────────────────────────────────────────────


_PackageFactory = Callable[[Sequence[str]], PropertyPackage]
_REGISTRY: Dict[str, _PackageFactory] = {}


def register_package(method: str, factory: _PackageFactory) -> None:
    """Register a property-package factory under the *method* key (lower-case)."""
    _REGISTRY[method.strip().lower()] = factory


def available_methods() -> List[str]:
    """Sorted list of registered method keys."""
    return sorted(_REGISTRY)


def get_property_package(
    method: Optional[str], species: Sequence[str]
) -> PropertyPackage:
    """Return a property-package instance for *method* over *species*.

    Empty / ``None`` *method* defaults to ``ideal_gas``. Method names are
    matched case-insensitively. Reserved keys (``peng_robinson``, ``srk``,
    ``nrtl``, ``wilson``, ``uniquac``, ``pr_nrtl``) raise
    :class:`NotImplementedError` until the corresponding packages land.
    """
    key = (method or "ideal_gas").strip().lower()
    if key not in _REGISTRY:
        raise ValueError(
            f"Unknown property method {method!r}. "
            f"Known methods: {available_methods()}."
        )
    return _REGISTRY[key](species)


# ── Built-in registrations ───────────────────────────────────────────────────


register_package("ideal_gas", IdealGasPackage)


def _reserved_factory(method: str) -> _PackageFactory:
    def _factory(species: Sequence[str]) -> PropertyPackage:
        raise NotImplementedError(
            f"Property method {method!r} is reserved for v1.6 but not yet "
            f"implemented. Use 'ideal_gas' for now or wait for the C.3 / C.4 "
            f"sub-tasks of the v1.6 thermo workstream."
        )

    return _factory


for _reserved in ("pr_nrtl",):
    register_package(_reserved, _reserved_factory(_reserved))

# peng_robinson / srk are registered concretely by ``cubic_eos.py`` and
# nrtl / wilson / uniquac by ``activity_models.py``. Importing those here
# would create circular dependencies, so the registrations are triggered by
# ``__init__.py``.


__all__ = [
    "PHASE_VAPOR",
    "PHASE_LIQUID",
    "PropertyPackage",
    "IdealGasPackage",
    "available_methods",
    "get_property_package",
    "register_package",
]
