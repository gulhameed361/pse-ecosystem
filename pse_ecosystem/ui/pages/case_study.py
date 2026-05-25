"""Case Study page (stub) — retained for navigation back-compat
after the Biomass → H₂ template moved into Flowsheet Builder."""

from __future__ import annotations

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit




def _page_case_study():
    """Stub retained for import-compatibility; page removed from navigation."""
    st = _require_streamlit()
    st.info(
        "The Biomass → H₂ case study has moved to the **Flowsheet Builder**. "
        "Select the 'Biomass → H₂ (Gasification)' template there."
    )



# ── Page 4: GPS Weather ───────────────────────────────────────────────────────
