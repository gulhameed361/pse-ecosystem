"""Per-variable scaling factors for LP and NLP models.

Called by lp_builder and nlp_builder to improve numerical conditioning.
Scaling is bounded-magnitude normalisation: scale_v = 1 / max(|lo|, |hi|, 1).
"""

from __future__ import annotations

from typing import Dict, Optional

import pyomo.environ as pyo

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
