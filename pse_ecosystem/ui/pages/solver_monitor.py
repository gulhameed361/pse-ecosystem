"""Solver Monitor page — post-solve diagnostics, KPI tables, and
Academic / Industrial persona-aware result views."""

from __future__ import annotations

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit




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
