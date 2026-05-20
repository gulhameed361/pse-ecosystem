# PSE Ecosystem (v1.5.2)

**Industrial-grade process simulation with transparent, auditable physics.**  
*Private — University of Surrey.*

---

## Who uses PSE Ecosystem?

| User | What they do with it |
|---|---|
| **Research academic** | Build novel flowsheets fast, inspect exact Jacobians and residuals, run 2D Pareto sweeps, validate against literature |
| **Process engineer** | Screen technologies, optimise operating points, generate engineering safety margins (ASME, LFL/UFL) |
| **Project developer / VC** | Compare Base / Optimistic / Pessimistic scenarios, run tornado sensitivity, compute break-even H₂ price, download an investor-grade report |
| **Regulatory analyst** | Audit every equation — all physics are explicit algebraic residuals with analytical Jacobians; no black-box solver |

### Why not Aspen?

| Capability | PSE Ecosystem | Aspen Plus |
|---|---|---|
| Auditable physics | Every equation visible as Python residuals | Compiled black-box |
| Integrated technoeconomics | NPV / IRR / LCOH / LCOE in the same tool | Requires separate Aspen Process Economic Analyzer |
| Analytical Jacobians | Yes — enables transparent sensitivity analysis | Finite-difference approximations |
| Scenario comparison | Built-in Scenario Manager (4 scenarios, delta table) | Manual Excel |
| Investor report | One-click Markdown/PDF download | Manual reporting |
| Python extensible | Add a unit model in 50 lines of Python | Requires Aspen user models (Fortran/COM) |
| ASME / flammability | Post-solve safety margins built in | Manual calculation |
| Monte Carlo | Fast enough for stochastic sweeps (seconds/solve) | Minutes per solve |
| Cost | Private — University research tool | £50k+/yr commercial licence |

---

## What's new in v1.5.2 — Dual-Persona Stabilisation + Scenario Analysis Enhancement

- **Pandas 2.0 Styler fixed.** `df.style.applymap()` → `df.style.map()` in the Industrial
  ASME safety table; resolves `AttributeError` on Pandas ≥ 2.0.
- **Plotly keyword collision fixed.** Scenario Manager dual-bar chart now strips colliding
  template keys (`yaxis`, `barmode`) before `update_layout()` unpack; resolves `TypeError`.
- **Zero-fill port padder.** Custom Flowsheet Builder no longer skips connections between
  ports with different component counts. Unmatched inlet species are zero-filled; a
  non-fatal warning is displayed. Enables exploration of topologically incomplete chains.
- **Exact equality count confirmed: 33.** The 7-unit workshop chain produces exactly 33
  port-variable equalities in both Academic and Industrial personas (corrects stale 31
  in prior docs). Locked by new regression test.
- **Custom flowsheet crash fixed.** `BaseFlowsheet` object no longer serialised directly;
  `custom_flowsheet_cfg` session-state key holds the JSON-safe spec dict.
- **Scenario Manager & Analysis.** Renamed page gains a new **Sensitivity Analysis**
  section for economic and engineering sweeps.
- **434 tests, 20/20 UI audit checks** — all green.

## What's new in v1.5.1 — Industrial Decision Support

- **Scenario Manager** (new nav page 📋). Capture up to 4 named solve results and compare them
  side-by-side: Installed CAPEX, OPEX, TAC, LCOH, LCOE, NPV, IRR — with % delta vs Base, a Plotly bar
  chart, and Excel export.
- **Tornado Chart.** One-at-a-time sensitivity of LCOH/NPV/TAC to 8 economic parameters (±20 %),
  rendered as a horizontal Plotly chart in the Industrial view.  Instantly answers "what kills the deal?"
- **Break-even Calculator.** Enter an expected H₂ market price; get NPV with revenue, margin USD/kg,
  and payback period.  The break-even price equals the LCOH — confirmed analytically.
- **Investor Report.** One-click Markdown download with 6 sections: process description, KPIs, project
  economics, ASME safety table, tornado sensitivity, and fully-explicit assumptions list.
- **ASME Material Selector.** Dropdown for 6 shell materials (carbon steel → Hastelloy C-276), each
  with ASME allowable stress; propagates to wall-thickness calculation.
- **Carbon Intensity Benchmark.** Compare computed CI (kg CO₂/kg H₂) against SMR, blue H₂, grid
  electrolysis, and the green H₂ target.
- **Equipment Datasheet** (Excel Sheet 6). Per-unit: T/P bounds, CapEx, ASME minimum wall thickness.
- **Solve time** displayed in convergence banner ("Solved in X.X s").
- **30 new tests** in `test_v151.py`. 431 pytest total; 482 total checks.

## What's new in v1.5.0 — Industrial Readiness

- **Dual-Persona UI.** Sidebar toggle switches between **Academic** view (Jacobian
  condition numbers, KPI sensitivity derivatives `∂KPI/∂var`, residual history) and
  **Industrial** view (CapEx/OpEx grouped bar chart per unit, ASME vessel sizing,
  flammability margin table).  Same physics, same solver, same converged solution —
  only the analysis panels change.
- **ASME + Flammability Safety Framework.**  New pure-Python module
  `pse_ecosystem/models/safety/safety_checks.py` implements ASME VIII Div.1
  UG-27(c)(1) wall thickness and Le Chatelier mixture LFL/UFL.  Post-solve only —
  never enters the LP/NLP objective or constraint set.
- **Persona persistence.** Flowsheet JSON configs now carry `user_persona`; old
  configs without the field default to "Academic".
- **34 new tests** (`tests/test_industrial_readiness.py`): ASME formula, Le Chatelier,
  persona toggle, safety bridge, and non-intrusiveness verification (AST-level).

## What's new in v1.5.0.dev

- **Multi-Tier Optimization Engine.** Three objective tiers — Technical (Energy, Carbon Intensity, H₂ Yield, Specific Energy), Economic (OPEX, TAC, NPV, IRR), Technoeconomic (LCOH, LCOE) — selected via context-dependent UI cards that show only the financial parameters relevant to the chosen tier.
- **Project Economics Engine.** Full NPV (with optional salvage), bisection IRR (returns `+inf` for unbounded rates), LCOE/LCOH, six-tenths equipment cost scaling, CEPCI escalation to the user's target year, Lang factor for installed-cost conversion.
- **Elastic-mode LP recovery.** When the hard-equality LP returns INFEASIBLE the SLP retries with slack variables on every equality; small-slack steps are accepted as feasible, larger-slack steps trigger a damped 0.3× motion toward the elastic solution. **Resolves** the v1.4.x "infeasible at minimum trust-region radius" failure mode that previously affected industrial flowsheets.
- **Pre-solve Validator.** `BaseFlowsheet.diagnose()` (and a UI surface on the Flowsheet Builder) reports errors / warnings / metrics before you Run Solve.
- **Project Economics & Cash Flow Excel sheet.** Annualised CAPEX (CEPCI + Lang), Annual OPEX, TAC, LCOH, LCOE, NPV, IRR, with full unit annotation and ERROR-row diagnostic when computation fails.
- **2D Pareto sweep + non-dominated frontier overlay** (Flowsheet Builder); axis-direction toggles invert per-axis.
- **Sankey diagram** of material flows on Solver Monitor results.
- **Solve History page** + persistent log at `~/.pse_ecosystem/history.jsonl` that survives Streamlit reloads.
- **Save / Load flowsheet config as JSON** for reproducibility.
- **Unified Plotly theme** applied to every chart across the app.

## Why PSE Ecosystem?

- **Explainable physics.** Every unit model ships its exact algebraic residuals and analytical Jacobian. Regulators, auditors, and partners can inspect every equation — no black-box solver.
- **Analytical Jacobians throughout.** v1.5.0.dev adds a closed-form 6×8 Jacobian for `BiomassGasifierHF` (was FD); the SLP loop now converges on the gasifier + WGS + PSA chain in 8 iterations.
- **3-layer separation.** UI / Solver / Knowledge are strictly decoupled via the Handshake Protocol. Swap the solver without touching the physics; swap the UI without touching the solver.
- **Standardised OPEX accounting.** Every unit declares an explicit `_OPEX_CONVENTION` (`USD_per_year` / `USD_per_second` / `yield_coefficient`); `BaseUnit.opex_per_year(x, operating_hours)` handles the conversion. Fixes the v1.4.x mixed-units defect that made Excel Sheet 5 OPEX wrong by a factor of ~3×10⁷.
- **Unrestricted Assembly Freedom (v1.4.0).** Aspen-style Custom Flowsheet builder — no hard cap on unit count. 3-column specification grid with pre-filled engineering defaults; smart Unit ID dropdown re-seeds on Type change. **23 UI-selectable unit types** drawn from a 36-class Layer-3 catalogue.
- **Unit Management System (v1.4.0).** Every float parameter with a convertible dimension (T, P, mass flow, mass, power, energy) shows a unit dropdown next to its value. Backend stays in SI; UI converts at the boundary. Excel export tags every numeric column with its SI unit.
- **Analytical Verification.** Every unit exposes exact Jacobians; the 7-unit and 10-unit workshop chains validated by the automated test suite (**431 pytest + 24 system audit + 20 UI audit + 7 Streamlit smoke = 482 total checks**; 0 skipped, 0 failures).
- **Live Help Center (v1.4.0).** A 6th nav page renders the workspace `docs/` markdown directly in the app.
- **Excel Export.** Download a **5-sheet ledger** (Stream Table / Unit Performance / Optimization Summary / Bound Saturation / Project Economics & Cash Flow) to `.xlsx` from the Solver Monitor.
- **Progressive Solver Tightening (default ON in v1.4.0).** SLP starts with loose tolerances (≈1e-3) and tightens to precision (≈1e-7) as iterations progress. Max Iterations slider extended to **1500**.

---

## Architecture

Three strictly separated layers:

| Layer | Location | Responsibility |
|---|---|---|
| **1 — UI** | `pse_ecosystem/ui/` | 6-page Streamlit app (Dashboard, Flowsheet Builder, Site Weather, Solver Monitor, Solve History, Help Center); `flowsheet_service.py` is the sole bridge to Layer 3 |
| **2 — Solver** | `pse_ecosystem/solvers/` | SLP / NLP / Trust-Region drivers; adaptive cascade orchestration |
| **3 — Knowledge** | `pse_ecosystem/models/` + `flowsheets/` | Unit models supplying residuals + analytical Jacobians via the Handshake Protocol |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full blueprint, Handshake Protocol, and hybrid-connection logic.

---

## Quick Start

The venv must live **outside OneDrive** to avoid sync churn over thousands of DLLs.

### Windows (PowerShell)

```powershell
# One-time: create venv outside OneDrive
python -m venv $HOME\.venvs\pse_ecosystem

# Activate (every new shell)
& $HOME\.venvs\pse_ecosystem\Scripts\Activate.ps1

# Install package + all extras
pip install -e ".[dev,solvers,gui,weather]"

# Run tests
pytest tests\ -q                       # 367 pytest cases pass (0 skipped)
python tests\system_audit.py           # 24/24 system audit (incl. v1.5 checks)
python tests\ui_audit.py               # 20/20 UI audit (incl. v1.5 checks)

# Launch the Streamlit UI
streamlit run pse_ecosystem/ui/app_streamlit.py
```

### macOS / Linux

```bash
python -m venv ~/.venvs/pse_ecosystem
source ~/.venvs/pse_ecosystem/bin/activate
pip install -e ".[dev,solvers,gui,weather]"
pytest
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Opens at **http://localhost:8501**.

---

## UI Overview

Five pages:

| Page | What it does |
|---|---|
| **Dashboard** | Solver status, template gallery (14 templates), last solve result |
| **Flowsheet Builder** | Category filter → template → Mermaid topology → parameter form → **Apply & Select**. 1D Sensitivity Sweep. Objective Function tab (Feasibility / OPEX / Energy / TAC / LCOH / H₂ Yield). Custom flowsheet assembler (**any number of units** in v1.4.0, shared component set, composite super-unit option, 3-column specification grid). |
| **GPS Weather** | pvlib clearsky solar GHI + Weibull wind profiles for any lat/lon/year |
| **Solver Monitor** | Active-objective mirror at the top. Solver mode selector (SLP / NLP / Trust-Region / Adaptive) → **Run Solve** → live convergence chart → KPI cards + solution table → 3-sheet Excel export. Iteration slider 1–1500; progressive tightening default ON. |
| **Help Center** | Live-loaded `docs/` markdown — User Manual, 7-Unit Workshop, Theory Reference, Architecture, Developer Guide. |

---

## Flowsheet Templates (v1.3.0 — 14 templates across 6 industrial sectors)

| Sector | Key | Name | Solver |
|---|---|---|---|
| **Hydrogen Production** | `hydrogen.electrolysis_only` | PEM Electrolysis | LP |
| **Hydrogen Production** | `hydrogen.electrolysis_or_gasification` | PEM + Gasifier (MILP) | MILP |
| **Hydrogen Production** | `industrial.green_hydrogen` | Green Hydrogen Hub | LP |
| **Biomass Processing** | `biomass.gasification_to_hydrogen` | Biomass → H₂ (B-HYPSYS) | SLP |
| **Biomass Processing** | `industrial.grand_challenge_10unit` | **Biomass → H₂ (10-Unit Grand Challenge)** | **SLP** |
| **Power Generation** | `industrial.gasification_to_power` | Gasification to Power | LP |
| **Petrochemicals** | `industrial.power_to_methanol` | Power-to-Methanol | LP |
| **Petrochemicals** | `industrial.syngas_production` | Syngas Production | LP |
| **Carbon Capture & Utilization** | `dac.power_to_methane` | Direct Air Capture → Methane | SLP |
| **Other Industrial** | `small.cstr_flash` | CSTR + Flash | SLP |
| **Other Industrial** | `small.compression_train` | Compression Train | LP |
| **Other Industrial** | `small.mixer_settler` | Mixer + Settler | LP |
| **Other Industrial** | `small.distillation` | Distillation Column | SLP |
| **Custom** | `custom.user_flowsheet` | Custom Flowsheet | LP |

### Grand Challenge — 10-Unit Biomass → H₂ (v1.3.0 new)

```
BiomassStorage → Gasifier → Cyclone → HTS-WGS → LTS-WGS →
MoistureSep → CO2Scrubber → PSA → Compressor → H2Polisher
```

Basis: 1 kg/s wet Pine Wood (800 °C gasifier, dual-stage WGS at 400 °C / 220 °C, 94 % PSA recovery, 50 bar product compression). Analytical mass-balance derivation in [`docs/THEORY_REFERENCE.md §10`](docs/THEORY_REFERENCE.md).

---

## Unit Model Library (Layer 3)

### DAC / Power (v1.2.0)

| Class | `is_linear` | Jacobian | Purpose |
|---|---|---|---|
| `TVSAContactor` | **True** | Analytical (5×8) | TVSA DAC unit — fan, thermal regen, vacuum duties |
| `ElectrolyserHF` | **True** | Analytical (3×4) | PEM / AEL electrolyser with StreamPort connectivity |
| `MethanationReactor` | False | Analytical (3×6) | Sabatier equilibrium CO₂ + 4H₂ → CH₄ + 2H₂O |
| `CHPUnit` | **True** | Analytical (7×13) | Combined Heat & Power — turbine + HRSG |

### Biomass / Gas Cooling (v1.1.0 + v1.3.0)

| Class | `is_linear` | Purpose |
|---|---|---|
| `BiomassStorageHF` | True | Drying + preheating |
| `BiomassGasifierHF` | False | Equilibrium gasifier (WGS + methanation Kp) |
| `WGSReactorHF` | False | Water-Gas Shift at fixed T |
| `H2SeparatorPSA` | True | PSA H₂ separation |
| `CoolerHF` | **True** | Single-stream gas cooler — linear, fixed T_out (v1.3.0) |

### Core Engineering

| Category | Units |
|---|---|
| **Reactors** | `StoichiometricReactor` (analytical J), `CSTRHF`, `PFRHF`, `EquilibriumReactor`, `GibbsReactor` |
| **Separators** | `SeparatorHF`, `FlashVLHF`, `DistillationHF`, `FlashSL` |
| **Heat Exchange** | `HeatExchangerNTU`, `ShellTubeHX`, `HeatExchanger1D` |
| **Pressure** | `Compressor`, `Pump`, `Valve` |
| **Mixing** | `MixerHF` |

---

## Solver Suite (Layer 2)

| Mode | `SolveMode` enum | Algorithm | When to use |
|---|---|---|---|
| **SLP** | `FIXED_LP` | Successive Linearization (LP subproblems) | Default — fast, handles 90 % of flowsheets |
| **MILP** | `FLEXIBLE_MILP` | MILP outer loop → SLP refinement | Technology selection (binary decisions) |
| **NLP** | `NLP_IPOPT` | scipy L-BFGS-B with `linearize()` Jacobians | Non-linear, poorly initialised, SLP stagnated |
| **Trust-Region** | `TRUST_REGION` | Filter / Funnel globalisation (Eason & Biegler 2016) | Highly non-linear, large Jacobian condition number |
| **Adaptive** | `ADAPTIVE` | SLP → NLP → Trust-Region cascade | Unknown difficulty — auto-escalates on failure |

**Infeasibility recovery (SLP):** trust-region shrink → warm-start restart (±5 % bound perturbation, up to 3 attempts) → Adaptive cascade.

**Port validation (v1.3.0):** `build_custom_flowsheet()` resolves ports via a prioritised candidate list (`_primary_outlet` / `_primary_inlet`) — any unit pair can be connected regardless of port naming convention. `BaseUnit.validate_connection()` enforces phase / species compatibility at build time.

---

## Economics

CEPCI data (2001–2024) and costing defaults live in `data/economics.json` and are loaded at runtime by `pse_ecosystem/models/costing/economic_engine.py`. Edit the JSON to update cost year assumptions without touching Python code.

---

## Documentation

| File | Contents |
|---|---|
| [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) | **Single funder-ready manual** — Part 1 (Basics), Part 2 (Intermediate: 3-unit chain proof + DACU sensitivity), Part 3 (Advanced Showcase: investor walkthrough, Grand Challenge 10-unit validation, Q&A, key equations) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 3-layer split, Handshake Protocol, hybrid-connection logic (v1.3.0), layer boundary enforcement |
| [`docs/THEORY_REFERENCE.md`](docs/THEORY_REFERENCE.md) | VLE, Rachford-Rice, SLP / Trust-Region theory, §10 Grand Challenge analytical derivation |
| [`docs/WORKSHOP_7UNIT.md`](docs/WORKSHOP_7UNIT.md) | **v1.4.0 — Canonical 7-unit biomass → H₂ workshop**: chain diagram, per-unit input matrix, UI walkthrough, theoretical answer key |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Adding units, flowsheets, testing patterns |
| [`docs/SYSTEM_STATE.md`](docs/SYSTEM_STATE.md) | Source of truth: what exists, test counts, known limitations |

---

## Test Suite (259 pytest cases — audit scripts now in CI)

```powershell
pytest tests\ -q                        # 259 pytest cases (includes audit scripts as subprocess wrappers)
python tests/ui_audit.py                # service + layer checks (also run by pytest)
python tests/system_audit.py            # cross-layer / registry checks (also run by pytest)
python tests/industrial_audit.py        # physics & KPI convergence checks (also run by pytest)
```

The `tests/test_unrestricted_flowsheet.py` suite (44 functions, expanded in
the v1.4.0 audit-hardening pass) guards:

- the uncapped builder (N up to 15) and N-1 connection count,
- openpyxl 3-sheet Excel round-trip with explicit `SI Unit` columns,
- custom-path solve determinism,
- UMS round-trip math (K↔°C↔°F, Pa↔bar↔atm↔psi, etc.) plus edge cases
  (NaN, ±Inf, absolute zero, very high pressure),
- progressive-tightening schedule behaviour at every phase,
- every entry in `AVAILABLE_UNITS` instantiates with empty params,
- TRF / NLP / Adaptive solver-mode smoke tests (the v1.3.x TRF spurious
  convergence bug is now guarded),
- slider bounds (1–1500), progressive-tightening default `True`, and
  version-string consistency across `__init__.py`, `pyproject.toml`,
  and the Streamlit caption.

---

## Packaging

```powershell
python scripts/package_app.py --check   # pre-flight
python scripts/package_app.py --build   # creates dist/pse_ecosystem_ui/
python scripts/package_app.py --info    # known issues
```
