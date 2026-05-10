"""SSLW Equipment Costing — pure Python.

Algebraic purchase-cost correlations extracted from:
    Seider, Seader, Lewin, Windagdo (SSLW), "Product and Process Design
    Principles", 3rd/4th Ed., Wiley.  Same coefficients used in the IDAES
    SSLW.py costing package but stripped of all Pyomo machinery.

All costs are on the CE (Chemical Engineering Plant Cost) Index basis at
CE = 500 (≈ year 2001).  Escalate to current year via:
    cost_now = cost_CE500 * CEPCI_now / 500

Layer compliance: this module lives in models/costing/ (Layer 3).
It is never imported by Layer 2 solvers.
"""

from __future__ import annotations

import math

# ── Material factors ──────────────────────────────────────────────────────────

MATERIAL_FACTORS = {
    "CS":  1.0,   # Carbon Steel (base)
    "SS":  2.5,   # Stainless Steel 316
    "SS304": 2.1, # Stainless Steel 304
    "Ni":  5.0,   # Nickel Alloy (Monel)
    "Ti":  9.0,   # Titanium
    "Cu":  1.4,   # Copper / Brass
}


# ── Heat Exchangers ───────────────────────────────────────────────────────────

# SSLW Table 22.19 / Eq. 22.43: ln(Cp) = α₁ - α₂·ln(A) + α₃·ln(A)²  (A in ft²)
_HX_ALPHA = {
    "floating_head": (11.9052, 0.8709, 0.09005),
    "fixed_head":    (11.2927, 0.8228, 0.09861),
    "Utube":         (11.3852, 0.9186, 0.09790),
    "kettle_vap":    (12.2052, 0.8709, 0.09005),
}

# Tube-length correction factor (Eq. 22.44)
_HX_C_FL = {8: 1.25, 12: 1.12, 16: 1.05, 20: 1.00}

# Material/shell-side correction: Fm = Am + (A_ft2/100)^Bm  (Table 22.20)
_HX_FM_PARAMS = {
    #      Am     Bm   (for shell/tube material CS/SS, etc.)
    "CS":  (0.00, 0.00),
    "SS":  (1.75, 0.13),
    "Ni":  (3.30, 0.08),
    "Ti":  (4.18, 0.08),
}


def hx_purchase_cost_USD(
    area_m2: float,
    hx_type: str = "Utube",
    material: str = "SS",
    tube_length_ft: int = 12,
    n_units: int = 1,
    oversize_factor: float = 1.1,
) -> float:
    """SSLW shell-and-tube HX purchase cost [USD, CE500 basis].

    Parameters
    ----------
    area_m2 : Heat transfer area per unit [m²].
    hx_type : One of 'floating_head', 'fixed_head', 'Utube', 'kettle_vap'.
    material : Shell material code (see MATERIAL_FACTORS).
    tube_length_ft : Tube length in feet (8, 12, 16 or 20).
    n_units : Number of identical shells in parallel.
    oversize_factor : Design oversize margin (default 1.1 = 10%).

    Valid range: 150–12 000 ft² per unit.
    """
    alpha = _HX_ALPHA[hx_type]
    c_fl = _HX_C_FL.get(tube_length_ft, 1.00)

    area_ft2_per_unit = area_m2 * 10.7639 / n_units * oversize_factor
    area_ft2_per_unit = max(area_ft2_per_unit, 150.0)  # lower validity bound

    ln_A = math.log(area_ft2_per_unit)
    Cp_per_unit = math.exp(alpha[0] - alpha[1] * ln_A + alpha[2] * ln_A ** 2)

    # Material / pressure factor
    am_params = _HX_FM_PARAMS.get(material, (0.0, 0.0))
    if material == "CS":
        fm = 1.0
    else:
        fm = am_params[0] + (area_ft2_per_unit / 100.0) ** am_params[1]

    return fm * c_fl * Cp_per_unit * n_units


# ── Vessels (CSTR, Flash drum, etc.) ─────────────────────────────────────────


def vessel_purchase_cost_USD(
    volume_m3: float,
    material: str = "CS",
) -> float:
    """Generic vertical vessel purchase cost [USD, CE500 basis].

    Correlation: ln(Cp) = 7.0600 + 0.8068·ln(V_gal) + 0.03850·ln(V_gal)²
    Valid range: 1–10 000 US gallons.
    """
    V_gal = volume_m3 * 264.172
    V_gal = max(V_gal, 1.0)
    ln_V = math.log(V_gal)
    Cp_base = math.exp(7.0600 + 0.8068 * ln_V + 0.03850 * ln_V ** 2)
    return Cp_base * MATERIAL_FACTORS.get(material, 1.0)


def cstr_purchase_cost_USD(volume_m3: float, material: str = "CS") -> float:
    """CSTR purchase cost = vessel cost.  [USD, CE500 basis]."""
    return vessel_purchase_cost_USD(volume_m3, material)


# ── Compressors ───────────────────────────────────────────────────────────────

# SSLW Eq. 22.52: ln(Cp) = α₁ + α₂·ln(W_hp)
_COMP_ALPHA = {
    "Centrifugal":   (7.5800, 0.8),
    "Reciprocating": (7.9661, 0.8),
    "Screw":         (8.1238, 0.7243),
}

_COMP_DRIVE = {
    "ElectricMotor": 1.00,
    "SteamTurbine":  1.15,
    "GasTurbine":    1.25,
}


def compressor_purchase_cost_USD(
    work_W: float,
    comp_type: str = "Centrifugal",
    material: str = "SS",
    drive: str = "ElectricMotor",
) -> float:
    """SSLW compressor purchase cost [USD, CE500 basis].

    Parameters
    ----------
    work_W : Shaft power [W].
    comp_type : 'Centrifugal', 'Reciprocating', or 'Screw'.
    material : Casing material code.
    drive : Drive type.
    """
    work_hp = max(work_W / 745.7, 1.0)
    alpha = _COMP_ALPHA[comp_type]
    Cp = math.exp(alpha[0] + alpha[1] * math.log(work_hp))
    fd = _COMP_DRIVE.get(drive, 1.0)
    fm = MATERIAL_FACTORS.get(material, 1.0)
    return fd * fm * Cp


# ── Pumps ─────────────────────────────────────────────────────────────────────


def pump_purchase_cost_USD(
    work_W: float,
    material: str = "SS",
) -> float:
    """SSLW centrifugal pump purchase cost [USD, CE500 basis].

    Correlation: ln(Cp) = 9.7171 - 0.6019·ln(W_hp) + 0.0519·ln(W_hp)²
    Valid range: 1–300 hp.
    """
    work_hp = max(work_W / 745.7, 1.0)
    ln_W = math.log(work_hp)
    Cp = math.exp(9.7171 - 0.6019 * ln_W + 0.0519 * ln_W ** 2)
    return Cp * MATERIAL_FACTORS.get(material, 1.0)


# ── Turbines ──────────────────────────────────────────────────────────────────


def turbine_purchase_cost_USD(work_W: float) -> float:
    """SSLW axial turbine cost: Cp = 530 * W_hp^0.81  [USD, CE500 basis]."""
    work_hp = max(work_W / 745.7, 1.0)
    return 530.0 * work_hp ** 0.81


# ── Annualised CAPEX ──────────────────────────────────────────────────────────


def annualized_capex(
    purchase_cost_USD: float,
    lang_factor: float = 5.0,
    crf: float = 0.10,
    cepci_now: float = 800.0,
) -> float:
    """Convert SSLW purchase cost to annualised CAPEX [USD/yr].

    installed_cost = purchase_cost * lang_factor * (cepci_now / 500)
    annual_capex   = installed_cost * crf

    Parameters
    ----------
    lang_factor : Installed cost factor (3.1 direct, 5.0 total with indirects).
    crf : Capital recovery factor (≈ discount_rate / (1-(1+r)^-n) for n years).
    cepci_now : Current CE Plant Cost Index (CE=500 ≈ year 2001, ~800 in 2024).
    """
    installed = purchase_cost_USD * lang_factor * (cepci_now / 500.0)
    return installed * crf
