"""PSE Ecosystem — multi-page Streamlit front-end entry point.

Run with::

    streamlit run pse_ecosystem/ui/app_streamlit.py

Requires the GUI extra::

    pip install 'pse_ecosystem[gui]'   # adds streamlit + plotly

All Streamlit and heavy-library imports are deferred to inside page
functions so this module can be imported without Streamlit installed
(e.g. during import checks in tests).

v1.6.1 P.2 refactor
-------------------
This module used to hold every page function inline (2 714 lines). The
page bodies have moved into ``pse_ecosystem/ui/pages/`` (one file per
page), and shared helpers (``_init_state`` / ``_infer_si_unit`` /
``_require_streamlit``) live under ``pse_ecosystem/ui/shared/``. This
file now contains only the ``main()`` entry point: persona toggle +
``st.navigation`` over the imported page functions.

Layer-boundary rule
-------------------
This file imports ONLY from:
  - ``pse_ecosystem.ui.shared.*``   (Layer 1 shared helpers)
  - ``pse_ecosystem.ui.pages.*``    (Layer 1 page modules)

It does NOT import from ``pse_ecosystem.models.*`` or
``pse_ecosystem.flowsheets.*``.
"""

from __future__ import annotations

# Shared helpers re-exported for back-compat — tests still import these
# names directly from ``pse_ecosystem.ui.app_streamlit``.
from pse_ecosystem.ui.shared.formatting import _infer_si_unit  # noqa: F401
from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit

# Page functions — one import per page.
from pse_ecosystem.ui.pages.dashboard import _page_dashboard
from pse_ecosystem.ui.pages.dynamics_studio import _page_dynamics_studio
from pse_ecosystem.ui.pages.flowsheet_builder import _page_flowsheet_builder
from pse_ecosystem.ui.pages.gps_weather import _page_gps_weather
from pse_ecosystem.ui.pages.help_center import _page_help_center
from pse_ecosystem.ui.pages.pinch_preview import _page_pinch_preview
from pse_ecosystem.ui.pages.relief_sizing import _page_relief_sizing
from pse_ecosystem.ui.pages.scenario_manager import _page_scenario_manager
from pse_ecosystem.ui.pages.solve_history import _page_solve_history
from pse_ecosystem.ui.pages.solver_monitor import _page_solver_monitor
from pse_ecosystem.ui.pages.validation import _page_validation


def main() -> None:
    st = _require_streamlit()

    st.set_page_config(
        page_title="PSE Ecosystem",
        page_icon="⚗",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _init_state(st)

    # ── Persona toggle — set once in main() so every page sees a stable value
    with st.sidebar:
        st.divider()
        st.caption("View Mode")
        _persona_idx = (
            0
            if st.session_state.get("user_persona", "Academic") == "Academic"
            else 1
        )
        _persona = st.radio(
            "Persona",
            ["Academic", "Industrial"],
            index=_persona_idx,
            key="persona_radio",
            horizontal=True,
        )
        st.session_state["user_persona"] = _persona
        if _persona == "Industrial":
            st.caption("CapEx · ASME · finance")
        else:
            st.caption("Jacobians · residuals · derivatives")

    pages = [
        st.Page(_page_dashboard,         title="Dashboard",                    icon="🏠"),
        st.Page(_page_flowsheet_builder, title="Flowsheet Builder",            icon="🔧"),
        st.Page(_page_gps_weather,       title="Site Weather",                 icon="🌍"),
        st.Page(_page_solver_monitor,    title="Solver Monitor",               icon="📊"),
        st.Page(_page_scenario_manager,  title="Scenario Manager & Analysis", icon="📋"),
        st.Page(_page_validation,        title="Validation",                   icon="✅"),
        st.Page(_page_pinch_preview,     title="Pinch Preview",                icon="🔥"),
        st.Page(_page_dynamics_studio,   title="Dynamics Studio",              icon="⏱"),
        st.Page(_page_relief_sizing,     title="Relief Sizing",                icon="🛡"),
        st.Page(_page_solve_history,     title="Solve History",                icon="📜"),
        st.Page(_page_help_center,       title="Help Center",                  icon="📖"),
    ]
    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
