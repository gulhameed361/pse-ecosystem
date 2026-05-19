"""Per-variable AND per-residual-row scaling factors for LP and NLP models.

Called by lp_builder and nlp_builder to improve numerical conditioning.

* Variable scaling: ``compute_scaling_factors`` — bounded-magnitude
  normalisation ``scale_v = 1 / max(|lo|, |hi|, 1)``.
* Residual-row scaling (v1.5.0.dev-AUDIT2 L2-2): ``compute_residual_row_scaling``
  — row-norm normalisation so the linearised system is well-balanced when
  some equations are inherently larger-magnitude than others (e.g. element
  balances summing 100 mol/s vs equilibrium residuals at 1e-3 mol²/s).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pyomo.environ as pyo

from pse_ecosystem.core.contracts import LinearizedModel
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet


def compute_scaling_factors(flowsheet: BaseFlowsheet) -> Dict[str, float]:
    """Return {var_name: scale_factor} from aggregated variable bounds.

    Variables without finite bounds get scale factor 1.0 (no scaling).
    """
    factors: Dict[str, float] = {}
    for v, (lo, hi) in flowsheet.aggregated_bounds().items():
        mag_lo = abs(lo) if lo > -1e18 else 0.0
        mag_hi = abs(hi) if hi < 1e18 else 0.0
        magnitude = max(mag_lo, mag_hi, 1.0)
        factors[v] = 1.0 / magnitude
    return factors


def compute_residual_row_scaling(
    linearizations: List[LinearizedModel],
    floor: float = 1.0,
) -> Dict[Tuple[str, int], float]:
    """Return ``{(unit_id, row_index): scale_factor}`` for residual rows.

    For each row of each unit's Jacobian, the scale is ``1 / max(‖J_row‖∞, floor)``
    so that after multiplication the row-norm sits in [floor, 1]. This avoids
    amplifying tiny rows (numerical noise) while damping rows whose magnitudes
    are orders larger than the rest.

    Use ``floor=1.0`` (default) for general-purpose problems; smaller floors
    can be useful when most residuals are sub-unity (e.g. dimensionless
    equilibrium ratios).

    v1.5.0.dev-AUDIT2 L2-2: helper introduced. Application by ``lp_builder``
    and ``nlp_builder`` is opt-in via a future ``scale_rows: bool`` parameter
    to keep the v1.5.x LP topology identical until the scaling pathway is
    validated against the full regression suite.
    """
    factors: Dict[Tuple[str, int], float] = {}
    for lin in linearizations:
        if lin.J.size == 0:
            continue
        # ‖row‖∞ is the per-equation natural scale: largest |∂f/∂x_j|.
        row_norms = np.max(np.abs(lin.J), axis=1)
        for i, rn in enumerate(row_norms):
            factors[(lin.unit_id, i)] = 1.0 / max(float(rn), floor)
    return factors


def apply_scaling_suffix(
    model: pyo.ConcreteModel,
    factors: Dict[str, float],
) -> None:
    """Attach a Pyomo SCALING_FACTOR suffix so IPOPT sees scaled variables.

    Safe to call even when VARS / x are not yet defined — it silently skips
    variables not present in the model.
    """
    if not hasattr(model, "x"):
        return
    if not hasattr(model, "scaling_factor"):
        model.scaling_factor = pyo.Suffix(direction=pyo.Suffix.EXPORT)
    for v_name, scale in factors.items():
        try:
            model.scaling_factor[model.x[v_name]] = scale
        except KeyError:
            pass
