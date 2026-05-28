# PSE Ecosystem (v1.6.1)

**Industrial-grade process simulation with transparent, auditable physics.**

---

## Who uses PSE Ecosystem?

| User | What they do with it |
|---|---|
| **Research academic** | Build novel flowsheets fast, inspect exact Jacobians and residuals, run 2D Pareto sweeps, validate against literature |
| **Process engineer** | Screen technologies, optimise operating points, generate engineering safety margins (ASME, LFL/UFL) |
| **Project developer / VC** | Compare Base / Optimistic / Pessimistic scenarios, run tornado sensitivity, compute break-even H₂ price, download an investor-grade report |
| **Regulatory analyst** | Audit every equation — all physics are explicit algebraic residuals with analytical Jacobians; no black-box solver |

---

## Why PSE Ecosystem?

- **Explainable physics.** Every unit model ships its exact algebraic residuals and analytical Jacobian. Regulators, auditors, and partners can inspect every equation — no black-box solver.
- **Analytical Jacobians throughout.** Closed-form Jacobians across the full unit library enable transparent sensitivity analysis and fast SLP convergence.
- **3-layer separation.** UI / Solver / Knowledge are strictly decoupled via the Handshake Protocol. Swap the solver without touching the physics; swap the UI without touching the solver.
- **Integrated technoeconomics.** NPV / IRR / LCOH / LCOE in the same tool — no separate post-processing step.
- **Scenario comparison.** Built-in Scenario Manager captures up to 4 named solve results and compares KPIs side-by-side with a delta table and Plotly chart.
- **Investor report.** One-click Markdown/PDF download with process description, KPIs, project economics, ASME safety table, and tornado sensitivity.
- **Standardised OPEX accounting.** Every unit declares an explicit `_OPEX_CONVENTION`; `BaseUnit.opex_per_year()` handles conversion. Excel export tags every numeric column with its SI unit.
- **Unit Management System.** Every float parameter with a convertible dimension shows a unit dropdown next to its value. Backend stays in SI; UI converts at the boundary.
- **Python extensible.** Add a unit model in ~50 lines of Python using the Handshake Protocol.

---

## Architecture

Three strictly separated layers:

| Layer | Location | Responsibility |
|---|---|---|
| **1 — UI** | `pse_ecosystem/ui/` | 12-page Streamlit app; `flowsheet_service.py` is the sole bridge to Layer 3 |
| **2 — Solver** | `pse_ecosystem/solvers/` | SLP / NLP / Trust-Region drivers; adaptive cascade orchestration |
| **3 — Knowledge** | `pse_ecosystem/models/` + `flowsheets/` | Unit models supplying residuals + analytical Jacobians via the Handshake Protocol |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full blueprint, Handshake Protocol, and hybrid-connection logic.

---

## Quick Start

### Windows (PowerShell)

```powershell
# One-time: create venv
python -m venv $HOME\.venvs\pse_ecosystem

# Activate (every new shell)
& $HOME\.venvs\pse_ecosystem\Scripts\Activate.ps1

# Install package + all extras
pip install -e ".[dev,solvers,gui,weather]"

# Run tests
pytest tests\ -q

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

12 pages:

| Page | What it does |
|---|---|
| **Dashboard** | Solver status, template gallery, last solve result |
| **Flowsheet Builder** | Category filter → template → Mermaid topology → parameter form → **Apply & Select**. 1D Sensitivity Sweep. Objective Function tab. Custom flowsheet assembler (any number of units, 3-column specification grid). |
| **GPS Weather** | pvlib clearsky solar GHI + Weibull wind profiles for any lat/lon/year |
| **Solver Monitor** | Active-objective mirror. Solver mode selector (SLP / NLP / Trust-Region / Adaptive) → **Run Solve** → live convergence chart → KPI cards + solution table → Excel export. |
| **Solve History** | Persistent log at `~/.pse_ecosystem/history.jsonl`; survives Streamlit reloads |
| **Scenario Manager** | Capture up to 4 named scenarios; KPI delta table + Plotly bar chart + Excel export |
| **Dynamics Studio** | DAE perturbation + time-domain response plots |
| **Relief Sizing** | API 520/521 relief valve sizing with post-solve safety margins |
| **Pinch Preview** | Heat-pinch composite curves and minimum utility targets |
| **Validation** | Parity dashboard; import Aspen streams; kinetic tuning |
| **Case Study** | Pre-built end-to-end industrial case studies |
| **Help Center** | Live-loaded `docs/` markdown — User Manual, Workshop, Theory Reference, Architecture, Developer Guide |

---

## Flowsheet Templates (14 templates across 6 industrial sectors)

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

### Grand Challenge — 10-Unit Biomass → H₂

```
BiomassStorage → Gasifier → Cyclone → HTS-WGS → LTS-WGS →
MoistureSep → CO2Scrubber → PSA → Compressor → H2Polisher
```

Basis: 1 kg/s wet Pine Wood (800 °C gasifier, dual-stage WGS at 400 °C / 220 °C, 94 % PSA recovery, 50 bar product compression). Analytical mass-balance derivation in [`docs/THEORY_REFERENCE.md §10`](docs/THEORY_REFERENCE.md).

---

## Unit Model Library (Layer 3)

### DAC / Power

| Class | `is_linear` | Jacobian | Purpose |
|---|---|---|---|
| `TVSAContactor` | **True** | Analytical (5×8) | TVSA DAC unit — fan, thermal regen, vacuum duties |
| `ElectrolyserHF` | **True** | Analytical (3×4) | PEM / AEL electrolyser with StreamPort connectivity |
| `MethanationReactor` | False | Analytical (3×6) | Sabatier equilibrium CO₂ + 4H₂ → CH₄ + 2H₂O |
| `CHPUnit` | **True** | Analytical (7×13) | Combined Heat & Power — turbine + HRSG |

### Biomass / Gas Cooling

| Class | `is_linear` | Purpose |
|---|---|---|
| `BiomassStorageHF` | True | Drying + preheating |
| `BiomassGasifierHF` | False | Equilibrium gasifier (WGS + methanation Kp) |
| `WGSReactorHF` | False | Water-Gas Shift at fixed T |
| `H2SeparatorPSA` | True | PSA H₂ separation |
| `CoolerHF` | **True** | Single-stream gas cooler — linear, fixed T_out |

### Core Engineering

| Category | Units |
|---|---|
| **Reactors** | `StoichiometricReactor` (analytical J), `CSTRHF`, `PFRHF`, `EquilibriumReactor`, `GibbsReactor`, `BatchReactor` |
| **Separators** | `SeparatorHF`, `FlashVLHF`, `DistillationHF`, `FlashSL`, `Decanter`, `Crystallizer`, `MembraneModule`, `PackedColumn`, `TrayColumn` |
| **Heat Exchange** | `HeatExchangerNTU`, `ShellTubeHX`, `HeatExchanger1D`, `FiredHeater` |
| **Pressure** | `Compressor`, `Pump`, `Valve`, `Expander`, `MultistageCompressor` |
| **Mixing** | `MixerHF` |
| **Utilities** | `SteamDrum` |

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

---

## Economics

CEPCI data (2001–2024) and costing defaults live in `pse_ecosystem/data/economics.json` and are loaded at runtime by `pse_ecosystem/models/costing/economic_engine.py`. Edit the JSON to update cost-year assumptions without touching Python code.

---

## Documentation

| File | Contents |
|---|---|
| [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) | End-to-end manual — Basics, Intermediate (3-unit chain + sensitivity), Advanced (investor walkthrough, Grand Challenge validation, key equations) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 3-layer split, Handshake Protocol, hybrid-connection logic |
| [`docs/THEORY_REFERENCE.md`](docs/THEORY_REFERENCE.md) | VLE, Rachford-Rice, SLP / Trust-Region theory, Grand Challenge analytical derivation |
| [`docs/WORKSHOP_7UNIT.md`](docs/WORKSHOP_7UNIT.md) | Canonical 7-unit biomass → H₂ workshop: chain diagram, per-unit input matrix, UI walkthrough, answer key |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Adding units, flowsheets, testing patterns |

---

## Test Suite

```powershell
pytest tests\ -q    # ~998 tests, 0 failures
```

---

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for the full release history.

---

## Packaging

```powershell
python scripts/package_app.py --check   # pre-flight
python scripts/package_app.py --build   # creates dist/pse_ecosystem_ui/
python scripts/package_app.py --info    # known issues
```
