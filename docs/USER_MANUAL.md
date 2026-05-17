# PSE Ecosystem — User Manual

**Version:** 1.4.0 | **Date:** 2026-05-17 | **Status:** Industrial Production Release

> Single source of truth for PSE Ecosystem users. Replaces `UI_GUIDE.md` (merged here in Phase 6)
> and `SHOWCASE_WALKTHROUGH.md` (merged in Phase 5). For architecture details see `ARCHITECTURE.md`;
> for equation derivations see `THEORY_REFERENCE.md`; for code extensions see `DEVELOPER_GUIDE.md`.
> For a step-by-step build of the 7-unit biomass → H₂ workshop with full answer key,
> see [`WORKSHOP_7UNIT.md`](WORKSHOP_7UNIT.md).

---

## What's new in v1.4.0

- **Unrestricted custom flowsheet.** No hard cap on the number of units in the
  Custom Flowsheet builder — scale to whatever your hardware allows. Past
  ~20 units expect noticeably slower Streamlit reruns.
- **Connection count display fixed.** A 7-unit sequential chain headlines as
  **"7 units, 6 connection(s)"**. The internal port-variable equality count
  (one per shared species + T + P per link) is shown underneath as a caption.
- **Smart Unit ID is no longer sticky.** Changing a unit's Type re-seeds the
  ID dropdown with the new type's suggested slug.
- **3-column specification grid.** The per-unit parameter form renders in
  three columns for Aspen-style density.
- **Max iterations slider 1–1500** (was 5–1000). Progressive tightening
  (loose ≈1e-3 → tight ≈1e-7) is **on by default**.
- **Active-objective mirror** appears at the top of the Solver Monitor page.
- **New 6th page: Help Center.** Live-loads `USER_MANUAL.md`, `WORKSHOP_7UNIT.md`,
  `THEORY_REFERENCE.md`, `ARCHITECTURE.md`, and `DEVELOPER_GUIDE.md` from the
  workspace `docs/` folder — edits to the source markdown refresh on the
  next render.

---

# Part 1 — Interface Basics

## 1.1 Install & Launch

```powershell
# One-time: create venv outside OneDrive to avoid sync churn
python -m venv $HOME\.venvs\pse_ecosystem

# Activate (every new shell)
& $HOME\.venvs\pse_ecosystem\Scripts\Activate.ps1

# Install with all extras
pip install -e ".[dev,solvers,gui,weather]"

# Verify — 170+ pytest functions must pass
pytest tests\ -q

# Launch
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Opens at **http://localhost:8501**. Requires at least one LP solver; install HiGHS if not present:

```powershell
pip install highspy
```

macOS/Linux: replace `Activate.ps1` → `source ~/.venvs/pse_ecosystem/bin/activate`.

---

## 1.2 Five-Minute Tour

| Step | Page | Action |
|---|---|---|
| 1 | **Dashboard** | Check LP Solver = "Available". Browse the 14-template gallery. |
| 2 | **Flowsheet Builder** | Pick sector → template → configure parameters → **Apply & Select**. Optionally run 1D Sensitivity Sweep directly here. |
| 3 | **GPS Weather** | Enter lat/lon → **Fetch Profiles** → view solar GHI and wind charts. |
| 4 | **Solver Monitor** | Choose solver mode (SLP / NLP / Trust-Region / Adaptive) → **Run Solve** → watch live convergence + KPI cards. |

---

## 1.3 Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚗ PSE Ecosystem                                 v1.4.0             │
│  Private — University of Surrey                                      │
├──────────────┬──────────────┬──────────────┬───────────────────────┤
│  Templates   │  Unit Models │  LP Solver   │  Last Solve           │
│     14       │  16+ HF units│  Available   │  CONVERGED            │
├──────────────┴──────────────┴──────────────┴───────────────────────┤
│  ▼ Architecture Overview                                             │
│    Layer 1: UI (Streamlit)          ← you are here                  │
│        │  calls flowsheet_service.py                                 │
│    Layer 2: Solvers (Pyomo LP/MILP) ← Orchestrator, SLPDriver       │
│        │  calls LinearizedModel interface                            │
│    Layer 3: Knowledge (Unit Models) ← Physics, VLE, costing         │
├─────────────────────────────────────────────────────────────────────┤
│  Template Gallery (grouped by industrial sector)                     │
│  ┌──────────────────────────────┬──────────────────┬──────────────┐ │
│  │ Name                         │ Sector           │ Solver       │ │
│  ├──────────────────────────────┼──────────────────┼──────────────┤ │
│  │ PEM Electrolysis             │ Hydrogen Prod.   │ LP (linear)  │ │
│  │ Grand Challenge: Biomass→H₂  │ Biomass Process. │ SLP          │ │
│  │ DAC → Methane                │ CCU              │ SLP          │ │
│  │ CSTR + Flash                 │ Other Industrial │ SLP          │ │
│  │ ...                          │ ...              │ ...          │ │
│  └──────────────────────────────┴──────────────────┴──────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

| Card | Meaning |
|---|---|
| Templates | 14 registered flowsheet templates across 6 industrial sectors + Custom |
| Unit Models | 16+ HF unit classes in Layer 3 |
| LP Solver | "Available" if HiGHS/GLPK detected; shows install hint otherwise |
| Last Solve | Status of the most recent solver run |

---

## 1.4 Flowsheet Builder

```
┌─────────────────────────────────────────────────────────────────────┐
│  🔧 Flowsheet Builder                                                │
├──────────────────────┬──────────────────────────────────────────────┤
│  Sector              │  Flowsheet Topology                          │
│  [Petrochemicals  ▼] │                                              │
│                      │   Feed([CO2+H2]) --> Rxr[Stoich. Reactor]    │
│  Template            │   Rxr --> Sep[Separator]                     │
│  [Power-to-Methanol▼]│   Sep --> Vap([Gas phase])                   │
│                      │   Sep --> Liq([Liquid MeOH])                 │
│  CO2+3H2→methanol    │                                              │
│  +H2O. Linear.       │  Parameters                                  │
│                      │  ┌──────────────────────────────────────┐   │
│                      │  │ ▼ Flowsheet                          │   │
│                      │  │   Extent Max   [  3.0            ]   │   │
│                      │  │         [ Apply & Select ]           │   │
│                      │  └──────────────────────────────────────┘   │
│                      │  ✓ Template selected. Go to Solver Monitor.  │
└──────────────────────┴──────────────────────────────────────────────┘
```

1. **Filter by Sector** — All / Hydrogen Production / Biomass Processing / Power Generation / Petrochemicals / Carbon Capture & Utilization / Other Industrial Processes / Custom.
2. **Select Template** — description appears below the list.
3. **View Topology** — Mermaid diagram. Toggle "Use simple Graphviz diagram" for offline environments.
4. **Configure Parameters** — grouped by unit in collapsible expanders.
5. **Apply & Select** → navigate to **Solver Monitor** to run, or use the Sensitivity Sweep (§1.4a below).

### §1.4a 1D Sensitivity Sweep

Expand **"1D Parameter Sensitivity Sweep"** at the bottom of the Flowsheet Builder page.

| Control | Description |
|---|---|
| Sweep parameter | Numeric template parameter to vary (auto-populated) |
| Min / Max value | Range of the sweep |
| Points | Number of solve calls (3–30) |
| **Run Sweep** | Runs N × `SolveMode.FIXED_LP` solves; plots all KPIs vs the swept parameter |

Results appear as a live Plotly multi-trace chart and a data table. Useful for CO₂ capture efficiency sensitivity, reactor temperature sweeps, LCOH vs electricity price, etc.

### §1.4b Custom Flowsheet Assembler

Select sector **Custom** → **Custom Flowsheet** to access the Aspen-style unit assembler:
1. Set **Shared Component Set** (e.g. `H2,CO,CO2,H2O,CH4,N2`).
2. Set **Number of units** (1–10).
3. For each unit: pick a **type** from the dropdown (16 types across 7 categories).
4. Set unit IDs and parameters.
5. In the **Connections** panel, wire outlet → inlet pairs.
6. Click **Build & Select** — success banner shows "N units, M connections".
7. Navigate to **Solver Monitor → Run Solve**.

See **Part 2** for the complete 7-unit step-by-step workshop.

---

## 1.5 GPS Weather

```
┌─────────────────────────────────────────────────────────────────────┐
│  🌍 GPS Weather                                                      │
├─────────────────────┬──────────────────────┬────────────────────────┤
│  Latitude (°N)      │  Longitude (°E)      │  Altitude (m)          │
│  [ 51.2400        ] │  [ -0.5900         ] │  [ 68.0             ]  │
├─────────────────────┴──────────────────────┴────────────────────────┤
│  Timezone [ Europe/London ]    Year  [ 2023 ]                        │
│                        [ Fetch Profiles ]                            │
├──────────────────────────────────────────────────────────────────────┤
│  Peak GHI (W/m²)  │  Mean Wind (m/s)  │  Solar Hours / Year         │
│      833          │      7.11         │       4 380                 │
└──────────────────────────────────────────────────────────────────────┘
```

Default site: University of Surrey, Guildford (51.24°N, −0.59°E, 68 m).
Profiles stored in session state; persist across pages within the same browser tab.

---

## 1.6 Solver Monitor

```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 Solver Monitor                                                   │
├─────────────────────────────────────────────────────────────────────┤
│  ▼ Solver Settings                                                   │
│    Max iterations  [═══════════════════════·····] 50                │
│    Step tolerance  [ 1.00e-04 ]                                      │
│    Solver Mode                                                       │
│    ● SLP (fast, LP-based)                                            │
│    ○ NLP (scipy L-BFGS-B, full residual)                             │
│    ○ Trust-Region Filter (robust, filter globalisation)              │
│    ○ Adaptive (SLP → NLP → Trust-Region cascade)                     │
│    ☐ Verbose solver output                                           │
│                          [ Run Solve ]                               │
├─────────────────────────────────────────────────────────────────────┤
│  [██████████████████░░░░░] Iteration 2/3 | Obj: 9.618e+05 | ‖f‖: 0.031
│                                                                      │
│  Convergence Chart (dual-axis: Objective + Residual norm)           │
│  KPI Cards  |  KPI Bar Chart  |  Solution Variables Table           │
└─────────────────────────────────────────────────────────────────────┘
```

| Section | Content |
|---|---|
| Progress bar | Iteration count, current objective, residual norm ‖f‖ |
| Convergence plot | Dual-axis Objective (left) + Residual norm (right) vs. SLP iteration |
| KPI cards | CI highlighted with EU green H₂ threshold (1.0 kg CO₂/kg H₂) |
| KPI bar chart | All KPIs in one Plotly bar chart |
| Solution Variables | Full `result.x` dict as scrollable table |

**Linear templates** (PEM Electrolysis, P2M): single LP shot — progress bar jumps to 100% immediately.

---

## 1.7 Solver Guide

| Mode | When to use | Speed | Robustness |
|---|---|---|---|
| **SLP (FIXED_LP)** | All linear units; mild non-linearity | ★★★★★ | ★★★ |
| **NLP (NLP_IPOPT)** | Non-linear, well-scaled, SLP stagnated | ★★★★ | ★★★★ |
| **Trust-Region** | Highly non-linear, large Jacobian condition number | ★★ | ★★★★★ |
| **Adaptive** | Unknown difficulty — auto-escalates | ★★★ | ★★★★★ |

```python
from pse_ecosystem.solvers.slp import SLPConfig
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.core.contracts import SolveMode

cfg = SLPConfig(max_iter=50, eps_f=1e-3, use_trust_region=False)
result = Orchestrator(fs, SolveMode.ADAPTIVE, slp_config=cfg).solve()
```

**SLP vs NLP — when to toggle:**
- Use **SLP** first; it is fast and works for ≥90% of templates.
- Switch to **NLP** when SLP returns `MAX_ITER` with residual norm > 1e-2 (the non-linearity is sharp at the current point, and the FD-based L-BFGS-B step will navigate around it).
- Switch to **Trust-Region** when both SLP and NLP return `MAX_ITER` (the problem is highly non-convex or the Jacobian is ill-conditioned near the optimum). The filter/funnel globalisation avoids the Maratos effect.
- **Adaptive** automatically escalates SLP → NLP → Trust-Region on failure; use it when you are unsure.

---

## 1.8 Architecture Reference

```
Layer 1 (UI)      ui/                 — Streamlit app, flowsheet_service.py
Layer 2 (Solver)  solvers/            — SLPDriver, NLPDriver, TrustRegionDriver
Layer 3 (Models)  models/, flowsheets/ — unit physics, port connectivity
core/contracts.py                     — shared dataclasses (all layers import here)
```

**Layer-boundary rules (enforced by tests):**
- Layer 2 **never** imports concrete unit modules from Layer 3.
- `ui/flowsheet_service.py` is the **sole** Layer-1 bridge to Layer-3 factories.
- `test_solvers_do_not_import_concrete_unit_modules` enforces this automatically.

---

## 1.9 Unit Catalog

### Biomass / Gas Cooling

| Unit | is_linear | Physics |
|---|---|---|
| `BiomassStorageHF` | Yes | Drying mass balance (analytical J) |
| `BiomassGasifierHF` | No | WGS + methanation equilibrium (van't Hoff) |
| `WGSReactorHF` | No | CO-shift equilibrium Kp(T) |
| `H2SeparatorPSA` | Yes | Recovery fraction (analytical J) |
| `CoolerHF` | **Yes** | Single-stream gas cooler — fixed T_out (v1.3.0) |

### DAC / Power

| Unit | is_linear | Physics |
|---|---|---|
| `TVSAContactor` | Yes | TVSA DAC contactor (analytical J) |
| `ElectrolyserHF` | Yes | PEM/AEL electrolyser (analytical J) |
| `MethanationReactor` | No | Sabatier equilibrium, analytical J |
| `CHPUnit` | Yes | Combined Heat & Power (analytical J) |

### Reactors

| Unit | is_linear | Physics |
|---|---|---|
| `StoichiometricReactor` | Yes | F_out = F_in + v·ξ (analytical J) |
| `CSTRHF` | No | Arrhenius kinetics + ideal-gas energy balance |
| `PFRHF` | No | ODE integration (scipy BDF) |
| `EquilibriumReactor` | No | van't Hoff Keq + Newton inner solve |
| `GibbsReactor` | No | Gibbs minimisation (scipy SLSQP) |

### Separators

| Unit | is_linear | Physics |
|---|---|---|
| `SeparatorHF` | Yes | Split fractions (analytical J) |
| `FlashVLHF` | No | Antoine K-values + Rachford-Rice + energy balance |
| `DistillationHF` | No | FUG shortcut (Fenske, Underwood, Gilliland) |

### Mixers / Heat Exchangers / Pressure Changers

| Unit | is_linear | Physics |
|---|---|---|
| `MixerHF` | No | Material + ideal-gas energy balance |
| `HeatExchangerNTU` | No | Counter-flow NTU-effectiveness |
| `CoolerHF` | **Yes** | Single-stream gas cooler — fixed T_out |
| `Compressor` | No | Isentropic + efficiency |
| `Valve` | No | Isoenthalpic throttle |
| `Pump` | No | Incompressible isentropic |

---

## 1.10 Troubleshooting

| Symptom | Fix |
|---|---|
| "No LP solver available" | `pip install highspy` or install GLPK |
| "pvlib not installed" | `pip install 'pse_ecosystem[weather]'` |
| "streamlit is required" | `pip install 'pse_ecosystem[gui]'` |
| Template shows INFEASIBLE | Increase Max iterations; try Adaptive solver mode |
| Mermaid diagram blank | Toggle "Use simple Graphviz diagram" (CDN may be blocked) |
| Pyomo W1002 warning | Harmless numerical precision note; result is correct |
| Custom flowsheet: "0 connections" | Check Shared Component Set matches all units; verify From/To dropdowns |
| Live chart doesn't update | Only non-linear templates trigger per-iteration callbacks; linear templates solve in one shot |

---

---

# Part 2 — Manual Assembly Workshop (7-Unit Build)

> **Gold Standard for solver independence:** No hard-coded template. No pre-wired connections.
> You select each unit, set each parameter, and draw each connection by hand — proving the
> Aspen-style Custom Flowsheet builder works for real industrial chains.

## 2.1 Philosophy

Like Aspen Plus, PSE Ecosystem lets you pick unit operations from a dropdown, configure their
parameters, and draw connections between ports. The solver then finds the steady-state operating
point satisfying all mass-balance residuals simultaneously. This section is a guided exercise
you can complete in under 15 minutes.

**The chain:**

```
[1] BiomassStorageHF → [2] BiomassGasifierHF → [3] SeparatorHF (Cyclone)
→ [4] WGSReactorHF → [5] CoolerHF → [6] SeparatorHF (PSA) → [7] Compressor
```

---

## 2.2 Step 1 — Open the Custom Flowsheet Builder

1. Flowsheet Builder page → sector filter: **Custom** → template: **Custom Flowsheet**.
2. **Shared Component Set**: type `H2,CO,CO2,H2O,CH4,N2`.
3. **Number of units**: set to **7**.
4. Click **Add Units**.

---

## 2.3 Step 2 — Configure Each Unit

| # | UI Unit Type | Unit ID | Key Parameters |
|---|---|---|---|
| 1 | `BiomassStorageHF` | `storage` | biomass_type = "Pine Wood", T_preheat_C = 200 |
| 2 | `BiomassGasifierHF` | `gasifier` | T_gasifier_C = 800, gasifying_agent = "Steam" |
| 3 | `SeparatorHF` | `cyclone` | n_outlets = 2 (99% each species → outlet_0) |
| 4 | `WGSReactorHF` | `wgs` | T_wgs_C = 400 |
| 5 | `CoolerHF` | `cooler` | T_out_K = 310 |
| 6 | `SeparatorHF` | `psa` | n_outlets = 2 (85% H₂ → outlet_0) |
| 7 | `Compressor` | `comp` | eta_isentropic = 0.78, P_out_Pa = 5000000 |

Expand each unit expander in turn and set the parameters above. Leave all other fields at defaults.

---

## 2.4 Step 3 — Wire the Connections

| Connection # | From Unit | To Unit |
|---|---|---|
| 1 | `storage` | `gasifier` |
| 2 | `gasifier` | `cyclone` |
| 3 | `cyclone` | `wgs` |
| 4 | `wgs` | `cooler` |
| 5 | `cooler` | `psa` |
| 6 | `psa` | `comp` |

> **Note on T/P mismatches:** When a port with no T/P variables connects to a port with T/P
> (e.g. WGSReactorHF → SeparatorHF), the builder applies a *flow-only fallback* and links only
> the shared `.F_*` component variables. The connection description shows `(flow-only)`. This
> is expected — not an error.

---

## 2.5 Step 4 — Build and Verify

Click **Build & Select**. Success banner:

```
Custom flowsheet built: 7 units, 6 connections.
```

If you see "0 connections": check that all unit IDs are unique, the Shared Component Set includes the syngas species, and all 6 connection From/To pairs are filled.

---

## 2.6 Step 5 — Solve

Navigate to **Solver Monitor** → mode: **SLP** → click **Run Solve**.

Expected: 5–20 SLP iterations. Linear units (storage, cyclone, cooler, PSA) satisfy their balances exactly at each LP step. Non-linear units (gasifier, WGS, compressor) converge iteratively.

---

## 2.7 Validation Answer Key

| Quantity | Basis | Expected |
|---|---|---|
| Storage dry outlet (kg/s) | `F_wet × (1 − MC)` = 1.0 × (1 − 0.17) | **0.83 kg/s** |
| Gasifier C balance closure | n_CO + n_CO₂ + n_CH₄ = n_C_feed | **< 0.1% error** |
| WGS CO conversion X_CO | K_WGS(400 °C) ≈ 8.9 → equilibrium | **60–85%** |
| Cooler outlet flow | F_out = F_in (mass conservation) | **= inlet total** |
| PSA H₂ to outlet_0 | 85% split fraction | **85% of H₂ feed** |
| Compressor P_out | Fixed parameter | **5 MPa** |

---

## 2.8 Programmatic Equivalent

```python
from pse_ecosystem.ui.flowsheet_service import build_custom_flowsheet

SYNGAS_6 = ["H2", "CO", "CO2", "H2O", "CH4", "N2"]
config = {
    "units": [
        {"type": "BiomassStorageHF", "id": "storage", "params": {}},
        {"type": "BiomassGasifierHF", "id": "gasifier",
         "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"}},
        {"type": "SeparatorHF", "id": "cyclone",
         "params": {"components": SYNGAS_6, "n_outlets": 2}},
        {"type": "WGSReactorHF", "id": "wgs", "params": {"T_wgs_C": 400.0}},
        {"type": "CoolerHF", "id": "cooler",
         "params": {"components": SYNGAS_6, "T_out_K": 310.0}},
        {"type": "SeparatorHF", "id": "psa",
         "params": {"components": SYNGAS_6, "n_outlets": 2}},
        {"type": "Compressor", "id": "comp",
         "params": {"components": SYNGAS_6, "P_out_Pa": 5e6}},
    ],
    "connections": [
        {"from_unit": "storage",  "to_unit": "gasifier"},
        {"from_unit": "gasifier", "to_unit": "cyclone"},
        {"from_unit": "cyclone",  "to_unit": "wgs"},
        {"from_unit": "wgs",      "to_unit": "cooler"},
        {"from_unit": "cooler",   "to_unit": "psa"},
        {"from_unit": "psa",      "to_unit": "comp"},
    ],
}
fs = build_custom_flowsheet(config)
print(f"Units: {len(fs.units)}, Connections: {len(fs.connections)}")
# → Units: 7, Connections: 6
```

**Test coverage:** `pytest tests/test_ui_assembly_logic.py -v` (18 tests, all green)

---

---

# Part 3 — Industrial Template Library

The 14 templates are organized into 6 industrial sectors. Select the sector in the Flowsheet Builder
Category dropdown to filter.

---

## 3.1 Hydrogen Production (4 templates)

| Template Key | Display Name | Units | Solver | Notes |
|---|---|---|---|---|
| `hydrogen.electrolysis_only` | PEM Electrolysis | PEMToy | LP (linear) | LCOH + Carbon Intensity KPIs |
| `hydrogen.electrolysis_or_gasification` | PEM + Gasifier (MILP) | PEMToy, GasifierToy | MILP | Technology-selection binary |
| `industrial.green_hydrogen` | Green Hydrogen Hub | PEMToy, MixerHF | LP | H₂ buffer with mixer |
| `biomass.gasification_to_hydrogen` | Biomass → H₂ (Gasification) | BiomassStorageHF, BiomassGasifierHF, WGSReactorHF, H2SeparatorPSA | SLP (3–10 iters) | Full B-HYPSYS chain |

**MILP technology-selection (PEM + Gasifier):**

```python
from pse_ecosystem.ui.flowsheet_service import load_template_with_choices
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.core.contracts import SolveMode

fs, choices = load_template_with_choices(
    "hydrogen.electrolysis_or_gasification", {"h2_demand_kg_per_h": 100.0}
)
result = Orchestrator(fs, SolveMode.FLEXIBLE_MILP, technology_choices=choices).solve()
print(result.technology_selection)   # {'pick_pem': True, 'pick_gasifier': False}
```

---

## 3.2 Biomass Processing (2 templates)

| Template Key | Display Name | Units | Solver | Notes |
|---|---|---|---|---|
| `biomass.gasification_to_hydrogen` | Biomass → H₂ (Gasification) | 4 units | SLP | Also in §3.1 |
| `industrial.grand_challenge_10unit` | Grand Challenge: Biomass → H₂ (10-Unit) | 10 units | SLP | Full industrial chain |

**Grand Challenge template:**

```python
from pse_ecosystem.ui.flowsheet_service import load_template
from pse_ecosystem.solvers.slp import SLPDriver, SLPConfig

fs = load_template("industrial.grand_challenge_10unit", {
    "biomass_feed_kg_s": 1.0,
    "T_gasifier_C": 800.0,
    "T_hts_C": 400.0,
    "T_lts_C": 220.0,
    "H2_recovery": 0.94,
    "P_out_Pa": 5_000_000.0,
})
result = SLPDriver(fs, SLPConfig(max_iter=60, use_trust_region=False)).run()
print(result.kpis["psa.H2_production_kg_h"])
```

10-unit chain:
```
BiomassStorage → Gasifier → Cyclone → HTS-WGS → LTS-WGS →
MoistureSep → CO2Scrubber → PSA → Compressor → H2Polisher
```

---

## 3.3 Power Generation (1 template)

| Template Key | Display Name | Units | Solver | Notes |
|---|---|---|---|---|
| `industrial.gasification_to_power` | Gasification to Power | StoichiometricReactor, Compressor | LP | Syngas compression for turbine |

Basis: CH₄ + CO₂ dry reforming → CO + H₂ → compression to 5 bar.

---

## 3.4 Petrochemicals (2 templates)

| Template Key | Display Name | Units | Solver | Notes |
|---|---|---|---|---|
| `industrial.power_to_methanol` | Power-to-Methanol | StoichiometricReactor, SeparatorHF | LP | CO₂ + 3H₂ → MeOH + H₂O |
| `industrial.syngas_production` | Syngas Production | GasifierToy, SeparatorHF | LP | Gasifier + CO₂ scrubber |

**Power-to-Methanol:**

```python
from pse_ecosystem.ui.flowsheet_service import load_template
from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.solvers.orchestrator import Orchestrator

fs = load_template("industrial.power_to_methanol", {"extent_max": 3.0})
result = Orchestrator(fs, SolveMode.FIXED_LP).solve()
print(result.status, result.kpis)
```

---

## 3.5 Carbon Capture & Utilization (1 template)

| Template Key | Display Name | Units | Solver | Notes |
|---|---|---|---|---|
| `dac.power_to_methane` | Direct Air Capture → Methane (DAC-U) | TVSAContactor, ElectrolyserHF, MethanationReactor | SLP (2 iters) | CO₂ 415 ppm → CH₄ |

**DAC sensitivity sweep (CO₂ capture efficiency vs energy):**

```
η_cap = 0.60 → spec. energy ≈ 455 kWh/tCO₂
η_cap = 0.85 → spec. energy ≈ 420 kWh/tCO₂
η_cap = 0.99 → spec. energy ≈ 411 kWh/tCO₂
```

W_fan is constant (fixed air flow); specific energy improves at higher η_cap because CO₂ output grows faster than the thermal regen penalty.

---

## 3.6 Other Industrial Processes (4 templates)

| Template Key | Display Name | Units | Solver | Notes |
|---|---|---|---|---|
| `small.cstr_flash` | CSTR + Flash | CSTRHF, FlashVLHF | SLP | WGS kinetics + Rachford-Rice |
| `small.compression_train` | Compression Train | Compressor, ShellTubeHX, Valve | LP | 3-unit train |
| `small.mixer_settler` | Mixer + Settler | MixerHF, SeparatorHF | LP | Energy balance mixer + settler |
| `small.distillation` | Distillation Column | DistillationHF | SLP | FUG shortcut, benzene/toluene |

---

## 3.7 Engineering Parameter Reference

All editable parameters in the Flowsheet Builder parameter form:

| Template | Parameter | Default | Unit | Controls |
|---|---|---|---|---|
| All PEM templates | `pem.eta_kg_per_kWh` | 0.018 | kg H₂/kWh | Electrolyser efficiency |
| All PEM templates | `pem.capacity_kW` | 10 000 | kW | Maximum rated power |
| All PEM templates | `pem.electricity_price_per_kWh` | 0.05 | £/kWh | Electricity OPEX rate |
| All PEM templates | `pem.capex_annual_per_kW` | 100 | £/kW/yr | Annualised CAPEX |
| All PEM templates | `pem.grid_carbon_intensity_kg_CO2_per_kWh` | 0.233 | kg CO₂/kWh | Grid emission factor |
| All PEM templates | `h2_demand_kg_per_h` | 100 | kg/h | H₂ production target |
| Power-to-Methanol | `extent_max` | 3.0 | mol/s | Max reaction extent |
| Gasification to Power | `comp.eta_isentropic` | 0.78 | — | Compressor efficiency |
| Gasification to Power | `comp.P_out_Pa` | 500 000 | Pa | Compressor outlet pressure |
| Syngas Production | `h2_demand_kg_per_h` | 200 | kg/h | H₂-rich syngas target |
| Syngas Production | `co2_capture_fraction` | 0.95 | — | CO₂ scrubber removal |
| Biomass templates | `T_gasifier_C` | 800 | °C | Gasifier temperature |
| Biomass templates | `T_wgs_C` | 400 | °C | WGS reactor temperature |
| Biomass templates | `biomass_feed_kg_s` | 1.0 | kg/s | Wet biomass feed rate |
| DAC (P2Methane) | `F_air_mol_s` | 10 000 | mol/s | Ambient air feed flow |
| DAC | `eta_cap` | 0.85 | — | CO₂ capture efficiency |
| DAC | `eta_elec` | 0.70 | — | Electrolyser efficiency (HHV) |
| DAC | `T_rx_K` | 673 | K | Methanation temperature |
| CSTR+Flash | `cstr.volume_m3` | 1.0 | m³ | Reactor volume |
| Compression Train | `hx.U_W_per_m2_K` | 500 | W/m²K | HX overall heat transfer |
| Compression Train | `hx.A_m2` | 10 | m² | HX heat transfer area |

*Cp and K-values are computed from NIST Shomate / Antoine correlations — not user-settable in the UI. See DEVELOPER_GUIDE.md §11 for code-level overrides.*

---

## 3.8 Carbon Intensity KPI

```
CI = (emission_factor × energy_or_feed × operating_hours) / annual_H2_produced
```

| Template | CI definition |
|---|---|
| PEM templates | `grid_carbon_intensity × electricity_kW × 8000 h / annual_H2_kg` |
| Syngas Production | `biomass_carbon_intensity × feed_kg_h × 8000 h / annual_H2_kg` |

**EU green hydrogen threshold: 1.0 kg CO₂/kg H₂.** The UI shows a red/green delta indicator.

Typical values:
- UK grid (2023): CI ≈ 12–13 kg CO₂/kg H₂
- Wind/solar power: CI ≈ 0.3–0.8 kg CO₂/kg H₂
- Biomass gasification (residual): CI ≈ 0.3 kg CO₂/kg H₂

---

---

# Part 4 — Advanced Showcase

## 4.1 Investor Walkthrough Script

**Audience:** Funders / Industrial Partners | **Total time:** 20 minutes

### Pre-Meeting Setup

```powershell
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1
cd "C:\Users\gh00616\OneDrive - University of Surrey\Desktop\PhD Folder\IMP\PSE_ECOSYSTEM"
streamlit run pse_ecosystem/ui/app_streamlit.py
```

### Stage 1 — "The Engine Works" (5 min)

1. Flowsheet Builder → Sector: **Other Industrial Processes** → **"CSTR + Flash (NL)"** → Apply & Select.
2. Solver Monitor → **SLP** → Run Solve.

> *"The linearisation uses an analytically-derived Jacobian — not finite differences. You are seeing exact gradient information from the physics equations."*

> *"The flash unit solves the Rachford-Rice equation:*
> $$\sum_i \frac{z_i (K_i - 1)}{1 + \psi(K_i - 1)} = 0, \qquad K_i = \frac{P_{sat,i}(T)}{P}$$
> *This is the same physics used in Aspen."*

### Stage 2 — "Real-World Scale" (7 min)

1. Sector: **Biomass Processing** → **"Biomass → H₂ (Gasification)"**.
2. Adjust `T_gasifier_C` (800 °C) and `biomass_feed_kg_s` (1.0 kg/s) → Apply & Select.
3. Solver Monitor → Run Solve.

> *"The gasifier solves two coupled equilibrium equations simultaneously:*
> $$K_{WGS}(T) = \frac{n_{CO_2} \cdot n_{H_2}}{n_{CO} \cdot n_{H_2O}}, \qquad \ln K_{met}(T) = \frac{25000}{T} - 26.2$$"*

### Stage 3 — "The Decision Tool" (5 min)

1. Sector: **Hydrogen Production** → **"PEM Electrolysis"** → Apply & Select.
2. Expand **1D Sensitivity Sweep** → parameter: `pem.electricity_price_per_kWh`, Min=0.02, Max=0.15, Points=12 → Run Sweep.

> *"This is the investor's decision curve. LCOH crosses grid parity at a specific electricity price — generated in under 2 seconds."*

### Stage 4 — "The Architecture" (optional, 3 min)

> *"Three strict layers: UI / Solver / Physics. They communicate only via the Handshake Protocol — a typed contract. Replace the solver without touching the physics; replace the UI without touching the solver."*

---

## 4.2 Q&A Preparation

### "Can it handle recycle loops?"
> "Yes — Wegstein tear-stream acceleration. See §4.6."

### "How does this compare to Aspen Plus?"
> "Aspen is proprietary, £30,000+/seat. PSE Ecosystem exposes the full algebraic residual and Jacobian — every equation is inspectable. Analytical Jacobians converge faster on well-initialised problems."

### "What's the IP moat?"
> Three things: **(1)** the three-layer handshake architecture; **(2)** the analytical Jacobian protocol; **(3)** B-HYPSYS corrections — 16 physics defects in the published benchmark corrected."

### "What sectors beyond hydrogen?"
> "Sector-agnostic. Current library: H₂ production, biomass processing, power generation, petrochemicals, DAC. Any process expressible as algebraic equations is a direct extension."

---

## 4.3 Grand Challenge: 10-Unit Biomass → H₂ Validation

**Template key:** `industrial.grand_challenge_10unit` | **Category:** Biomass Processing

### Chain Architecture

```
Unit 1:  BiomassStorageHF   (storage)      — drying
Unit 2:  BiomassGasifierHF  (gasifier)     — thermochemical equilibrium, 800 °C
Unit 3:  SeparatorHF        (cyclone)      — 99% char/ash removal
Unit 4:  WGSReactorHF       (hts)          — High-Temperature Shift, 400 °C
Unit 5:  WGSReactorHF       (lts)          — Low-Temperature Shift, 220 °C
Unit 6:  SeparatorHF        (moisture_sep) — 70% H₂O condensate removal
Unit 7:  SeparatorHF        (co2_scrubber) — 97% CO₂ absorption
Unit 8:  H2SeparatorPSA     (psa)          — 94% H₂ recovery
Unit 9:  Compressor         (h2_comp)      — 50 bar compression
Unit 10: SeparatorHF        (h2_polisher)  — 99.5% final purity
```

### Analytical vs UI Verification

| KPI | Analytical Target | Tolerance |
|---|---|---|
| Gasifier C balance closure | 100.0% | < 0.1% |
| HTS CO conversion | ~75% (K_WGS(673K) ≈ 8.9) | ±10% |
| LTS CO conversion | ~90% of HTS residual | ±10% |
| PSA H₂ recovery | 94.0% (exact linear) | < 0.01% |
| H₂ polisher recovery | 99.5% (exact linear) | < 0.01% |

**Test suite:** `pytest tests/test_grand_challenge.py -v` (9 pass, 1 conditional skip)

---

## 4.4 Known Limitations

| Limitation | Status | Roadmap |
|---|---|---|
| VLE limited to Raoult's Law (Antoine) | Current | Cubic EOS (PR/SRK) v1.4 |
| No recycle loop in gallery templates | Implemented in solver, no demo | Add CSTR-recycle template v1.4 |
| FlashVLHF: Antoine extrapolates above Tc for syngas species | Known — use SeparatorHF instead | Extended EOS |
| IPOPT requires `idaes-pse` install (optional) | Not required for SLP | Documented |
| Biomass template validated T ≥ 650 °C only | Physics-valid constraint | Add T warning in UI |
| 10-unit chain: full convergence needs Adaptive solver | SLP gives LP-feasible iterate | Adaptive integration |

---

## 4.5 Key Equations Reference

### Rachford-Rice (Flash VLE)

$$f(\psi) = \sum_{i=1}^{N_c} \frac{z_i (K_i - 1)}{1 + \psi(K_i - 1)} = 0, \qquad K_i = \frac{P_{sat,i}(T)}{P}$$

### Water-Gas Shift Equilibrium

$$K_{WGS}(T) = \exp\!\left(\frac{4300}{T} - 3.84\right) \qquad \text{(van't Hoff fit, 600–1200 K)}$$

### SLP Linearisation

$$f(x^k) + J(x^k)(x - x^k) = 0, \qquad J_{ij} = \frac{\partial f_i}{\partial x_j}\bigg|_{x^k}$$

### Methanation Equilibrium (Sabatier)

$$K_{Sab}(T) = \frac{K_{met}(T)}{(P/P°)^{-2}}, \quad X_{CO_2} = \frac{K_{Sab}}{1 + K_{Sab}}$$

---

## 4.6 Programmatic Reference

### Case A: 3-Unit Chain (P2M)

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.reactors.stoichiometric_reactor import StoichiometricReactor, StoichiometricParams
from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.core.contracts import SolveMode

components = ["CO2", "H2", "methanol", "water"]
p2m_stoich = {"CO2": [-1.0], "H2": [-3.0], "methanol": [1.0], "water": [1.0]}

heater  = StoichiometricReactor("heater",  components, StoichiometricParams(stoichiometry=p2m_stoich))
reactor = StoichiometricReactor("reactor", components, StoichiometricParams(stoichiometry=p2m_stoich, xi_max=[50.0]))
sep     = SeparatorHF("sep", components, SeparatorHFParams(n_outlets=2))

fs = BaseFlowsheet(name="p2m", units=[heater, reactor, sep])
fs.connect(heater.outlet_port,  reactor.inlet_port)
fs.connect(reactor.outlet_port, sep.inlet_port)

result = Orchestrator(fs, SolveMode.FIXED_LP).solve()
print(result.status, result.iterations)   # CONVERGED, 1
```

### Programmatic `fs.connect()`

```python
from pse_ecosystem.flowsheets.base_flowsheet import Connection

# Flow-only connection (T/P mismatch workaround):
for c in ["H2", "CO", "CO2", "H2O", "CH4", "N2"]:
    fs.connections.append(Connection(
        var_a=f"wgs.shifted_out.F_{c}",
        var_b=f"separator.inlet.F_{c}",
    ))
```

### Recycle Loops

```python
from pse_ecosystem.solvers.slp import SLPConfig, TearStreamConfig

cfg = SLPConfig(
    max_iter=50,
    tear_streams=[TearStreamConfig(var_name="recycle.F_A", connected_to="feed.F_A",
                                   q_min=-5.0, q_max=0.0)],
)
```

### Costing

```python
from pse_ecosystem.models.costing.sslw_costing import cstr_purchase_cost_USD, annualized_capex

cost = cstr_purchase_cost_USD(5.0, material="CS")   # 5 m³ CSTR, CE500 basis
ann  = annualized_capex(cost, lang_factor=5.0, crf=0.10, cepci_now=800.0)
```

### Properties Module

```python
from pse_ecosystem.models.properties.ideal_gas import cp_J_mol_K
from pse_ecosystem.models.properties.vle import K_value

cp = cp_J_mol_K("CO2", 1000.0)             # 54.3 J/mol/K (NIST Shomate)
K  = K_value("benzene", 353.15, 101325.0)  # ~1.0 at normal boiling point
```

---

## 4.7 Flowsheet Merging & Composition

### Merging Two Templates

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.ui.flowsheet_service import load_template

fs_a = load_template("industrial.gasification_to_power")
fs_b = load_template("industrial.green_hydrogen")

fs_merged = BaseFlowsheet(
    name="gasif_plus_pem",
    units=[*fs_a.units, *fs_b.units],
)
for conn in [*fs_a.connections, *fs_b.connections]:
    fs_merged.connections.append(conn)
fs_merged.extra_bounds = {**fs_a.extra_bounds, **fs_b.extra_bounds}
```

### Cross-Flowsheet Connections

```python
comp_unit = next(u for u in fs_a.units if "comp" in u.unit_id)
pem_unit  = next(u for u in fs_b.units if "pem"  in u.unit_id)
fs_merged.connect(comp_unit.outlet_port, pem_unit.inlet_port, description="Syngas to PEM feed")
```

`connect()` raises `ValueError` if ports have different component lists.

---

## 4.8 Adding a Custom Unit

```python
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.core.contracts import StreamPort
import numpy as np

class MyUnit(BaseUnit):
    is_linear = False

    def __init__(self, unit_id, components):
        self.unit_id = unit_id
        self.components = components
        self.inlet_port  = StreamPort(unit_id, "inlet",  components)
        self.outlet_port = StreamPort(unit_id, "outlet", components)

    def variables(self):
        return self.inlet_port.variable_names() + self.outlet_port.variable_names()

    def bounds(self):
        return {v: (0.0, 1e6) for v in self.variables()}

    def residual(self, x):
        F_in  = [x.get(f"{self.unit_id}.inlet.F_{c}",  0.0) for c in self.components]
        F_out = [x.get(f"{self.unit_id}.outlet.F_{c}", 0.0) for c in self.components]
        return np.array(F_out) - np.array(F_in)

    def objective_contribution(self, x):
        return {}
```

Override `linearize(guess)` with an analytical Jacobian for SLP performance.

---

## 4.9 SLP Configuration Reference

```python
SLPConfig(
    max_iter=50,            # maximum SLP iterations
    eps_x=1e-4,             # step-norm convergence tolerance
    eps_f=1e-4,             # residual-norm convergence tolerance
    eps_kpi=1e-3,           # KPI-change convergence tolerance
    use_trust_region=False, # enable adaptive trust region
    trust_region_init=1.0,
    trust_region_min=1e-2,
    trust_region_max=1e2,
    rho_shrink=0.25,
    rho_grow=0.75,
    solver_name=None,       # None → auto (HiGHS > CBC > GLPK)
    verbose=False,
)
```

---

## 2.9 Understanding the Connection Display

After clicking **Build & Select** you will see a banner such as:

```
Custom flowsheet built: 7 units, 6 stream link(s) (33 variable equalities).
```

- **6 stream links** = the number of From→To pairs you drew in the Connections panel.
  This is the number that should match your flowsheet diagram.
- **33 variable equalities** = the number of individual equality constraints the solver
  enforces internally. Each stream link generates one constraint per shared variable
  (one per component flow, plus T and P where both ports include them). For a 6-component
  syngas chain with flow-only connections (no T/P), each link produces 6 equalities:
  6 links × 6 species = 36, minus a few for the Biomass-to-Gasifier link (1 species) ≈ 31–33.

This is expected behaviour and not an error. The solver correctly enforces all variable equalities.

---

## 2.10 Setting an Optimization Objective

The **Objective Function** tab (inside the Flowsheet Builder, alongside the Sensitivity Sweep)
lets you instruct the solver to pursue an economic or process goal — not just find a
feasible point.

### How it works

The LP solver uses three sources for the objective:
1. **Unit-level OPEX** — each unit's `objective_contribution()` returns linear cost coefficients
   (e.g. `{electricity_kW: 400}` for PEMToy, `{biomass_in.F_Biomass: 0.05}` for BiomassGasifier).
   These are always active unless you choose **Feasibility Only**.
2. **`objective_extra`** — additional coefficients set by the Objective Function tab
   (energy penalties, annualised CAPEX, H₂ yield terms).
3. **`force_feasibility`** — when active, the LP objective is set to 0.0, suppressing
   all unit costs. The solver finds any point satisfying the mass/energy balance residuals.

### Objective options

| Mode | LP objective | When to use |
|---|---|---|
| **Feasibility Only** | 0 (pure constraint satisfaction) | Debugging connections; checking mass-balance closes |
| **Minimize OPEX** | Unit feedstock + electricity costs | Cost-optimal operation using built-in unit economics |
| **Minimize Energy** | Shaft work + electrical power × electricity price × annual hours | Reducing compression or electrolysis energy use |
| **Minimize TAC** | OPEX + annualised CAPEX (linear terms only) | Holistic cost; includes capital cost penalty on power vars |
| **Minimize LCOH** | TAC + negative H₂ yield | Levelized cost proxy; exact when H₂ demand is fixed |
| **Maximize H₂ Yield** | −1 × most-downstream H₂ outlet flow | Maximise hydrogen production regardless of cost |

### LCOH and TAC — what's implemented

- **LCOH** [USD/kg H₂] = TAC [USD/yr] / H₂_production [kg/yr]. This is a ratio — not
  directly linearizable. The PSE Ecosystem proxy minimises TAC while simultaneously
  maximising H₂ yield. For fixed-demand flowsheets (`extra_bounds` pins H₂ = target),
  this is mathematically exact (minimising TAC ≡ minimising LCOH).

- **TAC = OPEX + annualised CAPEX.** OPEX contributions come from unit
  `objective_contribution()` (already in LP). Annualised CAPEX is added as a linear term
  for units with linear capex models (e.g. ElectrolyserHF: 700 USD/kW × CRF). For SSLW
  units (Compressor, vessels), capex is non-linear; it is reported as a post-solve KPI
  in the Excel export's Unit Performance sheet.

### Steps

1. Flowsheet Builder → **Objective Function** tab.
2. Select an objective mode.
3. Optionally adjust economic parameters (electricity price, CRF, annual hours) in the
   Advanced section.
4. Click **Apply Objective**.
5. Solver Monitor → **Run Solve**. The convergence chart objective column will be non-zero
   for all modes except Feasibility Only.

*Programmatic equivalent:*
```python
from pse_ecosystem.ui.flowsheet_service import build_objective_extra
fs.objective_extra, fs.force_feasibility = build_objective_extra(
    fs, "Minimize TAC",
    electricity_price_USD_per_kWh=0.05,
    operating_hours=8000.0,
    crf=0.10,
)
```

---

## 2.11 Solve Benchmarks — 7-Unit Chain

Use these benchmarks to choose solver settings for the workshop chain:

| Solver Mode | Max Iter Setting | Progressive Tightening | Expected Status | Typical Iterations |
|---|---|---|---|---|
| **SLP** | 50 | Off | CONVERGED | 8–18 |
| **SLP** | 50 | On | CONVERGED | 12–22 |
| **NLP** | 200 | — | CONVERGED | 20–60 (L-BFGS-B steps) |
| **Trust-Region** | 200 | — | CONVERGED | 15–40 |
| **Adaptive** | 200 | — | CONVERGED | best-of-above |

**Recommended:** SLP with 50 iterations (progressive tightening OFF) is sufficient for this chain.
Enable progressive tightening only if SLP returns `MAX_ITER`.
Increase Max Iterations (slider now goes to 1000) for chains with more non-linear units.

### Per-Unit Property Defaults (used by the Dynamic Parameter Form)

When you select a unit type in the Custom Flowsheet builder, the UI now auto-fills a
parameter form. The defaults for each workshop unit are:

| Step | Unit Type | Parameter | Default | UI Label |
|---|---|---|---|---|
| 1 | `BiomassStorageHF` | biomass_type | "Pine Wood" | Biomass Type |
| 1 | `BiomassStorageHF` | T_preheat_C | 200 °C | Preheat Temperature |
| 2 | `BiomassGasifierHF` | T_gasifier_C | 800 °C | Gasifier Temperature |
| 2 | `BiomassGasifierHF` | gasifying_agent | "Steam" | Gasifying Agent |
| 2 | `BiomassGasifierHF` | P_atm | 1.0 atm | Pressure |
| 3 | `SeparatorHF` (Cyclone) | n_outlets | 2 | Number of Outlets |
| 4 | `WGSReactorHF` | T_wgs_C | 400 °C | WGS Temperature |
| 5 | `CoolerHF` | T_out_K | 310 K | Outlet Temperature |
| 6 | `SeparatorHF` (PSA) | n_outlets | 2 | Number of Outlets |
| 7 | `Compressor` | eta_isentropic | 0.78 | Isentropic Efficiency |
| 7 | `Compressor` | P_out_Pa | 500 000 Pa | Outlet Pressure |

You can edit any value directly in the form before clicking **Build & Select**.

---

*User Manual v1.4.0 — PSE Ecosystem | Private — University of Surrey*
