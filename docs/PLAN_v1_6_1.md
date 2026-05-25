# PSE Ecosystem v1.6.1 — Polish & Activation Release

## Context

The post-release audit (`docs/AUDIT_v1_6.md`) found v1.6 to be structurally
sound but **feature-rich-unwired**: dynamics, sizing modes, parity, relief
sizing, and HAZOP infrastructure all exist in code but have no UI page and
no in-tree consumers. Two source files have grown into 3 000-line monoliths.
Every load-bearing doc still reads "v1.5.2".

v1.6.1 is a **3–4 week polish sprint** that closes those gaps *before*
v1.7 stacks new capabilities on top. The principle: **activate, don't
accumulate.** Every feature shipped in v1.6 should have a UI surface, a
documented walkthrough, and at least one in-tree consumer.

**Targets**: 1050+ tests passing (currently 998) · zero new workstream-scale
features · 4 case studies runnable end-to-end · all docs at v1.6.1.

---

## Scope Overview (8 sub-tracks, 3–4 weeks)

| # | Sub-track | Days | Risk |
|---|---|---|---|
| P.1 | Refactor `flowsheet_service.py` into 5 modules | 4–5 | Med |
| P.2 | Split `app_streamlit.py` into per-page modules | 2–3 | Low |
| P.3 | Doc refresh — Architecture, System State, Dev Guide, User Manual, CHANGELOG | 5 | Low |
| P.4 | Analytical Jacobians for 5 highest-traffic units | 5–7 | Med |
| P.5 | Move `TechnologyChoice` to `core/contracts.py` + OPEX-convention safeguards | 1 | Low |
| P.6 | Wire `available_units_for_persona` into Custom Builder UI | 1 | Low |
| P.7 | Add UI pages: Validation, Pinch preview, Dynamics, Relief Sizing | 3–4 | Med |
| P.8 | Build 4 PSE Ecosystem flowsheet templates matching the v1.6 case studies | 4–5 | Med |

> **No new capability workstreams.** v1.7's Pinch, UQ, Multi-objective,
> PR-NRTL, Control tracks remain queued. This sprint exists *only* to
> harden what's already there.

---

## P.1 — Refactor `flowsheet_service.py`

**Current state**: 3 392 lines mixing 7 distinct concerns.

**Target structure** under `pse_ecosystem/ui/`:

```
pse_ecosystem/ui/
  flowsheet_service.py      # ~600 lines — thin facade re-exporting from below
  catalogue.py              # AVAILABLE_UNITS, UNIT_CATEGORIES, persona filters
  instantiate.py            # _instantiate_unit factory (~700 lines)
  templates/
    registry.py             # TemplateSpec + _REGISTRY + loaders
    _loaders.py             # per-template build functions
  economics_bridge.py       # compute_project_economics, KPI rollups
  safety_bridge.py          # compute_safety_margins, ASME / flammability hooks
  port_resolver.py          # _primary_inlet / _primary_outlet + _INLET_NAMED tables
```

**Acceptance**:
- `from pse_ecosystem.ui.flowsheet_service import *` keeps every existing
  public symbol (deprecation-free re-export shim).
- Every existing test passes unchanged.
- `git log --stat` shows ~3000 lines moved, ~500 lines added (facade
  module + new test).

**Risk**: every UI page and several solver tests transitively import
from `flowsheet_service`. A thin facade with `from .catalogue import *`
prevents breakage during the move.

---

## P.2 — Split `app_streamlit.py`

**Current state**: 2 714 lines holding 7 `_page_*` functions, `main()`,
plus shared helpers.

**Target structure**:

```
pse_ecosystem/ui/
  app_streamlit.py           # main() + persona toggle + page list (~200 lines)
  pages/
    __init__.py
    dashboard.py             # _page_dashboard (~100 lines)
    flowsheet_builder.py     # _page_flowsheet_builder (~800 lines, biggest)
    site_weather.py          # _page_gps_weather
    solver_monitor.py        # _page_solver_monitor
    scenario_manager.py      # _page_scenario_manager
    solve_history.py         # _page_solve_history
    help_center.py           # _page_help_center
  shared/
    state.py                 # _init_state, session-state keys
    formatting.py            # _infer_si_unit, number formatters
    plotly_helpers.py        # PSE_PLOTLY_TEMPLATE + layout safe-unpack
```

**Acceptance**:
- Streamlit's `st.Page(_page_*, title=...)` API in `app_streamlit.py`
  imports the functions from `pages/` modules; nothing else changes.
- `tests/test_streamlit_smoke.py` passes.

---

## P.3 — Documentation Refresh

Update every load-bearing doc to v1.6.1 content. Each gets a "What's New"
section plus diffs against the v1.5.2 content already there.

| Doc | v1.6.1 work |
|---|---|
| `ARCHITECTURE.md` | New section on property-package framework, sizing-mode hook, dynamics + safety subpackages. Update layer-boundary table with v1.6 leaks |
| `SYSTEM_STATE.md` | New v1.6 + v1.6.1 entries; test count 998 → target; CHANGELOG-style |
| `DEVELOPER_GUIDE.md` | "How to add a property package" recipe, "How to add a unit with v1.6 features" walkthrough; updated UI page conventions |
| `USER_MANUAL.md` | New chapters: Industrial Mode, Property Method selector, Validation page, Relief sizing |
| `THEORY_REFERENCE.md` | New sections: NRTL, PR/SRK, Antoine derivation in components.py; relief / depressuring math |
| `CHANGELOG.md` | **CREATE** — retro-fill v1.5.0 onwards; tag v1.6 changes; tag v1.6.1 changes |

**Acceptance**: every `.md` in `docs/` carries v1.6.1 in its header.

---

## P.4 — Analytical Jacobians (5 units)

71 % of v1.6 units use central-difference FD. Adding analytical Jacobians
to the 5 highest-traffic units yields 5–10× SLP speedup on typical
flowsheets.

| Priority | Unit | Why |
|---|---|---|
| 1 | `CSTRHF` | Reactor in almost every template; ~120 residual evals per SLP iter currently |
| 2 | `FlashVLHF` | Every separator chain; non-trivial K-value derivatives |
| 3 | `HeatExchangerNTU` | NTU effectiveness derivative is analytical (closed form) |
| 4 | `ShellTubeHX` | LMTD + F-factor derivatives are tractable |
| 5 | `Compressor` | Isentropic + multi-stage analytical via chain rule |

Each adds:
- `linearize(guess) → LinearizedModel` override
- Regression test verifying analytical J vs FD J within 1e-6 relative

**Acceptance**: 5 new tests; SLP iteration count benchmarked unchanged or
better; wall-clock improvement documented in a comment.

---

## P.5 — Layer Boundary + OPEX Footgun

### P.5a — Move `TechnologyChoice` to `core/contracts.py`

Closes the only top-level L3 → L2 import in the codebase. Pure-data
dataclass; no behavioural change. Update one import in
`flowsheets/hydrogen/electrolysis_grid.py`.

### P.5b — OPEX-convention safeguards

Add to `BaseUnit`:

```python
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    # Force explicit OPEX declaration on units that override
    # objective_contribution but inherit the default _OPEX_CONVENTION.
    if 'objective_contribution' in cls.__dict__ and \
       '_OPEX_CONVENTION' not in cls.__dict__:
        warnings.warn(
            f"{cls.__name__} overrides objective_contribution but doesn't "
            f"declare _OPEX_CONVENTION. Defaulting to USD_PER_YEAR. "
            f"This is a 3600x annualisation footgun.",
            DeprecationWarning, stacklevel=2,
        )
```

**Acceptance**: 1 test for the warning fire; existing tests pass.

---

## P.6 — Industrial Mode Filter Wired

The v1.6 G.1 helper `available_units_for_persona()` exists but the Custom
Builder UI's unit dropdown doesn't call it yet.

Changes:
- In `flowsheet_builder.py` (post-split), replace
  `AVAILABLE_UNITS.keys()` with
  `available_units_for_persona(st.session_state["user_persona"]).keys()`.
- Add a small badge per unit: "DIDACTIC" / "LEGACY" / "SCREENING" colour
  pills, with category-aware tooltips.

**Acceptance**: switching the persona radio toggles the picker contents
in real time. Test added to `test_ui_assembly_logic.py`.

---

## P.7 — New UI Pages for v1.6 Features

Four pages, all read-only views of existing infrastructure:

### P.7a — Validation page

- File upload widget for measured-data CSV (column layout from
  `validation/csv_io.py`).
- Calls `compute_metrics(measured, predicted)`.
- Plotly parity scatter (uses `scatter_data` helper).
- Per-variable MAPE / RMSE / R² table.
- "Tune kinetics" button → `kinetic_tuner.tune_kinetics`.

### P.7b — Pinch Preview page (placeholder, no algorithm)

- Auto-extracts hot/cold streams from current flowsheet HX units.
- Displays a stream-data table.
- Calls a `pinch_targets(...)` stub that **returns NotImplementedError
  with a "v1.7 H" message** — the UI placeholder is here so v1.7 has
  somewhere to land.

### P.7c — Dynamics Studio page

- Picks a unit from current flowsheet.
- Lets the user add `Perturbation.step / ramp / pulse / sinusoid` on an
  input variable.
- Calls `DynamicSimulator.integrate()` with a fixed t_span.
- Plotly trace plot of every state variable that any unit returns.
- Empty-flowsheet message when no unit overrides `dynamic_residuals`.

### P.7d — Relief Sizing page

- Per-vessel inputs: P_design, T_relief, A_wetted, fluid (MW, γ, H_vap).
- Calls `size_psv_for_vessel()` for each of the three scenarios.
- Displays orifice area + recommended setpoints in a table.
- Exports as CSV.

**Acceptance**: 4 new pages added to `st.navigation`; smoke tests in
`test_streamlit_smoke.py` confirm each page renders without errors on
an empty flowsheet.

---

## P.8 — End-to-End Case Study Templates

The 4 v1.6 case-study CSVs (`smr.csv`, `mea_absorber.csv`,
`propane_splitter.csv`, `ammonia_loop.csv`) have **no matching PSE
Ecosystem flowsheets that can solve them**. The "self-round-trip
MAPE = 0" tests prove only that the CSV parser works.

Build one `TemplateSpec` per case study under
`pse_ecosystem/flowsheets/case_studies/`:

| Case study | Units involved | Property method |
|---|---|---|
| SMR | `BiomassGasifierHF` + `WGSReactorHF` + `H2SeparatorPSA` (existing!) | `ideal_gas` |
| MEA absorber | `PackedColumnHF` (v1.6 B) | `nrtl` (closest available; flag `pr_nrtl` as future) |
| Propane splitter | `TrayColumnHF` (v1.6 B) | `peng_robinson` |
| Ammonia loop | `EquilibriumReactor` + `FlashVLHF` + `Compressor` + recycle | `peng_robinson` |

Each adds:
- Template loader in the v1.6.1-refactored `templates/_loaders.py`
- Default parameters matching the CSV reference data
- A parity test: solve template → compare to reference CSV → assert
  MAPE < 10 % per variable (loose acceptance; v1.7 F kinetic tuner can
  tighten later)

**Acceptance**: 4 new tests in `tests/test_case_studies_e2e.py`;
expected MAPE per case documented; UI exposes the templates in the
Flowsheet Builder.

---

## Sequencing (3–4 weeks)

| Week | Primary | Secondary |
|---|---|---|
| 1 | P.1 catalogue + persona modules · P.5 boundary fix | P.3 architecture + system state doc updates |
| 2 | P.1 instantiate + templates · P.2 split app_streamlit | P.6 wire persona filter · P.7d Relief Sizing page |
| 3 | P.4 analytical Jacobians (CSTR, Flash, HX NTU) | P.7a Validation page · P.7c Dynamics page · P.8 SMR + ammonia templates |
| 4 | P.4 analytical Jacobians (Shell-Tube, Compressor) · P.7b Pinch placeholder · P.8 MEA + C3 splitter templates | P.3 user manual + theory ref · CHANGELOG |

---

## Verification Gates (before tagging v1.6.1)

1. `pytest` → 1050+ tests pass.
2. `python -m pse_ecosystem.ui` launches Streamlit; persona toggle alters
   the unit picker; all 11 pages (7 existing + 4 new) render without
   errors.
3. Five analytical-Jacobian benchmarks: SLP iterations on a CSTR-Flash
   chain converge in equal-or-fewer iters than the v1.6 FD baseline.
4. Each of the 4 case-study templates solves to converged status; MAPE
   < 10 % on the reference CSV per variable.
5. `docs/` — every `.md` carries v1.6.1 header; CHANGELOG.md tracks all
   changes since v1.5.0.
6. `git grep -l 'v1\.5\.2'` returns 0 results in docs.
7. `pse_ecosystem/ui/flowsheet_service.py` is < 700 lines (down from
   3 392).
8. `pse_ecosystem/ui/app_streamlit.py` is < 400 lines (down from 2 714).
9. Layer-boundary grep returns 0 top-level L3 → L2 imports.

---

## What v1.6.1 Does **NOT** Cover

Held for v1.7 (capability sprint):
- Pinch / HEN synthesis algorithm (P.7b only adds the UI placeholder)
- Uncertainty quantification (Monte Carlo, Sobol)
- Multi-objective optimisation (Pareto, ε-constraint)
- `pr_nrtl` hybrid property package + 3-phase VLLE flash
- Process control (PI/PID + MPC)
- OPC UA / Modbus live-data gateway
- New unit models beyond the existing 45

---

## Why This Approach

- **Unblocks v1.7 by halving its UI risk.** The current 3 392-line
  flowsheet_service makes every v1.7 UI page change painful. Splitting
  it now is 4 days; later, with N more pages on top, it's 2 weeks.
- **Closes the "feature exists but no UI" gap** that the audit identified
  as the highest-leverage user-facing weakness.
- **Documentation lift is owed.** Customers / collaborators read docs first
  and code second. A 4-version doc gap is the single largest barrier to
  adoption identified in §10.4 of the audit.
- **No new capability risk.** Every line of code already exists in some
  form; v1.6.1 is reorganisation + activation, not invention.
- **Sets up case-study validation for v1.7.** Once SMR / MEA / C3 / NH3
  have solvable templates, v1.7 F's kinetic-tuner has real work to do
  instead of self-round-tripping CSVs.
