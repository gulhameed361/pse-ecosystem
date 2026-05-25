"""Solve History page — persisted record of past solves with
filterable status / template / mode columns."""

from __future__ import annotations

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit




# ── Page: Solve History (v1.5.0.dev-AUDIT3 UI-2) ─────────────────────────────

def _page_solve_history() -> None:
    """Rolling log of the last 20 solves in this session + persistent log
    at ``~/.pse_ecosystem/history.jsonl`` (v1.5.0.dev-AUDIT4 #6).
    """
    st = _require_streamlit()
    _init_state(st)

    st.title("Solve History")
    st.caption(
        "In-memory log of the last 20 solves in this session + persistent "
        "log at `~/.pse_ecosystem/history.jsonl` (survives app reload)."
    )

    # v1.5.0.dev-AUDIT4 #6: lazy-seed from disk on first render.
    if not st.session_state.get("solve_history") and not st.session_state.get("_history_seeded"):
        from pse_ecosystem.ui.flowsheet_service import load_persisted_solve_history
        st.session_state["solve_history"] = load_persisted_solve_history(max_entries=20)
        st.session_state["_history_seeded"] = True

    history = st.session_state.get("solve_history", [])
    if not history:
        st.info(
            "No solves yet. Run one from **Solver Monitor**; entries appear here "
            "automatically (most-recent last) and persist to `~/.pse_ecosystem/history.jsonl`."
        )
        return

    import pandas as pd
    df = pd.DataFrame(history)
    # Most-recent first for readability.
    df = df.iloc[::-1].reset_index(drop=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total solves", len(history))
    c2.metric("Converged", int(df["converged"].sum()))
    c3.metric("Failed", int((~df["converged"]).sum()))
    last_status = df.iloc[0]["status"] if len(df) else "—"
    c4.metric("Most recent", last_status)

    st.dataframe(
        df[[
            "timestamp", "mode", "objective", "status", "iterations",
            "obj_value", "n_vars", "n_kpis", "message",
        ]].style.format({"obj_value": "{:.6g}"}),
        use_container_width=True,
        hide_index=True,
    )

    if st.button("Clear history", type="secondary"):
        st.session_state["solve_history"] = []
        st.success("History cleared.")
        st.rerun()


# ── Main entry point ──────────────────────────────────────────────────────────
