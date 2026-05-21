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
    st.session_state.setdefault("custom_flowsheet_cfg", None)  # v1.5.2 serializable config dict
    st.session_state.setdefault("objective_config", None)      # v1.4.0 audit M10
    st.session_state.setdefault("weather_ghi", None)
    st.session_state.setdefault("weather_wind", None)
    st.session_state.setdefault("weather_site", None)
    st.session_state.setdefault("user_persona", "Academic")    # v1.5.0 dual-persona
    st.session_state.setdefault("last_solve_elapsed", None)   # v1.5.1 solve timing
    st.session_state.setdefault("scenarios", [])              # v1.5.1 scenario manager


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
            from pse_ecosystem.ui.flowsheet_service import PSE_PLOTLY_TEMPLATE
            fig.update_layout(
                title="Annual Solar GHI Profile",
                xaxis_title="Hour of year",
                yaxis_title="GHI [W/m²]",
                height=350,
                **PSE_PLOTLY_TEMPLATE["layout"],
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
                **PSE_PLOTLY_TEMPLATE["layout"],
            )
            st.plotly_chart(fig2, use_container_width=True)


# ── Persona-specific solver-result views ─────────────────────────────────────

def _render_academic_solver_view(st, result, flowsheet) -> None:
    """Display Jacobian diagnostics and sensitivity derivatives (Academic persona)."""
    from pse_ecosystem.core.contracts import PrimalGuess

    st.subheader("Academic Analysis")

    if flowsheet is None or not result.x:
        st.info("No flowsheet available for Jacobian analysis.")
        return

    import numpy as np
    import pandas as pd

    guess = PrimalGuess(values=result.x, iteration=0)

    cond_rows = []
    grad_rows = []
    for unit in flowsheet.units:
        try:
            lm = unit.linearize(guess)
        except Exception:
            continue
        if lm.J.size > 0:
            cond = float(np.linalg.cond(lm.J))
            cond_rows.append({
                "Unit": unit.unit_id,
                "Type": type(unit).__name__,
                "J rows": lm.J.shape[0],
                "J cols": lm.J.shape[1],
                "Condition number": cond,
            })
        for kpi_name, grad in lm.kpi_gradients.items():
            for var, g in zip(lm.variables, grad):
                if abs(g) > 1e-12:
                    grad_rows.append({
                        "Unit": unit.unit_id,
                        "KPI": kpi_name,
                        "Variable": var,
                        "dKPI/dvar": g,
                    })

    if cond_rows:
        st.markdown("**Jacobian condition numbers** (post-solve re-linearisation at x*)")
        df_cond = pd.DataFrame(cond_rows)
        max_cond = df_cond["Condition number"].max()
        cond_color = "green" if max_cond < 100 else ("orange" if max_cond < 1000 else "red")
        st.markdown(
            f"Max condition: <span style='color:{cond_color}'><b>{max_cond:.3g}</b></span>",
            unsafe_allow_html=True,
        )
        st.dataframe(
            df_cond.style.format({"Condition number": "{:.3g}"}),
            use_container_width=True,
            hide_index=True,
        )

    if grad_rows:
        with st.expander("KPI sensitivity derivatives  dKPI/dvar  (non-zero only)"):
            st.dataframe(
                pd.DataFrame(grad_rows).style.format({"dKPI/dvar": "{:.4g}"}),
                use_container_width=True,
                hide_index=True,
            )


def _build_econ_config_from_session(st) -> "ProjectEconomicsConfig":
    """Reconstruct a ProjectEconomicsConfig from session state objective_config."""
    from pse_ecosystem.ui.flowsheet_service import ProjectEconomicsConfig
    oc = st.session_state.get("objective_config") or {}
    return ProjectEconomicsConfig(
        plant_life_yr=int(oc.get("plant_life_yr", 20)),
        interest_rate=float(oc.get("interest_rate", 0.08)),
        tax_rate=float(oc.get("tax_rate", 0.20)),
        inflation_rate=float(oc.get("inflation_rate", 0.025)),
        operating_hours_per_year=float(oc.get("op_hours", 8000.0)),
        electricity_price_USD_per_kWh=float(oc.get("elec_price", 0.05)),
        biomass_price_USD_per_tonne=float(oc.get("biomass_price", 60.0)),
        water_price_USD_per_tonne=float(oc.get("water_price", 0.5)),
        cooling_water_price_USD_per_GJ=float(oc.get("cw_price", 0.35)),
        carbon_tax_USD_per_tonne=float(oc.get("carbon_tax", 50.0)),
    )


def _render_industrial_solver_view(st, result, flowsheet) -> None:
    """Display CapEx/OpEx, safety margins, tornado chart, break-even, and report download."""
    from pse_ecosystem.ui.flowsheet_service import (
        compute_safety_margins, SafetyMarginRow,
        tornado_sensitivity, compute_npv_with_revenue,
        generate_investor_report, PSE_PLOTLY_TEMPLATE,
        get_template,
    )

    st.subheader("Industrial Analysis")

    if flowsheet is None or not result.x:
        st.info("No flowsheet available for industrial analysis.")
        return

    import plotly.graph_objects as go
    import pandas as pd

    econ_cfg = _build_econ_config_from_session(st)

    # ── CapEx / OpEx breakdown ────────────────────────────────────────────────
    capex_vals, opex_vals, unit_labels = [], [], []
    for unit in flowsheet.units:
        try:
            cx = unit.capex(result.x)
            ox = unit.opex_per_year(result.x)
        except Exception:
            continue
        if cx > 0.0 or ox > 0.0:
            unit_labels.append(unit.unit_id)
            capex_vals.append(cx)
            opex_vals.append(ox)

    if unit_labels:
        fig_cost = go.Figure(data=[
            go.Bar(name="CapEx (USD)", x=unit_labels, y=capex_vals,
                   marker_color="#4a90e2"),
            go.Bar(name="OpEx/yr (USD/yr)", x=unit_labels, y=opex_vals,
                   marker_color="#e24a4a"),
        ])
        fig_cost.update_layout(
            barmode="group",
            title="Equipment Capital & Operating Cost",
            xaxis_title="Unit",
            yaxis_title="Cost [USD or USD/yr]",
            height=350,
            **PSE_PLOTLY_TEMPLATE["layout"],
        )
        st.plotly_chart(fig_cost, use_container_width=True)

        total_capex = sum(capex_vals)
        total_opex  = sum(opex_vals)
        c1, c2 = st.columns(2)
        c1.metric("Total CapEx (USD)", f"${total_capex:,.0f}")
        c2.metric("Total OpEx/yr (USD/yr)", f"${total_opex:,.0f}")

    # ── Carbon Intensity benchmark ────────────────────────────────────────────
    _CI_KEY_SUFFIX = "CI_kg_CO2_per_kg_H2"
    _ci_kpis = {k: v for k, v in result.kpis.items() if k.endswith(_CI_KEY_SUFFIX)}
    if _ci_kpis:
        _CI_BENCHMARKS = {
            "SMR (unabated)": 9.0,
            "Blue H₂ (SMR + CCS 90%)": 1.8,
            "Grid electrolysis (UK 2024)": 24.0,
            "Green H₂ target (<1 kg CO₂/kg)": 1.0,
        }
        ci_val = list(_ci_kpis.values())[0]
        st.markdown("**Carbon Intensity Benchmark**")
        bench_rows = []
        for bench_name, bench_val in _CI_BENCHMARKS.items():
            diff = ci_val - bench_val
            bench_rows.append({
                "Reference pathway": bench_name,
                "CI [kg CO₂/kg H₂]": f"{bench_val:.1f}",
                "This design vs reference": f"{diff:+.2f}",
                "Better?": "Yes" if diff < 0 else "No",
            })
        st.dataframe(
            pd.DataFrame(bench_rows).style.applymap(
                lambda v: "color: green" if v == "Yes" else "color: red",
                subset=["Better?"],
            ),
            use_container_width=True, hide_index=True,
        )

    # ── ASME material selector ────────────────────────────────────────────────
    from pse_ecosystem.ui.flowsheet_service import get_asme_materials
    _asme_mats = get_asme_materials()
    _material_choice = st.selectbox(
        "Shell material (ASME allowable stress)",
        list(_asme_mats.keys()),
        key="asme_material_selector",
    )
    _allowable_stress = _asme_mats[_material_choice]

    # ── ASME + flammability safety margins ────────────────────────────────────
    st.markdown("**Engineering Safety Margins** *(post-solve audit — not a certified ASME analysis)*")
    safety_rows: list = []
    try:
        safety_rows = compute_safety_margins(
            flowsheet, result.x,
            allowable_stress_Pa=_allowable_stress,
        )
    except Exception as exc:
        st.caption(f"Safety check unavailable: {exc}")

    _STATUS_COLOR = {"OK": "green", "WARNING": "orange", "VIOLATION": "red"}
    if safety_rows:
        rows_data = []
        for row in safety_rows:
            rows_data.append({
                "Unit":   row.unit_id,
                "Check":  row.check_type,
                "Value":  f"{row.value:.4g}" if row.value == row.value else "—",
                "Status": row.status,
                "Detail": row.detail,
            })
        df_safety = pd.DataFrame(rows_data)

        def _color_status(val):
            return f"color: {_STATUS_COLOR.get(val, 'grey')}; font-weight: bold"

        st.dataframe(
            df_safety.style.map(_color_status, subset=["Status"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("No pressure-vessel units identified — no ASME checks generated.")

    # ── Economic Sensitivity (Tornado) ────────────────────────────────────────
    with st.expander("Economic Sensitivity — Tornado Chart", expanded=False):
        _target = st.selectbox(
            "KPI to analyse", ["LCOH", "LCOE", "TAC", "Annualised CAPEX", "Annual OPEX"],
            key="tornado_target_metric",
        )
        _pct = st.slider("Perturbation (%)", min_value=5, max_value=50, value=20, step=5,
                         key="tornado_pct") / 100.0

        try:
            t_rows = tornado_sensitivity(
                flowsheet, result.x, result.kpis, econ_cfg,
                target_metric=_target, perturbation_frac=_pct,
            )
            t_rows_valid = [r for r in t_rows if r.impact > 0]
        except Exception as exc:
            st.warning(f"Tornado computation failed: {exc}")
            t_rows_valid = []

        if t_rows_valid:
            # Horizontal bar chart — bars show [delta_low, delta_high] relative to base
            params   = [r.param_label for r in t_rows_valid]
            d_low    = [r.delta_low   for r in t_rows_valid]
            d_high   = [r.delta_high  for r in t_rows_valid]

            fig_t = go.Figure()
            fig_t.add_trace(go.Bar(
                name=f"−{int(_pct*100)}%",
                y=params, x=d_low,
                orientation="h",
                marker_color="#e24a4a",
            ))
            fig_t.add_trace(go.Bar(
                name=f"+{int(_pct*100)}%",
                y=params, x=d_high,
                orientation="h",
                marker_color="#4a90e2",
            ))
            fig_t.update_layout(
                barmode="overlay",
                title=f"Δ{_target} vs ±{int(_pct*100)}% parameter perturbation",
                xaxis_title=f"Δ{_target}",
                height=max(300, 50 * len(t_rows_valid) + 80),
                **PSE_PLOTLY_TEMPLATE["layout"],
            )
            st.plotly_chart(fig_t, use_container_width=True)
        else:
            st.info(f"No sensitivity detected for {_target} — check that the flowsheet has non-zero economics.")

    # ── Break-even Calculator ─────────────────────────────────────────────────
    with st.expander("Break-even & NPV Calculator", expanded=False):
        st.caption(
            "Enter an expected H₂ selling price to compute NPV with revenue.  "
            "The break-even price equals the LCOH."
        )
        h2_price = st.number_input(
            "H₂ market price (USD/kg)", min_value=0.0, value=3.0, step=0.1,
            format="%.2f", key="breakeven_h2_price",
        )
        try:
            be = compute_npv_with_revenue(
                flowsheet, result.x, result.kpis, econ_cfg,
                product_price_USD_per_kg=h2_price,
            )
            lcoh = be["lcoh"]
            npv_rev = be["npv_with_revenue"]
            margin = be["margin_USD_per_kg"]
            payback = be["payback_yr"]

            import math
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Break-even price (LCOH)", f"${lcoh:.2f}/kg" if not math.isnan(lcoh) else "N/A")
            b2.metric("NPV at market price", f"${npv_rev:,.0f}",
                      delta=f"{'positive' if npv_rev >= 0 else 'negative'}",
                      delta_color="normal" if npv_rev >= 0 else "inverse")
            b3.metric("Margin vs LCOH", f"${margin:+.2f}/kg",
                      delta_color="normal" if margin >= 0 else "inverse")
            b4.metric("Payback period", f"{payback:.1f} yr" if payback < 1e6 else "∞")
        except Exception as exc:
            st.warning(f"Break-even computation failed: {exc}")

    # ── Investor Report download ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Investor Report**")

    _selected_key = st.session_state.get("selected_template")
    _spec = None
    if _selected_key:
        try:
            _spec = get_template(_selected_key)
        except Exception:
            pass

    _scenario_label = st.text_input("Scenario name for report", value="Base Case",
                                    key="report_scenario_label")

    try:
        t_rows_for_report = tornado_sensitivity(
            flowsheet, result.x, result.kpis, econ_cfg,
            target_metric="LCOH", perturbation_frac=0.20,
        ) if result.x else []
    except Exception:
        t_rows_for_report = []

    try:
        _report_md = generate_investor_report(
            flowsheet=flowsheet,
            result=result,
            econ_config=econ_cfg,
            safety_rows=safety_rows,
            template_spec=_spec,
            scenario_label=_scenario_label,
            tornado_rows=t_rows_for_report,
        )
        st.download_button(
            label="⬇ Download Investor Report (.md)",
            data=_report_md,
            file_name=f"pse_investor_report_{_scenario_label.replace(' ', '_')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
        with st.expander("Preview Report"):
            st.markdown(_report_md)
    except Exception as exc:
        st.warning(f"Report generation failed: {exc}")


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
                    from pse_ecosystem.ui.flowsheet_service import PSE_PLOTLY_TEMPLATE
                    fig_.update_layout(
                        title="SLP — Live Convergence",
                        xaxis_title="Iteration",
                        height=300,
                        **PSE_PLOTLY_TEMPLATE["layout"],
                    )
                    fig_.update_yaxes(title_text="Objective",    secondary_y=False)
                    fig_.update_yaxes(title_text="Residual norm", secondary_y=True)
                    live_chart.plotly_chart(fig_, use_container_width=True)

            # If the template recommends trust regions (non-linear physics),
            # enable them automatically unless the user has explicitly disabled
            # them via advanced settings.
            _use_tr = getattr(spec, "recommends_trust_region", False)
            slp_cfg = SLPConfig(
                max_iter=int(max_iter),
                eps_x=float(eps_x),
                verbose=verbose,
                iteration_callback=_on_iter,
                progressive_tightening=bool(prog_tighten),
                trust_region_min=float(tr_min_radius),
                use_trust_region=_use_tr,
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

                import time as _time
                orch = Orchestrator(
                    flowsheet=flowsheet,
                    mode=mode,
                    slp_config=slp_cfg,
                    technology_choices=tech_choices,
                )
                _t0 = _time.perf_counter()
                result = orch.solve()
                _solve_elapsed = _time.perf_counter() - _t0
                st.session_state["last_solve_elapsed"] = _solve_elapsed

            # Collapse the live chart — the final chart below is higher quality.
            live_chart.empty()
            st.session_state["last_result"] = result
            st.session_state["last_flowsheet"] = flowsheet   # for per-unit Excel export

            # v1.5.0.dev-AUDIT3 UI-2: record this solve in the rolling history.
            from pse_ecosystem.ui.flowsheet_service import record_solve_in_history
            record_solve_in_history(
                st.session_state, result,
                mode_label=str(mode).split(".")[-1],
                objective_label=_obj_mode_val,
            )

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

    _elapsed = st.session_state.get("last_solve_elapsed")
    _elapsed_str = f"  |  Solved in **{_elapsed:.1f} s**" if _elapsed is not None else ""

    if result.converged:
        st.success(
            f"Converged in **{result.iterations}** iteration(s)  |  "
            f"Objective: **{result.objective:.4g}**{_elapsed_str}"
        )
    else:
        st.error(
            f"Solver status: **{str(result.status).split('.')[-1]}**  |  "
            f"{result.message}{_elapsed_str}"
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
        from pse_ecosystem.ui.flowsheet_service import PSE_PLOTLY_TEMPLATE
        fig.update_layout(title="SLP Convergence", xaxis_title="Iteration", height=350,
                          **PSE_PLOTLY_TEMPLATE["layout"])
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

        # v1.5.0.dev-AUDIT3 UI-4: apply unified PSE Plotly theme to all charts.
        from pse_ecosystem.ui.flowsheet_service import (
            PSE_PLOTLY_TEMPLATE, build_sankey_data,
        )
        fig_kpi = go.Figure(go.Bar(
            x=[k.split(".")[-1] for k in result.kpis],
            y=list(result.kpis.values()),
            marker_color="#4a90e2",
        ))
        fig_kpi.update_layout(
            title="KPI Summary", xaxis_title="KPI", yaxis_title="Value", height=300,
            **PSE_PLOTLY_TEMPLATE["layout"],
        )
        st.plotly_chart(fig_kpi, use_container_width=True)

        # v1.5.0.dev-AUDIT3 UI-1: Sankey diagram for material flows.
        _last_fs_sankey = st.session_state.get("last_flowsheet")
        if _last_fs_sankey is not None and getattr(_last_fs_sankey, "connections", None):
            try:
                sankey_data = build_sankey_data(_last_fs_sankey, result.x)
                if sankey_data["sources"]:
                    fig_sankey = go.Figure(go.Sankey(
                        node=dict(
                            label=sankey_data["labels"],
                            pad=20, thickness=20,
                            line=dict(color="#666", width=0.5),
                            color="#4a90e2",
                        ),
                        link=dict(
                            source=sankey_data["sources"],
                            target=sankey_data["targets"],
                            value=sankey_data["values"],
                            label=sankey_data["link_labels"],
                            color="rgba(74,144,226,0.35)",
                        ),
                    ))
                    fig_sankey.update_layout(
                        title="Material Flow Sankey", height=400,
                        font=PSE_PLOTLY_TEMPLATE["layout"]["font"],
                        paper_bgcolor=PSE_PLOTLY_TEMPLATE["layout"]["paper_bgcolor"],
                        margin=PSE_PLOTLY_TEMPLATE["layout"]["margin"],
                    )
                    st.plotly_chart(fig_sankey, use_container_width=True)
            except Exception as _sankey_exc:
                st.caption(f"Sankey unavailable: {_sankey_exc}")

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

        # S6: Flammability badge in stream table (Industrial view)
        if st.session_state.get("user_persona") == "Industrial":
            _last_fs_badge = st.session_state.get("last_flowsheet")
            if _last_fs_badge is not None:
                try:
                    from pse_ecosystem.ui.flowsheet_service import compute_outlet_flammability_warnings
                    _flamm_warnings = compute_outlet_flammability_warnings(
                        _last_fs_badge, result.x
                    )
                    if _flamm_warnings:
                        st.warning("**Flammability Flags** *(streams near or above LFL)*\n\n" +
                                   "\n\n".join(_flamm_warnings))
                except Exception:
                    pass

    # ── Persona-specific analysis view ────────────────────────────────────────
    _persona = st.session_state.get("user_persona", "Academic")
    _last_fs = st.session_state.get("last_flowsheet")
    st.divider()
    if _persona == "Industrial":
        _render_industrial_solver_view(st, result, _last_fs)
    else:
        _render_academic_solver_view(st, result, _last_fs)

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

            # Sheet 6: Equipment Datasheet (v1.5.1)
            if _last_fs is not None and result.x:
                _ds_rows = []
                try:
                    from pse_ecosystem.ui.flowsheet_service import compute_safety_margins
                    _ds_safety = {r.unit_id: r for r in compute_safety_margins(_last_fs, result.x)
                                  if r.check_type == "ASME_wall_thickness"}
                except Exception:
                    _ds_safety = {}
                for _unit in _last_fs.units:
                    try:
                        _bnds = _unit.bounds()
                        _t_min = min((v[0] for k, v in _bnds.items() if k.endswith(".T") or "T" in k.split(".")[-1]), default=float("nan"))
                        _t_max = max((v[1] for k, v in _bnds.items() if k.endswith(".T") or "T" in k.split(".")[-1]), default=float("nan"))
                        _p_max = max((v[1] for k, v in _bnds.items() if k.endswith(".P") or "P" in k.split(".")[-1]), default=float("nan"))
                        _cx  = _unit.capex(result.x)
                        _ox  = _unit.opex_per_year(result.x)
                        _asme = _ds_safety.get(_unit.unit_id)
                        _ds_rows.append({
                            "Tag":          _unit.unit_id,
                            "Type":         type(_unit).__name__,
                            "T_min [K]":    _t_min,
                            "T_max [K]":    _t_max,
                            "P_max [Pa]":   _p_max,
                            "CapEx [USD]":  round(_cx, 2),
                            "OpEx [USD/yr]": round(_ox, 2),
                            "ASME t_min [mm]": round(_asme.value * 1000, 2) if _asme and _asme.value == _asme.value else "N/A",
                            "ASME status":  _asme.status if _asme else "N/A",
                        })
                    except Exception:
                        continue
                if _ds_rows:
                    _pd.DataFrame(_ds_rows).to_excel(_writer, sheet_name="Equipment Datasheet", index=False)

        st.download_button(
            label="⬇ Download Results (XLSX)",
            data=_buf.getvalue(),
            file_name="pse_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help=(
                "Sheet 1: Stream Table | Sheet 2: Unit Performance | "
                "Sheet 3: Optimization Summary | Sheet 4: Bound Saturation | "
                "Sheet 5: Project Economics & Cash Flow | "
                "Sheet 6: Equipment Datasheet"
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


def _page_scenario_manager() -> None:
    """Scenario Manager & Analysis — compare scenarios and run per-scenario parameter sweeps."""
    st = _require_streamlit()
    _init_state(st)

    st.title("Scenario Manager & Analysis")
    st.caption(
        "Capture the current solve result as a named scenario, compare up to "
        "4 scenarios side-by-side, and run per-scenario 1D sensitivity sweeps "
        "to explore how engineering parameters drive economic KPIs."
    )

    from pse_ecosystem.ui.flowsheet_service import (
        ProjectEconomicsConfig, compute_project_economics,
        get_template, PSE_PLOTLY_TEMPLATE,
    )
    import math, pandas as pd, plotly.graph_objects as go

    _MAX_SCENARIOS = 4

    # ── Capture current solve as a scenario ──────────────────────────────────
    result    = st.session_state.get("last_result")
    flowsheet = st.session_state.get("last_flowsheet")
    tmpl_key  = st.session_state.get("selected_template")

    if result is not None and result.converged and flowsheet is not None:
        with st.form("capture_scenario_form"):
            _name = st.text_input(
                "Scenario name",
                value=f"Scenario {len(st.session_state['scenarios']) + 1}",
                placeholder="e.g. Base Case, High WACC, +20% CapEx",
            )
            _submitted = st.form_submit_button("Capture current solve as scenario",
                                               type="primary")

        if _submitted and _name.strip():
            oc = st.session_state.get("objective_config") or {}
            try:
                econ_cfg = _build_econ_config_from_session(st)
            except Exception:
                econ_cfg = None

            econ_rows: list = []
            if econ_cfg is not None:
                try:
                    econ_rows = compute_project_economics(
                        flowsheet, result.x, result.kpis, econ_cfg, oc
                    )
                except Exception:
                    pass

            def _ev(metric):
                for r in econ_rows:
                    if r.get("Metric") == metric:
                        try:
                            return float(r["Value"])
                        except (TypeError, ValueError):
                            return float("nan")
                return float("nan")

            record = {
                "name":         _name.strip(),
                "template_key": tmpl_key or "—",
                "template_params": dict(st.session_state.get("template_params") or {}),
                "iterations":   result.iterations,
                "objective":    result.objective,
                "kpis":         dict(result.kpis),
                # Economics summary
                "installed_capex":  _ev("Installed CAPEX"),
                "annual_opex":      _ev("Annual OPEX"),
                "tac":              _ev("TAC"),
                "lcoh":             _ev("LCOH"),
                "lcoe":             _ev("LCOE"),
                "npv":              _ev("NPV"),
                "irr":              _ev("IRR"),
                # Config snapshot
                "econ_config": {
                    "plant_life_yr":   econ_cfg.plant_life_yr if econ_cfg else None,
                    "interest_rate":   econ_cfg.interest_rate if econ_cfg else None,
                    "elec_price":      econ_cfg.electricity_price_USD_per_kWh if econ_cfg else None,
                    "biomass_price":   econ_cfg.biomass_price_USD_per_tonne if econ_cfg else None,
                    "op_hours":        econ_cfg.operating_hours_per_year if econ_cfg else None,
                },
            }

            scenarios = st.session_state["scenarios"]
            if len(scenarios) >= _MAX_SCENARIOS:
                scenarios.pop(0)  # evict oldest
            scenarios.append(record)
            st.session_state["scenarios"] = scenarios
            st.success(f"Scenario '{_name.strip()}' captured ({len(scenarios)}/{_MAX_SCENARIOS}).")
            st.rerun()
    else:
        st.info(
            "No converged solve available.  Run a solve on the **Solver Monitor** page first, "
            "then return here to capture it as a scenario."
        )

    # ── Scenario list + clear ────────────────────────────────────────────────
    scenarios = st.session_state.get("scenarios", [])
    if not scenarios:
        st.info("No scenarios captured yet.  Solve a flowsheet and use the form above.")
        return

    col_clear, _ = st.columns([1, 4])
    if col_clear.button("Clear all scenarios"):
        st.session_state["scenarios"] = []
        st.rerun()

    st.subheader(f"Comparison — {len(scenarios)} scenario(s)")

    # ── Side-by-side comparison table ────────────────────────────────────────
    _ECON_METRICS = [
        ("Installed CAPEX", "installed_capex", "USD"),
        ("Annual OPEX",     "annual_opex",     "USD/yr"),
        ("TAC",             "tac",             "USD/yr"),
        ("LCOH",            "lcoh",            "USD/kg H₂"),
        ("LCOE",            "lcoe",            "USD/kWh"),
        ("NPV",             "npv",             "USD"),
        ("IRR",             "irr",             "%"),
    ]

    table_rows = []
    for label, key, unit in _ECON_METRICS:
        row_vals = {"Metric": label, "Unit": unit}
        base_val = scenarios[0].get(key, float("nan"))
        for i, sc in enumerate(scenarios):
            v = sc.get(key, float("nan"))
            v_str = f"{v:,.2f}" if isinstance(v, float) and not math.isnan(v) and not math.isinf(v) else "—"
            if i > 0 and isinstance(v, float) and isinstance(base_val, float) and not math.isnan(v) and not math.isnan(base_val) and base_val != 0:
                delta_pct = (v - base_val) / abs(base_val) * 100
                v_str += f"  ({delta_pct:+.1f}%)"
            row_vals[sc["name"]] = v_str
        table_rows.append(row_vals)

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    st.caption("Δ% values are relative to the first (Base) scenario.")

    # ── Solver stats ─────────────────────────────────────────────────────────
    st.subheader("Solver Summary")
    stat_rows = []
    for sc in scenarios:
        stat_rows.append({
            "Scenario":    sc["name"],
            "Template":    sc["template_key"],
            "Iterations":  sc["iterations"],
            "Objective":   f"{sc['objective']:.4g}",
        })
    st.dataframe(pd.DataFrame(stat_rows), use_container_width=True, hide_index=True)

    # ── LCOH / NPV bar chart ──────────────────────────────────────────────────
    names    = [sc["name"] for sc in scenarios]
    lcoh_vals = [sc.get("lcoh", float("nan")) for sc in scenarios]
    npv_vals  = [sc.get("npv",  float("nan")) for sc in scenarios]

    if any(not math.isnan(v) for v in lcoh_vals):
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Bar(name="LCOH (USD/kg)", x=names, y=lcoh_vals,
                                marker_color="#4a90e2", yaxis="y1"))
        fig_sc.add_trace(go.Bar(name="NPV (USD ×1M)", x=names,
                                y=[v / 1e6 if not math.isnan(v) else float("nan")
                                   for v in npv_vals],
                                marker_color="#50c878", yaxis="y2"))
        _sc_layout = {k: v for k, v in PSE_PLOTLY_TEMPLATE["layout"].items()
                      if k not in ("yaxis", "yaxis2", "barmode")}
        fig_sc.update_layout(
            barmode="group",
            title="LCOH and NPV comparison",
            yaxis=dict(title="LCOH [USD/kg H₂]"),
            yaxis2=dict(title="NPV [M USD]", overlaying="y", side="right"),
            height=380,
            **_sc_layout,
        )
        st.plotly_chart(fig_sc, use_container_width=True)

    # ── Excel download of scenario table ────────────────────────────────────
    try:
        import io
        import pandas as _pd
        _buf = io.BytesIO()
        with _pd.ExcelWriter(_buf, engine="openpyxl") as _writer:
            _pd.DataFrame(table_rows).to_excel(_writer, sheet_name="Scenario Comparison", index=False)
            _pd.DataFrame(stat_rows).to_excel(_writer, sheet_name="Solver Stats", index=False)
        st.download_button(
            label="⬇ Download Scenario Comparison (XLSX)",
            data=_buf.getvalue(),
            file_name="pse_scenario_comparison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except ImportError:
        pass

    # ── Per-scenario sensitivity analysis ───────────────────────────────────
    st.divider()
    st.subheader("Sensitivity Analysis")
    st.caption(
        "Pick a captured scenario and sweep one of its engineering parameters "
        "to see how KPIs (LCOH, NPV, H₂ yield…) respond.  No re-solve is needed "
        "for economic parameters — a full LP re-solve runs for engineering ones."
    )

    if not scenarios:
        st.info("Capture at least one scenario above before running a sweep.")
    else:
        _sc_names = [sc["name"] for sc in scenarios]
        _sel_sc_name = st.selectbox("Scenario to analyse", _sc_names,
                                    key="sens_scenario_sel")
        _sel_sc = next(sc for sc in scenarios if sc["name"] == _sel_sc_name)
        _sc_tmpl_key = _sel_sc.get("template_key", "—")

        # Economic parameter sweep (no re-solve, uses stored econ_config)
        _econ_sens_params = {
            "plant_life_yr":   ("Plant life [yr]",    1,   50),
            "interest_rate":   ("Interest / WACC [–]", 0.01, 0.30),
            "elec_price":      ("Electricity price [USD/kWh]", 0.01, 0.30),
            "biomass_price":   ("Biomass price [USD/t]",       10.0, 300.0),
            "op_hours":        ("Operating hours [h/yr]",      2000, 8760),
        }

        _sweep_type = st.radio(
            "Sweep type",
            ["Economic parameter (fast, no re-solve)",
             "Engineering parameter (requires LP re-solve per point)"],
            horizontal=True,
            key="sens_sweep_type",
        )

        if "Economic" in _sweep_type:
            _ep_labels = {v[0]: k for k, v in _econ_sens_params.items()}
            _ep_sel = st.selectbox("Parameter", list(_ep_labels.keys()),
                                   key="sens_econ_param")
            _ep_key = _ep_labels[_ep_sel]
            _ep_lo_def, _ep_hi_def = _econ_sens_params[_ep_key][1], _econ_sens_params[_ep_key][2]
            _ep_base = _sel_sc.get("econ_config", {}).get(_ep_key, (_ep_lo_def + _ep_hi_def) / 2)

            _sens_col1, _sens_col2, _sens_col3 = st.columns(3)
            _ep_lo  = _sens_col1.number_input("Min", value=float(_ep_lo_def), format="%.4g",
                                              key="sens_ep_lo")
            _ep_hi  = _sens_col2.number_input("Max", value=float(_ep_hi_def), format="%.4g",
                                              key="sens_ep_hi")
            _ep_pts = int(_sens_col3.number_input("Points", min_value=3, max_value=30,
                                                  value=10, step=1, key="sens_ep_pts"))

            if st.button("Run Economic Sweep", key="run_econ_sweep_btn", type="primary"):
                import numpy as np, pandas as pd, plotly.graph_objects as go
                from pse_ecosystem.ui.flowsheet_service import (
                    ProjectEconomicsConfig, compute_project_economics,
                )
                _base_ec = _sel_sc.get("econ_config", {})
                _kpi_targets = ["LCOH", "NPV", "TAC"]
                _sweep_vals = list(np.linspace(_ep_lo, _ep_hi, _ep_pts))
                _rows = []
                _prog = st.progress(0, text=f"Sweeping {_ep_sel}…")
                for _i, _v in enumerate(_sweep_vals):
                    try:
                        _ec_kwargs = {
                            "plant_life_yr":   _base_ec.get("plant_life_yr", 20),
                            "interest_rate":   _base_ec.get("interest_rate", 0.08),
                            "electricity_price_USD_per_kWh": _base_ec.get("elec_price", 0.05),
                            "biomass_price_USD_per_tonne":   _base_ec.get("biomass_price", 80.0),
                            "operating_hours_per_year":      _base_ec.get("op_hours", 8000),
                        }
                        _ec_kwargs[
                            {"plant_life_yr": "plant_life_yr",
                             "interest_rate": "interest_rate",
                             "elec_price": "electricity_price_USD_per_kWh",
                             "biomass_price": "biomass_price_USD_per_tonne",
                             "op_hours": "operating_hours_per_year"}.get(_ep_key, _ep_key)
                        ] = _v
                        _cfg_i = ProjectEconomicsConfig(**_ec_kwargs)
                        _fs_i  = st.session_state.get("last_flowsheet")
                        _res_i = st.session_state.get("last_result")
                        if _fs_i is None or _res_i is None:
                            st.warning("No flowsheet in memory — run a solve first.")
                            break
                        _erows = compute_project_economics(
                            _fs_i, _res_i.x, _res_i.kpis, _cfg_i, {}
                        )
                        def _get_kpi(metric):
                            for r in _erows:
                                if r.get("Metric") == metric:
                                    try:
                                        return float(r["Value"])
                                    except Exception:
                                        return float("nan")
                            return float("nan")
                        _row = {"param_value": _v}
                        for _m in _kpi_targets:
                            _row[_m] = _get_kpi(_m)
                        _rows.append(_row)
                    except Exception:
                        _rows.append({"param_value": _v,
                                      **{_m: float("nan") for _m in _kpi_targets}})
                    _prog.progress((_i + 1) / _ep_pts)
                _prog.empty()

                if _rows:
                    _df_sw = pd.DataFrame(_rows)
                    import math as _math
                    for _m in _kpi_targets:
                        if any(not _math.isnan(v) for v in _df_sw[_m]):
                            _fig_sw = go.Figure()
                            _fig_sw.add_trace(go.Scatter(
                                x=_df_sw["param_value"], y=_df_sw[_m],
                                mode="lines+markers", name=_m,
                            ))
                            _fig_sw.update_layout(
                                title=f"{_m} vs {_ep_sel}  [{_sel_sc_name}]",
                                xaxis_title=_ep_sel, yaxis_title=_m, height=340,
                                **PSE_PLOTLY_TEMPLATE["layout"],
                            )
                            st.plotly_chart(_fig_sw, use_container_width=True)
                    st.dataframe(_df_sw, use_container_width=True, hide_index=True)

        else:
            # Engineering parameter sweep — requires LP re-solve per point
            if _sc_tmpl_key in ("—", "custom.user_flowsheet"):
                st.info(
                    "Engineering sweeps are not available for custom-assembled flowsheets "
                    "(no fixed parameter spec). Use the **1D Sensitivity Sweep** tab "
                    "in the Flowsheet Builder instead."
                )
            else:
                try:
                    from pse_ecosystem.ui.flowsheet_service import get_template
                    _sc_spec = get_template(_sc_tmpl_key)
                    _eng_params = {
                        k: v for k, v in dict(_sc_spec.default_params).items()
                        if isinstance(v, (int, float)) and v != 0
                    }
                except Exception:
                    _eng_params = {}

                if not _eng_params:
                    st.info("No numeric engineering parameters available for this template.")
                else:
                    _ep2_sel = st.selectbox("Engineering parameter",
                                            list(_eng_params.keys()),
                                            key="sens_eng_param")
                    _ep2_base = float(_sel_sc.get("template_params", {}).get(
                        _ep2_sel, _eng_params[_ep2_sel]))
                    _eng_col1, _eng_col2, _eng_col3 = st.columns(3)
                    _ep2_lo  = _eng_col1.number_input(
                        "Min", value=_ep2_base * 0.5, format="%.4g", key="sens_eng_lo")
                    _ep2_hi  = _eng_col2.number_input(
                        "Max", value=_ep2_base * 1.5, format="%.4g", key="sens_eng_hi")
                    _ep2_pts = int(_eng_col3.number_input(
                        "Points", min_value=3, max_value=20, value=6, step=1,
                        key="sens_eng_pts"))

                    if st.button("Run Engineering Sweep", key="run_eng_sweep_btn",
                                 type="primary"):
                        import numpy as np, pandas as pd, plotly.graph_objects as go
                        from pse_ecosystem.ui.flowsheet_service import load_template
                        from pse_ecosystem.solvers.orchestrator import Orchestrator
                        from pse_ecosystem.solvers.slp import SLPConfig
                        from pse_ecosystem.core.contracts import SolveMode

                        _base_params = dict(_sel_sc.get("template_params", {}))
                        _sweep2_vals = list(np.linspace(_ep2_lo, _ep2_hi, _ep2_pts))
                        _rows2, _kpi_keys = [], None
                        _prog2 = st.progress(0, text=f"Solving {_ep2_pts} points…")
                        for _i2, _v2 in enumerate(_sweep2_vals):
                            try:
                                _p2 = dict(_base_params)
                                _p2[_ep2_sel] = _v2
                                _fs2 = load_template(_sc_tmpl_key, _p2)
                                _orch2 = Orchestrator(
                                    flowsheet=_fs2, mode=SolveMode.FIXED_LP,
                                    slp_config=SLPConfig(max_iter=150),
                                )
                                _res2 = _orch2.solve()
                                if _kpi_keys is None and _res2.kpis:
                                    _kpi_keys = list(_res2.kpis.keys())[:5]
                                _row2 = {"param_value": _v2,
                                         "converged": _res2.converged,
                                         "iterations": _res2.iterations}
                                for _k in (_kpi_keys or []):
                                    _row2[_k] = _res2.kpis.get(_k, float("nan"))
                                _rows2.append(_row2)
                            except Exception:
                                _rows2.append({"param_value": _v2, "converged": False})
                            _prog2.progress((_i2 + 1) / _ep2_pts)
                        _prog2.empty()

                        if _rows2 and _kpi_keys:
                            import math as _math
                            _df2 = pd.DataFrame(_rows2)
                            for _k in _kpi_keys:
                                if _k in _df2.columns and any(
                                    not _math.isnan(v)
                                    for v in _df2[_k] if isinstance(v, float)
                                ):
                                    _fig2 = go.Figure()
                                    _fig2.add_trace(go.Scatter(
                                        x=_df2["param_value"], y=_df2[_k],
                                        mode="lines+markers", name=_k,
                                    ))
                                    _fig2.update_layout(
                                        title=f"{_k} vs {_ep2_sel}  [{_sel_sc_name}]",
                                        xaxis_title=_ep2_sel, yaxis_title=_k,
                                        height=320,
                                        **PSE_PLOTLY_TEMPLATE["layout"],
                                    )
                                    st.plotly_chart(_fig2, use_container_width=True)
                            st.dataframe(_df2, use_container_width=True, hide_index=True)
                        elif _rows2:
                            st.warning("No KPIs available in sweep results.")


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

def main() -> None:
    st = _require_streamlit()

    st.set_page_config(
        page_title="PSE Ecosystem",
        page_icon="⚗",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _init_state(st)

    # ── Persona toggle — set once in main() so every page sees a stable value ──
    with st.sidebar:
        st.divider()
        st.caption("View Mode")
        _persona_idx = 0 if st.session_state.get("user_persona", "Academic") == "Academic" else 1
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
        st.Page(_page_dashboard,          title="Dashboard",          icon="🏠"),
        st.Page(_page_flowsheet_builder,  title="Flowsheet Builder",  icon="🔧"),
        st.Page(_page_gps_weather,        title="Site Weather",       icon="🌍"),
        st.Page(_page_solver_monitor,     title="Solver Monitor",     icon="📊"),
        st.Page(_page_scenario_manager,   title="Scenario Manager & Analysis",   icon="📋"),
        st.Page(_page_solve_history,      title="Solve History",      icon="📜"),
        st.Page(_page_help_center,        title="Help Center",        icon="📖"),
    ]
    pg = st.navigation(pages)
    pg.run()


if __name__ == "__main__":
    main()
