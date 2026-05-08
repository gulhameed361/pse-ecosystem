# PSE Ecosystem — System State

**Version:** 0.1.0  
**Date:** 2026-05-08  
**Status:** v0.1.0 stable — all tests passing

This file is the **source of truth** for future Claude sessions. It describes
every implemented feature, unit model, solver mode, and known limitation
exactly as they exist in the codebase right now. Update this file whenever
the system state changes.

---

## Package Structure

```
pse_ecosystem/
├── core/           contracts.py, registry.py
├── data/           weather.py (solar + wind profiles)
├── flowsheets/     base_flowsheet.py (BaseFlowsheet, CompositeUnit)
│   └── hydrogen/   electrolysis_grid.py
├── models/
│   ├── _blackbox/  hda_reactor_bb, hda_flash_bb, hda_distillation_bb
│   ├── electrolysis/  pem_toy.py
│   ├── gasification/  gasifier_toy.py
│   ├── mixer/         ideal_mixer.py
│   ├── heat_exchanger/ heat_exchanger_toy.py, boiler_toy.py
│   ├── reactor/        cstr_toy.py, hda_pfr.py
│   ├── separator/      flash_toy.py, hda_flash.py
│   └── distillation/   hda_column.py
├── solvers/        slp.py, lp_builder.py, milp_builder.py, orchestrator.py
├── themes/         hydrogen.py
└── ui/             entry.py, __main__.py, app_streamlit.py
```

---

## Implemented Unit Models

| Class | File | Type | n\_vars | n\_residuals | Jacobian | is\_linear |
|---|---|---|---|---|---|---|
| `PEMToy` | models/electrolysis/pem\_toy.py | Electrolyser | 2 | 1 | Analytical | True |
| `GasifierToy` | models/gasification/gasifier\_toy.py | Gasifier | 3 | 2 | Analytical | False |
| `IdealMixer` | models/mixer/ideal\_mixer.py | Mixer | n\_inlets×n\_comp + n\_comp | n\_comp | Analytical | True |
| `BoilerToy` | models/heat\_exchanger/boiler\_toy.py | Boiler | 3 | 2 | Analytical | True |
| `HeatExchangerToy` | models/heat\_exchanger/heat\_exchanger\_toy.py | HX (LMTD) | 5 | 3 | FD | False |
| `CSTRToy` | models/reactor/cstr\_toy.py | CSTR | 4 | 2 | Analytical | False |
| `FlashToy` | models/separator/flash\_toy.py | Flash (const K) | 6 | 4 | FD | False |
| `HDAPFRUnit` | models/reactor/hda\_pfr.py | HDA PFR (ODE) | 13 | 7 | FD (ODE) | False |
| `HDAFlashUnit` | models/separator/hda\_flash.py | HDA Flash (VLE) | 19 | 12 | FD (VLE) | False |
| `HDADistillationUnit` | models/distillation/hda\_column.py | HDA Column (FUG) | 10 | 5 | FD (FUG) | False |

### Unit Physics Summary

**PEMToy:** `h2 = eta * electricity`. `eta = 0.018 kg/kWh`. LCOH [£/kg].

**GasifierToy:** `h2 = a*feed - b*feed²` (non-linear yield). `a=0.10, b=1e-7`. LCOH [£/kg].

**IdealMixer:** `F_out_c = Σ_j F_in_j_c` per component. Parametric (n_inlets, components).

**BoilerToy:** `Q = eta * LHV * F_fuel`, `Q = F_steam * h_steam`. `eta=0.85, LHV=50 MJ/kg`.

**HeatExchangerToy:** `Q = m_hot*Cp_hot*(T_hi - T_ho) = m_cold*Cp_cold*(T_co - T_ci) = U*A*LMTD`. FD Jacobian (LMTD partials are complex; analytical TODO).

**CSTRToy:** `F_A_in - F_A_out - k*V*(F_A_out/F_total_nom) = 0`, `F_B_out = k*V*(F_A_out/F_total_nom)`. Analytical Jacobian.

**FlashToy:** Constant K-value (Raoult toy). 4 residuals: total/component balance, K-value, Rachford-Rice. FD Jacobian.

**HDAPFRUnit (BB wrapper):** Adiabatic PFR, 2 reactions (Toluene→Benzene, 2Benzene→Diphenyl), Arrhenius kinetics. A1=5.987e4, A2=3.160e4 mol/(m³·s·atm²). Corrected from erroneous A2=3.160e9. ODE integration via scipy.solve_ivp (LSODA).

**HDAFlashUnit (BB wrapper):** Wilson K-values (T,P-dependent), Rachford-Rice solved via scipy.brentq. 5 components: H2/CH4/Tol/Benz/Diph.

**HDADistillationUnit (BB wrapper):** FUG shortcut — Fenske (N_min), Underwood (RR_min), Gilliland/Molokanov (N_actual). Two-column benzene/toluene train.

---

## Flowsheet Infrastructure

### BaseFlowsheet
`dataclass(name, units, connections, objective_kpi, extra_bounds, extra_equalities, recycle_streams)`

- `Connection(var_a, var_b)` — equality `var_a == var_b`
- `extra_equalities` — linear constraints `Σ a_i x_i == b`
- `recycle_streams` — metadata only (variable names in recycle loops; solver ignores this field)
- `initial_guess()` — midpoint of bounds

**Important:** When `extra_equalities` pin variables to values far from the midpoint of bounds (e.g., fixing F=10 when bounds are [0, 1e6]), the LP will be infeasible at the default initial guess. Always pass an explicit `x0` to `SLPDriver.run()` in these cases.

### CompositeUnit
Wraps a `BaseFlowsheet` as a single `BaseUnit`. Exposes selected variables as inputs/outputs to a parent flowsheet. Inner flowsheet solved via `SLPDriver` on each `residual()` call. FD Jacobian (each FD step = one full inner SLP solve — expensive). Lives in `flowsheets/base_flowsheet.py`.

---

## Layer 2 Solvers

### SLPDriver (`solvers/slp.py`)
Iterative SLP loop. Key features:
- Linear short-circuit: if all units `is_exact=True`, returns after 1 LP solve
- Trust region: optional, disabled by default (`use_trust_region=False`)
- Wegstein acceleration: `TearStreamConfig` in `SLPConfig.tear_streams` for recycle loops
- Convergence: `‖x_{k+1}-x_k‖∞ < eps_x` AND `‖f(x)‖∞ < eps_f` AND `|Δkpi| < eps_kpi`

### TearStreamConfig (`solvers/slp.py`)
Wegstein-accelerated recycle tear streams. Declare one per recycle connection. `q ∈ [q_min, q_max]` Wegstein factor adapted per iteration. `q=0` = direct substitution. Harmless if used on non-recycle variables.

### Orchestrator (`solvers/orchestrator.py`)
- Mode 1 (FIXED_LP): delegates to SLPDriver
- Mode 2 (FLEXIBLE_MILP): linearise → MILP → if non-linear selected → SLP refinement

### LP/MILP Builders
- `lp_builder.py`: Pyomo ConcreteModel from LinearizedModel list + BaseFlowsheet
- `milp_builder.py`: binary technology selection with big-M coupling

---

## Solver Modes

| Mode | API | Description |
|---|---|---|
| `SolveMode.FIXED_LP` | `Orchestrator(mode=SolveMode.FIXED_LP)` | Fixed topology. LP (linear) or SLP (non-linear). |
| `SolveMode.FLEXIBLE_MILP` | `Orchestrator(mode=SolveMode.FLEXIBLE_MILP, technology_choices=[...])` | Binary technology selection, then SLP refinement. |

---

## Themes and Applications

| Theme | Application | Flowsheet Factory | Mode |
|---|---|---|---|
| `hydrogen` | `electrolysis_only` | `make_electrolysis_only(h2_demand_kg_per_h)` | 1 |
| `hydrogen` | `electrolysis_or_gasification` | `make_electrolysis_or_gasification(h2_demand_kg_per_h)` | 2 |

---

## Data Layer (`pse_ecosystem/data/`)

| Function | Requires | Description |
|---|---|---|
| `fetch_solar_profile(site, year)` | pvlib | Hourly GHI [W/m²] via Ineichen clearsky |
| `fetch_wind_profile(site, year)` | numpy only | Synthetic Weibull wind speed [m/s] |
| `generate_demand_profile(peak, n_hours)` | numpy only | Flat or seasonal H2 demand |
| `electricity_price_from_solar(ghi)` | numpy only | Price [£/kWh] decreasing with GHI |
| `WeatherDrivenFlowsheet` | numpy | Container linking flowsheet to weather time-series |

`SiteData(latitude, longitude, altitude, timezone, name)` — site descriptor.

---

## Handshake Protocol (unchanged from v0)

```
Layer 2 → Layer 3:  PrimalGuess(values, iteration, metadata)
Layer 3 → Layer 2:  LinearizedModel(unit_id, variables, x0, f0, J, bounds,
                                    objective_terms, is_exact, trust_region,
                                    kpi_gradients)
Layer 3 → Layer 2:  UnitResponse(unit_id, outputs, kpis, residual, feasible,
                                 diagnostics)
```

**Layer boundary rule:** `pse_ecosystem/solvers/` must never import from `pse_ecosystem/models/`. Enforced by `test_solvers_do_not_import_concrete_unit_modules`.

`CompositeUnit` (in `flowsheets/`) is the only sanctioned cross-layer call — Layer 3 calling Layer 2 for hierarchical decomposition. This uses a deferred import inside `residual()`.

---

## Standalone App

- `python -m pse_ecosystem [--theme] [--application] [--mode] [--demand]` — CLI
- `streamlit run pse_ecosystem/ui/app_streamlit.py` — Streamlit stub (requires `pip install pse_ecosystem[gui]`)

---

## Optional Dependencies

| Extra | Packages | Purpose |
|---|---|---|
| `[solvers]` | highspy | HiGHS LP/MILP solver |
| `[weather]` | pvlib, pandas | Solar irradiance profiles |
| `[gui]` | streamlit | Streamlit front-end |
| `[blackbox]` | scipy | HDA black-box unit wrappers (ODE, VLE) |
| `[all]` | all above | Full installation |

---

## Test Suite

| File | Tests | Coverage |
|---|---|---|
| `tests/system_audit.py` | 17 checks (standalone) | Handshake, SLP loop, Hydrogen theme, KPI sanity |
| `tests/test_base_unit.py` | 4 pytest | BaseUnit Jacobian, bounds, FD correctness |
| `tests/test_slp_convergence.py` | 4 pytest | E2E convergence, layer boundary enforcement |
| `tests/flowsheet_optimization_test.py` | 9 pytest (7+2 skip) | New unit library, weather, CompositeUnit, HDA reactor |

Run all: `python tests/system_audit.py && pytest tests/ -v`

---

## Known Limitations

| Item | Detail |
|---|---|
| Midpoint initial guess | `BaseFlowsheet.initial_guess()` uses midpoints of bounds. If `extra_equalities` pin variables far from midpoints, the LP will be infeasible. Always pass an explicit `x0` to `SLPDriver.run()`. |
| FD Jacobian cost for BB wrappers | Each SLP iteration requires 2×n+1 BB evaluations for FD. For HDAPFRUnit (n=13), that is 27 ODE integrations per SLP step. Accept for demo use. |
| CompositeUnit FD cost | Each FD step of the outer SLP requires a complete inner SLP solve. Use only for prototyping. |
| FlashToy constant K | `K_A_ref` is temperature/pressure-independent. Sufficient for conceptual design; not rigorous. |
| HeatExchangerToy LMTD Jacobian | Computed via FD (not analytical). The analytical form exists but is complex. TODO for performance. |
| Recycle convergence | Wegstein acceleration is implemented but untested on a real recycle flowsheet. The HDA case study (`examples/hda_case_study.py`) uses a simplified version. |
| Weather profiles | Solar uses Ineichen clearsky (no cloud cover). Wind is synthetic Weibull (not from ERA5 or reanalysis data). |
| pvlib/scipy not in core deps | `pip install pse_ecosystem[weather]` for solar, `pse_ecosystem[blackbox]` for HDA units. |

---

## Deferred / Not Implemented

| Item | Reason |
|---|---|
| PSA model (`PSA_real_simulation_EM.py`) | PDE-based, requires pyAPEP (not on PyPI). Needs surrogate fitting. |
| B-HYPSYS models | 68-constraint monolith; needs full decomposition into unit objects. |
| SGN seasonal model | Broken code (truncated constraint definitions). Needs full rewrite. |
| Analytical LMTD Jacobian | Complex chain-rule. FD is correct for v1. |
| Time-series parallel execution | 8760 hourly SLP solves are sequential. Parallelism via multiprocessing is future work. |
| OA/Benders for MILP | Sequential MILP→SLP decomposition is the current approach. |
| Full Streamlit deployment | Stub only — no secrets management, no multi-user support. |
| Surrogate/ANN unit models | Future Layer 3 extension. |
