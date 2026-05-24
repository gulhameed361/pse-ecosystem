"""Unified component database (v1.6).

A single ``Component`` dataclass carries every property needed across the
PSE Ecosystem property packages — ideal-gas, cubic-EOS (PR/SRK), and
activity-coefficient (NRTL/Wilson/UNIQUAC). The existing
``ideal_gas.SHOMATE`` / ``ideal_gas.MW`` / ``ideal_gas.H_REF_298`` /
``vle.ANTOINE`` dictionaries are rebuilt from this registry at import time
so v1.5.3 numerics are preserved bit-for-bit while the new property
packages can query the broader database.

Design contract
---------------
* A species appears in the rebuilt ``SHOMATE`` dict **only if** its
  ``Component.shomate`` is not ``None``. This preserves the
  ``if species in SHOMATE`` guard pattern used throughout the unit models.
* Same rule for ``ANTOINE`` (species with ``component.antoine is not None``)
  and ``MW`` (species with non-zero molecular weight).
* Aliases register the same ``Component`` under multiple keys. Existing
  data uses ``"methane"`` in Antoine and ``"CH4"`` in Shomate for the same
  physical species; both keys continue to resolve correctly.

Sources
-------
* Shomate Cp / H — NIST Chemistry WebBook (https://webbook.nist.gov)
* Antoine A, B, C — Perry's Chemical Engineers' Handbook 8e, Table 2-8
  (form: ``log10(P_sat/mmHg) = A - B/(T_°C + C)``)
* Tc, Pc, ω        — Reid, Prausnitz & Poling, *The Properties of Gases
  and Liquids*, 4th/5th ed, Appendix A; cross-checked vs DIPPR where
  available.
* Hf_298           — NIST WebBook (gas-phase standard enthalpy of
  formation at 298.15 K) for Shomate-bearing species, otherwise DIPPR.
* UNIQUAC r, q     — Gmehling, Onken & Arlt, *Vapor-Liquid Equilibrium
  Data Collection* (Chemistry Data Series).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ShomateCoeffs:
    """NIST Shomate polynomial coefficients.

    Cp°(T)        = A + B·t + C·t² + D·t³ + E/t²              [J/mol/K]
    H°(T)−H°(298) = A·t + B·t²/2 + C·t³/3 + D·t⁴/4 − E/t + F − H   [kJ/mol]

    where t = T[K] / 1000 and ``H`` is the species' standard enthalpy of
    formation at 298.15 K in kJ/mol (NIST convention).
    """

    A: float
    B: float
    C: float
    D: float
    E: float
    F: float
    H: float
    T_min: float = 298.0
    T_max: float = 1200.0


@dataclass(frozen=True)
class AntoineCoeffs:
    """Antoine vapour-pressure correlation (Perry / Lange form).

    ``log10(P_sat / mmHg) = A − B / (T_°C + C)``
    """

    A: float
    B: float
    C: float
    T_min_K: float = 273.15
    T_max_K: float = 500.0


@dataclass(frozen=True)
class Component:
    """All property-package-relevant data for a single chemical species.

    Most fields are optional. A property package documents which fields it
    requires; an attempt to use a method on a species lacking the required
    field raises a clear ``ValueError`` at residual time.
    """

    id: str
    name: str
    formula: str
    cas: Optional[str] = None

    # Bulk properties
    MW: float = 0.0                          # g/mol
    Tb_K: Optional[float] = None             # normal boiling point
    Tm_K: Optional[float] = None             # normal melting point
    Hf_298_J_mol: Optional[float] = None     # gas-phase ΔH_f° at 298.15 K

    # Cubic-EOS parameters
    Tc_K: Optional[float] = None             # critical temperature
    Pc_Pa: Optional[float] = None            # critical pressure (Pa — note unit)
    omega: Optional[float] = None            # Pitzer acentric factor

    # Property correlations
    shomate: Optional[ShomateCoeffs] = None
    antoine: Optional[AntoineCoeffs] = None

    # Activity-coefficient (UNIQUAC) parameters
    uniquac_r: Optional[float] = None        # van der Waals volume
    uniquac_q: Optional[float] = None        # van der Waals surface area

    # Cross-reference
    aliases: Tuple[str, ...] = ()
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

REGISTRY: Dict[str, Component] = {}


def register(c: Component) -> None:
    """Add ``c`` to REGISTRY under its primary id and all aliases.

    A duplicate registration on the same id raises ``KeyError`` so silent
    overwrites cannot happen during module import or testing.
    """
    if c.id in REGISTRY and REGISTRY[c.id] is not c:
        raise KeyError(f"Duplicate component id {c.id!r}")
    REGISTRY[c.id] = c
    for alias in c.aliases:
        # Aliases may already point to this component (idempotent). Silent
        # collision with a different component is an error.
        existing = REGISTRY.get(alias)
        if existing is not None and existing is not c:
            raise KeyError(
                f"Alias {alias!r} on {c.id!r} collides with existing "
                f"component {existing.id!r}"
            )
        REGISTRY[alias] = c


def get(species: str) -> Component:
    """Return the ``Component`` for *species* (canonical id or alias)."""
    try:
        return REGISTRY[species]
    except KeyError:
        known = sorted({c.id for c in REGISTRY.values()})
        raise KeyError(
            f"Component {species!r} not in registry. Known canonical ids: "
            f"{known}"
        )


def has_shomate(species: str) -> bool:
    return species in REGISTRY and REGISTRY[species].shomate is not None


def has_antoine(species: str) -> bool:
    return species in REGISTRY and REGISTRY[species].antoine is not None


def has_eos_params(species: str) -> bool:
    if species not in REGISTRY:
        return False
    c = REGISTRY[species]
    return c.Tc_K is not None and c.Pc_Pa is not None and c.omega is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tier-1 species — every species used in v1.5.3 unit models or tests.
# Numerics MUST match the existing SHOMATE / ANTOINE dictionaries; regression
# tests in test_properties.py validate this at every commit.
# ─────────────────────────────────────────────────────────────────────────────

register(Component(
    id="H2", name="hydrogen", formula="H2", cas="1333-74-0",
    MW=2.016, Tb_K=20.27, Tm_K=13.99, Hf_298_J_mol=0.0,
    Tc_K=33.18, Pc_Pa=13.0e5, omega=-0.220,
    shomate=ShomateCoeffs(
        A=33.066178, B=-11.363417, C=11.432816, D=-2.772874,
        E=-0.158558, F=-9.980797, H=0.0, T_min=298, T_max=1000,
    ),
    antoine=AntoineCoeffs(A=6.23400, B=99.395, C=307.180, T_min_K=15, T_max_K=33),
    aliases=("hydrogen",),
))

register(Component(
    id="O2", name="oxygen", formula="O2", cas="7782-44-7",
    MW=31.999, Tb_K=90.19, Tm_K=54.36, Hf_298_J_mol=0.0,
    Tc_K=154.58, Pc_Pa=50.43e5, omega=0.022,
    shomate=ShomateCoeffs(
        A=31.32234, B=-20.23531, C=57.86644, D=-36.50624,
        E=-0.007374, F=-8.903471, H=0.0, T_min=100, T_max=700,
    ),
    aliases=("oxygen",),
))

register(Component(
    id="N2", name="nitrogen", formula="N2", cas="7727-37-9",
    MW=28.014, Tb_K=77.36, Tm_K=63.15, Hf_298_J_mol=0.0,
    Tc_K=126.20, Pc_Pa=33.98e5, omega=0.037,
    shomate=ShomateCoeffs(
        A=28.98641, B=1.853978, C=-9.647574, D=16.63537,
        E=0.000117, F=-8.671914, H=0.0, T_min=298, T_max=1000,
    ),
    aliases=("nitrogen",),
))

register(Component(
    id="CO", name="carbon monoxide", formula="CO", cas="630-08-0",
    MW=28.010, Tb_K=81.65, Tm_K=68.13, Hf_298_J_mol=-110527.0,
    Tc_K=132.92, Pc_Pa=34.99e5, omega=0.066,
    shomate=ShomateCoeffs(
        A=25.567959, B=6.096130, C=4.054656, D=-2.671301,
        E=0.131021, F=-118.009590, H=-110.527, T_min=298, T_max=1300,
    ),
    aliases=("carbon_monoxide",),
))

register(Component(
    id="CO2", name="carbon dioxide", formula="CO2", cas="124-38-9",
    MW=44.010, Tb_K=194.65, Tm_K=216.58, Hf_298_J_mol=-393510.0,
    Tc_K=304.13, Pc_Pa=73.77e5, omega=0.224,
    shomate=ShomateCoeffs(
        A=24.997557, B=55.187022, C=-33.691572, D=7.948387,
        E=-0.136638, F=-403.608069, H=-393.510, T_min=298, T_max=1200,
    ),
    antoine=AntoineCoeffs(A=6.81228, B=975.700, C=270.580, T_min_K=194, T_max_K=304),
    aliases=("carbon_dioxide",),
))

register(Component(
    id="CH4", name="methane", formula="CH4", cas="74-82-8",
    MW=16.043, Tb_K=111.65, Tm_K=90.69, Hf_298_J_mol=-74873.0,
    Tc_K=190.56, Pc_Pa=45.99e5, omega=0.011,
    shomate=ShomateCoeffs(
        A=-0.703029, B=108.477300, C=-42.521800, D=5.862640,
        E=0.678565, F=-76.843500, H=-74.873, T_min=298, T_max=1300,
    ),
    antoine=AntoineCoeffs(A=6.69561, B=405.420, C=267.780, T_min_K=111, T_max_K=190),
    aliases=("methane",),
))

register(Component(
    id="H2O", name="water", formula="H2O", cas="7732-18-5",
    MW=18.015, Tb_K=373.15, Tm_K=273.15, Hf_298_J_mol=-241826.0,
    Tc_K=647.10, Pc_Pa=220.64e5, omega=0.345,
    shomate=ShomateCoeffs(
        A=30.092000, B=6.832514, C=6.793435, D=-2.534480,
        E=0.082139, F=-250.881100, H=-241.826, T_min=298, T_max=1700,
    ),
    antoine=AntoineCoeffs(A=8.07131, B=1730.630, C=233.426, T_min_K=273, T_max_K=373),
    uniquac_r=0.92, uniquac_q=1.40,
    aliases=("water",),
))

# ── Tier-1 organics (existing Antoine entries) ──────────────────────────────

register(Component(
    id="benzene", name="benzene", formula="C6H6", cas="71-43-2",
    MW=78.114, Tb_K=353.24, Tm_K=278.68, Hf_298_J_mol=82880.0,
    Tc_K=562.05, Pc_Pa=48.95e5, omega=0.210,
    antoine=AntoineCoeffs(A=6.90565, B=1211.033, C=220.790, T_min_K=278, T_max_K=377),
    uniquac_r=3.1878, uniquac_q=2.40,
))

register(Component(
    id="toluene", name="toluene", formula="C7H8", cas="108-88-3",
    MW=92.140, Tb_K=383.78, Tm_K=178.18, Hf_298_J_mol=50170.0,
    Tc_K=591.75, Pc_Pa=41.08e5, omega=0.264,
    antoine=AntoineCoeffs(A=6.95334, B=1343.943, C=219.377, T_min_K=280, T_max_K=410),
    uniquac_r=3.9228, uniquac_q=2.97,
))

register(Component(
    id="n-hexane", name="n-hexane", formula="C6H14", cas="110-54-3",
    MW=86.178, Tb_K=341.88, Tm_K=177.83, Hf_298_J_mol=-166900.0,
    Tc_K=507.60, Pc_Pa=30.25e5, omega=0.301,
    antoine=AntoineCoeffs(A=6.87601, B=1171.170, C=224.408, T_min_K=286, T_max_K=342),
    uniquac_r=4.4998, uniquac_q=3.856,
    aliases=("hexane",),
))

register(Component(
    id="n-heptane", name="n-heptane", formula="C7H16", cas="142-82-5",
    MW=100.205, Tb_K=371.55, Tm_K=182.55, Hf_298_J_mol=-187800.0,
    Tc_K=540.20, Pc_Pa=27.40e5, omega=0.350,
    antoine=AntoineCoeffs(A=6.89385, B=1264.370, C=216.636, T_min_K=270, T_max_K=400),
    uniquac_r=5.1742, uniquac_q=4.396,
    aliases=("heptane",),
))

register(Component(
    id="methanol", name="methanol", formula="CH4O", cas="67-56-1",
    MW=32.042, Tb_K=337.85, Tm_K=175.61, Hf_298_J_mol=-201000.0,
    Tc_K=512.50, Pc_Pa=80.84e5, omega=0.565,
    antoine=AntoineCoeffs(A=7.89750, B=1474.080, C=217.840, T_min_K=288, T_max_K=357),
    uniquac_r=1.4311, uniquac_q=1.432,
))

register(Component(
    id="ethanol", name="ethanol", formula="C2H6O", cas="64-17-5",
    MW=46.069, Tb_K=351.44, Tm_K=159.05, Hf_298_J_mol=-234810.0,
    Tc_K=513.92, Pc_Pa=61.48e5, omega=0.649,
    antoine=AntoineCoeffs(A=8.11220, B=1592.864, C=226.184, T_min_K=290, T_max_K=369),
    uniquac_r=2.1055, uniquac_q=1.972,
))

# ─────────────────────────────────────────────────────────────────────────────
# Tier-2 species — new in v1.6. Critical-property data only for now; Shomate
# coefficients and group contributions are deferred to a follow-up sprint
# unless a unit model requires them.
# ─────────────────────────────────────────────────────────────────────────────

# Light paraffins (LPG / NGL / refining)
register(Component(
    id="ethane", name="ethane", formula="C2H6", cas="74-84-0",
    MW=30.070, Tb_K=184.55, Tm_K=90.36, Hf_298_J_mol=-83820.0,
    Tc_K=305.32, Pc_Pa=48.72e5, omega=0.099,
    antoine=AntoineCoeffs(A=6.95335, B=699.106, C=260.264, T_min_K=90, T_max_K=185),
))

register(Component(
    id="propane", name="propane", formula="C3H8", cas="74-98-6",
    MW=44.097, Tb_K=231.04, Tm_K=85.47, Hf_298_J_mol=-104680.0,
    Tc_K=369.83, Pc_Pa=42.48e5, omega=0.152,
    antoine=AntoineCoeffs(A=6.80398, B=803.81, C=246.99, T_min_K=164, T_max_K=249),
))

register(Component(
    id="n-butane", name="n-butane", formula="C4H10", cas="106-97-8",
    MW=58.123, Tb_K=272.65, Tm_K=134.79, Hf_298_J_mol=-125790.0,
    Tc_K=425.12, Pc_Pa=37.96e5, omega=0.200,
    antoine=AntoineCoeffs(A=6.83029, B=945.90, C=240.00, T_min_K=195, T_max_K=290),
    aliases=("butane",),
))

register(Component(
    id="i-butane", name="isobutane", formula="C4H10", cas="75-28-5",
    MW=58.123, Tb_K=261.34, Tm_K=113.55, Hf_298_J_mol=-134990.0,
    Tc_K=407.81, Pc_Pa=36.29e5, omega=0.184,
    antoine=AntoineCoeffs(A=6.78866, B=899.617, C=241.942, T_min_K=190, T_max_K=280),
    aliases=("isobutane",),
))

register(Component(
    id="n-pentane", name="n-pentane", formula="C5H12", cas="109-66-0",
    MW=72.150, Tb_K=309.21, Tm_K=143.43, Hf_298_J_mol=-146760.0,
    Tc_K=469.70, Pc_Pa=33.70e5, omega=0.252,
    antoine=AntoineCoeffs(A=6.85221, B=1064.63, C=232.000, T_min_K=270, T_max_K=380),
    aliases=("pentane",),
))

# Light olefins (petrochemical building blocks)
register(Component(
    id="ethylene", name="ethylene", formula="C2H4", cas="74-85-1",
    MW=28.054, Tb_K=169.42, Tm_K=104.01, Hf_298_J_mol=52280.0,
    Tc_K=282.34, Pc_Pa=50.41e5, omega=0.087,
    antoine=AntoineCoeffs(A=6.74756, B=585.00, C=255.00, T_min_K=120, T_max_K=200),
    aliases=("ethene",),
))

register(Component(
    id="propylene", name="propylene", formula="C3H6", cas="115-07-1",
    MW=42.081, Tb_K=225.46, Tm_K=87.89, Hf_298_J_mol=20410.0,
    Tc_K=364.85, Pc_Pa=46.00e5, omega=0.137,
    antoine=AntoineCoeffs(A=6.81960, B=789.62, C=247.99, T_min_K=160, T_max_K=240),
    aliases=("propene",),
))

# Cyclics & aromatics
register(Component(
    id="cyclohexane", name="cyclohexane", formula="C6H12", cas="110-82-7",
    MW=84.162, Tb_K=353.87, Tm_K=279.69, Hf_298_J_mol=-123140.0,
    Tc_K=553.50, Pc_Pa=40.73e5, omega=0.211,
    antoine=AntoineCoeffs(A=6.84130, B=1201.531, C=222.647, T_min_K=280, T_max_K=380),
    uniquac_r=4.0464, uniquac_q=3.240,
))

register(Component(
    id="p-xylene", name="p-xylene", formula="C8H10", cas="106-42-3",
    MW=106.167, Tb_K=411.51, Tm_K=286.41, Hf_298_J_mol=17950.0,
    Tc_K=616.20, Pc_Pa=35.11e5, omega=0.322,
    antoine=AntoineCoeffs(A=6.99053, B=1453.430, C=215.307, T_min_K=290, T_max_K=440),
))

# Alcohols beyond C2
register(Component(
    id="n-propanol", name="1-propanol", formula="C3H8O", cas="71-23-8",
    MW=60.096, Tb_K=370.35, Tm_K=147.05, Hf_298_J_mol=-255200.0,
    Tc_K=536.78, Pc_Pa=51.75e5, omega=0.629,
    antoine=AntoineCoeffs(A=7.99733, B=1569.70, C=204.64, T_min_K=290, T_max_K=400),
    aliases=("1-propanol",),
))

register(Component(
    id="isopropanol", name="2-propanol", formula="C3H8O", cas="67-63-0",
    MW=60.096, Tb_K=355.41, Tm_K=185.26, Hf_298_J_mol=-272590.0,
    Tc_K=508.30, Pc_Pa=47.62e5, omega=0.668,
    antoine=AntoineCoeffs(A=8.11778, B=1580.92, C=219.61, T_min_K=283, T_max_K=370),
    aliases=("2-propanol", "ipa"),
))

register(Component(
    id="n-butanol", name="1-butanol", formula="C4H10O", cas="71-36-3",
    MW=74.123, Tb_K=390.88, Tm_K=183.85, Hf_298_J_mol=-274430.0,
    Tc_K=563.05, Pc_Pa=44.14e5, omega=0.591,
    antoine=AntoineCoeffs(A=7.83847, B=1558.19, C=196.881, T_min_K=310, T_max_K=410),
    aliases=("1-butanol",),
))

register(Component(
    id="ethylene_glycol", name="ethylene glycol", formula="C2H6O2", cas="107-21-1",
    MW=62.068, Tb_K=470.45, Tm_K=260.15, Hf_298_J_mol=-389300.0,
    Tc_K=719.70, Pc_Pa=82.00e5, omega=0.487,
    antoine=AntoineCoeffs(A=8.09080, B=2088.93, C=203.45, T_min_K=370, T_max_K=480),
    aliases=("MEG",),
))

# Carbonyls and acids
register(Component(
    id="acetone", name="acetone", formula="C3H6O", cas="67-64-1",
    MW=58.080, Tb_K=329.22, Tm_K=178.45, Hf_298_J_mol=-217150.0,
    Tc_K=508.20, Pc_Pa=47.01e5, omega=0.307,
    antoine=AntoineCoeffs(A=7.02447, B=1161.00, C=224.00, T_min_K=260, T_max_K=350),
))

register(Component(
    id="acetic_acid", name="acetic acid", formula="C2H4O2", cas="64-19-7",
    MW=60.052, Tb_K=391.05, Tm_K=289.81, Hf_298_J_mol=-432250.0,
    Tc_K=592.70, Pc_Pa=57.90e5, omega=0.467,
    antoine=AntoineCoeffs(A=7.38782, B=1533.313, C=222.309, T_min_K=290, T_max_K=400),
))

# Amines and ammonia
register(Component(
    id="ammonia", name="ammonia", formula="NH3", cas="7664-41-7",
    MW=17.031, Tb_K=239.82, Tm_K=195.41, Hf_298_J_mol=-45940.0,
    Tc_K=405.65, Pc_Pa=112.78e5, omega=0.253,
    antoine=AntoineCoeffs(A=7.55466, B=1002.711, C=247.885, T_min_K=190, T_max_K=333),
    aliases=("NH3",),
))

# MEA — Pc varies in literature; the value below is the most common DIPPR
# estimate (Lide, *CRC Handbook* 90e). Antoine coefficients fit to DIPPR
# vapor-pressure data over 320–470 K.
register(Component(
    id="MEA", name="monoethanolamine", formula="C2H7NO", cas="141-43-5",
    MW=61.083, Tb_K=443.45, Tm_K=283.65, Hf_298_J_mol=-208000.0,
    Tc_K=678.00, Pc_Pa=44.74e5, omega=0.450,
    antoine=AntoineCoeffs(A=7.45627, B=1592.220, C=159.500, T_min_K=320, T_max_K=470),
    aliases=("monoethanolamine",),
    notes="Pc literature range 44–73 bar; ω estimate. Use with caution at "
          "high P or near critical.",
))

# Sour gas and combustion products
register(Component(
    id="H2S", name="hydrogen sulfide", formula="H2S", cas="7783-06-4",
    MW=34.082, Tb_K=212.85, Tm_K=187.65, Hf_298_J_mol=-20630.0,
    Tc_K=373.40, Pc_Pa=89.63e5, omega=0.094,
    antoine=AntoineCoeffs(A=7.04270, B=872.000, C=270.500, T_min_K=190, T_max_K=320),
    aliases=("hydrogen_sulfide",),
))

register(Component(
    id="SO2", name="sulfur dioxide", formula="SO2", cas="7446-09-5",
    MW=64.066, Tb_K=263.13, Tm_K=200.75, Hf_298_J_mol=-296840.0,
    Tc_K=430.75, Pc_Pa=78.84e5, omega=0.245,
    antoine=AntoineCoeffs(A=7.32776, B=999.900, C=237.190, T_min_K=200, T_max_K=350),
    aliases=("sulfur_dioxide",),
))

# Inerts
register(Component(
    id="Ar", name="argon", formula="Ar", cas="7440-37-1",
    MW=39.948, Tb_K=87.30, Tm_K=83.81, Hf_298_J_mol=0.0,
    Tc_K=150.86, Pc_Pa=48.98e5, omega=0.000,
    aliases=("argon",),
))


# ─────────────────────────────────────────────────────────────────────────────
# Back-compat builders. These rebuild the legacy SHOMATE / ANTOINE / MW /
# H_REF_298 dictionaries from the REGISTRY. The functions are called once at
# module import time in ``ideal_gas.py`` and ``vle.py`` — the dicts they
# produce are byte-identical to the v1.5.3 versions for every species that
# was already present, with new species appearing only if they carry the
# relevant coefficients.
# ─────────────────────────────────────────────────────────────────────────────


def _build_shomate_dict() -> Dict[str, Dict[str, float]]:
    """Rebuild the legacy ``SHOMATE`` dict — primary ids only, no aliases.

    The legacy callers iterate ``SHOMATE.keys()`` (e.g. ``set(SHOMATE)``)
    to discover the set of known species. Emitting aliases would inflate
    that set and confuse callers, so each species appears once under its
    canonical id.
    """
    out: Dict[str, Dict[str, float]] = {}
    seen_ids: set[str] = set()
    for key, c in REGISTRY.items():
        if c.id in seen_ids:
            continue
        if c.shomate is None:
            continue
        s = c.shomate
        out[c.id] = {
            "A": s.A, "B": s.B, "C": s.C, "D": s.D,
            "E": s.E, "F": s.F, "H": s.H,
            "T_min": s.T_min, "T_max": s.T_max,
        }
        seen_ids.add(c.id)
    return out


def _build_antoine_dict() -> Dict[str, Dict[str, float]]:
    """Rebuild the legacy ``ANTOINE`` dict.

    Unlike ``_build_shomate_dict`` this emits **all** keys (canonical id +
    aliases) so that both ``ANTOINE["methane"]`` and ``ANTOINE["CH4"]``
    resolve correctly — the v1.5.3 data file used "methane" while the
    Shomate file used "CH4" for the same physical species.
    """
    out: Dict[str, Dict[str, float]] = {}
    for key, c in REGISTRY.items():
        if c.antoine is None:
            continue
        a = c.antoine
        out[key] = {
            "A": a.A, "B": a.B, "C": a.C,
            "T_min": a.T_min_K, "T_max": a.T_max_K,
        }
    return out


def _build_mw_dict() -> Dict[str, float]:
    """Rebuild the legacy ``MW`` dict — restricted to species that also have
    Shomate coefficients, which is exactly the v1.5.3 set.

    The legacy ``ideal_gas.MW`` carried molecular weights only for the seven
    Shomate species. New species in v1.6 have MWs on their ``Component`` but
    do not appear in this legacy dict; new code should use
    ``components.get(species).MW`` directly.
    """
    out: Dict[str, float] = {}
    seen_ids: set[str] = set()
    for key, c in REGISTRY.items():
        if c.id in seen_ids:
            continue
        if c.shomate is None or c.MW == 0.0:
            continue
        out[c.id] = c.MW
        seen_ids.add(c.id)
    return out


def _build_hf_298_dict() -> Dict[str, float]:
    """Rebuild the legacy ``H_REF_298`` dict from Shomate ``H`` coefficient.

    The legacy formula ``H_REF_298[sp] = SHOMATE[sp]["H"] * 1000.0`` reads
    the Shomate ``H`` field directly. We replicate that exactly so byte-
    identical regression is preserved.
    """
    out: Dict[str, float] = {}
    seen_ids: set[str] = set()
    for key, c in REGISTRY.items():
        if c.id in seen_ids:
            continue
        if c.shomate is None:
            continue
        out[c.id] = c.shomate.H * 1000.0
        seen_ids.add(c.id)
    return out


__all__ = [
    "Component", "ShomateCoeffs", "AntoineCoeffs",
    "REGISTRY", "register", "get",
    "has_shomate", "has_antoine", "has_eos_params",
    "_build_shomate_dict", "_build_antoine_dict",
    "_build_mw_dict", "_build_hf_298_dict",
]
