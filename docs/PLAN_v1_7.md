# PSE Ecosystem v1.7 — Energy Integration + Decision Under Uncertainty

## Context

v1.6 closed the thermo ladder (PR / SRK / NRTL / Wilson / UNIQUAC + generic
flash), audited every unit in the catalogue, added 10 new industrial unit
models, introduced sizing modes (Design / Rating), built the dynamics + API
520 / 521 relief sizing framework, and shipped a parity dashboard with Aspen
interop. Test suite 512 → 998 passing, zero regressions.

v1.7 builds on that foundation to deliver the **two highest-value workflows
that EPCs and consultancies expect from a process simulator beyond
steady-state mass balance**:

1. **Energy + mass integration** — heat-pinch, HEN synthesis, water- and
   hydrogen-pinch networks. The #1 industrial use case for a simulator
   after closure; routinely saves 15–30 % of utility cost.
2. **Decision under uncertainty** — Monte Carlo, Sobol indices,
   multi-objective Pareto optimisation. Turns "the NPV is $42 M" into
   "the NPV is $42 M with 90 % CI ± $11 M, dominated by gas-price
   uncertainty (Sobol 0.38)". Industrial decision-makers cannot sign off
   without this.

Plus closes two known thermo / control gaps and starts a digital-twin
on-ramp via live data interop.

**Targets**: 1200+ tests passing · 5 new case studies (energy
integration, water network, MEA with PR-NRTL, NH3 loop with feed
uncertainty, PID-controlled CSTR) · backward-compatible with all v1.5.3
and v1.6 flowsheet JSON.

---

## Scope Overview (7 workstreams)

| # | Workstream | Weeks | Risk |
|---|---|---|---|
| H | Heat-integration pinch + HEN synthesis | 1–3 | Med |
| I | Mass-integration (water + H₂ networks) | 2–4 | Med |
| J | Uncertainty quantification (MC + Sobol + LHS) | 4–5 | Low |
| K | Multi-objective optimisation (Pareto / ε-constraint) | 5–6 | Med |
| L | PR-NRTL hybrid + 3-phase VLLE flash | 7 | Med |
| M | Process control toolkit (PI/PID + linearised MPC) | 8–10 | Med |
| N | Cross-cutting (UI, docs, 5 case studies) | 11–12 | Low |

> **Realism note**: 12-week sprint. Track J (UQ) and Track L (PR-NRTL)
> are foundational for the case studies in N — keep them on the critical
> path. OPC UA / Modbus gateway and surrogate-model layer are stretch
> goals; cut from N first if slipping.

---

## Workstream H — Heat-Integration Pinch + HEN Synthesis

**New module**: `pse_ecosystem/integration/`

```
pse_ecosystem/integration/
  pinch.py                 # Composite + grand composite curves; Q_h_min / Q_c_min
  hen_synthesis.py         # Linnhoff-Hindmarsh + Yee-Grossmann LP / NLP
  stream_data.py           # Auto-extract hot/cold streams from flowsheet HX units
```

**Approach**:
- ``StreamData`` dataclass with T_supply, T_target, mCp, name, type (hot/cold).
- ``pinch_targets(streams, dT_min)`` → ``PinchResult(Q_h_min, Q_c_min, T_pinch, composite_curves)``.
- ``hen_synthesis(streams, dT_min, U_table)`` → list of ``MatchedExchanger``
  proposals with required A, ΔT_LMTD, and CAPEX estimate (reuses SSLW).
- ``extract_streams_from_flowsheet(fs)`` walks the flowsheet's HX units
  and emits the stream list automatically; users can override with manual
  ``StreamData`` objects.

**Validation case**:
- Linnhoff (1979) ammonia-plant 4-stream textbook benchmark — Q_h_min
  exact, HEN cost within 5 % of published.

**UI**: new "Pinch" page — composite curves + grand composite (Plotly),
HEN matrix table, energy-savings vs base-case bar chart.

---

## Workstream I — Mass-Integration (Water + Hydrogen Networks)

**New modules**: `pse_ecosystem/integration/mass_pinch.py`, `water_network.py`

**Approach** (mirrors heat-pinch but on concentrations / purity):
- Water-pinch: Wang & Smith (1994) source-sink composite curves with
  contaminant concentrations.
- Hydrogen-pinch: Alves & Towler (2002) — same algorithm with hydrogen
  purity instead of contaminants.
- ``MassPinchResult(F_freshwater_min, F_wastewater_min, F_h2_min,
  source_sink_matches)``.

**Validation case**:
- Wang-Smith (1994) Example 1 — refinery water network, 4 sources × 4
  sinks; target = 90 t/h fresh water (published).

---

## Workstream J — Uncertainty Quantification

**New module**: `pse_ecosystem/uq/`

```
pse_ecosystem/uq/
  sampling.py              # uniform / normal / triangular / LHS / Sobol seq
  monte_carlo.py           # Run flowsheet N times; collect outputs
  sensitivity.py           # First-order + total Sobol indices via Saltelli
  reporting.py             # Quantile / CI / tornado / cobweb plots
```

**Approach**:
- ``UncertainParam(name, distribution, args)`` dataclass.
- ``run_monte_carlo(flowsheet, params, n_samples, output_vars)`` →
  ``MCResult(samples, outputs, statistics)``.
- ``sobol_indices(flowsheet, params, output_var, n_base=1024)`` —
  Saltelli's scheme; returns first-order S_i and total S_T_i per param.
- LHS via scipy.stats.qmc.

**Validation case**:
- 5-parameter Ishigami function (analytic Sobol indices); ours within 5 %
  of S_i = 0.314, 0.443, 0.0 at n_base = 1024.

**UI**: new "Uncertainty" page — distribution selector per variable,
output histograms, tornado chart for sensitivity.

---

## Workstream K — Multi-Objective Optimisation

**New module**: `pse_ecosystem/optimization/multi_objective.py`

**Approach**:
- ``epsilon_constraint(objectives, constraints, eps_grid)`` — generates
  the Pareto front by fixing all-but-one objective as ε-constraint and
  scanning ε. Uses the existing Layer 2 LP / NLP for each ε.
- ``weighted_sum(objectives, weights)`` — for log-linear trade-offs.
- ``ParetoFront`` dataclass with dominated-point filter and decision-
  maker selectors (lexicographic, knee-point, TOPSIS).

**Validation case**:
- Bi-objective minimise (TAC, CO₂-equiv) on the v1.6 SMR case study;
  reports the 10-point Pareto front + chosen knee-point trade-off.

---

## Workstream L — PR-NRTL Hybrid + 3-Phase VLLE Flash

**Closes a v1.6 stub** — ``pr_nrtl`` was reserved but raised
``NotImplementedError``. Industrial-fidelity MEA absorber, sour-gas, and
amine systems need it.

**Files**:
- ``pse_ecosystem/models/properties/pr_nrtl.py`` — combines PR for vapor-
  phase fugacity with NRTL γ for liquid; K_i = γ_i^L × P_sat_i × φ_i^L,sat
  / (φ_i^V × P).
- ``pse_ecosystem/models/properties/flash_vlle.py`` — three-phase VLLE
  flash (Michelsen stability analysis + Rachford-Rice extension for two
  liquid phases).

**Validation case**:
- IEAGHG MEA absorber benchmark — re-run with PR-NRTL + VLLE; target
  <3 % MAPE on rich-amine CO₂ loading.

---

## Workstream M — Process Control Toolkit

**New modules**: `pse_ecosystem/control/`

```
pse_ecosystem/control/
  controllers.py           # PI / PID / on-off; anti-windup
  tuning.py                # IMC / Ziegler-Nichols / Cohen-Coon
  closed_loop.py           # Wraps DynamicSimulator with controller in the loop
  mpc.py                   # Linearised state-space MPC (ABCD via Jacobian)
  process_identification.py # Step / pulse / PRBS → FOPDT model fit
```

**Approach**:
- ``Controller`` interface with ``output(t, error)`` method.
- ``ClosedLoopSim`` wraps the v1.6 ``DynamicSimulator`` and routes
  controlled-variable feedback to manipulated-variable inputs.
- ``MPC`` builds an A·B·C·D state-space from the flowsheet's numerical
  Jacobian at steady state; horizon-N receding-horizon optimisation via
  scipy.optimize.

**Validation case**:
- Closed-loop CSTR temperature control with feed-temperature step
  disturbance; PI controller IAE < 200 K·s after Ziegler-Nichols tuning.

---

## Workstream N — Cross-Cutting

- **UI**: Industrial Mode gains "Pinch", "Uncertainty", "Control" pages.
- **Tests**: target ≥1200 passing (currently 998). New regression files:
  ``test_pinch.py``, ``test_hen_synthesis.py``, ``test_water_pinch.py``,
  ``test_uq.py``, ``test_pareto.py``, ``test_pr_nrtl.py``,
  ``test_vlle_flash.py``, ``test_controllers.py``, ``test_mpc.py``.
- **Docs**: ``docs/USER_MANUAL.md`` extended with v1.7 pages;
  ``docs/INDUSTRIAL_GUIDE.md`` adds energy-integration + UQ walkthroughs;
  ``docs/VALIDATION.md`` adds 5 new case-study results.
- **Backward compatibility**: every v1.5.3 and v1.6 flowsheet JSON loads
  in v1.7 unchanged; default property method, sizing mode, dynamics, and
  control loops all remain off by default.

---

## Critical Files & Patterns to Reuse

- ``pse_ecosystem/safety/`` — pattern for the new ``integration/``,
  ``uq/``, ``optimization/``, ``control/`` sub-packages (pure-Python,
  post-solve, no Layer 2 imports).
- ``pse_ecosystem/dynamics/dae_solver.py`` — the ``ClosedLoopSim`` extends
  it with controller feedback.
- ``pse_ecosystem/models/properties/property_package.py`` — the
  PR-NRTL package slots into the factory registry the same way the v1.6
  packages do.
- ``pse_ecosystem/validation/parity.py`` — UQ output reporting reuses the
  same MAPE / RMSE / R² kernels.
- ``pse_ecosystem/ui/flowsheet_service.py`` — ``available_units_for_persona``
  + ``unit_categories_for_persona`` helpers gain new categories for
  controllers (visible only in Industrial mode).

---

## Sequencing (12-week sprint)

| Week | Primary | Secondary |
|---|---|---|
| 1–2 | H: Pinch targets + composite curves | J: Sampling backends |
| 3–4 | H: HEN synthesis + Linnhoff benchmark | I: Water-pinch math |
| 4–5 | J: Sobol + Monte Carlo + Ishikami validation | I: Hydrogen-pinch |
| 5–6 | K: Pareto / ε-constraint | J: UI Uncertainty page |
| 7 | L: PR-NRTL package + VLLE flash | K: Decision-maker selectors |
| 8–9 | M: Controllers + tuning + ClosedLoopSim | L: MEA case-study re-run |
| 10 | M: MPC stub + FOPDT identification | N: UI Pinch + Control pages |
| 11 | N: 5 case studies + docs | — |
| 12 | N: Hardening + test backfill + release | — |

---

## Stretch Goals (cut first if slipping)

1. **OPC UA / Modbus gateway** — ``pse_ecosystem/connectors/`` for live-
   plant tag read / write; digital-twin on-ramp.
2. **Surrogate-model layer** — Kriging / neural-network surrogates for
   slow units (Gibbs reactor, PFR with stiff kinetics), 10–100× faster
   MC and Pareto scans.
3. **Reactive distillation** — combined TrayColumn + ReactionSet unit;
   captures esterification / etherification (MTBE) processes.
4. **Membrane reactor** — combines MembraneModule + PFR for water-gas
   shift with H₂ in-situ removal.
5. **Population-balance crystalliser** — particle-size distribution
   instead of single-yield CrystallizerHF.
6. **Stochastic programming** — UQ + optimisation in one shot; design
   under uncertainty rather than just analysis.

---

## Verification

End-to-end checks before tagging v1.7:

1. ``pytest`` → 1200+ tests pass.
2. ``python -m pse_ecosystem.ui`` launches Streamlit; manually run all 5
   new case studies; export Excel; verify each result panel.
3. Load 5 v1.5.3 / v1.6 flowsheet JSON files unchanged → identical KPIs
   (back-compat regression).
4. Pinch targets for Linnhoff (1979) match published within 0.1 K and
   0.5 kW for Q_h_min / Q_c_min.
5. Sobol indices for Ishigami function within 5 % of analytical.
6. Pareto front on bi-objective SMR (TAC, CO₂) returns ≥ 10 non-
   dominated points spanning the feasible region.
7. PR-NRTL MEA absorber MAPE < 3 % on rich-amine loading vs IEAGHG.
8. Closed-loop CSTR with PI controller IAE within 10 % of Ziegler-
   Nichols target on a standard step-disturbance test.

---

## Why This Approach

- **Industrial value first** (H + I + J + K in weeks 1–6) — these four
  workstreams alone justify the release for EPC / consultancy users,
  even before the thermo and control extras land.
- **Foundation-closing** (L in week 7) — clears the largest known v1.6
  thermo gap before the MEA case study runs in week 8–9.
- **Dynamics activation** (M in weeks 8–10) — the v1.6 dynamics
  framework only becomes useful once controllers are in the loop;
  v1.7 turns it from a capability into a workflow.
- **Decision-grade rigor** — v1.6 gave you "the answer is X"; v1.7 gives
  you "the answer is X ± Y at confidence Z, dominated by parameter P",
  which is what every approval-stage gate review actually asks for.
- **Stretch goals on the cut line** — OPC UA, surrogates, reactive
  distillation, population balance preserve long-horizon ambition
  without risking the critical path.

---

## What v1.7 Does NOT Cover

Held over to v1.8+ to keep this sprint achievable:

- **Real-time optimisation (RTO)** — needs the v1.7 controllers + OPC UA
  + closed-loop Pareto, then the RTO layer; too much for one release.
- **Reactor network synthesis** (attainable-region method) — speciality
  problem with a small audience.
- **Multi-scale modelling** (CFD-informed efficiencies) — requires
  external CFD toolchain integration.
- **Solid handling** (size reduction, screening, pneumatic conveying) —
  large unit-library addition; defer to a dedicated v1.8 solids-track.
- **Cybersecurity / OT-IT layer** — once OPC UA lands, the security
  hardening is a separate workstream.
