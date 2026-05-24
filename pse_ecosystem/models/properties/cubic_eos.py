"""Cubic equation of state — Peng-Robinson and SRK.

Both EOSs share the unified form
    P = R T / (v − b) − a(T) / (v² + u b v + w b²)
with (u, w) = (2, −1) for PR and (1, 0) for SRK. Pure-component a and b are
fixed by the critical triple (Tc, Pc, ω) from the component registry; α(T)
uses Soave-style polynomials in ω.

In dimensionless form, with A = a P / (R T)² and B = b P / (R T), the cubic
in compressibility factor Z reduces to
    PR:   Z³ − (1 − B) Z² + (A − 3 B² − 2 B) Z − (A B − B² − B³) = 0
    SRK:  Z³ − Z² + (A − B − B²) Z − A B = 0

For mixtures the van der Waals one-fluid mixing rule applies:
    a_mix = Σ_i Σ_j y_i y_j (1 − k_ij) √(a_i a_j)
    b_mix = Σ_i y_i b_i
with binary interaction parameters ``k_ij`` defaulting to zero. A dedicated
``binary_interactions`` module is planned for v1.6+ and will populate the
``kij_table`` argument of :class:`CubicEOSPackage`.

K-values returned by the high-level packages are the **Wilson approximation**
    K_i = (Pc_i / P) · exp(5.373 (1 + ω_i) (1 − Tc_i / T))
which is the standard initial estimate for any cubic-EOS flash. Rigorous K
from φ_L / φ_V comes via :func:`fugacity_coeffs`, exposed for use by the
generic flash routine landing in sub-task C.5 of the v1.6 thermo workstream.

Every species used by :class:`PengRobinsonPackage` / :class:`SRKPackage` must
have **both** Shomate coefficients (so the ideal-gas reference Cp / H is
defined) **and** the (Tc, Pc, ω) triple (so the EOS itself is defined). The
constructor raises ``ValueError`` if either is missing.

References
----------
* Peng, D-Y.; Robinson, D.B. (1976). "A New Two-Constant Equation of State."
  Ind. Eng. Chem. Fundam. 15, 59-64.
* Soave, G. (1972). "Equilibrium constants from a modified Redlich-Kwong
  equation of state." Chem. Eng. Sci. 27, 1197-1203.
* Reid, R.C.; Prausnitz, J.M.; Poling, B.E. (1987). *The Properties of Gases
  and Liquids*, 4th ed., Ch. 3.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from pse_ecosystem.models.properties import components as _cdb
from pse_ecosystem.models.properties import ideal_gas as _ig
from pse_ecosystem.models.properties.property_package import (
    PHASE_LIQUID,
    PHASE_VAPOR,
    PropertyPackage,
    register_package,
)

_R = 8.314462  # J/mol/K
_SQRT2 = math.sqrt(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# Pure-component a, b, α and their temperature derivatives
# ─────────────────────────────────────────────────────────────────────────────


def _kappa_PR(omega: float) -> float:
    """PR α-function temperature coefficient κ(ω)."""
    return 0.37464 + 1.54226 * omega - 0.26992 * omega * omega


def _m_SRK(omega: float) -> float:
    """SRK α-function temperature coefficient m(ω)."""
    return 0.480 + 1.574 * omega - 0.176 * omega * omega


def _ac_PR(Tc_K: float, Pc_Pa: float) -> float:
    """PR temperature-independent ``a_c`` prefactor [Pa·m⁶/mol²]."""
    return 0.45724 * (_R * Tc_K) ** 2 / Pc_Pa


def _ac_SRK(Tc_K: float, Pc_Pa: float) -> float:
    return 0.42748 * (_R * Tc_K) ** 2 / Pc_Pa


def _b_PR(Tc_K: float, Pc_Pa: float) -> float:
    """PR co-volume parameter b [m³/mol]."""
    return 0.07780 * _R * Tc_K / Pc_Pa


def _b_SRK(Tc_K: float, Pc_Pa: float) -> float:
    return 0.08664 * _R * Tc_K / Pc_Pa


def alpha(T_K: float, Tc_K: float, omega: float, eos: str = "PR") -> float:
    """Soave α(T) for the chosen EOS — α = [1 + κ (1 − √(T/Tc))]²."""
    if eos == "PR":
        k = _kappa_PR(omega)
    elif eos == "SRK":
        k = _m_SRK(omega)
    else:
        raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")
    inner = 1.0 + k * (1.0 - math.sqrt(T_K / Tc_K))
    return inner * inner


def a_pure(T_K: float, Tc_K: float, Pc_Pa: float, omega: float, eos: str = "PR") -> float:
    """Pure-component attractive parameter a(T) [Pa·m⁶/mol²]."""
    if eos == "PR":
        return _ac_PR(Tc_K, Pc_Pa) * alpha(T_K, Tc_K, omega, "PR")
    if eos == "SRK":
        return _ac_SRK(Tc_K, Pc_Pa) * alpha(T_K, Tc_K, omega, "SRK")
    raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")


def b_pure(Tc_K: float, Pc_Pa: float, eos: str = "PR") -> float:
    if eos == "PR":
        return _b_PR(Tc_K, Pc_Pa)
    if eos == "SRK":
        return _b_SRK(Tc_K, Pc_Pa)
    raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")


def da_dT_pure(
    T_K: float, Tc_K: float, Pc_Pa: float, omega: float, eos: str = "PR"
) -> float:
    """∂a/∂T for a pure component [Pa·m⁶/(mol²·K)].

    Derived analytically: with α(T) = [1 + κ (1 − √(T/Tc))]²,
        ∂α/∂T = −κ √α / √(T·Tc)
    so ∂a/∂T = a_c · ∂α/∂T.
    """
    if eos == "PR":
        ac = _ac_PR(Tc_K, Pc_Pa)
        k = _kappa_PR(omega)
    elif eos == "SRK":
        ac = _ac_SRK(Tc_K, Pc_Pa)
        k = _m_SRK(omega)
    else:
        raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")
    a_val = ac * alpha(T_K, Tc_K, omega, eos)
    return -ac * k * math.sqrt(a_val / ac) / math.sqrt(T_K * Tc_K)


# ─────────────────────────────────────────────────────────────────────────────
# Mixture mixing rules
# ─────────────────────────────────────────────────────────────────────────────


def mix_a_b(
    z: np.ndarray,
    a_vec: np.ndarray,
    b_vec: np.ndarray,
    kij: np.ndarray,
) -> Tuple[float, float, np.ndarray]:
    """Van der Waals one-fluid mixing.

    Returns
    -------
    a_mix : float
    b_mix : float
    a_ij  : (N, N) matrix of (1 − k_ij) √(a_i a_j) — needed for fugacity.
    """
    sqrt_a = np.sqrt(a_vec)
    a_ij = (1.0 - kij) * np.outer(sqrt_a, sqrt_a)
    a_mix = float(z @ a_ij @ z)
    b_mix = float(z @ b_vec)
    return a_mix, b_mix, a_ij


# ─────────────────────────────────────────────────────────────────────────────
# Cubic-Z solver
# ─────────────────────────────────────────────────────────────────────────────


def solve_Z(A: float, B: float, eos: str = "PR") -> List[float]:
    """Real roots of the cubic in Z for the chosen EOS, in ascending order.

    Returned roots are filtered to those with Z > B (positive molar volume
    above the co-volume), which is the physical constraint v > b.
    """
    if eos == "PR":
        # Z³ − (1 − B) Z² + (A − 3B² − 2B) Z − (AB − B² − B³) = 0
        c2 = -(1.0 - B)
        c1 = A - 3.0 * B * B - 2.0 * B
        c0 = -(A * B - B * B - B ** 3)
    elif eos == "SRK":
        c2 = -1.0
        c1 = A - B - B * B
        c0 = -A * B
    else:
        raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")

    roots = np.roots([1.0, c2, c1, c0])
    real_roots = sorted(
        float(r.real) for r in roots if abs(r.imag) < 1e-9 and r.real > B
    )
    return real_roots


def Z_phase(A: float, B: float, phase: str, eos: str = "PR") -> float:
    """Select the physically appropriate Z root for *phase*.

    * Vapor: largest real root.
    * Liquid: smallest real root.

    If only one real root is available (supercritical region) both phases
    collapse to it.
    """
    roots = solve_Z(A, B, eos)
    if not roots:
        raise RuntimeError(
            f"No physical Z root found for {eos} at A={A:.4g}, B={B:.4g}. "
            f"Check that the input (T, P, z) is in a region where the EOS "
            f"has a solution."
        )
    if phase == PHASE_VAPOR:
        return roots[-1]
    if phase == PHASE_LIQUID:
        return roots[0]
    raise ValueError(f"Unknown phase {phase!r}; expected 'vapor' or 'liquid'")


# ─────────────────────────────────────────────────────────────────────────────
# Fugacity coefficients (mixture, component-i form)
# ─────────────────────────────────────────────────────────────────────────────


def fugacity_coeffs(
    z: np.ndarray,
    T_K: float,
    P_Pa: float,
    Tc_K: np.ndarray,
    Pc_Pa: np.ndarray,
    omega: np.ndarray,
    kij: np.ndarray,
    phase: str,
    eos: str = "PR",
) -> np.ndarray:
    """Vector of fugacity coefficients φ_i for the requested phase.

    Implements the standard PR and SRK forms (Reid-Prausnitz-Poling §3-6):

    PR:
        ln φ_i = (b_i / b)(Z − 1) − ln(Z − B)
                 − A / (2 √2 B)
                   · [ 2 Σ_j z_j (1 − k_ij) √(a_i a_j) / a_mix − b_i / b ]
                   · ln[(Z + (1 + √2) B) / (Z + (1 − √2) B)]

    SRK:
        ln φ_i = (b_i / b)(Z − 1) − ln(Z − B)
                 − A / B
                   · [ 2 Σ_j z_j (1 − k_ij) √(a_i a_j) / a_mix − b_i / b ]
                   · ln[(Z + B) / Z]
    """
    N = len(z)
    a_vec = np.array(
        [a_pure(T_K, Tc_K[i], Pc_Pa[i], omega[i], eos) for i in range(N)]
    )
    b_vec = np.array([b_pure(Tc_K[i], Pc_Pa[i], eos) for i in range(N)])
    a_mix, b_mix, a_ij = mix_a_b(z, a_vec, b_vec, kij)

    A = a_mix * P_Pa / (_R * T_K) ** 2
    B = b_mix * P_Pa / (_R * T_K)
    Z = Z_phase(A, B, phase, eos)

    # Σ_j z_j a_ij  =  row sums of (a_ij · z)
    sigma = a_ij @ z

    bi_over_b = b_vec / b_mix
    bracket = 2.0 * sigma / a_mix - bi_over_b

    ln_phi = bi_over_b * (Z - 1.0) - math.log(Z - B)

    if eos == "PR":
        log_term = math.log((Z + (1.0 + _SQRT2) * B) / (Z + (1.0 - _SQRT2) * B))
        ln_phi -= A / (2.0 * _SQRT2 * B) * bracket * log_term
    elif eos == "SRK":
        log_term = math.log((Z + B) / Z)
        ln_phi -= A / B * bracket * log_term
    else:
        raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")

    return np.exp(ln_phi)


# ─────────────────────────────────────────────────────────────────────────────
# Enthalpy and entropy departures
# ─────────────────────────────────────────────────────────────────────────────


def enthalpy_departure(
    z: np.ndarray,
    T_K: float,
    P_Pa: float,
    Tc_K: np.ndarray,
    Pc_Pa: np.ndarray,
    omega: np.ndarray,
    kij: np.ndarray,
    phase: str,
    eos: str = "PR",
) -> float:
    """Molar enthalpy departure H − H_ig [J/mol].

    PR:
        H_dep = (T da/dT − a) / (2 √2 b)
                · ln[(Z + (1+√2)B) / (Z + (1−√2)B)] + R T (Z − 1)
    SRK:
        H_dep = (T da/dT − a) / b · ln[Z / (Z + B)] + R T (Z − 1)
    """
    N = len(z)
    a_vec = np.array(
        [a_pure(T_K, Tc_K[i], Pc_Pa[i], omega[i], eos) for i in range(N)]
    )
    b_vec = np.array([b_pure(Tc_K[i], Pc_Pa[i], eos) for i in range(N)])
    dadT_vec = np.array(
        [da_dT_pure(T_K, Tc_K[i], Pc_Pa[i], omega[i], eos) for i in range(N)]
    )

    sqrt_a = np.sqrt(a_vec)
    a_mix, b_mix, _ = mix_a_b(z, a_vec, b_vec, kij)

    # da_mix/dT via chain rule on the geometric mean mixing rule.
    one_minus_k = 1.0 - kij
    # d[√(a_i a_j)]/dT = (sqrt_a_j · da_i/dT + sqrt_a_i · da_j/dT) / (2 sqrt(a_i a_j))
    # but we can express d(√(a_i a_j))/dT directly via factoring.
    # ∂a_mix/∂T = Σ_i Σ_j z_i z_j (1 - k_ij) · (da_i/dT · √(a_j/a_i)
    #                                          + da_j/dT · √(a_i/a_j)) / 2
    da_mix_dT = 0.0
    for i in range(N):
        for j in range(N):
            if a_vec[i] <= 0 or a_vec[j] <= 0:
                continue
            term = (
                dadT_vec[i] * sqrt_a[j] / sqrt_a[i]
                + dadT_vec[j] * sqrt_a[i] / sqrt_a[j]
            )
            da_mix_dT += 0.5 * z[i] * z[j] * one_minus_k[i, j] * term

    A = a_mix * P_Pa / (_R * T_K) ** 2
    B = b_mix * P_Pa / (_R * T_K)
    Z = Z_phase(A, B, phase, eos)

    if eos == "PR":
        log_term = math.log((Z + (1.0 + _SQRT2) * B) / (Z + (1.0 - _SQRT2) * B))
        H_dep = (T_K * da_mix_dT - a_mix) / (2.0 * _SQRT2 * b_mix) * log_term
    elif eos == "SRK":
        log_term = math.log(Z / (Z + B))
        H_dep = (T_K * da_mix_dT - a_mix) / b_mix * log_term
    else:
        raise ValueError(f"Unknown EOS {eos!r}; expected 'PR' or 'SRK'")

    H_dep += _R * T_K * (Z - 1.0)
    return H_dep


# ─────────────────────────────────────────────────────────────────────────────
# Wilson K-value approximation
# ─────────────────────────────────────────────────────────────────────────────


def wilson_K(T_K: float, P_Pa: float, Tc_K: float, Pc_Pa: float, omega: float) -> float:
    """Wilson initial-estimate K-value.

    K_i^Wilson = (Pc_i / P) · exp[5.373 (1 + ω_i) (1 − Tc_i / T)]

    Universally used as the start for cubic-EOS flash iterations because it
    is composition-independent, monotonic in T, and asymptotes correctly at
    high and low pressure.
    """
    return (Pc_Pa / P_Pa) * math.exp(5.373 * (1.0 + omega) * (1.0 - Tc_K / T_K))


# ─────────────────────────────────────────────────────────────────────────────
# Property-package wrappers
# ─────────────────────────────────────────────────────────────────────────────


class CubicEOSPackage(PropertyPackage):
    """Shared scaffolding for PR / SRK packages.

    Concrete subclasses override the ``EOS`` class attribute. The constructor
    pulls (Tc, Pc, ω) from the component registry and verifies every species
    also has Shomate coefficients so the ideal-gas reference Cp/H is defined.
    Binary interaction parameters default to zero; pass ``kij_table`` to
    inject a partial sparse table.
    """

    EOS: str = "PR"
    method_name: str = "abstract_cubic"

    def __init__(
        self,
        species: Sequence[str],
        kij_table: Optional[Dict[Tuple[str, str], float]] = None,
    ) -> None:
        super().__init__(species)
        missing_eos = [sp for sp in self.species if not _cdb.has_eos_params(sp)]
        if missing_eos:
            raise ValueError(
                f"{type(self).__name__} requires (Tc, Pc, ω) for every "
                f"species; missing: {missing_eos}. Extend the component "
                f"registry in pse_ecosystem/models/properties/components.py."
            )
        missing_ig = [sp for sp in self.species if sp not in _ig.SHOMATE]
        if missing_ig:
            raise ValueError(
                f"{type(self).__name__} requires Shomate coefficients for "
                f"the ideal-gas reference; missing: {missing_ig}. Add "
                f"Shomate entries to the Components for these species."
            )

        comps = [_cdb.get(sp) for sp in self.species]
        self._Tc = np.array([c.Tc_K for c in comps], dtype=float)
        self._Pc = np.array([c.Pc_Pa for c in comps], dtype=float)
        self._omega = np.array([c.omega for c in comps], dtype=float)
        self._kij = self._build_kij_matrix(kij_table)

    def _build_kij_matrix(
        self, kij_table: Optional[Dict[Tuple[str, str], float]]
    ) -> np.ndarray:
        N = len(self.species)
        kij = np.zeros((N, N), dtype=float)
        if kij_table:
            for (a, b), value in kij_table.items():
                if a not in self._index or b not in self._index:
                    continue
                i, j = self._index[a], self._index[b]
                kij[i, j] = value
                kij[j, i] = value
        return kij

    # ── PropertyPackage contract ────────────────────────────────────────
    def K_values(
        self, T_K: float, P_Pa: float, z: Optional[Sequence[float]] = None
    ) -> np.ndarray:
        """Wilson initial K-values (composition-independent).

        Rigorous φ-based K values come from the generic flash routine
        (sub-task C.5), which iterates on these estimates.
        """
        return np.array(
            [
                wilson_K(T_K, P_Pa, self._Tc[i], self._Pc[i], self._omega[i])
                for i in range(len(self.species))
            ]
        )

    def K_iteration(
        self,
        T_K: float,
        P_Pa: float,
        x: Sequence[float],
        y: Sequence[float],
    ) -> np.ndarray:
        """Rigorous flash-iteration K = φ_L(x) / φ_V(y) for cubic EOS."""
        phi_L = self.fugacity_coefficients(T_K, P_Pa, x, PHASE_LIQUID)
        phi_V = self.fugacity_coefficients(T_K, P_Pa, y, PHASE_VAPOR)
        return phi_L / phi_V

    def fugacity_coefficients(
        self, T_K: float, P_Pa: float, z: Sequence[float], phase: str
    ) -> np.ndarray:
        """Rigorous fugacity coefficients φ_i for a given phase.

        Exposed publicly because the generic flash in C.5 will iterate on
        K_i = φ_i^L / φ_i^V until composition convergence.
        """
        zarr = self._as_array(z)
        return fugacity_coeffs(
            zarr, T_K, P_Pa, self._Tc, self._Pc, self._omega,
            self._kij, phase, eos=self.EOS,
        )

    def enthalpy(
        self,
        T_K: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
        T_ref_K: float = 298.15,
    ) -> float:
        zarr = self._as_array(z)
        h_ig = _ig.mixture_enthalpy_J_mol(
            self._composition_dict(zarr), T_K, T_ref_K
        )
        # Pressure-state for departure: use 1 atm as the implicit reference
        # since the ideal-gas reference is at zero pressure. The departure
        # cancels the (T_ref, P) state, but the user only gave us T_K. For
        # consistency with how Aspen/Hysys define this, we evaluate the
        # departure at the *current* state (T_K, P_state) where P_state is
        # an attribute set by the caller via :meth:`set_pressure_state`.
        if self._pressure_state is None:
            return h_ig
        H_dep = enthalpy_departure(
            zarr, T_K, self._pressure_state, self._Tc, self._Pc,
            self._omega, self._kij, phase, eos=self.EOS,
        )
        return h_ig + H_dep

    def Cp(
        self, T_K: float, z: Sequence[float], phase: str = PHASE_VAPOR
    ) -> float:
        """Mixture Cp [J/mol/K].

        Returns the *ideal-gas* mixture Cp; cubic-EOS Cp departure is a
        small second-order correction at moderate (T, P) and is omitted for
        v1.6. Add by reusing :func:`enthalpy_departure` with a temperature
        finite difference if higher fidelity becomes necessary.
        """
        zarr = self._as_array(z)
        return _ig.mixture_cp_J_mol_K(self._composition_dict(zarr), T_K)

    def density(
        self,
        T_K: float,
        P_Pa: float,
        z: Sequence[float],
        phase: str = PHASE_VAPOR,
    ) -> float:
        """Molar density ρ_molar = P / (Z R T) [mol/m³]."""
        zarr = self._as_array(z)
        a_vec = np.array(
            [
                a_pure(T_K, self._Tc[i], self._Pc[i], self._omega[i], self.EOS)
                for i in range(len(self.species))
            ]
        )
        b_vec = np.array(
            [
                b_pure(self._Tc[i], self._Pc[i], self.EOS)
                for i in range(len(self.species))
            ]
        )
        a_mix, b_mix, _ = mix_a_b(zarr, a_vec, b_vec, self._kij)
        A = a_mix * P_Pa / (_R * T_K) ** 2
        B = b_mix * P_Pa / (_R * T_K)
        Z = Z_phase(A, B, phase, self.EOS)
        return P_Pa / (Z * _R * T_K)

    _pressure_state: Optional[float] = None

    def set_pressure_state(self, P_Pa: Optional[float]) -> None:
        """Set the pressure used for enthalpy-departure evaluation.

        Stream-level callers that want a real PR/SRK enthalpy (including the
        non-ideal pressure correction) should call this before
        :meth:`enthalpy`. ``None`` falls back to ideal-gas enthalpy.
        """
        self._pressure_state = P_Pa


class PengRobinsonPackage(CubicEOSPackage):
    """Peng-Robinson 1976 EOS — recommended for hydrocarbons + light gases."""

    EOS = "PR"
    method_name = "peng_robinson"


class SRKPackage(CubicEOSPackage):
    """Soave-Redlich-Kwong 1972 EOS — generally similar accuracy to PR."""

    EOS = "SRK"
    method_name = "srk"


# ── Registration ─────────────────────────────────────────────────────────────


register_package("peng_robinson", PengRobinsonPackage)
register_package("srk", SRKPackage)


__all__ = [
    # math primitives
    "alpha", "a_pure", "b_pure", "da_dT_pure",
    "mix_a_b", "solve_Z", "Z_phase",
    "fugacity_coeffs", "enthalpy_departure", "wilson_K",
    # packages
    "CubicEOSPackage", "PengRobinsonPackage", "SRKPackage",
]
