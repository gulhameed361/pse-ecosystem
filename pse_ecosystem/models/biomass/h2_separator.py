"""H2SeparatorPSA — Pressure Swing Adsorption hydrogen separator.

Models a PSA unit that produces a high-purity H2 product stream and a
tail gas containing all non-H2 species.

Ports
-----
feed_in    : 6-component syngas (H2, CO, CO2, H2O, CH4, N2)
h2_out     : pure H2 product (species = {"H2"})
tail_out   : tail gas (CO, CO2, H2O, CH4, N2 — no H2)

Variables (12 total)
--------------------
feed_in.F_{H2,CO,CO2,H2O,CH4,N2}  (6)
h2_out.F_H2                         (1)
tail_out.F_{CO,CO2,H2O,CH4,N2}     (5)

Residuals (6)
-------------
f[0] : h2_out.F_H2 − feed_in.F_H2 × H2_recovery = 0
f[1..5] : tail_out.F_X − feed_in.F_X = 0  (for X ∈ {CO, CO2, H2O, CH4, N2})

H2 in the tail gas = feed_in.F_H2 × (1 − H2_recovery) is implicitly lost
(a PSA blowdown stream, not tracked in the LP).

KPIs
----
H2_production_kg_h, H2_recovery_pct, W_PSA_kW (power from literature ≈ 1.5 kWh/kg H2)
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from pse_ecosystem.core.contracts import StreamPort
from pse_ecosystem.models.base_unit import BaseUnit

_MW_H2 = 2.016   # g/mol

_SYNGAS_COMPS = ["H2", "CO", "CO2", "H2O", "CH4", "N2"]
_TAIL_COMPS   = ["CO", "CO2", "H2O", "CH4", "N2"]
_SYNGAS_SPECIES = frozenset(_SYNGAS_COMPS)
_H2_SPECIES     = frozenset({"H2"})
_TAIL_SPECIES   = frozenset(_TAIL_COMPS)


class H2SeparatorPSA(BaseUnit):
    """PSA hydrogen separator.

    Parameters
    ----------
    unit_id       : Unique identifier.
    H2_recovery   : Fraction of feed H2 recovered in product stream [0–1].
    """

    is_linear: bool = True
    # v1.5.0.dev-AUDIT2 L3-1: the objective_contribution {h2_var: -1.0} is a
    # YIELD signal (maximise H₂), not an operating cost. Tell the BaseUnit
    # OPEX aggregator to ignore it.
    _OPEX_CONVENTION = "yield_coefficient"

    def __init__(
        self,
        unit_id: str,
        H2_recovery: float = 0.85,
        electricity_price_USD_per_kWh: float = 0.05,
        operating_hours_per_year: float = 8_000.0,
        feed_max: float = 1e4,
    ) -> None:
        self.unit_id = unit_id
        self.H2_recovery = float(H2_recovery)
        self._elec_price = electricity_price_USD_per_kWh
        self._op_hours = operating_hours_per_year
        self._feed_max = feed_max

        self.feed_in_port = StreamPort(
            unit_id=unit_id, tag="feed_in",
            components=_SYNGAS_COMPS, has_T=False, has_P=False,
            phase="gas", species=_SYNGAS_SPECIES,
        )
        self.h2_out_port = StreamPort(
            unit_id=unit_id, tag="h2_out",
            components=["H2"], has_T=False, has_P=False,
            phase="gas", species=_H2_SPECIES,
        )
        self.tail_out_port = StreamPort(
            unit_id=unit_id, tag="tail_out",
            components=_TAIL_COMPS, has_T=False, has_P=False,
            phase="gas", species=_TAIL_SPECIES,
        )

    @property
    def _primary_inlet_port(self):
        return self.feed_in_port

    @property
    def _primary_outlet_port(self):
        return self.h2_out_port

    # ── Variable helpers ──────────────────────────────────────────────────────

    def _feed_vars(self) -> List[str]:
        return [f"{self.unit_id}.feed_in.F_{c}" for c in _SYNGAS_COMPS]

    def _h2_var(self) -> str:
        return f"{self.unit_id}.h2_out.F_H2"

    def _tail_vars(self) -> List[str]:
        return [f"{self.unit_id}.tail_out.F_{c}" for c in _TAIL_COMPS]

    def variables(self) -> List[str]:
        return self._feed_vars() + [self._h2_var()] + self._tail_vars()

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        b: Dict[str, Tuple[float, float]] = {}
        for v in self._feed_vars():
            b[v] = (0.0, self._feed_max)
        b[self._h2_var()] = (0.0, self._feed_max)
        for v in self._tail_vars():
            b[v] = (0.0, self._feed_max)
        return b

    # ── Residuals ─────────────────────────────────────────────────────────────

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        uid = self.unit_id
        n_H2_feed = x.get(f"{uid}.feed_in.F_H2", 0.0)
        n_H2_out  = x.get(self._h2_var(), 0.0)

        f = np.zeros(6, dtype=float)
        f[0] = n_H2_out - n_H2_feed * self.H2_recovery  # H2 recovery balance

        for i, c in enumerate(_TAIL_COMPS):
            n_feed = x.get(f"{uid}.feed_in.F_{c}", 0.0)
            n_tail = x.get(f"{uid}.tail_out.F_{c}", 0.0)
            f[i + 1] = n_tail - n_feed   # all non-H2 go to tail gas

        return f

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        # Maximise H2 product (negative coefficient → minimise −H2).
        # Electricity cost is computed in opex_per_year() below.
        return {self._h2_var(): -1.0}

    def opex_per_year(self, x: Dict[str, float],
                      operating_hours: float = 8_000.0) -> float:
        """PSA electricity cost [USD/yr].

        _OPEX_CONVENTION = "yield_coefficient" suppresses the objective_contribution
        from the BaseUnit default.  This override adds the real electricity cost
        (W_PSA_kW × price × hours) so it appears in the Project Economics report.
        """
        kpis = self.kpis(x)
        uid = self.unit_id
        W_kW = kpis.get(f"{uid}.W_PSA_kW", 0.0)
        hours = operating_hours or self._op_hours
        return W_kW * self._elec_price * hours

    # ── KPIs ──────────────────────────────────────────────────────────────────

    def capex(self, x: Dict[str, float]) -> float:
        """PSA vessel + compressor CAPEX [USD, CE500 basis].

        Sized on H₂ production rate: ~$1 500/kg-H₂/day purchase cost
        (literature mid-point for 10–10 000 kg/day PSA units).
        """
        from pse_ecosystem.models.costing.sslw_costing import vessel_purchase_cost_USD
        uid = self.unit_id
        n_H2_out = max(x.get(self._h2_var(), 0.0), 0.0)
        h2_kg_day = n_H2_out * _MW_H2 / 1000.0 * 3600.0 * 24.0
        # Use vessel_purchase_cost_USD as a proxy (PSA vessel sized by throughput)
        V_m3 = max(h2_kg_day / 50.0, 0.1)   # rough: 50 kg H2/day per m³
        return vessel_purchase_cost_USD(V_m3)

    def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
        uid = self.unit_id
        n_H2_out  = max(x.get(self._h2_var(), 0.0), 0.0)
        n_H2_feed = max(x.get(f"{uid}.feed_in.F_H2", 1e-12), 1e-12)

        h2_kg_s = n_H2_out * _MW_H2 / 1000.0   # mol/s → kg/s
        h2_kg_h = h2_kg_s * 3600.0
        recovery_pct = 100.0 * n_H2_out / n_H2_feed

        # PSA electricity: 1.5 kWh/kg H₂ (literature average).
        # Correct conversion: 1.5 kWh/kg × h2_kg_s kg/s = 1.5 × 3600 kW
        # (1 kWh = 3600 kJ; 1 kJ/s = 1 kW → multiply by 3600 not divide)
        W_psa_kW = h2_kg_s * 1.5 * 3600.0   # kW

        return {
            f"{uid}.H2_production_kg_h": h2_kg_h,
            f"{uid}.H2_production_kg_s": h2_kg_s,
            f"{uid}.H2_recovery_pct":    recovery_pct,
            f"{uid}.W_PSA_kW":           W_psa_kW,
        }
