# PSE Ecosystem (v0.3.0)

Application-centric Knowledge Ecosystem for Process Systems Engineering.

Three-layer architecture:

1. **Layer 1 — UI / Application:** multi-page Streamlit UI with flowsheet builder, GPS weather, and solver monitor. Service bridge (`flowsheet_service.py`) is the sole Layer-1 module authorised to access Layer-3 factories.
2. **Layer 2 — Decision / Solver:** Pyomo-based LP / MILP with a Successive Linearization (SLP) driver for non-linear units.
3. **Layer 3 — Knowledge / Models:** unit models that supply both residuals and Jacobians via the **Handshake Protocol** in `pse_ecosystem/core/contracts.py`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full architectural blueprint and the L2↔L3 contract.

## Quick start

The repo lives inside OneDrive, so the recommended pattern is to keep the
virtual environment **outside** OneDrive to avoid sync churn over thousands
of DLLs.

### Windows (PowerShell)

```powershell
# One-time: create the venv outside OneDrive
python -m venv $HOME\.venvs\pse_ecosystem

# Activate (every new shell)
& $HOME\.venvs\pse_ecosystem\Scripts\Activate.ps1

# One-time: install the package and dependencies
pip install -e ".[dev,solvers,gui,weather]"

# Run tests
pytest

# Launch the Streamlit UI (v0.3.0)
streamlit run pse_ecosystem/ui/app_streamlit.py

# Run examples (CLI)
python examples/electrolysis_v0.py --mode 1
python examples/electrolysis_v0.py --mode 2
```

### macOS / Linux

```bash
python -m venv ~/.venvs/pse_ecosystem
source ~/.venvs/pse_ecosystem/bin/activate
pip install -e ".[dev,solvers]"
pytest
python examples/electrolysis_v0.py
```
