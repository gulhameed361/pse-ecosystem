"""Streamlit session-state initialisation.

One ``_init_state(st)`` call per page render seeds every session key the
app expects. Centralising the defaults here means new keys can be added
without touching every page module.
"""

from __future__ import annotations


def _init_state(st) -> None:
    st.session_state.setdefault("selected_template", None)
    st.session_state.setdefault("template_params", {})
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_flowsheet", None)        # v1.4.0 audit M10
    st.session_state.setdefault("custom_flowsheet", None)      # v1.4.0 audit M10
    st.session_state.setdefault("custom_flowsheet_cfg", None)  # v1.5.2 serializable config dict
    st.session_state.setdefault("objective_config", None)      # v1.4.0 audit M10
    st.session_state.setdefault("weather_ghi", None)
    st.session_state.setdefault("weather_wind", None)
    st.session_state.setdefault("weather_site", None)
    st.session_state.setdefault("user_persona", "Academic")    # v1.5.0 dual-persona
    st.session_state.setdefault("last_solve_elapsed", None)   # v1.5.1 solve timing
    st.session_state.setdefault("scenarios", [])              # v1.5.1 scenario manager


__all__ = ["_init_state"]
