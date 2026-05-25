"""Shared UI helpers used across multiple Streamlit pages.

Extracted from ``app_streamlit.py`` in v1.6.1 P.2 — see
``docs/PLAN_v1_6_1.md``.
"""

from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit

__all__ = [
    "_init_state",
    "_infer_si_unit",
    "_require_streamlit",
]
