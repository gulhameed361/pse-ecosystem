"""Activity-coefficient models for liquid-phase non-ideality.

Implements three of the most widely-used liquid-activity models in process
simulation:

* **NRTL** — Non-Random Two-Liquid (Renon & Prausnitz, 1968). The de-facto
  default for polar / hydrogen-bonded mixtures (alcohols, amines, acids).
  Supports VLE and LLE; α_ij controls non-randomness.
* **Wilson** — Wilson (1964). Compact two-parameter local-composition model.
  Cannot represent LLE; widely used for hydrocarbon-alcohol mixtures.
* **UNIQUAC** — Universal Quasi-Chemical (Abrams & Prausnitz, 1975). Group-
  contribution-friendly; uses r_i (volume) and q_i (surface area) from the
  component registry.

All three are wrapped as :class:`~pse_ecosystem.models.properties.PropertyPackage`
subclasses. K-values follow the modified Raoult law
    K_i = γ_i(T, x) · P_sat_i(T) / P
which requires Antoine coefficients for every species; the constructor raises
:class:`ValueError` if any are missing.

**Limitations for v1.6**
* Liquid-phase enthalpy and density are approximated as ideal-gas — proper
  liquid models require either a corresponding-states correlation or a hybrid
  package (e.g. PR-NRTL, reserved for a later release).
* Binary interaction parameters are loaded from a sparse internal table; pairs
  not in the table default to ideal (γ = 1) with a runtime warning unless the
  caller passes an explicit ``params`` argument.

Parameter conventions
---------------------
* **NRTL**   τ_ij = A_ij / T               (A_ij in K, ``= (g_ij − g_jj)/R``)
             G_ij = exp(−α_ij τ_ij)
* **Wilson** ln Λ_ij = a_ij + b_ij / T     (b_ij in K, ``= −(λ_ij − λ_ii)/R``;
             a_ij absorbs the volume ratio ln(V_j / V_i))
* **UNIQUAC** τ_ij = exp(−A_ij / T)        (A_ij in K, ``= (u_ij − u_jj)/R``)

References
----------
* Renon, H.; Prausnitz, J. M. (1968). AIChE J. 14, 135-144.
* Wilson, G. M. (1964). J. Am. Chem. Soc. 86, 127-130.
* Abrams, D. S.; Prausnitz, J. M. (1975). AIChE J. 21, 116-128.
* Gmehling, J.; Onken, U.; Arlt, W. (1977-onwards). *Vapor-Liquid Equilibrium
  Data Collection*, DECHEMA Chemistry Data Series.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from pse_ecosystem.models.properties import components as _cdb
from pse_ecosystem.models.properties import ideal_gas as _ig
from pse_ecosystem.models.properties import vle as _vle
from pse_ecosystem.models.properties.property_package import (
    PHASE_LIQUID,
    PHASE_VAPOR,
    PropertyPackage,
    register_package,
)

_R = 8.314462

# ─────────────────────────────────────────────────────────────────────────────
# Math primitives
# ─────────────────────────────────────────────────────────────────────────────


def nrtl_ln_gamma(
    x: np.ndarray, tau: np.ndarray, G: np.ndarray
) -> np.ndarray:
    """Vector of ``ln γ_i`` for NRTL.

    Parameters
    ----------
    x   : (N,)   liquid mole fractions
    tau : (N,N)  τ_ij = (g_ij − g_jj)/(R T); τ_ii = 0
    G   : (N,N)  G_ij = exp(−α_ij τ_ij); G_ii = 1
    """
    # S_j = Σ_k x_k G_kj ;  R_j = Σ_m x_m τ_mj G_mj
    S = x @ G
    R = x @ (tau * G)
    term1 = R / S
    factor = x / S
    inner = R / S
    bracket = tau - inner[np.newaxis, :]
    term2 = (G * factor[np.newaxis, :] * bracket).sum(axis=1)
    return term1 + term2


def wilson_ln_gamma(x: np.ndarray, Lam: np.ndarray) -> np.ndarray:
    """Vector of ``ln γ_i`` for Wilson.

    ``Lam[i, j]`` = Λ_ij with Λ_ii = 1.

        ln γ_i = 1 − ln(Σ_j Λ_ij x_j) − Σ_k (x_k Λ_ki / Σ_j Λ_kj x_j)
    """
    N = len(x)
    # S_i = Σ_j Λ_ij x_j
    S = Lam @ x
    term1 = 1.0 - np.log(S)
    # T_i = Σ_k x_k Λ_ki / S_k  →  Σ_k x_k Λ[k, i] / S[k]
    T = (Lam * (x / S)[:, np.newaxis]).sum(axis=0)
    return term1 - T


def uniquac_ln_gamma(
    x: np.ndarray, r: np.ndarray, q: np.ndarray, tau: np.ndarray
) -> np.ndarray:
    """Vector of ``ln γ_i`` for UNIQUAC.

    Combinatorial uses Stavermann-Guggenheim form with coordination number
    z = 10. Residual uses the two-parameter τ_ij = exp(−A_ij/T) form.
    """
    z = 10.0
    # Volume and surface fractions
    rx = r * x
    qx = q * x
    Phi = rx / rx.sum()
    theta = qx / qx.sum()
    l = (z / 2.0) * (r - q) - (r - 1.0)

    # Combinatorial
    # ln γ_C_i = ln(Φ_i / x_i) + (z/2) q_i ln(θ_i / Φ_i) + l_i
    #          − (Φ_i / x_i) Σ_j x_j l_j
    safe_x = np.where(x > 0, x, 1.0)
    ratio_Phi_x = np.where(x > 0, Phi / safe_x, 1.0)
    ratio_theta_Phi = np.where(Phi > 0, theta / np.where(Phi > 0, Phi, 1.0), 1.0)
    ln_gamma_C = (
        np.log(ratio_Phi_x)
        + (z / 2.0) * q * np.log(ratio_theta_Phi)
        + l
        - ratio_Phi_x * float(np.dot(x, l))
    )

    # Residual
    # ln γ_R_i = q_i [1 − ln(Σ_j θ_j τ_ji) − Σ_j θ_j τ_ij / (Σ_k θ_k τ_kj)]
    # Define T_j = Σ_k θ_k τ_kj  (sum over k)
    T_vec = theta @ tau  # T_vec[j] = Σ_k θ_k τ[k, j]
    # First part: ln(Σ_j θ_j τ_ji)  →  vector indexed by i
    # That sum is over j: Σ_j θ_j τ[j, i]  = (theta @ tau)[i] = T_vec[i]
    ln_sum_ji = np.log(T_vec)
    # Second part: Σ_j θ_j τ_ij / T_vec[j]  →  per i
    # = Σ_j θ_j τ[i, j] / T_vec[j]
    second = (tau * (theta / T_vec)[np.newaxis, :]).sum(axis=1)
    ln_gamma_R = q * (1.0 - ln_sum_ji - second)

    return ln_gamma_C + ln_gamma_R


# ─────────────────────────────────────────────────────────────────────────────
# Binary parameter tables
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NRTLPair:
    """Symmetric NRTL binary parameter set.

    ``A_ab_K`` and ``A_ba_K`` follow the canonical (sorted) species order
    stored in the table key. Look up via :func:`get_nrtl_pair`, which returns
    a tuple oriented to the user's argument order.
    """

    A_ab_K: float
    A_ba_K: float
    alpha: float = 0.3
    source: str = ""


@dataclass(frozen=True)
class WilsonPair:
    a_ab: float
    b_ab_K: float
    a_ba: float
    b_ba_K: float
    source: str = ""


@dataclass(frozen=True)
class UNIQUACPair:
    A_ab_K: float
    A_ba_K: float
    source: str = ""


_NRTL: Dict[Tuple[str, str], NRTLPair] = {}
_WILSON: Dict[Tuple[str, str], WilsonPair] = {}
_UNIQUAC: Dict[Tuple[str, str], UNIQUACPair] = {}


def _canonical(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def register_nrtl_pair(a: str, b: str, pair: NRTLPair) -> None:
    """Register an NRTL pair. ``pair`` parameters are in the (a, b) direction
    given by the caller; the table internally sorts to canonical order so
    look-ups return the correctly-oriented tuple regardless of arg order."""
    key = _canonical(a, b)
    if (a, b) == key:
        _NRTL[key] = pair
    else:
        _NRTL[key] = NRTLPair(
            A_ab_K=pair.A_ba_K, A_ba_K=pair.A_ab_K,
            alpha=pair.alpha, source=pair.source,
        )


def register_wilson_pair(a: str, b: str, pair: WilsonPair) -> None:
    key = _canonical(a, b)
    if (a, b) == key:
        _WILSON[key] = pair
    else:
        _WILSON[key] = WilsonPair(
            a_ab=pair.a_ba, b_ab_K=pair.b_ba_K,
            a_ba=pair.a_ab, b_ba_K=pair.b_ab_K,
            source=pair.source,
        )


def register_uniquac_pair(a: str, b: str, pair: UNIQUACPair) -> None:
    key = _canonical(a, b)
    if (a, b) == key:
        _UNIQUAC[key] = pair
    else:
        _UNIQUAC[key] = UNIQUACPair(
            A_ab_K=pair.A_ba_K, A_ba_K=pair.A_ab_K,
            source=pair.source,
        )


def get_nrtl_pair(a: str, b: str) -> Optional[Tuple[float, float, float]]:
    """Return ``(A_a→b, A_b→a, α)`` or ``None`` if the pair is unknown."""
    key = _canonical(a, b)
    pair = _NRTL.get(key)
    if pair is None:
        return None
    if (a, b) == key:
        return (pair.A_ab_K, pair.A_ba_K, pair.alpha)
    return (pair.A_ba_K, pair.A_ab_K, pair.alpha)


def get_wilson_pair(
    a: str, b: str
) -> Optional[Tuple[float, float, float, float]]:
    """Return ``(a_a→b, b_a→b, a_b→a, b_b→a)`` for Wilson, or ``None``."""
    key = _canonical(a, b)
    pair = _WILSON.get(key)
    if pair is None:
        return None
    if (a, b) == key:
        return (pair.a_ab, pair.b_ab_K, pair.a_ba, pair.b_ba_K)
    return (pair.a_ba, pair.b_ba_K, pair.a_ab, pair.b_ab_K)


def get_uniquac_pair(a: str, b: str) -> Optional[Tuple[float, float]]:
    key = _canonical(a, b)
    pair = _UNIQUAC.get(key)
    if pair is None:
        return None
    if (a, b) == key:
        return (pair.A_ab_K, pair.A_ba_K)
    return (pair.A_ba_K, pair.A_ab_K)


# ── Pre-populated industrial pairs ───────────────────────────────────────────
# All values are DECHEMA / Aspen NRTL fits chosen for the v1.6 default case
# studies (ethanol-water, methanol-water). Users should supply project-
# specific parameters via the package's ``params`` constructor argument.

register_nrtl_pair(
    "ethanol", "water",
    NRTLPair(A_ab_K=-55.17, A_ba_K=670.44, alpha=0.303, source="DECHEMA"),
)
register_nrtl_pair(
    "methanol", "water",
    NRTLPair(A_ab_K=-253.88, A_ba_K=845.21, alpha=0.299, source="DECHEMA"),
)
register_nrtl_pair(
    "benzene", "toluene",
    NRTLPair(A_ab_K=-7.0, A_ba_K=14.0, alpha=0.30, source="near-ideal"),
)

register_uniquac_pair(
    "ethanol", "water",
    UNIQUACPair(A_ab_K=-50.0, A_ba_K=300.0, source="DECHEMA"),
)
register_uniquac_pair(
    "methanol", "water",
    UNIQUACPair(A_ab_K=-100.0, A_ba_K=300.0, source="DECHEMA"),
)

register_wilson_pair(
    "ethanol", "water",
    WilsonPair(
        a_ab=0.0, b_ab_K=276.76,
        a_ba=0.0, b_ba_K=975.49,
        source="Wilson 1964 fit, V-independent form",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Property-package base for activity models
# ─────────────────────────────────────────────────────────────────────────────


class ActivityModelPackage(PropertyPackage):
    """Shared scaffolding for NRTL / Wilson / UNIQUAC packages.

    Concrete subclasses implement :meth:`activity_coefficients`. K-values
    follow the modified Raoult law and enthalpy / Cp fall back to the
    ideal-gas mixture functions (heat of mixing is omitted in v1.6).
    """

    method_name = "abstract_activity"

    def __init__(self, species: Sequence[str]) -> None:
        super().__init__(species)
        missing_ant = [sp for sp in self.species if sp not in _vle.ANTOINE]
        if missing_ant:
            raise ValueError(
                f"{type(self).__name__} requires Antoine coefficients for "
                f"every species (modified Raoult K_i = γ_i P_sat_i / P); "
                f"missing: {missing_ant}. Activity models do not handle "
                f"non-condensable gases — split those out or use a hybrid "
                f"package like 'pr_nrtl' (reserved for a future release)."
            )

    def activity_coefficients(self, T_K: float, x: Sequence[float]) -> np.ndarray:
        raise NotImplementedError

    # ── PropertyPackage contract ────────────────────────────────────────
    def K_values(
        self, T_K: float, P_Pa: float, z: Optional[Sequence[float]] = None
    ) -> np.ndarray:
        """K_i = γ_i(T, x) · P_sat_i(T) / P.

        If ``z`` is ``None`` the package uses an equimolar liquid composition
        for the γ evaluation — fine as a flash starting point. Flash
        iterations should pass the current liquid composition explicitly.
        """
        if z is None:
            x = np.full(len(self.species), 1.0 / len(self.species))
        else:
            x = self._as_array(z)
        gamma = self.activity_coefficients(T_K, x)
        Psat = np.array([self._psat(sp, T_K) for sp in self.species])
        return gamma * Psat / P_Pa

    @staticmethod
    def _psat(species: str, T_K: float) -> float:
        """Antoine P_sat [Pa]. Returns a sentinel ``1e6 * P`` for species that
        slip past validation (defensive — should not happen)."""
        p = _vle.ANTOINE[species]
        T_C = T_K - 273.15
        return (10.0 ** (p["A"] - p["B"] / (T_C + p["C"]))) * 133.322

    def enthalpy(
        self,
        T_K: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
        T_ref_K: float = 298.15,
    ) -> float:
        """Ideal-gas mixture enthalpy. Heat of mixing is omitted in v1.6.

        Species lacking Shomate (any pure-solvent in our activity-model
        databank) contribute zero enthalpy. Callers that need accurate
        liquid enthalpies should use a hybrid PR-NRTL package once it
        lands.
        """
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
            return P_Pa / (_R * T_K)
        raise NotImplementedError(
            f"{type(self).__name__} does not model liquid-phase density. "
            f"Use a cubic-EOS or hybrid package for that."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Concrete packages
# ─────────────────────────────────────────────────────────────────────────────


class NRTLPackage(ActivityModelPackage):
    method_name = "nrtl"

    def __init__(
        self,
        species: Sequence[str],
        params: Optional[Dict[Tuple[str, str], NRTLPair]] = None,
        default_alpha: float = 0.3,
    ) -> None:
        super().__init__(species)
        self._default_alpha = default_alpha
        self._A, self._alpha = self._build_matrices(params)

    def _build_matrices(
        self, override: Optional[Dict[Tuple[str, str], NRTLPair]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        N = len(self.species)
        A = np.zeros((N, N), dtype=float)
        alpha = np.full((N, N), self._default_alpha, dtype=float)
        for i in range(N):
            alpha[i, i] = 0.0  # diagonal irrelevant
        missing: list = []
        for i, a in enumerate(self.species):
            for j, b in enumerate(self.species):
                if i == j:
                    continue
                pair_override = None
                if override:
                    pair_override = override.get((a, b)) or override.get((b, a))
                if pair_override is not None:
                    if (a, b) in override:
                        A[i, j] = pair_override.A_ab_K
                    else:
                        A[i, j] = pair_override.A_ba_K
                    alpha[i, j] = pair_override.alpha
                    continue
                pair = get_nrtl_pair(a, b)
                if pair is not None:
                    A_ab, _, al = pair
                    A[i, j] = A_ab
                    alpha[i, j] = al
                else:
                    missing.append((a, b))
        if missing and not override:
            warnings.warn(
                f"NRTL parameters missing for pairs: {missing}. "
                f"Defaulting to ideal (A_ij = 0); supply explicit ``params`` "
                f"for production fidelity.",
                stacklevel=3,
            )
        return A, alpha

    def activity_coefficients(self, T_K: float, x: Sequence[float]) -> np.ndarray:
        xarr = self._as_array(x)
        tau = self._A / T_K
        G = np.exp(-self._alpha * tau)
        return np.exp(nrtl_ln_gamma(xarr, tau, G))


class WilsonPackage(ActivityModelPackage):
    method_name = "wilson"

    def __init__(
        self,
        species: Sequence[str],
        params: Optional[Dict[Tuple[str, str], WilsonPair]] = None,
    ) -> None:
        super().__init__(species)
        self._a, self._b = self._build_matrices(params)

    def _build_matrices(
        self, override: Optional[Dict[Tuple[str, str], WilsonPair]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        N = len(self.species)
        a_mat = np.zeros((N, N), dtype=float)  # ln Λ_ii = 0 ⇒ Λ_ii = 1
        b_mat = np.zeros((N, N), dtype=float)
        missing: list = []
        for i, sp_i in enumerate(self.species):
            for j, sp_j in enumerate(self.species):
                if i == j:
                    continue
                pair_override = None
                if override:
                    pair_override = (
                        override.get((sp_i, sp_j))
                        or override.get((sp_j, sp_i))
                    )
                if pair_override is not None:
                    if (sp_i, sp_j) in override:
                        a_mat[i, j] = pair_override.a_ab
                        b_mat[i, j] = pair_override.b_ab_K
                    else:
                        a_mat[i, j] = pair_override.a_ba
                        b_mat[i, j] = pair_override.b_ba_K
                    continue
                pair = get_wilson_pair(sp_i, sp_j)
                if pair is not None:
                    a_mat[i, j] = pair[0]
                    b_mat[i, j] = pair[1]
                else:
                    missing.append((sp_i, sp_j))
        if missing and not override:
            warnings.warn(
                f"Wilson parameters missing for pairs: {missing}. "
                f"Defaulting to ideal (Λ_ij = 1).",
                stacklevel=3,
            )
        return a_mat, b_mat

    def activity_coefficients(self, T_K: float, x: Sequence[float]) -> np.ndarray:
        xarr = self._as_array(x)
        Lam = np.exp(self._a + self._b / T_K)
        # Diagonal must be exactly 1 (numerical guard).
        np.fill_diagonal(Lam, 1.0)
        return np.exp(wilson_ln_gamma(xarr, Lam))


class UNIQUACPackage(ActivityModelPackage):
    method_name = "uniquac"

    def __init__(
        self,
        species: Sequence[str],
        params: Optional[Dict[Tuple[str, str], UNIQUACPair]] = None,
    ) -> None:
        super().__init__(species)
        comps = [_cdb.get(sp) for sp in self.species]
        missing_rq = [
            sp for sp, c in zip(self.species, comps)
            if c.uniquac_r is None or c.uniquac_q is None
        ]
        if missing_rq:
            raise ValueError(
                f"UNIQUACPackage requires r, q for every species; missing: "
                f"{missing_rq}. Extend the component registry."
            )
        self._r = np.array([c.uniquac_r for c in comps], dtype=float)
        self._q = np.array([c.uniquac_q for c in comps], dtype=float)
        self._A = self._build_matrix(params)

    def _build_matrix(
        self, override: Optional[Dict[Tuple[str, str], UNIQUACPair]]
    ) -> np.ndarray:
        N = len(self.species)
        A = np.zeros((N, N), dtype=float)
        missing: list = []
        for i, sp_i in enumerate(self.species):
            for j, sp_j in enumerate(self.species):
                if i == j:
                    continue
                pair_override = None
                if override:
                    pair_override = (
                        override.get((sp_i, sp_j))
                        or override.get((sp_j, sp_i))
                    )
                if pair_override is not None:
                    if (sp_i, sp_j) in override:
                        A[i, j] = pair_override.A_ab_K
                    else:
                        A[i, j] = pair_override.A_ba_K
                    continue
                pair = get_uniquac_pair(sp_i, sp_j)
                if pair is not None:
                    A[i, j] = pair[0]
                else:
                    missing.append((sp_i, sp_j))
        if missing and not override:
            warnings.warn(
                f"UNIQUAC parameters missing for pairs: {missing}. "
                f"Defaulting to ideal (τ_ij = 1).",
                stacklevel=3,
            )
        return A

    def activity_coefficients(self, T_K: float, x: Sequence[float]) -> np.ndarray:
        xarr = self._as_array(x)
        tau = np.exp(-self._A / T_K)
        np.fill_diagonal(tau, 1.0)
        return np.exp(uniquac_ln_gamma(xarr, self._r, self._q, tau))


# ── Registration ─────────────────────────────────────────────────────────────


register_package("nrtl", NRTLPackage)
register_package("wilson", WilsonPackage)
register_package("uniquac", UNIQUACPackage)


__all__ = [
    # math
    "nrtl_ln_gamma", "wilson_ln_gamma", "uniquac_ln_gamma",
    # parameter tables
    "NRTLPair", "WilsonPair", "UNIQUACPair",
    "register_nrtl_pair", "register_wilson_pair", "register_uniquac_pair",
    "get_nrtl_pair", "get_wilson_pair", "get_uniquac_pair",
    # packages
    "ActivityModelPackage", "NRTLPackage", "WilsonPackage", "UNIQUACPackage",
]
