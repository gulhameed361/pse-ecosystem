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

__all__ = [
    "SHOMATE", "MW", "H_REF_298",
    "cp_J_mol_K", "enthalpy_J_mol", "mixture_cp_J_mol_K",
    "mixture_enthalpy_J_mol", "gamma",
    "ANTOINE", "K_value", "rachford_rice", "bubble_T", "dew_T",
]
