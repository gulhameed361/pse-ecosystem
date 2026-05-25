# PSE Ecosystem — Deep Audit (v1.6 post-release)

**Audit date**: 2026-05-25
**Audited version**: v1.6 (commit `0404aca`, tag `v1.6`)
**Test baseline**: 998 passing, 1 skipped (60 s sweep)
**Scope**: every package, every layer, every doc — pre-v1.7 planning.

---

## 1. Inventory

| Subsystem            | Files | Lines  | Notes                                              |
|----------------------|------:|-------:|----------------------------------------------------|
| `models/`            |    81 | 11 576 | 45 BaseUnit subclasses + properties + costing      |
| `tests/`             |    44 | 11 173 | 44 .py + 4 CSV case-study refs                     |
| `ui/`                |     5 |  6 192 | Streamlit app (2 714 ln) + service bridge (3 392 ln) |
| `docs/`              |     7 |  5 570 | Architecture, theory, dev guide, user manual, plan |
| `solvers/`           |    13 |  2 309 | SLP, NLP, TRF Filter/Funnel, MILP, scaling          |
| `flowsheets/`        |    14 |  1 075 | BaseFlowsheet + CompositeUnit + template subdirs   |
| `validation/` (v1.6) |    10 |    708 | Parity, CSV, Aspen, kinetic tuner, 4 case studies   |
| `safety/` (v1.6)     |     4 |    557 | Relief sizing, depressuring, HAZOP nodes            |
| `core/`              |     3 |    281 | Cross-layer data contracts                          |
| `dynamics/` (v1.6)   |     3 |    296 | DynamicSimulator + Perturbation                     |
| **Total**            | **184** | **39 737** |                                                     |

### Top-10 largest files

| File | Lines | Concern |
|---|---:|---|
| `ui/flowsheet_service.py`             | 3 392 | **Monolith** — see §9.1 |
| `ui/app_streamlit.py`                 | 2 714 | All UI pages in one file — see §9.2 |
| `solvers/slp.py`                       |   584 | Largest solver file; healthy structure |
| `models/properties/activity_models.py` |   513 | New in v1.6 — clean |
| `models/properties/components.py`      |   499 | New in v1.6 — clean |
| `models/properties/cubic_eos.py`       |   469 | New in v1.6 — clean |
| `flowsheets/base_flowsheet.py`         |   412 | Reasonable for what it owns |
| `models/biomass/biomass_gasifier.py`   |   373 | Equilibrium reactor + 6-species syngas |
| `solvers/trust_region_driver.py`       |   358 | Filter/Funnel — clean |
| `models/base_unit.py`                   |   315 | ABC with v1.6 hooks; healthy |

---

## 2. Architecture — 3-Layer Split

```
                       ┌─────────────────────────────┐
   Layer 1 (UI) ─────► │   pse_ecosystem.ui.*        │ ← Streamlit, Plotly, Pandas
                       └────────────┬────────────────┘
                                    │ via flowsheet_service
                       ┌────────────▼────────────────┐
   Layer 2 (Decision) ─►│  pse_ecosystem.solvers.*   │ ← Pyomo LP/MILP, scipy NLP/TRF
                       └────────────┬────────────────┘
                                    │ talks only through
                       ┌────────────▼────────────────┐
       Shared contract  │  pse_ecosystem.core.*       │ ← StreamPort, LinearizedModel,
                       └────────────┬────────────────┘    PrimalGuess, UnitResponse
                                    ▲
                       ┌────────────┴────────────────┐
   Layer 3 (Knowledge)  │  pse_ecosystem.models.*    │ ← BaseUnit subclasses, thermo,
                       │  pse_ecosystem.dynamics.*   │   safety, costing
                       │  pse_ecosystem.safety.*     │
                       │  pse_ecosystem.validation.* │
                       └─────────────────────────────┘
```

**Layer-boundary verification** (grep-validated):
- `solvers/` imports from `models/`: **0 occurrences** ✓
- `models/` imports from `solvers/`: **0 occurrences** ✓
- `flowsheets/` → `solvers/`: **2 occurrences** (one deferred inside `CompositeUnit.residual`,
  one top-level in `flowsheets/hydrogen/electrolysis_grid.py` importing the
  `TechnologyChoice` dataclass). The deferred one is documented as "the only
  sanctioned exception"; the dataclass import is debatable — see §11.4.
- `ui/flowsheet_service.py` → solvers / models / dynamics / safety / validation:
  100 imports, expected (UI is the bridge layer).

**Verdict**: 3-layer split is intact. The two cross-layer leaks are minor.

### 2.1 The Handshake Protocol — `core/contracts.py`

Three frozen dataclasses define the entire cross-layer surface:

| Type | Direction | Carries |
|---|---|---|
| `PrimalGuess`     | L2 → L3 | `{var_name: float}` candidate point |
| `LinearizedModel` | L3 → L2 | Taylor f₀ + J at x₀, bounds, objective coeffs, KPI gradients, optional trust-region |
| `UnitResponse`     | L3 → L2 | True non-linear residual + KPIs (for residual checking & post-solve report) |

Plus:
- `StreamPort` — variable-name generator, holds **no values** (only produces flat
  `unit_id.tag.F_<comp>` style strings).
- `SolveMode` enum: `FIXED_LP`, `FLEXIBLE_MILP`, `NLP_IPOPT`/`NLP_SCIPY`, `TRUST_REGION`, `ADAPTIVE`.
- `SolverStatus` enum: `CONVERGED`, `MAX_ITER`, `INFEASIBLE`, `UNBOUNDED`, `NUMERICAL_ERROR`.

**Strengths**:
- `LinearizedModel.__post_init__` validates shape consistency at construction —
  a 1-line wrong Jacobian shape can't survive into the LP builder.
- `predicted_residual()` helper on `LinearizedModel` enables ρ-ratio computation
  without recomputing the linearisation.

**Smell**: `SolveMode` has both `NLP_IPOPT` and `NLP_SCIPY` as enum members
mapping to the same value `"mode_3"`. The retain-the-old-name-for-compat
gesture creates two enum singletons that compare equal but `is`-differ;
brittle for code that uses `mode is SolveMode.NLP_IPOPT`. Either drop one or
collapse to a single member.

---

## 3. Solver Layer (Layer 2)

The decision layer ships **five solver paths** through one Orchestrator:

| Mode | Driver | Path | When to use |
|---|---|---|---|
| FIXED_LP | `SLPDriver` | LP if all units linear; SLP loop otherwise | Default mode 1 |
| FLEXIBLE_MILP | `Orchestrator._solve_flexible` | MILP (linearised) + SLP refine on selected topology | Mode 2 — technology choice |
| NLP_IPOPT / NLP_SCIPY | `NLPDriver` | scipy L-BFGS-B on ½‖f‖²; analytical gradient | Mode 3 — square or near-square systems |
| TRUST_REGION | `TrustRegionDriver` | SLP LP-subproblem + Filter/Funnel acceptance + feasibility restoration | Mode 4 — robust fallback |
| ADAPTIVE | cascade | SLP → NLP → TRF, escalating on failure | Most resilient |

### 3.1 SLP driver (584 lines) — Highlights

Many sophisticated features that aren't always visible from the high level:

1. **Elastic LP fallback** (`elastic_fallback=True` default) — on `INFEASIBLE`,
   re-runs the LP with non-negative slack pairs on every equality, accepts the
   step iff total slack < `elastic_slack_tol`. Almost-always saves the
   "infeasible at min trust-region after 3 restarts" failure mode for
   industrial flowsheets with tight bounds. **This is a real innovation worth
   keeping.**
2. **Wegstein tear-stream acceleration** (`TearStreamConfig`) — q ∈ [-5, 0]
   damped extrapolation on user-declared recycle variables.
3. **Progressive tightening** — eps_x / eps_f / eps_kpi relaxed early, tightened
   late. Default off; opt-in for 7–10 unit chains.
4. **Warm-start restarts** — up to 3 perturbed-x retries when TR collapses.
5. **`scale_rows`** — opt-in 1/max(‖J_row‖∞, 1) row-scaling for ill-conditioned
   flowsheets.
6. **`bound_active` reporting** — converged solutions that pin against a
   non-fixed bound get explicit attribution. The v1.4.0 cooler-saturation bug
   would've been caught by this earlier.
7. **`fail_on_bound_saturation`** — opt-in CI flag to downgrade
   bound-pinned converged solves to NUMERICAL_ERROR.
8. **`iteration_callback`** — hook for the Solver Monitor UI page; streams
   convergence data without a Layer-1 dependency.

### 3.2 LP builder (277 lines)

- Per-unit Taylor expansion rearranged to `J·x = J·x₀ - f₀`.
- Adds connections, `extra_equalities`, `extra_bounds`, optional trust-region
  box constraints.
- Optional elastic mode (slack pairs) and row scaling.
- Uses Pyomo `ConcreteModel`; backend chosen by `select_lp_solver` (HiGHS
  preferred via `appsi`, then CBC, then GLPK).

### 3.3 TRF driver (358 lines)

- Eason & Biegler 2016 filter / funnel acceptance.
- Feasibility restoration via NLP when Δ ≤ Δ_min.
- 5 funnel parameters (β, κ_f, κ_r, α, μ_s, η) all configurable.
- Imports its own `Filter` / `Funnel` from `solvers/trf/`.

### 3.4 MILP builder (`milp_builder.py`)

- big-M coupling for technology binaries (default M = 1e9).
- `TechnologyChoice` dataclass binds `unit_id` to its flow variables.
- `minimum_one_active` flag forces at least one technology selected.
- Sequential MILP → SLP decomposition for mixed linear/non-linear flowsheets.

### 3.5 Findings

| # | Finding | Severity |
|---|---|---|
| S-1 | `SolveMode.NLP_IPOPT` and `NLP_SCIPY` both equal `"mode_3"` — brittle `is`-comparison | Low |
| S-2 | `_solve_adaptive` catches `AttributeError` along with the import errors — broad and could mask real bugs | Med |
| S-3 | SLP has hard-coded `_max_restarts = 3` — should be configurable via `SLPConfig` | Low |
| S-4 | No actual Pyomo+IPOPT path despite the name — driver falls back to scipy. v1.5 docs flagged this as a v1.6 item that wasn't picked up | Med |

---

## 4. BaseUnit + Flowsheet Contracts

### 4.1 `BaseUnit` (315 lines)

Required interface (abstract):
- `variables() → List[str]`
- `bounds() → Dict[str, Tuple[float, float]]`
- `residual(x: Dict[str, float]) → np.ndarray`
- `objective_contribution(x) → Dict[str, float]`

Optional hooks (default no-op or sensible):
- `kpis(x)` → empty dict
- `kpi_gradients(x)` → empty dict
- `capex(x)` → 0.0
- `opex_per_year(x, operating_hours=8000)` → derived from `objective_contribution`
- `linearize(guess)` → central-difference FD (overrideable for analytical Jacobian)
- `evaluate(x) → UnitResponse` (for residual checking)
- `dynamic_residuals(t, y, x)` → empty dict (v1.6 — opt-in dynamics)
- `design_sizing(x)` → empty dict (v1.6 — opt-in)
- `control_hooks()` → empty dict (for future control pairing)
- `validate_connection(port_a, port_b)` → raises `PortCompatibilityError`

Class-level attributes:
- `is_linear: bool = False` — short-circuits SLP to single LP solve
- `trust_region: float | None = None` — per-unit TR radius hint
- `_OPEX_CONVENTION: OPEXConvention = USD_PER_YEAR` — annualisation rule
- `category: UnitCategory = INDUSTRIAL` — UI persona filter
- `sizing_mode: SizingMode = RATING` — v1.6 sizing-mode workflow

**Finding**: the FD linearisation has multi-scale step adaption:
```
step = max(1e-6 * max(1.0, |x_val|), 1e-9)
if |x_val| > 1.0: step = min(step, 0.1 * |x_val|)
```
This was the v1.4.0 audit L5 fix; it correctly handles micro-scale (mole-fraction
~1e-4) and large-magnitude (pressure ~1e6 Pa) variables. **Good**.

### 4.2 `BaseFlowsheet` (412 lines)

Holds: `units`, `connections`, `objective_kpi`, `extra_bounds`, `extra_equalities`,
`initial_x0`, `recycle_streams`, `objective_extra`, `force_feasibility`,
`property_method` (v1.6), and `validate()` / `diagnose()` / `aggregate_kpis()`.

**Strengths**:
- `validate()` checks every variable referenced in connections / extras against
  the set produced by units (catches phantom connections — a real v1.4 bug).
- `diagnose()` is a non-raising pre-solve sanity check; returns
  `{errors, warnings, info}` for UI display.
- `initial_guess()` is **scale-aware**: half-bounded vars step off the bound by
  `max(10% × |bound|, 1.0)` not a flat ±1.
- `aggregate_kpis()` is the single source of truth (was duplicated 4× pre-1.5).
- `build_property_package(species)` (v1.6) factory wrapper — clean.

### 4.3 `CompositeUnit`

Wraps a `BaseFlowsheet` as a `BaseUnit` so sub-processes can be reused as
atomic units. Validates that every exposed input/output is actually a variable
in the inner flowsheet (catches typos — pre-v1.4 these silently defaulted to 0).

**Finding**: `CompositeUnit.residual()` does a deferred `from pse_ecosystem.solvers.slp import SLPDriver`.
This is **the only sanctioned Layer 3 → Layer 2 call** in the codebase
(documented in the file). Acceptable.

### 4.4 Findings

| # | Finding | Severity |
|---|---|---|
| F-1 | `flowsheets/hydrogen/electrolysis_grid.py` top-level-imports `TechnologyChoice` from `solvers/milp_builder` — strictly a Layer 3 → Layer 2 leak. The import is just a dataclass so the practical cost is zero, but the rule needs either an update or a relocation of `TechnologyChoice` to `core/contracts.py` | Low |
| F-2 | `BaseUnit.dynamic_residuals` default empty dict means **no shipped unit uses dynamics**; the v1.6 DynamicSimulator has zero in-tree consumers | Med — dynamics is unused infrastructure |
| F-3 | `BaseUnit.design_sizing` is overridden by **10 of 45 units** (CSTR/Equilibrium/Gibbs/Stoichiometric, FlashVLHF, the 3 HX, Pump, Compressor, Tray/Packed columns). The other 35 silently return empty | Low — opt-in design is the v1.6 contract |
| F-4 | `BaseUnit._OPEX_CONVENTION` defaults to `USD_PER_YEAR` — quiet annualisation if a unit author forgets to switch to `USD_PER_SECOND` (×3600×hours factor missed) | Med — easy footgun for new contributors |

---

## 5. Property Packages (v1.6 thermo)

The C-track v1.6 work delivers a clean ladder:

```
                       PropertyPackage (ABC)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
      IdealGasPackage   CubicEOSPackage   ActivityModelPackage
                              │                │
                       ┌──────┴──────┐    ┌────┴────┬────────────┐
                       ▼             ▼    ▼         ▼            ▼
                 PengRobinsonPackage SRKPackage NRTLPackage WilsonPackage UNIQUACPackage
```

### 5.1 Component database (`components.py`, 499 lines)

- 27 distinct species under a frozen `Component` dataclass.
- Tier-1 (v1.5.3 byte-compat): H2, O2, N2, CO, CO2, CH4, H2O.
- Tier-2 (v1.6, EOS-ready): C1–C7 alkanes, ethylene, propylene, cyclohexane,
  p-xylene, alcohols, glycol, acetone, acetic acid, NH3, MEA, H2S, SO2, Ar.
- Each species carries (optionally): MW, Tb, Tm, Hf_298, Tc, Pc, ω, Shomate,
  Antoine, UNIQUAC r/q.
- Aliases (`"CH4" ↔ "methane"`) registered alongside canonical ids.
- Back-compat builders rebuild v1.5.3's `SHOMATE` / `ANTOINE` / `MW` /
  `H_REF_298` dicts at import time **byte-identical** to the v1.5.3 versions.

### 5.2 Property-package factory

`get_property_package(method, species)` routes to:
- `ideal_gas` → `IdealGasPackage`
- `peng_robinson` → `PengRobinsonPackage`
- `srk` → `SRKPackage`
- `nrtl` → `NRTLPackage`
- `wilson` → `WilsonPackage`
- `uniquac` → `UNIQUACPackage`
- `pr_nrtl` → **reserved stub** (`NotImplementedError`) — see §11.3

The contract surface every package implements: `K_values`, `enthalpy`, `Cp`,
`density`, optional `K_iteration` (rigorous for cubic EOS).

### 5.3 Findings

| # | Finding | Severity |
|---|---|---|
| P-1 | `pr_nrtl` hybrid package is still a stub — needed for industrial-fidelity MEA-CO2-H2O. Reserved in v1.6 with `NotImplementedError` | Med — explicit v1.7 item |
| P-2 | 3-phase VLLE flash not implemented; the generic `flash_PT` is VLE only. MEA / decanter use partition-coefficient surrogates | Med — explicit v1.7 item |
| P-3 | Binary parameter coverage is sparse: NRTL has 3 pairs (ethanol-water, methanol-water, benzene-toluene), UNIQUAC has 2, Wilson has 1. Real plants use 10–50 pairs | High for industrial users; v1.6 documents this as project-supply expectation |
| P-4 | New B-units (TrayColumnHF, PackedColumnHF, DecanterHF) don't fully accept a `property_package` — only `FlashVLHF` does. TrayColumnHF takes one optionally, others hardcode | Med — completes the v1.6 wiring |
| P-5 | No EOS departure-Cp; `Cp` method on CubicEOSPackage returns ideal-gas mixture Cp + 0 departure | Low — flagged in code comments |

---

## 6. Unit Catalogue (45 BaseUnit subclasses)

### 6.1 By category (post-A.0)

| Category | Count | Members |
|---|---:|---|
| INDUSTRIAL | 34 | Industrial-grade HF units, biomass/DAC/power, 10 new B-units |
| SCREENING |  1 | DistillationHF (shortcut FUG) |
| DIDACTIC  |  7 | CSTRToy, FlashToy, HXToy, BoilerToy, IdealMixer, GasifierToy, PEMToy |
| LEGACY    |  3 | HDAPFRUnit, HDAFlashUnit, HDADistillationUnit (black-box wrappers) |

### 6.2 Analytical Jacobian coverage

Only **13 of 45 units (29%)** override `linearize()` for an analytical Jacobian.
The rest fall back to central-difference FD (2n+1 residual evals per step).

Units with analytical Jacobian:
- `StoichiometricReactor` (truly linear)
- `CHPUnit`
- `SeparatorHF`
- `PEMToy`
- `GasifierToy`
- `IdealMixer`
- `BoilerToy`
- `CSTRToy`
- `MethanationReactor`
- `CoolerHF`
- `TVSAContactor`
- `BiomassGasifierHF`
- `ElectrolyserHF`

Notably **missing** analytical Jacobian (on units the solver hits most):
- `CSTRHF`, `PFRHF`, `EquilibriumReactor`, `GibbsReactor`, `BatchReactorHF`
- All HX units (`HeatExchangerNTU`, `ShellTubeHX`, `HeatExchanger1D`)
- All v1.6 B-units except where derived from CSTR/Flash patterns
- `Compressor`, `Pump`, `Valve`, `ExpanderHF`, `MultistageCompressorHF`
- `FlashVLHF`, `DistillationHF`, `TrayColumnHF`, `PackedColumnHF`,
  `MembraneModuleHF`, `CrystallizerHF`, `DecanterHF`, `FlashSL`
- `WGSReactorHF`, `BiomassStorageHF`, `H2SeparatorPSA`
- `SteamDrumHF`, `FiredHeaterHF`, `MixerHF`

### 6.3 `is_linear` flag

8 units claim `is_linear = True`:
- `StoichiometricReactor`, `CHPUnit`, `SeparatorHF`, `PEMToy`,
- `IdealMixer`, `BoilerToy`, `TVSAContactor`, `ElectrolyserHF`

**Verify**: CHPUnit's residual has products of fuel flows × LHV coefficients
which are linear, but the energy balance includes `(W + Q) = q_elec × Q_fuel`
where Q_fuel = Σ_i F_i × LHV_i — also linear in flows. **CHPUnit is correctly
linear**, despite the surface complexity. ✓

### 6.4 Costing / KPI completeness (post-v1.6 audits)

After Workstream A audits, every INDUSTRIAL unit ships:
- ports (StreamPort attributes)
- `capex(x) > 0`
- `kpis(x)` non-empty
- bounded variables
- v1.6 `category = INDUSTRIAL`

Verified by `tests/test_*_audit.py` (5 files, 104 tests covering A.1–A.5).

### 6.5 Findings

| # | Finding | Severity |
|---|---|---|
| U-1 | 71 % of units use FD Jacobians. Each FD step is 2n+1 residual evaluations. For an 8-unit non-linear flowsheet with ~80 variables this is ~1300 calls per SLP iteration. Plant-scale (50+ units) makes SLP visibly slow | High for industrial scale |
| U-2 | Several "should be analytical" units don't have it: `CSTRHF`, `Compressor`, `Pump`, `Valve`, `FlashVLHF`. The math is tractable; the work just wasn't done | Med |
| U-3 | v1.6 B-units (TrayColumn, PackedColumn, etc.) ship FD-only — and they're the most non-linear additions | Med |
| U-4 | `BaseUnit.kpi_gradients` exists but only `CHPUnit` populates it. Sensitivity analysis in the UI relies on FD differences against re-solves rather than analytical KPI gradients | Low — sensitivity feature unused |

---

## 7. UI Layer

### 7.1 `app_streamlit.py` (2 714 lines)

All 7 pages defined as `_page_*` functions in a single file:

| Page | Function | Lines |
|---|---|---:|
| Dashboard | `_page_dashboard` | 95 |
| Flowsheet Builder | `_page_flowsheet_builder` | 786 |
| Site Weather | `_page_gps_weather` | 449 |
| Solver Monitor | `_page_solver_monitor` | 677 |
| Scenario Manager & Analysis | `_page_scenario_manager` | 411 |
| Solve History | `_page_solve_history` | 49 |
| Help Center | `_page_help_center` | 33 |

Plus `main()` which sets persona radio + page navigation.

**Persona toggle**: lives in `st.sidebar`, written to
`session_state["user_persona"]` ∈ {"Academic", "Industrial"}. Read by every page
to decide rendering (e.g. show Jacobian diagnostics or hide them, show CapEx
table or hide).

### 7.2 `flowsheet_service.py` (3 392 lines)

The bridge between UI and lower layers. Owns:

- `AVAILABLE_UNITS` — 32 UI labels mapped to descriptions
- `UNIT_CATEGORIES` — grouping by category for the Custom Builder picker
- `TemplateSpec` / `_REGISTRY` — bundled flowsheet templates (electrolysis,
  gasification, ammonia, methanol, ...)
- `_instantiate_unit()` — factory mapping UI label → unit constructor
- `build_custom_flowsheet()` — assembles a flowsheet from a user-supplied
  unit/connection spec
- `compute_safety_margins()` — post-solve ASME / flammability checks
- `compute_project_economics()` — post-solve LCOH / NPV / IRR rollup
- `available_units_for_persona()` / `unit_categories_for_persona()` (v1.6) —
  Industrial Mode filter
- `_primary_inlet()` / `_primary_outlet()` — port resolver
- 100+ imports from solvers / models / dynamics / safety / validation

### 7.3 Findings

| # | Finding | Severity |
|---|---|---|
| UI-1 | `flowsheet_service.py` (3392 ln) mixes catalog, factory, templates, JSON, persona filters, safety hooks, economics. Refactor candidate — at least 4 logical sub-modules | High for maintenance |
| UI-2 | `app_streamlit.py` (2714 ln) holds all 7 pages. Streamlit's `st.Page(...)` API permits page-per-file structure; the project doesn't use it | Med |
| UI-3 | Persona toggle is the only user-controllable layer-1 state besides templates. No visible "Industrial Mode" toggle for the unit picker yet — A.0 categories are wired but the picker still shows all units in default Streamlit dropdown | Med — wiring needed to expose v1.6 G.1 helper |
| UI-4 | No dedicated pages for v1.6 features: Pinch, Validation (parity dashboard), Relief sizing, Dynamics. The infrastructure is built (parity.py, relief_sizing.py, etc.) but the UI doesn't surface it yet | High for industrial discoverability |
| UI-5 | Solver Monitor page exists (677 lines) but Dynamics monitoring (v1.6 DynamicSimulator) is not surfaced | Med |

---

## 8. Costing + Economics

### 8.1 SSLW (`sslw_costing.py`)

Six correlations, all CE500 (2001) basis:
- `hx_purchase_cost_USD(area_m2, ...)`
- `vessel_purchase_cost_USD(volume_m3, ...)`
- `cstr_purchase_cost_USD(volume_m3, material="CS")`
- `compressor_purchase_cost_USD(work_W)`
- `pump_purchase_cost_USD(work_W)`
- `turbine_purchase_cost_USD(work_W)`

### 8.2 `EconomicEngine`

CEPCI-escalated NPV / IRR / LCOH / LCOE rollup:
- `target_year` selects CEPCI index
- `cepci_factor(base_year)` returns ratio
- `sslw_cepci_factor()` is shorthand for SSLW CE=500 (2001) basis
- `capital_recovery_factor()` = `i(1+i)^n / ((1+i)^n - 1)` (with `i=0` fallback)
- `annualized_capex(purchase_cost, lang_factor=5.0)` rolls up to USD/yr
- Hard validation on construction: `plant_life_yr > 0`, `interest_rate ≥ 0`,
  `0 < operating_hours_per_year ≤ 8760`

### 8.3 OPEX convention

Three cases per unit (set via `_OPEX_CONVENTION`):
- `USD_PER_YEAR` (default) — coefficient × var × 1 = USD/yr directly
- `USD_PER_SECOND` — coefficient × var × 3600 × hours = USD/yr
- `YIELD_COEFFICIENT` — coefficient is LP yield/penalty, opex_per_year() = 0

### 8.4 Findings

| # | Finding | Severity |
|---|---|---|
| E-1 | `_OPEX_CONVENTION` defaults to `USD_PER_YEAR` — forgetting to set `USD_PER_SECOND` is silent and produces a 3600× annualisation error | Med |
| E-2 | No Lang factor tracking per unit type. All units use `lang_factor=5.0` in `annualized_capex`. Real plants: 4.7 (fluids), 3.9 (solid), 4.1 (mixed) | Low |
| E-3 | No CAPEX uncertainty bands. Industrial decisions need ±%, not a point estimate | Med — v1.7 UQ workstream J covers this |
| E-4 | No tax / depreciation modelling. NPV is pre-tax | Med — out of scope per v1.5 release notes |

---

## 9. Dynamics / Safety / Validation (v1.6 additions)

### 9.1 Dynamics

- `DynamicSimulator` wraps `scipy.solve_ivp` (BDF default).
- Empty-state shortcut: returns single-point if no unit overrides
  `dynamic_residuals`.
- `SimEvent` callbacks for time-trigger or predicate-trigger events.
- `Perturbation` factory shapes (step / ramp / pulse / sinusoid) composable
  via `+`.

**Finding D-1**: Zero in-tree consumers — no unit overrides
`BaseUnit.dynamic_residuals`. The framework is built; the wiring isn't.

### 9.2 Safety

- `relief_sizing.py` — API 520 / 521 orifice area + fire-case duty + ASME
  setpoints. Real engineering correlations with citations.
- `depressuring.py` — choked + sub-critical orifice mass flux + isothermal
  blowdown integrator (forward Euler).
- `hazop_nodes.py` — topology-walking node generator with 7 guidewords ×
  shape-applicable parameter matrix.

**Finding D-2**: `depressuring.py` uses **isothermal** integration — real
blowdown features Joule-Thomson cooling that risks brittle fracture. Marked
as screening-grade in the docstring; acceptable for the scope.

### 9.3 Validation

- `parity.py` — MAPE / RMSE / R² + scatter data. Clean kernels.
- `csv_io.py` — Aspen-compatible stream-table I/O. Aspen column naming
  convention respected.
- `aspen_importer.py` — best-effort ASCII parser for `.bkp` files. Robust
  to missing summary section.
- `kinetic_tuner.py` — scipy.optimize TRF wrapper with log-scale Arrhenius
  support.
- 4 bundled case studies (SMR, MEA absorber, propane splitter, NH3 loop) as
  CSV reference data.

**Finding D-3**: The 4 case studies have no corresponding PSE Ecosystem
flowsheet templates that solve them. "Self-round-trip MAPE=0" tests don't
actually validate any model. They're reference data waiting for end-to-end
runs (v1.7 / v1.8).

**Finding D-4**: Aspen importer parses the ASCII summary block only — real
Aspen `.bkp` files are mostly binary, and the ASCII section varies between
V8 / V10 / V11 / V12. Brittle.

---

## 10. Tests + Documentation

### 10.1 Test inventory (44 files, 11k lines)

| Family | Files | Approx tests |
|---|---:|---:|
| Version regression (`test_v121`, `test_v131`, `test_v151`, `test_v153`) | 4 | ~200 |
| Audit suites (`test_*_audit.py` — A.1–A.5) | 5 | 104 |
| Workstream B/E/F/G | 4 | 142 |
| Thermo (components, property_package, cubic_eos, activity_models, flash, sizing_modes) | 6 | 222 |
| Original HF / unit / interface | 4 | ~120 |
| UI assembly + Streamlit smoke | 3 | ~30 |
| Solver / SLP convergence / objectives / costing | 4 | ~60 |
| Misc / phase-7 UI / industrial readiness / case-bound | 7 | ~50 |
| **Total** | **44** | **998** |

### 10.2 Test naming inconsistency

- Version-locked: `test_v121.py`, `test_v131.py`, `test_v151.py`, `test_v153.py`
- Workstream-named: `test_workstream_b_units.py`, `test_workstream_e.py`,
  `test_workstream_f.py`, `test_workstream_g.py`
- Audit-named: `test_reactor_audit.py`, `test_hx_audit.py`,
  `test_separator_audit.py`, `test_pressure_changer_audit.py`,
  `test_biomass_dac_power_audit.py`
- Three top-level audit scripts (`tests/industrial_audit.py`,
  `tests/system_audit.py`, `tests/ui_audit.py`) — older pre-v1.6 scripts.

**Finding T-1**: Each major release adds another `test_v*` file; no
deprecation policy. Hard to maintain.

### 10.3 Doc inventory (7 files, 5.5k lines)

| Doc | Lines | Status |
|---|---:|---|
| ARCHITECTURE.md | 526 | **v1.5.2** — no v1.6 content |
| DEVELOPER_GUIDE.md | 1 291 | **v1.5.2** |
| SYSTEM_STATE.md | 1 223 | **v1.5.2** — 434 test count (current: 998) |
| THEORY_REFERENCE.md | 890 | **v1.5.2** |
| USER_MANUAL.md | 1 198 | **v1.5.x** |
| WORKSHOP_7UNIT.md | 196 | Tutorial |
| PLAN_v1_7.md | 246 | New (just created) |

**Finding T-2**: Every load-bearing doc is at v1.5.2. The v1.6 release shipped
without doc updates — the v1.6 plan's Workstream G explicitly listed
USER_MANUAL.md, INDUSTRIAL_GUIDE.md, VALIDATION.md updates, but my Claude Code
session ban on creating `.md` files without explicit user request meant these
were deliberately deferred. **All v1.6 features are undocumented outside of
docstrings and tests.**

### 10.4 Findings

| # | Finding | Severity |
|---|---|---|
| T-1 | Tests are version-locked, not feature-locked — `test_v153.py` will become noise after a year | Low |
| T-2 | Five separate `test_*_audit.py` files could consolidate into a single parametrised audit suite | Low |
| T-3 | Docs are 4 versions behind code | **High** — first thing any new contributor / customer sees |
| T-4 | No CHANGELOG.md tracking v1.6 contents — only git commit messages | Med |
| T-5 | No deprecation log (e.g. legacy unit removal schedule for `models/_blackbox/`) | Low |

---

## 11. Cross-Cutting Findings

### 11.1 Layer-Boundary Health

| Direction | Status | Notes |
|---|---|---|
| L1 → L2 / L3 | OK | UI imports everything below; this is correct |
| L2 → L3 | **Clean** | Zero imports from solvers into models |
| L3 → L2 | 2 leaks | `electrolysis_grid.py` top-level + `CompositeUnit.residual()` deferred |
| L3 → L3 | OK | `dynamics` / `safety` / `validation` are post-solve helpers |

### 11.2 Naming Convention Drift

- Some units use `HF` suffix (HighFidelity): `CSTRHF`, `FlashVLHF`, `ShellTubeHX` (no HF).
- Some use `Unit` suffix: `HDAFlashUnit`, `HDADistillationUnit`, `HDAPFRUnit`, `CHPUnit`.
- Some are plain: `Compressor`, `Pump`, `Valve`, `MethanationReactor`, `GibbsReactor`, `EquilibriumReactor`.

**Finding N-1**: No naming convention is enforced. New B-units adopted `HF`
(`ExpanderHF`, `MultistageCompressorHF`, `DecanterHF`, etc.) but inherited
inconsistency from pre-v1.6 units.

### 11.3 Reserved / Unfinished v1.6 Features

| Item | Status | Owner |
|---|---|---|
| `pr_nrtl` property method | Stub raising NotImplementedError | v1.7 L |
| 3-phase VLLE flash | Not implemented | v1.7 L |
| Pyomo + IPOPT executable backend | Driver hook exists, no implementation | v1.7? |
| `BaseUnit.kpi_gradients` | Default empty; only CHPUnit populates | v1.7 — analytical sensitivity |
| `BaseUnit.dynamic_residuals` | Default empty; zero unit overrides | v1.7 M dynamics activation |
| `BaseUnit.control_hooks` | Default empty; informational only | v1.7 M control |
| `BaseUnit.design_sizing` | 10/45 implement; no enforcement loop | v1.7 — closed-loop design mode |
| Aspen .bkp binary section parser | ASCII only | Out of scope |

### 11.4 Technical Debt Hotspots

Ranked by impact × frequency:

1. **`flowsheet_service.py` (3392 lines)** — single most concentrated tech-debt
   file. Refactor into 4–5 sub-modules: `catalogue.py`, `instantiate.py`,
   `templates.py`, `persona.py`, `economics_bridge.py`. **Estimate: 1 week.**
2. **`app_streamlit.py` (2714 lines)** — split each page into its own module
   under `pse_ecosystem/ui/pages/`. **Estimate: 3–4 days.**
3. **FD Jacobian coverage** — 32 of 45 units. Adding analytical Jacobians on
   the 5 most-called units (CSTRHF, FlashVLHF, all 3 HX) would speed up
   typical SLP iterations by 5–10×. **Estimate: 2 weeks for 5 units.**
4. **Docs drift** — every load-bearing doc is at v1.5.2. **Estimate: 1 week.**
5. **`TechnologyChoice` import leak** — move dataclass to `core/contracts.py`.
   **Estimate: 30 minutes.**
6. **OPEX-convention footgun** — auto-detect by inspecting variable units,
   or force the constructor to declare the convention. **Estimate: 1 day.**

### 11.5 v1.7 Readiness — Where the Hooks Already Exist

| v1.7 Workstream | Existing hook | Wire-up effort |
|---|---|---|
| H — Pinch / HEN | HX units expose `T_K` + `Q_W` KPIs; flowsheet has stream topology | Walk units, build StreamData list — straightforward |
| I — Mass pinch | Component-resolved port flows already in `StreamPort` | Sources / sinks are conceptual layers above the unit catalogue |
| J — UQ | `Orchestrator.solve()` is a clean function call; wrap in sampling | Trivial |
| K — Multi-objective | `BaseFlowsheet.objective_extra` already allows weighted-sum on multiple objectives; ε-constraint extends it | Easy |
| L — PR-NRTL | Factory registry already reserves `pr_nrtl` slot | Implement; ~1 week |
| M — Control | `DynamicSimulator` + `Perturbation` + `BaseUnit.dynamic_residuals` ready; just need controller layer | Medium — need first-class dynamic CSTR / Flash holdup models |

### 11.6 Architectural Patterns Worth Preserving in v1.7

- **Frozen dataclasses** for cross-layer data (`PrimalGuess`,
  `LinearizedModel`, `UnitResponse`, `StreamPort`, `Component`, all v1.6
  config dataclasses)
- **Factory + ABC** for property packages — extends cleanly to PR-NRTL
- **Per-unit `category` attribute** — extends cleanly to controllers (new
  CONTROLLER category for v1.7 M)
- **SSLW CE500 + CEPCI escalation** — proven; v1.7 doesn't need its own costing
- **SLP elastic fallback + Wegstein tear-streams** — keep
- **Test-per-workstream + test-per-audit-phase** — proven pattern for v1.7

---

## 12. Top-10 Action Items (Pre-v1.7)

Ranked by leverage:

1. **Refactor `flowsheet_service.py`** into 4–5 modules. Touches every UI page;
   unblocks Workstream N UI changes in v1.7.
2. **Split `app_streamlit.py`** into `pse_ecosystem/ui/pages/`. Streamlit v1.34+
   native multi-file pages supported.
3. **Update docs**: rewrite ARCHITECTURE.md / SYSTEM_STATE.md / DEVELOPER_GUIDE.md
   to v1.6 content. Add CHANGELOG.md.
4. **Add analytical Jacobians** to the 5 highest-traffic units (CSTRHF, FlashVLHF,
   HeatExchangerNTU, ShellTubeHX, Compressor). 5–10× SLP speedup.
5. **Move `TechnologyChoice` to `core/contracts.py`** — closes the L3 → L2 leak.
6. **Auto-detect or force OPEX convention** — eliminate the 3600× annualisation
   footgun.
7. **Wire `available_units_for_persona` into the Custom Builder UI** — v1.6 G.1
   helper exists but the picker doesn't filter yet.
8. **Add Validation / Pinch / Dynamics pages to the UI** — surfaces v1.6 features.
9. **Build PSE Ecosystem flowsheet templates for the 4 case studies** —
   currently only reference CSVs exist; no model to compare against.
10. **Implement `pr_nrtl` + 3-phase VLLE flash** — closes the v1.6 thermo gap
    before v1.7 picks it up as a workstream.

---

## 13. Verdict

v1.6 is a **strong industrial release** with a few clearly-identified gaps:

- The 3-layer architecture is intact and load-bearing.
- The thermo ladder (PR / SRK / NRTL / Wilson / UNIQUAC) is the largest single
  step-change since v1.0.
- The 10 new industrial units are well-tested for contract surface, less so for
  physics validation.
- Dynamics, sizing-modes, and validation infrastructure is built but
  **under-consumed** — none of these features has a fully-wired UI page yet.
- Docs are 4 versions behind and **block adoption** more than any other gap.

**Two pieces of guidance for v1.7 planning:**

1. **Eat the cake first**: split `flowsheet_service.py` / `app_streamlit.py`
   and update docs **before** adding more workstreams. The current monoliths
   make every v1.7 UI change harder.

2. **Activate, don't accumulate**: the v1.7 plan as drafted (Workstreams H–N)
   adds 7 new capability areas. Half the v1.6 features (dynamics, sizing,
   parity, relief) aren't yet UI-visible. v1.7 should split into a **polish
   release (v1.6.1)** that wires what we have, and a **capability release
   (v1.7)** that adds the new tracks. Otherwise the UX gap compounds.

End of audit.
