# PSE Ecosystem — UI Guide (v1.2.0)

**Private — University of Surrey**

---

## 1. Install & Launch

```powershell
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1
pip install -e ".[solvers,weather,gui]"
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Opens at **http://localhost:8501**. Requires at least one LP solver — install HiGHS if not present:

```powershell
pip install highspy
```

---

## 2. Five-Minute Tour

| Step | Page | Action |
|---|---|---|
| 1 | **Dashboard** | Check LP Solver = "Available". Browse the 13-template gallery. |
| 2 | **Flowsheet Builder** | Pick category → template → configure parameters → **Apply & Select**. Optionally run a 1D Sensitivity Sweep directly on this page. |
| 3 | **GPS Weather** | Enter lat/lon → **Fetch Profiles** → view solar GHI and wind charts. |
| 4 | **Solver Monitor** | Choose solver mode (SLP / NLP / Trust-Region / Adaptive) → **Run Solve** → watch live convergence + KPIs. |

---

## 3. Page-by-Page Walkthrough

### 3.1 Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚗ PSE Ecosystem                                    v1.0.0          │
│  Private — University of Surrey                                      │
├──────────────┬──────────────┬──────────────┬───────────────────────┤
│  Templates   │  Unit Models │  LP Solver   │  Last Solve           │
│     11       │  16+ HF units│  Available   │  CONVERGED            │
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
│  │ Syngas Production            │ Industrial │ GasifierToy, SepHF │ │
│  │ CSTR + Flash                 │ Small      │ CSTRHF, FlashVLHF  │ │
│  │ ...                          │ ...        │ ...                │ │
│  └──────────────────────────────┴────────────┴────────────────────┘ │
│                                                                      │
│  Last Solve Result                                                   │
│  ✓ Converged in 3 iteration(s)  |  Objective: 9.62e+05              │
└─────────────────────────────────────────────────────────────────────┘
```

| Card | Meaning |
|---|---|
| Templates | Number of registered flowsheet templates |
| Unit Models | "16+ HF units" — the Layer-3 model library |
| LP Solver | "Available" if HiGHS/GLPK detected, else an install hint |
| Last Solve | Status of the most recent solver run |

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
│  + H2O, then split.  │  Stream Connections                          │
│  Fully linear.       │  From            To        Description       │
│                      │  Reactor outlet  Sep inlet  Rxr → Sep        │
│                      │                                              │
│                      │  Parameters                                  │
│                      │  ┌──────────────────────────────────────┐   │
│                      │  │ ▼ Flowsheet                          │   │
│                      │  │   Extent Max   [  3.0            ]   │   │
│                      │  │         [ Apply & Select ]           │   │
│                      │  └──────────────────────────────────────┘   │
│                      │  ✓ Template selected. Go to Solver Monitor.  │
└──────────────────────┴──────────────────────────────────────────────┘
```

1. **Filter by Category** — All / Custom / Hydrogen / Industrial / Small.
2. **Select Template** — description appears below the list.
3. **View Topology** — Mermaid diagram renders the flowsheet. Toggle "Use simple Graphviz diagram" for offline environments.
4. **Configure Parameters** — grouped by unit in collapsible expanders.
5. **Apply & Select** → navigate to **Solver Monitor** to run, or use the Sensitivity Sweep (see §5a).

For the **Custom Flowsheet** option see §6 below.

### §5a. 1D Sensitivity Sweep (new in v1.2.0)

Expand **"1D Parameter Sensitivity Sweep"** at the bottom of the Flowsheet Builder page (below the parameter form). This does NOT require navigating to the Solver Monitor.

| Control | Description |
|---|---|
| Sweep parameter | Numeric template parameter to vary (auto-populated from the template) |
| Min / Max value | Range of the sweep |
| Points | Number of solve calls (3–30) |
| **Run Sweep** | Runs N × `SolveMode.FIXED_LP` solves; plots all KPIs vs the swept parameter |

Results appear as a live Plotly multi-trace chart and a data table. Useful for CO₂ capture efficiency sensitivity, reactor temperature sweeps, etc.

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
│                        [ Fetch Profiles ]                            │
├──────────────────────────────────────────────────────────────────────┤
│  Peak GHI (W/m²)  │  Mean Wind (m/s)  │  Solar Hours / Year         │
│      833          │      7.11         │       4 380                 │
├──────────────────────────────────────────────────────────────────────┤
│  [ Solar GHI ]  [ Wind Speed ]         (interactive Plotly tabs)    │
└─────────────────────────────────────────────────────────────────────┘
```

Default site: University of Surrey, Guildford (51.24°N, −0.59°E, 68 m).  
Profiles are stored in session state and persist while the browser tab is open.

---

### 3.4 Solver Monitor

```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 Solver Monitor                                                   │
│  Template: Syngas Production   Key: industrial.syngas_production     │
├─────────────────────────────────────────────────────────────────────┤
│  ▼ Solver Settings                                                   │
│    Max iterations  [=============================·····] 50          │
│    Step tolerance  [ 1.00e-04 ]                                      │
│    Solver Mode                                                       │
│    ● SLP (fast, LP-based)                                            │
│    ○ NLP (scipy L-BFGS-B, full residual)                             │
│    ○ Trust-Region Filter (robust, filter globalization)              │
│    ○ Adaptive (SLP → NLP → Trust-Region cascade)                     │
│    ☐ Verbose solver output                                           │
│                          [ Run Solve ]                               │
├─────────────────────────────────────────────────────────────────────┤
│  [████████████████████░░░░░] Iteration 2 / 3 | Obj: 9.618e+05 | ‖f‖: 0.031
│                                                                      │
│  SLP — Live Convergence (updates each iteration)                     │
│  Obj  1e6 ┤●                                                         │
│           │╲                                                         │
│       5e5 ┤ ╲●────────────────  — Objective                         │
│       ‖f‖     ╲●  - - - - - - -  - - Residual norm                  │
│           └──────────────────── iteration                            │
├─────────────────────────────────────────────────────────────────────┤
│  ✓ Converged in 3 iteration(s)  |  Objective: 9.619e+05             │
│                                                                      │
│  CI — gasifier (kg CO₂/kg H₂)   0.280   -0.720 vs 1.0 threshold ✓  │
│                                                                      │
│  h2_produced  │  lcoh    │  capex_USD  │  opex_per_year             │
│    ...        │  ...     │  ...        │  ...                       │
│                                                                      │
│  [KPI bar chart]        [Solution Variables table]                   │
└─────────────────────────────────────────────────────────────────────┘
```

**During solve (non-linear templates):** progress bar + per-iteration caption + live dual-axis chart update on every SLP step.  
**After solve:** live chart clears; full-resolution convergence chart, KPI cards, KPI bar chart, and solution variables table appear.  
**Linear templates** (PEM, P2M): single LP shot — progress bar jumps to 100 % immediately.

| Section | Content |
|---|---|
| Progress bar + caption | Iteration count, current objective, residual norm ‖f‖ |
| Convergence plot | Dual-axis: Objective (left) + Residual norm (right) vs. SLP iteration |
| CI KPI cards | Carbon Intensity highlighted with EU green H₂ threshold (1.0 kg CO₂/kg H₂) |
| Other KPI cards | Rows of 4 metric cards |
| KPI bar chart | All KPIs in one Plotly bar chart |
| Solution Variables | Full `result.x` dict as a scrollable table |
| Technology Selection | JSON badge (MILP mode only) showing active technologies |

---

## 4. Template Reference (13 templates)

| Key | Name | Category | Units | Solver |
|---|---|---|---|---|
| `hydrogen.electrolysis_only` | PEM Electrolysis | Hydrogen | PEMToy | LP (linear) |
| `hydrogen.electrolysis_or_gasification` | PEM + Gasifier | Hydrogen | PEMToy, GasifierToy | MILP |
| `industrial.green_hydrogen` | Green Hydrogen Hub | Industrial | PEMToy, MixerHF | LP |
| `industrial.power_to_methanol` | Power-to-Methanol | Industrial | StoichiometricReactor, SeparatorHF | LP |
| `industrial.gasification_to_power` | Gasification to Power | Industrial | StoichiometricReactor, Compressor | LP |
| `industrial.syngas_production` | Syngas Production | Industrial | GasifierToy, SeparatorHF | LP |
| `biomass.gasification_to_hydrogen` | Biomass → H₂ (B-HYPSYS) | Hydrogen | BiomassStorageHF, BiomassGasifierHF, WGSReactorHF, H2SeparatorPSA | SLP (3–10 iters) |
| **`dac.power_to_methane`** | **Direct Air Capture → Methane** | **Industrial** | **TVSAContactor, ElectrolyserHF, MethanationReactor** | **SLP (2 iters)** |
| `custom.user_flowsheet` | Custom Flowsheet | Custom | User-defined (1–4 units) | LP |
| `small.cstr_flash` | CSTR + Flash | Small | CSTRHF, FlashVLHF | SLP |
| `small.compression_train` | Compression Train | Small | Compressor, ShellTubeHX, Valve | LP |
| `small.mixer_settler` | Mixer + Settler | Small | MixerHF, SeparatorHF | LP |
| `small.distillation` | Distillation Column | Small | DistillationHF | SLP |

---

## 5. Engineering Parameter Reference

All editable parameters. Adjusted in the **Flowsheet Builder** parameter form.

| Template | Parameter | Default | Unit | What it controls |
|---|---|---|---|---|
| All PEM templates | `pem.eta_kg_per_kWh` | 0.018 | kg H₂/kWh | Electrolyser efficiency |
| All PEM templates | `pem.capacity_kW` | 10 000 | kW | Maximum rated power |
| All PEM templates | `pem.electricity_price_per_kWh` | 0.05 | £/kWh | Electricity OPEX rate |
| All PEM templates | `pem.capex_annual_per_kW` | 100 | £/kW/yr | Annualised CAPEX rate |
| All PEM templates | `pem.grid_carbon_intensity_kg_CO2_per_kWh` | 0.233 | kg CO₂/kWh | Grid emission factor |
| All PEM templates | `h2_demand_kg_per_h` | 100 | kg/h | H₂ production target |
| P2M | `extent_max` | 3.0 | mol/s | Max reaction extent |
| G2P | `comp.eta_isentropic` | 0.78 | — | Compressor isentropic efficiency |
| G2P | `comp.P_out_Pa` | 500 000 | Pa | Compressor outlet pressure |
| Syngas | `h2_demand_kg_per_h` | 200 | kg/h | Syngas production target |
| Syngas | `co2_capture_fraction` | 0.95 | — | CO₂ scrubber removal fraction |
| Syngas | `gasifier.biomass_carbon_intensity_kg_CO2_per_kg` | 0.03 | kg CO₂/kg | Biomass lifecycle emission factor |
| CSTR+Flash | `cstr.volume_m3` | 1.0 | m³ | Reactor volume |
| Compression | `comp.eta_isentropic` | 0.75 | — | Compressor efficiency |
| Compression | `hx.U_W_per_m2_K` | 500 | W/m²K | HX overall heat transfer coeff. |
| Compression | `hx.A_m2` | 10 | m² | HX heat transfer area |
| **DAC (Power-to-Methane)** | `F_air_mol_s` | 10 000 | mol/s | Ambient air feed flow |
| DAC | `eta_cap` | 0.85 | — | CO₂ capture efficiency (0–1) |
| DAC | `eta_elec` | 0.70 | — | Electrolyser efficiency (HHV basis) |
| DAC | `T_rx_K` | 673 | K | Methanation reactor temperature (400 °C default) |

**Note:** Cp and K-values are computed from NIST Shomate / Antoine correlations — not user-settable via the UI. See §9 for code-level overrides.

---

## 6. Carbon Intensity KPI

```
CI = (emission_factor × energy_or_feed × operating_hours) / annual_H2_produced
```

| Template | CI definition |
|---|---|
| PEM templates | grid_carbon_intensity × electricity_kW × 8000 h / annual_H2_kg |
| Syngas Production | biomass_carbon_intensity × feed_kg_h × 8000 h / annual_H2_kg |

**EU green hydrogen threshold: 1.0 kg CO₂/kg H₂.** The UI shows a red/green delta indicator.

Typical values:
- UK grid (2023): CI ≈ 12–13 kg CO₂/kg H₂ (use renewable tariff to reduce)
- Wind/solar power: CI ≈ 0.3–0.8 kg CO₂/kg H₂
- Biomass gasification (residual): CI ≈ 0.3 kg CO₂/kg H₂

---

## 7. Custom Flowsheet

1. In **Flowsheet Builder**, select category **Custom** → **Custom Flowsheet**.
2. Set **Number of units** (1–4).
3. For each unit: pick a **type** from the allowlist and enter a short **ID** (e.g. `pem`, `comp`).
4. In the **Connections** panel, confirm which units wire together (outlet → inlet).
5. Click **Build & Select** — the flowsheet is stored in session state.
6. Go to **Solver Monitor** → **Run Solve**.

**Available unit types** (grouped by process category):

| Category | Type | Linear? | Key KPIs |
|---|---|---|---|
| Feed/Product | `PEMToy` | Yes | LCOH, Carbon Intensity |
| Feed/Product | `GasifierToy` | No | LCOH, Carbon Intensity |
| Reactors | `StoichiometricReactor` | Yes | — |
| Reactors | `MethanationReactor` | No | CH4_yield_pct, heat_released_kW |
| Separation/DAC | `SeparatorHF` | Yes | — |
| Separation/DAC | `TVSAContactor` | **Yes** | co2_capture_rate_tonne_per_day, specific_energy_kWh_per_tCO2 |
| Heat Exchange | `HeatExchangerNTU` | No | Q, effectiveness |
| Power/CHP | `ElectrolyserHF` | **Yes** | H2_production_kg_h, efficiency_pct |
| Power/CHP | `CHPUnit` | **Yes** | W_elec_kW, Q_process_kW, power_to_heat_ratio |
| Mixing | `MixerHF` | No | — |
| Pressure Changers | `Compressor` | No | W_shaft, capex |

**Tips:**
- Port phase and species must match — `BaseUnit.validate_connection()` raises `PortCompatibilityError` at `connect()` time, not at solve time.
- For complex topologies, build a factory function in `flowsheets/` and register it (see §11).

---

## 8. Packaging as a Standalone App

```powershell
python scripts/package_app.py --check    # pre-flight: Python version, PyInstaller, deps
python scripts/package_app.py --build    # creates dist/pse_ecosystem_ui/
python scripts/package_app.py --info     # known issues (Streamlit bootstrap, solver bundling)
```

Output: `dist/pse_ecosystem_ui/` folder — copy to target machine and run. See `scripts/package_app.py` for Nuitka alternative and macOS/Linux notes.

---

## 9. Running All Tests

```powershell
pytest tests\ -q                   # 107 pytest unit tests
python tests/ui_audit.py           # 15 service + layer checks
python tests/system_audit.py       # 17 system checks
python tests/industrial_audit.py   # 11 physics checks
```

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| "No LP solver available" | `pip install highspy` or install GLPK |
| "pvlib not installed" | `pip install 'pse_ecosystem[weather]'` |
| "streamlit is required" | `pip install 'pse_ecosystem[gui]'` |
| Template shows INFEASIBLE | Increase Max iterations in Solver Settings |
| Mermaid diagram blank | Toggle "Use simple Graphviz diagram" (CDN may be blocked) |
| Pyomo W1002 warning | Harmless numerical precision note; result is correct |
| Live chart doesn't update | Only non-linear templates (Syngas, G2P, CSTR+Flash) trigger the callback; linear templates solve in one shot |

---

## 11. Developer Guide — Adding a Template

1. **Create the flowsheet factory** in `pse_ecosystem/flowsheets/` (Layer 3). Follow patterns in `pse_ecosystem/flowsheets/industrial/`.

2. **Register in `flowsheet_service.py`** (Layer 1 bridge):
   - Add a `TemplateSpec` to `_REGISTRY`.
   - Write `_load_<name>(p: dict)` with deferred Layer-3 imports.
   - Add the key → loader mapping to `_LOADER_MAP`.

3. **Verify** with the UI audit:
   ```powershell
   python tests/ui_audit.py
   ```

4. **Test convergence** programmatically:
   ```python
   from pse_ecosystem.ui.flowsheet_service import load_template
   from pse_ecosystem.solvers.orchestrator import Orchestrator
   from pse_ecosystem.core.contracts import SolveMode
   fs = load_template("your.template.key", {})
   r = Orchestrator(fs, SolveMode.FIXED_LP).solve()
   print(r.status, r.kpis)
   ```

---

## 12. Property Overrides (Code-Level)

The UI exposes only engineering parameters. Thermodynamic properties (Shomate Cp/H, Antoine K-values) are computed from NIST data at the solver's operating T and P — exposing raw coefficients in the UI would risk thermodynamic inconsistency.

### 12a. Overriding engineering parameters programmatically

```python
from pse_ecosystem.ui.flowsheet_service import load_template

fs = load_template("hydrogen.electrolysis_only", {
    "h2_demand_kg_per_h": 200.0,
    "pem.eta_kg_per_kWh": 0.022,
    "pem.electricity_price_per_kWh": 0.03,
    "pem.grid_carbon_intensity_kg_CO2_per_kWh": 0.05,
})
```

All `default_params` keys from `flowsheet_service._REGISTRY` are valid override keys.

### 12b. Adding a new species to ideal-gas enthalpies

Edit `pse_ecosystem/models/properties/ideal_gas.py`, add to `_SHOMATE`:

```python
_SHOMATE["ethanol"] = {
    "A": 102.8, "B": -46.69, "C": 9.0, "D": -0.54,
    "E": 0.0, "F": -217.0, "G": 0.0, "H": -168.6,
    "T_range": (298.0, 1500.0),
    "T_ref": 298.15,
}
```

NIST Webbook format; units are J/(mol·K) for Cp, kJ/mol for H. Immediately available to any HF unit listing the species in `components`.

### 12c. Adding a new species to VLE K-values (Antoine)

Edit `pse_ecosystem/models/properties/vle.py`, add to `ANTOINE`:

```python
ANTOINE["ethanol"] = {"A": 8.04494, "B": 1554.3, "C": 222.65}  # log10(P/mmHg), T in °C
```

Usable in `FlashVLHF`, `FlashSL`, `DistillationHF`, and `GibbsReactor`.

### 12d. Custom EOS via subclassing

```python
from pse_ecosystem.models.reactors.cstr_hf import CSTRHF

class PengRobinsonCSTR(CSTRHF):
    def residual(self, x):
        # add PR enthalpy departure, then call super()
        ...
```

Only `residual()` (and optionally `jacobian()`) need overriding. `linearize()` is inherited and calls your overridden `residual()` for the FD Jacobian.

**Layer boundary:** all property edits stay in `models/properties/` (Layer 3) — the Orchestrator and SLP driver only see `LinearizedModel`.

---

## 13. Flowsheet Merging / Composition

### 13a. Merging two flowsheets

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

# fs_b's bounds take precedence on conflicts
fs_merged.extra_bounds = {**fs_a.extra_bounds, **fs_b.extra_bounds}
```

### 13b. Wiring a cross-flowsheet connection

```python
comp_unit = next(u for u in fs_a.units if "comp" in u.unit_id)
pem_unit  = next(u for u in fs_b.units if "pem"  in u.unit_id)

fs_merged.connect(
    comp_unit.outlet_port,
    pem_unit.inlet_port,
    description="Syngas to PEM feed",
)
```

`connect()` raises `ValueError` if ports have different component lists.

### 13c. Registering a merged flowsheet in the UI

```python
# flowsheet_service.py — _REGISTRY
TemplateSpec(
    key="industrial.gasif_plus_pem",
    display_name="Gasification + PEM Hub",
    category="Industrial",
    description="Biomass gasification feeding a PEM electrolysis buffer.",
    topology_diagram="graph LR\n  Feed --> Gasif --> Comp --> PEM --> Out",
    unit_labels=["GasifierToy", "Compressor", "PEMToy", "MixerHF"],
    default_params={},
)

# _LOADER_MAP
"industrial.gasif_plus_pem": _load_gasif_plus_pem,
```

### 13d. Gotchas

| Issue | Fix |
|---|---|
| Port component mismatch | Both ports must list identical components (same strings, same order) |
| `extra_bounds` conflict | Set explicitly; `{**fs_a, **fs_b}` gives fs_b precedence |
| KPI name collisions | Unit IDs from both flowsheets must be unique |
| SLP initial guess | Ensure each unit's `initial_guess()` returns a sensible midpoint |
