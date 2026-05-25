"""Flowsheet Builder page — the workhorse UI. Hosts template
selection, parameter editing, the Custom Builder, sensitivity
sweeps, Pareto sweeps, and the Solve button."""

from __future__ import annotations

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit




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
                    # Auto-set Industrial persona for industrial.* templates
                    if chosen_key.startswith("industrial."):
                        st.session_state["user_persona"] = "Industrial"
                    st.success(
                        f"Template **{spec.display_name}** selected. "
                        "Go to **Solver Monitor** to run, or use the sweep below."
                    )

        st.divider()

        # ── Pre-solve validator (v1.5.0.dev-AUDIT5 #1) ───────────────────────
        with st.expander("Pre-solve Validator", expanded=False):
            st.caption(
                "Runs `BaseFlowsheet.diagnose()` on the currently-selected "
                "template + parameters.  Catches inverted bounds, very-wide "
                "bounds, orphan units, and unknown variable references "
                "**before** you hit Run Solve on the Solver Monitor page."
            )
            if st.button("Validate Flowsheet", key="validate_fs_btn", type="primary"):
                try:
                    from pse_ecosystem.ui.flowsheet_service import load_template
                    _tmpl_key = st.session_state.get("selected_template", chosen_key)
                    if _tmpl_key == "custom.user_flowsheet":
                        _fs_to_check = st.session_state.get("custom_flowsheet")
                        if _fs_to_check is None:
                            st.warning(
                                "Build the custom flowsheet first (click **Build & Select** "
                                "on the assembler above)."
                            )
                            st.stop()
                    else:
                        _fs_to_check = load_template(
                            _tmpl_key,
                            st.session_state.get("template_params", {}),
                        )
                    diag = _fs_to_check.diagnose()
                    if diag["errors"]:
                        st.error(
                            f"**{len(diag['errors'])} error(s)** — solve will fail."
                        )
                        for e in diag["errors"]:
                            st.code(e, language=None)
                    else:
                        st.success("No errors. Safe to run.")
                    if diag["warnings"]:
                        st.warning(
                            f"**{len(diag['warnings'])} warning(s)** — may slow "
                            f"convergence:"
                        )
                        for w in diag["warnings"]:
                            st.code(w, language=None)
                    st.caption("**Flowsheet metrics**")
                    _info_cols = st.columns(len(diag["info"]) or 1)
                    for col, line in zip(_info_cols, diag["info"]):
                        if ":" in line:
                            label, val = line.split(":", 1)
                            col.metric(label.strip(), val.strip())
                except Exception as _ve:
                    st.error(
                        f"Could not build flowsheet for validation: "
                        f"{type(_ve).__name__}: {_ve}"
                    )

        # ── Save / Load flowsheet JSON (v1.5.0.dev-AUDIT3 UI-3) ──────────────
        with st.expander("Save / Load Configuration", expanded=False):
            from pse_ecosystem.ui.flowsheet_service import (
                serialize_flowsheet_config, deserialize_flowsheet_config,
            )
            _save_col, _load_col = st.columns(2)
            with _save_col:
                st.caption(
                    "Download the current template selection + parameters + "
                    "objective config as a JSON file for reproducibility."
                )
                _cfg_blob = serialize_flowsheet_config(
                    template_key=st.session_state.get("selected_template", chosen_key),
                    params=st.session_state.get("template_params", {}),
                    custom_cfg=st.session_state.get("custom_flowsheet_cfg"),
                    objective_config=st.session_state.get("objective_config"),
                    user_persona=st.session_state.get("user_persona", "Academic"),
                )
                st.download_button(
                    label="⬇ Save Configuration (JSON)",
                    data=_cfg_blob,
                    file_name=f"pse_flowsheet_config.json",
                    mime="application/json",
                    use_container_width=True,
                )
            with _load_col:
                st.caption("Load a previously-saved JSON to restore the run setup.")
                _upload = st.file_uploader(
                    "Upload JSON", type=["json"], key="flowsheet_cfg_upload",
                    label_visibility="collapsed",
                )
                if _upload is not None:
                    try:
                        _cfg = deserialize_flowsheet_config(_upload.read().decode("utf-8"))
                        if _cfg.get("template_key"):
                            st.session_state["selected_template"] = _cfg["template_key"]
                        if _cfg.get("params"):
                            st.session_state["template_params"] = _cfg["params"]
                        if _cfg.get("custom_cfg"):
                            # Restore serializable config; the BaseFlowsheet object cannot
                            # round-trip through JSON — user must click Build & Select again.
                            st.session_state["custom_flowsheet_cfg"] = _cfg["custom_cfg"]
                            st.session_state["custom_flowsheet"] = None
                        if _cfg.get("objective_config"):
                            st.session_state["objective_config"] = _cfg["objective_config"]
                        # v1.5.0: restore persona; old configs without the key default to Academic
                        st.session_state["user_persona"] = _cfg.get("user_persona", "Academic")
                        st.success(
                            f"Loaded config (schema v{_cfg.get('schema_version','?')}). "
                            "Switch to the Solver Monitor to run."
                        )
                    except ValueError as _le:
                        st.error(f"Bad JSON: {_le}")

        _fb_tabs = st.tabs([
            "1D Sensitivity Sweep",
            "2D Parameter Sensitivity Sweep",
            "Objective Function",
        ])

        with _fb_tabs[0]:
            _section_sensitivity_sweep(st, chosen_key, spec)

        with _fb_tabs[1]:
            _section_pareto_sweep(st, chosen_key, spec)

        with _fb_tabs[2]:
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
            # v1.5.0.dev-AUDIT D9: per-tier selectbox key so switching tiers
            # never triggers StreamlitAPIException ("Default value … not in options").
            # Each tier remembers its own last-selected objective independently.
            _obj_mode = st.selectbox(
                "Objective",
                OBJECTIVE_TIERS[_tier],
                key=f"objective_mode__{_tier}",
            )
            # Mirror into a shared key for downstream consumers (Solver Monitor).
            st.session_state["objective_mode"] = _obj_mode

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

            # Banner for objectives whose LP proxy differs from the labelled metric.
            from pse_ecosystem.ui.flowsheet_service import OBJECTIVE_LP_PROXY_NOTE
            if _obj_mode in OBJECTIVE_LP_PROXY_NOTE:
                st.warning(
                    f"**LP proxy note:** {OBJECTIVE_LP_PROXY_NOTE[_obj_mode]}"
                )

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

            # v1.5.0.dev-AUDIT3 UI-6: Apply + Reset buttons side by side.
            _apply_col, _reset_col = st.columns([1, 1])
            with _apply_col:
                if st.button("Apply Objective", key="apply_objective_btn",
                             type="primary", use_container_width=True):
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
            with _reset_col:
                if st.button("Reset to defaults", key="reset_objective_btn",
                             use_container_width=True,
                             help="Clear all financial parameter widgets and the saved objective_config."):
                    # Remove all obj_* widget keys so number_inputs revert to their default values.
                    _to_clear = [
                        k for k in list(st.session_state.keys())
                        if k.startswith("obj_") or k.startswith("objective_mode__")
                    ] + ["objective_config", "objective_mode"]
                    for _k in _to_clear:
                        st.session_state.pop(_k, None)
                    st.success("Reset. Refresh the page if widgets don't update.")
                    st.rerun()

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
                from pse_ecosystem.ui.flowsheet_service import PSE_PLOTLY_TEMPLATE
                fig_sw.update_layout(
                    title=f"Sensitivity: KPIs vs {sweep_param}",
                    xaxis_title=sweep_param,
                    yaxis_title="KPI value",
                    height=420,
                    legend=dict(orientation="h", y=-0.25),
                    **PSE_PLOTLY_TEMPLATE["layout"],
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


# ── 2D Parameter Sensitivity Sweep (v1.5.0.dev-AUDIT3 UI-5) ──────────────────




# ── 2D Parameter Sensitivity Sweep (v1.5.0.dev-AUDIT3 UI-5) ──────────────────

def _section_pareto_sweep(st, chosen_key: str, spec) -> None:
    """Vary two parameters across a small grid and scatter two KPIs against each
    other.  This is a **parameter sensitivity sweep** — not a multi-objective
    Pareto optimisation.  The lower-left cloud boundary approximates the
    trade-off frontier when both KPIs are 'lower is better'."""
    from pse_ecosystem.ui.flowsheet_service import load_template

    defaults = dict(spec.default_params)
    numeric_params = {
        k: v for k, v in defaults.items()
        if isinstance(v, (int, float)) and v != 0
    }
    if len(numeric_params) < 2:
        st.info("Need at least 2 numeric parameters to run a 2D sweep.")
        return

    st.subheader("2D Parameter Sensitivity Sweep")
    st.caption(
        "Sweeps two parameters across a small grid (≤ 6 × 6) and scatters two "
        "KPIs against each other.  Each marker is one solved flowsheet. "
        "Note: this is a sensitivity sweep, not a rigorous multi-objective "
        "Pareto front — use it to identify trade-off regions, not optimum points."
    )

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Parameter A**")
        param_a = st.selectbox("Variable A", list(numeric_params.keys()),
                               key=f"pareto_a_{chosen_key}", index=0)
        a_default = float(numeric_params[param_a])
        a_min = st.number_input("Min A", value=a_default * 0.5, format="%.4g",
                                key=f"pareto_amin_{chosen_key}")
        a_max = st.number_input("Max A", value=a_default * 1.5, format="%.4g",
                                key=f"pareto_amax_{chosen_key}")
        n_a = int(st.number_input("Points A", min_value=2, max_value=6, value=4,
                                  key=f"pareto_na_{chosen_key}"))
    with cB:
        st.markdown("**Parameter B**")
        param_b_options = [p for p in numeric_params if p != param_a]
        param_b = st.selectbox("Variable B", param_b_options,
                               key=f"pareto_b_{chosen_key}", index=0)
        b_default = float(numeric_params[param_b])
        b_min = st.number_input("Min B", value=b_default * 0.5, format="%.4g",
                                key=f"pareto_bmin_{chosen_key}")
        b_max = st.number_input("Max B", value=b_default * 1.5, format="%.4g",
                                key=f"pareto_bmax_{chosen_key}")
        n_b = int(st.number_input("Points B", min_value=2, max_value=6, value=4,
                                  key=f"pareto_nb_{chosen_key}"))

    if st.button("Run 2D Sweep", key=f"run_pareto_{chosen_key}"):
        import numpy as np
        import pandas as pd
        from pse_ecosystem.solvers.orchestrator import Orchestrator
        from pse_ecosystem.solvers.slp import SLPConfig
        from pse_ecosystem.core.contracts import SolveMode

        base_params = dict(st.session_state.get("template_params", defaults))
        a_grid = np.linspace(a_min, a_max, n_a)
        b_grid = np.linspace(b_min, b_max, n_b)
        total = n_a * n_b

        bar = st.progress(0.0, text=f"Sweeping 0/{total}")
        rows = []
        idx = 0
        for a_val in a_grid:
            for b_val in b_grid:
                idx += 1
                p = dict(base_params)
                p[param_a] = a_val
                p[param_b] = b_val
                try:
                    fs = load_template(chosen_key, p)
                    orch = Orchestrator(flowsheet=fs, mode=SolveMode.FIXED_LP,
                                        slp_config=SLPConfig(max_iter=40))
                    res = orch.solve()
                    row = {param_a: a_val, param_b: b_val,
                           "converged": res.converged}
                    row.update(res.kpis)
                except Exception as exc:
                    row = {param_a: a_val, param_b: b_val, "converged": False,
                           "_error": f"{type(exc).__name__}: {exc}"}
                rows.append(row)
                bar.progress(idx / total, text=f"Sweeping {idx}/{total}")
        bar.empty()

        df = pd.DataFrame(rows)
        st.session_state[f"pareto_df_{chosen_key}"] = df

    # Visualise the most recent sweep result (persists across reruns).
    df = st.session_state.get(f"pareto_df_{chosen_key}")
    if df is not None and len(df):
        kpi_cols = [c for c in df.columns
                    if c not in (param_a, param_b, "converged", "_error")
                    and df[c].dtype in (float, int)]
        if len(kpi_cols) < 2:
            st.warning("Need ≥ 2 numeric KPIs in the solve result to scatter.")
        else:
            cX, cY = st.columns(2)
            with cX:
                xk = st.selectbox("X-axis KPI", kpi_cols,
                                  key=f"pareto_xk_{chosen_key}", index=0)
            with cY:
                yk = st.selectbox("Y-axis KPI", kpi_cols,
                                  key=f"pareto_yk_{chosen_key}",
                                  index=min(1, len(kpi_cols)-1))
            import plotly.graph_objects as go
            from pse_ecosystem.ui.flowsheet_service import PSE_PLOTLY_TEMPLATE
            converged = df[df["converged"] == True]
            failed    = df[df["converged"] == False]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=converged[xk], y=converged[yk],
                mode="markers",
                marker=dict(size=10, color="#4a90e2",
                            line=dict(color="#2c3e50", width=1)),
                name=f"Converged ({len(converged)})",
                hovertext=[
                    f"{param_a}={row[param_a]:.4g}<br>{param_b}={row[param_b]:.4g}"
                    for _, row in converged.iterrows()
                ],
            ))
            if len(failed):
                fig.add_trace(go.Scatter(
                    x=failed[xk], y=failed[yk],
                    mode="markers",
                    marker=dict(size=8, color="#d62728", symbol="x"),
                    name=f"Failed ({len(failed)})",
                ))

            # v1.5.0.dev-AUDIT4 (#5): non-dominated frontier overlay.
            # Assumes both KPIs are 'lower is better' (the most common case);
            # toggle below lets the user invert per-axis if needed.
            import numpy as np
            _xmin = st.checkbox(f"Minimize {xk}", value=True, key=f"pareto_min_x_{chosen_key}")
            _ymin = st.checkbox(f"Minimize {yk}", value=True, key=f"pareto_min_y_{chosen_key}")
            if len(converged) >= 2:
                pts = converged[[xk, yk]].dropna().to_numpy()
                if pts.size and pts.shape[0] >= 2:
                    # Flip axes if maximising so we always seek lower-left.
                    sx = 1.0 if _xmin else -1.0
                    sy = 1.0 if _ymin else -1.0
                    scored = pts * np.array([sx, sy])
                    # Non-dominated: no other point is ≤ in both dimensions
                    # AND strictly < in at least one.
                    mask = []
                    for i, p in enumerate(scored):
                        dominated = False
                        for j, q in enumerate(scored):
                            if i == j:
                                continue
                            if (q[0] <= p[0]) and (q[1] <= p[1]) and (
                                q[0] < p[0] or q[1] < p[1]
                            ):
                                dominated = True
                                break
                        mask.append(not dominated)
                    front_pts = pts[np.array(mask)]
                    # Sort frontier by X for a clean connected line.
                    front_pts = front_pts[front_pts[:, 0].argsort()]
                    fig.add_trace(go.Scatter(
                        x=front_pts[:, 0], y=front_pts[:, 1],
                        mode="lines+markers",
                        line=dict(color="#27ae60", width=2, dash="dash"),
                        marker=dict(size=12, color="#27ae60", symbol="diamond",
                                    line=dict(color="#1e8449", width=1)),
                        name=f"Pareto front ({len(front_pts)})",
                    ))

            fig.update_layout(
                title=f"Pareto-style Trade-off: {yk} vs {xk}",
                xaxis_title=xk, yaxis_title=yk,
                height=460,
                **PSE_PLOTLY_TEMPLATE["layout"],
            )
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df, use_container_width=True, hide_index=True)


# ── Custom flowsheet assembler ────────────────────────────────────────────────




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
            from pse_ecosystem.ui.flowsheet_service import get_unit_main_specs, get_unit_bounds_specs
            _specs = get_unit_main_specs(utype)
            _bounds_spec_list = get_unit_bounds_specs(utype)
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

            # ── Advanced Bounds expander ──────────────────────────────────
            if _bounds_spec_list:
                with st.expander("Advanced Bounds", expanded=False):
                    st.caption(
                        "Override the default variable bounds for scale-up or "
                        "constraint tightening. Changes here propagate directly "
                        "into the LP — wide bounds allow the solver more freedom; "
                        "narrow bounds enforce design constraints."
                    )
                    _NCOL_B = 3
                    for _brow_start in range(0, len(_bounds_spec_list), _NCOL_B):
                        _brow = _bounds_spec_list[_brow_start:_brow_start + _NCOL_B]
                        _bcols = st.columns(_NCOL_B)
                        for _bcol, _bps in zip(_bcols, _brow):
                            _bkey = f"bound_{i}_{_bps.name}"
                            _blabel = f"{_bps.label} [{_bps.unit}]" if _bps.unit else _bps.label
                            if _bps.dtype == "float":
                                unit_params[_bps.name] = _bcol.number_input(
                                    _blabel, value=float(_bps.default),
                                    help=_bps.help, key=_bkey,
                                )
                            elif _bps.dtype == "int":
                                unit_params[_bps.name] = int(_bcol.number_input(
                                    _blabel, value=int(_bps.default),
                                    step=1, help=_bps.help, key=_bkey,
                                ))

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
            st.session_state["custom_flowsheet_cfg"] = config  # JSON-serializable snapshot
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
