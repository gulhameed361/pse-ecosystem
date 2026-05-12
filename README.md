# PSE Ecosystem (v1.2.0)

Application-centric Knowledge Ecosystem for Process Systems Engineering.  
**Private — University of Surrey.**

---

## Architecture

Three strictly separated layers:

| Layer | Location | Responsibility |
|---|---|---|
| **1 — UI** | `pse_ecosystem/ui/` | 4-page Streamlit app; `flowsheet_service.py` is the sole bridge to Layer 3 |
| **2 — Solver** | `pse_ecosystem/solvers/` | SLP / NLP / Trust-Region drivers; adaptive cascade orchestration |
| **3 — Knowledge** | `pse_ecosystem/models/` + `flowsheets/` | Unit models supplying residuals + analytical Jacobians via the Handshake Protocol |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full blueprint and L2↔L3 contract.

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
pytest tests\ -q                       # 107 unit tests

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
| **Dashboard** | Solver status, template gallery (13 templates), last solve result |
| **Flowsheet Builder** | Category filter → template → Mermaid topology → parameter form → **Apply & Select**. 1D Sensitivity Sweep. Custom flowsheet assembler (1–4 units). |
| **GPS Weather** | pvlib clearsky solar GHI + Weibull wind profiles for any lat/lon/year |
| **Solver Monitor** | Solver mode selector (SLP / NLP / Trust-Region / Adaptive) → **Run Solve** → live convergence chart → KPI cards + solution table |

---

## Flowsheet Templates (v1.2.0)

| Key | Name | Category | Solver |
|---|---|---|---|
| `hydrogen.electrolysis_only` | PEM Electrolysis | Hydrogen | LP (linear) |
| `hydrogen.electrolysis_or_gasification` | PEM + Gasifier | Hydrogen | MILP |
| `industrial.green_hydrogen` | Green Hydrogen Hub | Industrial | LP |
| `industrial.power_to_methanol` | Power-to-Methanol | Industrial | LP |
| `industrial.gasification_to_power` | Gasification to Power | Industrial | LP |
| `industrial.syngas_production` | Syngas Production | Industrial | LP |
| `biomass.gasification_to_hydrogen` | Biomass → H₂ (B-HYPSYS) | Hydrogen | SLP (3–10 iters) |
| **`dac.power_to_methane`** | **Direct Air Capture → Methane** | **Industrial** | **SLP (2 iters)** |
| `custom.user_flowsheet` | Custom Flowsheet | Custom | LP |
| `small.cstr_flash` | CSTR + Flash | Small | SLP |
| `small.compression_train` | Compression Train | Small | LP |
| `small.mixer_settler` | Mixer + Settler | Small | LP |
| `small.distillation` | Distillation Column | Small | SLP |

---

## Unit Model Library (Layer 3)

### DAC / Power (v1.2.0 — new)

| Class | `is_linear` | Jacobian | Purpose |
|---|---|---|---|
| `TVSAContactor` | **True** | Analytical (5×8) | TVSA DAC unit — fan, thermal regen, vacuum duties |
| `ElectrolyserHF` | **True** | Analytical (3×4) | PEM / AEL electrolyser with StreamPort connectivity |
| `MethanationReactor` | False | Analytical (3×6) | Sabatier equilibrium CO₂ + 4H₂ → CH₄ + 2H₂O |
| `CHPUnit` | **True** | Analytical (7×13) | Combined Heat & Power — turbine + HRSG |

### Biomass (v1.1.0)

| Class | `is_linear` | Purpose |
|---|---|---|
| `BiomassStorageHF` | True | Drying + preheating |
| `BiomassGasifierHF` | False | Equilibrium gasifier (WGS + methanation Kp) |
| `WGSReactorHF` | False | Water-Gas Shift at fixed T |
| `H2SeparatorPSA` | True | PSA H₂ separation |

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

**Port validation:** `BaseUnit.validate_connection()` is called at `BaseFlowsheet.connect()` build time — phase / species mismatches raise `PortCompatibilityError` immediately, not at solve time.

---

## Economics

CEPCI data (2001–2024) and costing defaults live in `data/economics.json` and are loaded at runtime by `pse_ecosystem/models/costing/economic_engine.py`. Edit the JSON to update cost year assumptions without touching Python code.

---

## Documentation

| File | Contents |
|---|---|
| [`docs/UI_GUIDE.md`](docs/UI_GUIDE.md) | Full UI reference: page walkthrough, template catalogue, parameter table, custom flowsheet, sensitivity sweep, solver modes |
| [`docs/TUTORIAL_WALKTHROUGH.md`](docs/TUTORIAL_WALKTHROUGH.md) | Step-by-step tutorial: Case A (3-unit SLP convergence proof), Case B (DACU sensitivity analysis), Solver Guide |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 3-layer split, Handshake Protocol, layer boundary enforcement |
| [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) | Installation, API examples, unit catalogue, solver configuration |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Adding units, flowsheets, testing patterns |
| [`docs/THEORY_REFERENCE.md`](docs/THEORY_REFERENCE.md) | VLE, Rachford-Rice, SLP / Trust-Region theory, property correlations |
| [`docs/SYSTEM_STATE.md`](docs/SYSTEM_STATE.md) | Source of truth: what exists, test counts, known limitations |

---

## Test Suite (107 checks)

```powershell
pytest tests\ -q                        # 107 pytest (all fast)
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
