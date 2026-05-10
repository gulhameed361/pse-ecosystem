# PSE Ecosystem — UI User Guide

**Version:** v0.3.0  |  **Private — University of Surrey**

---

## 1. Prerequisites & Installation

Ensure you are using the project venv located **outside** OneDrive:

```powershell
# Activate venv (PowerShell)
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1

# Install with GUI + weather extras
pip install -e ".[gui,weather]"
```

This installs `streamlit>=1.28`, `plotly>=5.0`, `pvlib>=0.10`, and `pandas>=1.5`
on top of the core `numpy` + `pyomo` dependencies.

You also need at least one LP solver. Install HiGHS (recommended):

```powershell
pip install highspy
```

---

## 2. Launching the UI

From the repo root (venv active):

```powershell
streamlit run pse_ecosystem/ui/app_streamlit.py
```

A browser window opens automatically at `http://localhost:8501`.

---

## 3. Page-by-Page Walkthrough

### 3.1 Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚗ PSE Ecosystem                                    v0.3.0          │
│  Private — University of Surrey                                      │
├──────────────┬──────────────┬──────────────┬───────────────────────┤
│  Templates   │  Unit Models │  LP Solver   │  Last Solve           │
│     9        │  16+ HF units│  Available   │  CONVERGED            │
├──────────────┴──────────────┴──────────────┴───────────────────────┤
│  ▼ Architecture Overview                                             │
│    Layer 1: UI (Streamlit)          ← you are here                  │
│        │  calls flowsheet_service.py                                 │
│    Layer 2: Solvers (Pyomo LP/MILP) ← Orchestrator, SLPDriver       │
│        │  calls LinearizedModel interface                            │
│    Layer 3: Knowledge (Unit Models) ← Physics, VLE, costing         │
├─────────────────────────────────────────────────────────────────────┤
│  Template Gallery                                                    │
│  ┌──────────────────────────────┬────────────┬────────────────────┐ │
│  │ Name                         │ Category   │ Units              │ │
│  ├──────────────────────────────┼────────────┼────────────────────┤ │
│  │ PEM Electrolysis             │ Hydrogen   │ PEMToy             │ │
│  │ PEM + Gasifier (MILP)        │ Hydrogen   │ PEMToy, GasifierToy│ │
│  │ Green Hydrogen Hub           │ Industrial │ PEMToy, MixerHF    │ │
│  │ Power-to-Methanol            │ Industrial │ StoichRxr, SepHF   │ │
│  │ Gasification to Power        │ Industrial │ StoichRxr, Comp    │ │
│  │ CSTR + Flash                 │ Small      │ CSTRHF, FlashVLHF  │ │
│  │ ...                          │ ...        │ ...                │ │
│  └──────────────────────────────┴────────────┴────────────────────┘ │
│                                                                      │
│  Last Solve Result                                                   │
│  ✓ Converged in 4 iteration(s)  |  Objective: 9.62e+05              │
└─────────────────────────────────────────────────────────────────────┘
```

**What you see:**

| Card | Meaning |
|---|---|
| Templates | Number of registered flowsheet templates |
| Unit Models | "16+ HF units" — the Layer-3 model library |
| LP Solver | "Available" if HiGHS/GLPK detected, else an install hint |
| Last Solve | Status of the most recent solver run |

The **Template Gallery** table lists every template with its category and unit names.
Click **Flowsheet Builder** in the left navigation to select one.

The **Architecture Overview** expander shows the 3-layer split as an ASCII diagram.

---

### 3.2 Flowsheet Builder

```
┌─────────────────────────────────────────────────────────────────────┐
│  🔧 Flowsheet Builder                                                │
├──────────────────────┬──────────────────────────────────────────────┤
│  Category            │  Flowsheet Topology                          │
│  [Industrial      ▼] │                                              │
│                      │   Feed([CO2+H2]) --> Rxr[Stoich. Reactor]    │
│  Template            │   Rxr --> Sep[Separator]                     │
│  [Power-to-Methanol▼]│   Sep --> Vap([Gas phase])                   │
│                      │   Sep --> Liq([Liquid MeOH])                 │
│  CO2 + 3H2 → methanol│                                              │
│  + H2O, then split   │  ┌──────────────────────────────────────┐   │
│  separation.         │  │ Stream Connections                    │   │
│  Fully linear.       │  │ From            To        Description │   │
│                      │  │ Reactor outlet  Sep inlet  Rxr → Sep  │   │
│  ☐ MILP template     │  └──────────────────────────────────────┘   │
│                      │                                              │
│                      │  Parameters                                  │
│                      │  ┌──────────────────────────────────────┐   │
│                      │  │ Extent Max   [  3.0              ]   │   │
│                      │  │                                      │   │
│                      │  │         [ Apply & Select ]           │   │
│                      │  └──────────────────────────────────────┘   │
│                      │  ✓ Template Power-to-Methanol selected.      │
│                      │    Go to Solver Monitor to run.              │
└──────────────────────┴──────────────────────────────────────────────┘
```

**Step-by-step:**

1. **Filter by Category** — use the "Category" drop-down (All / Small / Hydrogen / Industrial).
2. **Select Template** — choose from the filtered list.  
   The description card below the list explains the process.
3. **View Topology** — an interactive Mermaid diagram renders the flowsheet.  
   Toggle "Use simple Graphviz diagram" for offline environments.
4. **Configure Parameters** — a form shows editable parameters (e.g. H2 demand, extent limit).  
   Templates with no user-facing parameters show a fixed-defaults notice.
5. **Apply & Select** — click the blue button. A confirmation message appears.  
   Navigate to **Solver Monitor** to run the solve.

**Connection table** — below the topology diagram, a table shows the stream connections
wired by `fs.connect()`.

---

### 3.3 GPS Weather

```
┌─────────────────────────────────────────────────────────────────────┐
│  🌍 GPS Weather                                                      │
│  Fetch site-specific solar & wind profiles via pvlib.                │
├─────────────────────┬──────────────────────┬────────────────────────┤
│  Latitude (°N)      │  Longitude (°E)      │  Altitude (m)          │
│  [ 51.2400        ] │  [ -0.5900         ] │  [ 68.0             ]  │
├─────────────────────┴──────────────────────┴────────────────────────┤
│  Timezone (IANA)  [ Europe/London ]    Year  [ 2023 ]               │
│                                                                      │
│                        [ Fetch Profiles ]                            │
├──────────────────────────────────────────────────────────────────────┤
│  ✓ Profiles fetched for Site (51.24°N, -0.59°E), year 2023.         │
├───────────────────┬──────────────────┬──────────────────────────────┤
│  Peak GHI (W/m²)  │  Mean Wind (m/s) │  Solar Hours / Year          │
│      892          │      7.84        │       4 380                  │
├───────────────────┴──────────────────┴──────────────────────────────┤
│  [ Solar GHI ]  [ Wind Speed ]                                       │
│                                                                      │
│  Annual Solar GHI Profile                                            │
│                                                                      │
│  900 ┤                        ╭──╮                                   │
│  700 ┤               ╭──╮   ╭╯  ╰╮   ╭──╮                          │
│  500 ┤         ╭╮   ╭╯  ╰───╯    ╰───╯  ╰╮                         │
│  300 ┤    ╭╮  ╭╯╰───╯                     ╰──╮  ╭╮                  │
│  100 ┤────╯╰──╯                               ╰──╯╰────             │
│    0 ┤                                                               │
│      └────────────────────────────────────────────────── hour        │
│         0      1000     2000     3000     4000     8760              │
└─────────────────────────────────────────────────────────────────────┘
```

**Purpose:** Fetch site-specific solar GHI and wind speed profiles via pvlib clearsky models.
The profiles are stored in the session and can be used to contextualise the simulation.

**Steps:**

1. Enter **Latitude**, **Longitude**, **Altitude**.  
   Default: University of Surrey, Guildford (51.24°N, −0.59°E, 68 m).
2. Set the **IANA Timezone** (e.g. `Europe/London`, `UTC`, `America/New_York`).
3. Choose the **Year** for the clearsky profile.
4. Click **Fetch Profiles**.

**Output:**

- Two Plotly interactive line charts: Solar GHI [W/m²] and Wind speed [m/s] vs. hour of year.
- Metric cards: Peak GHI, Mean Wind, Solar Hours / Year.
- Profiles are stored in session state and persist while the browser tab is open.

---

### 3.4 Solver Monitor

```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 Solver Monitor                                                   │
│  Template: Power-to-Methanol   Key: industrial.power_to_methanol     │
│  Category: Industrial                                                │
├─────────────────────────────────────────────────────────────────────┤
│  ▼ Solver Settings                                                   │
│    Max iterations  [=============================·····] 50          │
│    Step tolerance  [ 1.00e-04 ]                                      │
│    ● Mode 1 — Fixed LP   ○ Mode 2 — Flexible MILP                   │
│    ☐ Verbose solver output                                           │
│                                                                      │
│                          [ Run Solve ]                               │
├─────────────────────────────────────────────────────────────────────┤
│  ✓  Converged in 1 iteration(s)  |  Objective: 0.0000               │
├─────────────────────────────────────────────────────────────────────┤
│  SLP Convergence                                                     │
│                                                                      │
│  Obj  1e5 ┤●                                                         │
│           │╲  — Objective                                            │
│       5e4 ┤ ╲                           - - Residual norm           │
│           │  ●───────────────────────                                │
│       0   ┤                                           iteration      │
│           └────────────────────────────                              │
│               0         1                                            │
├─────────────────────────────────────────────────────────────────────┤
│  KPIs                                                                │
│  ┌───────────────┬───────────────┬───────────────┬─────────────┐   │
│  │  V frac       │  vapor flow   │  liquid flow  │  Q W        │   │
│  │    0.05       │   0.5882      │   11.18       │   0.0       │   │
│  └───────────────┴───────────────┴───────────────┴─────────────┘   │
│                                                                      │
│  ████████████████████████████                                        │
│    vapor_flow  ██████████                    [KPI bar chart]         │
│    liquid_flow ████████████████████████████                          │
│    Q_W         ▏                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Solution Variables                                                  │
│  ┌───────────────────────────────┬──────────────┐                   │
│  │ Variable                      │ Value        │                   │
│  ├───────────────────────────────┼──────────────┤                   │
│  │ rxr.inlet.F_CO2               │ 3.000000     │                   │
│  │ rxr.inlet.F_H2                │ 9.000000     │                   │
│  │ rxr.outlet.F_methanol         │ 3.000000     │                   │
│  │ rxr.outlet.F_water            │ 3.000000     │                   │
│  │ sep.outlet_1.F_methanol       │ 2.850000     │                   │
│  │ sep.outlet_1.F_water          │ 2.940000     │                   │
│  │ ...                           │ ...          │                   │
│  └───────────────────────────────┴──────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

**Step-by-step:**

1. Verify the **Selected Template** shown at the top (set in Flowsheet Builder).
2. Expand **Solver Settings**:
   - **Max iterations**: 5–100 (default 50). Increase for convergence-sensitive templates.
   - **Step tolerance (eps_x)**: LP convergence criterion (default 1×10⁻⁴).
   - **Mode 1 / Mode 2**: Fixed LP or Flexible MILP (MILP only for supported templates).
   - **Verbose**: print SLP iteration detail to the server console.
3. Click **Run Solve** (blue button).

**Post-solve output:**

| Section | Content |
|---|---|
| Status banner | Green ✓ (converged) or Red ✗ (failed) with iteration count and objective |
| Convergence plot | Dual-axis Plotly chart: Objective + Residual norm vs. SLP iteration |
| KPI cards | One `st.metric()` card per KPI (rows of 4) |
| KPI bar chart | Plotly bar chart of all KPI values |
| Solution Variables | Full `result.x` dict as a scrollable table |
| Technology Selection | JSON badge (MILP mode only) showing active technologies |

---

## 4. Template Reference

| Key | Name | Category | Units | Solve mode |
|---|---|---|---|---|
| `hydrogen.electrolysis_only` | PEM Electrolysis | Hydrogen | PEMToy | Mode 1 LP |
| `hydrogen.electrolysis_or_gasification` | PEM + Gasifier | Hydrogen | PEMToy, GasifierToy | Mode 2 MILP |
| `industrial.green_hydrogen` | Green Hydrogen Hub | Industrial | PEMToy, MixerHF | Mode 1 LP |
| `industrial.power_to_methanol` | Power-to-Methanol | Industrial | StoichiometricReactor, SeparatorHF | Mode 1 LP |
| `industrial.gasification_to_power` | Gasification to Power | Industrial | StoichiometricReactor, Compressor | Mode 1 LP |
| `small.cstr_flash` | CSTR + Flash | Small | CSTRHF, FlashVLHF | Mode 1 LP |
| `small.compression_train` | Compression Train | Small | Compressor, ShellTubeHX, Valve | Mode 1 LP |
| `small.mixer_settler` | Mixer + Settler | Small | MixerHF, SeparatorHF | Mode 1 LP |
| `small.distillation` | Distillation Column | Small | DistillationHF | Mode 1 LP |

---

## 5. Running the Audit

The UI audit validates the service bridge, layer boundaries, and template convergence:

```powershell
python tests/ui_audit.py --verbose
```

Expected output: **15 passed, 0 failed**.

For full regression coverage also run:

```powershell
python tests/system_audit.py
python tests/industrial_audit.py
python -m pytest tests\ -q
```

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| "No LP solver available" | `pip install highspy` or install GLPK via your package manager |
| "pvlib not installed" | `pip install 'pse_ecosystem[weather]'` |
| "streamlit is required" | `pip install 'pse_ecosystem[gui]'` |
| Template shows INFEASIBLE | Try increasing Max iterations in Solver Settings |
| Mermaid diagram blank | Toggle "Use simple Graphviz diagram" (CDN may be blocked) |
| Pyomo W1002 warning on Green Hydrogen | Harmless numerical precision warning; result is correct |

---

## 7. Developer Guide — Adding a Template

1. **Create the flowsheet factory** in `pse_ecosystem/flowsheets/` (Layer 3).  
   Follow the patterns in `pse_ecosystem/flowsheets/industrial/`.

2. **Register it in the service bridge** (`pse_ecosystem/ui/flowsheet_service.py`):
   - Add a `TemplateSpec` entry to `_REGISTRY`.
   - Write a `_load_<name>(p: dict)` helper function with deferred Layer-3 imports.
   - Add the key → loader mapping to `_LOADER_MAP`.

3. **Verify** with the UI audit:
   ```powershell
   python tests/ui_audit.py
   ```

4. **Test convergence** manually:
   ```powershell
   python -c "
   from pse_ecosystem.ui.flowsheet_service import load_template
   from pse_ecosystem.solvers.orchestrator import Orchestrator
   from pse_ecosystem.core.contracts import SolveMode
   fs = load_template('your.template.key', {})
   r = Orchestrator(fs, SolveMode.FIXED_LP).solve()
   print(r.status, r.kpis)
   "
   ```
