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
    st.caption("v1.1.0  |  Private — University of Surrey")

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
                        "Go to **Solver Monitor** to run."
                    )


# ── Custom flowsheet assembler ────────────────────────────────────────────────

def _render_custom_assembler(st, current_params: dict, chosen_key: str, spec) -> None:
    """Render the unit-picker + port-wiring UI for the custom template."""
    from pse_ecosystem.ui.flowsheet_service import AVAILABLE_UNITS, build_custom_flowsheet

    st.info(
        "Pick up to 4 units, set their parameters, declare connections, "
        "then click **Build & Select**."
    )

    n_units = st.number_input("Number of units", min_value=1, max_value=4, value=2, step=1)
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
            unit_configs.append({"type": utype, "id": uid, "params": {}})

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
            config = {"units": unit_configs, "connections": connections}
            fs = build_custom_flowsheet(config)
            st.session_state["selected_template"] = chosen_key
            st.session_state["template_params"] = {}
            st.session_state["custom_flowsheet"] = fs
            n_conn = len(fs.connections)
            st.success(
                f"Custom flowsheet built: {len(fs.units)} units, "
                f"{n_conn} connections. Go to **Solver Monitor** to run."
            )
        except Exception as exc:
            st.error(f"Build failed: {exc}")


# ── Page 3: Case Study — Biomass → H2 ───────────────────────────────────────

def _page_case_study():
    st = _require_streamlit()
    _init_state(st)

    st.title("Case Study: Biomass → H₂ (Gasification)")
    st.caption(
        "Full B-HYPSYS flowsheet: drying → thermochemical gasification "
        "→ WGS reactor → PSA separation. "
        "Physics corrected from B-HYPSYS audit (16 defects fixed)."
    )

    # ── Inputs ───────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Process Inputs")
        from pse_ecosystem.models.biomass.biomass_database import BIOMASS_DB
        biomass_type = st.selectbox("Biomass Type", list(BIOMASS_DB.keys()))
        agent = st.radio("Gasifying Agent", ["Steam", "Air"])
        feed_kg_s = st.number_input(
            "Biomass Feed Rate (kg/s wet)", min_value=0.1, max_value=20.0,
            value=1.0, step=0.1, format="%.2f",
        )
        sb_ratio = st.number_input(
            "Steam-to-Biomass Ratio (kg/kg dry)", min_value=0.1, max_value=3.0,
            value=1.0, step=0.1, format="%.2f",
        )
        T_gas = st.slider("Gasifier Temperature (°C)", 600, 900, 800, step=10)
        T_wgs = st.slider("WGS Temperature (°C)", 250, 500, 400, step=10)
        H2_rec = st.slider("H2 PSA Recovery (%)", 60, 97, 85) / 100.0

    with col2:
        st.subheader("Economic Parameters")
        plant_life = st.number_input(
            "Plant Life (years)", min_value=5, max_value=40, value=20, step=1,
        )
        interest = st.slider("Interest Rate (%)", 2, 20, 8) / 100.0

        from pse_ecosystem.models.costing.economic_engine import CEPCI
        cepci_years = sorted(CEPCI.keys())
        target_year = st.selectbox(
            "Cost Year (CEPCI)", cepci_years, index=cepci_years.index(2024),
        )

        st.subheader("Biomass Properties")
        b = BIOMASS_DB[biomass_type]
        props_col1, props_col2 = st.columns(2)
        props_col1.metric("Moisture Content", f"{b['MC']*100:.0f}%")
        props_col1.metric("LHV (dry)", f"{b['LHV_MJ_kg']:.1f} MJ/kg")
        props_col2.metric("C content (dry)", f"{b['C']*100:.1f}%")
        props_col2.metric("H content (dry)", f"{b['H']*100:.1f}%")

    st.divider()

    # ── Run button ────────────────────────────────────────────────────────────
    if st.button("Run Case Study", type="primary"):
        try:
            from pse_ecosystem.ui.flowsheet_service import load_template
            from pse_ecosystem.solvers.orchestrator import Orchestrator
            from pse_ecosystem.solvers.slp import SLPConfig
            from pse_ecosystem.core.contracts import SolveMode
            from pse_ecosystem.models.costing.economic_engine import EconomicEngine

            params = {
                "biomass_type": biomass_type,
                "gasifying_agent": agent,
                "biomass_feed_kg_s": feed_kg_s,
                "steam_to_biomass_ratio": sb_ratio,
                "T_gasifier_C": float(T_gas),
                "T_wgs_C": float(T_wgs),
                "H2_recovery": H2_rec,
                "plant_life_yr": plant_life,
                "interest_rate": interest,
                "target_year": target_year,
            }

            progress = st.progress(0, text="Building flowsheet…")

            with st.spinner("Solving Biomass → H₂ flowsheet…"):
                fs = load_template("biomass.gasification_to_hydrogen", params)

                _cs_history: list = []

                def _on_iter(k: int, obj: float, resid: float) -> None:
                    _cs_history.append(k)
                    progress.progress(
                        min((k + 1) / 50, 1.0),
                        text=f"SLP iteration {k+1}  |  ‖f‖ = {resid:.3g}",
                    )

                cfg = SLPConfig(
                    max_iter=60,
                    eps_x=1e-4,
                    eps_f=1e-4,
                    use_trust_region=True,
                    trust_region_init=0.5,
                    verbose=False,
                    iteration_callback=_on_iter,
                )
                orch = Orchestrator(flowsheet=fs, mode=SolveMode.FIXED_LP, slp_config=cfg)
                result = orch.solve()

            progress.empty()

        except Exception as exc:
            st.error(f"Solve failed: {exc}")
            import traceback
            with st.expander("Traceback"):
                st.code(traceback.format_exc())
            return

        # ── Results ───────────────────────────────────────────────────────────
        if result.converged:
            st.success(f"Converged in {result.iterations} iteration(s).")
        else:
            st.warning(
                f"Solver status: {str(result.status).split('.')[-1]}  |  "
                f"{result.message}"
            )

        kpis = result.kpis

        # Compute economics
        eco = EconomicEngine(
            target_year=int(target_year),
            plant_life_yr=int(plant_life),
            interest_rate=float(interest),
        )

        h2_kg_s = kpis.get("psa.H2_production_kg_s", 0.0)
        capex_est_USD = sum(
            u.capex(result.x) for u in fs.units
            if hasattr(u, "capex")
        )
        capex_annual = eco.annualized_capex(capex_est_USD)
        biomass_cost_per_year = (
            feed_kg_s * 3600 * eco.operating_hours_per_year *
            float(params.get("biomass_cost_USD_per_kg", 0.05))
        )
        opex_annual = biomass_cost_per_year + kpis.get("storage.Q_drying_kW", 0.0) * 0.05 * 8000 * 3600
        lcoh = eco.lcoh(capex_annual, opex_annual, h2_kg_s)

        # Key metric cards
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("LCOH", f"${lcoh:.2f} / kg H₂" if lcoh < 1e6 else "N/A")
        m2.metric(
            "Cold Gas Efficiency",
            f"{kpis.get('gasifier.CGE_percent', 0.0):.1f}%",
        )
        m3.metric(
            "H₂ Production",
            f"{kpis.get('psa.H2_production_kg_h', 0.0):.1f} kg/h",
        )
        m4.metric(
            "H₂ in Syngas (gasifier)",
            f"{kpis.get('gasifier.H2_pct_vol', 0.0):.1f} vol%",
        )

        # Additional KPIs
        st.subheader("Unit KPIs")
        import pandas as pd
        kpi_rows = [
            {"Unit": k.split(".")[0], "KPI": k.split(".", 1)[1], "Value": f"{v:.4g}"}
            for k, v in kpis.items()
        ]
        if kpi_rows:
            st.dataframe(
                pd.DataFrame(kpi_rows),
                use_container_width=True,
                hide_index=True,
            )

        # LCOH breakdown
        if lcoh < 1e6:
            st.subheader("LCOH Breakdown")
            import plotly.graph_objects as go
            fig = go.Figure(go.Bar(
                x=["CAPEX (annualised)", "OPEX (annual)", "Total LCOH × 100 kg/yr"],
                y=[capex_annual / max(h2_kg_s * 8000 * 3600, 1),
                   opex_annual / max(h2_kg_s * 8000 * 3600, 1),
                   lcoh],
                marker_color=["#3498db", "#e67e22", "#2ecc71"],
                text=[f"${capex_annual/max(h2_kg_s*8000*3600,1):.2f}/kg",
                      f"${opex_annual/max(h2_kg_s*8000*3600,1):.2f}/kg",
                      f"${lcoh:.2f}/kg"],
                textposition="auto",
            ))
            fig.update_layout(
                title="LCOH Cost Breakdown [$/kg H₂]",
                yaxis_title="$/kg H₂",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

        # Syngas composition at gasifier outlet
        st.subheader("Syngas Composition (Gasifier Outlet)")
        syngas_vars = {
            "H2": result.x.get("gasifier.syngas_out.F_H2", 0),
            "CO": result.x.get("gasifier.syngas_out.F_CO", 0),
            "CO2": result.x.get("gasifier.syngas_out.F_CO2", 0),
            "H2O": result.x.get("gasifier.syngas_out.F_H2O", 0),
            "CH4": result.x.get("gasifier.syngas_out.F_CH4", 0),
            "N2": result.x.get("gasifier.syngas_out.F_N2", 0),
        }
        n_total = sum(syngas_vars.values())
        if n_total > 1e-9:
            import plotly.graph_objects as go
            fig2 = go.Figure(go.Pie(
                labels=list(syngas_vars.keys()),
                values=[v / n_total * 100 for v in syngas_vars.values()],
                hole=0.35,
            ))
            fig2.update_layout(title="Syngas Mole % (dry + wet)", height=320)
            st.plotly_chart(fig2, use_container_width=True)

        # Full solution table
        with st.expander("Full Solution Variables"):
            df_x = pd.DataFrame(
                {"Variable": list(result.x.keys()), "Value": list(result.x.values())}
            )
            st.dataframe(
                df_x.style.format({"Value": "{:.6g}"}),
                use_container_width=True,
                hide_index=True,
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
            if spec.supports_milp:
                mode_choice = st.radio(
                    "Solve Mode",
                    ["Mode 1 — Fixed LP", "Mode 2 — Flexible MILP"],
                )
            else:
                mode_choice = "Mode 1 — Fixed LP"
                st.info("Mode 1 (Fixed LP) — this template does not support MILP.")
            verbose = st.checkbox("Verbose solver output", value=False)

    # ── Run button ───────────────────────────────────────────────────────────
    if st.button("Run Solve", type="primary"):
        try:
            from pse_ecosystem.ui.flowsheet_service import load_template, load_template_with_choices
            from pse_ecosystem.solvers.orchestrator import Orchestrator
            from pse_ecosystem.solvers.slp import SLPConfig
            from pse_ecosystem.core.contracts import SolveMode, SolverStatus

            mode = SolveMode.FIXED_LP if "1" in mode_choice else SolveMode.FLEXIBLE_MILP
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
        st.Page(_page_dashboard,         title="Dashboard",              icon="🏠"),
        st.Page(_page_flowsheet_builder,  title="Flowsheet Builder",      icon="🔧"),
        st.Page(_page_case_study,         title="Case Study: Biomass→H2", icon="🌿"),
        st.Page(_page_gps_weather,        title="GPS Weather",            icon="🌍"),
        st.Page(_page_solver_monitor,     title="Solver Monitor",         icon="📊"),
    ]
    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
