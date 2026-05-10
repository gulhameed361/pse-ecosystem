"""Simplified solid-liquid flash (dissolution model).

Models the dissolution of solid components into a liquid solvent.  The amount
dissolved is limited by the temperature-dependent solubility S_i(T).  A
softplus approximation is used for the min() function to maintain
differentiability for the SLP Jacobian.

Ports
-----
solid_in   : StreamPort  (m_solid_i [kg/s], T)
solvent_in : StreamPort  (m_solvent [kg/s], T)
solution   : StreamPort  (c_i [mol/m³], V_sol [m³/s], T_out)
solid_out  : StreamPort  (m_residual_i [kg/s])

Additional variables
---------------------
V_sol : volumetric flow rate of solution [m³/s]

Residuals (N + 2 equations)
-----------------------------
  Dissolved_i : c_i * V_sol - softmin(m_solid_i/MW_i, S_i(T)*V_sol) = 0  [N]
  Solvent vol : V_sol - m_solvent / rho_solvent = 0                         [1]
  Solid out_i : m_residual_i - max(m_solid_i - c_i*V_sol*MW_i, 0) = 0     [N]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class FlashSLParams:
    species: List[str] = field(default_factory=list)  # solute species names
    MW_kg_per_mol: Dict[str, float] = field(default_factory=dict)  # molar mass [kg/mol]
    # Solubility: S_i(T) [mol/m³] = S_ref_i * exp(dH_sol_i/R * (1/T_ref - 1/T))
    S_ref: Dict[str, float] = field(default_factory=dict)  # reference solubility [mol/m³] at T_ref
    dH_sol: Dict[str, float] = field(default_factory=dict)  # dissolution enthalpy [J/mol]
    T_ref_K: float = 298.15
    rho_solvent_kg_m3: float = 1000.0   # water by default
    feed_max_kg_s: float = 100.0
    T_min: float = 250.0
    T_max: float = 400.0
    softplus_alpha: float = 100.0   # sharpness of softmin approximation


def _softmin(a: float, b: float, alpha: float = 100.0) -> float:
    """Smooth approximation of min(a, b): -log(exp(-α*a)+exp(-α*b))/α."""
    scaled = alpha * (a - b)
    if scaled > 500:
        return b
    if scaled < -500:
        return a
    return b - math.log(1.0 + math.exp(scaled)) / alpha


class FlashSL(BaseUnit):
    """Simplified solid-liquid dissolution flash."""

    is_linear = False

    def __init__(self, unit_id: str, params: FlashSLParams):
        self.unit_id = unit_id
        self.params = params
        self.species = params.species
        self.solid_in_port   = StreamPort(unit_id, "solid_in",  components=params.species, has_T=True, has_P=False)
        self.solvent_in_port = StreamPort(unit_id, "solvent_in", components=[], has_T=True, has_P=False)
        self.solution_port   = StreamPort(unit_id, "solution",  components=params.species, has_T=True, has_P=False)
        self.solid_out_port  = StreamPort(unit_id, "solid_out", components=params.species, has_T=False, has_P=False)

    def _v_solid(self, c: str)    -> str: return f"{self.unit_id}.solid_in.F_{c}"
    def _v_T(self)                -> str: return f"{self.unit_id}.solid_in.T"
    def _v_solvent(self)          -> str: return f"{self.unit_id}.solvent_in.F_solvent"
    def _v_T_solvent(self)        -> str: return f"{self.unit_id}.solvent_in.T"
    def _v_c(self, c: str)        -> str: return f"{self.unit_id}.solution.F_{c}"
    def _v_V_sol(self)            -> str: return f"{self.unit_id}.solution.T"  # reuse T slot for V_sol
    def _v_solid_out(self, c: str)-> str: return f"{self.unit_id}.solid_out.F_{c}"

    def _v_V_vol(self) -> str: return f"{self.unit_id}.V_sol_m3_s"

    def variables(self) -> List[str]:
        vlist = []
        for c in self.species:
            vlist.append(self._v_solid(c))
        vlist += [self._v_T(), self._v_solvent()]
        for c in self.species:
            vlist.append(self._v_c(c))
        vlist.append(self._v_V_vol())
        for c in self.species:
            vlist.append(self._v_solid_out(c))
        return vlist

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        p = self.params
        bds: Dict[str, Tuple[float, float]] = {}
        for c in self.species:
            bds[self._v_solid(c)]    = (0.0, p.feed_max_kg_s)
            bds[self._v_c(c)]        = (0.0, 1e6)  # mol/m³
            bds[self._v_solid_out(c)]= (0.0, p.feed_max_kg_s)
        bds[self._v_T()]      = (p.T_min, p.T_max)
        bds[self._v_solvent()] = (0.0, p.feed_max_kg_s)
        bds[self._v_V_vol()]  = (0.0, 1e3)
        return bds

    def _solubility(self, c: str, T: float) -> float:
        p = self.params
        S_ref = p.S_ref.get(c, 1000.0)
        dH = p.dH_sol.get(c, 0.0)
        return S_ref * math.exp(dH / 8.314462 * (1.0 / p.T_ref_K - 1.0 / max(T, 1.0)))

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        p = self.params
        N = len(self.species)
        res = np.zeros(2 * N + 1, dtype=float)

        T     = x.get(self._v_T(), 298.15)
        m_sol = x.get(self._v_solvent(), 1.0)
        V_vol = x.get(self._v_V_vol(), m_sol / p.rho_solvent_kg_m3)

        # Solvent volumetric flow [1]
        res[2 * N] = V_vol - m_sol / p.rho_solvent_kg_m3

        for i, c in enumerate(self.species):
            m_solid_i = x.get(self._v_solid(c), 0.0)
            MW = p.MW_kg_per_mol.get(c, 0.1)
            n_solid_i = m_solid_i / max(MW, 1e-10)  # mol/s
            S_i = self._solubility(c, T)             # mol/m³
            n_max_dissolve = S_i * V_vol              # mol/s

            # c_i * V_vol = softmin(n_solid_i, n_max_dissolve) [N]
            c_i = x.get(self._v_c(c), 0.0)
            dissolved = _softmin(n_solid_i, n_max_dissolve, p.softplus_alpha)
            res[i] = c_i * V_vol - dissolved

            # m_residual = m_solid - dissolved * MW [N]
            m_residual = x.get(self._v_solid_out(c), 0.0)
            res[N + i] = m_residual - max(m_solid_i - dissolved * MW, 0.0)

        return res

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {}
