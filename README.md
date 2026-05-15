# PSE Ecosystem (v1.3.0)

Application-centric Knowledge Ecosystem for Process Systems Engineering.  
**Private — University of Surrey.**

---

## Why PSE Ecosystem?

- **Explainable physics.** Every unit model ships its exact algebraic residuals and analytical Jacobian. Regulators, auditors, and partners can inspect every equation — no black-box solver.
- **Analytical Jacobians throughout.** The SLP solver linearises using exact ∂f/∂x, not finite differences. Faster convergence, provable gradient accuracy.
- **3-layer separation.** UI / Solver / Knowledge are strictly decoupled via the Handshake Protocol. Swap the solver without touching the physics; swap the UI without touching the solver.
- **Modular Assembly Freedom.** Aspen-style Custom Flowsheet builder with dynamic parameter forms — pre-filled engineering defaults per unit type. 16+ unit types supported.
- **Analytical Verification.** Every unit exposes exact Jacobians; 7-unit workshop chain validated via 154 automated tests.
- **Excel Export.** Download KPIs and solution variables to `.xlsx` from the Solver Monitor.
- **Progressive Solver Tightening.** New SLP strategy for complex chains; Max Iterations slider extended to 1000.

---

## Architecture

Three strictly separated layers:

| Layer | Location | Responsibility |
|---|---|---|
| **1 — UI** | `pse_ecosystem/ui/` | 4-page Streamlit app; `flowsheet_service.py` is the sole bridge to Layer 3 |
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
pytest tests\ -q                       # 146 unit tests

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

Four pages:

| Page | What it does |
|---|---|
| **Dashboard** | Solver status, template gallery (14 templates), last solve result |
| **Flowsheet Builder** | Category filter → template → Mermaid topology → parameter form → **Apply & Select**. 1D Sensitivity Sweep. Custom flowsheet assembler (1–10 units, shared component set, composite super-unit option). |
| **GPS Weather** | pvlib clearsky solar GHI + Weibull wind profiles for any lat/lon/year |
| **Solver Monitor** | Solver mode selector (SLP / NLP / Trust-Region / Adaptive) → **Run Solve** → live convergence chart → KPI cards + solution table |

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
| [`docs/UI_GUIDE.md`](docs/UI_GUIDE.md) | Full UI reference: page walkthrough, template catalogue, parameter table, custom flowsheet, sensitivity sweep |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Adding units, flowsheets, testing patterns |
| [`docs/SYSTEM_STATE.md`](docs/SYSTEM_STATE.md) | Source of truth: what exists, test counts, known limitations |

---

## Test Suite (128 checks)

```powershell
pytest tests\ -q                        # 128 pytest (9 new Grand Challenge tests)
python tests/ui_audit.py                # 15 service + layer checks
python tests/system_audit.py            # 17 system checks
python tests/industrial_audit.py        # 11 physics checks
```

---

## Packaging

```powershell
python scripts/package_app.py --check   # pre-flight
python scripts/package_app.py --build   # creates dist/pse_ecosystem_ui/
python scripts/package_app.py --info    # known issues
```
