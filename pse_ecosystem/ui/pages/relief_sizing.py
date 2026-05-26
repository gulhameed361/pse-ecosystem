"""Relief Sizing page — API 520 / 521 orifice-area calculator.

Surfaces ``pse_ecosystem.safety.relief_sizing`` (shipped in v1.6 E.1)
through a Streamlit form. The user picks a relieving scenario (fire,
blocked-outlet gas, thermal expansion), supplies vessel and fluid
properties, and gets the recommended orifice area + ASME setpoints +
relief load back in a table they can copy or export.

v1.6.1 P.7d — completes the audit-flagged "feature exists but no UI"
gap for the safety subpackage.
"""

from __future__ import annotations

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit


def _page_relief_sizing():
    st = _require_streamlit()
    _init_state(st)

    st.title("Relief Sizing — API 520 / 521")
    st.caption(
        "Orifice-area calculator for pressure-relief valves. Implements "
        "API 520 Part I (orifice area), API 521 §5.15 (fire case), and "
        "ASME Sec VIII UG-125 (set / full-lift pressures)."
    )

    from pse_ecosystem.safety.relief_sizing import (
        ReliefScenario, size_psv_for_vessel,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Vessel & fluid")
        P_design_bar = st.number_input(
            "Design pressure [bar]", min_value=0.1, value=20.0, step=0.5,
            help="ASME nameplate design pressure (gauge or absolute — be consistent).",
        )
        T_relief_C = st.number_input(
            "Relief temperature [°C]", min_value=-100.0, value=100.0, step=10.0,
            help="Operating temperature at which the PSV is sized.",
        )
        A_wetted_m2 = st.number_input(
            "Wetted area [m²]", min_value=0.0, value=50.0, step=5.0,
            help="External pool-fire heat-transfer area (API 521 §5.15). "
                 "0 = use blocked-outlet load instead.",
        )
        blocked_kg_s = st.number_input(
            "Blocked-outlet inflow [kg/s]", min_value=0.0, value=10.0, step=1.0,
        )

    with col_b:
        st.subheader("Fluid properties")
        MW_kg_mol = st.number_input(
            "MW [kg/mol]", min_value=0.002, value=0.044, step=0.001,
            format="%.4f",
            help="0.029 for air, 0.018 for water, 0.044 for propane / CO₂.",
        )
        gamma = st.number_input(
            "γ = Cp/Cv [-]", min_value=1.0, value=1.30, step=0.01,
            format="%.2f",
            help="1.4 for air, 1.32 for methane, 1.13 for ethanol, 1.30 light HC.",
        )
        H_vap_kJ_kg = st.number_input(
            "Latent heat H_vap [kJ/kg]", min_value=10.0, value=350.0, step=10.0,
            help="Used only for the fire case (sets the relief load).",
        )
        K_d = st.number_input(
            "Discharge coefficient K_d [-]", min_value=0.4, max_value=1.0,
            value=0.975, step=0.005, format="%.3f",
            help="0.975 for spring-operated PSV (API 520 Table 6), "
                 "0.65 for liquid service, 0.62 for rupture discs.",
        )

    st.divider()

    scenarios = [
        ReliefScenario.FIRE,
        ReliefScenario.BLOCKED_OUTLET_GAS,
        ReliefScenario.THERMAL_EXPANSION,
    ]
    rows = []
    for sc in scenarios:
        try:
            res = size_psv_for_vessel(
                P_design_Pa=P_design_bar * 1.0e5,
                T_relief_K=T_relief_C + 273.15,
                A_wetted_m2=A_wetted_m2,
                blocked_inflow_kg_per_s=blocked_kg_s,
                MW_kg_per_mol=MW_kg_mol,
                gamma=gamma,
                H_vap_J_per_kg=H_vap_kJ_kg * 1000.0,
                K_d=K_d,
                scenario=sc,
            )
            rows.append({
                "scenario": sc.value,
                "relief_load_kg_per_s": res.relief_load_kg_per_s,
                "orifice_area_cm2": res.orifice_area_m2 * 1.0e4,
                "P_set_bar": res.setpoints.P_set_Pa / 1.0e5,
                "P_full_lift_bar": res.setpoints.P_full_lift_Pa / 1.0e5,
                "P_back_max_bar": res.setpoints.P_back_max_Pa / 1.0e5,
                "notes": res.notes,
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "scenario": sc.value,
                "relief_load_kg_per_s": float("nan"),
                "orifice_area_cm2": float("nan"),
                "P_set_bar": float("nan"),
                "P_full_lift_bar": float("nan"),
                "P_back_max_bar": float("nan"),
                "notes": f"failed: {exc}",
            })

    st.subheader("Results")
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV", csv, "relief_sizing.csv", "text/csv",
            key="relief_csv",
        )
    except ImportError:
        # Pandas missing — fall back to JSON.
        st.json(rows)

    st.caption(
        "ASME Sec VIII UG-125 allows 10 % accumulation (P_full_lift = "
        "1.10 P_design) for non-fire scenarios and 21 % for fire "
        "(UG-125(c)). API 521 §5.15 fire-case heat input: "
        "Q = 21 000 · F · A_wetted^0.82 [W]; F = 1.0 for a bare vessel."
    )


__all__ = ["_page_relief_sizing"]
