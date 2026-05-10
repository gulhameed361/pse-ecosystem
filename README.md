# PSE Ecosystem (v1.0.0)

Application-centric Knowledge Ecosystem for Process Systems Engineering.  
Private — University of Surrey.

---

## Architecture

Three strictly separated layers:

| Layer | Location | Responsibility |
|---|---|---|
| **1 — UI** | `pse_ecosystem/ui/` | Multi-page Streamlit app; `flowsheet_service.py` is the sole bridge to Layer 3 |
| **2 — Solver** | `pse_ecosystem/solvers/` | Pyomo LP / MILP + Successive Linearization (SLP) driver |
| **3 — Knowledge** | `pse_ecosystem/models/` + `flowsheets/` | Unit models supplying residuals + Jacobians via the Handshake Protocol |

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
pytest tests\ -q                        # 107 unit tests
python tests/industrial_audit.py        # 11 physics checks
python tests/ui_audit.py                # 15 service + layer checks

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
| **Dashboard** | LP solver status, template gallery (11 templates), last solve result |
| **Flowsheet Builder** | Category filter → template → Mermaid topology → parameter form → Apply & Select. Custom flowsheet assembler (1–4 units, port wiring) |
| **GPS Weather** | pvlib clearsky solar GHI + Weibull wind profiles for any lat/lon/year |
| **Solver Monitor** | Run Solve → live SLP progress bar + per-iteration convergence chart → KPI cards + solution table |

---

## Flowsheet Templates (v1.0.0)

| Key | Name | Category | Solve |
|---|---|---|---|
| `hydrogen.electrolysis_only` | PEM Electrolysis | Hydrogen | LP |
| `hydrogen.electrolysis_or_gasification` | PEM + Gasifier | Hydrogen | MILP |
| `industrial.green_hydrogen` | Green Hydrogen Hub | Industrial | LP |
| `industrial.power_to_methanol` | Power-to-Methanol | Industrial | LP |
| `industrial.gasification_to_power` | Gasification to Power | Industrial | LP |
| `industrial.syngas_production` | Syngas Production | Industrial | LP |
| `custom.user_flowsheet` | Custom Flowsheet | Custom | LP |
| `small.cstr_flash` | CSTR + Flash | Small | LP |
| `small.compression_train` | Compression Train | Small | LP |
| `small.mixer_settler` | Mixer + Settler | Small | LP |
| `small.distillation` | Distillation Column | Small | LP |

---

## Documentation

| File | Contents |
|---|---|
| [`docs/UI_GUIDE.md`](docs/UI_GUIDE.md) | Full UI reference: quick-start, page walkthrough, template ref, parameter table, CI KPI, custom flowsheet, packaging, troubleshooting, developer guide, property overrides, flowsheet merging |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 3-layer split, Handshake Protocol, layer boundary enforcement |
| [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) | Installation, API examples, unit catalog, SLP config |
| [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) | Adding units, flowsheets, testing patterns |
| [`docs/THEORY_REFERENCE.md`](docs/THEORY_REFERENCE.md) | VLE, Rachford-Rice, SLP theory, property correlations |
| [`docs/SYSTEM_STATE.md`](docs/SYSTEM_STATE.md) | Source of truth: what exists, test counts, known limitations |

---

## Test Suite (158 checks)

```powershell
pytest tests\ -q                        # 107 pytest
python tests/ui_backend_sync.py         # 8 math accuracy
python tests/ui_audit.py                # 15 service + layer
python tests/system_audit.py            # 17 system
python tests/industrial_audit.py        # 11 physics (Feed→CSTR→Flash→Sep)
```

---

## Packaging

```powershell
python scripts/package_app.py --check   # pre-flight
python scripts/package_app.py --build   # creates dist/pse_ecosystem_ui/
python scripts/package_app.py --info    # known issues
```
