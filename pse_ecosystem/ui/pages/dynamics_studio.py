"""Dynamics Studio page — transient simulation on top of a steady-state solve.

Surfaces ``pse_ecosystem.dynamics.dae_solver.DynamicSimulator`` +
``Perturbation`` (v1.6 E.3, E.4) through a Streamlit form. The user
picks an input variable from the last-solved flowsheet, adds a step /
ramp / pulse / sinusoid perturbation on it, runs the integrator, and
gets a Plotly time-series of every dynamic state variable a unit
contributes.

v1.6.1 P.7c — completes the audit-flagged "feature exists but no UI"
gap for the dynamics subpackage. Most shipped units don't override
``dynamic_residuals`` yet, so the page detects an empty-state flowsheet
and displays guidance rather than running a no-op simulation.
"""

from __future__ import annotations

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit


def _page_dynamics_studio():
    st = _require_streamlit()
    _init_state(st)

    st.title("Dynamics Studio")
    st.caption(
        "Transient simulation around the last steady-state solve. Pick an "
        "input variable, add a perturbation, integrate, plot."
    )

    flowsheet = st.session_state.get("last_flowsheet")
    last_result = st.session_state.get("last_result")
    if flowsheet is None or last_result is None:
        st.info(
            "No solved flowsheet in session. Run a flowsheet on the "
            "**Flowsheet Builder** page first — the steady-state solution "
            "becomes the initial condition for the dynamic study here."
        )
        return

    from pse_ecosystem.dynamics.dae_solver import DynamicSimulator
    from pse_ecosystem.dynamics.perturbation import Perturbation

    # Build the simulator and check whether anything in the flowsheet
    # actually contributes dynamic state.
    sim = DynamicSimulator(
        units=list(flowsheet.units),
        x_state=dict(last_result.x),
    )

    if not sim._state_vars:
        st.warning(
            "None of the units in this flowsheet override "
            "``BaseUnit.dynamic_residuals`` — the simulator has no state "
            "to integrate. Dynamics support is opt-in per unit (v1.6 E.3); "
            "v1.7 Workstream M will add first-class dynamic CSTR / Flash "
            "holdup models. Until then, this page is a forward-looking "
            "scaffold."
        )
        st.write("**Detected state variables**: *(none)*")
        return

    st.success(
        f"Detected {len(sim._state_vars)} dynamic state variable(s): "
        f"{', '.join(sim._state_vars[:6])}"
        + ("…" if len(sim._state_vars) > 6 else "")
    )

    st.subheader("Perturbation")
    col_a, col_b = st.columns(2)
    with col_a:
        shape = st.selectbox(
            "Shape", ["step", "ramp", "pulse", "sinusoid"], key="dyn_shape",
        )
        target_var = st.selectbox(
            "Target variable", sorted(sim.x_state.keys()), key="dyn_target",
            help="An algebraic input the perturbation will drive over time.",
        )
        t0 = st.number_input(
            "t₀ [s] (start of perturbation)", min_value=0.0, value=10.0,
        )
    with col_b:
        magnitude = st.number_input(
            "Magnitude / amplitude", value=1.0, format="%.6g",
        )
        if shape == "ramp":
            slope = st.number_input("Slope per second", value=0.1, format="%.4g")
            t_end = st.number_input("Ramp end [s]", value=30.0)
        elif shape == "pulse":
            duration = st.number_input("Pulse duration [s]", value=5.0, min_value=0.1)
        elif shape == "sinusoid":
            period = st.number_input("Period [s]", value=4.0, min_value=0.1)
            phase = st.number_input("Phase [rad]", value=0.0)

    baseline = sim.x_state.get(target_var, 0.0)
    if shape == "step":
        pert = Perturbation.step(t0=t0, magnitude=magnitude, baseline=baseline)
    elif shape == "ramp":
        pert = Perturbation.ramp(
            t0=t0, slope=slope, baseline=baseline, t_end=t_end,
        )
    elif shape == "pulse":
        pert = Perturbation.pulse(
            t0=t0, duration=duration, magnitude=magnitude, baseline=baseline,
        )
    else:  # sinusoid
        pert = Perturbation.sinusoid(
            amplitude=magnitude, period_s=period, baseline=baseline,
            phase_rad=phase,
        )
    sim.add_perturbation(target_var, pert)

    st.subheader("Integrator")
    col_c, col_d = st.columns(2)
    with col_c:
        t_end_sim = st.number_input(
            "Simulation time [s]", min_value=1.0, value=120.0, step=10.0,
        )
        dt_output = st.number_input(
            "Output Δt [s]", min_value=0.01, value=1.0, step=0.5,
        )
    with col_d:
        method = st.selectbox(
            "Solver", ["BDF", "Radau", "LSODA", "RK45"], key="dyn_method",
        )
        sim.method = method

    if not st.button("Integrate", key="dyn_run"):
        return

    with st.spinner(f"Integrating with {method}…"):
        result = sim.integrate(
            t_span=(0.0, t_end_sim), dt_output=dt_output,
        )

    if not result.converged:
        st.error(f"Solver did not converge: {result.message}")
        return

    st.success(
        f"Integrated to t = {result.t_s[-1]:.1f} s in {len(result.t_s)} "
        f"output steps. Fired {len(result.fired_events)} event(s)."
    )

    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        for var, trace in result.y_history.items():
            fig.add_trace(go.Scatter(
                x=result.t_s, y=trace, mode="lines", name=var,
            ))
        fig.update_layout(
            xaxis_title="t [s]", yaxis_title="state value",
            height=500, legend_orientation="h",
        )
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.dataframe(
            {"t_s": result.t_s.tolist()}
            | {k: v.tolist() for k, v in result.y_history.items()}
        )


__all__ = ["_page_dynamics_studio"]
