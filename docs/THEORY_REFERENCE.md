# Theory Reference

> **v1.5.2** — The mathematical and process-systems-engineering
> underpinnings of the PSE Ecosystem. For the high-level architecture see
> [`ARCHITECTURE.md`](ARCHITECTURE.md); for code-level details see
> [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md); for end-user usage see
> [`USER_MANUAL.md`](USER_MANUAL.md).

---

## 0. v1.4.0 — Numerical foundations relevant to the UMS

The Unit Management System (v1.4.0) lives at Layer 1 and is invisible to
the solver. Every equation in this document is stated in SI units (K, Pa,
kg/s, J, W) because that is what the Layer-3 unit models actually
manipulate when they evaluate residuals and Jacobians. The display units
exposed to the end user (°C, atm, kW, t/h, …) are converted to the native
intake unit at the UI boundary, and each unit model then performs its own
internal conversion to SI before doing any math.

Why this matters numerically:

- **Jacobian scaling.** When variables span very different magnitudes
  (e.g. P ≈ 5×10⁶ Pa next to T ≈ 700 K next to F ≈ 1 kg/s), the SLP
  driver's LP subproblem becomes ill-conditioned. Keeping the entire
  computation in SI avoids drift in column scales.
- **Trust-Region radii.** The TR driver maintains a single scalar radius Δ
  on the step in `x`. Mixed units (some entries in K, others in °C) would
  collapse the radius to whichever variable had the largest absolute
  magnitude. SI-only internals keep Δ meaningful across variables.
- **Progressive tightening (v1.4.0 default ON).** The loose-to-tight
  schedule (`eps_x` 1e-3 → 1e-7, `eps_f` 1e-3 → 1e-7) assumes consistent
  units throughout. Mixing display units mid-solve would invalidate the
  tightening schedule.

---

## 1. Scope of the v0 Theory

### 1.1 Steady-state, single-period, deterministic

Every unit, every flowsheet, and every optimisation run in v0 assumes:

- **Steady state.** No accumulation terms, no transient response.
- **Single period.** One representative operating point — no time
  index, no diurnal variation, no seasonality.
- **Deterministic.** Fixed parameters; no probability distributions,
  scenario trees, or robust-optimisation uncertainty.

These assumptions collapse mass and energy balances into algebraic
equations of the form `f(x) = 0`, which is exactly what the Handshake
Protocol is built around.

### 1.2 Deliberately omitted from v0

The toy models are intentionally simplified placeholders. v0 does
**not** include:

- Reaction kinetics (Arrhenius, residence-time distributions).
- Electrochemistry (Butler–Volmer, overpotentials, cell-stack physics).
- Heat integration / utility networks.
- Pressure / temperature distinct as decision variables.
- Phase equilibria, separation column rigour.
- Component-by-component mass balance (we track mass flows of named
  streams, not full mole-fraction matrices).

The architecture supports all of these; v0 simply hasn't implemented
them yet. See [`DEVELOPER_GUIDE.md` §8](DEVELOPER_GUIDE.md#8-future-roadmap)
for the roadmap.

---

## 2. Mass & Energy Balance Conventions

### 2.1 General balance form

For a unit operation at steady state:

```
Σ (inputs)  −  Σ (outputs)  +  Σ (generation)  −  Σ (consumption)  =  0
```

In v0 we collapse this into a small set of algebraic residuals
`f_i(x) = 0`, where each residual represents one balance the unit
asserts against its variables.

### 2.2 v0 simplification — aggregated balances

Each unit exposes only the variables it cares about (electricity in,
hydrogen out, feed in, etc.) — not full component balances. A toy
electrolyser, for instance, has a single residual relating electricity
to hydrogen output. A toy gasifier has two residuals: one for hydrogen
yield and one for steam stoichiometry.

This is a fully legitimate level of abstraction for early-stage
techno-economic studies; it is not a substitute for an Aspen-grade
balance.

### 2.3 Steady-state implication

No mass or energy *accumulates*. The optimisation finds a single
operating point that satisfies every unit's residual simultaneously.

### 2.4 Sign convention for residuals

Residuals are written so that **the satisfied state is `f(x) = 0`**.
For example, the PEM relation `m_H2 = η · P_elec` becomes the residual

```
r(x) = m_H2  −  η · P_elec
```

The Handshake Protocol's `LinearizedModel.f0` field carries `r(x_k)`
evaluated at the linearisation point.

---

## 3. Toy PEM Electrolyser — Unit Model

Code: [`pse_ecosystem/models/electrolysis/pem_toy.py`](../pse_ecosystem/models/electrolysis/pem_toy.py).

### 3.1 Variables

| Variable name | Symbol | Units | Range |
|---|---|---|---|
| `pem.electricity_kW` | P_elec | kW | [0, capacity_kW] |
| `pem.h2_kg_per_h` | m_H2 | kg/h | [0, η · capacity_kW] |

Where `pem` is the unit's `unit_id` — multiple PEM stacks in the same
flowsheet use distinct ids and therefore disjoint variable namespaces.

### 3.2 The single linear residual

```
r(x)  =  m_H2  −  η · P_elec   =   0
```

This is the entirety of the PEM physics in v0: one constraint, one
parameter (η). No load-dependent efficiency, no degradation, no warm-up
losses.

### 3.3 Default efficiency η = 0.018 kg/kWh

Equivalently `≈ 55 kWh / kg H₂`. Where this comes from:

- The thermoneutral voltage of water electrolysis is 1.481 V; HHV-based
  energy demand is 39.4 kWh/kg H₂.
- A modern PEM stack runs at ~80 % efficiency on an HHV basis, putting
  practical SEC (specific energy consumption) at ~50 kWh/kg.
- Adding balance-of-plant losses (rectifier, compression, water
  treatment) brings system-level SEC to ~55 kWh/kg.
- Inverting: 1 / 55 ≈ 0.0182 kg/kWh, which we round to 0.018.

This is a *toy* default optimistically aligned with current
best-in-class systems. Override `PEMToyParams.eta_kg_per_kWh` for your
own scenarios.

### 3.4 Bounds and capacity treatment

Capacity is a **parameter**, not a decision variable, in v0:

```
0  ≤  P_elec  ≤  capacity_kW
0  ≤  m_H2    ≤  η · capacity_kW
```

The optimisation chooses the operating point at fixed installed
capacity. Capacity sizing as a decision is deferred to the Mode-2 MILP
(via `TechnologyChoice.fixed_cost`) or to a future v1 enhancement.

### 3.5 Cost coefficients

The unit contributes to the global linear objective via a single
coefficient on the electricity variable:

```
objective_term[P_elec]  =  electricity_price_per_kWh  ×  operating_hours_per_year
                        =  0.05  ×  8000
                        =  400 £ / (kW · yr)         (default)
```

CAPEX is *not* part of the LP/MILP objective when capacity is a
parameter; it is constant across all feasible operating points.

### 3.6 KPI definitions

```
annual_h2_kg     =  m_H2  ×  hours_per_year
annual_opex_GBP  =  P_elec  ×  £elec  ×  hours_per_year
annual_capex_GBP =  capex_annual_per_kW  ×  capacity_kW
LCOH_GBP_per_kg  =  (annual_capex_GBP + annual_opex_GBP)  /  annual_h2_kg
```

These are computed in `PEMToy.kpis()` and surfaced in `SolveResult.kpis`.

---

## 4. Toy Gasifier — Unit Model

Code: [`pse_ecosystem/models/gasification/gasifier_toy.py`](../pse_ecosystem/models/gasification/gasifier_toy.py).

### 4.1 Variables

| Variable name | Symbol | Units | Range |
|---|---|---|---|
| `gasifier.feed_kg_per_h`  | m_feed   | kg/h | [0, feed_max] |
| `gasifier.h2_kg_per_h`    | m_H2     | kg/h | [0, a · feed_max] |
| `gasifier.steam_kg_per_h` | m_steam  | kg/h | [0, c · feed_max] |

### 4.2 Quadratic yield residual

```
r₁(x)  =  m_H2  −  ( a · m_feed  −  b · m_feed² )   =   0
```

Reading the curve:

- At low throughput, yield is approximately `a · m_feed` (linear
  proportionality).
- At higher throughput, the `−b · m_feed²` term subtracts an off-design
  loss — yield-per-tonne falls as the unit is pushed.
- The maximum yield occurs at `m_feed* = a / (2b)`; beyond that, more
  feed produces *less* hydrogen. With defaults a=0.10, b=10⁻⁷, this
  peak is at m_feed* = 500 000 kg/h, far above the bound `feed_max =
  50 000`, so the bounded region is monotonically increasing.

This is a deliberately gentle non-linearity: small enough that a
textbook SLP trust region is not required, large enough that the
Successive-Linearization loop must run more than one iteration to
converge.

### 4.3 Linear steam residual

```
r₂(x)  =  m_steam  −  c · m_feed   =   0
```

A stoichiometric ratio: every kg of feed needs `c` kg of steam.
Default `c = 0.5` is loosely consistent with biomass gasification with
moderate steam-to-biomass ratios.

### 4.4 Default coefficients

| Symbol | Default | Units | Source / rationale |
|---|---|---|---|
| a | 0.10 | kg H₂ / kg feed | A round 10 % yield representative of biomass gasification with shift. |
| b | 1.0 × 10⁻⁷ | kg H₂ / (kg feed)² | Picked to give a ~5 % yield droop at full design throughput. |
| c | 0.5 | kg steam / kg feed | Mid-range steam ratio. |
| feed_max | 50 000 | kg/h | Notional plant capacity. |

### 4.5 Cost coefficients

```
objective_term[m_feed]  = feed_price_per_kg   ×  hours_per_year  =  400 £ / (kg/h · yr)
objective_term[m_steam] = steam_price_per_kg  ×  hours_per_year  =  160 £ / (kg/h · yr)
```

Plus a fixed annual CAPEX of £5 000 000 added to the **MILP** objective
when the gasifier's technology binary is 1 (it is *not* added to a
Mode-1 LP because capacity is fixed in that path).

### 4.6 Trust-region radius

The gasifier sets `LinearizedModel.trust_region = 5000 kg/h`. This is
the unit's hint to the SLP driver that linearisations of the quadratic
yield are dependable within ±5 000 kg/h of any anchor point. The driver
multiplies this radius by its scalar `Δ` (adapted via the ρ ratio), and
the LP builder applies per-variable box constraints
`|x_v − x_anchor_v| ≤ trust_region · Δ` for variables owned by units
that supplied a hint.

In v0 `use_trust_region` defaults to `False`; the toy gasifier
converges fine without TR. The hint is preserved so that turning on TR
later is a one-line config change, not a model change.

---

## 5. Cost Model

### 5.1 Annualised CAPEX assumption

CAPEX in v0 is reported as an *annualised* quantity (£/yr). The toy
defaults bake in an implicit capital recovery factor; that factor is
**not exposed** as a parameter in v0. Future versions will let users
specify a discount rate r and asset life L and compute

```
CRF  =  r · (1 + r)^L  /  ((1 + r)^L − 1)
```

internally.

### 5.2 OPEX as a linear function of operating point

The platform requires every unit's `objective_contribution(x)` to
return a `Dict[str, float]` mapping variable names to linear cost
coefficients. The global objective is the sum:

```
J(x)  =  Σ_units  Σ_vars  c_v · x_v
```

where `c_v = objective_term[v]` is the unit's coefficient (typically
price × operating_hours_per_year for flow variables).

The platform's solver layer is **strictly linear** in v0 — costs that
are non-linear in the operating point would have to be split into
piecewise-linear segments or absorbed into a unit's residual via slack
variables.

### 5.3 LCOH formula

For a single hydrogen-producing unit:

```
LCOH  =  ( annual_capex  +  annual_opex )  /  annual_h2
```

Where:
- `annual_capex` is the annualised capital recovery (£/yr).
- `annual_opex` aggregates electricity, feed, steam, and any other
  variable cost (£/yr).
- `annual_h2` is hourly H₂ output × `operating_hours_per_year` (kg/yr).

Each unit defines this in its own `kpis()` method. For multi-unit
flowsheets, total LCOH is computed as

```
LCOH_total  =  Σ_units (annual_capex_u + annual_opex_u)  /  Σ_units annual_h2_u
```

(currently surfaced as the per-unit values; an aggregated total is on
the v1 list).

### 5.4 Fixed-cost contribution from MILP binaries

In Mode 2, each `TechnologyChoice` has a `fixed_cost` field added to
the objective when its binary is 1:

```
J(x, y)  =  Σ_v  c_v · x_v   +   Σ_i  fixed_cost_i · y_i
```

Use `fixed_cost` for annualised CAPEX of an entire technology selection
(e.g. £1 000 000 / yr to "have a PEM stack at all"). The flow-variable
coefficients still capture variable OPEX.

---

## 6. Optimisation Formulations

### 6.1 Mode 1 — LP form

Given a flowsheet of `U` units, with each unit producing a
linearisation `(x0, f0, J, bounds, c)` at the current operating point:

```
minimise           Σ_v  c_v · x_v
subject to         f0_u  +  J_u · ( x − x0_u )   =   0       for each unit u
                   x_a  −  x_b  =  0                          for each connection (a, b)
                   Σ_v  α_v · x_v  =  β                       for each extra equality
                   lb_v  ≤  x_v  ≤  ub_v                      for each variable v
                   |x_v − x_anchor_v|  ≤  trust_region_u · Δ  optional, when TR is on
```

When all units are linear (`is_exact = True` for every linearisation),
the LP is exact and one Pyomo solve returns the global optimum. When
any unit is non-linear, the LP is the linearised approximation at the
current iterate `x_k`, and the SLP loop iterates (see §7).

### 6.2 Mode 2 — MILP extension

In addition to the continuous variables `x_v`, introduce a binary
`y_i ∈ {0, 1}` per `TechnologyChoice`. Let

- `flow(i)` = the set of flow variables owned by tech i,
- `unit(i)` = the unit_id gated by tech i.

```
minimise           Σ_v  c_v · x_v   +   Σ_i  fixed_cost_i · y_i

subject to         (LP rows from §6.1, but with residual gating below)

flow gating:       −M_i · y_i   ≤   x_v   ≤   M_i · y_i      for v ∈ flow(i)

residual gating:   | (J_u · x  −  rhs_u_r) |   ≤   M_row · ( 1 − y_i )
                                                              for u = unit(i), each row r

at-least-one:      Σ_i  y_i   ≥   1

binarity:          y_i  ∈  {0, 1}
```

The residual gating is the v0 fix that makes Mode 2 well-posed: when
`y_i = 0` the unit's flow variables are forced to 0, and its residual
equation is *also* relaxed by `M_row · (1 − y_i)` so that
`J · 0 ≠ rhs` is not forced to be zero.

`M_row` is sized in the builder as

```
M_row  =  max( big_M,  |rhs|  +  ‖J_row‖₁ · big_M,  1 )
```

so the slack always covers the worst residual the linearisation can
produce inside the bound box.

---

## 7. Successive Linear Programming

### 7.1 Taylor expansion at x_k

For a non-linear unit with residual `f(x)`, the first-order Taylor
expansion at the current iterate `x_k` is

```
f(x)   ≈   f(x_k)  +  J(x_k) · ( x − x_k )
```

Setting the right-hand side to zero gives a linear approximation of the
true non-linear constraint. The SLP loop solves this LP, evaluates the
**true** non-linear residual at the LP solution, checks convergence, and
re-linearises if needed.

### 7.2 The SLP iteration loop

Pseudocode matching the implementation in
[`solvers/slp.py`](../pse_ecosystem/solvers/slp.py):

```
input:   flowsheet F, initial guess x_0, configuration C
output:  SolveResult

x_k       ← x_0
Δ         ← C.trust_region_init                   ( = 1.0 )
prev_kpi  ← +∞
last_obj  ← undefined

for k = 0 .. C.max_iter − 1:

    # ── Layer-3 round: linearise around x_k ────────────────────────
    L_k  ←  { unit.linearize( PrimalGuess(x_k, k) )  for unit in F.units }

    if k == 0  and  every L in L_k has L.is_exact == True:
        return single LP solve                            # short-circuit

    # ── Layer-2 round: build & solve the LP ─────────────────────────
    tr  ←  Δ if C.use_trust_region else 0
    M   ←  build_lp( L_k, F, x_anchor=x_k, tr_multiplier=tr )
    x_{k+1}, lp_obj  ←  pyomo_solve( M )                  # may raise

    if pyomo_solve infeasible:
        Δ  ←  max( Δ / 2,  C.trust_region_min )
        if Δ ≤ C.trust_region_min:
            return SolveResult( status=INFEASIBLE, ... )
        continue

    # ── Validate against TRUE non-linear physics ────────────────────
    r_true  ←  concat( unit.residual(x_{k+1})  for unit in F.units )
    kpi     ←  Σ  c_v · x_{k+1, v}                         # objective at new iterate

    # ── Convergence test (all three must hold) ──────────────────────
    step   ←  ‖ x_{k+1} − x_k ‖_∞  /  max(1, ‖x_k‖_∞)
    res    ←  ‖ r_true ‖_∞
    Δkpi   ←  | kpi − prev_kpi |  /  max(1, |prev_kpi|)

    if  step < eps_x  and  res < eps_f  and  Δkpi < eps_kpi:
        return SolveResult( status=CONVERGED, x=x_{k+1}, ... )

    # ── Trust-region update (predicted vs actual decrease) ──────────
    if last_obj is defined:
        ρ  ←  ( prev_kpi − kpi )  /  ( last_obj − lp_obj )
        if ρ < C.rho_shrink:  Δ ← max( Δ / 2,  C.trust_region_min )
        if ρ > C.rho_grow:    Δ ← min( Δ · 2,  C.trust_region_max )

    x_k       ← x_{k+1}
    prev_kpi  ← kpi
    last_obj  ← lp_obj

return SolveResult( status=MAX_ITER, ... )
```

### 7.3 Convergence criteria — what each catches

| Symbol | Default | Meaning |
|---|---|---|
| ε_x | 1 × 10⁻⁴ | Relative step norm. The LP isn't moving any more. |
| ε_f | 1 × 10⁻⁴ | Absolute true-residual norm. Linearisation matches actual physics. |
| ε_kpi | 1 × 10⁻³ | Relative KPI change. Objective is no longer improving. |

All three must hold simultaneously. Step alone isn't enough — you can
sit on a stationary point of the linearisation that doesn't satisfy
the true non-linear physics. Residual alone isn't enough — the LP could
oscillate between feasible-but-suboptimal points.

### 7.4 Trust-region adaptation

The standard ratio-of-actual-vs-predicted decrease:

```
ρ_k   =   ( prev_kpi  −  true_kpi )   /   ( last_lp_obj  −  current_lp_obj )
```

Interpretation:
- ρ ≈ 1 — the linearisation is predicting the true cost change well.
  Grow Δ to take bigger steps.
- ρ < 0.25 — the linearisation is over-promising. Shrink Δ.
- 0.25 ≤ ρ ≤ 0.75 — keep Δ as is.

In v0 we shrink/grow by a constant factor of 2 at each crossing of the
thresholds, with hard caps `Δ ∈ [trust_region_min, trust_region_max] =
[0.01, 100]`.

### 7.5 Linear short-circuit

When *every* `LinearizedModel.is_exact` is True at the very first
iteration, the residual `f0 + J · (x − x0) = 0` is the true physics, not
an approximation. The SLP driver detects this and falls through to a
single Pyomo solve — saving an entire round of true-residual checks
and convergence tests. This is how Mode-1 with all-linear units
collapses to a plain LP with zero special casing.

### 7.6 Convergence guarantees and known limitations

What v0 SLP **does** guarantee (under standard assumptions):

- Local convergence to a Karush-Kuhn-Tucker point of the underlying
  non-linear program when the trust region is properly tuned.
- Exact global optimum when every unit is linear.
- Detection of LP infeasibility and trust-region collapse.

What v0 SLP **does not** guarantee:

- **Global optima** for non-convex problems. SLP is a local method;
  multiple starts are needed for global guarantees.
- **Robustness to ill-conditioned Jacobians.** If a unit's J is
  near-singular, the LP may be solved to a numerically unstable point.
- **Smoothness.** Non-smooth residuals (kinks, max(·) operators) break
  the Taylor expansion. v0 has no support for non-smooth physics; the
  workaround is to refactor the residual or use mixed-integer
  formulations.
- **Globalisation strategies** (line-search, filter methods, second-order
  corrections) are deferred to v1.

For non-convex problems where global optima matter, the v1 roadmap
includes Outer Approximation (for Mode 2 with smooth non-linearities)
and globally-valid relaxations.

---

## 8. Sequential MILP → SLP Decomposition (Mode 2 with Non-linear Units)

When Mode 2 is invoked and any unit selected by the MILP is non-linear,
v0 decomposes the problem into two sequential phases.

### 8.1 Outer MILP

Build the MILP using each unit's linearisation evaluated at the
**initial guess** (typically the bound midpoint). Solve to optimality
(or solver tolerance). Extract:

- `x*_milp` — the continuous part of the MILP solution (an approximation
  of the true non-linear optimum).
- `y*_milp` — the binary technology selection.

### 8.2 Inner SLP refinement

If every unit selected by `y*_milp` is linear, return `x*_milp`
directly. Otherwise:

1. Clone the flowsheet, adding `extra_bounds[v] = (0, 0)` for every
   flow variable belonging to an *unselected* technology. This freezes
   the topology.
2. Run `SLPDriver.run(x0=x*_milp)` on the clone. The SLP refines the
   operating point against the *true* non-linear physics, with the
   technology choice held fixed.
3. Tag the result with `y*_milp` and return.

### 8.3 What this approach sacrifices

- The MILP is solved against an approximate (linearised) version of
  the non-linear physics — its technology selection is therefore not
  guaranteed to be the true global optimum.
- A different technology mix might become attractive if the
  linearisation were taken at a different point.

What it gains:

- Simplicity. No cuts, no branching scheme, no convergence proofs
  beyond what SLP itself supplies.
- A clean v1 upgrade path: replacing the outer MILP with Outer
  Approximation or Generalised Benders is a `solvers/` change, not an
  architectural one.

---

## 8b. Trust-Region Filter / Funnel Globalisation (v1.2.0)

Implemented in `pse_ecosystem/solvers/trf/` (filter.py, funnel.py, util.py) and called via `SolveMode.TRUST_REGION`. Based on Eason & Biegler (2016) and Hameed et al. (2021).

### 8b.1 Motivation

The basic SLP trust-region (§7.4) can suffer the **Maratos effect**: a trial step that improves the objective but increases infeasibility is rejected even though it is globally useful. The filter avoids this by maintaining a list of Pareto-non-dominated (objective, infeasibility) pairs and accepting any step that is not dominated.

### 8b.2 Filter mechanism

Define a pair `(f, h)` where:
- `f` = current objective value
- `h` = infeasibility measure: `h(x) = ‖f_nonlinear(x)‖₁` (sum of absolute residuals)

The **filter** `F` is a set of such pairs. A trial point `(f_trial, h_trial)` is **acceptable** to the filter if it is not dominated:

```
∃ (f_i, h_i) ∈ F : f_trial ≥ f_i − δ AND h_trial ≥ h_i  →  reject
```

i.e., a point is rejected only if another filter entry is at least as good in both objective and infeasibility (with margin `δ`). The filter starts empty. Accepted points are added only if they introduce a new non-dominated trade-off.

### 8b.3 Funnel variant

The funnel replaces the filter with a **cone-shaped infeasibility envelope**:

```
h(x_{k+1}) ≤ κ_h · h(x_k)   (infeasibility must decrease by factor κ_h each iteration)
```

where `κ_h ∈ (0, 1)` (typically 0.9). This provides a tighter, monotone-decreasing infeasibility requirement — more conservative than the filter but with stronger convergence guarantees for well-scaled problems.

### 8b.4 Step acceptance protocol

At each Trust-Region iteration:

1. Solve the linearised LP subproblem within the trust-region ball.
2. Evaluate the true (non-linear) residual at the trial point.
3. Compute the ratio `ρ = (f_k − f_trial) / (f_k − f_LP_trial)`.
4. Apply the filter or funnel test.
5. If accepted: update `x`, potentially expand TR. If rejected: shrink TR.

The combination of filter acceptance + TR radius update gives convergence to KKT points of the non-linear equality-constrained problem, subject to regularity conditions (linear independence constraint qualification, second-order sufficiency).

### 8b.5 Adaptive cascade (SolveMode.ADAPTIVE)

When mode = `ADAPTIVE`, the Orchestrator runs:

1. **SLP** (fast, LP-based) — up to `max_iter` iterations.
2. If SLP fails (MAX_ITER or INFEASIBLE): **NLP** (scipy L-BFGS-B with Jacobians from `linearize()`).
3. If NLP fails: **Trust-Region Filter** (full filter/funnel globalisation).

The cascade exits at the first mode that converges. This policy trades speed for robustness automatically without manual mode selection.

---

## 9. Notation Glossary

| Symbol | Meaning | Typical units |
|---|---|---|
| `x` | Vector of decision variables (flows, capacities, …) | mixed |
| `x_v` | Component of `x` named `v` | depends on `v` |
| `x_k` | Vector at SLP iteration `k` | mixed |
| `x_0`, `x*` | Initial guess; converged optimum | mixed |
| `f(x)` | Vector of unit residuals; satisfied at `f = 0` | mixed |
| `f0` | `f(x_k)` evaluated at the linearisation point | mixed |
| `J` | Jacobian `∂f/∂x` evaluated at `x_k` | per-row units |
| `c` | Linear objective coefficient vector | £ / variable units / yr |
| `lb`, `ub` | Variable lower / upper bounds | mixed |
| `y_i` | Binary technology variable | dimensionless {0, 1} |
| `M`, `M_row` | Big-M coupling constants in MILP | matched to constraint |
| `Δ` | Driver-level trust-region multiplier | dimensionless |
| `Δ_min`, `Δ_max` | TR multiplier bounds | dimensionless |
| `ρ` | Actual-vs-predicted decrease ratio | dimensionless |
| `ε_x`, `ε_f`, `ε_kpi` | SLP convergence tolerances | dimensionless / mixed |
| `η` | PEM efficiency | kg H₂ / kWh |
| `a, b, c` | Gasifier model coefficients | see §4.4 |
| `m_·` | Mass flow rate of stream `·` | kg/h |
| `P_elec` | Electrical power input | kW |
| LCOH | Levelised Cost Of Hydrogen | £ / kg H₂ |

---

## 10. References

Foundational reading for the techniques used in v0. (Placeholders —
update as you accrete a working bibliography.)

- Biegler, L. T. *Nonlinear Programming: Concepts, Algorithms, and
  Applications to Chemical Processes.* SIAM, 2010.
- Edgar, T. F.; Himmelblau, D. M.; Lasdon, L. S. *Optimization of
  Chemical Processes.* 2nd edition, McGraw-Hill, 2001.
- Hart, W. E.; Watson, J.-P.; Woodruff, D. L. *Pyomo — Optimization
  Modeling in Python.* 3rd edition, Springer, 2021.
- Floudas, C. A. *Nonlinear and Mixed-Integer Optimization.* Oxford
  University Press, 1995.
- Conn, A. R.; Gould, N. I. M.; Toint, P. L. *Trust-Region Methods.*
  SIAM, 2000. (For the trust-region update rules in §7.4.)
- Eason, J. P.; Biegler, L. T. "A Trust Region Filter Method for Equation-Oriented Flowsheet Optimisation." *Computers & Chemical Engineering*, 86, 2016.
- Hameed, A.; et al. "A Funnel-Based Trust-Region Filter for Flowsheet Optimisation." *AIChE J.*, 2021.

---

## §7 Project Economics & Technoeconomic Metrics (v1.5.0.dev)

This section defines the financial mathematics embedded in
`EconomicEngine` (`models/costing/economic_engine.py`) and exposed through
the `ProjectEconomicsConfig` / `compute_project_economics()` bridge in
`flowsheet_service.py`.

### 7.1 Capital Recovery Factor (CRF)

Converts a total installed capital cost to an equal series of annual
payments over the plant life $N$ at discount rate $r$ (WACC):

$$\text{CRF} = \frac{r(1+r)^N}{(1+r)^N - 1}$$

For $r = 0$, $\text{CRF} = 1/N$ (straight-line amortisation).

**Code:** `EconomicEngine.capital_recovery_factor()`

### 7.2 Net Present Value (NPV)

For a project with uniform annual cash flow $CF$, up-front capital $C_0$,
and terminal salvage value $SV$:

$$\text{NPV} = -C_0 + CF \cdot \frac{1 - (1+r)^{-N}}{r} + \frac{SV}{(1+r)^N}$$

A positive NPV indicates the project returns more than the cost of capital;
a negative NPV destroys value.

**Code:** `EconomicEngine.npv(annual_net_cashflow, initial_capex, salvage_value=0)`

**LP proxy:** For a steady-state flowsheet at fixed production rate,
maximising NPV is equivalent to minimising TAC (total annualised cost),
because $\text{NPV} \approx -\text{TAC}/\text{CRF} \times \text{annuity factor}$.
The solver uses TAC coefficients; the exact NPV is computed post-solve.

### 7.3 Internal Rate of Return (IRR)

The IRR $r^*$ is the discount rate at which $\text{NPV}(r^*) = 0$:

$$-C_0 + CF \cdot \frac{1 - (1+r^*)^{-N}}{r^*} = 0$$

There is no closed-form solution; the implementation uses bisection over
$r \in [0, 10]$ to tolerance $10^{-6}$ within 200 iterations.  Returns
`NaN` when $CF \times N \leq C_0$ (project never pays back undiscounted).

**Code:** `EconomicEngine.irr(initial_capex, annual_net_cashflow, r_max=10.0)`

**Return-value semantics (v1.5.0.dev-AUDIT):**
| Condition | Returned IRR |
|---|---|
| Project never pays back undiscounted (CF·N ≤ C₀) | `nan` |
| IRR exceeds `r_max` (1000% by default) | `+inf` |
| Otherwise | bisected IRR to tolerance |

This makes pathological cash flows fail loudly in the Project Economics
Excel sheet rather than silently clamping at 1000%.

### 7.4 Levelized Cost of Hydrogen (LCOH)

$$\text{LCOH} = \frac{\text{annualised CAPEX} + \text{annual OPEX}}{\dot{m}_{\text{H}_2} \times 3600 \times h_{\text{op}}}$$

where $\dot{m}_{\text{H}_2}$ is in kg/s, $h_{\text{op}}$ is annual operating
hours, giving LCOH in USD/kg H₂.

For a DCF-rigorous form with time-varying costs and production:

$$\text{LCOH} = \frac{\displaystyle\sum_{t=1}^{N} \frac{\text{CapEx}_t + \text{OpEx}_t}{(1+r)^t}}{\displaystyle\sum_{t=1}^{N} \frac{\dot{m}_{\text{H}_2,t}}{(1+r)^t}}$$

The steady-state approximation above (used here) is equivalent when $\dot{m}$
and costs are constant over the plant life.

**Code:** `EconomicEngine.lcoh(capex_annual_USD, opex_annual_USD, h2_kg_per_s)`

### 7.5 Levelized Cost of Energy (LCOE)

$$\text{LCOE} = \frac{\text{annualised CAPEX} + \text{annual OPEX}}{E_{\text{annual}}}
\quad [\text{USD/kWh}]$$

where $E_{\text{annual}}$ is the net annual electrical energy output in kWh/yr.

**Code:** `EconomicEngine.lcoe(capex_annual_USD, opex_annual_USD, energy_kWh_per_year)`

### 7.6 Equipment Cost Scaling (Six-Tenths Rule)

For a piece of equipment with known purchase cost $C_0$ at reference capacity
$S_0$, the cost at a different capacity $S$ is:

$$C = C_0 \left(\frac{S}{S_0}\right)^\alpha$$

The default exponent $\alpha = 0.6$ is the chemical-engineering six-tenths
rule (economies of scale). For exact linear scaling use $\alpha = 1$.

**Code:** `EquipmentScalingRule(reference_cost_USD, reference_size, scaling_exponent=0.6).cost_at(size)`

Typical $\alpha$ values (Turton et al., *Analysis, Synthesis and Design of
Chemical Processes*, 4th ed.):

| Equipment type | α |
|---|---|
| Compressor (centrifugal) | 0.60 |
| Heat exchanger (shell & tube) | 0.65 |
| Distillation column (vessel) | 0.57 |
| Pump (centrifugal) | 0.33 |
| PEM electrolyser stack | 0.85 |

### 7.7 CEPCI Cost Escalation

All SSLW purchase costs are expressed at the CE=500 index basis year (2001).
To convert to a target year $y$:

$$C_y = C_{\text{CE500}} \times \frac{\text{CEPCI}(y)}{500}$$

The `sslw_cepci_factor()` convenience method on `EconomicEngine` computes this ratio.
CEPCI values beyond 2024 are projected at 2.5%/yr compound growth.
- IEA. *Global Hydrogen Review.* (Various years — current edition for
  techno-economic baselines.)
- IRENA. *Green Hydrogen Cost Reduction.* IRENA, 2020.
- Higman, C.; van der Burgt, M. *Gasification.* 2nd edition,
  Gulf Professional Publishing, 2008. (For gasifier yield curves.)

---

## 11. Future Roadmap (Placeholders)

The following are planned theoretical extensions. Each is consistent
with the existing Handshake Protocol and does not require contract
changes in `core/contracts.py`.

- **Full energy balance per unit.** Add temperature, pressure, and
  enthalpy variables; add energy-balance residuals alongside the mass
  ones.
- **Electrochemistry for PEM** (Butler–Volmer, ohmic & activation
  overpotentials, load-dependent η). Becomes a non-linear unit; SLP
  handles it natively.
- **Gasifier kinetics and equilibrium.** Replace the quadratic yield
  with reaction-network kinetics and Gibbs minimisation; expose
  composition variables.
- **MINLP global solvers.** Replace sequential MILP→SLP with Outer
  Approximation, Branch-and-Refine, or Spatial B&B for non-convex cases.
- **Stochastic / robust optimisation.** Scenario trees at the
  Orchestrator level, scenario-weighted objectives, chance constraints.
- **Multi-objective.** Pareto fronts for cost vs emissions, or cost vs
  capacity factor.
- **Carbon accounting.** Emissions factors on every flow variable;
  carbon price as a configurable multiplier.

---

## §10 Grand Challenge: 10-Unit Biomass → H₂ Flowsheet

This section provides the analytical mass-balance derivation for the
`industrial.grand_challenge_10unit` template (v1.3.0).

### §10.1 Basis Definition

| Parameter | Symbol | Value |
|---|---|---|
| Wet biomass feed | Ḟ_wet | 1.0 kg/s |
| Moisture content (Pine Wood) | MC | 0.17 (17 wt%) |
| Dry feed | Ḟ_dry = Ḟ_wet (1 − MC) | 0.83 kg/s |
| Steam-to-biomass ratio | S/B | 1.0 kg_steam/kg_dry |
| Steam feed | ṅ_steam = Ḟ_dry × 1000 / 18.015 | 46.1 mol/s |
| Gasifier temperature | T_gas | 800 °C = 1073 K |
| HTS reactor temperature | T_HTS | 400 °C = 673 K |
| LTS reactor temperature | T_LTS | 220 °C = 493 K |
| PSA H₂ recovery | r_H₂ | 0.94 |
| H₂ polisher recovery | r_pol | 0.995 |

### §10.2 Elemental Feeds (Pine Wood Composition)

Pine Wood dry elemental composition (mass fractions, NIST/ECN database):
C = 47.1%, H = 6.3%, O = 44.2%, N = 0.5%

$$\dot{n}_C = \frac{\dot{F}_{dry} \times 0.471}{M_C} = \frac{0.83 \times 0.471}{12.011} \times 10^3 \approx 32.5 \text{ mol/s}$$

$$\dot{n}_{H,biomass} = \frac{0.83 \times 0.063}{1.008} \times 10^3 \approx 51.9 \text{ mol/s (H atoms)}$$

Total hydrogen (biomass + steam):
$$\dot{n}_{H,total} = \dot{n}_{H,biomass} + 2 \dot{n}_{steam} = 51.9 + 92.2 = 144.1 \text{ mol H/s}$$

### §10.3 Gasifier Equilibrium (Unit 2)

Two simultaneous equilibrium constraints at T = 1073 K:

**WGS equilibrium:**
$$K_{WGS}(T) = \exp\!\left(\frac{4300}{T} - 3.84\right) = \exp\!\left(\frac{4300}{1073} - 3.84\right) \approx 1.80$$

$$K_{WGS} = \frac{n_{CO_2} \cdot n_{H_2}}{n_{CO} \cdot n_{H_2O}}$$

**Methanation equilibrium:**
$$K_{met}(T) = \exp\!\left(\frac{25000}{T} - 26.2\right) = \exp\!\left(\frac{25000}{1073} - 26.2\right) \approx 150$$

$$K_{met} = \frac{n_{CH_4} \cdot n_{H_2O}}{n_{CO} \cdot n_{H_2}^3} \cdot \left(\frac{P}{n_{total}}\right)^{-2}$$

**Element balances (4 equations, 6 unknowns):**

$$n_{CO} + n_{CO_2} + n_{CH_4} = \dot{n}_C \quad \text{(carbon)}$$

$$2n_{H_2} + 2n_{H_2O} + 4n_{CH_4} = \dot{n}_{H,total} \quad \text{(hydrogen)}$$

$$n_{CO} + 2n_{CO_2} + n_{H_2O} = \dot{n}_{O,total} \quad \text{(oxygen)}$$

$$2n_{N_2} = \dot{n}_N \quad \text{(nitrogen)}$$

### §10.4 Cyclone (Unit 3) — Linear

Split fraction 99%/1% applied uniformly to all 6 species:
$$n_{c,out_0} = 0.99 \cdot n_{c,in}, \qquad n_{c,out_1} = 0.01 \cdot n_{c,in} \quad \forall c \in \{H_2, CO, CO_2, H_2O, CH_4, N_2\}$$

### §10.5 Dual-Stage WGS (Units 4–5)

**High-Temperature Shift (HTS, 400 °C):**

$$K_{WGS}(673) = \exp\!\left(\frac{4300}{673} - 3.84\right) \approx 8.9$$

At equilibrium with 6-component syngas, ~75% CO conversion expected analytically:
$$X_{CO,HTS} = \frac{K_{WGS}(T_{HTS}) \cdot r}{1 + K_{WGS}(T_{HTS}) \cdot r}, \quad r = \frac{n_{H_2O,in}}{n_{CO,in}}$$

**Low-Temperature Shift (LTS, 220 °C):**

$$K_{WGS}(493) = \exp\!\left(\frac{4300}{493} - 3.84\right) \approx 86$$

Additional ~90% conversion of HTS residual CO. WGSReactorHF enforces:
$$f_{stoich}: \; n_{CO,out} = n_{CO,in}(1 - X_{CO}), \quad n_{H_2,out} = n_{H_2,in} + n_{CO,in} X_{CO}$$

$$f_{equil}: \; K_{WGS}(T) \cdot n_{CO,out} \cdot n_{H_2O,out} - n_{CO_2,out} \cdot n_{H_2,out} = 0$$

### §10.6 Separation Train (Units 6–7) — Linear

**Moisture separator** (Unit 6): H₂O split 30%/70% (gas/liquid), all other species 99%/1%.

**CO₂ scrubber** (Unit 7): CO₂ split 3%/97% (gas/absorbed), H₂O 20%/80%, other 97%/3%.

### §10.7 PSA (Unit 8) — Linear

$$n_{H_2,product} = r_{H_2} \cdot n_{H_2,feed} = 0.94 \cdot n_{H_2,feed}$$

All non-H₂ species pass to tail gas. H₂ blowdown = (1 − 0.94) × n_H₂_feed (not tracked).

PSA power (KPI): W_PSA ≈ 1.5 kWh/kg H₂ (literature value).

### §10.8 Compressor (Unit 9) — Nonlinear

Isentropic compression of pure H₂ (γ = 1.41, η = 0.78):

$$W_{shaft} = \frac{\dot{n}_{H_2} \cdot c_{p,H_2} \cdot T_{in}}{\eta_{is}} \left[\left(\frac{P_{out}}{P_{in}}\right)^{(\gamma-1)/\gamma} - 1\right]$$

At T_in = 298 K, P_out/P_in = 50 bar / 1 bar = 50, γ = 1.41:
$$(P_{out}/P_{in})^{0.291} = 50^{0.291} \approx 3.32 \implies W/\dot{n} \approx 15.5 \text{ kJ/mol H}_2$$

### §10.9 H₂ Polisher (Unit 10) — Linear

$$n_{H_2,product} = 0.995 \cdot n_{H_2,comp\_outlet}$$

### §10.10 Verification Table

| KPI | Analytical Formula | Solver Verification |
|---|---|---|
| Carbon balance (gasifier) | n_CO + n_CO₂ + n_CH₄ = n_C_feed | `pytest test_grand_challenge::test_grand_challenge_mass_balance` |
| HTS CO conversion | ~75% (K_WGS(673K) ≈ 8.9) | `hts.CO_conversion_pct` KPI |
| LTS CO conversion | ~90% of HTS residual | `lts.CO_conversion_pct` KPI |
| PSA H₂ recovery | exactly 94% (linear) | `psa.H2_recovery_pct` KPI |
| Polisher H₂ recovery | exactly 99.5% (linear) | `h2_polisher.outlet_0.F_H2 / h2_comp.outlet.F_H2` |
| H₂ product flow | > 0 mol/s | `psa.h2_out.F_H2 > 0` |

All 9 structural tests in `tests/test_grand_challenge.py` pass on a clean install.

---

## §11 Manual Build Workshop: 7-Unit Chain Mass & Energy Balances

This section provides the symbolic residual mathematics for each unit in the v1.3.0-Phase5
workshop chain:

```
[1] BiomassStorageHF → [2] BiomassGasifierHF → [3] SeparatorHF (Cyclone)
→ [4] WGSReactorHF → [5] CoolerHF → [6] SeparatorHF (PSA) → [7] Compressor
```

Notation: $\dot{n}$ [mol/s], $\dot{F}$ [kg/s], $T$ [K], $P$ [Pa].

---

### §11.1 BiomassStorageHF (Unit 1) — Linear

Single residual: dry biomass outlet = wet inlet minus moisture.

$$f_1 = \dot{F}_{dry} - \dot{F}_{wet}(1 - \text{MC}) = 0$$

where MC = moisture content (e.g. 0.17 for Pine Wood). One residual, two variables.

Jacobian (exact, constant):

$$J = \begin{bmatrix} -(1-\text{MC}) & +1 \end{bmatrix}$$

---

### §11.2 BiomassGasifierHF (Unit 2) — Non-linear

Six residuals, 8 variables ($\dot{F}_{biomass}$, $\dot{F}_{steam}$, $\dot{n}_{H_2}$, $\dot{n}_{CO}$, $\dot{n}_{CO_2}$, $\dot{n}_{H_2O}$, $\dot{n}_{CH_4}$, $\dot{n}_{N_2}$):

**Element balances:**

$$f_1 = \dot{n}_{CO} + \dot{n}_{CO_2} + \dot{n}_{CH_4} - \dot{n}_C(\dot{F}_{bio}) = 0 \quad \text{(carbon)}$$

$$f_2 = 2\dot{n}_{H_2} + 2\dot{n}_{H_2O} + 4\dot{n}_{CH_4} - \dot{n}_{H}(\dot{F}_{bio}, \dot{F}_{steam}) = 0 \quad \text{(hydrogen)}$$

$$f_3 = \dot{n}_{CO} + 2\dot{n}_{CO_2} + \dot{n}_{H_2O} - \dot{n}_{O}(\dot{F}_{bio}, \dot{F}_{steam}) = 0 \quad \text{(oxygen)}$$

$$f_4 = 2\dot{n}_{N_2} - \dot{n}_N(\dot{F}_{bio}) = 0 \quad \text{(nitrogen)}$$

**Equilibrium constraints:**

$$f_5 = K_{WGS}(T) \cdot \dot{n}_{CO} \cdot \dot{n}_{H_2O} - \dot{n}_{CO_2} \cdot \dot{n}_{H_2} = 0$$

$$f_6 = K_{met}(T) \cdot \dot{n}_{CO} \cdot \dot{n}_{H_2}^3 \cdot \left(\frac{P}{\dot{n}_{total}}\right)^{-2} - \dot{n}_{CH_4} \cdot \dot{n}_{H_2O} = 0$$

where:

$$K_{WGS}(T) = \exp\!\left(\frac{4300}{T} - 3.84\right), \qquad K_{met}(T) = \exp\!\left(\frac{25000}{T} - 26.2\right)$$

---

### §11.3 SeparatorHF — Cyclone (Unit 3) — Linear

For each species $c \in \{H_2, CO, CO_2, H_2O, CH_4, N_2\}$ with split fraction $s_c$ to outlet_0:

$$f_{c,1} = \dot{n}_{c, out_0} - s_c \cdot \dot{n}_{c, in} = 0$$

$$f_{c,2} = \dot{n}_{c, out_1} - (1 - s_c) \cdot \dot{n}_{c, in} = 0$$

With $s_c = 0.99$ for all species (99% char/ash removal to outlet_0 is clean syngas):
12 residuals, 18 flow variables. Exact analytical Jacobian.

---

### §11.4 WGSReactorHF (Unit 4) — Non-linear

7 residuals, 13 variables (6 inlet + 6 outlet flows + $X_{CO}$):

**Stoichiometric balances** ($i \in \{H_2, CO, CO_2, H_2O, CH_4, N_2\}$):

$$f_{CO}:     \quad \dot{n}_{CO,out}    = \dot{n}_{CO,in}(1 - X_{CO}) = 0$$

$$f_{H_2O}:   \quad \dot{n}_{H_2O,out}  = \dot{n}_{H_2O,in} - \dot{n}_{CO,in} X_{CO} = 0$$

$$f_{CO_2}:   \quad \dot{n}_{CO_2,out}  = \dot{n}_{CO_2,in} + \dot{n}_{CO,in} X_{CO} = 0$$

$$f_{H_2}:    \quad \dot{n}_{H_2,out}   = \dot{n}_{H_2,in}  + \dot{n}_{CO,in} X_{CO} = 0$$

$$f_{CH_4}:   \quad \dot{n}_{CH_4,out}  = \dot{n}_{CH_4,in} = 0$$

$$f_{N_2}:    \quad \dot{n}_{N_2,out}   = \dot{n}_{N_2,in}  = 0$$

**Equilibrium constraint** (Δn = 0, pressure-independent):

$$f_{eq}: \; K_{WGS}(T_{wgs}) \cdot \dot{n}_{CO,out} \cdot \dot{n}_{H_2O,out} - \dot{n}_{CO_2,out} \cdot \dot{n}_{H_2,out} = 0$$

At $T_{wgs} = 400°C = 673\,\text{K}$: $K_{WGS}(673) \approx 8.9$, giving $X_{CO} \approx 75\%$.

---

### §11.5 CoolerHF (Unit 5) — Linear

$N$ residuals, $2N$ variables (N inlet + N outlet flows, no T/P in ports):

$$f_i = \dot{n}_{c_i, out} - \dot{n}_{c_i, in} = 0 \qquad \forall\, i = 1, \ldots, N$$

Mass is conserved; outlet temperature is fixed by parameter $T_{out}$ (informational KPI, not
a solver variable). Exact analytical Jacobian:

$$J_{ij} = \begin{cases} -1 & \text{if } j = \text{inlet index of } c_i \\ +1 & \text{if } j = \text{outlet index of } c_i \\ 0 & \text{otherwise} \end{cases}$$

---

### §11.6 SeparatorHF — PSA Proxy (Unit 6) — Linear

Same split-fraction structure as the Cyclone (§11.3), but with species-specific splits to model
H₂ enrichment. Example: H₂ split to outlet_0 = 0.85, all other species = 0.05. 12 residuals,
exact linear.

---

### §11.7 Compressor (Unit 7) — Non-linear

$N + 3$ residuals, $2N + 5$ variables (N inlet + N outlet flows + $T_{in}$, $P_{in}$, $T_{out}$, $P_{out}$, $W_{shaft}$):

**Material balances** (N equations):

$$f_i = \dot{n}_{c_i, out} - \dot{n}_{c_i, in} = 0 \qquad \forall\, i = 1, \ldots, N$$

**Isentropic outlet temperature:**

$$f_{T}: \; T_{out} - \frac{T_{in}}{\eta_{is}} \left[\left(\frac{P_{out}}{P_{in}}\right)^{(\gamma-1)/\gamma} - 1\right] - T_{in} = 0$$

with $\gamma = c_p / c_v$ evaluated at $T_{in}$ for the mixture, $\eta_{is}$ = isentropic efficiency.

**Outlet pressure constraint** (when $P_{out}$ is fixed):

$$f_P: \; P_{out} - P_{out,set} = 0$$

**Shaft work:**

$$f_W: \; W_{shaft} - \dot{n}_{total} \cdot c_p(T_{avg}) \cdot (T_{out} - T_{in}) = 0$$

At $P_{out} = 5\,\text{MPa}$, $P_{in} = 101325\,\text{Pa}$, $T_{in} = 310\,\text{K}$, $\eta_{is} = 0.78$:

$$\left(\frac{5 \times 10^6}{101325}\right)^{0.286} \approx 3.35 \implies T_{out} \approx 310 + \frac{310 \times (3.35 - 1)}{0.78} \approx 1243\,\text{K (multi-species)}$$

*Note: the actual outlet temperature depends on the mixture $\gamma$ computed from species Shomate coefficients.*

---

### §11.8 Connection Topology — Variable Equalities

Each connection in the workshop chain generates one equality constraint per shared variable.
Let $H(x) = 0$ denote the full set of port-variable equalities; the 7-unit chain produces
exactly **33 scalar equations**:

$$H(x) = \begin{bmatrix} H_{\text{conn},1}(x) \\ \vdots \\ H_{\text{conn},6}(x) \end{bmatrix} = 0 \quad \in \mathbb{R}^{33}$$

| Connection | Port type (outlet → inlet) | $|H_{\text{conn}}|$ |
|---|---|:---:|
| `storage.dry_out` → `gasifier.biomass_in` | 1-comp solid, no T/P → 1-comp solid, no T/P (full-port) | 1 |
| `gasifier.syngas_out` → `cyclone.inlet` | 6-comp gas, **no T/P** → 6-comp gas, with T/P (flow-only) | 6 |
| `cyclone.outlet_0` → `wgs.syngas_in` | 6-comp gas, with T/P → 6-comp gas, **no T/P** (flow-only) | 6 |
| `wgs.shifted_out` → `cooler.inlet` | 6-comp gas, no T/P → 6-comp gas, no T/P (full-port) | 6 |
| `cooler.outlet` → `psa.inlet` | 6-comp gas, **no T/P** → 6-comp gas, with T/P (flow-only) | 6 |
| `psa.outlet_0` → `comp.inlet` | 6-comp gas, with T/P → 6-comp gas, with T/P (full-port) | 8 |
| **Total** | | **33** |

Flow-only connections arise when the outlet port carries no T/P variables but the inlet
port does (or vice versa). The `build_custom_flowsheet()` fallback in
`flowsheet_service.py` detects the `ValueError` from `BaseFlowsheet.connect()` and links
only the 6 `F_` variables.

### §11.9 Component-Mismatch Zero-Fill Padder (v1.5.2)

When a Custom Builder connection links two ports with **different component counts**
(e.g. a 1-species solid `storage.dry_out` connected directly to a 6-species gas
`cyclone.inlet`), the flow-only fallback cannot pair variables.  The **zero-fill padder**
in `build_custom_flowsheet()` handles this by:

1. **Name-matching**: for each species $s$ present in both the outlet and inlet port's
   `F_` variable set, an equality $x_{\text{out},s} = x_{\text{in},s}$ is added.

2. **Zero-fill**: for each species $s'$ present only in the inlet port (no matching
   outlet source), the equality $x_{\text{in},s'} = 0$ is added as an
   `extra_equality` constraint.  This pins the unmatched inlet flow to zero without
   requiring an explicit unit.

3. **Free surplus**: outlet species with no matching inlet are left as free
   optimisation variables (they appear only in the outlet unit's own residuals).

Formally, let $\mathcal{A}$ be the outlet species set, $\mathcal{B}$ the inlet species
set.  The padder adds:

$$x_{\text{out},s} - x_{\text{in},s} = 0 \quad \forall s \in \mathcal{A} \cap \mathcal{B}$$
$$x_{\text{in},s'} = 0 \quad \forall s' \in \mathcal{B} \setminus \mathcal{A}$$

A user-visible warning (not a fatal skip) is recorded in `fs._conn_warnings` listing
the number of zero-filled species.

---

## §8 Cold Gas Efficiency and the steam-enthalpy correction (v1.5.0.dev-AUDIT5)

The classical Cold Gas Efficiency definition

$$\eta_{\text{CGE}}^{\text{LHV}} = \frac{\text{LHV}(\text{syngas})}{\text{LHV}(\text{biomass}_{\text{dry}})}$$

is a meaningful performance indicator for **autothermal** gasification
(air or oxygen, partial oxidation supplies the heat).  For **steam**
gasification the steam carries enthalpy not accounted for in the
denominator, so this ratio routinely exceeds unity:

$$\eta_{\text{CGE}}^{\text{LHV}} = \frac{\dot{m}_{\text{H}_2}h_{H_2}^{LHV} + \dot{m}_{\text{CO}}h_{\text{CO}}^{LHV} + \dot{m}_{\text{CH}_4}h_{\text{CH}_4}^{LHV}}{\dot{m}_{\text{biomass}}\,h_{\text{biomass}}^{LHV}} \, > \, 1 \quad \text{for steam gasif.}$$

A second-law-consistent metric adds the steam thermal input:

$$\eta_{\text{CGE}}^{\text{with steam}} = \frac{\text{LHV}(\text{syngas})}{\text{LHV}(\text{biomass}_{\text{dry}}) + \dot{m}_{\text{steam}} \cdot h_{\text{steam}}(T)}$$

bounded by $\leq 1$ for any feasible operating point.

### Steam enthalpy correlation

`BiomassGasifierHF.kpis()` uses a three-term decomposition relative to
25 °C liquid water:

$$h_{\text{steam}}(T_C) = c_{p,\text{water}} \cdot (100 - 25) + \Delta h_{\text{vap}}(100\,°\text{C}) + c_{p,\text{steam}} \cdot \max(T_C - 100, 0)$$

with $c_{p,\text{water}} \approx 4.18$ kJ/kg/K, $\Delta h_{\text{vap}} = 2257$ kJ/kg, $c_{p,\text{steam}} \approx 2.1$ kJ/kg/K.  At $T_C = 800\,°\text{C}$
this gives $h_{\text{steam}} \approx 4041$ kJ/kg — within 3 % of the NIST
steam-table value 4159 kJ/kg.

### Reporting convention

| KPI key | Symbol | Formula | Bound |
|---|---|---|---|
| `CGE_LHV_percent` | $\eta_{\text{CGE}}^{\text{LHV}}$ | LHV(syngas) / LHV(biomass) | unbounded; can exceed 100 % |
| `CGE_with_steam_percent` | $\eta_{\text{CGE}}^{\text{with steam}}$ | LHV(syngas) / (LHV(biomass) + $\dot{m}h_{\text{steam}}$) | $\leq 100$ % |
| `CGE_percent` | — | (legacy alias for `CGE_LHV_percent`) | per above |

Any new biomass-like unit that adds external-heat-supply inputs should
follow the same convention: emit both a bare-LHV and a corrected variant.

---

## §9 Elastic-mode LP recovery (v1.5.0.dev-AUDIT4)

When the hard-equality LP at iteration $k$ of an SLP loop returns
INFEASIBLE — typically because tight `extra_bounds` intersect with the
local linearisation of nonlinear residuals — the driver retries in
**elastic mode**.  Each equality

$$J \cdot x = J \cdot x_0 - f_0$$

is augmented with non-negative slack pairs $(s^+, s^-)$:

$$J \cdot x + s^+ - s^- = J \cdot x_0 - f_0, \quad s^+, s^- \geq 0$$

and the LP objective is augmented with a large penalty $\mu = $
`elastic_penalty` (default $10^6$):

$$\min_{x, s^\pm} \; c^T x + \mu \sum_i (s_i^+ + s_i^-)$$

The slack-augmented LP is **always feasible** (set $x$ to any
bound-feasible point and let the slacks absorb the residual).  The SLP
driver then accepts the step only when $\sum_i (s_i^+ + s_i^-) < $
`elastic_slack_tol` (default $10^{-3}$); above tolerance, it takes a
damped 0.3× step toward the elastic solution and re-linearises at the
next iteration.

This is the standard "$\ell_1$-elastic" recovery used in SQP-style NLP
solvers (e.g., SNOPT, Gurobi's barrier-with-relaxation mode).  See
Fletcher & Leyffer (2002) for the convergence theory.

---

## §9. Safety Engineering Foundations

### §9.1 ASME Pressure Vessel Sizing — UG-27(c)(1)

For a thin-walled cylindrical shell under internal pressure, ASME Section VIII
Division 1 Equation UG-27(c)(1) gives the minimum required wall thickness:

$$\boxed{t = \frac{P \cdot R}{S \cdot E - 0.6\,P}}$$

| Symbol | Definition | Typical value |
|---|---|---|
| $t$ | Minimum wall thickness [m] | — |
| $P$ | Internal design pressure [Pa] | Operating pressure × 1.1 |
| $R$ | Inner radius [m] | 0.5 m (default in PSE model) |
| $S$ | Maximum allowable stress [Pa] | 138 MPa (SA-516-70, $\leq$ 300 °C) |
| $E$ | Weld joint efficiency [-] | 1.0 (full radiography) |

**Validity limit**: $P / (S \cdot E) < 0.385$.  Above this the thin-wall
assumption breaks down; ASME Division 2 or UG-27(c)(2) (longitudinal stress)
must be used.  `asme_minimum_wall_thickness()` raises `ValueError` when the
limit is exceeded.

**Worked example** (Compressor outlet, P = 50 bar, R = 0.5 m, SA-516-70):

$$t = \frac{5 \times 10^6 \times 0.5}{138 \times 10^6 - 0.6 \times 5 \times 10^6}
    = \frac{2.5 \times 10^6}{135 \times 10^6} \approx 18.5 \text{ mm}$$

This exceeds the PSE model's 3 mm warning threshold → status "OK".

### §9.2 Le Chatelier Flammability Estimation

For a mixture of $n$ flammable gases, Le Chatelier (1891) gives the mixture
lower and upper flammability limits (LFL, UFL) in air:

$$\text{LFL}_\text{mix} = \frac{1}{\displaystyle\sum_{i=1}^{n} \frac{x_i}{\text{LFL}_i}},
\qquad
\text{UFL}_\text{mix} = \frac{1}{\displaystyle\sum_{i=1}^{n} \frac{x_i}{\text{UFL}_i}}$$

where $x_i$ are the **renormalized mole fractions of flammable species only**
(non-flammable N₂, CO₂, H₂O, O₂ are excluded before renormalization).

**Flammability database** (vol% in air, NFPA 68 / IEC 60079-20-1):

| Species | LFL [vol%] | UFL [vol%] |
|---|---|---|
| H₂ | 4.0 | 75.0 |
| CO | 12.5 | 74.0 |
| CH₄ | 5.0 | 15.0 |
| C₂H₆ | 3.0 | 12.4 |
| C₃H₈ | 2.1 | 9.5 |

**Worked example** (syngas stream: H₂ = 50 mol%, CO = 50 mol%):

$$\text{LFL}_\text{mix} = \frac{1}{0.5/4.0 + 0.5/12.5}
    = \frac{1}{0.125 + 0.040} = \frac{1}{0.165} \approx 6.06 \text{ vol\%}$$

### §9.3 Pressure Safety Margin

The operating pressure margin is defined as:

$$\text{margin} = \frac{P_\text{design} - P_\text{operating}}{P_\text{design}}$$

By default $P_\text{design} = 1.1 \times P_\text{operating}$ (10 % engineering
margin), giving margin $= 1 - 1/1.1 \approx 9.1\,\%$.  A WARNING is raised when
margin $< 5\,\%$; a VIOLATION when margin $< 0$ (operating above design pressure).

### §9.4 Non-intrusiveness Guarantee

All three safety functions (`asme_minimum_wall_thickness`, `flammability_margins`,
`operating_pressure_margin`) are **pure functions**: same inputs always produce the
same outputs, no side effects, no access to solver state, no modification of unit
residuals or bounds.  They are tested for this property in
`tests/test_industrial_readiness.py::TestNonIntrusiveness`.
