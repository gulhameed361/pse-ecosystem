"""PSE Ecosystem — multi-page Streamlit front-end (v0.3.0).

Run with::

    streamlit run pse_ecosystem/ui/app_streamlit.py

Requires the GUI extra::

    pip install 'pse_ecosystem[gui]'  # adds streamlit + plotly

All Streamlit and heavy-library imports are deferred inside page functions so
the module can be imported without Streamlit installed (e.g. during import
checks in tests).

Layer-boundary rule
--------------------
This file imports ONLY from:
  - pse_ecosystem.ui.flowsheet_service   (the sole Layer-1 bridge to Layer 3)
  - pse_ecosystem.solvers.*              (Layer 2 — Orchestrator, SLPConfig)
  - pse_ecosystem.core.contracts         (protocol dataclasses — shared)

It does NOT import from pse_ecosystem.models.* or pse_ecosystem.flowsheets.*
"""

from __future__ import annotations


# ── Streamlit guard ───────────────────────────────────────────────────────────

def _require_streamlit():
    try:
        import streamlit as st  # type: ignore
        return st
    except ImportError:
        raise ImportError(
            "streamlit is required. Install with: pip install 'pse_ecosystem[gui]'"
        )


# ── Session state initialisation ──────────────────────────────────────────────

def _init_state(st) -> None:
    st.session_state.setdefault("selected_template", None)
    st.session_state.setdefault("template_params", {})
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("weather_ghi", None)
    st.session_state.setdefault("weather_wind", None)
    st.session_state.setdefault("weather_site", None)


# ── Page 1: Dashboard ─────────────────────────────────────────────────────────

def _page_dashboard():
    st = _require_streamlit()
    _init_state(st)

    from pse_ecosystem.ui.flowsheet_service import list_templates

    st.title("PSE Ecosystem")
    st.caption("v1.2.1  |  Private — University of Surrey")

    # ── LP solver check ────────────────────────────────────────────────────
    try:
        from pse_ecosystem.solvers.lp_builder import select_lp_solver
        select_lp_solver()
        solver_status = "Available"
    except RuntimeError as exc:
        solver_status = f"Not found"
        st.warning(
            f"No LP solver detected: {exc}. "
            "Install with: `pip install highspy` or install GLPK."
        )

    templates = list_templates()
    last_result = st.session_state.get("last_result")
    last_status = (
        str(last_result.status).split(".")[-1] if last_result else "No solve yet"
    )

    # ── Metric cards ────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Templates", len(templates))
    c2.metric("Unit Models", "16+ HF units")
    c3.metric("LP Solver", solver_status)
    c4.metric("Last Solve", last_status)

    st.divider()

    # ── Architecture overview ────────────────────────────────────────────────
    with st.expander("Architecture Overview", expanded=False):
        st.code(
            "Layer 1: UI (Streamlit)           ← you are here\n"
            "    │  calls flowsheet_service.py\n"
            "Layer 2: Solvers (Pyomo LP/MILP)  ← Orchestrator, SLPDriver\n"
            "    │  calls LinearizedModel interface\n"
            "Layer 3: Knowledge (Unit Models)  ← Physics, VLE, costing",
            language=None,
        )

    # ── Template gallery ─────────────────────────────────────────────────────
    st.subheader("Template Gallery")
    import pandas as pd

    rows = [
        {
            "Key": t.key,
            "Name": t.display_name,
            "Category": t.category,
            "Units": ", ".join(t.unit_labels),
            "Description": t.description[:80] + "..." if len(t.description) > 80 else t.description,
        }
        for t in templates
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Last result summary ──────────────────────────────────────────────────
    if last_result:
        st.divider()
        st.subheader("Last Solve Result")
        if last_result.converged:
            st.success(
                f"Converged in {last_result.iterations} iteration(s)  |  "
                f"Objective: {last_result.objective:.4g}"
            )
        else:
            st.error(
                f"Status: {str(last_result.status).split('.')[-1]}  |  "
                f"{last_result.message}"
            )


# ── Page 2: Flowsheet Builder ─────────────────────────────────────────────────

def _page_flowsheet_builder():
    st = _require_streamlit()
    _init_state(st)

    from pse_ecosystem.ui.flowsheet_service import list_templates, get_template

    st.title("Flowsheet Builder")

    templates = list_templates()
    categories = ["All"] + sorted({t.category for t in templates},
                                  key=lambda c: ["Custom", "Hydrogen", "Industrial", "Small"].index(c)
                                  if c in ["Custom", "Hydrogen", "Industrial", "Small"] else 99)

    col_left, col_right = st.columns([1, 2])

    with col_left:
        cat_filter = st.selectbox("Category", categories)
        filtered = (
            templates if cat_filter == "All"
            else [t for t in templates if t.category == cat_filter]
        )
        template_names = [t.display_name for t in filtered]
        template_keys  = [t.key for t in filtered]

        selected_idx = 0
        current_key = st.session_state.get("selected_template")
        if current_key in template_keys:
            selected_idx = template_keys.index(current_key)

        chosen_name = st.selectbox("Template", template_names, index=selected_idx)
        chosen_idx  = template_names.index(chosen_name)
        chosen_key  = template_keys[chosen_idx]
        spec = get_template(chosen_key)

        st.caption(spec.description)
        if spec.supports_milp:
            st.info("MILP template — use Mode 2 in Solver Monitor.")

    with col_right:
        st.subheader("Flowsheet Topology")

        use_simple = st.toggle("Use simple Graphviz diagram (offline)", value=False)
        if use_simple:
            # Fallback: generate a simple DOT graph from unit_labels
            dot_nodes = " ".join(f'"{u}"' for u in spec.unit_labels)
            dot_edges = " -> ".join(f'"{u}"' for u in spec.unit_labels)
            dot = f'digraph {{\n  rankdir=LR;\n  node [shape=box];\n  {dot_edges};\n}}'
            st.graphviz_chart(dot)
        else:
            mermaid_html = f"""
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<div class="mermaid" style="background:#1e1e2e;padding:12px;border-radius:8px">
{spec.topology_diagram}
</div>
<script>mermaid.initialize({{startOnLoad:true, theme:'dark'}});</script>
"""
            st.components.v1.html(mermaid_html, height=260, scrolling=False)

        # Connections table
        if spec.connections_human:
            import pandas as pd
            st.subheader("Stream Connections")
            st.dataframe(
                pd.DataFrame(
                    spec.connections_human,
                    columns=["From", "To", "Description"],
                ),
                use_container_width=True,
                hide_index=True,
            )

        # Parameter form — grouped by unit prefix
        st.subheader("Engineering Parameters")
        defaults = dict(spec.default_params)
        current_params = st.session_state.get("template_params", {})
        if st.session_state.get("selected_template") != chosen_key:
            current_params = {}

        # Custom flowsheet assembler (shown only for custom.user_flowsheet)
        if chosen_key == "custom.user_flowsheet":
            _render_custom_assembler(st, current_params, chosen_key, spec)
        else:
            with st.form("configure_template"):
                updated: dict = {}
                if defaults:
                    # Group params by unit prefix (e.g. "pem.", "comp.")
                    groups: dict = {}
                    for k, v in defaults.items():
                        prefix = k.split(".")[0] if "." in k else "flowsheet"
                        groups.setdefault(prefix, {})[k] = v

                    for group_name, group_params in groups.items():
                        label = "Flowsheet" if group_name == "flowsheet" else f"Unit: {group_name}"
                        with st.expander(label, expanded=True):
                            for k, v in group_params.items():
                                param_label = k.split(".")[-1].replace("_", " ").title()
                                cur_val = current_params.get(k, v)
                                if isinstance(v, float):
                                    updated[k] = st.number_input(
                                        param_label, value=float(cur_val), format="%.4g",
                                        key=f"param_{chosen_key}_{k}"
                                    )
                                elif isinstance(v, int):
                                    updated[k] = int(st.number_input(
                                        param_label, value=int(cur_val), step=1,
                                        key=f"param_{chosen_key}_{k}"
                                    ))
                                elif isinstance(v, str):
                                    updated[k] = st.text_input(
                                        param_label, value=str(cur_val),
                                        key=f"param_{chosen_key}_{k}"
                                    )
                                else:
                                    updated[k] = v
                else:
                    st.info("This template uses fixed default parameters.")

                if st.form_submit_button("Apply & Select", type="primary"):
                    st.session_state["selected_template"] = chosen_key
                    st.session_state["template_params"] = updated
                    st.success(
                        f"Template **{spec.display_name}** selected. "
                        "Go to **Solver Monitor** to run, or use the sweep below."
                    )

        st.divider()
        with st.expander("1D Parameter Sensitivity Sweep", expanded=False):
            _section_sensitivity_sweep(st, chosen_key, spec)


# ── Sensitivity sweep ────────────────────────────────────────────────────────

def _section_sensitivity_sweep(st, chosen_key: str, spec) -> None:
    """Render a 1D parameter sweep with live Plotly visualisation."""
    from pse_ecosystem.ui.flowsheet_service import load_template

    defaults = dict(spec.default_params)
    numeric_params = {
        k: v for k, v in defaults.items()
        if isinstance(v, (int, float)) and v != 0
    }
    if not numeric_params:
        st.info("No numeric parameters available for sweep.")
        return

    st.subheader("1D Parameter Sweep")
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        sweep_param = st.selectbox(
            "Sweep parameter", list(numeric_params.keys()),
            key=f"sweep_param_{chosen_key}",
        )
    default_val = float(numeric_params[sweep_param])
    with col_s2:
        sweep_min = st.number_input(
            "Min value", value=default_val * 0.5, format="%.4g",
            key=f"sweep_min_{chosen_key}",
        )
    with col_s3:
        sweep_max = st.number_input(
            "Max value", value=default_val * 1.5, format="%.4g",
            key=f"sweep_max_{chosen_key}",
        )
    with col_s4:
        n_points = int(st.number_input(
            "Points", min_value=3, max_value=30, value=8, step=1,
            key=f"sweep_n_{chosen_key}",
        ))

    if st.button("Run Sweep", key=f"run_sweep_{chosen_key}"):
        import numpy as np
        import pandas as pd

        sweep_values = list(np.linspace(sweep_min, sweep_max, n_points))
        base_params = dict(st.session_state.get("template_params", defaults))

        results_rows = []
        sweep_bar = st.progress(0, text="Sweeping…")

        try:
            from pse_ecosystem.solvers.orchestrator import Orchestrator
            from pse_ecosystem.solvers.slp import SLPConfig
            from pse_ecosystem.core.contracts import SolveMode

            for idx, val in enumerate(sweep_values):
                p = dict(base_params)
                p[sweep_param] = val
                try:
                    fs = load_template(chosen_key, p)
                    cfg = SLPConfig(max_iter=40, verbose=False)
                    orch = Orchestrator(flowsheet=fs, mode=SolveMode.FIXED_LP, slp_config=cfg)
                    res = orch.solve()
                    row = {sweep_param: val, "converged": res.converged}
                    row.update(res.kpis)
                except Exception:
                    row = {sweep_param: val, "converged": False}
                results_rows.append(row)
                sweep_bar.progress((idx + 1) / n_points, text=f"Point {idx+1}/{n_points}")

            sweep_bar.empty()
            df_sweep = pd.DataFrame(results_rows)

            # Plot all numeric KPI columns
            kpi_cols = [
                c for c in df_sweep.columns
                if c not in (sweep_param, "converged")
                and df_sweep[c].dtype in (float, int)
            ]
            if kpi_cols:
                import plotly.graph_objects as go
                fig_sw = go.Figure()
                for col in kpi_cols:
                    fig_sw.add_trace(go.Scatter(
                        x=df_sweep[sweep_param].tolist(),
                        y=df_sweep[col].tolist(),
                        mode="lines+markers",
                        name=col,
                    ))
                fig_sw.update_layout(
                    title=f"Sensitivity: KPIs vs {sweep_param}",
                    xaxis_title=sweep_param,
                    yaxis_title="KPI value",
                    height=420,
                    legend=dict(orientation="h", y=-0.25),
                )
                st.plotly_chart(fig_sw, use_container_width=True)

            st.dataframe(
                df_sweep.style.format({
                    c: "{:.4g}" for c in df_sweep.columns if df_sweep[c].dtype in (float,)
                }),
                use_container_width=True,
                hide_index=True,
            )
        except Exception as exc:
            st.error(f"Sweep failed: {exc}")


# ── Custom flowsheet assembler ────────────────────────────────────────────────

def _render_custom_assembler(st, current_params: dict, chosen_key: str, spec) -> None:
    """Render the unit-picker + port-wiring UI for the custom template."""
    from pse_ecosystem.ui.flowsheet_service import AVAILABLE_UNITS, build_custom_flowsheet

    st.info(
        "Pick up to 8 units, set their parameters, declare connections, "
        "then click **Build & Select**."
    )

    raw_comps = st.text_input(
        "Shared component set (comma-separated)",
        value="H2, CO, CO2",
        help="All port-based units will use this species list. "
             "For VLE (FlashVLHF) use Antoine-supported species e.g. benzene, toluene.",
    )
    shared_components = [c.strip() for c in raw_comps.split(",") if c.strip()]

    n_units = st.number_input("Number of units", min_value=1, max_value=10, value=2, step=1)
    unit_types = list(AVAILABLE_UNITS.keys())

    unit_configs = []
    for i in range(int(n_units)):
        with st.expander(f"Unit {i + 1}", expanded=True):
            utype = st.selectbox(
                "Type", unit_types,
                index=min(i, len(unit_types) - 1),
                key=f"custom_unit_type_{i}",
                help=AVAILABLE_UNITS.get(unit_types[min(i, len(unit_types)-1)], ""),
            )
            uid = st.text_input("Unit ID", value=f"u{i+1}", key=f"custom_unit_id_{i}")
            unit_configs.append({"type": utype, "id": uid, "params": {"components": shared_components}})

    # ── Composite / super-unit option ────────────────────────────────────────
    st.divider()
    use_composite = st.checkbox(
        "Add a built-in template as a super-unit",
        value=False,
        help="Wraps a complete built-in flowsheet as a single CompositeUnit. "
             "Expose its internal variables as inputs/outputs to wire it into your custom chain.",
    )
    composite_unit_obj = None
    comp_uid = "super_1"
    if use_composite:
        from pse_ecosystem.ui.flowsheet_service import list_templates, build_composite_unit
        all_templates = [t for t in list_templates() if t.key != "custom.user_flowsheet"]
        comp_name = st.selectbox(
            "Template to wrap", [t.display_name for t in all_templates],
            key="composite_template_name",
        )
        comp_key = next(t.key for t in all_templates if t.display_name == comp_name)
        comp_uid = st.text_input("Super-unit ID", value="super_1", key="composite_uid")
        comp_in_str  = st.text_input(
            "Exposed inputs (comma-separated variable names)", value="",
            key="composite_exposed_in",
            help="Inner flowsheet variables the parent can drive (e.g. pem.electricity_price_per_kWh)",
        )
        comp_out_str = st.text_input(
            "Exposed outputs (comma-separated variable names)", value="",
            key="composite_exposed_out",
            help="Inner flowsheet variables reported to the parent (e.g. pem.H2_kg_per_h)",
        )
        st.caption(
            "The super-unit will be appended to the flowsheet after the units above. "
            "Add a connection targeting its ID to wire it in."
        )
        if comp_uid:
            comp_in_list  = [x.strip() for x in comp_in_str.split(",")  if x.strip()]
            comp_out_list = [x.strip() for x in comp_out_str.split(",") if x.strip()]
            try:
                composite_unit_obj = build_composite_unit(
                    comp_key, comp_uid, comp_in_list, comp_out_list
                )
                unit_configs.append({"type": "__composite__", "id": comp_uid, "params": {}})
            except Exception as comp_exc:
                st.warning(f"Super-unit preview failed (will retry on Build): {comp_exc}")

    # ── Connections ───────────────────────────────────────────────────────────
    st.subheader("Connections")
    st.caption("Wire outlet → inlet between adjacent units (sequential by default).")
    ids = [u["id"] for u in unit_configs]
    connections = []
    for i in range(len(ids) - 1):
        col_a, col_b = st.columns(2)
        from_u = col_a.selectbox("From", ids, index=i,   key=f"conn_from_{i}")
        to_u   = col_b.selectbox("To",   ids, index=i+1, key=f"conn_to_{i}")
        connections.append({"from_unit": from_u, "to_unit": to_u})

    if st.button("Build & Select", type="primary"):
        try:
            config = {
                "units": unit_configs,
                "connections": connections,
                "__composites__": {comp_uid: composite_unit_obj} if composite_unit_obj else {},
            }
            fs = build_custom_flowsheet(config)
            st.session_state["selected_template"] = chosen_key
            st.session_state["template_params"] = {}
            st.session_state["custom_flowsheet"] = fs
            for w in getattr(fs, "_conn_warnings", []):
                st.warning(f"Connection skipped: {w}")
            n_conn = len(fs.connections)
            st.success(
                f"Custom flowsheet built: {len(fs.units)} units, "
                f"{n_conn} connections. Go to **Solver Monitor** to run."
            )
        except Exception as exc:
            st.error(f"Build failed: {exc}")


# ── Page 3 (removed): Biomass Case Study migrated to Template Library ─────────
# The Biomass → H2 flowsheet is now loaded via the Template Library using key
# "biomass.gasification_to_hydrogen". Use the Flowsheet Builder page instead.


def _page_case_study():
    """Stub retained for import-compatibility; page removed from navigation."""
    st = _require_streamlit()
    st.info(
        "The Biomass → H₂ case study has moved to the **Flowsheet Builder**. "
        "Select the 'Biomass → H₂ (Gasification)' template there."
    )



# ── Page 4: GPS Weather ───────────────────────────────────────────────────────

def _page_gps_weather():
    st = _require_streamlit()
    _init_state(st)

    st.title("GPS Weather")
    st.caption("Fetch site-specific solar & wind profiles via pvlib.")

    col1, col2, col3 = st.columns(3)
    with col1:
        lat = st.number_input("Latitude (°N)", value=51.24, min_value=-90.0, max_value=90.0, format="%.4f")
    with col2:
        lon = st.number_input("Longitude (°E)", value=-0.59, min_value=-180.0, max_value=180.0, format="%.4f")
    with col3:
        alt = st.number_input("Altitude (m)", value=68.0, min_value=0.0, max_value=5000.0, format="%.1f")

    tz   = st.text_input("Timezone (IANA)", value="Europe/London")
    year = st.number_input("Year", value=2023, min_value=2000, max_value=2030, step=1)

    if st.button("Fetch Profiles", type="primary"):
        try:
            from pse_ecosystem.data.weather import SiteData, fetch_solar_profile, fetch_wind_profile
        except ImportError:
            st.error(
                "pvlib not installed. Run: `pip install 'pse_ecosystem[weather]'`"
            )
            return

        with st.spinner("Computing clearsky solar and wind profiles..."):
            site = SiteData(
                latitude=float(lat),
                longitude=float(lon),
                altitude=float(alt),
                timezone=tz,
                name=f"Site ({lat:.2f}°N, {lon:.2f}°E)",
            )
            try:
                ghi  = fetch_solar_profile(site, int(year))
                wind = fetch_wind_profile(site, int(year))
            except Exception as exc:
                st.error(f"Weather fetch failed: {exc}")
                return

        st.session_state["weather_ghi"]  = ghi
        st.session_state["weather_wind"] = wind
        st.session_state["weather_site"] = site
        st.success(f"Profiles fetched for {site.name}, year {year}.")

    ghi  = st.session_state.get("weather_ghi")
    wind = st.session_state.get("weather_wind")

    if ghi is not None and wind is not None:
        import numpy as np
        import plotly.graph_objects as go

        hours = list(range(len(ghi)))

        m1, m2, m3 = st.columns(3)
        m1.metric("Peak GHI (W/m²)", f"{float(ghi.max()):.0f}")
        m2.metric("Mean Wind (m/s)", f"{float(wind.mean()):.2f}")
        cap_factor = float((ghi > 0).sum()) / len(ghi)
        m3.metric("Solar Hours / Year", f"{int((ghi > 0).sum())}")

        tab1, tab2 = st.tabs(["Solar GHI", "Wind Speed"])
        with tab1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hours, y=ghi.tolist(),
                mode="lines", name="GHI [W/m²]",
                line=dict(color="#f39c12", width=1),
            ))
            fig.update_layout(
                title="Annual Solar GHI Profile",
                xaxis_title="Hour of year",
                yaxis_title="GHI [W/m²]",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=hours, y=wind.tolist(),
                mode="lines", name="Wind speed [m/s]",
                line=dict(color="#3498db", width=1),
            ))
            fig2.update_layout(
                title="Annual Wind Speed Profile",
                xaxis_title="Hour of year",
                yaxis_title="Wind speed [m/s]",
                height=350,
            )
            st.plotly_chart(fig2, use_container_width=True)


# ── Page 5: Solver Monitor ────────────────────────────────────────────────────

def _page_solver_monitor():
    st = _require_streamlit()
    _init_state(st)

    st.title("Solver Monitor")

    selected_key = st.session_state.get("selected_template")
    if not selected_key:
        st.info("No template selected. Go to **Flowsheet Builder** first.")
        return

    from pse_ecosystem.ui.flowsheet_service import get_template
    spec = get_template(selected_key)
    st.subheader(f"Template: {spec.display_name}")
    st.caption(f"Key: `{selected_key}` | Category: {spec.category}")

    # ── Solver settings ──────────────────────────────────────────────────────
    with st.expander("Solver Settings", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            max_iter = st.slider("Max iterations", 5, 100, 50)
            eps_x    = st.number_input("Step tolerance (eps_x)", value=1e-4,
                                        format="%.2e", min_value=1e-10, max_value=1.0)
        with col_b:
            _solver_options = ["SLP (fast, LP-based)"]
            if spec.supports_milp:
                _solver_options.append("MILP → SLP (technology selection)")
            _solver_options += [
                "NLP (scipy L-BFGS-B, full residual)",
                "Trust-Region Filter (robust, filter globalization)",
                "Adaptive (SLP → NLP → Trust-Region cascade)",
            ]
            _mode_label = st.radio("Solver Mode", _solver_options)
            verbose = st.checkbox("Verbose solver output", value=False)

        _MODE_MAP = {
            "SLP (fast, LP-based)":                            "FIXED_LP",
            "MILP → SLP (technology selection)":              "FLEXIBLE_MILP",
            "NLP (scipy L-BFGS-B, full residual)":            "NLP_IPOPT",
            "Trust-Region Filter (robust, filter globalization)": "TRUST_REGION",
            "Adaptive (SLP → NLP → Trust-Region cascade)":    "ADAPTIVE",
        }
        _solve_mode_name = _MODE_MAP.get(_mode_label, "FIXED_LP")

    # ── Run button ───────────────────────────────────────────────────────────
    if st.button("Run Solve", type="primary"):
        try:
            from pse_ecosystem.ui.flowsheet_service import load_template, load_template_with_choices
            from pse_ecosystem.solvers.orchestrator import Orchestrator
            from pse_ecosystem.solvers.slp import SLPConfig
            from pse_ecosystem.core.contracts import SolveMode, SolverStatus

            _mode_enum_map = {
                "FIXED_LP":     SolveMode.FIXED_LP,
                "FLEXIBLE_MILP": SolveMode.FLEXIBLE_MILP,
                "NLP_IPOPT":    SolveMode.NLP_IPOPT,
                "TRUST_REGION": SolveMode.TRUST_REGION,
                "ADAPTIVE":     SolveMode.ADAPTIVE,
            }
            mode = _mode_enum_map.get(_solve_mode_name, SolveMode.FIXED_LP)
            params = st.session_state.get("template_params", {})

            # ── Live convergence containers ──────────────────────────────────
            progress_bar = st.progress(0)
            iter_text    = st.empty()
            live_chart   = st.empty()
            _iter_history: list = []

            def _on_iter(k: int, obj: float, resid: float) -> None:
                _iter_history.append({"iteration": k, "objective": obj,
                                      "residual_norm": resid})
                progress_bar.progress(min((k + 1) / max(max_iter, 1), 1.0))
                iter_text.caption(
                    f"Iteration {k + 1} / {max_iter}  |  "
                    f"Obj: {obj:.4g}  |  ‖f‖: {resid:.3g}"
                )
                if len(_iter_history) > 1:
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                    iters_  = [h["iteration"]    for h in _iter_history]
                    objs_   = [h["objective"]    for h in _iter_history]
                    resids_ = [h["residual_norm"] for h in _iter_history]
                    fig_ = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_.add_trace(
                        go.Scatter(x=iters_, y=objs_, mode="lines+markers",
                                   name="Objective"),
                        secondary_y=False,
                    )
                    fig_.add_trace(
                        go.Scatter(x=iters_, y=resids_, mode="lines+markers",
                                   name="‖f‖", line=dict(dash="dash")),
                        secondary_y=True,
                    )
                    fig_.update_layout(
                        title="SLP — Live Convergence",
                        xaxis_title="Iteration",
                        height=300,
                    )
                    fig_.update_yaxes(title_text="Objective",    secondary_y=False)
                    fig_.update_yaxes(title_text="Residual norm", secondary_y=True)
                    live_chart.plotly_chart(fig_, use_container_width=True)

            slp_cfg = SLPConfig(
                max_iter=int(max_iter),
                eps_x=float(eps_x),
                verbose=verbose,
                iteration_callback=_on_iter,
            )

            with st.spinner(f"Solving {spec.display_name}…"):
                # Custom flowsheet: use pre-built flowsheet from session state
                if selected_key == "custom.user_flowsheet":
                    flowsheet = st.session_state.get("custom_flowsheet")
                    if flowsheet is None:
                        st.error("No custom flowsheet built yet. Go to Flowsheet Builder first.")
                        return
                    tech_choices = []
                elif mode == SolveMode.FLEXIBLE_MILP:
                    flowsheet, tech_choices = load_template_with_choices(selected_key, params)
                else:
                    flowsheet = load_template(selected_key, params)
                    tech_choices = []

                orch = Orchestrator(
                    flowsheet=flowsheet,
                    mode=mode,
                    slp_config=slp_cfg,
                    technology_choices=tech_choices,
                )
                result = orch.solve()

            # Collapse the live chart — the final chart below is higher quality.
            live_chart.empty()
            st.session_state["last_result"] = result

        except Exception as exc:
            st.error(f"Solve failed: {exc}")
            import traceback
            with st.expander("Traceback"):
                st.code(traceback.format_exc())
            return

    # ── Results display ──────────────────────────────────────────────────────
    result = st.session_state.get("last_result")
    if result is None:
        st.info("Press **Run Solve** to start.")
        return

    if result.converged:
        st.success(
            f"Converged in **{result.iterations}** iteration(s)  |  "
            f"Objective: **{result.objective:.4g}**"
        )
    else:
        st.error(
            f"Solver status: **{str(result.status).split('.')[-1]}**  |  "
            f"{result.message}"
        )

    # Convergence plot
    if result.history:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        iters = [h.get("iteration", i) for i, h in enumerate(result.history)]
        objs  = [h.get("objective", float("nan")) for h in result.history]
        resids = [h.get("residual_norm", float("nan")) for h in result.history]

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(x=iters, y=objs, mode="lines+markers", name="Objective"),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(x=iters, y=resids, mode="lines+markers",
                       name="Residual norm", line=dict(dash="dash")),
            secondary_y=True,
        )
        fig.update_layout(title="SLP Convergence", xaxis_title="Iteration", height=350)
        fig.update_yaxes(title_text="Objective", secondary_y=False)
        fig.update_yaxes(title_text="Residual norm", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

    # KPI cards + bar chart
    if result.kpis:
        import plotly.graph_objects as go

        st.subheader("KPIs")

        # Carbon Intensity — highlight separately with threshold indicator
        _CI_KEY_SUFFIX = "CI_kg_CO2_per_kg_H2"
        _CI_GREEN_THRESHOLD = 1.0   # kg CO2/kg H2 (below = green hydrogen)
        ci_kpis = {k: v for k, v in result.kpis.items() if k.endswith(_CI_KEY_SUFFIX)}
        if ci_kpis:
            ci_cols = st.columns(len(ci_kpis))
            for col, (k, v) in zip(ci_cols, ci_kpis.items()):
                unit_label = k.split(".")[0]
                delta_str = (
                    f"{v - _CI_GREEN_THRESHOLD:+.3f} vs 1.0 threshold"
                    if not (v != v) else "N/A"
                )
                col.metric(
                    f"CI — {unit_label} (kg CO₂/kg H₂)",
                    f"{v:.3f}" if not (v != v) else "N/A",
                    delta=delta_str,
                    delta_color="inverse",
                )
            st.caption(
                "Carbon Intensity threshold: **1.0 kg CO₂/kg H₂** "
                "(EU green hydrogen definition). Lower is greener."
            )
            st.divider()

        # All other KPIs in rows of 4
        other_kpis = [(k, v) for k, v in result.kpis.items()
                      if not k.endswith(_CI_KEY_SUFFIX)]
        row_size = 4
        for row_start in range(0, len(other_kpis), row_size):
            row_items = other_kpis[row_start:row_start + row_size]
            cols = st.columns(len(row_items))
            for col, (k, v) in zip(cols, row_items):
                label = k.split(".")[-1].replace("_", " ")
                col.metric(label, f"{v:.4g}")

        fig_kpi = go.Figure(go.Bar(
            x=[k.split(".")[-1] for k in result.kpis],
            y=list(result.kpis.values()),
            marker_color="#4a90e2",
        ))
        fig_kpi.update_layout(
            title="KPI Summary", xaxis_title="KPI", yaxis_title="Value", height=300
        )
        st.plotly_chart(fig_kpi, use_container_width=True)

    # Solution variables table
    if result.x:
        import pandas as pd

        st.subheader("Solution Variables")
        df_x = pd.DataFrame(
            {"Variable": list(result.x.keys()), "Value": list(result.x.values())}
        )
        st.dataframe(
            df_x.style.format({"Value": "{:.6g}"}),
            use_container_width=True,
            hide_index=True,
        )

    # Technology selection (MILP only)
    if result.technology_selection:
        st.subheader("Technology Selection")
        selected = [k for k, v in result.technology_selection.items() if v]
        if selected:
            st.success(f"Active technologies: {', '.join(selected)}")
        else:
            st.warning("No technology was selected.")
        st.json(result.technology_selection)


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    st = _require_streamlit()

    st.set_page_config(
        page_title="PSE Ecosystem",
        page_icon="⚗",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    pages = [
        st.Page(_page_dashboard,         title="Dashboard",         icon="🏠"),
        st.Page(_page_flowsheet_builder,  title="Flowsheet Builder", icon="🔧"),
        st.Page(_page_gps_weather,        title="GPS Weather",       icon="🌍"),
        st.Page(_page_solver_monitor,     title="Solver Monitor",    icon="📊"),
    ]
    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
