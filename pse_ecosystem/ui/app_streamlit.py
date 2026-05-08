"""Streamlit front-end stub for PSE Ecosystem.

Run with::

    streamlit run pse_ecosystem/ui/app_streamlit.py

Requires the GUI extra::

    pip install 'pse_ecosystem[gui]'

All Streamlit imports are deferred inside ``main()`` so the module can be
imported without Streamlit installed (e.g. during import checks in tests).
"""

from __future__ import annotations


def _require_streamlit():
    try:
        import streamlit as st  # type: ignore
        return st
    except ImportError:
        raise ImportError(
            "streamlit is required to run the PSE Ecosystem GUI. "
            "Install with: pip install 'pse_ecosystem[gui]'"
        )


def main() -> None:
    st = _require_streamlit()

    st.set_page_config(
        page_title="PSE Ecosystem",
        page_icon="⚗️",
        layout="wide",
    )
    st.title("PSE Ecosystem — Process Optimisation Platform")
    st.caption("v0.1.0  |  Private — University of Surrey")

    # ── Sidebar: solver configuration ─────────────────────────────────────
    with st.sidebar:
        st.header("Configuration")
        theme_choice = st.selectbox("Theme", ["hydrogen"])
        app_choice   = st.selectbox(
            "Application",
            ["electrolysis_only", "electrolysis_or_gasification"],
        )
        mode_label = st.radio(
            "Solver Mode",
            ["Mode 1 — Fixed LP", "Mode 2 — Flexible MILP"],
        )
        demand = st.number_input(
            "H2 Demand (kg/h)", min_value=1.0, max_value=500.0, value=100.0, step=10.0
        )
        verbose = st.checkbox("Verbose solver output", value=False)
        run_btn = st.button("Run Optimisation", type="primary")

    # ── Main panel ────────────────────────────────────────────────────────
    if not run_btn:
        st.info(
            "Configure the solver settings in the sidebar, then click "
            "**Run Optimisation** to solve."
        )
        st.markdown(
            """
### Available Unit Models (v0.1.0)
| Unit | Type | Jacobian |
|---|---|---|
| PEMToy | Linear electrolyser | Analytical |
| GasifierToy | Non-linear gasifier | Analytical |
| IdealMixer | Linear mixer | Analytical |
| HeatExchangerToy | Non-linear HX (LMTD) | FD |
| BoilerToy | Linear boiler | Analytical |
| CSTRToy | Non-linear CSTR | Analytical |
| FlashToy | Non-linear flash | FD |
| HDAPFRUnit | Black-box HDA reactor | FD (ODE) |
| HDAFlashUnit | Black-box HDA flash | FD (VLE) |
| HDADistillationUnit | Black-box HDA column | FD (FUG) |
"""
        )
        return

    # ── Solve ─────────────────────────────────────────────────────────────
    import pse_ecosystem.themes.hydrogen  # noqa: F401 — registers theme
    from pse_ecosystem.core.contracts import SolveMode
    from pse_ecosystem.core.registry import get_theme
    from pse_ecosystem.solvers.orchestrator import Orchestrator
    from pse_ecosystem.solvers.slp import SLPConfig

    mode = SolveMode.FIXED_LP if "1" in mode_label else SolveMode.FLEXIBLE_MILP
    theme_obj = get_theme(theme_choice)
    app_obj   = theme_obj.applications[app_choice]

    factory_result = app_obj.flowsheet_factory(h2_demand_kg_per_h=demand)
    if isinstance(factory_result, tuple):
        flowsheet, tech_choices = factory_result
    else:
        flowsheet, tech_choices = factory_result, None

    if mode == SolveMode.FLEXIBLE_MILP and tech_choices is None:
        st.error("This application does not support Mode 2. Choose Mode 1.")
        return

    orch = Orchestrator(
        flowsheet=flowsheet,
        mode=mode,
        slp_config=SLPConfig(verbose=verbose),
        technology_choices=tech_choices or [],
    )

    with st.spinner("Solving..."):
        result = orch.solve()

    # ── Results ───────────────────────────────────────────────────────────
    if result.converged:
        st.success(
            f"Converged in **{result.iterations}** iteration(s)  |  "
            f"Objective: **{result.objective:.4g}**"
        )
    else:
        st.error(f"Solver status: **{result.status.value}** — {result.message}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Solution Variables")
        st.json({k: round(v, 6) for k, v in result.x.items()})
    with col2:
        st.subheader("KPIs")
        st.json({k: round(v, 6) for k, v in result.kpis.items()})

    if result.technology_selection:
        st.subheader("Technology Selection")
        selected = [k for k, v in result.technology_selection.items() if v]
        st.success(f"Active technologies: {', '.join(selected) or 'none'}")
        st.json(result.technology_selection)


if __name__ == "__main__":
    main()
