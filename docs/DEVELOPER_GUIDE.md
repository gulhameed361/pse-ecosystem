# Developer Guide

> Companion to [`ARCHITECTURE.md`](ARCHITECTURE.md) (the high-level
> blueprint), [`THEORY_REFERENCE.md`](THEORY_REFERENCE.md) (the maths) and
> [`USER_MANUAL.md`](USER_MANUAL.md) (the operator's view). This document
> is the code-first manual for anyone extending the platform.

---

## 0. v1.4.1 — Conventions you must know before extending

### 0.0 v1.4.1 developer notes

Three new patterns you must be aware of when extending the platform:

**Bound-saturation guard.** `SolveResult.bound_active` is populated on every
CONVERGED return from the SLP driver. If your new unit model's default bounds
are too tight relative to the expected operating range, users will see the
yellow warning banner and the "Bound Saturation" Excel sheet. Fix by widening
the default `feed_max`/`P_max`/`W_max` in the unit's `Params` dataclass to
cover the full engineering envelope, not just a toy default.

**Connection validation.** `BaseFlowsheet.validate()` now checks every
`Connection.var_a` and `Connection.var_b` against the union of unit-produced
variables. When writing a new template in `flowsheets/industrial/`, use
`fs.connect(unit_a.outlet_port, unit_b.inlet_port)` (which generates the
correct variable names via `StreamPort.variable_names()`) instead of
hand-coding variable name strings in `Connection(var_a=..., var_b=...)`.
A typo in a hand-coded string will now raise a clear `ValueError` at solve time.

**UI unit callback factory.** If you add a new float `ParamSpec` with a unit
in a recognised conversion family (`UNIT_FAMILIES` in `flowsheet_service.py`),
the on_change callback is wired automatically — no extra code required in
`app_streamlit.py`. If you add a new conversion family, also add a round-trip
test to `TestUnitConversions` and `TestUnitAutoConversionCallback`.

### 0.1 Versioning — single source of truth

`pse_ecosystem/__init__.py` exports `__version__`. Every other place that
displays a version (`pyproject.toml`, the Streamlit Dashboard caption, the
test suite) reads it from there. To cut a new release, edit `__init__.py`
and `pyproject.toml` and update the doc banners; the UI follows
automatically. The test `tests/test_unrestricted_flowsheet.py::test_pyproject_version_matches_package`
will fail if these drift.

### 0.2 Help Center loader

`pse_ecosystem/ui/app_streamlit.py::_load_doc(name)` reads `docs/<name>.md`
via `pathlib` and caches the result with `@st.cache_data` keyed on the
file's `mtime`. To add a new doc to the Help Center: drop the markdown into
`docs/`, then append `(tab title, filename)` to the `_tabs`/`_files` lists
in `_page_help_center()`. No imports from Layer 2 or Layer 3.

### 0.3 Custom flowsheet scaling

The Custom Flowsheet builder accepts arbitrarily many units. When adding a
new unit type to `AVAILABLE_UNITS`, make sure its `UNIT_PARAM_SPECS` entries
include `help` text — the 3-column grid relies on tooltips for pedagogy.
The `TYPE_ID_SUGGESTIONS` slug feeds the smart Unit ID dropdown; the widget
keys embed `{utype}` so the dropdown resets when the user switches the Type.

### 0.4 Unit Management System (UMS) — backend handling

The UMS lives entirely at Layer 1, in `pse_ecosystem/ui/flowsheet_service.py`:

- `UNIT_FAMILIES` (module-level dict). One sub-dict per physical dimension
  — `temperature`, `pressure`, `mass_flow`, `mass`, `power`, `energy`. Each
  sub-dict maps a unit string (e.g. `"°C"`, `"atm"`, `"kW"`) to a
  `(to_si, from_si)` lambda pair. The **first key in each sub-dict is the SI
  baseline** (`K`, `Pa`, `kg/s`, `kg`, `W`, `J`) — relied upon by
  `si_baseline_of()`. Preserve that ordering when extending the table.
- `supported_display_units(native_unit)` — returns the list of display
  alternatives for a given native unit, or `[]` for dimensionless and
  compound units. Drives the Streamlit unit-picker dropdown.
- `to_native(value, display_unit, native_unit)` — converts user input to
  the unit each `ParamSpec` declares. **This is the only place** the
  display→native conversion happens; nothing downstream sees display units.
- `from_native` is the inverse, used to seed the UI input box with the
  ParamSpec default expressed in the user's selected display unit.

The Streamlit Excel exporter calls `app_streamlit._infer_si_unit(var_name)`
to annotate each row of the Stream Table and Unit Performance sheets with
the SI tag of its value. The heuristic is name-based — `T*` → K, `P*` → Pa,
`F_*` → kg/s, `n_*` → mol/s, `W_shaft` / `duty_kW` etc. — keep variable
naming conventions stable to avoid breaking inference.

**Extending the UMS:** to add a new conversion family (e.g. molar flow
families, length units, time units):

1. Define `_FAMILY_<NAME>` at module scope in `flowsheet_service.py`.
2. Register it under a new key in `UNIT_FAMILIES`.
3. Add the relevant suffix to `_infer_si_unit` in `app_streamlit.py` so the
   Excel exporter recognises the new dimension.
4. Add round-trip tests in `tests/test_unrestricted_flowsheet.py::TestUnitConversions`.

**Do not** push UMS logic into Layer 2 or Layer 3. The backend stays in SI;
the UMS is an input-side convenience that lives behind the Layer-1
flowsheet service.

---

## 1. Repo Layout & Layer Map

### 1.1 Folder-by-folder tour

```
pse_ecosystem/
├── core/                       # Cross-layer contracts. Pure data.
│   ├── contracts.py            #   PrimalGuess, LinearizedModel, UnitResponse,
│   │                           #   SolveResult, SolveMode, SolverStatus
│   └── registry.py             #   ThemeSpec / ApplicationSpec registry
├── models/                     # ── LAYER 3 ── Knowledge / physics
│   ├── base_unit.py            #   Abstract BaseUnit + finite-difference Jacobian
│   ├── electrolysis/           #   PEMToy
│   ├── gasification/           #   GasifierToy
│   ├── reactors/               #   StoichiometricReactor, CSTRHF, PFRHF, EquilibriumReactor, GibbsReactor
│   ├── separators/             #   FlashVLHF, FlashSL, DistillationHF, SeparatorHF
│   ├── mixers/                 #   MixerHF
│   ├── heat_exchangers/        #   HeatExchangerNTU, ShellTubeHX, HeatExchanger1D
│   ├── pressure_changers/      #   Compressor, Pump, Valve
│   ├── properties/             #   ideal_gas.py (Shomate Cp/H), vle.py (Antoine K-values)
│   ├── costing/                #   sslw_costing.py, economic_engine.py
│   ├── biomass/                #   BiomassStorageHF, BiomassGasifierHF, WGSReactorHF, H2SeparatorPSA
│   ├── dac/                    #   TVSAContactor, ElectrolyserHF, MethanationReactor
│   └── power/                  #   CHPUnit
├── flowsheets/                 # Topology containers (between L2 and L3)
│   ├── base_flowsheet.py       #   BaseFlowsheet, Connection, CompositeUnit (super-unit)
│   ├── hydrogen/               #   electrolysis_grid.py
│   ├── industrial/             #   green_hydrogen, power_to_methanol, gasification_to_power, syngas_production
│   └── small/                  #   adiabatic_cstr_flash, compression_train, mixer_settler, distillation_column
├── solvers/                    # ── LAYER 2 ── Decision / optimisation
│   ├── orchestrator.py         #   SolveMode dispatcher (SLP/NLP/TRF/Adaptive)
│   ├── slp.py                  #   SLPDriver + SLPConfig + TearStreamConfig
│   ├── lp_builder.py           #   build_lp(), select_lp_solver()
│   ├── milp_builder.py         #   build_milp(), TechnologyChoice
│   ├── nlp_builder.py          #   scipy L-BFGS-B full-NLP driver
│   ├── trust_region_driver.py  #   Filter/Funnel Trust-Region driver
│   ├── scaling.py              #   compute_scaling_factors()
│   └── trf/                    #   filter.py, funnel.py, util.py
├── themes/                     # Theme metadata only
│   └── hydrogen.py
└── ui/                         # ── LAYER 1 ── Streamlit application
    ├── app_streamlit.py        #   4-page Streamlit UI
    ├── flowsheet_service.py    #   Sole Layer-1 bridge to Layer-3 factories
    └── entry.py                #   CLI: pse-ecosystem ...
```

### 1.2 Where new code belongs (and where it doesn't)

| You are adding... | Lives in | Must not touch |
|---|---|---|
| A new electrolyser/reactor/separator | `models/<route>/<unit>.py` | `solvers/`, `core/` |
| A new theme (ammonia, methanol, CCS) | `themes/<theme>.py` + `flowsheets/<theme>/` | `solvers/`, `core/` |
| A new flowsheet topology under an existing theme | `flowsheets/<theme>/<topo>.py` | `solvers/`, `core/` |
| A new solver strategy (e.g. multi-period) | `solvers/<driver>.py` | `models/<route>/*` |
| A new contract field on the Handshake | `core/contracts.py` (and update both layers) | n/a — this is a breaking change |
| UI work (Streamlit, FastAPI) | `ui/<frontend>/` | `models/`, `solvers/` directly — go via `Orchestrator` |

### 1.3 The two unbreakable layer-boundary rules

1. **`solvers/*.py` must never directly import a concrete unit module.**
   Only `core/contracts.py` and the abstract `BaseFlowsheet` surface are
   allowed. The test
   `tests/test_slp_convergence.py::test_solvers_do_not_import_concrete_unit_modules`
   greps `solvers/*.py` for forbidden imports and fails the suite if it
   sees `pse_ecosystem.models.electrolysis` or `…gasification` in there.
2. **`models/*.py` must never import from `solvers/`, `flowsheets/`, or
   `themes/`.** Units only need `core/contracts.py` and `models/base_unit.py`.

If you are tempted to break either rule, you are about to leak knowledge
across layers — re-shape the work into a contract change in `core/` instead.

---

## 2. The Handshake Protocol — Layer 2 ↔ Layer 3

The single pipe between Layer 2 and Layer 3. Three dataclasses in
[`pse_ecosystem/core/contracts.py`](../pse_ecosystem/core/contracts.py).

### 2.1 `PrimalGuess` — Layer 2 → Layer 3

```python
@dataclass(frozen=True)
class PrimalGuess:
    values: Dict[str, float]      # variable name → current value at iter k
    iteration: int = 0            # SLP iteration counter
    metadata: Dict[str, Any] = ...
```

Sent to every unit at the start of each SLP iteration. The variable names
are the only handle Layer 2 has on the unit's state.

### 2.2 `LinearizedModel` — Layer 3 → Layer 2

```python
@dataclass
class LinearizedModel:
    unit_id: str
    variables: List[str]                  # column ordering for x0 and J
    x0: np.ndarray                        # shape (n,) — linearisation point
    f0: np.ndarray                        # shape (m,) — residual at x0
    J:  np.ndarray                        # shape (m, n) — Jacobian ∂f/∂x at x0
    bounds: Dict[str, Tuple[float, float]]
    objective_terms: Dict[str, float]     # var → linear cost coefficient
    is_exact: bool = False                # True ⇒ unit is genuinely linear
    trust_region: Optional[float] = None  # unit-supplied step cap (variable units)
    kpi_gradients: Dict[str, np.ndarray] = ...
```

Returned from `unit.linearize(guess)`. This tuple is **everything** the
solver needs to construct LP rows for that unit.

### 2.3 `UnitResponse` — Layer 3 → Layer 2 (true evaluation)

```python
@dataclass
class UnitResponse:
    unit_id: str
    outputs: Dict[str, float]
    kpis:    Dict[str, float]
    residual: np.ndarray              # f(x) at the candidate point — the truth
    feasible: bool
    diagnostics: Dict[str, Any]
```

Returned from `unit.evaluate(x)`. Used **only** for residual checks at the
end of an SLP iteration and for final KPI reporting; never required to
solve an LP.

### 2.4 How LP rows fall out of the handshake

Layer 2 turns each `LinearizedModel` into LP rows by rearranging the
Taylor expansion `f0 + J · (x − x0) = 0`:

```
J · x  =  J · x0 − f0
```

so each row of `J` produces one equality constraint in the Pyomo model.
See [`solvers/lp_builder.py`](../pse_ecosystem/solvers/lp_builder.py)
lines 96–116 for the actual loop.

For the full mathematical derivation see
[`THEORY_REFERENCE.md` §7](THEORY_REFERENCE.md#7-successive-linear-programming).

### 2.5 Why this contract scales

Same five lines describe a unit at every stage of the platform's life:

| Phase | `residual()` implementation | `linearize()` implementation |
|---|---|---|
| Toy linear (today) | hand-coded equality | analytical, sets `is_exact=True` |
| Toy non-linear (today) | hand-coded polynomial / equation | analytical Jacobian override |
| ML surrogate trained from Aspen | calls `model(x).numpy()` | `jax.jacfwd(self.residual)(x)` |
| Black-box surrogate | calls remote API | use BaseUnit's FD fallback (override `is_linear=False`) |

Layer 2 sees no difference. Adding ML surrogates is a unit-by-unit task,
not an architectural rewrite.

---

## 3. Layer 3 — Adding a Unit Model

### 3.1 Subclassing `BaseUnit`

[`pse_ecosystem/models/base_unit.py`](../pse_ecosystem/models/base_unit.py)
defines:

```python
class BaseUnit(ABC):
    unit_id: str = "unit"
    is_linear: bool = False
    trust_region: float | None = None
```

A new unit subclasses `BaseUnit`, sets a stable `unit_id`, optionally
flips `is_linear` to `True` for genuinely linear models, and optionally
sets a `trust_region` radius.

### 3.2 Required methods

| Method | Returns | Purpose |
|---|---|---|
| `variables(self)` | `List[str]` | Canonical ordering of variable names |
| `bounds(self)` | `Dict[str, Tuple[float, float]]` | Per-variable `(lower, upper)` bounds |
| `residual(self, x)` | `np.ndarray` shape `(m,)` | f(x); `m` may be 0 for "no constraints" |
| `objective_contribution(self, x)` | `Dict[str, float]` | Linear cost coefficient per variable |

### 3.3 Optional hooks

| Method | Default | Override when |
|---|---|---|
| `kpis(self, x)` | empty dict | You want LCOH / emissions / annual quantities surfaced |
| `kpi_gradients(self, x)` | empty dict | You can supply analytical KPI sensitivities |
| `linearize(self, guess)` | central-difference fallback | You have analytical or AD Jacobians |
| `evaluate(self, x)` | wraps `residual` + `kpis` | You need custom diagnostics in `UnitResponse` |

### 3.4 The `unit_id.varname` naming convention

Variable names should be globally unique across the flowsheet. The
standard pattern is to expose a property per variable that prefixes the
unit's id:

```python
@property
def v_h2(self) -> str:
    return f"{self.unit_id}.h2_kg_per_h"
```

Two PEM stacks instantiated as `PEMToy("pem_a")` and `PEMToy("pem_b")`
therefore expose disjoint variable sets and the flowsheet decides whether
they share a feed via an explicit `Connection`.

### 3.5 The finite-difference fallback

If you don't override `linearize()`, `BaseUnit.linearize` (in
[`base_unit.py`](../pse_ecosystem/models/base_unit.py) lines 105–144)
applies a central-difference scheme with a step size scaled to the
variable magnitude (`max(1e-6 * |x|, 1e-9)`). This is enough to make a
brand-new toy unit work end-to-end with the SLP driver before you ever
write a Jacobian.

When to override:

- The unit is **genuinely linear** — write the analytical override and
  set `is_exact=True` in the returned `LinearizedModel` so the SLP
  driver short-circuits to a single LP solve.
- The unit is **non-linear with cheap analytical derivatives** — write
  the analytical override (see `gasifier_toy.py` for the canonical
  example).
- The unit has **AD-able** residuals (JAX/PyTorch) — return
  `jax.jacfwd(self.residual)(x)` from a thin `linearize` wrapper.

When to leave it alone:

- The unit is a black-box ML surrogate with no gradient API. The FD
  fallback works; you pay 2*n* extra residual evaluations per SLP
  iteration.

### 3.6 Walk-through: implementing a toy reactor end-to-end

```python
# pse_ecosystem/models/reaction/cstr_toy.py
from dataclasses import dataclass
import numpy as np
from typing import Dict, List, Tuple
from pse_ecosystem.models.base_unit import BaseUnit


@dataclass
class CSTRParams:
    k: float = 0.5            # 1st-order rate constant (1/h)
    feed_max_kg_per_h: float = 1000.0
    feed_price_per_kg: float = 0.10


class CSTRToy(BaseUnit):
    """First-order conversion: product = (1 - exp(-k·tau)) · feed.

    For toy purposes we approximate with a linearised conversion at the
    nominal residence time."""

    is_linear = False
    trust_region = 100.0       # kg/h — keep linearisation local

    def __init__(self, unit_id: str = "cstr", params: CSTRParams | None = None):
        self.unit_id = unit_id
        self.params = params or CSTRParams()

    @property
    def v_feed(self):    return f"{self.unit_id}.feed_kg_per_h"
    @property
    def v_product(self): return f"{self.unit_id}.product_kg_per_h"

    def variables(self) -> List[str]:
        return [self.v_feed, self.v_product]

    def bounds(self) -> Dict[str, Tuple[float, float]]:
        feed_max = self.params.feed_max_kg_per_h
        return {self.v_feed: (0.0, feed_max), self.v_product: (0.0, feed_max)}

    def residual(self, x: Dict[str, float]) -> np.ndarray:
        # product = feed * (1 - exp(-k * tau)),  tau implicit in k
        feed = x[self.v_feed]
        prod = x[self.v_product]
        conv = 1.0 - np.exp(-self.params.k)
        return np.array([prod - conv * feed])

    def objective_contribution(self, x: Dict[str, float]) -> Dict[str, float]:
        return {self.v_feed: self.params.feed_price_per_kg * 8000.0}
```

That's a complete, working unit. The FD fallback in `BaseUnit` will
produce a Jacobian; the SLP driver will iterate on it; the LP builder
will translate it into Pyomo rows. No solver code is touched.

### 3.7 Unit-test patterns

Two patterns from
[`tests/test_base_unit.py`](../tests/test_base_unit.py) you should reuse:

**Pattern A — FD vs analytical Jacobian agreement.** Demonstrates that
your analytical override matches the BaseUnit FD fallback to ~1e-5:

```python
def test_fd_fallback_matches_analytical(my_unit):
    guess = PrimalGuess(values={...})
    lin_a = my_unit.linearize(guess)
    lin_fd = BaseUnit.linearize(my_unit, guess)
    np.testing.assert_allclose(lin_a.J, lin_fd.J, atol=1e-5)
```

**Pattern B — Linearisation self-consistency.** `f0 + J·(x − x0)`
evaluated at `x = x0` must equal `f0`. Catches off-by-one errors in `J`:

```python
def test_predicted_residual_at_x0_equals_f0(my_unit):
    guess = PrimalGuess(values={...})
    lin = my_unit.linearize(guess)
    np.testing.assert_allclose(lin.predicted_residual(guess.values), lin.f0, atol=1e-12)
```

---

## 4. Layer 3 — Adding a Theme & Application

### 4.1 Folder structure for a new theme

```
pse_ecosystem/
├── flowsheets/
│   └── ammonia/
│       ├── __init__.py
│       └── haber_bosch.py        # Flowsheet factory function(s)
├── models/
│   └── ammonia/
│       ├── __init__.py
│       └── haber_bosch_toy.py    # Unit models specific to this route
└── themes/
    └── ammonia.py                # ThemeSpec registration
```

### 4.2 Building a flowsheet

A flowsheet is just a `BaseFlowsheet` instance. Three things go in:
units, inter-unit connections, and flowsheet-level extra equalities.

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
from pse_ecosystem.models.ammonia.haber_bosch_toy import HaberBoschToy

def make_haber_bosch(nh3_demand_kg_per_h: float = 100.0) -> BaseFlowsheet:
    rx = HaberBoschToy(unit_id="reactor")
    fs = BaseFlowsheet(
        name="ammonia.haber_bosch_basic",
        units=[rx],
        connections=[],                      # no inter-unit links yet
        objective_kpi="annual_cost",
    )
    # Demand: reactor.nh3_kg_per_h == demand
    fs.extra_equalities.append(({rx.v_nh3: 1.0}, nh3_demand_kg_per_h))
    return fs
```

`Connection(var_a, var_b)` is for stream connectivity between two units;
`extra_equalities` is for flowsheet-level relations the user injects
(demand satisfaction, totals, etc.).

### 4.3 Registering a `ThemeSpec`

```python
# pse_ecosystem/themes/ammonia.py
from pse_ecosystem.core.registry import (
    ApplicationSpec, ThemeSpec, register_theme,
)
from pse_ecosystem.flowsheets.ammonia.haber_bosch import make_haber_bosch

AMMONIA_THEME = ThemeSpec(
    name="ammonia",
    description="Ammonia synthesis (Haber–Bosch and variants).",
    applications={
        "haber_bosch_basic": ApplicationSpec(
            name="haber_bosch_basic",
            description="Toy single-reactor Haber–Bosch.",
            flowsheet_factory=make_haber_bosch,
        ),
    },
)

register_theme(AMMONIA_THEME)
```

### 4.4 Hooking into `ui/entry.py`

[`ui/entry.py`](../pse_ecosystem/ui/entry.py) imports
`pse_ecosystem.themes.hydrogen` for its registration side-effect. To
expose the new theme through the CLI:

```python
import pse_ecosystem.themes.hydrogen   # noqa: F401
import pse_ecosystem.themes.ammonia    # noqa: F401   ← add this line
```

The `--theme` choice list comes from `list_themes()` so it picks up the
new entry automatically.

---

## 5. Layer 2 — Solver Internals

### 5.1 Orchestrator dispatch

[`solvers/orchestrator.py`](../pse_ecosystem/solvers/orchestrator.py)

```
Orchestrator.solve()
  ├─ if mode == FIXED_LP:        → _solve_fixed()  → SLPDriver.run()
  └─ if mode == FLEXIBLE_MILP:   → _solve_flexible()
                                    ├─ build_milp at initial guess
                                    ├─ extract (x*, y*)
                                    ├─ if all selected units linear → return
                                    └─ else clone flowsheet, force inactive
                                       flow vars to 0, run SLPDriver from x*
```

The key invariant: the Orchestrator only ever calls `unit.linearize(...)`
and `unit.residual(...)` indirectly — through `SLPDriver`, `build_lp`,
and `build_milp`. It never imports a concrete unit module.

### 5.2 SLPDriver loop

[`solvers/slp.py`](../pse_ecosystem/solvers/slp.py) lines 99–233.

```
state: x_k = x0;  Δ = trust_region_init;  prev_kpi = +∞

for k in 0..max_iter-1:
    # ── Layer-3 round ──
    lin_models ← [unit.linearize(PrimalGuess(x_k, k)) for unit in flowsheet]

    if k == 0 and every model.is_exact:
        return single LP solve              # "linear short-circuit"

    # ── Layer-2 round ──
    model ← build_lp(lin_models, flowsheet, x_anchor=x_k, tr_multiplier=Δ if TR on)
    try:
        x_{k+1}, lp_obj ← solve(model)
    except RuntimeError:
        treat as INFEASIBLE ⇒ shrink Δ ⇒ retry (or give up at Δ_min)

    # ── Validate against TRUE physics ──
    true_residual ← concat(unit.residual(x_{k+1}) for each unit)
    true_kpi      ← Σ objective_terms · x_{k+1}

    # ── Convergence test (all three must hold) ──
    if step < eps_x and ‖true_residual‖∞ < eps_f and Δkpi < eps_kpi:
        return CONVERGED

    # ── Trust-region update ──
    ρ = (prev_kpi − true_kpi) / (last_lp_obj − lp_obj)
    if ρ < ρ_shrink:  Δ ← max(Δ/2, Δ_min)
    if ρ > ρ_grow:    Δ ← min(Δ·2, Δ_max)

    x_k = x_{k+1}; prev_kpi = true_kpi; last_lp_obj = lp_obj

return MAX_ITER
```

### 5.3 Convergence criteria — what each catches

| Criterion | Default | Catches |
|---|---|---|
| `eps_x` (relative step norm) | 1e-4 | LP no longer moving |
| `eps_f` (true-residual norm) | 1e-4 | linearisation has converged to actual physics |
| `eps_kpi` (relative KPI delta) | 1e-3 | objective no longer improving |

All three must hold simultaneously. Step alone isn't enough — you can
sit on a stationary point of the linearisation that doesn't satisfy the
true non-linear physics. Residual alone isn't enough — the LP could
oscillate between feasible-but-suboptimal points.

### 5.4 Trust region — per-unit hint × driver multiplier

The trust region is **unit-driven**:

- A unit may set `LinearizedModel.trust_region` to a radius in variable
  units (e.g. the toy gasifier supplies 5000 kg/h).
- The SLP driver carries a scalar multiplier `Δ` ∈ `[trust_region_min,
  trust_region_max]`, adapted via the ρ ratio of actual-vs-predicted
  decrease.
- The LP builder applies `|x_v − x_anchor_v| ≤ trust_region · Δ` for
  every variable owned by a unit that supplied a hint.

Setting `SLPConfig.use_trust_region = False` (the v0 default) disables
the box constraints entirely — sufficient for toy flowsheets. Turn it on
when units have meaningful TR hints and the physics is sharply
non-linear.

### 5.5 LP builder internals

[`solvers/lp_builder.py`](../pse_ecosystem/solvers/lp_builder.py)
builds a `pyo.ConcreteModel` from:

1. The union of all variables across all units, plus connection vars and
   extra-equality vars (`flowsheet.all_variables()`).
2. Per-unit linearised equalities `J · x = J · x0 − f0`.
3. Connection equalities `var_a == var_b`.
4. Flowsheet `extra_equalities` (e.g. demand = Σ producers).
5. Optional per-unit trust-region box constraints.
6. Linear objective: `Σ_units Σ_vars objective_terms[var] · x[var]`.

Bounds are intersected across unit, flowsheet, and `LinearizedModel`
sources before being applied to `pyo.Var`.

### 5.6 MILP builder internals

[`solvers/milp_builder.py`](../pse_ecosystem/solvers/milp_builder.py)
extends the LP with binary technology variables:

1. **Binaries.** One `y_i ∈ {0, 1}` per `TechnologyChoice`.
2. **Flow gating.** For every `flow_variable v` of tech `i`:
   `−M·y_i ≤ x_v ≤ M·y_i`. When `y_i = 0`, `x_v = 0`.
3. **Residual gating** (the v0 fix): for every linearised row of a unit
   gated by tech `i`:
   `|J·x − rhs| ≤ M_row · (1 − y_i)`. When `y_i = 0` the row is fully
   slack — without this an unselected unit's residual would force
   infeasibility because `J·0 − rhs ≠ 0` in general.
4. **At-least-one.** `Σ y_i ≥ 1` so the solver can't pick "do nothing".
5. **Fixed costs.** `Σ tech.fixed_cost · y_i` is added to the objective
   (e.g. annualised CAPEX per technology).

`row_M` for residual gating is sized as
`max(big_M, |rhs| + ‖row‖₁ · big_M, 1)` so it always covers the worst
residual the linearisation can produce inside the bound box.

### 5.7 Sequential MILP→SLP decomposition

For Mode 2 with non-linear units, the v0 strategy is:

1. Build the MILP using linearisations at the initial guess.
2. Solve → `(x*, y*)`. The technology mix is now fixed.
3. Identify "active" units (any unit whose tech binary is 1, plus
   ungated units).
4. Clone the flowsheet, adding `extra_bounds[v] = (0, 0)` for every flow
   variable of an inactive tech.
5. Run `SLPDriver.run(x0=x*)` on the cloned flowsheet to refine
   operations against the true physics.

This is intentionally simple — Outer Approximation, Benders, or
branch-and-bound on the relaxed NLP are all viable upgrades. The
contract doesn't change.

### 5.8 Solver back-end selection

[`select_lp_solver()`](../pse_ecosystem/solvers/lp_builder.py) probes
candidates in this order: `glpk → cbc → appsi_highs → highs`.
[`select_milp_solver()`](../pse_ecosystem/solvers/milp_builder.py) does
`cbc → glpk → appsi_highs → highs`. Pass `preferred="cbc"` (etc.) to
override.

The v0 dependency manifest installs `highspy`; CBC and GLPK are
available via the system package manager when needed.

### 5.9 Infeasibility recovery and HiGHS quirks

Newer Pyomo+HiGHS (`highspy ≥ 1.7`) raises `RuntimeError("A feasible
solution was not found…")` instead of returning a status object when the
LP has no feasible solution. The SLP driver wraps `solver.solve(...)` in
`try/except RuntimeError → SolverStatus.INFEASIBLE` so the loop's
shrink-and-retry path still fires.

Older Pyomo returns `TerminationCondition.infeasible`; both paths land
on the same `SolverStatus.INFEASIBLE` enum value, so the rest of the
driver doesn't care.

---

## 5b. CompositeUnit — Hierarchical Sub-Process Decomposition (v1.2.1)

`CompositeUnit` (in `flowsheets/base_flowsheet.py`) wraps a `BaseFlowsheet` as a single `BaseUnit`. Use it when a sub-process should be solved internally while appearing as an atomic black-box to the parent flowsheet.

### When to use

- A heat-exchange network or gas-cleaning train that has its own internal degrees of freedom.
- Any sub-process that is too non-linear for the parent SLP to handle simultaneously.
- Hierarchical decomposition: solve the inner sub-problem at each outer SLP iteration.

### Architectural note

`CompositeUnit.residual()` calls `SLPDriver` from `solvers/slp.py`. This is the **only sanctioned cross-layer call** from Layer 3 to Layer 2. The import is deferred inside the method body to avoid circular imports. The direction is reversed from the normal flow (Layer 3 calling Layer 2 to solve an inner sub-problem), which is architecturally sound for hierarchical decomposition.

### Usage pattern

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, CompositeUnit
from pse_ecosystem.solvers.slp import SLPConfig

inner_fs = ...  # any BaseFlowsheet
super_unit = CompositeUnit(
    unit_id="sub_process",
    inner_flowsheet=inner_fs,
    exposed_inputs=["inner_unit.feed_var"],   # parent can drive these
    exposed_outputs=["inner_unit.product_var"], # parent reads these
    slp_config=SLPConfig(max_iter=30, verbose=False),
)

parent_fs = BaseFlowsheet("parent", units=[super_unit, ...])
# Wire super_unit like any other unit
```

The inner SLP runs fully at each outer SLP iteration. If the inner solve fails to converge, `CompositeUnit.residual()` returns a large penalty vector (1e6) to signal infeasibility to the outer driver.

### Registering in the UI

Add the `CompositeUnit` wrapping logic to `flowsheet_service.build_composite_unit()` and it becomes available in the Custom Flowsheet assembler "super-unit" checkbox.

---

## 6. Adding a New Layer-2 Strategy

### 6.1 When SLP isn't enough

- **Multi-period / temporal optimisation.** Variable namespace expands
  from `unit.var` to `unit.var[t]`. Build a builder that indexes over
  time; units optionally provide hour-of-year sensitivities.
- **MINLP.** When binaries and non-linearities co-exist and sequential
  MILP→SLP is too crude, swap in Outer Approximation or
  generalised-Benders.
- **Decomposition.** Scenario-based stochastic optimisation, Lagrangian
  relaxation, etc.

### 6.2 How to add a driver without touching Layer 3

A new driver only needs to:

1. Live in `pse_ecosystem/solvers/<your_driver>.py`.
2. Consume `LinearizedModel`s by calling `unit.linearize(guess)` on each
   unit in a flowsheet. Never import a unit class directly.
3. Return a `SolveResult`.

Use `SLPDriver` as the canonical reference implementation.

### 6.3 Hooking through the Orchestrator

Add a new `SolveMode` enum value in `core/contracts.py`, then a
corresponding branch in `Orchestrator.solve()`. All three of the public
API surface (`SolveMode`, `Orchestrator`, `SolveResult`) stay
backwards-compatible because the enum is open-ended.

---

## 7. Testing & Quality Gates

### 7.1 Test layout

```
tests/
├── test_base_unit.py            # FD vs analytical, predicted_residual, bounds
└── test_slp_convergence.py      # Mode 1 / Mode 2 end-to-end, layer-boundary canary
```

Every new unit should ship at least the two patterns from §3.7. Every
new theme should ship at least one end-to-end test that runs the
Orchestrator and asserts convergence.

### 7.2 The layer-boundary canary

```python
_FORBIDDEN_IMPORTS = (
    "pse_ecosystem.models.electrolysis",
    "pse_ecosystem.models.gasification",
)

def test_solvers_do_not_import_concrete_unit_modules():
    solvers_dir = Path(solvers_pkg.__file__).parent
    for py_file in solvers_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_IMPORTS:
            assert forbidden not in text
```

When you add a new unit subpackage (e.g. `models/ccs/`), append it to
`_FORBIDDEN_IMPORTS`. This is the fastest line in the repo to break
when someone accidentally crosses the layer boundary, and the cheapest
to fix.

### 7.3 Running tests inside the venv

```powershell
& "C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1"
pytest -v
```

or, without activating:

```powershell
& "C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\python.exe" -m pytest -v
```

---

## 8. Wrapping a Black-Box Unit

When a simulator (ODE integrator, VLE solver, shortcut method) exists but
is not algebraic, wrap it as a `BaseUnit` subclass. The SLP driver will use
the base-class FD Jacobian automatically.

**Pattern** (using `HDAPFRUnit` as the canonical example):

```python
from pse_ecosystem.models._blackbox.hda_reactor_bb import HDA_Reactor_sim
from pse_ecosystem.models.base_unit import BaseUnit

class HDAPFRUnit(BaseUnit):
    is_linear = False

    def __init__(self, unit_id="hda_pfr"):
        self.unit_id = unit_id
        self._cache_key = None
        self._cache_result = None

    def variables(self):
        # inputs + outputs, all as separate variables
        return [f"{self.unit_id}.F_H2_in", ..., f"{self.unit_id}.F_H2_out", ...]

    def bounds(self):
        return {v: (lo, hi) for v in self.variables()}

    def residual(self, x):
        # 1. Extract inputs, call BB (cached by input key)
        inputs = tuple(round(x[v], 6) for v in self._input_vars)
        if inputs != self._cache_key:
            self._cache_result = HDA_Reactor_sim(*[x[v] for v in self._input_vars])
            self._cache_key = inputs
        sim_out = self._cache_result
        # 2. Residual = output_var - simulator_output
        return np.array([x[v] - sim_out[k] for k, v in enumerate(self._output_vars)])

    def objective_contribution(self, x): return {}
```

Do **not** override `linearize()` — the base-class FD fallback will call
`residual()` with `±step` perturbations for each variable. The cache in
`residual()` avoids redundant simulator calls within a single FD sweep.

**Cost:** Each SLP iteration requires `2*n + 1` simulator evaluations for the
FD Jacobian (n = number of variables). For `HDAPFRUnit` (n=13), that is 27
ODE integrations per iteration. This is acceptable for demos but expensive for
large flowsheets.

---

## 9. Adding Weather-Driven Scenarios

```python
from pse_ecosystem.data.weather import (
    SiteData, fetch_solar_profile, electricity_price_from_solar,
    generate_demand_profile, WeatherDrivenFlowsheet,
)
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only

site = SiteData(51.24, -0.59, 50, "Europe/London", "Surrey_UK")
ghi    = fetch_solar_profile(site, 2023)        # shape (8760,) W/m²
prices = electricity_price_from_solar(ghi)      # shape (8760,) £/kWh
demand = generate_demand_profile(100.0)         # flat 100 kg/h

wdf = WeatherDrivenFlowsheet(
    name="solar_pem",
    base_flowsheet=make_electrolysis_only(100.0),
    solar_ghi=ghi,
    electricity_prices=prices,
    h2_demand=demand,
)

# Solve for each hour (sequential)
from pse_ecosystem.solvers.slp import SLPDriver, SLPConfig
results = []
for hour in range(8760):
    fs = wdf.make_pem_snapshot_flowsheet(hour)
    r  = SLPDriver(fs, SLPConfig()).run()
    results.append(r)
```

`fetch_solar_profile` uses pvlib (install `pse_ecosystem[weather]`).
`fetch_wind_profile` and the price/demand helpers require only numpy.

---

## 10. Standalone App Structure

**CLI (no extra install):**
```bash
python -m pse_ecosystem --theme hydrogen --application electrolysis_only \
       --mode 1 --demand 100
```

**Streamlit GUI (requires `pip install pse_ecosystem[gui]`):**
```bash
streamlit run pse_ecosystem/ui/app_streamlit.py
```

The Streamlit module defers all imports inside `main()` so it can be
imported safely without Streamlit installed. To add a new page, add a
`st.tabs()` or `st.sidebar.radio()` branch inside `main()`.

---

## 11. Registering a New Optimization Objective (v1.5.0.dev)

The objective system is string-dispatch: `build_objective_extra()` in
`pse_ecosystem/ui/flowsheet_service.py` maps mode-label strings to LP
coefficient dicts.  Adding a new objective requires exactly **four steps**:

### Step 1 — Declare the mode in `OBJECTIVE_TIERS`

```python
# flowsheet_service.py
OBJECTIVE_TIERS: Dict[str, List[str]] = {
    "Technical": [..., "Minimize My New Metric"],
    ...
}
```

Choose the tier that best describes whether the metric is purely
physical (`Technical`), purely financial (`Economic`), or a ratio of
cost to physical output (`Technoeconomic`).

### Step 2 — Implement the LP coefficient logic in `build_objective_extra()`

Add an `elif` branch after the existing modes:

```python
if mode == "Minimize My New Metric":
    for v in all_vars:
        if "my_variable_fragment" in v.lower():
            obj[v] = obj.get(v, 0.0) + my_coefficient
```

Rules:
- **Positive coefficient** → minimise the variable (cost, energy, emissions).
- **Negative coefficient** → maximise the variable (production, revenue).
- If the mode requires financial parameters from `ProjectEconomicsConfig`,
  they are available via the `econ_config` argument (already unwrapped at
  the top of `build_objective_extra()`).
- Return `(obj, False)` at the end; only "Feasibility Only" returns `True`.

### Step 3 — Add context-dependent UI inputs in `app_streamlit.py`

In the `_fb_tabs[1]` block, extend the relevant tier expander with the
parameter widgets your new mode needs (e.g., a penalty rate).  Store them
in `st.session_state["objective_config"]` under a clear key so the Solver
Monitor can forward them to `ProjectEconomicsConfig`.

### Step 4 — Write a test

```python
# tests/test_technoeconomic_optimization.py  or  tests/test_objectives.py
def test_minimize_my_new_metric_finds_correct_variable():
    fs = _my_flowsheet()
    extra, force_feas = build_objective_extra(fs, "Minimize My New Metric")
    assert force_feas is False
    relevant = [k for k in extra if "my_variable_fragment" in k.lower()]
    assert len(relevant) >= 1
    for k in relevant:
        assert extra[k] > 0   # or < 0 for maximisation
```

Run `pytest tests/ -q` and confirm 0 failures before committing.

---

## 12. Registering a New Equipment Cost Scaling Factor (v1.5.0.dev)

Use `EquipmentScalingRule` from `pse_ecosystem/models/costing/economic_engine.py`
inside any unit's `capex()` method:

```python
from pse_ecosystem.models.costing.economic_engine import EquipmentScalingRule

class MyReactorHF(BaseUnit):
    def capex(self, x: Dict[str, float]) -> float:
        volume_m3 = x.get(f"{self.unit_id}.outlet.V_m3", self._params.V_m3)
        rule = EquipmentScalingRule(
            reference_cost_USD=500_000,   # C₀ at S₀
            reference_size=10.0,           # S₀ = 10 m³
            scaling_exponent=0.57,         # vessel exponent (Turton et al.)
        )
        return rule.cost_at(volume_m3)
```

Then surface the result in `kpis()`:

```python
def kpis(self, x: Dict[str, float]) -> Dict[str, float]:
    return {"capex_purchase_USD": self.capex(x), ...}
```

The Excel Sheet 2 ("Unit Performance") and Sheet 5 ("Project Economics")
pick up `capex_annual_USD` and `opex_annual_USD` keys automatically from
`result.kpis`.  If your unit contributes annualised cost directly, emit it
under those canonical KPI names; otherwise the post-solve economics sheet
will show zero CAPEX/OPEX for that unit.

For a compiled standalone `.exe` (PyInstaller):
```bash
pip install pyinstaller
pyinstaller --onefile --name pse_ecosystem \
    --add-data "pse_ecosystem:pse_ecosystem" \
    pse_ecosystem/ui/entry.py
```

---

## 11. Future Roadmap

The following are deliberately deferred past v0. Adding any of them
should not require contract changes in `core/`.

- **JAX / PyTorch surrogate units.** Implement `residual()` in JAX,
  override `linearize()` with `jax.jacfwd(self.residual)(x)`. No solver
  changes.
- **Black-box ML units.** Use the FD fallback. Pay the cost in extra
  evaluations.
- **Outer Approximation / Benders for Mode 2.** Replace the sequential
  MILP→SLP in `Orchestrator._solve_flexible` with proper cuts.
- **Multi-period / hourly resolution.** Variable namespace expands to
  include time index; builders gain a time set.
- **Distributed / parallel SLP across scenarios.** Run multiple
  `SLPDriver` instances against scenario-cloned flowsheets in parallel,
  aggregate results.
- **Stochastic / robust optimisation.** Scenario tree at the
  Orchestrator level, scenario probability weights in objective terms.

---

## 12. Registering a New Unit in an Industrial Category (v1.4.0)

The Template Library uses **8 industrial sectors** (v1.4.0 audit H11 added
3 new categories' worth of units and expanded the catalogue to 23 entries).
When you add a new unit and want it to be available in the Custom Flowsheet
builder, register it in **four places** in
`pse_ecosystem/ui/flowsheet_service.py`:

### Step 1 — Add to `AVAILABLE_UNITS`

```python
AVAILABLE_UNITS: Dict[str, str] = {
    # ... existing entries ...
    "MyNewUnit": "Brief description — linear/nonlinear, key physics",
}
```

### Step 2 — Add to `UNIT_CATEGORIES`

Choose the appropriate sector. The 8 sectors and their current v1.4.0 members:

| Sector | Current Unit Types |
|---|---|
| `"Feed/Product"` | `PEMToy`, `GasifierToy` |
| `"Biomass"` | `BiomassStorageHF`, `BiomassGasifierHF`, `WGSReactorHF` |
| `"Reactors"` | `StoichiometricReactor`, `MethanationReactor`, `EquilibriumReactor`, `GibbsReactor` |
| `"Separation/DAC"` | `SeparatorHF`, `FlashVLHF`, `TVSAContactor`, `H2SeparatorPSA`, `DistillationHF` |
| `"Heat Exchange"` | `HeatExchangerNTU`, `ShellTubeHX`, `CoolerHF` |
| `"Power/CHP"` | `ElectrolyserHF`, `CHPUnit` |
| `"Mixing"` | `MixerHF` |
| `"Pressure Changers"` | `Compressor`, `Pump`, `Valve` |

### Step 2a — Add a `TYPE_ID_SUGGESTIONS` slug (v1.3.1+)

The slug feeds the smart Unit ID dropdown in the Custom Builder
(e.g. `comp` → `comp_1`, `comp_2`, …). Keep it short, lower-snake-case,
and unique across the registry:

```python
TYPE_ID_SUGGESTIONS: Dict[str, str] = {
    # ... existing entries ...
    "MyNewUnit": "myu",
}
```

If you omit this step, the UI falls back to a generic ``u1`` / ``u2``
slug — functional but unhelpful in a multi-unit chain. The smart-ID
widget key embeds ``{utype}`` (v1.4.0 audit H11) so the suggestion
refreshes when the user switches Type.

```python
UNIT_CATEGORIES: Dict[str, List[str]] = {
    # ... existing entries ...
    "Reactors": ["StoichiometricReactor", "MethanationReactor", "MyNewUnit"],
}
```

If adding a truly new process sector, create a new key:

```python
UNIT_CATEGORIES["Ammonia Synthesis"] = ["MyNewUnit"]
```

### Step 3 — Add to `_instantiate_unit()`

```python
def _instantiate_unit(utype: str, uid: str, params: dict) -> Any:
    # ... existing blocks ...

    if utype == "MyNewUnit":
        from pse_ecosystem.models.my_module.my_new_unit import MyNewUnit, MyNewUnitParams
        p = MyNewUnitParams(
            key_param=float(params.get("key_param", default_value)),
        )
        return MyNewUnit(uid, params.get("components", ["H2", "CO2"]), p)

    raise ValueError(f"Unknown unit type: {utype}")
```

### Step 4 — Add port names to resolution lists (if using non-standard names)

If your unit's primary outlet/inlet attributes are not in the existing priority lists, add them:

```python
_OUTLET_NAMED = (
    "outlet_port",        # standard
    # ... existing ...
    "my_new_outlet_port", # add here
)
_INLET_NAMED = (
    "inlet_port",         # standard
    # ... existing ...
    "my_new_inlet_port",  # add here
)
```

### Step 5 — Verify

```powershell
pytest tests/test_ui_assembly_logic.py -v
python -c "from pse_ecosystem.ui.flowsheet_service import AVAILABLE_UNITS; print('MyNewUnit' in AVAILABLE_UNITS)"
```

---

## 13. Updating the Shared Component Set for New Chemical Species

The Shared Component Set is the species list users type into the Custom Flowsheet assembler
(e.g. `H2,CO,CO2,H2O,CH4,N2`). Adding a new species requires updates in up to 3 places:

### 13.1 Ideal-gas Cp / enthalpy (Shomate)

Edit `pse_ecosystem/models/properties/ideal_gas.py`, add to `_SHOMATE`:

```python
_SHOMATE["ethanol"] = {
    "A": 102.8,   "B": -46.69, "C": 9.0,   "D": -0.54,
    "E": 0.0,     "F": -217.0, "G": 0.0,   "H": -168.6,
    "T_range": (298.0, 1500.0),
    "T_ref": 298.15,
}
```

NIST Webbook format; units are J/(mol·K) for Cp, kJ/mol for H.
The species is immediately available to any HF unit listing it in `components`.

### 13.2 VLE K-values (Antoine, for flash/distillation units)

Edit `pse_ecosystem/models/properties/vle.py`, add to `ANTOINE`:

```python
ANTOINE["ethanol"] = {"A": 8.04494, "B": 1554.3, "C": 222.65}  # log10(P/mmHg), T in °C
```

Used by `FlashVLHF`, `FlashSL`, `DistillationHF`, and `GibbsReactor`.

### 13.3 Unit model `components` list

When a unit's port uses a hard-coded component list (e.g. WGSReactorHF always uses 6 syngas
components), adding a new species requires overriding the unit's `__init__` or creating a subclass.
For flexible-component units like `SeparatorHF`, `CoolerHF`, and `StoichiometricReactor`,
the user simply adds the new species to the Custom Flowsheet's Shared Component Set — no code change.

**Species compatibility rule:** all ports wired together must share an identical component list
(same strings, same order). `BaseFlowsheet.connect()` enforces this via `validate_connection()`.

### 13.4 Verification

```python
from pse_ecosystem.models.properties.ideal_gas import cp_J_mol_K
print(cp_J_mol_K("ethanol", 400.0))   # should return a positive float
```

```python
from pse_ecosystem.models.properties.vle import K_value
print(K_value("ethanol", 351.0, 101325.0))   # ~1.0 at ~78 °C normal boiling point
```

---

## 14. Trust-Region vs IPOPT Solver Toggle — Decision Logic

Choosing between solver modes is a runtime decision, not a code change. Here is the
decision tree:

```
Is the flowsheet fully linear (all units is_linear=True)?
├─ YES → SLP short-circuits to a single LP in iteration 0. No toggle needed.
└─ NO ↓

Does SLP converge in ≤ 50 iterations with ‖f‖ < 1e-4?
├─ YES → Keep SLP. Fastest option.
└─ NO ↓

Is SLP stagnating (step norm < eps_x but ‖f‖ > eps_f)?
├─ YES → The linearisation is stuck at a non-linear kink.
│        Switch to NLP (SolveMode.NLP_IPOPT).
│        NLP uses scipy L-BFGS-B with analytical Jacobians from linearize().
│        Better at navigating non-convex regions.
└─ NO (still oscillating / infeasible) ↓

Is the Jacobian ill-conditioned? (condition number >> 1e6, or SLP oscillates)
├─ YES → Switch to Trust-Region Filter (SolveMode.TRUST_REGION).
│        The filter/funnel prevents the Maratos effect.
│        Robust but slow — only use when both SLP and NLP fail.
└─ Unsure → Use Adaptive (SolveMode.ADAPTIVE).
             Auto-escalates SLP → NLP → Trust-Region on failure.
```

### Programmatic toggle (SLP → NLP)

```python
from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig

# Try SLP first
result = Orchestrator(fs, SolveMode.FIXED_LP,
                      slp_config=SLPConfig(max_iter=50)).solve()

if result.status.name != "CONVERGED":
    # Escalate to NLP
    result = Orchestrator(fs, SolveMode.NLP_IPOPT).solve()

if result.status.name != "CONVERGED":
    # Last resort: Trust-Region
    result = Orchestrator(fs, SolveMode.TRUST_REGION).solve()
```

### Per-unit trust-region hint

Units can supply a `trust_region` radius in their `LinearizedModel` to limit how far
the SLP driver steps in one iteration:

```python
class MyNonLinearUnit(BaseUnit):
    def linearize(self, guess):
        ...
        return LinearizedModel(
            ...,
            trust_region=500.0,   # max step of 500 variable-units per SLP iteration
        )
```

The SLP driver's scalar multiplier `Δ` is adapted via the ratio-of-actual-vs-predicted decrease ρ.
See `THEORY_REFERENCE.md §7.4` for the full update formula.

### When IPOPT is not available

`SolveMode.NLP_IPOPT` uses `scipy.optimize.minimize(method='L-BFGS-B')` with analytical gradients
from `unit.linearize()`. It does **not** require IPOPT or `idaes-pse` — the name is legacy.
The actual solver is always scipy L-BFGS-B, which ships with the base `scipy` dependency.

As of v1.5.0.dev-AUDIT4, the canonical alias `SolveMode.NLP_SCIPY` (same enum
value) reflects this honestly.  `NLPDriver._ipopt_available()` probes for a
real IPOPT executable on PATH and emits a diagnostic when found; the actual
Pyomo+IPOPT model rewrite is scheduled for v1.6.

---

## 13. Elastic-mode LP and the diagnose() API (v1.5.0.dev-AUDIT4+AUDIT5)

Two algorithmic additions that materially change how to write & debug units.

### 13.1 Elastic-mode LP

`pse_ecosystem/solvers/lp_builder.py::build_lp(elastic_penalty=1e6, …)`
adds non-negative slack pairs `(s+, s−)` to every unit, connection, and
extra equality constraint with a large penalty on `Σ (s+ + s−)`.  The LP
is then **always feasible** — even when the hard-equality version is not.

The SLP driver calls this automatically whenever the normal LP returns
INFEASIBLE.  Two cases:

| Total slack after elastic solve | SLP action |
|---|---|
| `< cfg.elastic_slack_tol` (default 1e-3) | Accept the step as effectively feasible; cancel the INFEASIBLE flag; subtract the slack penalty from the reported objective. |
| `≥ cfg.elastic_slack_tol` | Take a damped 0.3 × step toward the elastic solution and continue. Skips trust-region adaptation for this iteration. |

This **resolves the v1.4.x "infeasible at minimum trust-region radius after
3 restarts"** failure mode for industrial flowsheets where tight
`extra_bounds` + nonlinear residuals make locally hard equalities infeasible.

To disable: `SLPConfig(elastic_fallback=False)`.

### 13.2 `BaseFlowsheet.diagnose()`

```python
diag = fs.diagnose()
# {"errors": [...], "warnings": [...], "info": [...]}
```

Non-raising pre-solve validator.  Detects:

| Category | Triggers |
|---|---|
| Errors   | Unknown variable references in `extra_*` dicts, unknown connection vars, inverted bounds (`lo > hi`) |
| Warnings | Very-wide bounds (span > 1e8), orphan units (no incoming/outgoing connection) |
| Info     | Counts: units, variables, connections, extra equalities, extra bounds, objective extras |

The Streamlit Flowsheet Builder page calls this from a "Pre-solve Validator"
expander.  When writing a new template, **always** call `fs.diagnose()` in
a unit test to catch wiring oversights at build time.

### 13.3 Per-residual-row LP scaling

`scaling.compute_residual_row_scaling(linearizations, floor=1.0)` returns
`1 / max(‖J_row‖∞, floor)` per row.  Apply via
`SLPConfig(scale_rows=True)`; the LP builder rescales each row of J and f0
so the LP solver sees well-balanced constraint magnitudes.

**Off by default** to preserve v1.5 LP topology bit-for-bit.  Turn on when
your flowsheet mixes element balances at 100 mol/s with equilibrium
residuals at 1e-3 mol²/s — typical symptom is HiGHS spending many simplex
iterations to find a feasible basis.

---

## 14. CGE KPI convention (v1.5.0.dev-AUDIT5)

`BiomassGasifierHF.kpis()` emits **two CGE values**:

- `<unit>.CGE_LHV_percent` — `100 × LHV(syngas) / LHV(biomass)`.
  Can exceed 100 % for steam gasification.
- `<unit>.CGE_with_steam_percent` — same numerator, but denominator
  includes `h_steam(T) × ṁ_steam`.  Bounded by ≤ 100 % per 2nd law.

The legacy bare `CGE_percent` key is now an alias for `CGE_LHV_percent`.
Any new biomass-like unit that adds external-heat-supply inputs should
follow the same convention: emit both a bare-LHV and a corrected variant.
