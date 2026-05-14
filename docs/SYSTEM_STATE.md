# PSE Ecosystem — System State Ledger

**Version:** 1.2.1
**Date:** 2026-05-14
**Status:** v1.2.1 "Showcase-Ready" — connections bug fixed, FlashVLHF in custom builder, Biomass convergence stabilised

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
