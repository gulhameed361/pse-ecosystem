# PSE Ecosystem — System State Ledger

**Version:** 1.6.1 (in-progress; v1.6 tagged)
**Date:** 2026-05-25
**Status:** v1.6.1 polish & activation — refactor of `flowsheet_service.py`
and `app_streamlit.py` complete (P.1 + P.2); doc refresh in progress (P.3).
**Test count:** 998 passing, 1 skipped (`pytest -q`).

---

## What's New in v1.6.1 — Polish & Activation

Activates v1.6 features that ship without UI surfaces (dynamics, sizing
modes, validation, relief sizing) and breaks the two 3 000-line monoliths
into focused per-concern modules. **No new capability features** — v1.7
workstreams H–N (pinch, UQ, multi-objective, PR-NRTL, control) all remain
queued.

### Refactor (P.1 + P.2)

- **`pse_ecosystem/ui/flowsheet_service.py`**: 3 392 → 1 446 lines (−57 %).
  Catalogue, factory, templates, port resolver, safety bridge each live in
  their own module now; the original module re-exports every public symbol
  for back-compat.
- **`pse_ecosystem/ui/app_streamlit.py`**: 2 714 → 81 lines (−97 %). Each
  of the 7 Streamlit pages lives under `pse_ecosystem/ui/pages/`, with
  shared helpers (`_init_state`, `_infer_si_unit`, `_require_streamlit`,
  `_docs_dir` / `_load_doc`) under `pse_ecosystem/ui/shared/`.
- The `pse_ecosystem/ui/` layout is now:
  ```
  pse_ecosystem/ui/
    app_streamlit.py       (81 ln)   main() + persona toggle + page list
    flowsheet_service.py   (1446 ln) bridge between UI and lower layers
    catalogue.py           (251 ln)  AVAILABLE_UNITS + persona filter
    instantiate.py         (509 ln)  _instantiate_unit + build_custom_flowsheet
    templates.py           (1056 ln) TemplateSpec + _REGISTRY + loaders
    port_resolver.py       (90 ln)   primary_inlet / primary_outlet
    safety_bridge.py       (244 ln)  compute_safety_margins + ASME
    shared/                          state, formatting, streamlit, docs
    pages/                           dashboard, flowsheet_builder,
                                     gps_weather, solver_monitor,
                                     scenario_manager, solve_history,
                                     help_center, case_study
  ```

### Doc refresh (P.3, this commit)

- All load-bearing markdown files updated from v1.5.2 → v1.6.1.
- `CHANGELOG.md` retro-filled with v1.6 release entries and v1.6.1
  in-progress entries.
- `docs/AUDIT_v1_6.md` — comprehensive post-release audit committed in
  `0850b11` covering inventory, layer-boundary verification, solver suite,
  unit catalogue, costing, dynamics / safety / validation, tests, docs,
  and 10 top action items.
- `docs/PLAN_v1_7.md` — v1.7 capability sprint plan (seven workstreams
  H–N: heat-integration pinch, mass pinch, UQ, multi-objective
  optimisation, PR-NRTL hybrid + VLLE flash, process control,
  cross-cutting).
- `docs/PLAN_v1_6_1.md` — this release's polish plan (eight sub-tracks).

### Remaining v1.6.1 sub-tracks

| Sub-track | Status | Notes |
|---|---|---|
| P.1 — Split `flowsheet_service.py` | ✅ done | commit `66d0112` |
| P.2 — Split `app_streamlit.py` | ✅ done | commit `170171b` |
| P.3 — Doc refresh | ✅ done | commit `f8014f6` |
| P.4 — Analytical Jacobians (CSTRHF + HX-NTU; 3 deferred) | 🔄 partial | CSTRHF + HX-NTU done; Flash / Shell-Tube / Compressor explicitly deferred to v1.7 with rationale |
| P.9 — Split `flowsheet_service.py` further | ✅ done | 1 696 → 609 lines; 4 new sibling modules under `pse_ecosystem/ui/` |
| P.10 — Sweep residual `v1.5.2` doc tags | ✅ done | Active docs cleaned; historical refs retained |
| P.5 — `TechnologyChoice` to core + OPEX guard | ✅ done | commit `120a882` |
| P.6 — Wire persona filter into Custom Builder | ✅ done | |
| P.7 — UI pages: Validation, Pinch, Dynamics, Relief | ✅ done | +14 smoke tests |
| P.8 — End-to-end case-study templates | ✅ done | this commit; 16 e2e tests; SMR ~30% MAPE (CSV inconsistent), MEA/C3/NH3 < 10% |

---

## What's New in v1.6 — Industrial Release (tagged 2026-05-23)

512 → 998 passing tests (+486, zero regressions). Default
`property_method=ideal_gas` and `sizing_mode=rating` preserve byte-
identical numerics on every existing v1.5.3 flowsheet JSON.

Headline additions:

- **Thermo ladder**: ideal-gas → Peng-Robinson → SRK → NRTL → Wilson →
  UNIQUAC, all behind a single `PropertyPackage` ABC + factory.
- **35-unit audit**: every existing unit tagged with a `UnitCategory`
  (INDUSTRIAL / SCREENING / DIDACTIC / LEGACY); CAPEX / KPI contract
  gaps closed; HX fouling resistance, Pump NPSHa, Compressor multi-stage,
  CHP NOx emissions.
- **10 new units**: ExpanderHF, MultistageCompressorHF, DecanterHF,
  SteamDrumHF, FiredHeaterHF, PackedColumnHF, MembraneModuleHF,
  BatchReactorHF, TrayColumnHF, CrystallizerHF.
- **Sizing modes**: RATING / DESIGN / PERFORMANCE_CHECK with
  per-unit `design_sizing` hook.
- **Dynamics framework**: `DynamicSimulator` wrapping scipy.solve_ivp +
  `Perturbation` step / ramp / pulse / sinusoid + `BaseUnit.dynamic_residuals`
  hook (opt-in).
- **Safety**: API 520 / 521 relief sizing, depressuring schedule, HAZOP
  node generator.
- **Validation**: parity dashboards (MAPE / RMSE / R²), Aspen `.bkp`
  ASCII parser, kinetic tuner, 4 bundled case studies.

See `CHANGELOG.md` for the full list and `docs/AUDIT_v1_6.md` for a
post-release deep audit.

---

## What's New in v1.5.2 — Dual-Persona Stabilisation

*434 pytest pass, 0 skipped, 0 failures.  20/20 ui_audit pass.*

### Bug Fix A — Pandas 2.0 `applymap` AttributeError (Industrial Persona)

**Root cause**: `df_safety.style.applymap()` in `_render_industrial_solver_view`
raises `AttributeError: 'Styler' object has no attribute 'applymap'` on Pandas ≥ 2.0.

**Fix**: Changed to `df_safety.style.map()` (line 1616 of `app_streamlit.py`).

### Bug Fix B — Plotly `yaxis` Keyword Collision (Scenario Manager)

**Root cause**: `fig_sc.update_layout(yaxis=..., **PSE_PLOTLY_TEMPLATE["layout"])`
in `_page_scenario_manager` raised `TypeError: got multiple values for keyword
argument 'yaxis'` because the template already contains `"yaxis"`.

**Fix**: Compute `_sc_layout` by excluding `"yaxis"`, `"yaxis2"`, and `"barmode"`
from the template before unpacking. Documented in `DEVELOPER_GUIDE.md §17.2`.

### Bug Fix C — Component-Mismatch Port Connection Skip

**Root cause**: `build_custom_flowsheet()` silently skipped connections between
ports with different component counts (e.g. 1-species storage → 6-species separator),
recording a fatal warning.

**Fix**: Zero-fill padder (v1.5.2) — matches species by name, pads unmatched inlet
species to zero via `extra_equalities`. Documented in `THEORY_REFERENCE.md §11.9`.
New tests: `test_zero_fill_padder_connects_matched_species` and
`test_7_unit_chain_exact_equality_count` (confirms 33 equalities).

### Bug Fix D — Version Drift: `pyproject.toml` vs `__init__.py`

`pyproject.toml` was pinned at `1.5.0.dev0` while `__init__.py` exported `1.5.2`.
Updated `pyproject.toml` to `1.5.2`; test renamed from `test_version_is_v150dev`
to `test_version_is_v152`.

### Bug Fix 1 — Custom Flowsheet JSON Serialization Crash

**Root cause**: `st.session_state["custom_flowsheet"]` stored the `BaseFlowsheet`
object.  `serialize_flowsheet_config()` passed it directly to `json.dumps`, which
raised `TypeError: Object of type BaseFlowsheet is not JSON serializable` on every
page render after a custom flowsheet was built.

**Cascade effect**: the crash at line 428 of `app_streamlit.py` halted page rendering
before the tabbed section, which caused the Objective Function selector tab to also
disappear.

**Fix**: introduce a separate `st.session_state["custom_flowsheet_cfg"]` key that
holds the JSON-serializable spec dict `{"units": [...], "connections": [...]}`.
`serialize_flowsheet_config` now reads `custom_flowsheet_cfg`; the `BaseFlowsheet`
object in `custom_flowsheet` is untouched and used only by the solver.  Load-from-JSON
now restores `custom_flowsheet_cfg` and sets `custom_flowsheet = None` (user must
click "Build & Select" to regenerate the object).

**Files changed**: `app_streamlit.py` (`_init_state`, `_render_custom_assembler`,
`_page_flowsheet_builder` save/load block), `pse_ecosystem/__init__.py`.

### Bug Fix 2 — Pre-solve Validator Crash for Custom Templates

**Root cause**: The Pre-solve Validator called `load_template("custom.user_flowsheet", {})`
which produced an empty placeholder flowsheet rather than the user's assembled units.

**Fix**: when `selected_template == "custom.user_flowsheet"`, read the already-built
object from `st.session_state["custom_flowsheet"]` directly.  If the object is `None`
(not yet built), show a descriptive warning and `st.stop()`.

### Enhancement — Scenario Manager & Analysis

**Scenario Manager** page renamed to **Scenario Manager & Analysis** (nav title and
page heading updated).

**New section: Sensitivity Analysis** (below the comparison table):

| Mode | Re-solve? | Parameters covered |
|---|---|---|
| Economic sweep | No | Plant life, WACC, electricity price, biomass price, operating hours |
| Engineering sweep | Yes (LP per point) | Any numeric template parameter (e.g. feed flow, temperature, pressure) |

- User picks a captured scenario + sweep type + parameter + range + number of points.
- Economic sweep re-computes `compute_project_economics()` (≈1 ms/point) and plots
  LCOH, NPV, TAC vs. the selected economic parameter.
- Engineering sweep calls `load_template()` + `Orchestrator.solve()` per point and
  plots the first 5 KPIs vs. the selected engineering parameter.
- Custom-assembled flowsheets are excluded from engineering sweeps (no fixed param
  spec); users are directed to the Flowsheet Builder 1D Sensitivity Sweep tab instead.
- Scenario record now stores `template_params` snapshot for use by engineering sweeps.

---

## What's New in v1.5.1 — Industrial Decision Support

*431 pytest pass, 0 skipped, 0 failures.  +24 system_audit, 20 ui_audit.  30 new tests in `test_v151.py`.*

### Grand 1 — Scenario Manager (new page)

New **Scenario Manager** navigation page (📋) captures up to 4 named solve results.
Each scenario records: template key, parameters, all KPIs, and a project economics
summary (Installed CAPEX, OPEX, TAC, LCOH, LCOE, NPV, IRR).  

Outputs:
- Side-by-side comparison table with % delta vs the Base scenario
- LCOH / NPV grouped bar chart (Plotly)
- Excel download: Sheet "Scenario Comparison" + "Solver Stats"

No re-solve is triggered; scenarios are captured from `st.session_state["last_result"]`.

### Grand 2 — Tornado Chart + Break-even Calculator

**Tornado chart** (inside Industrial view expander "Economic Sensitivity"):
- `tornado_sensitivity(flowsheet, solution_x, kpis, econ_config, target_metric, perturbation_frac)`
  in `flowsheet_service.py`.
- One-at-a-time perturbation of 8 `ProjectEconomicsConfig` fields (±20 % default, user-adjustable).
- Returns `List[TornadoRow]` sorted by `impact = |kpi_at_high − kpi_at_low|`.
- Target metric: LCOH, LCOE, TAC, Annualised CAPEX, Annual OPEX (selectbox).
- Rendered as a horizontal overlay bar chart.

**Break-even Calculator** (expander "Break-even & NPV Calculator"):
- `compute_npv_with_revenue(flowsheet, solution_x, kpis, econ_config, product_price_USD_per_kg)`
  in `flowsheet_service.py`.
- Computes NPV with an explicit revenue stream (H₂ price × annual production).
- Shows: Break-even price (= LCOH), NPV at market price, margin USD/kg, payback period.
- Mathematical identity: break-even price = LCOH (confirmed analytically).

### Grand 3 — Investor Report Generator

`generate_investor_report(flowsheet, result, econ_config, safety_rows, template_spec, scenario_label, tornado_rows)`
in `flowsheet_service.py`.

Generates a structured Markdown document with:
- §1 Process Description (unit inventory)
- §2 Key Performance Indicators
- §3 Project Economics (key metrics table + break-even callout)
- §4 Engineering Safety Assessment (ASME + flammability table)
- §5 Economic Sensitivity — top 5 tornado rows
- §6 Assumptions & Limitations (fully explicit)

Downloadable via `st.download_button` (`.md`, text/markdown MIME type).
In-app preview via collapsible expander.

### Small Changes (S1, S3, S4, S5, S6, S7)

| ID | Change |
|---|---|
| S1 | ASME material selector dropdown — 6 materials (CS to Hastelloy), changes allowable stress |
| S3 | Carbon intensity benchmark table vs SMR / blue H₂ / grid electrolysis / green H₂ target |
| S4 | `industrial.*` templates auto-set Industrial persona on "Apply & Select" |
| S5 | Equipment datasheet — Excel Sheet 6 with T/P bounds, CapEx, ASME wall thickness per unit |
| S6 | Flammability badge — warns on streams near or above LFL after each solve (Industrial view) |
| S7 | Solve time displayed in convergence banner: "Solved in X.X s" |

### Layer compliance (new additions)

Two new gateway helpers in `flowsheet_service.py` keep `app_streamlit.py` free of
direct `models.*` imports:
- `get_asme_materials()` — deferred import of `ASME_MATERIALS` dict
- `compute_outlet_flammability_warnings(flowsheet, solution_x)` — deferred import of `flammability_margins`

Both verified by `TestComputeOutletFlammabilityWarnings::test_no_pse_models_import_in_app_streamlit`
(AST-level check).

---

---

## What's New in v1.5.0 — Industrial Readiness

*401 pytest pass, 0 skipped, 0 failures.  +24 system_audit, 20 ui_audit.  34 new tests.*

### Dual-Persona UI Toggle

Session-state key `user_persona ∈ {"Academic", "Industrial"}` toggled by a sidebar
`st.radio` widget initialised in `main()` before page dispatch.  Every page function
sees a stable, pre-set persona for the entire Streamlit render cycle.

**Academic view** (Solver Monitor):
- Jacobian condition numbers per unit (re-linearisation at x* via `unit.linearize(PrimalGuess(values=result.x))`)
- KPI sensitivity derivatives `∂KPI/∂var` from `LinearizedModel.kpi_gradients`

**Industrial view** (Solver Monitor):
- CapEx/OpEx grouped bar chart per unit (`unit.capex(x)` / `unit.opex_per_year(x)`)
- ASME safety margin table and flammability indicators (see Safety Framework below)

Same physics, same converged solution — only the presentation branch differs.

`user_persona` is serialised in the flowsheet JSON (`serialize_flowsheet_config`
now accepts `user_persona: str = "Academic"`).  Old configs without the key
default to `"Academic"` on load (backward compatible).

### ASME + Flammability Safety Framework

New pure-Python module: `pse_ecosystem/models/safety/safety_checks.py`

| Function | Formula | Reference |
|---|---|---|
| `asme_minimum_wall_thickness(P, R, S, E)` | t = P·R / (S·E − 0.6·P) | ASME VIII Div.1 UG-27(c)(1) |
| `flammability_margins(composition)` | LFL_mix = 1 / Σ(x_i / LFL_i) | Le Chatelier (1891) |
| `operating_pressure_margin(P_op, P_design)` | (P_design − P_op) / P_design | Engineering design practice |

Flammability database: H₂ [4 / 75 vol%], CO [12.5 / 74], CH₄ [5 / 15], C₂H₆ [3 / 12.4], C₃H₈ [2.1 / 9.5].

Bridge function `compute_safety_margins(flowsheet, solution_x)` in
`flowsheet_service.py` applies these checks post-solve to whitelisted pressure-vessel
units: `Compressor`, `FlashVLHF`, `CSTRHF`, `EquilibriumReactor`, `GibbsReactor`,
`BiomassGasifierHF`.  Returns `List[SafetyMarginRow]`.

**Critical constraint**: none of these functions enter `residual()`, `bounds()`, or
the LP/NLP objective.  They are audit-only.  The `test_flammability_no_pse_imports`
test (AST parse) enforces the layer boundary at CI time.

### Layer boundary validation

| Check | Result |
|---|---|
| `safety_checks.py` has zero `pse_ecosystem.*` imports | PASS (AST-verified by new test) |
| `app_streamlit.py` has no direct `models.*` import | PASS (ui_audit check #3) |
| `compute_safety_margins` defers import inside function body | PASS (matches existing pattern) |

---

---

## What's New in v1.5.0.dev — Multi-Tier Optimization Engine

*321 tests pass (303 release + 18 audit-driven), 2 skipped (pre-existing v1.5.x investigation items), 0 failures.*

### v1.5.0.dev-AUDIT5 — Release-candidate sweep (7 items, 17 new tests)

*367 pytest pass, 0 skipped, 0 failures. + 24/24 system_audit, 20/20 ui_audit.*

| # | Item | Outcome |
|---|---|---|
| **#1** | UI: wire `diagnose()` | New "Pre-solve Validator" expander on Flowsheet Builder runs `BaseFlowsheet.diagnose()` and renders errors / warnings / 6 metric cards. Helper from AUDIT4 #4 now has a UI surface. |
| **#2** | Docs refresh | USER_MANUAL §5 (Pre-solve Validator + Solve History), DEVELOPER_GUIDE §13 (elastic-mode + diagnose() API), THEORY_REFERENCE §8 (CGE definitions), README v1.5.0 highlights. |
| **#3** | CGE KPI fix | `BiomassGasifierHF.kpis` now emits both `CGE_LHV_percent` (legacy LHV-only, can exceed 100%) and `CGE_with_steam_percent` (steam-enthalpy-corrected, ≤ 100% by 2nd law). Steam enthalpy formula refined to 3-term decomposition: liquid sensible + latent + steam sensible (accurate within 3% of NIST steam tables at 800 °C). |
| **#4** | `CHANGELOG.md` | Keep-a-Changelog-formatted release log added at repo root. |
| **#5** | Audit scripts | `tests/system_audit.py` +7 v1.5 checks (24/24), `tests/ui_audit.py` +5 v1.5 checks (20/20). |
| **#6** | Tag `v1.5.0-rc1` | First release-candidate tag pushed; lets internal users pin. |
| **#7** | Streamlit smoke test | New `tests/test_streamlit_smoke.py` uses `streamlit.testing.v1.AppTest` to render every page in-process and assert no unhandled exception (7/7 pass). |

---

### v1.5.0.dev-AUDIT4 — Follow-up sweep (6 enhancements, 10 new tests, 2 previously-skipped tests unskipped)

*360 tests pass (up from 352), 0 skipped, 0 failures.*

| # | Fix | Description |
|---|---|---|
| **#1** | 🔴 Convergence | The two `v1.5.x INVESTIGATION ITEM` skips are gone. `biomass.gasification_to_hydrogen` converges in **8 iterations**; `grand_challenge.gasification` converges via ADAPTIVE cascade. Three-part fix: (a) AUDIT3's L3-3 analytical Jacobian for BiomassGasifierHF; (b) NEW elastic-mode LP fallback in `lp_builder.build_lp(elastic_penalty=…)` adding slack variables to every equality with high penalty + damped-step recovery when slack > tol; (c) widened the biomass template's `extra_bounds` from 0.4×–4× to 0.05×–20× of the heuristic estimate. |
| **#2** | 🟡 Conditioning | `SLPConfig.scale_rows: bool = False` wires `compute_residual_row_scaling` into `lp_builder.build_lp(scale_rows=True)`. Opt-in per-row Jacobian normalisation preserves v1.5 LP topology for existing callers. |
| **#3** | 🟡 Honesty | `NLPDriver._ipopt_available()` probes for real IPOPT on PATH and emits a diagnostic when found — wiring point for v1.6 Pyomo+IPOPT path. |
| **#4** | 🟠 UX | `BaseFlowsheet.diagnose() -> {errors, warnings, info}` — non-raising pre-solve validator that catches inverted bounds, very-wide bounds, orphan units, etc. Designed for the UI to call BEFORE Run Solve. |
| **#5** | 🟠 Analysis | 2D Pareto sweep now overlays the **non-dominated frontier** (lower-left envelope by default, axis-direction toggles let user invert per-axis). |
| **#6** | 🟢 QoL | Solve history persists to `~/.pse_ecosystem/history.jsonl` via `record_solve_in_history` + `load_persisted_solve_history`; the Solve History page seeds from disk on first render. |

---

### v1.5.0.dev-AUDIT3 — Comprehensive 3-layer audit (17 defects, 29 new tests)

*350 tests pass, 2 skipped, 0 failures.*

**Layer 3 (physics)** — 3 fixes:

| ID | Severity | Fix |
|---|---|---|
| **L3-1** | 🔴 CRITICAL | OPEX time-unit standardisation: `BaseUnit._OPEX_CONVENTION` (`USD_per_year` / `USD_per_second` / `yield_coefficient`) ends the inconsistency where Excel Sheet 5 Annual OPEX was wrong by factor ~3×10⁷ when biomass units dominated |
| **L3-2** | 🟡 Important | H₂ production KPI uid-prefix standardisation across PEMToy, ElectrolyserHF, BiomassGasifierHF, H2SeparatorPSA |
| **L3-3** | 🟡 Important | BiomassGasifierHF closed-form analytical Jacobian (6×8 / 6×9) replaces 48-call FD fallback |

**Layer 2 (solvers)** — 6 fixes:

| ID | Severity | Fix |
|---|---|---|
| **L2-1** | 🔴 CRITICAL | `SolveMode.NLP_SCIPY` introduced as canonical alias for `NLP_IPOPT` (which actually uses scipy L-BFGS-B, not IPOPT) — docstring honesty |
| **L2-2** | 🟡 Important | `scaling.compute_residual_row_scaling()` helper — foundation for v1.6 LP-row scaling |
| **L2-3** | 🟡 Important | NLPDriver honours `cfg.eps_x` via step-norm callback |
| **L2-4** | 🟡 Important | NLPDriver restart-with-perturbation (up to 3 attempts) — single L-BFGS-B failure no longer aborts the solve |
| **L2-5** | 🟠 Medium | SLP MAX_ITER message reports final trust-region radius + explicit "Trust region collapsed" diagnostic |
| **L2-6** | 🟠 Medium | `BaseFlowsheet.aggregate_kpis(x)` is the single source of truth; 4 duplicate `_aggregate_kpis` delegate to it (and skip-on-error per unit) |

**Layer 1 (UI)** — 6 improvements:

| ID | Priority | Improvement |
|---|---|---|
| **UI-1** | 🟡 High | Sankey diagram for material flows on Solver Monitor results |
| **UI-2** | 🟡 High | **Solve History page** — rolling log of last 20 solves with metrics summary |
| **UI-3** | 🟡 High | Save / Load flowsheet config as JSON on Flowsheet Builder (reproducibility) |
| **UI-4** | 🟠 Medium | `PSE_PLOTLY_TEMPLATE` unifies fonts, colorway, axis grids, backgrounds across all charts |
| **UI-5** | 🟠 Medium | 2D Pareto-style sweep tab — two parameters × ≤ 6×6 grid → KPI-vs-KPI scatter with converged/failed split |
| **UI-6** | 🟠 Medium | "Reset to defaults" button alongside "Apply Objective" in every objective tier expander |

---

### v1.5.0.dev-AUDIT — Hardening sweep (8 defects closed)

| ID | Severity | Fix |
|---|---|---|
| **D1** | CRITICAL | `compute_project_economics()` now reads from real unit `capex(x)`, `opex_per_year(x)` and the unit-tagged `H2_production_kg_h/_s` KPIs (previous version queried non-existent keys → Sheet 5 was always zero/NaN) |
| **D2/D7** | Important | Module docstrings in `app_streamlit.py` and `__init__.py` bumped to v1.5.0.dev |
| **D3** | Important | `ProjectEconomicsConfig` + `EconomicEngine` validate `plant_life_yr > 0`, `interest_rate ≥ 0`, `0 < operating_hours ≤ 8760`, `lang_factor ≥ 1` in `__post_init__` (zero/negative values now raise `ValueError`) |
| **D4** | Important | `EconomicEngine.irr()` returns `+inf` for IRR > `r_max` (default 10 = 1000%) instead of silently clamping; `r_max` parameter exposed for user override |
| **D5** | Important | `ProjectEconomicsConfig.target_year` field added — UI can now control CEPCI cost-escalation target year |
| **D6** | Important | `ProjectEconomicsConfig.lang_factor` field added — installed-cost multiplier exposed at UI layer |
| **D7** | Minor | New `TestComputeProjectEconomicsAudit` (6 tests) + `TestInputValidation` (10 tests) classes — exercise the real KPI pipeline end-to-end |
| **Excel** | Important | Sheet 5 now includes `Purchase CAPEX (CE500)`, `Installed CAPEX`, `H₂ Production`, `Power Output`, `Tax Rate`, `Inflation Rate`, `Target Year`, `Lang Factor`, `CEPCI Escalation` rows (24 metrics total). Failure during economics computation emits an ERROR row instead of silent absence. |

| Area | Change |
|---|---|
| **Layer 3 — `economic_engine.py`** | Added `EquipmentScalingRule` (C = C₀·(S/S₀)^α), `EconomicEngine.npv()`, `EconomicEngine.irr()` (bisection), `EconomicEngine.lcoe()` |
| **Layer 1 bridge — `flowsheet_service.py`** | Added `ProjectEconomicsConfig` dataclass (plant life, WACC, tax rate, feedstock/utility prices, carbon tax); `OBJECTIVE_TIERS` dict (3 tiers, 11 objectives); `compute_project_economics()` helper; extended `build_objective_extra()` with 5 new modes |
| **Layer 1 UI — `app_streamlit.py`** | Redesigned Objective Function tab: 3-tier radio selector → context-dependent expanders per tier; all solver calls pass `ProjectEconomicsConfig`; added "Project Economics & Cash Flow" Excel Sheet 5 |
| **Tests** | New `tests/test_technoeconomic_optimization.py` — 28 tests covering EconomicEngine extensions, ProjectEconomicsConfig, all new objective modes, layer-boundary compliance |
| **Docs** | All `docs/*.md` + `README.md` bumped to v1.5.0.dev |
| **Version** | `pyproject.toml` + `pse_ecosystem/__init__.py` → `1.5.0.dev0` |

### New objective modes (v1.5.0.dev)

| Tier | Mode | LP Proxy |
|---|---|---|
| Technical | Minimize Specific Energy Consumption | Energy penalty + H₂ reward |
| Technical | Minimize Carbon Intensity | Carbon tax × CO₂ outlet flow |
| Economic | Maximize NPV | TAC minimisation proxy (steady-state equivalence) |
| Economic | Maximize IRR | Same as NPV; exact IRR post-solve via bisection |
| Technoeconomic | Minimize LCOE | Energy penalty + net-power reward |

---

## What's New in v1.4.1 — Physics Safety Net

*Commits: `1a755d3` (v1.4.0-HOTFIX) + `ae00231` (v1.4.1). 275 tests pass, 2 skipped with documented v1.5.x investigation reasons, 0 xfailed.*

### The unifying theme

All three changes share the same principle: **the solver must fail loudly on non-physical results, never silently.** The 7-unit biomass Excel audit (Extra/pse_results.xlsx) revealed three distinct silent-failure modes; v1.4.1 closes all of them.

### v1.4.0-HOTFIX — Connection validation + UI auto-conversion (commit `1a755d3`)

#### Layer 2/Flowsheet — Phantom-connection guard

`pse_ecosystem/flowsheets/base_flowsheet.py` — `validate()` extended to check
every `Connection.var_a` and `Connection.var_b` against the union of all unit
`variables()`. Previously only `extra_equalities`/`extra_bounds`/`objective_extra`
were verified. A wrong port name silently created a phantom LP constraint; units
solved independently, each achieving `res_norm ≈ 0`, and the SLP reported
`CONVERGED` while inter-unit mass/energy balances were completely violated.

*Root cause of the Excel anomalies:*
- Gasifier biomass_in = 0.078 kg/s (should be 429 kg/s from storage) — connection broken
- Cyclone inlet H₂ = 9,552 kg/s vs. gasifier syngas_out H₂ = 60.5 kg/s — not connected
- Cooler all outlet flows = exactly 1,000 kg/s (hit `CoolerHFParams.feed_max` bound)
- Compressor: 9.9 MPa in → 0.5 MPa out (decompression), F_H₂ 191 → 5,340 kg/s (mass created)

The fix raises `ValueError` at the start of every solve (via `build_lp` → `validate()`),
naming the bad connection index and variable before the LP is built.

*13 new tests* in `TestFlowsheetValidateConnections`.

#### Layer 1 — UI unit auto-conversion on_change callback

`pse_ecosystem/ui/app_streamlit.py` — the unit dropdown in the Custom Flowsheet
Builder had no `on_change` callback. Changing from °C to K left the numeric
value unchanged (800 °C → displayed as "800 K"). Fix: `_make_unit_callback`
factory produces a closure per parameter that converts `session_state[value_key]`
via `to_native → from_native` when the unit dropdown fires. Tracks the previous
unit in `session_state[prev_unit_key]` to compute the direction of conversion.

*7 new tests* in `TestUnitAutoConversionCallback`.

### v1.4.1 — Bound-saturation guard (commit `ae00231`)

#### Layer 2 — `SolveResult.bound_active` + `SLPConfig.fail_on_bound_saturation`

**`pse_ecosystem/core/contracts.py`:** `SolveResult` gains `bound_active: List[str]`
— variable names whose converged value sits at (or within 1e-6 rel-tol of) a
non-fixed bound. Excludes intentionally-fixed variables (lb == ub).

**`pse_ecosystem/solvers/slp.py`:** new `_detect_bound_active()` method walks
the converged solution against `flowsheet.aggregated_bounds()` and populates
`bound_active` on every CONVERGED return path (iterative SLP loop and one-shot
LP fast path). `SLPConfig` gains `fail_on_bound_saturation: bool = False`; when
`True`, an otherwise-CONVERGED solve is downgraded to `NUMERICAL_ERROR` with
a message naming up to 5 offending variables.

**Why warn-not-fail by default:** some flowsheets legitimately operate at a bound
(e.g. a compressor running at its rated W_max). Default `False` preserves existing
behaviour; opt in per-flowsheet when you want CI to catch bound-saturated solutions.

#### Layer 1 — UI and Excel surfacing

- **Dashboard**: yellow warning banner when `result.bound_active` is non-empty,
  with an expander listing the saturated variables.
- **Excel export**: new 4th sheet "Bound Saturation" (Variable | Value | Lower |
  Upper | Hit). Always emitted (headers-only when clean) to keep export shape
  consistent. `Optimization Summary` sheet gains `BoundActiveCount` row.

*3 new tests* in `TestBoundSaturationGuard`.

### Silent xfail / skip closure

- **`tests/test_biomass_audit.py`** — `test_biomass_flowsheet_solves_to_convergence`
  was `@xfail(strict=False)` (passes silently when the test fails). Investigated
  on 2026-05-19: the template returns INFEASIBLE after 3 warm-start restarts under
  every SLP config attempted. Structural infeasibility is a real v1.5.x item.
  Converted to `@pytest.mark.skip` with the full diagnostic reason (27 extra_bounds
  possibly incompatible with 13 connection equalities).

- **`tests/test_grand_challenge.py`** — `test_grand_challenge_mass_balance` had
  an inline `if not result.converged: pytest.skip(...)` — quietly hiding
  non-convergence regressions. Promoted to a module-level `@pytest.mark.skip` with
  v1.5.x reason; test body rewritten to `assert result.converged` so removing
  the skip decorator exposes the real check when the underlying solver issue is fixed.

### Carry-forward into v1.5.x

- **LP infeasibility at iter=27 on complex flowsheets.** Both
  `biomass.gasification_to_hydrogen` and the 10-unit grand challenge flowsheet hit
  the same INFEASIBLE-at-iter-27 pattern (3 warm-start restarts exhausted) under
  every SLP config tried (TR on/off, init=0.5/1.0/2.0, max_iter=50–200,
  progressive_tightening, ADAPTIVE cascade). Diagnose by dumping the Pyomo LP model
  at the failing iteration with `model.write("debug.lp")` and inspecting for
  incompatible bound/equality pairs. Likely culprit: the template's many `extra_bounds`
  clashing with connection equalities inside the trust-region box.
- **Smooth-floor WGS equilibrium** — replace `max(x, 1e-12)` kink with
  `(x + √(x²+ε²))/2` for continuous Jacobian.
- **Biomass template extra_bounds audit** — reduce `extra_bounds` count from 27
  toward only those truly required by the engineering spec.

---

## What's New in v1.4.0-AUDIT2 — Second-Pass Hardening

A second five-agent code audit was run after the first round of fixes. It
focused on DAC/Power Layer-3 (uncovered by the first audit), the LP/MILP
internals, flowsheet templates, and cross-cutting concerns — and looked
explicitly for regressions introduced by the first hardening pass. The
audit returned 37 new findings; this release closes 35 of them. Suite now
stands at **259 passed, 1 pre-existing skip, 1 documented xfail, 0
failures** (was 240). 19 of the new pytest functions live in the brand-
new `tests/test_dac_power_units.py`.

### Physics correctness

- **N1** — `solvers/lp_builder.py:78` now raises `ValueError` when two
  contributors declare conflicting variable bounds whose intersection is
  empty. Pre-fix the merge silently produced an inverted interval that
  Pyomo reported as opaque infeasibility.
- **N2** — `models/dac/tvsa_contactor.py` exposed `T_in` and `P_in` as
  port variables but never used them in the residual. The LP picked
  ambient T/P arbitrarily inside `(270, 320) K` and `(95, 105) kPa`. Two
  pin rows (`T_in − 298.15 = 0`, `P_in − 101.325 = 0`) now anchor the
  variables to ambient defaults; analytical Jacobian extended to 7×8.
- **N3** — `models/power/chp_unit.py` docstring overloaded the symbol
  `Q_comb` between "raw fuel energy" and "post-combustor heat release".
  Rewritten to distinguish `Q_fuel` (raw) from `Q_comb` (post-combustor)
  and trace the η_comb × η_turb × η_hrec chain explicitly. No physics
  change.

### UI / UMS

- **N4** — `models/dac/electrolyser_hf.py` now clamps `eta_elec` to
  `[0.30, 0.95]` at constructor time. Pre-fix accepted 0.05 → 2858 kW
  per mol/s H₂ (unphysical).
- **N5** — `models/dac/tvsa_contactor.py` ambient CO₂ mole fraction is
  now a per-instance parameter (`y_co2_atm`) with the 415 ppm default,
  validated to `[1e-6, 0.05]` (1 ppm – 5 %). Lets pilot DAC studies use
  current ambient (425 ppm) or indoor-air HVAC loops (1200 ppm).
- **N12** — `ui/app_streamlit.py:496` and `:1250` swallowed every
  exception silently in the sweep loop and the capex extractor.
  Replaced with `st.warning(...)` so users see the failure.
- **N31** — Excel exporter's `getattr(_unit, "capex_USD", lambda)` was
  dead code post-H6 (no unit defines a `capex_USD()` method anymore).
  Switched to `capex` per the `BaseUnit` contract; deduplicated rows so
  units whose `kpis()` dict already reports `capex_USD` aren't doubled.

### Solver internals

- **N6** — `solvers/milp_builder.py` row-M sizing now incorporates the
  actual aggregated bound widths of each non-zero column, so a row
  spanning flow variables (gated big-M) and structural ones (wide P/T
  ranges) is correctly relaxed under `y = 0`.
- **N7** — Gated rows with non-zero RHS on a zero Jacobian row now emit
  a `RuntimeWarning` instead of being silently relaxed.
- **N8** — `solvers/lp_builder.py:140` trust-region anchor fallback for
  variables missing from `x_anchor` is now the bound midpoint (was
  `0.0`, which collapsed the TR box outside feasibility for variables
  bounded `(1e4, 1e7)` Pa).
- **N9** — `flowsheets/base_flowsheet.py::initial_guess()` half-bounded
  fallback now scales with `0.1 × |bound|` (was a flat `±1.0` offset).
  For a pressure variable bounded `(1e4, ∞)` Pa the starting point is
  now 1.1e4 Pa instead of 1.0001e4 Pa.

### Silent fallbacks → logged warnings

- **N10** — `models/separators/distillation_hf.py:163` and
  `models/reactors/gibbs_reactor.py:169` now cache the inner-solve
  exception on the unit instance (`_last_underwood_error`,
  `_last_inner_error`) so downstream KPI / status reports can surface
  the root cause instead of reporting a plausible-looking but wrong
  result.
- **N11** — `BaseFlowsheet.validate()` cross-checks every variable
  referenced in `extra_equalities`, `extra_bounds`, and
  `objective_extra` against `all_variables()`. Called from the top of
  `build_lp` so a typo in a template surfaces with a helpful error
  before Pyomo's opaque `KeyError`.
- **N20** — `ui/flowsheet_service.py::_instantiate_unit DistillationHF`
  no longer silently rewrites user-supplied `hk` / `lk` to first/last
  VLE species when they're absent from `components`. Raises with a
  clear error instead.
- **N30** — TRF feasibility-restore caught bare `Exception:`; narrowed
  to `RuntimeError | ValueError | ArithmeticError` so programming bugs
  propagate.

### DAC / Power polish + dedicated tests

- **N13** — Sabatier `K_Sab(T) = exp(4786/T − 4.92)` now carries
  references (Vannice 1976, Lunde & Kester 1973, NIST JANAF) and notes
  the calibration range (600–1000 K, low pressure).
- **N15** — KPI specific-energy divisions in `TVSAContactor` and
  `MethanationReactor` now use `1e-6 mol/s` and `1e-3 mol/s` floors
  (was `1e-9`), preventing the 1e13 kWh/tonne nonsense at trace flows.
  TVSA's KPI dict adds a `_warning_low_feed` flag at the floor.
- **N16** — `ElectrolyserHF.kpis()` no longer reports `eta_elec * 100`
  as if it were a per-iteration KPI; clarified as a nameplate constant.
- **N32** — New `tests/test_dac_power_units.py` provides 19 direct
  contract checks: residual shapes, Jacobian dimensions, KPI near-zero
  handling, η clamps, ambient-CO₂ clamps, energy-balance ratios.

### Packaging completeness

- **N28** — `pyproject.toml` now declares `include-package-data = true`
  and `[tool.setuptools.package-data] "pse_ecosystem" = ["data/*.json"]`.
  New `MANIFEST.in` ships `docs/*.md` and `data/*.json` in the sdist
  and wheel so pip installs expose them to the Help Center loader and
  the EconomicEngine CEPCI loader.
- **N29** — `scripts/package_app.py` pre-flight now checks `openpyxl`
  in the required-packages list; packaged apps without it crashed on
  Excel download.

### Template + infrastructure polish

- **N21** — `flowsheets/industrial/syngas_production.py` asserts that
  `gasifier.v_h2` is a string before using it as a dict key.
- **N22** — `flowsheets/industrial/green_hydrogen.py` `kg_h_to_mol_s`
  coefficient is now flagged as H₂-specific so a future generalisation
  to multi-species mixers doesn't reuse the H₂ molar-mass coefficient.
- **N23** — `flowsheets/small/adiabatic_cstr_flash.py` no longer
  overwrites a caller-supplied `cstr_params.reactions`.
- **N24** — `flowsheets/small/mixer_settler.py` deep-copies the caller's
  `mixer_params` / `sep_params` before mutation.
- **N26** — Help Center loader's `@st.cache_data` cache key switched
  from file `mtime` to SHA-1 content hash. Robust to symlink mtime
  inconsistencies; invalidates only when the bytes actually change.
- **N27** — `_load_doc(rel_name)` now resolves the candidate path and
  asserts it lives under `docs/`, refusing directory-traversal inputs.
- **N33** — `CompositeUnit.__init__` validates that every name in
  `exposed_inputs` / `exposed_outputs` exists in the inner flowsheet's
  `all_variables()`.
- **N35** — Module-load self-check in `flowsheet_service.py` asserts
  every `_REGISTRY` entry has a corresponding loader in `_LOADER_MAP`
  or `_MILP_LOADER_MAP`. Dead loaders trigger a `RuntimeWarning`.
- **N36** — Builder's Build & Select banner now warns when the user
  has picked the same Type for ≥3 units (a typo footprint from the
  saturating default Type index past unit 7).
- **N37** — Site Weather page tz input changed from free text to a
  curated `selectbox` populated from `zoneinfo.available_timezones()`,
  so typos like `"Europe/Lonon"` are impossible.

### Skipped (false positives on close reading)

- **N18** — TRF funnel switching test uses `theta_old`; the agent
  flagged it as needing paper verification. On re-reading the comment
  at `trf/funnel.py:30`, the notation matches Eason & Biegler 2016
  intent (measuring reduction relative to a high baseline). Left as-is.
- **N19** — Filter invariant validation. The filter is correct on
  insertion; corruption would require upstream code violation that is
  not exposed.
- **N34** — `objective_kpi` field validation. Deferred; the field is
  advisory metadata and the LP builder ignores invalid values
  gracefully.

### Carry-forward into v1.5.x

- Numerical-noise gating in `milp_builder` (the row-M now also accounts
  for variable bounds, but the noise threshold `1e-9` is still hard-
  coded — could become a `TRFConfig`-style parameter).
- Symbolic Sabatier K_eq validation against an external thermodynamic
  reference (NIST WebBook query) as a regression-guard test.
- The xfailed biomass-to-hydrogen test still needs SLP re-tuning.

---

## What's New in v1.4.0-CARRYFORWARD — Audit Polish + CI Integration

Closes the remaining items flagged in the v1.4.0 audit punch list. Suite
now stands at **240 passed, 1 pre-existing skip, 1 xfail (documented),
0 failures** (up from 213 in v1.4.0-HARDENING).

### Audit-script CI integration (M17)

- `tests/biomass_audit.py` renamed to `tests/test_biomass_audit.py` so
  pytest discovers it natively. The rename surfaced two latent test bugs
  (lowercase regex `phase mismatch` / `species mismatch` failing to match
  the real `Phase mismatch` / `Species mismatch` messages — fixed via
  case-insensitive regex flag `(?i)`) and one pre-existing convergence
  failure on the biomass-to-hydrogen template under
  `trust_region_init=0.5`. The convergence test is now marked
  `@pytest.mark.xfail` with a clear reason; the flowsheet itself converges
  via `test_grand_challenge.py` under different solver tuning.
- New `tests/test_audit_scripts.py` runs `ui_audit.py`, `system_audit.py`,
  and `industrial_audit.py` as subprocesses under pytest and asserts
  exit-code 0, so the full audit fleet is now part of CI. `ui_audit.py`
  also picked up a stale category whitelist (`{"Small", "Hydrogen",
  "Industrial", "Custom"}`) that did not match the v1.3.0+ industrial-
  sector category names — expanded to cover both naming families.

### Progressive-tightening documentation (M1)

`slp.py::_tighten` now ships a table of effective multipliers and an
explanation of why `eps_kpi` uses ×10 / ×3 while `eps_x` and `eps_f` use
×100 / ×10. The schedule is intentionally chosen so all three signals
sit in the same decade at every band; the multipliers differ only
because `eps_kpi` has a 10× larger base value.

### Template-vs-custom numerical parity (M12)

`test_template_path_and_custom_path_yield_identical_solution` builds a
`CoolerHF` flowsheet twice — once via direct Layer-3 factory (the path
`load_template()` uses internally), once via `build_custom_flowsheet`
— solves both via `Orchestrator.solve()`, and asserts a bit-identical
variable vector and identical solver status. Confirms the architecture
claim that custom vs. template construction is a Layer-1 distinction
the solver never sees.

### Layer-3 polish (L5, L7, L8)

- `base_unit.py::_finite_difference_jacobian` now caps the FD step at
  `0.1·|x_val|` once `|x_val| > 1`, so the perturbed point never
  overshoots a variable bound by more than 10 % for large-magnitude
  variables.
- `separators/separator_hf.py` residual now carries an explanatory
  comment on why the closure constraints are kept alongside the split-
  fraction rows (drift-detection, not redundancy).
- `reactors/gibbs_reactor.py` class docstring now states explicitly that
  the model is isothermal-only (`T_out = T_in`); points at
  `EquilibriumReactor` for adiabatic / with-Q operation.

### UI polish (L9, L10)

- Streamlit nav page renamed from `"GPS Weather"` to `"Site Weather"`
  (the page has lat/lon text inputs, not a map).
- `DEVELOPER_GUIDE.md` §12 expanded to 8 industrial sectors with the
  v1.4.0 catalogue, and a new `Step 2a` describes the
  `TYPE_ID_SUGGESTIONS` registration step.

### Carry-forward into v1.5.x (updated v1.4.1)

- **LP infeasibility at iter=27 on complex flowsheets.** Both the biomass
  template and the grand challenge hit INFEASIBLE-at-iter-27 under every
  SLP config attempted. Both tests are now `@pytest.mark.skip` with full
  diagnostic context (see v1.4.1 section above).
- **Smooth-floor WGS equilibrium.** Replace `max(x, 1e-12)` kink with
  `(x + √(x²+ε²))/2` so the Jacobian stays continuous.
- **Biomass template extra_bounds audit** — 27 extra_bounds may be over-constrained;
  audit and reduce to only engineering-required values.

---

## What's New in v1.4.0-HARDENING — Audit Punch-List Fixes

A five-agent code audit of every file in the repository (see the punch list
shipped with this commit) identified 42 defects across the three layers.
This release closes everything in the **CRITICAL**, **HIGH**, and almost all
**MEDIUM** bands; two audit findings (H4 — re-linearise MILP after SLP; M3
— filter insertion symmetry) turned out to be false positives on close
reading and were not changed.

### Solver core (`solvers/`)

- **C1 — TRF spurious convergence.** `trust_region_driver.py:209` had the
  step-norm condition inverted: an accepted step zeroed `step_norm`, which
  then unconditionally passed the convergence guard at line 230. Rewritten
  to capture the step magnitude *before* the in-place update of `x_k` and
  force `step_norm = +∞` on rejected steps so the test cannot fire
  spuriously. New regression test:
  `tests/test_unrestricted_flowsheet.py::test_trf_convergence_not_spurious_on_first_accepted_step`.
- **H1 — SLP warm-start clip.** `slp.py:233–234` simplified to a single
  `np.clip(x + perturbation, lo, hi)` after disentangling the redundant
  `lo > -1e18` / `hi < 1e18` ternary chain.
- **H2 — MILP big-M.** `milp_builder.py:38` default lifted from `1e6` to
  `1e9` with documented rationale; industrial flow ranges (≤ 1e3 kg/s,
  ≤ 1e8 Pa, ≤ 1e8 W) now sit safely below the cut.
- **H3 — TRF `eta1` shrink branch.** `trust_region_driver.py:198` now
  implements the Eason & Biegler 2016 §3.2 schedule in full: `ρ ≥ η₂`
  grows Δ, `η₁ ≤ ρ < η₂` keeps Δ, `ρ < η₁` shrinks Δ even when the step
  was accepted on filter grounds.
- **M2 — NLP scipy tolerances.** `ipopt_driver.py:75–79` annotated to
  document why `ftol = eps_f²·1e-2` (objective scale is ½‖f‖²).

### Properties / VLE / ideal gas (`models/properties/`)

- **C2 — Antoine `KeyError`.** `vle.py::K_value` now raises a descriptive
  `ValueError` listing every species in the Antoine table when an unknown
  species is requested.
- **C3 — Rachford–Rice all-K=1 degeneracy.** `vle.py::rachford_rice` early-
  exits with `NaN` when every K-value is within 1e-9 of unity, and the
  denominator inside the `_rr` inner function is now guarded against
  near-singular values.
- **M6 — Ideal-gas Cv floor.** `ideal_gas.py::gamma` clamps `cv = max(cp − R, 1)`
  so a Shomate polynomial dipping below R at low T cannot produce
  `γ ≤ 0`.
- **M8 — HX NTU `exp()` overflow.** `heat_exchanger_ntu.py::_eps_from_NTU`
  clamps the exponent argument to ±700.

### Layer-3 unit fixes (`models/`)

- **H5 — WGS equilibrium floor.** `wgs_reactor.py:134–135` removed the
  `max(n_*, 1e-12)` floors from the equilibrium residual; variable lower
  bounds at the LP level already enforce non-negative species so the
  Jacobian stays smooth.
- **H6 — CoolerHF `capex` rename.** `cooler_hf.py:142` method renamed
  `capex_USD → capex` to match the `BaseUnit` contract every other unit
  follows.
- **H7 — Compressor γ at large P-ratio.** `compressor.py::_gamma` no longer
  reads `T_out` directly from `x` (which is just the solver guess on iter
  0); it bootstraps an isentropic T_out estimate with γ = 1.4, then
  evaluates the mixture γ at the resulting `T_avg`. Removes the 2-3 %
  error at P_r ≈ 50.
- **M4 — FlashVL phase-boundary singularity.** `flash_vl_hf.py:119–121`
  raises the phase-total floor from 1e-12 to 1e-6 so mole fractions stay
  bounded when one phase vanishes.
- **M5 — Valve dP smoothing.** `valve.py:113–114` adds a 1e-9 ε inside the
  `√(dP)` so the Jacobian stays finite at `P_in = P_out` (the v1.3.x
  version had an infinite derivative at zero crossing).
- **M7 — Distillation θ-bracket guard.** `distillation_hf.py:146–148`
  auto-swaps `α_hk` / `α_lk` when the user mis-labels the keys instead of
  silently falling back to a constant.
- **M9 — PFR ODE failure surfacing.** `pfr_hf.py:181` now caches the
  exception on `self._last_integration_error` so the 1e6 penalty residual
  comes with a debuggable root cause.

### UI / UMS expansion (`ui/`)

- **H10 — Absolute-zero guard.** UMS number inputs now declare
  `min_value` = 0 K / −273.15 °C / −459.67 °F so the user cannot type a
  sub-absolute-zero temperature into the builder.
- **H11 — AVAILABLE_UNITS expansion.** Seven previously-orphaned Layer 3
  classes are now selectable in the Custom Builder dropdown: **Pump,
  Valve, ShellTubeHX, H2SeparatorPSA, GibbsReactor, EquilibriumReactor
  (with a default WGS reaction), DistillationHF**. The catalogue is now
  23 entries across 8 categories, drawn from a 36-class Layer-3 base.
  FlashSL and PFRHF stay Python-API-only because their reaction /
  solubility configuration is richer than the flat parameter form.
- **M10 — Session-state defaults.** `_init_state` now `setdefault`s
  `custom_flowsheet`, `last_flowsheet`, and `objective_config` so a
  direct-lookup style consumer cannot crash on first render.
- **M11 — Excel `_infer_si_unit` regex.** Suffix dispatch is now a sorted
  longest-suffix-wins rule list rather than an ordered `if` chain.

### Packaging / black-box / docs (`models/_blackbox/`, `models/costing/`)

- **H8 — Deferred scipy imports.** `_blackbox/hda_*_bb.py` modules no
  longer import scipy at module load time. A `gui`-only install can now
  import the package without the `blackbox` extra.
- **H9 — `economics.json` via `importlib.resources`.** `economic_engine.py`
  resolves the data file via `importlib.resources.files("pse_ecosystem.data")`,
  falling back to the source-tree path for editable installs.
- **L1 / L2 — Stale `v0.3.0` / `v0` docstrings.** Updated to v1.4.0 in
  `ui/app_streamlit.py` and `ui/entry.py`.
- **L4 — `costing/__init__.py`** now re-exports `CEPCI`,
  `CEPCI_ESCALATION_RATE`, `EconomicEngine`, and the SSLW purchase-cost
  helpers.

### Test coverage (`tests/test_unrestricted_flowsheet.py`)

10 new pytest functions across three new test groups:

- `TestUMSEdgeCases` — NaN, ±Inf, absolute zero, very high pressure.
- `test_solver_mode_nlp_ipopt_smoke`, `..._trust_region_smoke`,
  `..._adaptive_smoke` — smoke tests for the three solver modes that had
  no automated coverage pre-v1.4.0 (and where C1 was hiding).
- `test_trf_convergence_not_spurious_on_first_accepted_step` — direct
  regression guard for C1.
- `test_progressive_tightening_loose_tolerances_in_early_iterations` —
  behavioural test of the `_tighten` schedule at k = 5 / 30 / 80 of 100.
- `test_every_available_unit_instantiates_with_defaults` — catalogue
  smoke test for H11.

**Suite total:** 213 passed, 1 pre-existing skip, 0 failures.

### Known carry-forward (not yet fixed in v1.4.0)

- **M1** — progressive-tightening `eps_kpi` uses ×10 / ×3 multipliers
  versus ×100 / ×10 for `eps_x` / `eps_f`. By design (`eps_kpi` base is
  10× larger), but worth documenting in a future tuning note.
- **M12** — no end-to-end *template-vs-custom* parity test on a complex
  industrial flowsheet (custom-path determinism is verified instead).
- **L5** — finite-difference Jacobian step size for variables near 1e-8
  may cross zero; impact is bounded by `max(1, |x|)` scaling.
- **L8** — `GibbsReactor` is isothermal-only by design; an adiabatic
  variant with a Q-coupled energy balance is a future track.
- **L9** — "GPS Weather" page name implies map UI it doesn't have.
- **L7** — Separator over-determined closure constraints.

---

## What's New in v1.4.0-UMS — Unit Management System

### Layer-1 unit conversion registry (`flowsheet_service.py`)

New module-level table `UNIT_FAMILIES` covering 6 physical dimensions:

| Family       | SI baseline | Display alternatives                 |
|--------------|-------------|--------------------------------------|
| temperature  | K           | K, °C, °F                            |
| pressure     | Pa          | Pa, kPa, bar, atm, psi               |
| mass_flow    | kg/s        | kg/s, kg/h, t/h                      |
| mass         | kg          | kg, t                                |
| power        | W           | W, kW, MW                            |
| energy       | J           | J, kJ, MJ                            |

Public helpers: `supported_display_units(native_unit)`,
`to_native(value, display_unit, native_unit)`,
`from_native(value, native_unit, display_unit)`, `si_baseline_of(unit)`.

### UI integration — per-param unit picker (`app_streamlit.py`)

In `_render_custom_assembler`, every float `ParamSpec` whose native unit
belongs to a recognised family now renders as a nested 2-column cell:
the value input on the left, a unit dropdown on the right. Default
selection mirrors the `ParamSpec.unit`. The UI converts user input back to
the ParamSpec's native unit before storing it in `unit_params`; nothing
downstream sees display units.

### Unit-aware Excel export (`app_streamlit.py`)

- New helper `_infer_si_unit(var_name)` maps solver variable names to SI
  tags using project naming conventions (`F_*` → kg/s, `T*` → K, `P*` → Pa,
  `W_shaft` → W, `duty_kW` → kW, etc.).
- The Stream Table sheet now has columns `Equipment | Port | Variable |
  Value | SI Unit` (was `Unit | Port | Variable | Value`).
- The Unit Performance sheet now has columns `Equipment | KPI | Value |
  SI Unit` (was `Unit | KPI | Value`).
- Optimization Summary unchanged.

### Tests (`tests/test_unrestricted_flowsheet.py`)

20 new pytest functions across three test classes:
`TestUnitConversions` (round-trip math for T / P / mass flow / power /
energy + dimensionless no-op), `TestSupportedDisplayUnits` (family
coverage + SI-baseline lookup), `TestExcelUnitInference` (variable-name
heuristic correctness). Excel round-trip test extended to assert the
`SI Unit` column is present on both numeric sheets.

Total: **34 pytest functions** in `test_unrestricted_flowsheet.py`,
**203+ pytest functions** project-wide.

### Scope notes

- The UMS is **input-side only**. Excel values remain in SI; the `SI Unit`
  column documents the unit of each row's value rather than converting it.
  Per-row output conversion is a future track.
- Layer 3 unit models continue to perform their own SI conversion at the
  parameter-intake boundary (`T_gasifier_C` is still accepted as °C, etc.);
  the UMS lives strictly at the UI ↔ ParamSpec boundary.

---

## What's New in v1.4.0 — Industrial Production Release

### Unrestricted custom flowsheet (`app_streamlit.py`)

- **Unit count cap removed.** `st.number_input("Number of units", …)` no longer
  declares `max_value`; the dynamic-loop builder scales to whatever hardware
  allows. A caption past unit 7 nudges users to set each Type explicitly
  (the default `index=min(i, len(unit_types)-1)` saturates at the last entry).
- **Connection count display fixed.** The Build & Select banner now headlines
  `N units, (N-1) connection(s)` for sequential chains; the internal
  port-variable equality count (e.g. 31 for the 7-unit workshop) is demoted
  to a small caption labelled "Internal port-variable equalities".
- **Smart Unit ID widget no longer sticky.** Widget keys at lines 504 and 510
  now embed `{utype}` so changing a unit's Type re-seeds the ID dropdown.
- **3-column specification grid.** The per-unit parameter form renders in
  `st.columns(3)` rows for Aspen-style density; help-text tooltips, units,
  and `float`/`int`/`select` dtype dispatch all preserved.

### Solver tuning (`app_streamlit.py`)

- **Max iterations slider 1–1500** (was 5–1000). `SLPConfig.max_iter` already
  has no hard upper bound — only the UI clipped.
- **Progressive tightening defaults ON.** The checkbox at the Solver Monitor
  flips to `value=True`; help text updated to reflect the recommended
  loose-to-tight schedule (≈1e-3 → ≈1e-7).
- **Solver Monitor active-objective mirror.** A read-only `st.info` block at
  the top of the Solver Monitor page renders `st.session_state["objective_config"]`
  so users always see which objective is active before clicking Run Solve.

### Help Center & live documentation (`app_streamlit.py`, `docs/`)

- **New 6th nav page: Help Center.** `_page_help_center()` renders
  `docs/USER_MANUAL.md`, the new `docs/WORKSHOP_7UNIT.md`,
  `docs/THEORY_REFERENCE.md`, `docs/ARCHITECTURE.md`, and
  `docs/DEVELOPER_GUIDE.md` in tabs.
- **Loader is mtime-cached.** `_load_doc(name)` uses `@st.cache_data` keyed on
  the file's `mtime`, so edits to the source markdown refresh automatically.
- **`docs/WORKSHOP_7UNIT.md` (new).** Canonical 7-unit biomass → H₂ workshop:
  chain diagram, per-unit input matrix, UI walkthrough, theoretical answer key
  cross-linked to `THEORY_REFERENCE.md` §11.

### Version single-source-of-truth (`pse_ecosystem/__init__.py`, `pyproject.toml`, `app_streamlit.py`)

- `pse_ecosystem/__init__.py:3` now exports `__version__ = "1.4.0"` (was the
  orphaned `"0.0.1"`).
- `pyproject.toml:7` bumped to `1.4.0`.
- The Dashboard caption imports `__version__` from the package instead of
  hardcoding `"v1.3.2"`. All future bumps require editing exactly one file.
- README banner, `ARCHITECTURE.md`, and `USER_MANUAL.md` synced to v1.4.0.

### Tests (`tests/test_unrestricted_flowsheet.py`, new)

13 new pytest functions covering: 8/12/15-unit chain builds, N-1 connection
count, 3-sheet Excel openpyxl round-trip, custom-path solve determinism,
slider-bounds source guard (1/1500), uncapped `number_input` source guard,
progressive-tightening default `True`, and version-string consistency across
`__init__.py` + `pyproject.toml` + `app_streamlit.py`.

### Known issues (carry-forward)

- **session_state widget bloat.** When `n_units` shrinks, leftover widget keys
  (`param_{i}_{name}`) linger. Mitigation deferred to a future release.
- **Streamlit rerun latency.** Past ~20 units, each interaction takes 2–4 s.
  Pyomo model construction is linear in N; the bottleneck is widget rendering.

---

## What's New in v1.3.2 — Proper Economic Objectives & Alignment

### Objective Function — Properly Grounded in Unit Economics (`flowsheet_service.py`)

New public function `build_objective_extra(flowsheet, mode, elec_price, hours, crf)` that
computes objective terms from the actual unit cost architecture:

| Mode | Source | LP terms |
|---|---|---|
| **Feasibility Only** | `force_feasibility=True` | objective = 0 (suppresses unit OPEX too) |
| **Minimize OPEX** | Unit `objective_contribution()` already in LP | `objective_extra = {}` |
| **Minimize Energy** | Searches `all_variables()` for W_shaft/W_elec/electricity_kW | Positive coeff = price × hours |
| **Minimize TAC** | Energy penalty + ElectrolyserHF annualised capex (700 × CRF) | Combined |
| **Minimize LCOH** | TAC + negative H₂ coefficient (most-downstream H₂ outlet variable) | Combined |
| **Maximize H₂ Yield** | Detects H₂ outlet variable via port-tag segment containing "out" | Coeff = −1 |

### `force_feasibility` flag (`base_flowsheet.py` + `lp_builder.py`)

`BaseFlowsheet.force_feasibility: bool = False` — when True, `lp_builder.build_lp()` sets
`objective = 0.0` unconditionally, skipping all unit OPEX contributions. Enables true
feasibility-only mode distinct from "minimize OPEX with existing unit costs".

### Objective Function tab — UI updated (`app_streamlit.py`)

- All 6 objective modes now use `build_objective_extra()` — no heuristic substring matching.
- Advanced economic parameters exposed: electricity price, annual hours, CRF.
- In-place help text explains each mode's LP behaviour.
- Version string: v1.3.1 → v1.3.2.

### Alignment (`pyproject.toml`, `README.md`, `USER_MANUAL.md`)

- `pyproject.toml`: version 1.3.1 → 1.3.2.
- `README.md`: test count 154 → 169.
- `USER_MANUAL.md §2.10`: full rewrite with proper LCOH/TAC explanation and programmatic API.

### Tests (`tests/test_objectives.py`): 8 new tests — 169 total, 1 pre-existing skip.

---

## What's New in v1.3.1 — Connection Fix, Objective Function & Enhanced Export

### Bug Fix
- **"33 connections" display corrected**: The success banner after "Build & Select" now reads
  "N stream link(s) (M variable equalities)". The stream link count (6 for the 7-unit chain)
  is the number you drew; the variable equality count is the solver's internal constraint count.
  These were previously conflated in `len(fs.connections)`.

### UI & UX (`app_streamlit.py` + `flowsheet_service.py`)
- **Smart unit IDs**: Unit ID dropdown now shows type-specific suggestions (e.g. `gasifier_1`,
  `wgs_1`, `comp_1`) using the new `TYPE_ID_SUGGESTIONS` dict in `flowsheet_service.py`.
- **Category filter**: A "Filter unit types by category" selectbox above the unit expanders
  narrows the type dropdown using the existing `UNIT_CATEGORIES` dict (Biomass, Reactors, etc.).
- **Objective Function tab**: New tab in the Flowsheet Builder (alongside Sensitivity Sweep).
  Four objectives: Maximize H₂ Yield, Minimize Energy, Minimize LCOH (proxy), Maximize Net Profit.
  The selected objective is injected into the flowsheet as `objective_extra` before each solve.
- **MAX_ITER tip messages**: When solver returns non-CONVERGED status, an expandable
  "Potential Fix" panel appears with mode-specific troubleshooting steps.
- **Solver default iterations**: slider default raised from 50 → 200.
- **Version tag**: v1.3.0 → v1.3.1 on Dashboard and pyproject.toml.

### Solver: Objective Injection (`base_flowsheet.py` + `lp_builder.py`)
- `BaseFlowsheet.objective_extra: Dict[str, float]` — new dataclass field (default empty).
- `lp_builder.build_lp()` now merges `flowsheet.objective_extra` into the LP objective terms
  before constructing the Pyomo `Objective`. Negative coefficient = maximise.
- Flowsheet reference stored in `session_state["last_flowsheet"]` after each solve for per-unit KPI extraction.

### Data Export (`app_streamlit.py`)
- **3-sheet Excel**: Stream Table (unit/port/variable/value), Unit Performance (per-unit KPIs + capex),
  Optimization Summary (status, iterations, objective, message). Replaced the previous 2-sheet export.

### Documentation (`USER_MANUAL.md`)
- §2.9: Explains the "6 stream links (33 variable equalities)" display.
- §2.10: Objective Function tab guide (4 options, advanced variable override).
- §2.11: Solve benchmarks table (unchanged from Phase 7).

### Tests (`tests/test_v131.py`): 7 new tests — 161 total, 1 pre-existing skip.

---

## What's New in v1.3.0-Phase7 — UI Ergonomics, Solver Tuning & Excel Export

### UI Specification & Ergonomics (`app_streamlit.py` + `flowsheet_service.py`)
- **Dynamic parameter forms**: Custom Flowsheet assembler now renders a pre-filled parameter
  form per unit type (T_gasifier_C, gasifying_agent, eta_isentropic, etc.). Users can edit
  defaults before clicking Build — no more memory-only parameter entry.
- **Smart-select Unit IDs**: Replaced plain `text_input` with a `selectbox` showing
  auto-generated IDs (u1, u2, …) plus a "custom..." fallback for free-form entry.
- **`UNIT_PARAM_SPECS` dict + `ParamSpec` dataclass**: 15 unit types covered with typed,
  labelled, and help-annotated parameter descriptors in `flowsheet_service.py`.
- **`get_unit_param_specs()` public function**: layer-1 accessor used by the UI.
- **Excel download**: "⬇ Download Results (XLSX)" button in Solver Monitor — exports KPIs
  (Sheet 1) and Solution Variables (Sheet 2) via `openpyxl`. Graceful fallback if not installed.

### Solver Convergence & Iteration Limits (`slp.py` + `app_streamlit.py`)
- **Max iterations slider expanded**: 100 → 1000 (sufficient for 10-unit non-linear chains).
- **Progressive tightening** (`SLPConfig.progressive_tightening`): new field (default False).
  When enabled: eps × 100 for first 20% of iterations, eps × 10 for next 40%, standard for
  final 40%. Implemented via `_tighten()` module-level helper.
- **Progressive tightening checkbox** in Solver Monitor UI (below solver mode radio).
- **Advanced solver settings expander**: Trust-Region minimum radius control, editable in UI.
- **Dashboard version corrected**: `v1.2.1` → `v1.3.0` (line 60 of `app_streamlit.py`).

### Infrastructure
- `pyproject.toml`: version bumped to 1.3.0, `openpyxl>=3.1` added to `[gui]` extras.
- `tests/test_phase7_ui.py`: 8 new tests — ParamSpec coverage, dtype validation, progressive
  tightening schedule. Full suite: 154 passed, 1 pre-existing skip.

---

## What's New in v1.3.0-Phase6 — Industrial Categorization & Documentation Consolidation

### Template Library Refactor (`flowsheet_service.py` + `app_streamlit.py`)
- **6-sector categorization** replaces the flat Hydrogen/Industrial/Small split:
  1. Hydrogen Production (3 templates: PEM Electrolysis, PEM+Gasifier MILP, Green Hydrogen Hub)
  2. Biomass Processing (2 templates: Grand Challenge 10-Unit, Biomass→H₂ B-HYPSYS)
  3. Power Generation (1 template: Gasification to Power)
  4. Petrochemicals (2 templates: Power-to-Methanol, Syngas Production)
  5. Carbon Capture & Utilization (1 template: DAC→Methane)
  6. Other Industrial Processes (4 templates: CSTR+Flash, Compression Train, Mixer+Settler, Distillation)
  7. Custom (1 template: Custom Flowsheet — unchanged)
- `app_streamlit.py` category selector updated with `_CAT_ORDER` list for deterministic ordering.

### Documentation Consolidation
- **`UI_GUIDE.md` merged into `USER_MANUAL.md`** and deleted (`git rm`).
  New 4-part structure: Interface Basics | Manual Assembly Workshop | Industrial Template Library | Advanced Showcase.
- **`DEVELOPER_GUIDE.md`** extended with 3 new sections:
  - §12: Registering a new unit in an industrial category (5-step guide)
  - §13: Updating the Shared Component Set for new chemical species (Shomate + Antoine + validation)
  - §14: Trust-Region vs IPOPT solver toggle — decision tree + programmatic examples

---

## What's New in v1.3.0-Phase5 — Aspen-Style Assembly & Validation

### New Unit
- **`CoolerHF`** (`models/heat_exchangers/cooler_hf.py`): Single-stream gas cooler.
  Linear, fixed-T_out, flow-through. Both ports T/P-free for direct chaining to WGS-style units.
  Exact analytical Jacobian (`is_linear = True`). Registered in `AVAILABLE_UNITS` + `UNIT_CATEGORIES`.

### Service Fixes (`flowsheet_service.py`)
- **AVAILABLE_UNITS extended**: `BiomassStorageHF`, `BiomassGasifierHF`, `WGSReactorHF`, `CoolerHF`
  now selectable in the Custom Flowsheet UI dropdown (previously only available via templates).
- **UNIT_CATEGORIES**: new `"Biomass"` and `"Cooling"` categories.
- **`_instantiate_unit()` extended**: 4 new instantiation blocks for the biomass + cooler units.
- **Flow-only fallback** in `build_custom_flowsheet()`: when `fs.connect()` raises `ValueError`
  due to T/P variable-count mismatch, the service now links only the shared `.F_*` component flow
  variables instead of silently logging 0 connections. This prevents the "0 connections" failure
  for chains like WGSReactorHF → SeparatorHF.

### Tests (`tests/test_ui_assembly_logic.py`)
- 18 new tests: CoolerHF unit physics (6), registration checks (5), flow-only fallback (1),
  7-unit chain integration (3). Full suite: 146 pass, 1 conditional skip.

### Documentation
- **USER_MANUAL.md §3.6**: Manual Build Workshop — step-by-step 7-unit chain assembly guide
  with UI input table, connection wiring table, and validation answer key.
- **ARCHITECTURE.md §5.1**: Dynamic port mapping and flow-only fallback — explains
  `_OUTLET_NAMED`, `_INLET_NAMED`, and the flow-only fallback mechanism.
- **THEORY_REFERENCE.md §8**: Mass/energy balance LaTeX math for all 7 workshop chain units.

---

## What's New in v1.2.1 — Investor Showcase Stabilization

### Bugs Fixed
- **`flowsheet_service.py` — "0 Connections" bug:** `except ValueError: pass` silently swallowed
  `PortCompatibilityError` on every custom flowsheet connection. Custom flowsheets now accumulate
  per-connection warnings in `fs._conn_warnings` and surface them as `st.warning()` in the UI.
  Previously the bug was compounded by the UI passing `params={}` to every unit, causing all units
  to use mismatched default component lists. The UI now provides a **Shared Component Set** text
  input; all port-based units in a custom flowsheet use this single species list.
- **`app_streamlit.py` — 4-unit hard cap:** `max_value=4` in `st.number_input` raised
  `StreamlitAPIException` for 5+ unit flowsheets. Changed to `max_value=8`.

### New Features
- **FlashVLHF in custom flowsheet builder:** Added to `AVAILABLE_UNITS`, `UNIT_CATEGORIES`, and
  `_instantiate_unit`. Species that lack Antoine constants are automatically excluded; falls back to
  `["benzene", "toluene"]` if fewer than 2 VLE-capable species remain. FlashVLHF is a terminal unit
  (accepts `inlet_port`, exposes `vapor_port` + `liquid_port`).
- **Biomass→H₂ convergence improvement:** Heuristic bounds tightened from `(0.05×est, 20×est)` to
  `(0.4×est, 4×est)` throughout `_load_biomass_gasification_to_h2`. `wgs.X_CO` constrained to
  `(0.5, 0.95)`. Heuristic estimates now seeded as `fs.initial_x0`; `BaseFlowsheet.initial_guess()`
  injects these values before the midpoint-of-bounds fallback.
- **Composite / super-unit UI:** `build_composite_unit()` helper added to `flowsheet_service.py`.
  Custom flowsheet assembler now has an optional "Add a built-in template as a super-unit" checkbox
  that wraps any registered template as a `CompositeUnit` and appends it to the flowsheet.
- **`docs/SHOWCASE_WALKTHROUGH.md`:** Investor-grade 3-stage demo script with equations,
  talking points, Q&A preparation, and known limitations disclosure.

---

## What's New in v1.2.0 — Industrial Realignment & DAC Integration

### UI Refactor: General-Purpose Process Simulator
- Removed standalone "Case Study: Biomass→H₂" page; Biomass template now in the Template Library
- Template Library grows to 13 templates across 4 categories (Hydrogen / Industrial / Small / Custom)
- DACU template added: TVSAContactor → ElectrolyserHF → MethanationReactor (Power-to-Methane)
- **1D Sensitivity Sweep** UI module: sweep any numeric parameter, live Plotly multi-trace chart
- **Solver Mode Selector**: SLP / NLP / Trust-Region / Adaptive (cascade) in Solver Monitor
- Unit Catalogue now categorised: Feed/Product, Reactors, Separation/DAC, Heat Exchange, Power/CHP

### Advanced Solver Suite (Layer 2)
- `SolveMode.NLP_IPOPT`: scipy L-BFGS-B full-NLP driver with analytical Jacobians from `linearize()`
- `SolveMode.TRUST_REGION`: Filter/Funnel globalisation (Eason & Biegler 2016, Hameed et al. 2021)
- `SolveMode.ADAPTIVE`: SLP → NLP → Trust-Region cascade (auto-escalation on convergence failure)
- Auto-scaling: `compute_scaling_factors()` normalises variable magnitudes for LP and NLP
- SLP infeasibility recovery: warm-start restarts (±5% bound perturbation, up to 3 attempts)
- TRF Filter/Funnel copied from Extra/ to `pse_ecosystem/solvers/trf/`

### New Layer 3 Unit Models (DAC + Power)
| Class | File | `is_linear` | Purpose |
|---|---|---|---|
| `TVSAContactor` | `models/dac/tvsa_contactor.py` | **True** | TVSA DAC; fan + regen + vacuum energy; analytical J |
| `ElectrolyserHF` | `models/dac/electrolyser_hf.py` | **True** | PEM/AEL electrolyser; port-based; analytical J |
| `MethanationReactor` | `models/dac/methanation_reactor.py` | False | Sabatier equilibrium K(T); analytical J |
| `CHPUnit` | `models/power/chp_unit.py` | **True** | Combined Heat & Power; combustion + HRSG; analytical J |

### Port Validation Architecture
- `BaseUnit.validate_connection(port_a, port_b)` — static method, raises `PortCompatibilityError`
- `BaseFlowsheet.connect()` delegates to `validate_connection()` (phase + species checking at build time)
- Prevents physically inconsistent links (e.g. gas CO2 stream into liquid water port)

### Economics Data
- `data/economics.json` — centralised CEPCI (2001–2024), escalation rate, costing defaults
- `economic_engine.py` loads from JSON at import time; falls back to hardcoded dict if absent

---

## What's New in v1.1.0 — SaaS Case Study 01: Biomass → H₂

### Physics Audit: B-HYPSYS Defect Corrections

Audited the client-provided B-HYPSYS code (`Extra/`). **16 defects identified; all corrected** before implementation.

| # | Original Error | Fix Applied |
|---|---|---|
| 1, 2 | Equilibrium constants applied to molar flows ≠ mole fractions | Extent-of-reaction with proper Kp(T) expressions |
| 3 | WGS and gasifier use same temperature variable | Separate T_gasifier and T_wgs parameters per unit |
| 4, 5, 6 | Elemental balances mix normalised (mol/mol biomass) and absolute (mol/s) units | All balances in mol/s; ×1000 g/kg conversion applied |
| 8 | WGS CO conversion and H₂O conversion are independent variables (violates 1:1 stoichiometry) | Single X_CO drives both CO and H₂O depletion |
| 12 | CHP energy balance form violates 1st law | CHP modelled as post-processing KPI only |
| 13 | Drying duty omits latent heat of evaporation | Q_dry includes sensible + h_vap (2257 kJ/kg) + steam superheat |
| 9, 10, 11, 15 | N₂ in LHV/CGE denominators; LHV includes CO₂/H₂O | LHV uses H₂, CO, CH₄ only; N₂ balanced separately |

### New Layer 3 Unit Models

| Class | File | `is_linear` | Purpose |
|---|---|---|---|
| `BiomassStorageHF` | `models/biomass/biomass_storage.py` | True | Drying + preheating; latent heat included |
| `BiomassGasifierHF` | `models/biomass/biomass_gasifier.py` | False | Equilibrium gasifier (6 residuals: element balances + WGS + methanation Kp) |
| `WGSReactorHF` | `models/biomass/wgs_reactor.py` | False | WGS at fixed T; single X_CO enforces 1:1 stoichiometry |
| `H2SeparatorPSA` | `models/biomass/h2_separator.py` | True | PSA H₂ recovery; tail gas tracking |

### Biomass Database (`models/biomass/biomass_database.py`)
8 representative biomasses with dry mass elemental fractions, moisture content, and LHV:
Pine Wood, Miscanthus, Rice Straw, Wheat Straw, Willow, MSW, Sewage Sludge, Sugarcane Bagasse.

### Economic Engine (`models/costing/economic_engine.py`)
- CEPCI historical data: 2001–2024 (source: Chemical Engineering magazine) + projection at 2.5%/yr
- `EconomicEngine` dataclass: `cepci_factor()`, `capital_recovery_factor()` (CRF), `annualized_capex()`, `lcoh()`
- Used by Case Study page for CAPEX escalation and LCOH computation

### Port Validation (`core/contracts.py`, `flowsheets/base_flowsheet.py`)
- `StreamPort` extended with `phase: str = "gas"` and `species: frozenset = frozenset()`
- `PortCompatibilityError(ValueError)` raised by `BaseFlowsheet.connect()` on phase or species mismatch
- Backward-compatible: existing units without declared `phase`/`species` default to unconstrained

### New UI Page — Case Study: Biomass → H₂ (`ui/app_streamlit.py`)
- 5th page added between Flowsheet Builder and GPS Weather
- Inputs: biomass type (8 choices), gasifying agent (Steam/Air), feed rate, steam/biomass ratio, T_gasifier, T_wgs, H₂ recovery, plant life, interest rate, CEPCI year
- Outputs: LCOH [$/kg H₂], CGE [%], H₂ production [kg/h], H₂ vol% in syngas
- LCOH waterfall bar chart, syngas composition pie chart, full KPI table, solution variables

### New Template (`ui/flowsheet_service.py`)
- `biomass.gasification_to_hydrogen` added (12th template, Hydrogen category)
- Port-validated connections: storage → gasifier → WGS → PSA
- Warm-start initial bounds computed from stoichiometric estimates for SLP convergence

### Test Suite (`tests/biomass_audit.py`)
23 unit tests (fast) + 1 end-to-end solve (marked `slow`):
- Database integrity, unit residual correctness, equilibrium calibration, stoichiometry, port validation, template loading, plausibility checks

---

---

## What's New in v0.3.0

### Multi-Page Streamlit UI
- `pse_ecosystem/ui/app_streamlit.py` replaced: single-page stub → full 4-page Streamlit application.
- **Page 1 — Dashboard**: metric cards (templates, solver status, last solve), template gallery, architecture overview.
- **Page 2 — Flowsheet Builder**: category filter, template selector, Mermaid topology diagram (+ Graphviz offline fallback), dynamic parameter form, connection table.
- **Page 3 — GPS Weather**: lat/lon/altitude/timezone inputs → pvlib clearsky solar GHI + synthetic Weibull wind → Plotly time-series charts.
- **Page 4 — Solver Monitor**: Max-iter slider, Mode 1/Mode 2 radio, Run Solve button → convergence plot (dual-axis: objective + residual norm), KPI cards, KPI bar chart, solution variables table.

### Flowsheet Service Bridge
- `pse_ecosystem/ui/flowsheet_service.py` (new): sole Layer-1 module authorised to import from Layer-3 factories. All Layer-3 imports deferred inside loader functions.
- Registry of 9 templates with `TemplateSpec` metadata (key, display_name, category, topology_diagram, unit_labels, default_params, supports_milp).
- Public API: `list_templates()`, `load_template(key, params)`, `load_template_with_choices(key, params)`.

### Three Industrial Flowsheet Templates
| File | Topology | Objective KPI |
|---|---|---|
| `flowsheets/industrial/green_hydrogen.py` | PEMToy → MixerHF (H2 buffer) | LCOH |
| `flowsheets/industrial/power_to_methanol.py` | StoichiometricReactor → SeparatorHF | methanol_yield |
| `flowsheets/industrial/gasification_to_power.py` | StoichiometricReactor (dry reforming) → Compressor | syngas_yield |

### UI Audit
- `tests/ui_audit.py` (new): 15-check standalone audit (no pytest) covering service imports, template solve convergence, layer boundary, and MILP loading.

### Dependency Addition
- `pyproject.toml`: added `plotly>=5.0` to the `gui` optional group.

### Documentation Updates
- `docs/UI_GUIDE.md` (merged v1.0): full page-by-page walkthrough with ASCII mockups, template reference, troubleshooting, developer guide, property overrides, and flowsheet merging How-Tos.
- `docs/USER_MANUAL.md` updated to v0.3.0: Streamlit launch instructions, 4-page UI table, new §2 Pre-Built Industrial Flowsheets with Python API examples, layer architecture updated to document `flowsheet_service.py` boundary rule.
- `README.md` updated: version header, `streamlit run` command in quick-start.

### What's New in v1.0.0

#### Carbon Intensity KPI
- `PEMToyParams.grid_carbon_intensity_kg_CO2_per_kWh` (default 0.233 — UK grid 2023) added; `PEMToy.kpis()` now returns `CI_kg_CO2_per_kg_H2`.
- `GasifierToyParams.biomass_carbon_intensity_kg_CO2_per_kg` (default 0.03 — residual biomass lifecycle) added; `GasifierToy.kpis()` returns same CI key.
- Solver Monitor page highlights CI KPI with EU green hydrogen threshold (1.0 kg CO₂/kg H₂) and red/green delta indicator.

#### Syngas Production Flowsheet
- `flowsheets/industrial/syngas_production.py` — GasifierToy → SeparatorHF (CO₂ scrubber). Converges in 3 iterations. CI KPI available.

#### Enhanced Flowsheet Builder
- Engineering parameters grouped by unit in collapsible expanders.
- **Custom Flowsheet** assembler: pick 1–4 units from allowlist, wire ports, build and solve.
- `flowsheet_service.py`: `AVAILABLE_UNITS` allowlist, `build_custom_flowsheet()`, deferred `_instantiate_unit()`.

#### Packaging Script
- `scripts/package_app.py` — PyInstaller/Nuitka packaging helper with `--check`, `--build`, `--info` modes.

#### Backend Sync Audit
- `tests/ui_backend_sync.py` — 8 math accuracy checks: demand equality, LCOH formula, CI formula, P2M stoichiometry, G2P pressure, G2P extent, Syngas CI, custom flowsheet build.

#### Documentation
- `docs/UI_GUIDE.md` (new) — condensed quick-start, parameter reference, CI guide, custom flowsheet walkthrough, packaging.
- All docs updated to v1.0.0.

---

This file is the **source of truth** for future Claude sessions.
Update it whenever the system state changes.

---

## What's New in v0.2.0

### Interface Changes
- `StreamPort` dataclass added to `core/contracts.py` — name-generator for stream variables
- `BaseFlowsheet.connect(port_a, port_b)` added — generates `Connection` objects from ports
- `BaseUnit` gains `capex()`, `opex_per_year()`, `control_hooks()`, `get_linearization()` — all with safe default implementations (no existing units break)
- Wegstein state reset bug fixed in `slp.py` — `SLPDriver.run()` now resets tear-stream state at the top of every call

### New Modules
- `models/properties/ideal_gas.py` — NIST Shomate Cp/H for H2, O2, N2, CO, CO2, CH4, H2O
- `models/properties/vle.py` — Antoine K-values + Rachford-Rice solver + bubble/dew T
- `models/costing/sslw_costing.py` — pure-Python SSLW purchase cost correlations (no Pyomo)

### 16 New HF Unit Models

| Class | Module | is_linear | Jacobian |
|---|---|---|---|
| `StoichiometricReactor` | reactors/stoichiometric_reactor.py | True | Analytical |
| `CSTRHF` | reactors/cstr_hf.py | False | Mixed (mat. analytical, energy FD) |
| `PFRHF` | reactors/pfr_hf.py | False | FD (ODE inner) |
| `EquilibriumReactor` | reactors/equilibrium_reactor.py | False | FD (Newton inner) |
| `GibbsReactor` | reactors/gibbs_reactor.py | False | FD (SLSQP inner) |
| `FlashVLHF` | separators/flash_vl_hf.py | False | FD |
| `FlashSL` | separators/flash_sl.py | False | FD |
| `DistillationHF` | separators/distillation_hf.py | False | FD |
| `SeparatorHF` | separators/separator_hf.py | True | Analytical |
| `MixerHF` | mixers/mixer_hf.py | False | FD |
| `HeatExchangerNTU` | heat_exchangers/heat_exchanger_ntu.py | False | FD |
| `ShellTubeHX` | heat_exchangers/shell_tube.py | False | FD |
| `HeatExchanger1D` | heat_exchangers/heat_exchanger_1d.py | False | FD |
| `Valve` | pressure_changers/valve.py | False | FD |
| `Pump` | pressure_changers/pump.py | False | FD |
| `Compressor` | pressure_changers/compressor.py | False | FD |

### Physics Corrections vs. IDAES Source
| Unit | IDAES Problem | v0.2 Fix |
|---|---|---|
| CSTR | Bilinear rate, no Arrhenius | `k0*exp(-Ea/RT)*V*ΠC_i^α` |
| Flash V/L | Constant K-values | Antoine K(T,P) + Rachford-Rice |
| Distillation | No Underwood root-finding | Multicomponent Underwood + Molokanov |
| Compressor | Pyomo property package | Explicit isentropic equations |
| HX LMTD | Smooth singularity approx | L'Hopital limit at ΔT1≈ΔT2 |
| SSLW Costing | Pyomo Var/Constraint wrappers | Pure Python float functions |

### Small Flowsheets Library

| File | Topology |
|---|---|
| `flowsheets/small/adiabatic_cstr_flash.py` | Feed → CSTR HF → Flash V/L HF |
| `flowsheets/small/compression_train.py` | Feed → Compressor → Shell&Tube HX → Valve |
| `flowsheets/small/mixer_settler.py` | [Feed1, Feed2] → Mixer HF → Separator HF |
| `flowsheets/small/distillation_column.py` | Feed → Distillation HF |

### Layer Boundary
- Forbidden import list in `test_slp_convergence.py` and `system_audit.py` extended to cover all 7 new model subdirectories (reactors, separators, heat_exchangers, pressure_changers, mixers, costing, properties).
- All HF unit models use only `core/contracts.py` and `models/properties/` imports — no Pyomo anywhere.

---

## Complete Package Structure (v1.2.1)

```
pse_ecosystem/
├── core/
│   ├── contracts.py     PrimalGuess, LinearizedModel, UnitResponse, StreamPort, SolveResult
│   └── registry.py
├── data/
│   └── weather.py       SiteData, fetch_solar_profile, fetch_wind_profile, WeatherDrivenFlowsheet
├── flowsheets/
│   ├── base_flowsheet.py    BaseFlowsheet (with connect()), CompositeUnit
│   ├── hydrogen/
│   │   └── electrolysis_grid.py
│   ├── industrial/
│   │   ├── green_hydrogen.py        PEMToy → MixerHF (LCOH + CI KPIs)
│   │   ├── power_to_methanol.py     StoichRxr → SeparatorHF (linear, 1-iter)
│   │   ├── gasification_to_power.py StoichRxr (dry reforming) → Compressor
│   │   └── syngas_production.py     ← NEW v1.0: GasifierToy → SeparatorHF (CO2 scrub, CI KPI)
│   └── small/
│       ├── adiabatic_cstr_flash.py
│       ├── compression_train.py
│       ├── mixer_settler.py
│       └── distillation_column.py
├── models/
│   ├── base_unit.py         BaseUnit (with capex, opex_per_year, control_hooks, get_linearization)
│   ├── properties/
│   │   ├── ideal_gas.py     Shomate Cp/H (7 species)
│   │   └── vle.py           Antoine K-values, Rachford-Rice, bubble/dew T
│   ├── costing/
│   │   └── sslw_costing.py  HX, vessel, compressor, pump, turbine, annualized CAPEX
│   ├── reactors/
│   │   ├── stoichiometric_reactor.py
│   │   ├── cstr_hf.py       (ReactionConfig dataclass)
│   │   ├── pfr_hf.py
│   │   ├── equilibrium_reactor.py
│   │   └── gibbs_reactor.py
│   ├── separators/
│   │   ├── flash_vl_hf.py
│   │   ├── flash_sl.py
│   │   ├── distillation_hf.py
│   │   └── separator_hf.py
│   ├── mixers/
│   │   └── mixer_hf.py
│   ├── heat_exchangers/
│   │   ├── heat_exchanger_ntu.py
│   │   ├── shell_tube.py
│   │   └── heat_exchanger_1d.py
│   ├── pressure_changers/
│   │   ├── valve.py
│   │   ├── pump.py
│   │   └── compressor.py
│   ├── _blackbox/       HDA black-box wrappers (hda_reactor_bb, hda_flash_bb, hda_distillation_bb)
│   ├── electrolysis/    pem_toy.py
│   ├── gasification/    gasifier_toy.py
│   ├── mixer/           ideal_mixer.py
│   ├── heat_exchanger/  heat_exchanger_toy.py, boiler_toy.py
│   ├── reactor/         cstr_toy.py, hda_pfr.py
│   ├── separator/       flash_toy.py, hda_flash.py
│   └── distillation/    hda_column.py
├── solvers/
│   ├── slp.py               SLPDriver, SLPConfig, TearStreamConfig
│   ├── lp_builder.py
│   ├── milp_builder.py
│   ├── nlp_builder.py       ← NEW v1.2.0: scipy L-BFGS-B full-NLP driver
│   ├── trust_region_driver.py ← NEW v1.2.0: filter/funnel Trust-Region driver
│   ├── scaling.py           ← NEW v1.2.0: auto-scaling factors
│   ├── ipopt_driver.py
│   ├── orchestrator.py
│   └── trf/                 ← NEW v1.2.0: Trust-Region Filter/Funnel modules
│       ├── filter.py
│       ├── funnel.py
│       └── util.py
├── themes/
│   └── hydrogen.py
└── ui/
    ├── entry.py
    ├── __main__.py
    ├── flowsheet_service.py  ← NEW v0.3.0 — sole Layer-1 bridge to Layer-3 factories
    └── app_streamlit.py      ← REPLACED v0.3.0 — full 4-page multi-page Streamlit app
```

---

## Test Suite (v1.2.1)

| File | Tests | Coverage |
|---|---|---|
| `tests/ui_backend_sync.py` | 8 (standalone) | ← NEW v1.0.0: math accuracy (demand, LCOH, CI, stoich, pressure, extent, custom) |
| `tests/ui_audit.py` | 15 (standalone) | Service imports, template convergence (11 templates), layer boundary, MILP |
| `tests/system_audit.py` | 17 (standalone) | Handshake, SLP, Hydrogen theme, KPI sanity, layer boundary |
| `tests/industrial_audit.py` | 11 (standalone) | Feed→CSTR→Flash→Sep: physics closure, costing, layer boundary |
| `tests/test_base_unit.py` | 4 pytest | BaseUnit Jacobian, bounds, FD correctness |
| `tests/test_slp_convergence.py` | 4 pytest | E2E convergence, layer boundary (9 forbidden patterns) |
| `tests/flowsheet_optimization_test.py` | 9 pytest | Unit library, weather, CompositeUnit, HDA |
| `tests/test_interface_evolution.py` | 13 pytest | StreamPort, connect(), capex/opex, get_linearization |
| `tests/test_properties.py` | 22 pytest | Shomate Cp/H (vs NIST), VLE K-values, Rachford-Rice |
| `tests/test_hf_units.py` | 38 pytest | All 16 HF units: residual shape, mass balance, capex |
| `tests/test_costing.py` | 17 pytest | SSLW correlations, CEPCI escalation, Pyomo-free check |

**v1.2.1 additions:**

| File | Tests | Coverage |
|---|---|---|
| `tests/test_v121.py` | ~12 pytest | FlashVLHF (VLE residual, pressure equality, custom-builder context), CompositeUnit (industrial sub-flowsheet assembly) |
| `tests/presentation_validation.py` | standalone | 3-unit chain (StoichRxr → CSTRHF → FlashVLHF): port connectivity, convergence, V_frac in expected range |

**Total: ~119 pytest + 8 backend-sync + 15 UI audit + 17 system audit + 11 industrial audit = ~170 checks**

Run all:
```powershell
python tests/ui_backend_sync.py
python tests/ui_audit.py
python tests/system_audit.py
python tests/industrial_audit.py
python tests/presentation_validation.py
pytest tests/ -v
```

---

## Handshake Protocol (unchanged from v0.1)

```
Layer 2 → Layer 3:  PrimalGuess(values, iteration, metadata)
Layer 3 → Layer 2:  LinearizedModel(unit_id, variables, x0, f0, J, bounds,
                                    objective_terms, is_exact, trust_region,
                                    kpi_gradients)
Layer 3 → Layer 2:  UnitResponse(unit_id, outputs, kpis, residual, feasible)
```

**Layer boundary rule:** `solvers/` must never import from `models/`.
Enforced by `test_solvers_do_not_import_concrete_unit_modules`.

---

## Known Limitations (v1.2.1)

| Item | Detail |
|---|---|
| VLE model | Raoult's Law (ideal VLE). NRTL/Wilson activity coefficients deferred to v0.4. |
| VLE species naming | ANTOINE dict uses `"methanol"` / `"water"` (not `"CH3OH"` / `"H2O"`). GibbsReactor `_ELEMENT_COMP` uses `"H2O"`. Never mix the two in the same flash unit. |
| `small.cstr_flash` UI template | CSTR+Flash does not converge from midpoint initial guess in the UI (returns INFEASIBLE). Loads correctly; underlying physics is valid — see `industrial_audit.py`. |
| PFR/Gibbs scipy dependency | Requires `pip install pse_ecosystem[blackbox]`. |
| DistillationHF last residual | 4th constraint is a placeholder (0=0). Column is uniquely determined by the first 3 FUG + energy residuals. |
| HX1D uses analytical NTU | The N finite-element discretisation resolves to the same result as the NTU formula. Internal profiles are not exposed. |
| Recycle convergence | Wegstein acceleration untested on real process recycles. |
| Weather | Solar clearsky only. Wind is synthetic Weibull. No windrose integration yet. |
| Ideal gas limit | All HF energy balances use ideal gas enthalpies. No departure function for liquid-phase heat of mixing. |
| LP with no cost objective | Reaction extents default to zero (lower bound) unless pinned via `extra_equalities`. All industrial templates include explicit extent equalities. |

---

## v0.1.0 Unit Models (still available)

| Class | Module | Type |
|---|---|---|
| `PEMToy` | models/electrolysis/pem_toy.py | Electrolyser (linear) |
| `GasifierToy` | models/gasification/gasifier_toy.py | Gasifier (non-linear) |
| `IdealMixer` | models/mixer/ideal_mixer.py | Mixer (linear) |
| `BoilerToy` | models/heat_exchanger/boiler_toy.py | Boiler (linear) |
| `HeatExchangerToy` | models/heat_exchanger/heat_exchanger_toy.py | HX LMTD (FD) |
| `CSTRToy` | models/reactor/cstr_toy.py | CSTR toy (analytical J) |
| `FlashToy` | models/separator/flash_toy.py | Flash constant-K (FD) |
| `HDAPFRUnit` | models/reactor/hda_pfr.py | HDA PFR ODE (FD) |
| `HDAFlashUnit` | models/separator/hda_flash.py | HDA Flash VLE (FD) |
| `HDADistillationUnit` | models/distillation/hda_column.py | HDA FUG (FD) |

---

---

## Documentation Index (v1.2.1)

| File | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Load-bearing architectural blueprint: 3-layer split, Handshake Protocol, solver suite (SLP/NLP/TRF/Adaptive), layer boundary enforcement |
| `docs/UI_GUIDE.md` | Full UI reference (v1.2.1): quick-start, page walkthrough, template catalogue, 1D Sensitivity Sweep, composite super-unit, solver mode selector |
| `docs/USER_MANUAL.md` | Installation, Streamlit launch, pre-built templates API, `fs.connect()` patterns, unit catalogue, SLP/NLP/TRF config |
| `docs/DEVELOPER_GUIDE.md` | Adding units, flowsheets, CompositeUnit, testing patterns, forbidden import rules |
| `docs/THEORY_REFERENCE.md` | Physics: VLE, Rachford-Rice, SLP theory, Trust-Region Filter/Funnel globalisation |
| `docs/SHOWCASE_WALKTHROUGH.md` | **Investor showcase script:** 3-stage demo (Engine Works / Real-World Scale / Decision Tool), Q&A prep, key equations |
| `docs/TUTORIAL_WALKTHROUGH.md` | Step-by-step tutorial: Case A (3-unit SLP proof), Case B (DACU sensitivity), Solver Guide |
| `docs/SYSTEM_STATE.md` | This file — source of truth for system state |

---

*Source of truth for PSE Ecosystem v1.0.0. Update this file after every significant change.*
