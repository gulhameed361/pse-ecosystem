# PSE Ecosystem — Architecture Blueprint (v0)

> Status: load-bearing document. The Layer 2 ↔ Layer 3 contract described
> here is the lever that lets us scale from toy LP flowsheets to MINLP /
> ML-surrogate workloads without rewriting the platform. Treat changes to
> this document as architectural decisions.

---

## 1. The three-layer split

```
┌────────────────────────────────────────────────────────────┐
│  Layer 1 — UI / Application                                │
│  • theme + application + flowsheet selection               │
│  • Mode 1 (Fixed/LP) vs Mode 2 (Flexible/MILP)             │
│  • v0: Python CLI stub (pse_ecosystem.ui.entry)            │
└────────────────────────────────┬───────────────────────────┘
                                 │   SolveMode, demand, scenario
                                 ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 2 — Decision / Solver                               │
│  • Orchestrator (mode dispatch)                            │
│  • SLPDriver (Successive-Linearization loop)               │
│  • lp_builder / milp_builder (Pyomo assembly)              │
│  • knows nothing about physics                             │
└────────────────┬─────────────────────────────┬─────────────┘
                 │  PrimalGuess                │  SolveResult
                 ▼                             ▲
┌────────────────────────────────────────────────────────────┐
│  Layer 3 — Knowledge / Models                              │
│  • BaseUnit + concrete unit models (PEM, gasifier, …)      │
│  • returns LinearizedModel(f0, J, bounds, …)               │
│  • returns UnitResponse for true non-linear evaluation     │
│  • knows nothing about optimisation                        │
└────────────────────────────────────────────────────────────┘
```

The single pipe between Layer 2 and Layer 3 is **the Handshake Protocol**
defined in `pse_ecosystem/core/contracts.py`. Both layers depend on
`core/contracts.py`; neither depends on the other. The directed dependency
graph is enforced by `tests/test_slp_convergence.py::test_solvers_do_not_import_concrete_unit_modules`.

---

## 2. The Handshake Protocol

Three datatypes (all dataclasses in `core/contracts.py`):

### 2.1 `PrimalGuess` — Layer 2 → Layer 3

```python
PrimalGuess(
    values: Dict[str, float],   # variable name → current value at iter k
    iteration: int,             # SLP iteration counter
    metadata: Dict[str, Any],   # scenario tags, scaling info, etc.
)
```

Shipped to every unit at the start of each SLP iteration. Variable names are
the only handle Layer 2 has on the unit's internal state — the unit owns
the interpretation.

### 2.2 `LinearizedModel` — Layer 3 → Layer 2

```python
LinearizedModel(
    unit_id:          str,
    variables:        List[str],       # column ordering for x0 and J
    x0:               np.ndarray,      # shape (n,)   — linearisation point
    f0:               np.ndarray,      # shape (m,)   — residual at x0
    J:                np.ndarray,      # shape (m, n) — Jacobian ∂f/∂x at x0
    bounds:           Dict[str, (lo, hi)],
    objective_terms:  Dict[str, float],   # var → linear cost coefficient
    is_exact:         bool,            # True ⇒ linear model, skip re-linearisation
    trust_region:     Optional[float], # unit-supplied step cap, optional
    kpi_gradients:    Dict[str, np.ndarray],
)
```

The Jacobian-residual pair is the entire physics window Layer 2 ever sees.
This is what lets us swap the implementation of a unit (toy → analytical →
JAX surrogate → ML) without touching Layer 2.

Layer 2 turns each `LinearizedModel` into LP rows by rearranging the Taylor
expansion `f0 + J · (x − x0) = 0`:

```
J · x  =  J · x0 − f0
```

so each row of `J` produces one equality constraint in the LP. Per-variable
bounds are intersected with flowsheet-level bounds. Trust-region radii are
overlaid as `|x_v − x_anchor_v| ≤ Δ`. The global objective is
`Σ_units Σ_vars objective_terms[var] · x[var]`.

### 2.3 `UnitResponse` — Layer 3 → Layer 2 (true evaluation)

```python
UnitResponse(
    unit_id:    str,
    outputs:    Dict[str, float],
    kpis:       Dict[str, float],
    residual:   np.ndarray,        # f(x) at the candidate point — the truth
    feasible:   bool,
    diagnostics: Dict[str, Any],
)
```

Used **only** to evaluate the *true* (non-linear) physics at a candidate
point — for residual checks at the end of an SLP iteration and for final
KPI reporting. Never required for solving.

### 2.4 The handshake, step by step

```
SLP iteration k:
  1. Layer 2 ships PrimalGuess(values=x_k, iteration=k) to every unit.
  2. Each unit returns a LinearizedModel(f0, J, …) at x_k.
  3. lp_builder assembles a single Pyomo LP:
        - per-unit linearised equalities         (J·x = J·x0 − f0)
        - stream-connectivity equalities         (from the flowsheet)
        - bounds (intersection of unit & flowsheet)
        - trust-region constraint                (when set)
        - objective = Σ objective_terms · x
  4. Pyomo solves → x_{k+1}
  5. Layer 2 calls unit.evaluate(x_{k+1}) → UnitResponse, gathering the
     TRUE non-linear residual f(x_{k+1}).
  6. Convergence test (see §3).
     If pass ⇒ converged. Else trust-region update; k ← k+1; goto 1.
```

**Linear short-circuit.** If every unit returns `is_exact=True`, the SLP
driver exits after a single LP solve. Mode-1 with all-linear units therefore
degenerates to a plain LP with no special casing.

---

## 3. Successive Linearization — the algorithm

Implemented in `pse_ecosystem/solvers/slp.py`.

```
Inputs
    flowsheet            — BaseFlowsheet (Layer 3 surface)
    x0                   — initial guess (defaults to bound midpoints)
    config               — SLPConfig with tolerances and trust-region knobs

State
    x_k         ← x0
    Δ           ← config.trust_region_init
    prev_kpi    ← +∞
    history     ← []

For k = 0 .. max_iter − 1:

  ── Layer-3 round ──
  lin_models ← [unit.linearize(PrimalGuess(x_k, k)) for unit in flowsheet]

  if k == 0 and every model is exact:
      return single LP solve            # short-circuit

  ── Layer-2 round ──
  pyomo_model ← lp_builder.build(lin_models, flowsheet, Δ, x_k)
  x_{k+1}, lp_obj ← pyomo_solve(pyomo_model)

  ── Validate against TRUE physics ──
  true_residual ← concat(unit.residual(x_{k+1}) for each unit)
  true_kpi      ← Σ objective_terms · x_{k+1}

  step  ← ‖x_{k+1} − x_k‖∞ / max(1, ‖x_k‖∞)
  res   ← ‖true_residual‖∞
  dkpi  ← |true_kpi − prev_kpi| / max(1, |prev_kpi|)

  ── Convergence test ──
  if step < eps_x  AND  res < eps_f  AND  dkpi < eps_kpi:
      return SolveResult(CONVERGED, …)

  ── Trust-region update ──
  predicted_decrease ← last_lp_obj − lp_obj
  actual_decrease    ← prev_kpi − true_kpi
  ρ                  ← actual_decrease / predicted_decrease
  if ρ < ρ_shrink:  Δ ← max(Δ/2, Δ_min)
  if ρ > ρ_grow:    Δ ← min(Δ·2, Δ_max)

  x_k, prev_kpi, last_lp_obj ← x_{k+1}, true_kpi, lp_obj

return SolveResult(MAX_ITER, …)
```

Three convergence criteria are checked simultaneously:

| symbol  | meaning                                | default  |
|---------|----------------------------------------|----------|
| ε_x     | relative step norm                     | 1e-4     |
| ε_f     | absolute true-residual norm            | 1e-4     |
| ε_kpi   | relative KPI change                    | 1e-3     |

The trust-region update is the standard ratio-of-actual-vs-predicted
heuristic. For genuinely linear flowsheets the update never fires because
the algorithm short-circuits in step 0.

### 3.1 Infeasibility recovery

If the LP comes back infeasible (typically because the trust region cut
through the feasible polytope), the driver shrinks Δ by a factor of 2 and
re-tries. If Δ hits `Δ_min` while still infeasible, the driver returns
`SolverStatus.INFEASIBLE` carrying the last feasible iterate.

---

## 4. Mode 1 vs Mode 2

Both routes are dispatched by `pse_ecosystem.solvers.orchestrator.Orchestrator`.

### 4.1 Mode 1 — `FIXED_LP`

Fixed flowsheet topology, fixed technology choices. The Orchestrator hands
the flowsheet directly to `SLPDriver`. If every unit is linear the
short-circuit kicks in and a single LP solve returns the answer.

### 4.2 Mode 2 — `FLEXIBLE_MILP`

The user supplies one `TechnologyChoice` per candidate, each with:

* a binary variable `y_i ∈ {0, 1}`
* a list of flow variables that should be forced to 0 when `y_i = 0`
* a `big_M` for the coupling constraints
* an annualised `fixed_cost` added to the MILP objective when `y_i = 1`

Pseudocode of `_solve_flexible`:

```
1. linearisations ← [u.linearize(PrimalGuess(x0, 0)) for u in flowsheet]
2. milp ← build_milp(linearisations, flowsheet, technology_choices)
3. solve milp → (x*, y*)
4. active ← {u : at least one y_i with unit_id(u) selected}
5. if every active unit is_linear:    return SolveResult(...) directly
   else:
       a. clone the flowsheet, forcing flow variables of inactive techs to 0
       b. SLPDriver(clone).run(x0=x*) to refine operations
       c. attach y* to the SLP result and return
```

This is the v0 **sequential MILP→SLP decomposition**. Outer-approximation
and Benders-style cuts are deliberately out of scope until the unit library
is richer.

---

## 5. Layer-boundary rules

These are non-negotiable; the test suite enforces them.

| Layer | May import from                          | May NOT import from                     |
|-------|-------------------------------------------|------------------------------------------|
| Layer 1 (`ui/`, `themes/`) | `core/`, `solvers/`, `flowsheets/`, specific units | — |
| Layer 2 (`solvers/`)       | `core/`, `flowsheets/` (abstract surface only) | `models/electrolysis/*`, `models/gasification/*`, any concrete unit module |
| Layer 3 (`models/`)        | `core/`                                  | `solvers/`, `flowsheets/`, `themes/`     |
| `core/`                    | nothing inside `pse_ecosystem`           | every other layer                        |

Note the asymmetry around `flowsheets/`: Layer 2 imports `BaseFlowsheet` to
iterate `flowsheet.units`, which transitively pulls in `BaseUnit`. That is
intentional and safe — `BaseUnit` is part of the *contract surface*. The
boundary that matters is "no concrete-physics module name appears in
`solvers/*.py`," which the test enforces by source-grep.

---

## 6. Roadmap — how this scales

The contract is unchanged across each phase below. Only Layer 3 grows.

1. **Toy linear models (today, v0).** PEM and a quadratic gasifier.
   `is_exact=True` on linear units gives one-shot LP solves.
2. **Hand-coded non-linear models.** Override `linearize()` with
   analytical Jacobians. SLP convergence in <10 iterations is typical
   for well-scaled flowsheets.
3. **Fitted ML surrogates.** Train surrogates from Aspen / gPROMS runs.
   Implement `residual` in JAX or PyTorch and override `linearize()` with
   `jax.jacfwd(self.residual)`. Layer 2 sees no change.
4. **Black-box surrogates without gradients.** Skip the override entirely;
   the FD fallback in `BaseUnit.linearize` produces a noisy but workable
   Jacobian. Cost shifts to extra evaluations, not architectural rewrites.
5. **MINLP / OA / Benders for Mode 2.** Replace the v0 sequential MILP→SLP
   in `Orchestrator._solve_flexible` with proper cuts. The Handshake
   Protocol does not change.
6. **Temporal / multi-period models.** Variable namespace expands from
   `unit.var` to `unit.var[t]`. Builders index over time; units optionally
   provide hour-of-year sensitivities. Still no contract change.

---

## 7. Verification (post-implementation)

```bash
pip install -e .[dev,solvers]
pytest                                        # base-unit + SLP + boundary tests
python examples/electrolysis_v0.py --mode 1   # Mode-1 demo
python examples/electrolysis_v0.py --mode 2   # Mode-2 MILP→SLP demo
```

The boundary test (`test_solvers_do_not_import_concrete_unit_modules`)
fails the moment a developer accidentally imports a unit module from
inside `solvers/`. That is the canary for architectural regressions.

---

## v0.1.0 Extensions

### Data Layer (`pse_ecosystem/data/`)

A new, optional fourth layer sits **above** Layer 1 and is never called by
the solver stack. It provides time-series weather and demand profiles that
flowsheet factories consume when building time-indexed optimisation problems.

```
pse_ecosystem/data/weather.py
  SiteData           — GPS + timezone descriptor
  fetch_solar_profile()     — pvlib Ineichen clearsky GHI [W/m²]
  fetch_wind_profile()      — synthetic Weibull wind speed [m/s]
  generate_demand_profile() — flat or seasonal H2 demand
  electricity_price_from_solar() — price proxy from GHI
  WeatherDrivenFlowsheet    — container linking flowsheet to time-series
```

The data layer has no Handshake objects (no PrimalGuess / LinearizedModel).
Its outputs are plain numpy arrays consumed by factory functions.

### CompositeUnit (hierarchical composition)

`CompositeUnit(BaseUnit)` lives in `flowsheets/base_flowsheet.py` and wraps
a `BaseFlowsheet` as a single `BaseUnit`. This allows nested process
structures — a sub-flowsheet (e.g. a gas-cleaning train) can be a unit in a
parent flowsheet.

**Circular-import resolution:** `CompositeUnit.residual()` must call
`SLPDriver` from `solvers/slp.py`, but `slp.py` already imports
`BaseFlowsheet`. The import is deferred to inside the method body so it
executes only at call time, after both modules are loaded. This is the *only*
sanctioned exception to "Layer 2 must not import Layer 3" — here the
direction is reversed (Layer 3 calls Layer 2 to solve an inner sub-problem).

### Recycle Loop Support (Wegstein)

`TearStreamConfig` in `SLPConfig.tear_streams` enables Wegstein acceleration
for recycle loops. Declare one entry per recycle tear stream variable. The
SLP driver applies the Wegstein update after each LP solve. When `q=0`
(default) it reduces to direct substitution. The `Connection` objects in
`BaseFlowsheet` still enforce recycle equalities in the LP; Wegstein only
accelerates the outer iteration.

`BaseFlowsheet.recycle_streams: List[str]` is a metadata field for
documentation — the solver never reads it.

### Standalone App Structure

```
python -m pse_ecosystem [CLI args]       # via ui/__main__.py
streamlit run pse_ecosystem/ui/app_streamlit.py  # GUI stub
```

The Streamlit app defers all imports inside `main()` so the module is
importable without Streamlit installed. The CLI auto-discovers themes via
the registry, so new themes appear without changing `entry.py`.
