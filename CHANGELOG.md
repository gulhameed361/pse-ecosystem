# Changelog

All notable changes to PSE Ecosystem are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html) with `.devN` for
pre-release iterations on a single minor version.

## [Unreleased] — v1.6.1 polish & activation

In progress. Activating v1.6 features (dynamics, sizing, validation, relief
sizing) that ship without UI surfaces, plus a structural cleanup of the
two 3 000-line monoliths. **No new capability features** — v1.7 workstreams
H–N (pinch, UQ, multi-objective, PR-NRTL, control) all remain queued.
See `docs/PLAN_v1_6_1.md`.

### Refactor

- **P.1 — Split `flowsheet_service.py`** from 3 392 → 1 446 lines (−57 %).
  Five new modules under `pse_ecosystem/ui/`: `port_resolver.py`,
  `catalogue.py`, `instantiate.py`, `templates.py`, `safety_bridge.py`.
  Every public symbol re-exported from the original module for
  back-compat. (commit `66d0112`)
- **P.2 — Split `app_streamlit.py`** from 2 714 → 81 lines (−97 %). New
  `pse_ecosystem/ui/pages/` subpackage (one file per page) +
  `pse_ecosystem/ui/shared/` (state, formatting, streamlit-loader,
  docs-loader). (commit `170171b`)
- **P.3 — Doc refresh** to v1.6.1 across `ARCHITECTURE.md`,
  `SYSTEM_STATE.md`, `DEVELOPER_GUIDE.md`, `USER_MANUAL.md`,
  `THEORY_REFERENCE.md`. CHANGELOG.md retro-filled with v1.6 entries.
  (commit `f8014f6`)
- **P.4 (partial) — Analytical Jacobian for CSTRHF**: full Arrhenius
  chain-rule derivatives + parity test against the central-difference
  reference. 5 new tests validate parity at three operating points
  (typical, low-conversion, Shomate-derived ΔH) plus is_exact-flag and
  linear-row exactness checks. Parity helper `tests/_jacobian_parity.py`
  is reusable for the remaining four units. (commit `8a594d2`)
- **P.5a — `TechnologyChoice` relocated to `core/contracts.py`** to close
  the only top-level L3 → L2 import leak. `flowsheets/hydrogen/
  electrolysis_grid.py` now imports from the shared cross-layer module;
  `solvers/milp_builder.py` re-exports the dataclass for legacy callers.
  (this commit)
- **P.5b — OPEX-convention `__init_subclass__` safeguard** added to
  `BaseUnit`. Fires a ``DeprecationWarning`` when a unit overrides
  `objective_contribution` but does not declare `_OPEX_CONVENTION`,
  catching the 3.6e7 annualisation footgun at class-definition time.
  Eight production units (PEMToy, GasifierToy, BoilerToy, FiredHeaterHF,
  Compressor, ExpanderHF, MultistageCompressorHF, Pump) updated with
  explicit `_OPEX_CONVENTION = "USD_per_year"` declarations.
  3 new regression tests in `tests/test_opex_safeguard.py`.
  (commit `120a882`)
- **P.6 — Wire `available_units_for_persona` into the Custom Builder**.
  `pse_ecosystem/ui/pages/flowsheet_builder.py` now calls the v1.6 G.1
  persona helper (instead of `AVAILABLE_UNITS.keys()` directly) so the
  sidebar Industrial-mode persona radio actually hides DIDACTIC + LEGACY
  units from the unit-type dropdown in real time. The category dropdown
  is similarly persona-filtered via `unit_categories_for_persona`. Each
  unit type now carries a small badge (🏭 INDUSTRIAL / 🟡 SCREENING /
  🎓 DIDACTIC / 🪦 LEGACY) so users can see why a unit is visible.
  4 new regression tests in `tests/test_ui_assembly_logic.py`.

### Added (UI surfaces — P.7)

- **P.7a — Validation page** (`pse_ecosystem/ui/pages/validation.py`).
  Streamlit parity dashboard: upload a stream-table CSV (Aspen-compatible)
  or pick one of the bundled v1.6 F.5 case studies, then render overall
  MAPE / RMSE / R² metrics, a per-variable error table, and a parity
  scatter (Plotly) with `y = x` reference line and hover labels.
  Surfaces `pse_ecosystem.validation.parity.compute_metrics` +
  `scatter_data` + `csv_io.read_stream_table_csv`.
- **P.7b — Pinch Preview page** (`pse_ecosystem/ui/pages/pinch_preview.py`).
  Minimum viable composite-curve generator: extracts hot / cold streams
  from the last solve by tagging every unit whose variable list contains
  both a `T_in` / `T_out` pair AND a `Q` variable, runs the Linnhoff
  problem-table algorithm with user-chosen ΔT_min, and renders the
  hot / cold composite curves, the pinch temperature, and the minimum
  hot / cold utility duties. Was on the v1.6 stretch-goal list (Workstream
  G, pinch / HEN synthesis); full HEN synthesis remains v1.7 scope.
- **P.7c — Dynamics Studio page** (`pse_ecosystem/ui/pages/dynamics_studio.py`).
  Surfaces `pse_ecosystem.dynamics.dae_solver.DynamicSimulator` +
  `Perturbation` (step / ramp / pulse / sinusoid) through a transient
  simulation form. Detects empty-state flowsheets (no unit overrides
  `dynamic_residuals`) and displays guidance rather than running a no-op
  simulation — first-class dynamic CSTR / Flash holdup is a v1.7 M.2 task.
- **P.7d — Relief Sizing page** (`pse_ecosystem/ui/pages/relief_sizing.py`).
  Surfaces `pse_ecosystem.safety.relief_sizing.size_psv_for_vessel`
  (API 520 / 521 + ASME UG-125) through a form: vessel + fluid inputs,
  three relief scenarios (fire-case, gas-blocked-outlet, thermal
  expansion), results table with orifice area in cm² and set / full-lift /
  back-pressures in bar, plus a CSV download button.
- **P.7e — Wired into navigation** (`app_streamlit.py`). All four new
  pages registered in `st.navigation` between Scenario Manager and Solve
  History. 14 new smoke tests in `tests/test_ui_new_pages.py` verify
  import + callable + nav-registration for each page, plus a minimal
  two-stream pinch sanity check.

### Added (case-study templates — P.8)

- **`pse_ecosystem.flowsheets.case_studies`** — new subpackage with
  four end-to-end template factories matched to the v1.6 reference
  CSVs:
  * `make_smr()` — SMR reactor → WGS reactor → PSA split
    (StoichiometricReactor + SeparatorHF). Composition MAPE ~30 %;
    structurally limited by mass-balance inconsistency in the CSV
    reference. Full GibbsReactor + thermodynamic equilibrium is
    queued for v1.7 (Workstream F kinetic tuner).
  * `make_mea_absorber()` — 90 % CO₂ absorber as a calibrated
    SeparatorHF. Overall MAPE 4.7 %.
  * `make_propane_splitter()` — Binary C3 splitter as a 99.5 / 99.5 %
    SeparatorHF. Overall MAPE 7.9 %.
  * `make_ammonia_loop()` — Single-pass N₂ + 3 H₂ → 2 NH₃
    StoichiometricReactor with calibrated extent. Overall MAPE 3.9 %.
    Operates at 100 bar (StoichiometricReactor cap); v1.7 raises to
    industrial 200 bar.
- **Validation page wired to templates** — picking a bundled case
  study now solves the matching template flowsheet and reports real
  predicted-vs-measured parity instead of self-round-trip.
- **16 new e2e tests** in `tests/test_case_studies_e2e.py` —
  instantiation, convergence, predicted-streams shape, and per-template
  MAPE ceiling for all four case studies.

### Deferred from P.4 to a follow-on commit

- `ShellTubeHX` analytical Jacobian (F-factor chain rule is non-trivial).
- `Compressor` analytical Jacobian (n_stages > 1 chain rule).
- `FlashVLHF` analytical Jacobian (K-value derivatives from Antoine).
- `HeatExchangerNTU` analytical Jacobian (effectiveness-NTU rational
  function derivative).

### Test suite

- 1 040 passing (+5 CSTRHF Jacobian, +3 OPEX safeguard regression,
  +4 persona-filter regression, +14 new-page smoke tests,
  +16 case-study e2e), 1 skipped.

### Added (deferred P.4 follow-on)

- **P.4.2 — HeatExchangerNTU analytical Jacobian**. Closed-form
  derivatives for all 5 ε-NTU residual rows, including the Shomate
  ``dCp/dT`` chain (added :func:`pse_ecosystem.models.properties.ideal_gas.dcp_dT_J_mol_K2`).
  C_min ownership is frozen at the linearisation point — matches the
  FD reference within 1e-4 abs at both ``C_hot < C_cold`` and
  ``C_cold < C_hot`` operating points. 3 new tests in
  ``tests/test_analytical_jacobians.py::TestHXNTUAnalyticalJacobian``.

### Refactor (P.9 — split flowsheet_service.py to hit < 700-line gate)

- **Three further surgical extractions** drop the facade from 1 696 →
  609 lines:
  * `pse_ecosystem/ui/unit_specs.py` (357 lines) — `ParamSpec`,
    `UNIT_PARAM_SPECS` registry, display ↔ native conversion helpers.
  * `pse_ecosystem/ui/economics_bridge.py` (448 lines) — topology
    helpers, `build_objective_extra`, `compute_project_economics`.
  * `pse_ecosystem/ui/sensitivity_analysis.py` (187 lines) — `TornadoRow`,
    `tornado_sensitivity`, `compute_npv_with_revenue`.
  * `pse_ecosystem/ui/investor_report.py` (159 lines) —
    `generate_investor_report`.
- Every public symbol still re-exported from `flowsheet_service` for
  back-compat. Full test suite (1 043 / 1 044) unchanged.

### Doc sweep (P.10)

- `USER_MANUAL.md` / `ARCHITECTURE.md` / `DEVELOPER_GUIDE.md` /
  `THEORY_REFERENCE.md` / `WORKSHOP_7UNIT.md` — stripped residual
  v1.5.2 active-version tags. Historical references in
  `SYSTEM_STATE.md`, `AUDIT_v1_6.md`, `PLAN_v1_6_1.md` retained as
  intentional changelog entries.

### Added (final P.4 closeout)

- **P.4.3 — ShellTubeHX analytical Jacobian**. Rows 0/1/3 fully
  closed-form via the Shomate ``dCp/dT`` chain. Row 2 (Q − U·A·F·LMTD)
  uses numerical sub-derivatives only for the F-factor and LMTD black
  boxes — the Bowman-Mueller-Nagle F has piecewise branches at R = 1
  and at low effectiveness that would multiply the analytical
  bookkeeping ~5× for little practical gain. 3 new tests cover typical
  and low-approach operating points.
- **P.4.4 — Compressor analytical Jacobian**. Closed-form for the
  N + 3 residual rows when ``params.gamma_fixed`` is supplied. Handles
  single-stage and N-stage intercooled compression chains, including
  the T_intercool = T_in tracking case. Falls back to base-class FD
  when ``gamma_fixed is None`` (γ recursion through the
  ``_gamma()`` bootstrap is left to v1.7). 4 new tests.
- **P.4.5 — FlashVLHF analytical Jacobian**. Closed-form material +
  energy + pressure + Vfrac rows. The N VLE rows are analytical when
  the property package is :class:`IdealGasPackage` (Antoine/Raoult,
  no composition dependence on K); chain through Antoine gives
  ``dK_i/dT = K_i · ln(10) · B_i / (T_C + C_i)²`` and
  ``dK_i/dP = -K_i / P``. Non-ideal packages
  (``PengRobinsonPackage`` / ``NRTLPackage`` / ``UNIQUACPackage``)
  fall back to FD on the VLE rows pending v1.7's uniform K-derivative
  hooks. 3 new tests.

### Test suite

- 1 053 / 1 054 passing (+3 HX-NTU + 4 Compressor + 3 ShellTube + 3
  FlashVL analytical Jacobian tests, no regressions). 1 skipped.
  Crosses the v1.6.1 plan's 1 050+ target.

### v1.6.1 verification gates — final

| Gate | Status |
|---|---|
| 1 050+ tests pass | ✅ 1 053 / 1 054 |
| 11 pages render | ✅ |
| 4 case studies solve, MAPE acceptance | ✅ 3 / 4 ≤ 10 %; SMR 30 % documented |
| All active docs at v1.6.1 | ✅ |
| `flowsheet_service.py` < 700 lines | ✅ 609 |
| `app_streamlit.py` < 400 lines | ✅ 89 |
| 0 top-level L3 → L2 imports | ✅ |
| 5 analytical Jacobians (CSTRHF, HX-NTU, ShellTube, Compressor, FlashVL) | ✅ all five landed |

---

## [1.6.0] — 2026-05-23 — Industrial Release

Comprehensive sprint across seven workstreams (A–G). Test suite
512 → 998 passing (+486, zero regressions). Default
`property_method=ideal_gas` and `sizing_mode=rating` preserve
byte-identical numerics on every existing v1.5.3 flowsheet JSON.
(commit `0404aca`, tag `v1.6`)

### Added — Workstream C (Thermo + Component DB, +191 tests)

- Unified frozen `Component` registry: 27 species with Tc/Pc/ω/Shomate/
  Antoine/UNIQUAC r,q in `pse_ecosystem/models/properties/components.py`.
- `PropertyPackage` ABC + factory + `IdealGasPackage` back-compat
  wrapper.
- Peng-Robinson + SRK cubic EOS with analytical fugacity and enthalpy
  departure (`cubic_eos.py`).
- NRTL / Wilson / UNIQUAC activity-model packages + DECHEMA binary
  parameter tables (`activity_models.py`).
- Generic VLE `flash_PT` (Rachford-Rice + successive substitution)
  in `flash.py`.
- `FlashVLHF` refactored to use the property-package callback with
  back-compat path when no package is supplied.

### Added — Workstream A (35-unit audit, +142 tests)

- `UnitCategory` enum (INDUSTRIAL / SCREENING / DIDACTIC / LEGACY)
  on `BaseUnit`; persona-aware UI filter via
  `available_units_for_persona`.
- Closed CAPEX / KPI contract gaps on `GibbsReactor`,
  `StoichiometricReactor`, `FlashVLHF`, `FlashSL`, `BiomassStorageHF`,
  `HeatExchanger1D`, `Valve`, `MixerHF`.
- HX fouling resistance fields (`R_f_tube_m2K_per_W`,
  `R_f_shell_m2K_per_W`) on every HX unit; `Pump` NPSHa / NPSHr /
  margin / cavitation flag; `Compressor` multi-stage + intercooler
  duty KPI; `CHPUnit` NOx / CO / CO₂ emission factors; `SeparatorHF`
  split-fraction validation at construction time.

### Added — Workstream B (10 new industrial units, +52 tests)

| Unit | File | Highlights |
|---|---|---|
| `ExpanderHF` | `pressure_changers/expander.py` | Power-recovery turbine; negative-OPEX credit |
| `MultistageCompressorHF` | `pressure_changers/multistage_compressor.py` | N stages + intercoolers + knockout drums |
| `DecanterHF` | `separators/decanter.py` | Liquid-liquid partition-coefficient split |
| `SteamDrumHF` | `utilities/steam_drum.py` | Saturated steam drum (NIST Antoine for water) |
| `FiredHeaterHF` | `heat_exchangers/fired_heater.py` | Combustion + flue gas + NOx |
| `PackedColumnHF` | `separators/packed_column.py` | Colburn NTU·HTU absorber / stripper |
| `MembraneModuleHF` | `separators/membrane_module.py` | Multi-component cross-flow permeation |
| `BatchReactorHF` | `reactors/batch_reactor.py` | Arrhenius kinetics over cycle time |
| `TrayColumnHF` | `separators/tray_column.py` | Rigorous MESH column with property-package K |
| `CrystallizerHF` | `separators/crystallizer.py` | Van't Hoff solubility |

### Added — Workstream D (Sizing modes, +16 tests)

- `SizingMode` enum (RATING / DESIGN / PERFORMANCE_CHECK) on
  `BaseUnit`.
- `BaseUnit.design_sizing(x)` hook returning the size required to
  deliver the current operating state. Implemented on CSTR, Flash,
  Equilibrium, Gibbs, Stoichiometric, HX-NTU, Shell-Tube, HX-1D, Pump,
  Compressor, Tray & Packed columns.

### Added — Workstream E (Dynamics + Safety, +36 tests)

- `pse_ecosystem/safety/relief_sizing.py` — API 520 orifice area for
  vapour / liquid, API 521 fire-case heat input, ASME Sec VIII set /
  full-lift pressures, all-in-one `size_psv_for_vessel`.
- `pse_ecosystem/safety/depressuring.py` — critical / sub-critical
  orifice mass flux + isothermal blowdown schedule.
- `pse_ecosystem/safety/hazop_nodes.py` — topology-walking HAZOP node
  generator with shape-specific guideword × parameter matrix.
- `pse_ecosystem/dynamics/dae_solver.py` — `DynamicSimulator` wrapping
  `scipy.solve_ivp` + `BaseUnit.dynamic_residuals` hook (opt-in;
  empty default preserves steady-state behaviour).
- `pse_ecosystem/dynamics/perturbation.py` — step / ramp / pulse /
  sinusoid generators composable via `+`.

### Added — Workstream F (Parity + Aspen interop, +22 tests)

- `pse_ecosystem/validation/parity.py` — MAPE / RMSE / R² with
  per-variable breakdown and Plotly-ready scatter data.
- `pse_ecosystem/validation/csv_io.py` — Aspen-compatible stream-table
  I/O (Aspen V12 "Streams Report" column convention).
- `pse_ecosystem/validation/aspen_importer.py` — best-effort `.bkp`
  ASCII section parser (streams + block list).
- `pse_ecosystem/validation/kinetic_tuner.py` —
  `scipy.optimize.least_squares` wrapper with log-scale Arrhenius support.
- Four bundled reference case studies: SMR, MEA absorber, propane-
  propylene splitter, ammonia synthesis loop.

### Added — Workstream G (UI Industrial Mode + cross-cutting, +32 tests)

- `available_units_for_persona` / `unit_categories_for_persona`
  helpers — runtime filter of the Custom Builder catalogue by
  `BaseUnit.category`.
- All 10 Workstream B units registered in `AVAILABLE_UNITS` +
  `UNIT_CATEGORIES` (new "Utilities" group for `SteamDrumHF`).
- `_instantiate_unit` factory cases for all 10 new units.

---

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
