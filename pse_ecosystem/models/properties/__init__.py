"""Physical property functions for use in Layer 3 unit models.

All functions are pure Python/NumPy — no Pyomo, no external thermodynamic
libraries required for basic operation.  Optional scipy is used only in vle.py
for the Rachford-Rice solver.
"""

from pse_ecosystem.models.properties.ideal_gas import (
    SHOMATE,
    MW,
    H_REF_298,
    cp_J_mol_K,
    enthalpy_J_mol,
    mixture_cp_J_mol_K,
    mixture_enthalpy_J_mol,
    gamma,
)
from pse_ecosystem.models.properties.vle import (
    ANTOINE,
    K_value,
    rachford_rice,
    bubble_T,
    dew_T,
)
from pse_ecosystem.models.properties.property_package import (
    PHASE_LIQUID,
    PHASE_VAPOR,
    IdealGasPackage,
    PropertyPackage,
    available_methods,
    get_property_package,
    register_package,
)
# Side-effect import: registers peng_robinson / srk with the factory.
from pse_ecosystem.models.properties.cubic_eos import (
    CubicEOSPackage,
    PengRobinsonPackage,
    SRKPackage,
)
# Side-effect import: registers nrtl / wilson / uniquac with the factory.
from pse_ecosystem.models.properties.activity_models import (
    ActivityModelPackage,
    NRTLPackage,
    WilsonPackage,
    UNIQUACPackage,
)
from pse_ecosystem.models.properties.flash import FlashResult, flash_PT

__all__ = [
    "SHOMATE", "MW", "H_REF_298",
    "cp_J_mol_K", "enthalpy_J_mol", "mixture_cp_J_mol_K",
    "mixture_enthalpy_J_mol", "gamma",
    "ANTOINE", "K_value", "rachford_rice", "bubble_T", "dew_T",
    "PHASE_VAPOR", "PHASE_LIQUID",
    "PropertyPackage", "IdealGasPackage",
    "CubicEOSPackage", "PengRobinsonPackage", "SRKPackage",
    "ActivityModelPackage", "NRTLPackage", "WilsonPackage", "UNIQUACPackage",
    "FlashResult", "flash_PT",
    "get_property_package", "available_methods", "register_package",
]
