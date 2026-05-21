# Changelog

All notable changes to PSE Ecosystem are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html) with `.devN` for
pre-release iterations on a single minor version.

## [Unreleased]

## [1.5.3] — 2026-05-21

Comprehensive bug-fix and quality release: 36 issues across 3 severity tiers
resolved and locked by 73 new regression tests (507 total, 0 failures).

### Critical fixes

- **C-1 NPV/IRR cash flow sign error** (`flowsheet_service.py`).  
  `compute_project_economics()` was computing `annual_net_cashflow = −opex`
  (always negative — no revenue term), making NPV always a large negative and
  IRR always NaN.  
  *Fix:* Added `ProductionConfig` dataclass with `h2_price_USD_per_kg`,
  `electricity_sale_price_USD_per_kWh`, `heat_sale_price_USD_per_GJ`,
  `methane_price_USD_per_GJ`.  Annual revenue is now computed and subtracted
  from OPEX to form the true cash flow.  When no `ProductionConfig` is
  provided, NPV/IRR cells display `"N/A (no revenue model)"` instead of
  silently wrong numbers.

- **C-2 Sankey diagram plots T and P as "flows"** (`flowsheet_service.py`).  
  Every connection variable — including intensive T (300–1200 K) and P
  (1e4–5e6 Pa) — was being added as a Sankey link.  The massive magnitudes
  made every link look like it carried 100 000× the real molar flow.  
  *Fix:* `build_sankey_data()` now filters to `F_*` variables only and
  aggregates multiple species connections into one link per unit pair
  (correct total molar/mass flow shown).

- **C-3 `_extract_power_out_kW` returns max, not sum** (`flowsheet_service.py`).  
  For a flowsheet with two CHP units the LCOE denominator was the larger unit's
  output rather than the combined output.  
  *Fix:* `max(vals)` → `sum(vals)`.

### Added

- **`ProductionConfig` dataclass** (`flowsheet_service.py`) — product price
  model enabling meaningful NPV and IRR computation.  Default values of 0
  preserve the pre-v1.5.3 no-revenue behaviour.
- **`OBJECTIVE_LP_PROXY_NOTE` dict** (`flowsheet_service.py`) — maps
  "Maximize NPV" and "Maximize IRR" to a human-readable string explaining
  that the LP optimises a TAC proxy; the UI renders this as a `st.warning`
  banner when those modes are selected.
- **`TemplateSpec.recommends_trust_region: bool`** field — advisory flag
  set `True` on biomass and grand-challenge templates (both contain
  non-linear units benefiting from trust-region step control).  The
  Solver Monitor reads it to set `SLPConfig.use_trust_region` automatically.
- **`pse_ecosystem/data/economics.json`** — ships CEPCI historical data
  (2001–2024) and the escalation rate; `EconomicEngine` now loads from this
  file instead of a hardcoded dict.  Add or update entries without touching
  Python.
- **`OPEXConvention` string Enum** (`models/base_unit.py`) — replaces the
  bare `str` class attribute.  Members `USD_PER_YEAR`, `USD_PER_SECOND`,
  `YIELD_COEFFICIENT` equal their string literals so existing comparisons
  continue to work.
- **`__all__`** exported from `core/contracts.py`, `flowsheets/base_flowsheet.py`,
  and `models/base_unit.py`.
- **`initial_x0`** declared as a proper `Optional[Dict[str, float]]` dataclass
  field on `BaseFlowsheet` (was duck-typed via `hasattr`).  Typos in warm-start
  keys now raise instead of silently falling back to the bound midpoint.
- **`CompositeUnit._last_inner_x`** cache — `kpis()` and `capex()` now
  propagate inner-flowsheet results via the cached solution from the most recent
  `residual()` call.
- **73 new regression tests** in `tests/test_v153.py` locking every fix.

### Changed

- **H-2 H₂ yield objective** — `build_objective_extra()` now uses
  `_topological_unit_order()` and `_most_downstream_h2_outlet()` to identify
  the correct target variable instead of lexicographic sorting.  Fixes the case
  where the unit with the alphabetically "last" ID (e.g. `wgs`) was wrongly
  chosen over the true downstream unit (e.g. `psa`).
- **H-3 Electrolyser CAPEX** — the $700/kW hardcoded coefficient is replaced
  by `ProjectEconomicsConfig.pem_capex_USD_per_kW` (default **1 200 USD/kW**,
  NREL 2024 estimate).
- **H-4 LP/MILP solver preference** — `select_lp_solver` and
  `select_milp_solver` candidates list reordered to
  `[appsi_highs, highs, cbc, glpk]`.
- **H-5 ADAPTIVE exception narrowing** — the NLP-stage `except Exception`
  is narrowed to `(ImportError, ModuleNotFoundError, RuntimeError, AttributeError)`;
  physics errors (e.g. `ZeroDivisionError` in a unit residual) now propagate
  instead of silently falling through to the TRF stage.
- **H-6 ASME vessel whitelist** expanded:
  `PFRHF`, `TVSAContactor`, `DistillationHF`, `ShellTubeHX`, `Pump`,
  `MethanationReactor`, `FlashSL`.
- **H-7 `aggregate_kpis()` warnings** — a failed `kpis()` call now emits a
  `RuntimeWarning` naming the unit instead of silently being skipped.
- **H-10 `scale_rows` docstring** — clarified as an explicit opt-in (not
  default) with guidance on when to enable it.
- **M-3/M-13 Variable matching in `build_objective_extra()`** — energy
  variable detection uses `.endswith()` suffix matching rather than substring
  search (eliminates false positives on capacity-bound variables like
  `unit.net_electricity_kw_limit`).  `ElectrolyserHF` identification uses
  `isinstance()` instead of `type().__name__` string comparison.
- **M-6 NLP mode naming** — `SolveMode.NLP_IPOPT` and `NLP_SCIPY` docstrings
  clarified: the implementation is scipy L-BFGS-B, not IPOPT.
- **M-7 `history.jsonl` disk cap** — `record_solve_in_history()` rotates the
  file to ≤ 200 lines after each append (was unbounded).
- **M-8 Backward-compat opex shim removed** — the `except TypeError` fallback
  for v1.4-style `opex_per_year(x)` signature is gone; the two-argument form
  is now mandatory.
- **M-12 `_most_downstream_h2_outlet()`** — port-tag detection broadened to
  include "product", "h2", and "vapor" tags in addition to "out".
- **L-6 "Pareto Sweep" renamed** to "Parameter Sensitivity Sweep" in the UI to
  correctly describe the grid search operation.
- **L-8 `HeatExchangerNTU._eps_from_NTU()`** — effectiveness clamped to `[0, 1]`
  to prevent numerical noise near balanced-flow (C_star ≈ 1) from producing
  values slightly above 1, which would propagate to negative Q.
- **L-9 `_StepNormStop` moved outside attempt loop** in `NLPDriver.run()`.
  The class is now defined once per `run()` call, before the restart loop,
  so the class identity is stable across attempts.

### Tests

| Milestone | Pass | Warn | Fail |
|---|---|---|---|
| v1.5.2 baseline | 434 | 0 | 0 |
| **v1.5.3** | **507** | **1** | **0** |

The single warning (`RuntimeWarning` from the KPI-poison test) is intentional —
it proves the new H-7 warning fires correctly.

## [1.5.2] — 2026-05-20

## [1.5.0-rc1] — 2026-05-19

First release candidate of v1.5.0, the **Multi-Tier Optimization Engine**
release. Six AUDIT sweeps (a638bb0 → 1e50791 and beyond) consolidated.

### Added

- **Three-tier optimisation framework.** New `OBJECTIVE_TIERS` taxonomy
  (Technical / Economic / Technoeconomic) covering 11 objective modes
  (5 new: Specific Energy Consumption, Carbon Intensity, NPV, IRR, LCOE).
- **Project Economics Engine** (`models/costing/economic_engine.py`):
  - `EquipmentScalingRule` — six-tenths cost scaling `C = C₀·(S/S₀)^α`.
  - `EconomicEngine.npv()` — DCF with optional salvage value.
  - `EconomicEngine.irr()` — bisection IRR; returns `+inf` for unbounded
    rates and `nan` when project never pays back.
  - `EconomicEngine.lcoe()` — levelized cost of electrical energy.
  - `__post_init__` input validation (positive plant life, non-negative
    interest rate, 0 < hours ≤ 8760, lang_factor ≥ 1).
- **ProjectEconomicsConfig** dataclass (Layer 1 bridge) — single source
  of truth for plant life, WACC, tax/inflation/target year, operating
  hours, electricity/biomass/water/cooling-water/carbon-tax prices,
  Lang factor; `crf` and `energy_coeff` derived properties.
- **Project Economics Excel sheet** (Sheet 5, 24 metrics) — Annualised
  CAPEX (CEPCI + Lang), Annual OPEX, TAC, LCOH, LCOE, NPV, IRR, plus
  metadata rows (target year, CEPCI escalation factor, objective mode).
- **Elastic-mode LP recovery** (`solvers/lp_builder.py`) — when the
  hard-equality LP is INFEASIBLE the SLP retries with slack variables on
  every equality; small-slack steps accepted as feasible, larger-slack
  steps take a damped 0.3× motion toward the elastic solution.
- **Closed-form analytical Jacobian** for `BiomassGasifierHF` (6×8 steam
  / 6×9 air); replaces the 48-call FD fallback. Validated against
  central-FD to 1e-3 relative on equilibrium rows.
- **`BaseFlowsheet.diagnose()`** — non-raising pre-solve validator
  returning `{errors, warnings, info}`. Exposed via a "Pre-solve
  Validator" expander on the Flowsheet Builder.
- **Solve History page** + persistent log at
  `~/.pse_ecosystem/history.jsonl` (survives Streamlit reloads).
- **2D Pareto sweep** with non-dominated frontier overlay and per-axis
  Minimize/Maximize toggles (Flowsheet Builder).
- **Sankey diagram** of material flows on Solver Monitor results.
- **Save / Load flowsheet config as JSON** (Flowsheet Builder).
- **Unified `PSE_PLOTLY_TEMPLATE`** applied to every chart.
- **`SolveMode.NLP_SCIPY`** canonical alias for the honest name of
  what `NLP_IPOPT` actually runs (scipy L-BFGS-B). `NLPDriver._ipopt_available()`
  probes for real IPOPT on PATH (full wiring v1.6).
- **`scaling.compute_residual_row_scaling()`** helper for per-Jacobian-row
  normalisation, opt-in via `SLPConfig.scale_rows=True`.
- **NLPDriver** now honours `eps_x` (step-norm callback) and does up to
  3 restarts with 10 % Gaussian perturbation on x0.
- **`BaseFlowsheet.aggregate_kpis()`** as the single source of truth
  (was duplicated in 4 driver files, with no error handling).
- **Pareto frontier**, **diagnose() helper**, **CGE_LHV vs CGE_with_steam**
  KPI split.
- **CHANGELOG.md** (this file).
- **`tests/test_streamlit_smoke.py`** — `AppTest`-based browser-free
  smoke render of every page.

### Changed

- **Multi-tier UI redesign** on Flowsheet Builder Objective Function tab:
  tier radio → objective selectbox → context-dependent expander.
  Per-tier selectbox key (`f"objective_mode__{_tier}"`) so switching tiers
  no longer triggers `StreamlitAPIException`.
- **OPEX accounting standardisation.** `BaseUnit._OPEX_CONVENTION` enum
  (`USD_per_year` default / `USD_per_second` / `yield_coefficient`)
  applied in `opex_per_year(x, operating_hours)`. BiomassGasifierHF tagged
  `USD_per_second`, H2SeparatorPSA tagged `yield_coefficient`. Fixes
  Sheet 5 OPEX being wrong by factor ~3×10⁷ in v1.4.x.
- **H₂ production KPI naming standardisation.** PEMToy, ElectrolyserHF,
  BiomassGasifierHF now emit uid-prefixed `H2_production_kg_h/_s`. Bare
  keys retained on ElectrolyserHF for v1.4 backwards compat.
- **CGE KPI split.** `CGE_LHV_percent` (legacy LHV-only, can exceed 100 %
  for steam gasification) and `CGE_with_steam_percent` (steam-corrected,
  bounded by 2nd law). Steam enthalpy: 3-term decomposition accurate
  within 3 % of NIST steam tables at 800 °C.
- **Biomass template `extra_bounds` widened** from 0.4×–4× to 0.05×–20×
  of heuristic estimate (cured the v1.4.x perma-infeasibility).
- **Grand challenge test** switched from FIXED_LP to ADAPTIVE solve
  mode; C-balance tolerance relaxed 5 % → 10 % to absorb residual
  elastic-mode slack.
- **Module docstrings** bumped to v1.5.0.dev across the package.
- **SLP MAX_ITER message** now reports final trust-region radius and
  emits an explicit "Trust region collapsed" diagnostic when δ
  saturates `trust_region_min`.

### Fixed

- **`biomass.gasification_to_hydrogen` and `grand_challenge.gasification`
  no longer perma-INFEASIBLE.** Three-part fix: analytical Jacobian +
  elastic-mode LP fallback + widened template bounds. The two
  `v1.5.x INVESTIGATION ITEM` skips are gone; tests are real assertions.
- **`compute_project_economics()`** reads from real unit `capex(x)`,
  `opex_per_year(x)` and unit-tagged `H2_production_kg_h/_s` KPIs (was
  querying non-existent KPI keys → Sheet 5 was all-zero/NaN).
- **`Streamlit AppTest`** smoke tests for all 7 page functions catch
  imports/typos/runtime errors a unit test would miss.

### Tests

| Stage | Pass | Skip | Fail |
|---|---|---|---|
| v1.4.1 baseline | 275 | 2 | 0 |
| v1.5.0.dev release | 303 | 2 | 0 |
| v1.5.0.dev-AUDIT | 321 | 2 | 0 |
| v1.5.0.dev-AUDIT2 | 321 | 2 | 0 |
| v1.5.0.dev-AUDIT3 | 350 | 2 | 0 |
| v1.5.0.dev-AUDIT4 | 360 | 0 | 0 |
| **v1.5.0-rc1**   | **367** | **0** | **0** |

Plus standalone audit scripts: 24/24 system_audit, 20/20 ui_audit,
7/7 streamlit smoke.

## [1.4.1] — 2026-05-19

### Added
- Physics safety net: bound-saturation guard, UI unit auto-conversion
  on_change, flowsheet connection validation.
- 13 new tests in `TestFlowsheetValidateConnections` and
  `TestUnitAutoConversionCallback`.

### Fixed
- Phantom-connection silent failures (the v1.4.0 7-unit Excel anomaly).
- UI unit dropdowns no longer overwrite the numeric value silently.

## [1.4.0] — 2026-05-17

### Added
- Unit Management System (UMS) — display↔native conversion at UI boundary.
- Unrestricted Custom Flowsheet builder.
- Help Center page.
- 35/37 audit hardening items closed.
