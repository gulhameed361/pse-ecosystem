# Theory Reference

> The mathematical and process-systems-engineering underpinnings of the
> PSE Ecosystem v0. For the high-level architecture see
> [`ARCHITECTURE.md`](ARCHITECTURE.md); for code-level details see
> [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md); for end-user usage see
> [`USER_MANUAL.md`](USER_MANUAL.md).

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
