"""Help Center page — bundled documentation viewer."""

from __future__ import annotations

from pse_ecosystem.ui.shared.docs_loader import _docs_dir, _load_doc
from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit




def _page_help_center():
    st = _require_streamlit()
    _init_state(st)

    from pse_ecosystem import __version__ as _pse_version

    st.title("Help Center & Documentation")
    st.caption(
        f"PSE Ecosystem v{_pse_version} — live-loaded from the workspace `docs/` "
        f"folder. Edits to the source markdown refresh on the next page render."
    )

    _tabs = st.tabs([
        "User Manual",
        "7-Unit Workshop",
        "Theory Reference",
        "Architecture",
        "Developer Guide",
    ])
    _files = [
        "USER_MANUAL.md",
        "WORKSHOP_7UNIT.md",
        "THEORY_REFERENCE.md",
        "ARCHITECTURE.md",
        "DEVELOPER_GUIDE.md",
    ]
    for _tab, _fname in zip(_tabs, _files):
        with _tab:
            st.markdown(_load_doc(_fname))


# ── Page: Solve History (v1.5.0.dev-AUDIT3 UI-2) ─────────────────────────────
