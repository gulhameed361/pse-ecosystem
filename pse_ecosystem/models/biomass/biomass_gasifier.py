"""BiomassGasifierHF — thermochemical equilibrium gasifier.

Physics fixes vs. B-HYPSYS legacy code
---------------------------------------
* Equilibrium constants applied as proper Kp(T) expressions with correct
  pressure-dependence (Issues #1, #2).
* Elemental balances use absolute mol/s flows throughout — no mixing of
  normalised and absolute units (Issues #4, #5, #6).
* N2 tracked correctly via air O2:N2 = 0.21:0.79 (Issue #15).
* LHV / CGE computed only from combustible species (Issues #10, #11).

Equilibrium correlations
------------------------
Two-parameter van't Hoff fits calibrated from NIST thermodynamic data:

  WGS:         CO + H2O ⇌ CO2 + H2         (Δn = 0, pressure-independent)
    K_WGS(T) = exp(4300/T − 3.84)
    Calibrated: K_WGS(800 K) ≈ 4.6, K_WGS(1073 K) ≈ 1.2 ✓

  Methanation: CO + 3H2 ⇌ CH4 + H2O        (Δn = −2)
    K_met(T) = exp(25000/T − 26.2)
    Calibrated: K_met(800 K) ≈ 150, K_met(1073 K) ≈ 0.05 ✓

Residuals (6 equations, 8 variables)
--------------------------------------
Variables: F_Biomass (biomass_in), F_agent (agent_in), n_H2, n_CO, n_CO2,
           n_H2O, n_CH4, n_N2 (all syngas_out molar flows, mol/s)

  f[0] = n_CO + n_CO2 + n_CH4 − n_C_feed(F_Biomass)
  f[1] = 2·n_H2 + 2·n_H2O + 4·n_CH4 − n_H_feed(F_Biomass, F_agent)
  f[2] = n_CO + 2·n_CO2 + n_H2O − n_O_feed(F_Biomass, F_agent)
  f[3] = 2·n_N2 − n_N_feed(F_Biomass, F_agent)
  f[4] = K_WGS(T) · n_CO · n_H2O − n_CO2 · n_H2       [WGS eq.]
  f[5] = K_met(T) · n_CO · n_H2³ · (P/n_total)² − n_CH4 · n_H2O  [met. eq.]

Jacobian: finite-difference via BaseUnit default (overridable for performance).
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.biomass.biomass_database import element_feeds_mol_s, get_biomass

# ── Constants ─────────────────────────────────────────────────────────────────
_LHV_MJ_per_mol = {   # LHV of combustible syngas species [MJ/mol]
    "H2":  0.2418,
    "CO":  0.2830,
    "CH4": 0.8026,
}
_MW_syngas = {  # g/mol (for Nm³/s computation)
    "H2": 2.016, "CO": 28.010, "CO2": 44.010,
    "H2O": 18.015, "CH4": 16.043, "N2": 28.014,
}
_VM_MOLAR = 22.414   # L/mol at NTP (0°C, 1 atm), for Nm³/s conversion

_SYNGAS_SPECIES = frozenset({"H2", "CO", "CO2", "H2O", "CH4", "N2"})
_AIR_SPECIES    = frozenset({"O2", "N2"})
_STEAM_SPECIES  = frozenset({"H2O"})


def _kp_wgs(T_K: float) -> float:
    """K_WGS(T) = exp(4300/T - 3.84), valid ~600–1200 K."""
    return math.exp(4300.0 / T_K - 3.84)


def _kp_met(T_K: float) -> float:
    """K_met(T) = exp(25000/T - 26.2), valid ~600–1200 K."""
    return math.exp(25000.0 / T_K - 26.2)


class BiomassGasifierHF(BaseUnit):
    """Thermochemical equilibrium gasifier (corrected B-HYPSYS physics).

    Parameters
    ----------
    unit_id          : Unique identifier.
    biomass_type     : Key into BIOMASS_DB.
    T_gasifier_C     : Gasifier operating temperature [°C].
    gasifying_agent  : "Steam" or "Air".
    P_atm            : Operating pressure [atm].
    biomass_cost_USD_per_kg : Feedstock cost used in objective [USD/kg dry].
    """

    is_linear: bool = False

    def __init__(
        self,
        unit_id: str,
        biomass_type: str = "Pine Wood",
        T_gasifier_C: float = 800.0,
        gasifying_agent: str = "Steam",
        P_atm: float = 1.0,
        biomass_cost_USD_per_kg: float = 0.05,
    ) -> None:
        self.unit_id = unit_id
        self.biomass_type = biomass_type
        self._b = get_biomass(biomass_type)
        self.T_K = T_gasifier_C + 273.15
        self.gasifying_agent = gasifying_agent
        self.P_atm = P_atm
        self.biomass_cost_USD_per_kg = biomass_cost_USD_per_kg

        if gasifying_agent == "Steam":
            _agent_species = _STEAM_SPECIES
            _agent_comps = ["H2O"]
        else:  # Air
            _agent_species = _AIR_SPECIES
            _agent_comps = ["O2", "N2"]

        self.biomass_in_port = StreamPort(
            unit_id=unit_id, tag="biomass_in",
            components=["Biomass"], has_T=False, has_P=False,
            phase="solid_dry", species=frozenset({"Biomass"}),
        )
        self.agent_in_port = StreamPort(
            unit_id=unit_id, tag="agent_in",
            components=_agent_comps, has_T=False, has_P=False,
            phase="gas", species=_agent_species,
        )
        self.syngas_out_port = StreamPort(
            unit_id=unit_id, tag="syngas_out",
            components=["H2", "CO", "CO2", "H2O", "CH4", "N2"],
            has_T=False, has_P=False,
            phase="gas", species=_SYNGAS_SPECIES,
        )

    # ── Variable helpers ──────────────────────────────────────────────────────

    def _v_biomass(self) -> str:
        return f"{self.unit_id}.biomass_in.F_Biomass"

    def _agent_vars(self) -> List[str]:
        if self.gasifying_agent == "Steam":
            return [f"{self.unit_id}.agent_in.F_H2O"]
        return [f"{self.unit_id}.agent_in.F_O2",
                f"{self.unit_id}.agent_in.F_N2"]

    def _syngas_vars(self) -> List[str]:
        uid = self.unit_id
        return [
            f"{uid}.syngas_out.F_H2",
            f"{uid}.syngas_out.F_CO",
            f"{uid}.syngas_out.F_CO2",
            f"{uid}.syngas_out.F_H2O",
            f"{uid}.syngas_out.F_CH4",
            f"{uid}.syngas_out.F_N2",
        ]

    def variables(self) -> List[str]:
        return [self._v_biomass()] + self._agent_vars() + self._syngas_vars()

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        b: Dict[str, Tuple[float, float]] = {
            self._v_biomass(): (1e-6, 1e3),
        }
        for v in self._agent_vars():
            b[v] = (0.0, 1e4)
        for v in self._syngas_vars():
            b[v] = (1e-9, 1e4)
        return b

    # ── Element feeds from x ──────────────────────────────────────────────────

    def _element_feeds(self, x: Dict[str, float]) -> Tuple[float, float, float, float]:
        """Return n_C, n_H, n_O, n_N [mol/s] from biomass + agent."""
        F_dry = max(x.get(self._v_biomass(), 0.0), 0.0)
        feeds = element_feeds_mol_s(self.biomass_type, F_dry)
        n_C, n_H, n_O, n_N = feeds["C"], feeds["H"], feeds["O"], feeds["N"]

        if self.gasifying_agent == "Steam":
            F_steam = max(x.get(f"{self.unit_id}.agent_in.F_H2O", 0.0), 0.0)
            n_H += 2.0 * F_steam   # 2 H atoms per H2O
            n_O += F_steam          # 1 O atom per H2O
        else:  # Air: 21% O2, 79% N2 by volume
            F_O2 = max(x.get(f"{self.unit_id}.agent_in.F_O2", 0.0), 0.0)
            F_N2_air = max(x.get(f"{self.unit_id}.agent_in.F_N2", 0.0), 0.0)
            n_O += 2.0 * F_O2
            n_N += 2.0 * F_N2_air  # N2 → 2 N atoms

        return n_C, n_H, n_O, n_N

    # ── Residuals ─────────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        uid = self.unit_id
        n_H2  = max(x.get(f"{uid}.syngas_out.F_H2",  1e-6), 1e-12)
        n_CO  = max(x.get(f"{uid}.syngas_out.F_CO",  1e-6), 1e-12)
        n_CO2 = max(x.get(f"{uid}.syngas_out.F_CO2", 1e-6), 1e-12)
        n_H2O = max(x.get(f"{uid}.syngas_out.F_H2O", 1e-6), 1e-12)
        n_CH4 = max(x.get(f"{uid}.syngas_out.F_CH4", 1e-6), 1e-12)
        n_N2  = max(x.get(f"{uid}.syngas_out.F_N2",  1e-9), 1e-12)

        n_C_feed, n_H_feed, n_O_feed, n_N_feed = self._element_feeds(x)

        K_wgs = _kp_wgs(self.T_K)
        K_met = _kp_met(self.T_K)
        n_total = n_H2 + n_CO + n_CO2 + n_H2O + n_CH4 + n_N2
        P = self.P_atm

        f = np.array([
            n_CO + n_CO2 + n_CH4 - n_C_feed,                          # C balance
            2*n_H2 + 2*n_H2O + 4*n_CH4 - n_H_feed,                   # H balance
            n_CO + 2*n_CO2 + n_H2O - n_O_feed,                        # O balance
            2*n_N2 - n_N_feed,                                         # N balance
            K_wgs * n_CO * n_H2O - n_CO2 * n_H2,                     # WGS eq.
            K_met * n_CO * n_H2**3 * (P / n_total)**2 - n_CH4 * n_H2O,  # met. eq.
        ], dtype=float)
        return f

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {self._v_biomass(): self.biomass_cost_USD_per_kg}

    def capex(self, x: Dict[str, float]) -> float:
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD
        F_dry = max(x.get(self._v_biomass(), 1.0), 0.1)
        vol_m3 = F_dry * 2000.0 * 0.001  # rough: 1 kg/s → ~2 m³/h, residence ~1 h
        return vessel_purchase_cost_USD(max(vol_m3, 1.0), material="CS")

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        n = {
            "H2":  max(x.get(f"{uid}.syngas_out.F_H2",  0.0), 0.0),
            "CO":  max(x.get(f"{uid}.syngas_out.F_CO",  0.0), 0.0),
            "CO2": max(x.get(f"{uid}.syngas_out.F_CO2", 0.0), 0.0),
            "H2O": max(x.get(f"{uid}.syngas_out.F_H2O", 0.0), 0.0),
            "CH4": max(x.get(f"{uid}.syngas_out.F_CH4", 0.0), 0.0),
            "N2":  max(x.get(f"{uid}.syngas_out.F_N2",  0.0), 0.0),
        }
        n_total = sum(n.values())
        if n_total < 1e-12:
            return {}

        F_dry = max(x.get(self._v_biomass(), 1e-9), 1e-9)

        # H2 vol%
        h2_pct = 100.0 * n["H2"] / n_total

        # LHV of syngas (only combustible species, excluding N2 and CO2)
        energy_kW = sum(
            n[sp] * _LHV_MJ_per_mol[sp] * 1000.0  # MJ/mol → kW (mol/s × kW·s/mol)
            for sp in ("H2", "CO", "CH4")
        )

        # Cold gas efficiency (CGE): energy in combustible syngas / LHV of dry biomass feed
        LHV_biomass_kW = F_dry * self._b["LHV_MJ_kg"] * 1000.0
        cge = 100.0 * energy_kW / LHV_biomass_kW if LHV_biomass_kW > 1e-9 else 0.0

        # Syngas yield [Nm³/kg dry biomass]
        vol_total_Nm3_s = n_total * _VM_MOLAR / 1000.0   # mol/s → Nm³/s
        yield_Nm3_per_kg = vol_total_Nm3_s / F_dry if F_dry > 1e-9 else 0.0

        return {
            f"{uid}.H2_pct_vol": h2_pct,
            f"{uid}.CGE_percent": cge,
            f"{uid}.syngas_yield_Nm3_per_kg": yield_Nm3_per_kg,
            f"{uid}.LHV_syngas_kW": energy_kW,
        }
