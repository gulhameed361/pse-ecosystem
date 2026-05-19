"""PSE Ecosystem — multi-page Streamlit front-end (v1.5.0.dev).

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
    st.session_state.setdefault("last_flowsheet", None)        # v1.4.0 audit M10
    st.session_state.setdefault("custom_flowsheet", None)      # v1.4.0 audit M10
    st.session_state.setdefault("objective_config", None)      # v1.4.0 audit M10
    st.session_state.setdefault("weather_ghi", None)
    st.session_state.setdefault("weather_wind", None)
    st.session_state.setdefault("weather_site", None)


# ── SI-unit inference for Excel export ────────────────────────────────────────

_SI_UNIT_SUFFIX_RULES = [
    # Order matters: longest / most specific suffix first to avoid being
    # short-circuited by a shorter match (e.g. `Y_H2_kg_per_h` must hit
    # `_kg_per_h` before any single-token suffix). v1.4.0 audit M11.
    ("_kg_per_h", "kg/h"),
    ("_mol_per_s", "mol/s"),
    ("_per_kWh",   "USD/kWh"),
    ("_per_kg",    "USD/kg"),
    ("_USD",       "USD"),
    ("_Pa",        "Pa"),
    ("_kPa",       "kPa"),
    ("_bar",       "bar"),
    ("_MW",        "MW"),
    ("_kW",        "kW"),
    ("_MJ",        "MJ"),
    ("_kJ",        "kJ"),
    ("_K",         "K"),
    ("_C",         "°C"),
]

_SI_UNIT_PREFIX_RULES = [
    ("F_", "kg/s"),
    ("n_", "mol/s"),
    ("X_", "—"),
    ("Y_", "—"),
]

_SI_UNIT_EXACT = {
    "T":         "K",
    "T_in":      "K",
    "T_out":     "K",
    "T_avg":     "K",
    "P":         "Pa",
    "P_in":      "Pa",
    "P_out":     "Pa",
    "W":         "W",
    "W_shaft":   "W",
    "W_elec":    "W",
    "Q":         "W",
    "duty":      "W",
    "duty_W":    "W",
    "H":         "J/s",
    "enthalpy":  "J/s",
}


def _infer_si_unit(var_name: str) -> str:
    """Best-effort guess at the SI unit of a solver variable from its name.

    Used to annotate the Stream Table sheet so every numeric value carries an
    explicit unit. Variable names follow the project's port convention:
    ``F_<species>`` for kg/s mass flow, ``T`` / ``T_in`` / ``T_out`` for K,
    ``P`` / ``P_in`` / ``P_out`` / ``P_out_Pa`` for Pa, ``X_<reaction>`` for
    dimensionless conversion, ``W_shaft`` / ``W_elec`` for W shaft work, etc.

    Returns an empty string when no inference is possible — never raises.

    Implementation: a longest-suffix-wins dispatch over `_SI_UNIT_SUFFIX_RULES`
    eliminates the v1.3.x order-dependent bug where short suffixes shadowed
    longer ones in compound variable names (audit M11).
    """
    if not var_name:
        return ""
    n = var_name.strip()

    # Exact bare names first.
    if n in _SI_UNIT_EXACT:
        return _SI_UNIT_EXACT[n]

    # Longest matching suffix wins (rules are pre-sorted longest-first).
    for suffix, unit in _SI_UNIT_SUFFIX_RULES:
        if n.endswith(suffix):
            return unit

    # Prefix conventions.
    for prefix, unit in _SI_UNIT_PREFIX_RULES:
        if n.startswith(prefix):
            return unit

    return ""


# ── Page 1: Dashboard ─────────────────────────────────────────────────────────

def _page_dashboard():
    st = _require_streamlit()
    _init_state(st)

    from pse_ecosystem.ui.flowsheet_service import list_templates

    from pse_ecosystem import __version__ as _pse_version

    st.title("PSE Ecosystem")
    st.caption(f"v{_pse_version}  |  Private — University of Surrey")

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

        # Physics safety net: warn when the converged solution sits at a
        # default unit bound (e.g. CoolerHFParams.feed_max=1000). v1.4.1.
        _bound_active = getattr(last_result, "bound_active", []) or []
        if _bound_active:
            st.warning(
                f"⚠ {len(_bound_active)} variable(s) saturated a non-fixed bound — "
                "inspect before trusting the KPIs. A default unit bound may be "
                "overriding the physics."
            )
            with st.expander("Show bound-saturated variables"):
                st.write(_bound_active)


# ── Page 2: Flowsheet Builder ─────────────────────────────────────────────────

def _page_flowsheet_builder():
    st = _require_streamlit()
    _init_state(st)

    from pse_ecosystem.ui.flowsheet_service import list_templates, get_template

    st.title("Flowsheet Builder")

    templates = list_templates()
    _CAT_ORDER = [
        "Hydrogen Production", "Biomass Processing", "Power Generation",
        "Petrochemicals", "Carbon Capture & Utilization",
        "Other Industrial Processes", "Custom",
    ]
    categories = ["All"] + sorted(
        {t.category for t in templates},
        key=lambda c: _CAT_ORDER.index(c) if c in _CAT_ORDER else 99,
    )

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
        _fb_tabs = st.tabs(["1D Sensitivity Sweep", "Objective Function"])

        with _fb_tabs[0]:
            _section_sensitivity_sweep(st, chosen_key, spec)

        with _fb_tabs[1]:
            from pse_ecosystem.ui.flowsheet_service import OBJECTIVE_TIERS
            st.subheader("Optimization & Project Economics")
            st.caption(
                "Sets the LP objective and financial parameters for your solve run. "
                "Applies when you click **Run Solve** on the Solver Monitor page."
            )

            # ── Tier selector ────────────────────────────────────────────────
            _tier = st.radio(
                "Optimization Category",
                list(OBJECTIVE_TIERS.keys()),
                horizontal=True,
                key="obj_tier",
            )
            _obj_mode = st.selectbox(
                "Objective",
                OBJECTIVE_TIERS[_tier],
                key="objective_mode",
            )

            _OBJ_HELP = {
                "Feasibility Only":
                    "objective = 0. Solver finds any feasible point satisfying all "
                    "mass/energy balances — no cost pressure. Best for debugging.",
                "Minimize Energy":
                    "Adds electricity price × annual hours as a coefficient on shaft-work "
                    "and electrical power decision variables (e.g. Compressor W_shaft).",
                "Maximize H₂ Yield":
                    "Coefficient −1 on the most-downstream H₂ outlet variable. "
                    "LP maximises H₂ production regardless of cost.",
                "Minimize Specific Energy Consumption":
                    "Minimises energy input per unit H₂ produced: energy penalty on power "
                    "variables, reward coefficient on H₂ outlet (LP proxy).",
                "Minimize Carbon Intensity":
                    "Penalises CO₂ outlet flows by the carbon tax rate × annual hours. "
                    "Configure carbon tax in the Financial Parameters expander.",
                "Minimize OPEX":
                    "Minimises the sum of unit operating costs already embedded in each "
                    "unit model (feedstock, electricity). No extra objective terms.",
                "Minimize TAC":
                    "Total Annualised Cost = OPEX + annualised CAPEX. Adds energy cost "
                    "+ 700 USD/kW × CRF for ElectrolyserHF. SSLW capex reported as KPIs.",
                "Maximize NPV (Net Present Value)":
                    "LP proxy = minimize TAC (equivalent under fixed production at steady state). "
                    "Exact NPV computed post-solve from KPIs using the financial parameters below.",
                "Maximize IRR (Internal Rate of Return)":
                    "Same LP proxy as NPV maximisation. Exact IRR computed post-solve via "
                    "bisection and displayed in the Project Economics Excel sheet.",
                "Minimize LCOH (Levelized Cost of H₂)":
                    "Proxy: minimise TAC while maximising H₂ outlet flow. "
                    "Exact LCOH [USD/kg H₂] displayed in the Project Economics Excel sheet.",
                "Minimize LCOE (Levelized Cost of Energy)":
                    "Minimises cost per kWh of electrical output. Energy penalty on power-draw "
                    "variables; reward coefficient on net-power output variables.",
            }
            st.info(_OBJ_HELP.get(_obj_mode, ""))

            # ── Context-dependent parameter expanders ────────────────────────
            _elec_price = 0.05
            _op_hours   = 8000.0
            _plant_life = 20
            _int_rate   = 0.08
            _tax_rate   = 0.20
            _infl_rate  = 0.025
            _biomass_p  = 60.0
            _water_p    = 0.5
            _cw_p       = 0.35
            _carbon_tax = 50.0

            if _tier == "Technical":
                with st.expander("Technical Parameters", expanded=True):
                    _elec_price = st.number_input(
                        "Electricity price (USD/kWh)", value=0.05, format="%.3f",
                        key="obj_elec_price",
                        help="Used for energy cost coefficients.",
                    )
                    _op_hours = float(st.number_input(
                        "Annual operating hours (h/yr)", value=8000, step=100,
                        key="obj_op_hours",
                    ))
                    if _obj_mode == "Minimize Carbon Intensity":
                        _carbon_tax = st.number_input(
                            "Carbon tax (USD/tonne CO₂)", value=50.0, format="%.1f",
                            key="obj_carbon_tax",
                        )

            elif _tier == "Economic":
                with st.expander("Financial Parameters", expanded=True):
                    _col1, _col2 = st.columns(2)
                    with _col1:
                        _plant_life = int(st.number_input(
                            "Plant economic life (years)", value=20, min_value=1, max_value=50,
                            key="obj_plant_life",
                        ))
                        _int_rate = st.number_input(
                            "Discount / interest rate (WACC)", value=0.08, format="%.3f",
                            key="obj_int_rate",
                            help="Fraction, e.g. 0.08 for 8%.",
                        )
                        _tax_rate = st.number_input(
                            "Corporate tax rate", value=0.20, format="%.2f",
                            key="obj_tax_rate",
                        )
                    with _col2:
                        _infl_rate = st.number_input(
                            "Inflation rate", value=0.025, format="%.3f",
                            key="obj_infl_rate",
                        )
                        _elec_price = st.number_input(
                            "Electricity price (USD/kWh)", value=0.05, format="%.3f",
                            key="obj_elec_price",
                        )
                        _op_hours = float(st.number_input(
                            "Annual operating hours (h/yr)", value=8000, step=100,
                            key="obj_op_hours",
                        ))
                    if _obj_mode in ("Maximize NPV (Net Present Value)",
                                     "Maximize IRR (Internal Rate of Return)"):
                        _carbon_tax = st.number_input(
                            "Carbon tax (USD/tonne CO₂)", value=50.0, format="%.1f",
                            key="obj_carbon_tax",
                        )

            else:  # Technoeconomic
                with st.expander("Project Economics", expanded=True):
                    _col1, _col2 = st.columns(2)
                    with _col1:
                        _plant_life = int(st.number_input(
                            "Plant economic life (years)", value=20, min_value=1, max_value=50,
                            key="obj_plant_life",
                        ))
                        _int_rate = st.number_input(
                            "Discount / interest rate (WACC)", value=0.08, format="%.3f",
                            key="obj_int_rate",
                        )
                        _tax_rate = st.number_input(
                            "Corporate tax rate", value=0.20, format="%.2f",
                            key="obj_tax_rate",
                        )
                        _infl_rate = st.number_input(
                            "Inflation rate", value=0.025, format="%.3f",
                            key="obj_infl_rate",
                        )
                    with _col2:
                        _elec_price = st.number_input(
                            "Electricity price (USD/kWh)", value=0.05, format="%.3f",
                            key="obj_elec_price",
                        )
                        _op_hours = float(st.number_input(
                            "Annual operating hours (h/yr)", value=8000, step=100,
                            key="obj_op_hours",
                        ))
                        _biomass_p = st.number_input(
                            "Biomass feedstock (USD/tonne)", value=60.0, format="%.1f",
                            key="obj_biomass_price",
                        )
                        _water_p = st.number_input(
                            "Water price (USD/tonne)", value=0.5, format="%.2f",
                            key="obj_water_price",
                        )
                        _cw_p = st.number_input(
                            "Cooling water (USD/GJ)", value=0.35, format="%.2f",
                            key="obj_cw_price",
                        )
                        _carbon_tax = st.number_input(
                            "Carbon tax (USD/tonne CO₂)", value=50.0, format="%.1f",
                            key="obj_carbon_tax",
                        )

            if st.button("Apply Objective", key="apply_objective_btn"):
                st.session_state["objective_config"] = {
                    "mode":          _obj_mode,
                    "tier":          _tier,
                    "elec_price":    float(_elec_price),
                    "op_hours":      float(_op_hours),
                    "plant_life_yr": int(_plant_life),
                    "interest_rate": float(_int_rate),
                    "tax_rate":      float(_tax_rate),
                    "inflation_rate": float(_infl_rate),
                    "biomass_price": float(_biomass_p),
                    "water_price":   float(_water_p),
                    "cw_price":      float(_cw_p),
                    "carbon_tax":    float(_carbon_tax),
                }
                st.success(f"Objective set to: **{_obj_mode}**. Run from Solver Monitor.")

            _oc = st.session_state.get("objective_config")
            if _oc:
                st.caption(
                    f"Active: **{_oc['mode']}** | {_oc.get('tier','—')} tier | "
                    f"elec {_oc.get('elec_price', 0.05):.3f} USD/kWh | "
                    f"{int(_oc.get('op_hours', 8000))} h/yr | "
                    f"plant life {_oc.get('plant_life_yr', 20)} yr | "
                    f"WACC {_oc.get('interest_rate', 0.08)*100:.1f}%"
                )


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
                except Exception as _sweep_exc:  # noqa: BLE001 — surface to UI
                    # v1.4.0 audit N12 — was a bare `except Exception: pass`
                    # that hid every solve failure inside the sweep loop.
                    st.warning(
                        f"Sweep point {sweep_param}={val} failed: "
                        f"{type(_sweep_exc).__name__}: {_sweep_exc}"
                    )
                    row = {
                        sweep_param: val,
                        "converged": False,
                        "_error": f"{type(_sweep_exc).__name__}: {_sweep_exc}",
                    }
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
        "Pick any number of units, set their parameters, declare connections, "
        "then click **Build & Select**. The builder scales to whatever your "
        "hardware can carry — past ~20 units expect noticeably slower reruns."
    )

    raw_comps = st.text_input(
        "Shared component set (comma-separated)",
        value="H2, CO, CO2",
        help="All port-based units will use this species list. "
             "For VLE (FlashVLHF) use Antoine-supported species e.g. benzene, toluene.",
    )
    shared_components = [c.strip() for c in raw_comps.split(",") if c.strip()]

    n_units = st.number_input("Number of units", min_value=1, value=2, step=1)
    if int(n_units) > 7:
        st.caption(
            "ℹ Past unit 7 the Type dropdown defaults to the last category entry — "
            "set each unit's Type explicitly to avoid duplicate-type chains."
        )

    from pse_ecosystem.ui.flowsheet_service import (
        get_unit_param_specs, UNIT_CATEGORIES, TYPE_ID_SUGGESTIONS,
        supported_display_units, to_native, from_native,
    )

    # Dynamic category filter — narrows the unit type dropdown
    _all_cats = ["All"] + list(UNIT_CATEGORIES.keys())
    _cat_sel = st.selectbox(
        "Filter unit types by category", _all_cats,
        index=0, key="custom_cat_filter",
        help="Narrows the Type dropdown in each unit expander.",
    )
    if _cat_sel == "All":
        unit_types = list(AVAILABLE_UNITS.keys())
    else:
        unit_types = UNIT_CATEGORIES.get(_cat_sel, list(AVAILABLE_UNITS.keys()))

    unit_configs = []
    for i in range(int(n_units)):
        with st.expander(f"Unit {i + 1}", expanded=True):
            utype = st.selectbox(
                "Type", unit_types,
                index=min(i, len(unit_types) - 1),
                key=f"custom_unit_type_{i}",
                help=AVAILABLE_UNITS.get(unit_types[min(i, len(unit_types)-1)], ""),
            )

            # Smart-select: type-specific ID suggestions + free-form fallback
            _base_id = TYPE_ID_SUGGESTIONS.get(utype, f"u{i+1}")
            _id_options = [f"{_base_id}_{j}" for j in range(1, 4)] + ["custom..."]
            _id_sel = st.selectbox(
                "Unit ID", _id_options,
                index=0,
                key=f"custom_unit_id_sel_{i}_{utype}",
                help=f"Suggested IDs for '{utype}'. Choose 'custom...' to type your own.",
            )
            if _id_sel == "custom...":
                uid = st.text_input(
                    "Custom ID", value=_base_id,
                    key=f"custom_unit_id_txt_{i}_{utype}",
                )
            else:
                uid = _id_sel

            # Dynamic parameter form — renders pre-filled inputs per unit type
            # in a 3-column Aspen-style specification grid. Float params whose
            # native unit belongs to a recognised conversion family (T, P, mass
            # flow, mass, power, energy) get an inline display-unit dropdown
            # — see the Unit Management System in flowsheet_service.py.
            unit_params: dict = {}
            _specs = get_unit_param_specs(utype)
            if _specs:
                st.caption(
                    "Specification Sheet (pre-filled with engineering defaults). "
                    "Float parameters with a convertible unit show a dropdown so you can "
                    "enter values in your preferred unit — the backend stores SI internally."
                )
                def _make_unit_callback(
                    value_key: str, prev_key: str, disp_key: str, native_unit: str
                ):
                    """Return a Streamlit on_change closure for a unit dropdown.

                    When the user switches display units (e.g. °C → K) the
                    closure converts the paired numeric value in session_state
                    so the displayed number stays physically correct.
                    """
                    def _cb() -> None:
                        new_u = st.session_state.get(disp_key, native_unit)
                        old_u = st.session_state.get(prev_key, native_unit)
                        if old_u != new_u and value_key in st.session_state:
                            old_v = float(st.session_state[value_key])
                            nat_v = to_native(old_v, old_u, native_unit)
                            st.session_state[value_key] = from_native(
                                nat_v, native_unit, new_u
                            )
                        st.session_state[prev_key] = new_u
                    return _cb

                _NCOL = 3
                for _row_start in range(0, len(_specs), _NCOL):
                    _row_specs = _specs[_row_start:_row_start + _NCOL]
                    _cols = st.columns(_NCOL)
                    for _col, _ps in zip(_cols, _row_specs):
                        _key = f"param_{i}_{_ps.name}"
                        _alt_units = (
                            supported_display_units(_ps.unit)
                            if _ps.dtype == "float" else []
                        )

                        if _ps.dtype == "float" and _alt_units:
                            # Two-column cell: value input (wider) + unit picker (narrower).
                            _vc, _uc = _col.columns([2, 1])
                            _disp_key = f"unit_{i}_{_ps.name}_{utype}"
                            _prev_unit_key = f"prev_unit_{i}_{_ps.name}_{utype}"
                            if _prev_unit_key not in st.session_state:
                                st.session_state[_prev_unit_key] = _ps.unit
                            _disp_unit = _uc.selectbox(
                                "Unit", _alt_units,
                                index=_alt_units.index(_ps.unit) if _ps.unit in _alt_units else 0,
                                key=_disp_key,
                                label_visibility="visible",
                                on_change=_make_unit_callback(
                                    _key, _prev_unit_key, _disp_key, _ps.unit
                                ),
                            )
                            _disp_default = from_native(float(_ps.default), _ps.unit, _disp_unit)
                            # Physical lower bound for temperature inputs:
                            # 0 K, -273.15 °C, -459.67 °F. v1.4.0 audit H10.
                            _TEMP_FLOOR = {"K": 0.0, "°C": -273.15, "°F": -459.67}
                            _min_val = _TEMP_FLOOR.get(_disp_unit)
                            _kw = {"help": _ps.help, "key": _key}
                            if _min_val is not None:
                                _kw["min_value"] = float(_min_val)
                            _ui_value = _vc.number_input(
                                f"{_ps.label}", value=float(_disp_default), **_kw,
                            )
                            # Convert back to native ParamSpec unit before storing.
                            unit_params[_ps.name] = to_native(
                                float(_ui_value), _disp_unit, _ps.unit,
                            )
                        else:
                            _label = f"{_ps.label} [{_ps.unit}]" if _ps.unit else _ps.label
                            if _ps.dtype == "float":
                                unit_params[_ps.name] = _col.number_input(
                                    _label, value=float(_ps.default),
                                    help=_ps.help, key=_key,
                                )
                            elif _ps.dtype == "int":
                                unit_params[_ps.name] = int(_col.number_input(
                                    _label, value=int(_ps.default),
                                    step=1, help=_ps.help, key=_key,
                                ))
                            elif _ps.dtype == "select":
                                unit_params[_ps.name] = _col.selectbox(
                                    _label, _ps.options,
                                    index=_ps.options.index(_ps.default) if _ps.default in _ps.options else 0,
                                    help=_ps.help, key=_key,
                                )

            unit_configs.append({
                "type": utype,
                "id": uid,
                "params": {**unit_params, "components": shared_components},
            })

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

    # v1.4.0 audit N36 — surface a soft warning when the user has picked
    # several units of the same Type. This is usually a typo (the caption
    # past unit 7 nudges users to set Types explicitly because the default
    # index saturates); a 5-unit chain of all "MixerHF" would silently
    # build but is rarely what the user intended.
    from collections import Counter
    _type_counts = Counter(u["type"] for u in unit_configs)
    _duplicated = [t for t, c in _type_counts.items() if c >= 3]
    if _duplicated:
        st.warning(
            f"Heads-up: you picked the same Type for ≥3 units: "
            f"{', '.join(_duplicated)}. If this is intentional, ignore. "
            f"Otherwise re-check the Type dropdowns above."
        )

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
            n_streams   = len(connections)        # logical stream pairs drawn in UI
            n_equalities = len(fs.connections)   # variable equality constraints (internal)
            st.success(
                f"Custom flowsheet built: {len(fs.units)} units, "
                f"{n_streams} connection(s). Go to **Solver Monitor** to run."
            )
            st.caption(
                f"Internal port-variable equalities: {n_equalities} "
                f"(one per shared species + T + P per connection — used by the LP solver)."
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

    st.title("Site Weather")
    st.caption("Fetch site-specific solar & wind profiles via pvlib.")

    col1, col2, col3 = st.columns(3)
    with col1:
        lat = st.number_input("Latitude (°N)", value=51.24, min_value=-90.0, max_value=90.0, format="%.4f")
    with col2:
        lon = st.number_input("Longitude (°E)", value=-0.59, min_value=-180.0, max_value=180.0, format="%.4f")
    with col3:
        alt = st.number_input("Altitude (m)", value=68.0, min_value=0.0, max_value=5000.0, format="%.1f")

    # v1.4.0 audit N37 — replace free-text tz with a curated IANA list to
    # avoid pvlib raising on typos like "Europe/Lonon". The selectbox is
    # populated from `zoneinfo.available_timezones()` so any zone the
    # standard library knows about is selectable.
    try:
        from zoneinfo import available_timezones
        _TZ_OPTIONS = sorted(available_timezones())
        _default_tz = "Europe/London"
        _default_idx = _TZ_OPTIONS.index(_default_tz) if _default_tz in _TZ_OPTIONS else 0
        tz = st.selectbox("Timezone (IANA)", _TZ_OPTIONS, index=_default_idx)
    except ImportError:
        # Python < 3.9 fallback — keep the text input but validate.
        tz = st.text_input("Timezone (IANA)", value="Europe/London")
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

    # ── Active objective mirror (read-only) ──────────────────────────────────
    _active_obj = st.session_state.get("objective_config")
    if _active_obj:
        st.info(
            f"**Active objective:** {_active_obj.get('mode', 'Feasibility Only')}  |  "
            f"elec {_active_obj.get('elec_price', 0.05):.3f} USD/kWh  |  "
            f"{int(_active_obj.get('op_hours', 8000))} h/yr  |  "
            f"CRF {_active_obj.get('crf', 0.10):.2f}  "
            f"_(set on the Flowsheet Builder → Objective Function tab)_"
        )
    else:
        st.info(
            "**Active objective:** Feasibility Only (default). "
            "Set a different objective on the Flowsheet Builder → Objective Function tab."
        )

    # ── Solver settings ──────────────────────────────────────────────────────
    with st.expander("Solver Settings", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            max_iter = st.slider("Max iterations", 1, 1500, 200)
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
            prog_tighten = st.checkbox(
                "Progressive tightening",
                value=True,
                help="Recommended. Starts with loose convergence tolerances (≈1e-3) and "
                     "tightens to precision (≈1e-7) as iterations progress. Uncheck to "
                     "enforce strict tolerance from iteration 0.",
            )

        with st.expander("Advanced solver settings", expanded=False):
            tr_min_radius = st.number_input(
                "Trust-Region minimum radius",
                value=1e-2,
                format="%.2e",
                min_value=1e-8,
                max_value=1.0,
                help="Reduce for complex chains where the default 1e-2 causes early exit. "
                     "Only active when Trust-Region or Adaptive solver is selected.",
            )

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
                progressive_tightening=bool(prog_tighten),
                trust_region_min=float(tr_min_radius),
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

                # Apply objective config from Objective Function tab
                from pse_ecosystem.ui.flowsheet_service import (
                    build_objective_extra, ProjectEconomicsConfig,
                )
                _oc = st.session_state.get("objective_config", {}) or {}
                _obj_mode_val = _oc.get("mode", "Feasibility Only")
                _econ_cfg = ProjectEconomicsConfig(
                    plant_life_yr=int(_oc.get("plant_life_yr", 20)),
                    interest_rate=float(_oc.get("interest_rate", 0.08)),
                    tax_rate=float(_oc.get("tax_rate", 0.20)),
                    inflation_rate=float(_oc.get("inflation_rate", 0.025)),
                    operating_hours_per_year=float(_oc.get("op_hours", 8000.0)),
                    electricity_price_USD_per_kWh=float(_oc.get("elec_price", 0.05)),
                    biomass_price_USD_per_tonne=float(_oc.get("biomass_price", 60.0)),
                    water_price_USD_per_tonne=float(_oc.get("water_price", 0.5)),
                    cooling_water_price_USD_per_GJ=float(_oc.get("cw_price", 0.35)),
                    carbon_tax_USD_per_tonne=float(_oc.get("carbon_tax", 50.0)),
                )
                flowsheet.objective_extra, flowsheet.force_feasibility = build_objective_extra(
                    flowsheet,
                    _obj_mode_val,
                    econ_config=_econ_cfg,
                )

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
            st.session_state["last_flowsheet"] = flowsheet   # for per-unit Excel export

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
        _status_name = str(result.status).split(".")[-1]
        _tips = {
            "MAX_ITER": (
                "**Potential fixes:**\n"
                "1. Increase the **Max Iterations** slider (currently " + str(int(max_iter)) + ").\n"
                "2. Enable **Progressive Tightening** checkbox — starts with loose tolerances.\n"
                "3. Switch to **Adaptive** solver mode (SLP → NLP → Trust-Region cascade).\n"
                "4. Verify the **Shared Component Set** matches all unit types."
            ),
            "INFEASIBLE": (
                "**Potential fixes:**\n"
                "1. Widen variable bounds or reduce `extra_bounds` constraints.\n"
                "2. Check connections are correctly wired (look for zero flows in the stream table).\n"
                "3. Loosen Step Tolerance (eps_x) in **Advanced solver settings**."
            ),
            "NUMERICAL_ERROR": (
                "**Potential fixes:**\n"
                "1. Try a different LP solver backend (HiGHS → CBC).\n"
                "2. Enable Trust-Region mode with a reduced minimum radius.\n"
                "3. Check for near-zero denominators in equilibrium unit models."
            ),
        }
        _tip = _tips.get(_status_name, "")
        if _tip:
            with st.expander("Potential Fix"):
                st.markdown(_tip)

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

    # ── Excel download (3 sheets, unit-tagged) ────────────────────────────────
    try:
        import io
        import pandas as _pd
        _last_fs = st.session_state.get("last_flowsheet")
        _buf = io.BytesIO()
        with _pd.ExcelWriter(_buf, engine="openpyxl") as _writer:

            # Sheet 1: Stream Table — variables parsed from unit.port.variable format.
            # Every row carries the inferred SI unit so the value is never ambiguous.
            _stream_rows = []
            for k, v in result.x.items():
                _parts = k.split(".")
                _var_name = ".".join(_parts[2:]) if len(_parts) >= 3 else k
                _si = _infer_si_unit(_var_name)
                _row = {
                    "Equipment": _parts[0] if len(_parts) >= 3 else "",
                    "Port":      _parts[1] if len(_parts) >= 3 else "",
                    "Variable":  _var_name,
                    "Value":     v,
                    "SI Unit":   _si,
                }
                _stream_rows.append(_row)
            _pd.DataFrame(_stream_rows).to_excel(_writer, sheet_name="Stream Table", index=False)

            # Sheet 2: Unit Performance — per-unit KPIs + capex where available.
            # KPI names already embed their unit by convention (e.g. duty_kW,
            # Y_H2_kg_per_h); we surface that suffix into its own column.
            _perf_rows = []
            if _last_fs is not None:
                for _unit in _last_fs.units:
                    try:
                        for kk, vv in _unit.kpis(result.x).items():
                            _perf_rows.append({
                                "Equipment": _unit.unit_id,
                                "KPI":       kk,
                                "Value":     vv,
                                "SI Unit":   _infer_si_unit(kk),
                            })
                        # v1.4.0 audit N31 — was `getattr(_unit, "capex_USD", …)`
                        # which only matched the legacy CoolerHF method name
                        # renamed in audit H6; now uses the BaseUnit.capex
                        # contract so every unit that overrides capex() is
                        # surfaced. Units that already report capex_USD via
                        # their kpis() dict get reported once via that loop;
                        # this block only adds a row when the BaseUnit
                        # method returns a non-zero value AND the kpis() dict
                        # did not already contribute one.
                        _has_capex_in_kpis = any(
                            r["Equipment"] == _unit.unit_id
                            and "capex" in str(r["KPI"]).lower()
                            for r in _perf_rows
                        )
                        _capex = getattr(_unit, "capex", lambda _x: 0.0)(result.x)
                        if _capex and not _has_capex_in_kpis:
                            _perf_rows.append({
                                "Equipment": _unit.unit_id,
                                "KPI":       "capex_USD",
                                "Value":     _capex,
                                "SI Unit":   "USD",
                            })
                    except Exception as _kpi_exc:  # noqa: BLE001
                        # v1.4.0 audit N12 — surface unit KPI failures
                        # instead of swallowing them silently.
                        st.warning(
                            f"KPI extraction failed for {_unit.unit_id}: "
                            f"{type(_kpi_exc).__name__}: {_kpi_exc}"
                        )
            if not _perf_rows:
                _perf_rows = [
                    {"Equipment": "all", "KPI": k, "Value": v, "SI Unit": _infer_si_unit(k)}
                    for k, v in result.kpis.items()
                ]
            _pd.DataFrame(_perf_rows).to_excel(_writer, sheet_name="Unit Performance", index=False)

            # Sheet 3: Optimization Summary
            _summary = [
                {"Field": "Status",     "Value": str(result.status).split(".")[-1]},
                {"Field": "Iterations", "Value": result.iterations},
                {"Field": "Objective",  "Value": result.objective},
                {"Field": "Converged",  "Value": result.converged},
                {"Field": "Message",    "Value": result.message},
                {"Field": "BoundActiveCount", "Value": len(getattr(result, "bound_active", []) or [])},
            ]
            _pd.DataFrame(_summary).to_excel(_writer, sheet_name="Optimization Summary", index=False)

            # Sheet 4: Bound Saturation — v1.4.1 physics safety net.
            # One row per variable whose converged value sits at a non-fixed
            # bound. Always emitted (headers-only when no saturation) so the
            # export shape stays consistent across runs.
            _bound_rows = []
            _bound_active_list = getattr(result, "bound_active", []) or []
            _bounds_map = _last_fs.aggregated_bounds() if _last_fs is not None else {}
            for _v in _bound_active_list:
                _val = float(result.x.get(_v, float("nan")))
                _lb, _ub = _bounds_map.get(_v, (float("-inf"), float("inf")))
                _hit = "lo" if abs(_val - _lb) < abs(_val - _ub) else "hi"
                _bound_rows.append({
                    "Variable":     _v,
                    "Value":        _val,
                    "Lower":        _lb,
                    "Upper":        _ub,
                    "Hit":          _hit,
                })
            if not _bound_rows:
                _bound_rows = [{"Variable": "", "Value": "", "Lower": "",
                                "Upper": "", "Hit": "(none — physics OK)"}]
            _pd.DataFrame(_bound_rows).to_excel(_writer, sheet_name="Bound Saturation", index=False)

            # Sheet 5: Project Economics & Cash Flow (computed via flowsheet_service bridge)
            try:
                from pse_ecosystem.ui.flowsheet_service import (
                    compute_project_economics, ProjectEconomicsConfig,
                )
                _oc_xls = st.session_state.get("objective_config") or {}
                _cfg_xls = ProjectEconomicsConfig(
                    plant_life_yr=int(_oc_xls.get("plant_life_yr", 20)),
                    interest_rate=float(_oc_xls.get("interest_rate", 0.08)),
                    tax_rate=float(_oc_xls.get("tax_rate", 0.20)),
                    inflation_rate=float(_oc_xls.get("inflation_rate", 0.025)),
                    operating_hours_per_year=float(_oc_xls.get("op_hours", 8000.0)),
                    electricity_price_USD_per_kWh=float(_oc_xls.get("elec_price", 0.05)),
                    biomass_price_USD_per_tonne=float(_oc_xls.get("biomass_price", 60.0)),
                    water_price_USD_per_tonne=float(_oc_xls.get("water_price", 0.5)),
                    cooling_water_price_USD_per_GJ=float(_oc_xls.get("cw_price", 0.35)),
                    carbon_tax_USD_per_tonne=float(_oc_xls.get("carbon_tax", 50.0)),
                )
                if _last_fs is not None and result.x:
                    _econ_rows = compute_project_economics(
                        flowsheet=_last_fs,
                        solution_x=result.x,
                        kpis=result.kpis,
                        econ_config=_cfg_xls,
                        obj_config=_oc_xls,
                    )
                    _pd.DataFrame(_econ_rows).to_excel(
                        _writer, sheet_name="Project Economics", index=False
                    )
            except Exception as _econ_exc:
                # Surface failure via a single-row diagnostic sheet so the user
                # sees WHY the economics aren't populated instead of silent absence.
                _pd.DataFrame([{
                    "Metric": "ERROR",
                    "Value":  f"{type(_econ_exc).__name__}: {_econ_exc}",
                    "Unit":   "—",
                }]).to_excel(_writer, sheet_name="Project Economics", index=False)

        st.download_button(
            label="⬇ Download Results (XLSX)",
            data=_buf.getvalue(),
            file_name="pse_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help=(
                "Sheet 1: Stream Table | Sheet 2: Unit Performance | "
                "Sheet 3: Optimization Summary | Sheet 4: Bound Saturation | "
                "Sheet 5: Project Economics & Cash Flow"
            ),
        )
    except ImportError:
        st.caption("Install `openpyxl` to enable Excel export: `pip install openpyxl`")

    # Technology selection (MILP only)
    if result.technology_selection:
        st.subheader("Technology Selection")
        selected = [k for k, v in result.technology_selection.items() if v]
        if selected:
            st.success(f"Active technologies: {', '.join(selected)}")
        else:
            st.warning("No technology was selected.")
        st.json(result.technology_selection)


# ── Page 6: Help Center & Documentation ───────────────────────────────────────

def _docs_dir():
    """Resolve the absolute docs/ folder regardless of CWD."""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.parent / "docs"


def _load_doc(rel_name: str) -> str:
    """Read a markdown file from docs/ with caching keyed on content hash.

    v1.4.0 audit N26 — pre-fix the cache key was ``path.stat().st_mtime``,
    which is unreliable for docs symlinked from a git checkout (some POSIX
    filesystems don't propagate mtime through symlinks; Windows preserves
    NTFS metadata but the value can lag by the filesystem's resolution).
    Use a SHA-1 of the file content instead so the cache is invariant
    under copies / symlinks but invalidates when the bytes actually change.

    Audit N27 — validate ``rel_name`` against directory traversal even
    though the Help Center only calls this with hardcoded names today;
    future API callers must not be able to escape ``docs/``.
    """
    import hashlib
    from pathlib import Path
    import streamlit as st  # already imported by caller; safe re-import for cache scope

    # N27: reject any rel_name that resolves outside docs/ after symlink
    # resolution. ``Path.resolve()`` collapses ".." segments.
    docs_root = _docs_dir().resolve()
    try:
        candidate = (docs_root / rel_name).resolve()
        candidate.relative_to(docs_root)
    except (ValueError, RuntimeError):
        return (
            f"_Refused to load `{rel_name}` — path escapes the docs/ "
            f"directory. Only filenames inside the workspace docs/ folder "
            f"are accepted by the Help Center loader._"
        )

    if not candidate.exists():
        return f"_Document `{rel_name}` is not yet available in this build._"

    @st.cache_data(show_spinner=False)
    def _read(path_str: str, content_hash: str) -> str:
        return Path(path_str).read_text(encoding="utf-8")

    raw = candidate.read_bytes()
    digest = hashlib.sha1(raw).hexdigest()
    return _read(str(candidate), digest)


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
        st.Page(_page_gps_weather,        title="Site Weather",      icon="🌍"),
        st.Page(_page_solver_monitor,     title="Solver Monitor",    icon="📊"),
        st.Page(_page_help_center,        title="Help Center",       icon="📖"),
    ]
    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
