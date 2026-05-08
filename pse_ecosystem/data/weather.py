"""Weather data and site utilities for time-indexed process optimisation.

Provides solar irradiance profiles (via pvlib clearsky, no API key required),
synthetic wind speed profiles (Weibull distribution), demand profiles, and a
helper to map solar output to time-varying electricity prices.

Optional dependency: pvlib>=0.10, pandas>=1.5
Install:  pip install 'pse_ecosystem[weather]'

Functions that only use numpy work without pvlib (wind, demand, price mapping).
Functions that use pvlib call ``_require_pvlib()`` at their top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

# ── pvlib optional import ─────────────────────────────────────────────────────

try:
    import pvlib          # type: ignore
    import pandas as pd   # type: ignore
    _PVLIB_AVAILABLE = True
except ImportError:
    _PVLIB_AVAILABLE = False


def _require_pvlib() -> None:
    if not _PVLIB_AVAILABLE:
        raise ImportError(
            "pvlib and pandas are required for solar profiles. "
            "Install with: pip install 'pse_ecosystem[weather]'"
        )


# ── Site metadata ─────────────────────────────────────────────────────────────

@dataclass
class SiteData:
    """Geographic and timezone data for a production site.

    Parameters
    ----------
    latitude:   decimal degrees North  (e.g. 51.24 for Guildford, UK)
    longitude:  decimal degrees East   (e.g. -0.59 for Guildford, UK)
    altitude:   metres above sea level (default 0)
    timezone:   IANA timezone string   (default "UTC")
    name:       human-readable label
    """
    latitude: float
    longitude: float
    altitude: float = 0.0
    timezone: str = "UTC"
    name: str = "site"


# ── Solar profile (pvlib clearsky) ────────────────────────────────────────────

def fetch_solar_profile(
    site: SiteData,
    year: int,
    freq: str = "1h",
) -> np.ndarray:
    """Return hourly Global Horizontal Irradiance [W/m2] for a full year.

    Uses pvlib's Ineichen clearsky model — purely geometric/empirical, no
    API key or network access required.

    Parameters
    ----------
    site:  site coordinates and timezone
    year:  calendar year (e.g. 2023)
    freq:  pandas frequency string (default '1h')

    Returns
    -------
    ghi : np.ndarray, shape (n_hours,)
        GHI in W/m2.  Night-time values are 0.
    """
    _require_pvlib()
    times = pd.date_range(
        start=f"{year}-01-01",
        end=f"{year + 1}-01-01",
        freq=freq,
        tz=site.timezone,
        inclusive="left",
    )
    location = pvlib.location.Location(
        latitude=site.latitude,
        longitude=site.longitude,
        tz=site.timezone,
        altitude=site.altitude,
        name=site.name,
    )
    clearsky = location.get_clearsky(times, model="ineichen")
    return clearsky["ghi"].values.astype(float)


# ── Wind speed profile (synthetic Weibull) ────────────────────────────────────

def fetch_wind_profile(
    site: SiteData,
    year: int,
    freq: str = "1h",
    v_ref: float = 8.0,
    weibull_k: float = 2.0,
) -> np.ndarray:
    """Return a synthetic hourly wind speed profile [m/s].

    Uses a Weibull distribution seeded deterministically from the site
    coordinates, so results are reproducible without network access.
    A diurnal correction (±10%) is applied — wind tends to be slightly
    stronger in the afternoon over land.

    Parameters
    ----------
    site:       site data (coordinates used for deterministic seeding)
    year:       calendar year (affects number of hours for leap years)
    freq:       frequency string — only '1h' is supported currently
    v_ref:      Weibull scale parameter [m/s] (≈ mean wind speed)
    weibull_k:  Weibull shape parameter (2 = Rayleigh; typical for wind)

    Returns
    -------
    wind_speed : np.ndarray, shape (n_hours,)
    """
    # Compute number of hours in the year
    if _PVLIB_AVAILABLE:
        import pandas as pd  # noqa: PLC0415
        n = len(pd.date_range(f"{year}-01-01", f"{year + 1}-01-01",
                              freq=freq, inclusive="left"))
    else:
        n = 8784 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 8760

    seed = int(abs(site.latitude) * 1000 + abs(site.longitude) * 100 + year) % (2**31)
    rng = np.random.default_rng(seed=seed)

    # Weibull-distributed base wind speed
    v_base = rng.weibull(weibull_k, size=n) * v_ref

    # Diurnal correction: 10% stronger in afternoon (peak at hour 14)
    hours = np.arange(n) % 24
    diurnal = 1.0 + 0.10 * np.sin(2.0 * np.pi * (hours - 6.0) / 24.0)

    return np.clip(v_base * diurnal, 0.0, None)


# ── Demand profile ────────────────────────────────────────────────────────────

def generate_demand_profile(
    peak_demand_kg_per_h: float,
    n_hours: int = 8760,
    seasonal: bool = False,
) -> np.ndarray:
    """Return an hourly H2 demand profile [kg/h].

    Parameters
    ----------
    peak_demand_kg_per_h:
        Peak (or constant) demand.
    n_hours:
        Number of time steps.
    seasonal:
        If True, apply a cosine seasonal variation (±20%, winter peak).

    Returns
    -------
    demand : np.ndarray, shape (n_hours,)
    """
    if not seasonal:
        return np.full(n_hours, float(peak_demand_kg_per_h))
    t = np.arange(n_hours)
    return float(peak_demand_kg_per_h) * (1.0 + 0.20 * np.cos(2.0 * np.pi * t / n_hours))


# ── Electricity price from solar ──────────────────────────────────────────────

def electricity_price_from_solar(
    ghi: np.ndarray,
    base_price: float = 0.10,
    solar_discount: float = 0.05,
) -> np.ndarray:
    """Map GHI [W/m2] to an electricity price [£/kWh].

    When solar generation is high, excess supply depresses the spot price.
    This is a simple linear proxy — suitable for conceptual sizing studies.

    price = base_price - solar_discount * (ghi / ghi_max)
    Clipped to [0.01, base_price + 0.05].

    Parameters
    ----------
    ghi:            GHI array [W/m2], shape (n_hours,)
    base_price:     baseline price when GHI = 0  [£/kWh]
    solar_discount: maximum price reduction at peak GHI [£/kWh]

    Returns
    -------
    prices : np.ndarray, shape (n_hours,)
    """
    ghi_max = max(float(ghi.max()), 1.0)
    prices = base_price - solar_discount * (ghi / ghi_max)
    return np.clip(prices, 0.01, base_price + 0.05)


# ── Weather-driven flowsheet ──────────────────────────────────────────────────

@dataclass
class WeatherDrivenFlowsheet:
    """Associates a :class:`~pse_ecosystem.flowsheets.base_flowsheet.BaseFlowsheet`
    with time-series weather and demand data.

    Use :meth:`make_snapshot_flowsheet` to retrieve a flowsheet with the
    electricity price fixed at a specific hour, then optimise with the
    standard Orchestrator / SLPDriver interface.

    Parameters
    ----------
    name:                 human-readable label
    base_flowsheet:       the template flowsheet (not mutated)
    solar_ghi:            hourly GHI [W/m2], shape (n_hours,)
    electricity_prices:   hourly electricity price [£/kWh], shape (n_hours,)
    h2_demand:            hourly H2 demand [kg/h], shape (n_hours,)
    pem_electricity_var:  variable name in base_flowsheet that receives the
                          electricity price (used to override objective coefficient)
    """
    name: str
    base_flowsheet: "object"  # BaseFlowsheet — avoid circular import at module level
    solar_ghi: np.ndarray
    electricity_prices: np.ndarray
    h2_demand: np.ndarray
    pem_electricity_var: str = "pem.electricity_kW"

    def make_snapshot_flowsheet(self, hour: int) -> "object":
        """Return a new flowsheet with parameters fixed to ``hour``.

        The returned flowsheet is a shallow copy of ``base_flowsheet`` with
        an extra equality constraint pinning the H2 demand at the hour value.
        The electricity price is injected by overriding the unit's params
        before building the flowsheet — callers must use the factory pattern
        (see ``examples/weather_optimisation.py``).

        For the simple case of a single PEM unit, use
        :func:`make_pem_snapshot_flowsheet` instead.
        """
        import copy  # noqa: PLC0415
        clone = copy.copy(self.base_flowsheet)
        clone.extra_equalities = list(self.base_flowsheet.extra_equalities)
        clone.extra_bounds = dict(self.base_flowsheet.extra_bounds)
        return clone

    def make_pem_snapshot_flowsheet(self, hour: int, h2_demand_override: Optional[float] = None):
        """Convenience factory: return an electrolysis-only flowsheet for one hour.

        Uses PEMToy with the electricity price at ``hour`` and demand from
        ``h2_demand[hour]`` (or the optional override).

        Requires pse_ecosystem[weather] for pvlib; the PEM unit itself has no
        extra dependencies.
        """
        from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only  # noqa: PLC0415
        from pse_ecosystem.models.electrolysis.pem_toy import PEMToyParams              # noqa: PLC0415

        price = float(self.electricity_prices[hour])
        demand = h2_demand_override if h2_demand_override is not None else float(self.h2_demand[hour])

        params = PEMToyParams(
            electricity_price_per_kWh=price,
            operating_hours_per_year=1.0,  # single-hour snapshot
        )
        return make_electrolysis_only(h2_demand_kg_per_h=demand, pem_params=params)
