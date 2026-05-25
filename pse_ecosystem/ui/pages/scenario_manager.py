"""Scenario Manager & Analysis page — multi-scenario solve runs,
tornado sensitivity, Pareto fronts, and investor-report exports."""

from __future__ import annotations

from pse_ecosystem.ui.shared.docs_loader import _docs_dir, _load_doc
from pse_ecosystem.ui.shared.formatting import _infer_si_unit
from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit




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
