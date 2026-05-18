# PSE Ecosystem (v1.4.0)

Application-centric Knowledge Ecosystem for Process Systems Engineering.  
**Private — University of Surrey.**

---

## Why PSE Ecosystem?

- **Explainable physics.** Every unit model ships its exact algebraic residuals and analytical Jacobian. Regulators, auditors, and partners can inspect every equation — no black-box solver.
- **Analytical Jacobians throughout.** The SLP solver linearises using exact ∂f/∂x, not finite differences. Faster convergence, provable gradient accuracy.
- **3-layer separation.** UI / Solver / Knowledge are strictly decoupled via the Handshake Protocol. Swap the solver without touching the physics; swap the UI without touching the solver.
- **Unrestricted Assembly Freedom (v1.4.0).** Aspen-style Custom Flowsheet builder — no hard cap on unit count. 3-column specification grid with pre-filled engineering defaults; smart Unit ID dropdown re-seeds on Type change. **23 UI-selectable unit types** drawn from a 36-class Layer-3 catalogue.
- **Unit Management System (v1.4.0).** Every float parameter with a convertible dimension (T, P, mass flow, mass, power, energy) shows a unit dropdown next to its value. Backend stays in SI; UI converts at the boundary. Excel export tags every numeric column with its SI unit.
- **Analytical Verification.** Every unit exposes exact Jacobians; 7-unit workshop chain validated via the automated test suite (**240 pytest cases**, plus the audit scripts integrated into CI).
- **Live Help Center (v1.4.0).** A 6th nav page renders the workspace `docs/` markdown directly in the app — User Manual, 7-Unit Workshop with answer key, Theory Reference, Architecture, Developer Guide. Edits to source markdown refresh on the next render.
- **Excel Export.** Download a 3-sheet ledger (Stream Table / Unit Performance / Optimization Summary) to `.xlsx` from the Solver Monitor.
- **Progressive Solver Tightening (default ON in v1.4.0).** SLP starts with loose tolerances (≈1e-3) and tightens to precision (≈1e-7) as iterations progress. Max Iterations slider extended to **1500**.

---

## Architecture

Three strictly separated layers:

| Layer | Location | Responsibility |
|---|---|---|
| **1 — UI** | `pse_ecosystem/ui/` | 5-page Streamlit app (incl. Help Center); `flowsheet_service.py` is the sole bridge to Layer 3 |
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
pytest tests\ -q                       # 240 pytest cases pass (incl. audit scripts)

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

## Test Suite (240 pytest cases — audit scripts now in CI)

```powershell
pytest tests\ -q                        # 240 pytest cases (includes audit scripts as subprocess wrappers)
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
