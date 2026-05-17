"""Economic Engine — CEPCI escalation, capital recovery, and LCOH.

Layer 3 module: lives in models/costing/.  Never imported by Layer 2.

CEPCI historical values from Chemical Engineering magazine and ICIS.
Years after 2024 are projected at CEPCI_ESCALATION_RATE per annum.
"""

from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass

# ── CEPCI data ────────────────────────────────────────────────────────────────
# Source: Chemical Engineering Plant Cost Index (published monthly)
# CE=500 is the traditional basis year used in SSLW correlations (~2001).
# Primary source: data/economics.json (loaded at import time if present).
# Fallback: hardcoded dict below (kept for environments without the data file).
#
# v1.4.0 audit H9: prefer `importlib.resources.files` so the loader works for
# a pip-installed package (where the source-tree relative path traversal
# fails silently). Fall back to the legacy path lookup for editable installs
# of older Python where importlib.resources lacks `files()`.


def _resolve_economics_json() -> pathlib.Path:
    # Try the packaged-data path first (works after `pip install`).
    try:
        from importlib.resources import files
        candidate = files("pse_ecosystem.data") / "economics.json"
        if candidate.is_file():
            return pathlib.Path(str(candidate))
    except (ImportError, ModuleNotFoundError, FileNotFoundError):
        pass
    # Fall back to the source-tree layout (editable installs).
    return (
        pathlib.Path(__file__).parent.parent.parent.parent
        / "data" / "economics.json"
    )


_ECONOMICS_JSON = _resolve_economics_json()


def _load_cepci_from_json() -> "tuple[dict[int, float], float]":
    """Load CEPCI dict and escalation rate from data/economics.json if present."""
    try:
        with open(_ECONOMICS_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("cepci", {})
        cepci = {int(k): float(v) for k, v in raw.items() if not k.startswith("_")}
        rate = float(data.get("cepci_escalation_rate", 0.025))
        return cepci, rate
    except (FileNotFoundError, KeyError, ValueError):
        return {}, 0.025


_json_cepci, _json_rate = _load_cepci_from_json()

CEPCI: dict[int, float] = _json_cepci or {
    2001: 394.3,   # CE=500 SSLW basis
    2005: 468.2,
    2010: 550.8,
    2015: 556.8,
    2016: 541.7,
    2017: 567.5,
    2018: 603.1,
    2019: 607.5,
    2020: 596.2,
    2021: 708.8,
    2022: 816.0,
    2023: 797.6,
    2024: 802.3,
}

CEPCI_ESCALATION_RATE: float = _json_rate   # 2.5%/yr beyond last data year

_CEPCI_BASE_YEAR: int = 2001           # matches sslw_costing.py (CE=500 at 394.3)
_CEPCI_SSLW_INDEX: float = 500.0      # legacy SSLW normalisation base
_LAST_DATA_YEAR: int = max(CEPCI)


def _cepci_for_year(year: int) -> float:
    """Return CEPCI for *year*, projecting forward if needed."""
    if year in CEPCI:
        return CEPCI[year]
    if year > _LAST_DATA_YEAR:
        return CEPCI[_LAST_DATA_YEAR] * (1 + CEPCI_ESCALATION_RATE) ** (
            year - _LAST_DATA_YEAR
        )
    # Interpolate between surrounding data points
    years_below = [y for y in CEPCI if y <= year]
    years_above = [y for y in CEPCI if y >= year]
    if not years_below or not years_above:
        raise ValueError(f"Cannot interpolate CEPCI for year {year}.")
    y0, y1 = max(years_below), min(years_above)
    if y0 == y1:
        return CEPCI[y0]
    frac = (year - y0) / (y1 - y0)
    return CEPCI[y0] + frac * (CEPCI[y1] - CEPCI[y0])


# ── EconomicEngine ────────────────────────────────────────────────────────────


@dataclass
class EconomicEngine:
    """Centralised economic parameters for a plant.

    Parameters
    ----------
    target_year : Cost year for equipment pricing escalation.
    plant_life_yr : Project lifetime [years].
    interest_rate : Discount / interest rate (fraction, e.g. 0.08 for 8%).
    operating_hours_per_year : Equivalent full-load hours/yr (default 8000).
    """

    target_year: int = 2024
    plant_life_yr: int = 20
    interest_rate: float = 0.08
    operating_hours_per_year: float = 8000.0

    # ── CEPCI ────────────────────────────────────────────────────────────────

    def cepci_value(self) -> float:
        """CEPCI index for the target year."""
        return _cepci_for_year(self.target_year)

    def cepci_factor(self, base_year: int = _CEPCI_BASE_YEAR) -> float:
        """Escalation ratio: CEPCI(target_year) / CEPCI(base_year)."""
        return _cepci_for_year(self.target_year) / _cepci_for_year(base_year)

    def sslw_cepci_factor(self) -> float:
        """Escalation factor relative to SSLW CE=500 (year 2001) basis.

        Use this to scale SSLW purchase costs to target_year dollars:
            cost_now = cost_CE500 * sslw_cepci_factor()
        """
        return _cepci_for_year(self.target_year) / _CEPCI_SSLW_INDEX

    # ── Capital recovery ─────────────────────────────────────────────────────

    def capital_recovery_factor(self) -> float:
        """CRF = i*(1+i)^n / ((1+i)^n - 1).

        Converts total installed capital cost to equal annual payments.
        """
        i = self.interest_rate
        n = self.plant_life_yr
        if i == 0.0:
            return 1.0 / n
        return i * (1 + i) ** n / ((1 + i) ** n - 1)

    # ── Annualised CAPEX ─────────────────────────────────────────────────────

    def annualized_capex(
        self,
        purchase_cost_CE500_USD: float,
        lang_factor: float = 5.0,
    ) -> float:
        """Annualise SSLW purchase cost [USD/yr].

        installed = purchase_cost * lang_factor * sslw_cepci_factor()
        annual    = installed * CRF
        """
        installed = purchase_cost_CE500_USD * lang_factor * self.sslw_cepci_factor()
        return installed * self.capital_recovery_factor()

    # ── LCOH ─────────────────────────────────────────────────────────────────

    def lcoh(
        self,
        capex_annual_USD: float,
        opex_annual_USD: float,
        h2_kg_per_s: float,
    ) -> float:
        """Levelised cost of hydrogen [USD/kg H2].

        Parameters
        ----------
        capex_annual_USD : Annualised capital cost [USD/yr].
        opex_annual_USD  : Annual operating cost [USD/yr].
        h2_kg_per_s      : H2 production rate at full load [kg/s].
        """
        h2_per_year = h2_kg_per_s * 3600.0 * self.operating_hours_per_year
        if h2_per_year <= 0.0:
            return float("inf")
        return (capex_annual_USD + opex_annual_USD) / h2_per_year
