"""Pinch Preview page — composite curves and minimum-utility targets.

Builds hot / cold composite curves from the heat exchangers, heaters,
and coolers in the last-solved flowsheet, computes the minimum hot and
cold utility duties at the user's chosen ΔT_min, and locates the pinch
temperature on the temperature-enthalpy diagram.

v1.6.1 P.7b — was on the v1.6 stretch-goal list (Workstream G, pinch
analysis / HEN synthesis) and never shipped. This page lands a minimum
viable composite-curve generator inside the existing UI so the
capability is visible; full HEN synthesis (stream-matching, MILP) is a
v1.7 candidate.

Methodology: standard pinch problem-table algorithm (Linnhoff & Hindmarsh
1983). Hot streams are tagged by ``Q < 0`` (releases heat); cold streams
by ``Q > 0`` (absorbs heat). For each unit we read ``T_in``, ``T_out``,
and ``Q`` from the last solve; CP = |Q| / |ΔT|.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from pse_ecosystem.ui.shared.state import _init_state
from pse_ecosystem.ui.shared.streamlit_loader import _require_streamlit


@dataclass
class _HotColdStream:
    unit_id: str
    kind: str          # "hot" | "cold"
    T_in_K: float
    T_out_K: float
    Q_W: float         # absolute value
    CP_W_per_K: float  # |Q| / |T_in − T_out|


def _extract_streams(flowsheet, x: Dict[str, float]) -> List[_HotColdStream]:
    """Pull (T_in, T_out, Q) from each thermally active unit.

    Heuristic: any unit whose variable list contains both a ``T_in`` /
    ``T_out`` pair AND a ``Q`` (or ``Q_duty``) variable is treated as a
    hot or cold stream. Direction is inferred from the duty sign and the
    temperature change.
    """
    streams: List[_HotColdStream] = []
    for unit in flowsheet.units:
        uid = unit.unit_id
        # Find a Q variable
        q_keys = [
            k for k in x if k.startswith(f"{uid}.") and (
                k.endswith(".Q") or k.endswith(".Q_duty") or k.endswith(".Q_heater")
                or k.endswith(".Q_cooler") or k.endswith(".Q_intercool")
            )
        ]
        if not q_keys:
            continue
        # Take the first match (compressors have Q_intercool too)
        Q = sum(x.get(k, 0.0) for k in q_keys)
        # Find inlet/outlet T
        t_in_k = next((k for k in x if k.startswith(f"{uid}.") and k.endswith(".inlet.T")), None)
        t_out_k = next((k for k in x if k.startswith(f"{uid}.") and k.endswith(".outlet.T")), None)
        if t_in_k is None or t_out_k is None:
            continue
        T_in = x[t_in_k]
        T_out = x[t_out_k]
        dT = T_out - T_in
        if abs(dT) < 1e-3 or abs(Q) < 1e-3:
            continue
        kind = "cold" if dT > 0 else "hot"
        # If the unit is e.g. a cooler with Q signed-negative, |dT| × CP must equal |Q|.
        CP = abs(Q) / max(abs(dT), 1e-6)
        streams.append(_HotColdStream(
            unit_id=uid, kind=kind,
            T_in_K=T_in, T_out_K=T_out, Q_W=abs(Q), CP_W_per_K=CP,
        ))
    return streams


def _problem_table(
    streams: List[_HotColdStream], dT_min_K: float,
) -> Tuple[List[float], List[float], List[float], float, float, float]:
    """Linnhoff problem-table — returns hot/cold cumulative enthalpies on
    the shifted temperature axis and pinch + utility targets."""
    if not streams:
        return [], [], [], 0.0, 0.0, 0.0
    # Shift hot streams down by ΔT_min/2, cold streams up by ΔT_min/2 to
    # construct a common shifted temperature axis.
    shift = dT_min_K / 2.0
    intervals: List[float] = []
    for s in streams:
        T_hi = max(s.T_in_K, s.T_out_K)
        T_lo = min(s.T_in_K, s.T_out_K)
        if s.kind == "hot":
            T_hi -= shift
            T_lo -= shift
        else:
            T_hi += shift
            T_lo += shift
        intervals.extend([T_hi, T_lo])
    Ts = sorted(set(intervals), reverse=True)
    # Net heat in each interval = Σ CP_cold − Σ CP_hot times ΔT (positive =
    # cold-dominated → utility needed; negative = hot-dominated → surplus).
    deficits: List[float] = []
    for i in range(len(Ts) - 1):
        T_hi, T_lo = Ts[i], Ts[i + 1]
        net = 0.0
        for s in streams:
            T_hot_eq = max(s.T_in_K, s.T_out_K) - (shift if s.kind == "hot" else -shift)
            T_cold_eq = min(s.T_in_K, s.T_out_K) - (shift if s.kind == "hot" else -shift)
            if T_cold_eq <= T_lo and T_hot_eq >= T_hi:
                if s.kind == "cold":
                    net += s.CP_W_per_K * (T_hi - T_lo)
                else:
                    net -= s.CP_W_per_K * (T_hi - T_lo)
        deficits.append(net)
    # Cumulative cascade — make the minimum cumulative ≥ 0 → hot utility.
    cum = [0.0]
    for d in deficits:
        cum.append(cum[-1] + d)
    Q_h_min = max(0.0, -min(cum))  # external heat to keep cascade non-negative
    feasible = [c + Q_h_min for c in cum]
    Q_c_min = feasible[-1]
    # Pinch temperature = location of zero in the feasible cascade
    pinch_T = Ts[feasible.index(min(feasible, key=abs))]
    return Ts, cum, feasible, Q_h_min, Q_c_min, pinch_T


def _composite_curve(
    streams: List[_HotColdStream], kind: str,
) -> Tuple[List[float], List[float]]:
    """Cumulative T-vs-H curve for hot or cold streams (no ΔT shift)."""
    relevant = [s for s in streams if s.kind == kind]
    if not relevant:
        return [], []
    temps = sorted({s.T_in_K for s in relevant} | {s.T_out_K for s in relevant})
    H = []
    for T in temps:
        h_at_T = 0.0
        for s in relevant:
            T_hi = max(s.T_in_K, s.T_out_K)
            T_lo = min(s.T_in_K, s.T_out_K)
            if T <= T_lo:
                continue
            T_eff = min(T, T_hi)
            h_at_T += s.CP_W_per_K * (T_eff - T_lo)
        H.append(h_at_T)
    return temps, H


def _page_pinch_preview():
    st = _require_streamlit()
    _init_state(st)

    st.title("Pinch Preview — composite curves & utility targets")
    st.caption(
        "Hot / cold composite curves and minimum-utility targets from the "
        "thermally active units in the last solve. v1.6.1 preview — full "
        "HEN synthesis (stream matching, MILP) is on the v1.7 roadmap."
    )

    flowsheet = st.session_state.get("last_flowsheet")
    last_result = st.session_state.get("last_result")
    if flowsheet is None or last_result is None or not getattr(last_result, "x", None):
        st.info(
            "No solved flowsheet in session. Solve a flowsheet on the "
            "**Flowsheet Builder** page first."
        )
        return

    streams = _extract_streams(flowsheet, dict(last_result.x))
    if not streams:
        st.warning(
            "No thermally active units detected. Add at least one heater, "
            "cooler, or heat exchanger to the flowsheet and re-solve."
        )
        return

    st.success(
        f"Detected {len(streams)} thermal stream(s): "
        f"{sum(1 for s in streams if s.kind == 'hot')} hot, "
        f"{sum(1 for s in streams if s.kind == 'cold')} cold."
    )

    dT_min = st.slider(
        "ΔT_min [K]", min_value=1.0, max_value=50.0, value=10.0, step=1.0,
    )

    Ts, cascade, feasible, Q_h_min, Q_c_min, T_pinch = _problem_table(streams, dT_min)

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Min hot utility [kW]", f"{Q_h_min / 1000.0:,.2f}")
    col_b.metric("Min cold utility [kW]", f"{Q_c_min / 1000.0:,.2f}")
    col_c.metric("Pinch T [K]", f"{T_pinch:,.1f}" if Ts else "n/a")

    st.divider()
    st.subheader("Stream table")
    try:
        import pandas as pd
        df = pd.DataFrame([
            {
                "unit": s.unit_id, "kind": s.kind,
                "T_in_K": s.T_in_K, "T_out_K": s.T_out_K,
                "Q_kW": s.Q_W / 1000.0, "CP_kW_per_K": s.CP_W_per_K / 1000.0,
            }
            for s in streams
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    except ImportError:
        st.write([s.__dict__ for s in streams])

    st.subheader("Composite curves")
    try:
        import plotly.graph_objects as go
        T_hot, H_hot = _composite_curve(streams, "hot")
        T_cold, H_cold = _composite_curve(streams, "cold")
        if T_hot or T_cold:
            fig = go.Figure()
            if T_hot:
                fig.add_trace(go.Scatter(
                    x=[h / 1000.0 for h in H_hot], y=T_hot,
                    mode="lines+markers", name="Hot composite",
                    line=dict(color="red"),
                ))
            if T_cold:
                # Shift cold curve so it sits ΔT_min above the pinch
                fig.add_trace(go.Scatter(
                    x=[h / 1000.0 + Q_h_min / 1000.0 for h in H_cold],
                    y=T_cold,
                    mode="lines+markers", name="Cold composite",
                    line=dict(color="blue"),
                ))
            fig.update_layout(
                xaxis_title="Enthalpy [kW]", yaxis_title="Temperature [K]",
                height=500,
            )
            st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.caption("Plotly not installed — composite plot unavailable.")


__all__ = ["_page_pinch_preview"]
