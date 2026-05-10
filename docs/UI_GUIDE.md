# PSE Ecosystem — UI Quick-Start Guide (v1.0)

**Private — University of Surrey**

For the full page-by-page walkthrough see [`docs/UI_USER_GUIDE.md`](UI_USER_GUIDE.md).

---

## 1. Install & Launch (3 commands)

```powershell
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1
pip install -e ".[solvers,weather,gui]"
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Opens at **http://localhost:8501**.

---

## 2. Five-Minute Tour

| Step | Page | Action |
|---|---|---|
| 1 | **Dashboard** | Check LP Solver = "Available". Browse the template gallery. |
| 2 | **Flowsheet Builder** | Pick category → template → configure parameters → **Apply & Select**. |
| 3 | **GPS Weather** | Enter lat/lon → **Fetch Profiles** → view solar GHI and wind charts. |
| 4 | **Solver Monitor** | Set max iterations → **Run Solve** → inspect convergence + KPIs. |

---

## 3. Engineering Parameter Reference

All editable parameters across templates. Adjusted in the **Flowsheet Builder** parameter form.

| Template | Parameter | Default | Unit | What it controls |
|---|---|---|---|---|
| All PEM templates | `pem.eta_kg_per_kWh` | 0.018 | kg H₂/kWh | Electrolyser efficiency |
| All PEM templates | `pem.capacity_kW` | 10 000 | kW | Maximum rated power |
| All PEM templates | `pem.electricity_price_per_kWh` | 0.05 | £/kWh | Electricity OPEX rate |
| All PEM templates | `pem.capex_annual_per_kW` | 100 | £/kW/yr | Annualised CAPEX rate |
| **All PEM templates** | **`pem.grid_carbon_intensity_kg_CO2_per_kWh`** | **0.233** | **kg CO₂/kWh** | **Grid emission factor** |
| All PEM templates | `h2_demand_kg_per_h` | 100 | kg/h | H₂ production target |
| P2M | `extent_max` | 3.0 | mol/s | Max reaction extent |
| G2P | `comp.eta_isentropic` | 0.78 | — | Compressor isentropic efficiency |
| G2P | `comp.P_out_Pa` | 500 000 | Pa | Compressor outlet pressure |
| Syngas | `h2_demand_kg_per_h` | 200 | kg/h | Syngas production target |
| Syngas | `co2_capture_fraction` | 0.95 | — | CO₂ scrubber removal fraction |
| **Syngas** | **`gasifier.biomass_carbon_intensity_kg_CO2_per_kg`** | **0.03** | **kg CO₂/kg** | **Biomass lifecycle emission factor** |
| CSTR+Flash | `cstr.volume_m3` | 1.0 | m³ | Reactor volume |
| Compression | `comp.eta_isentropic` | 0.75 | — | Compressor efficiency |
| Compression | `hx.U_W_per_m2_K` | 500 | W/m²K | HX overall heat transfer coeff. |
| Compression | `hx.A_m2` | 10 | m² | HX heat transfer area |

**Note:** Cp and K-values are computed from NIST Shomate / Antoine correlations at the solver's operating T and P — they are not user-settable. This preserves thermodynamic consistency.

---

## 4. Carbon Intensity KPI

The **Solver Monitor** highlights the Carbon Intensity (CI) KPI separately when it appears in the results:

```
CI = (emission_factor × energy_or_feed × operating_hours) / annual_H2_produced
```

| Template | CI definition |
|---|---|
| PEM templates | grid_carbon_intensity × electricity_kW × 8000 h / annual_H2_kg |
| Syngas Production | biomass_carbon_intensity × feed_kg_h × 8000 h / annual_H2_kg |

**EU green hydrogen threshold: 1.0 kg CO₂/kg H₂.**  
The UI shows a red/green delta indicator against this value.

Typical values:
- UK grid (2023): CI ≈ 12–13 kg CO₂/kg H₂ (high — use renewable tariff)
- Wind/solar power: CI ≈ 0.3–0.8 kg CO₂/kg H₂ (below threshold)
- Biomass gasification (residual): CI ≈ 0.3 kg CO₂/kg H₂

---

## 5. Custom Flowsheet Walkthrough

1. In **Flowsheet Builder**, select category **Custom** → **Custom Flowsheet**.
2. Set **Number of units** (1–4).
3. For each unit: pick a **type** from the allowlist and enter a short **ID** (e.g. `pem`, `comp`).
4. In the **Connections** panel, confirm which units wire together (outlet → inlet).
5. Click **Build & Select** — the flowsheet is assembled and stored in session state.
6. Go to **Solver Monitor** → **Run Solve**.

**Available unit types:**

| Type | Linear? | Key KPIs |
|---|---|---|
| `PEMToy` | Yes | LCOH, Carbon Intensity |
| `GasifierToy` | No | LCOH, Carbon Intensity |
| `StoichiometricReactor` | Yes | — |
| `MixerHF` | No | — |
| `SeparatorHF` | Yes | — |
| `Compressor` | No | W_shaft, capex |
| `HeatExchangerNTU` | No | Q, effectiveness |

**Tips:**
- Connections only work when both ports have the same component list.
- For complex topologies, build a factory function in `flowsheets/` instead (see Developer Guide in `UI_USER_GUIDE.md`).

---

## 6. Packaging as a Standalone App

```powershell
# Check that PyInstaller and all deps are ready
python scripts/package_app.py --check

# Build (creates dist/pse_ecosystem_ui/)
python scripts/package_app.py --build

# See known issues (Streamlit bootstrap, solver bundling, etc.)
python scripts/package_app.py --info
```

Output: `dist/pse_ecosystem_ui/` folder — copy to target machine and run.

---

## 7. Running All Tests

```powershell
python tests/ui_backend_sync.py    # 8 math accuracy checks
python tests/ui_audit.py           # 15 service + layer checks
python tests/system_audit.py       # 17 system checks
python tests/industrial_audit.py   # 11 physics checks
pytest tests\ -q                   # 107 unit tests
# Total: 158 checks
```

---

## 8. Property Overrides (Code-Level)

The Streamlit UI exposes only *engineering* parameters (flow rates, temperatures, efficiencies). Thermodynamic properties — Shomate Cp/H, Antoine K-values — are computed from NIST data at the solver's operating T and P. This is intentional: exposing raw correlation coefficients in the UI would risk thermodynamic inconsistency (e.g. using methanol Antoine constants with water enthalpy).

### 8a. Overriding unit engineering parameters

Template parameters in **Flowsheet Builder** correspond directly to dataclass fields. You can also pass them programmatically:

```python
from pse_ecosystem.ui.flowsheet_service import load_template

fs = load_template("hydrogen.electrolysis_only", {
    "h2_demand_kg_per_h": 200.0,
    "pem.eta_kg_per_kWh": 0.022,          # advanced-stack efficiency
    "pem.electricity_price_per_kWh": 0.03, # wind PPA tariff
    "pem.grid_carbon_intensity_kg_CO2_per_kWh": 0.05,  # wind grid mix
})
```

All `default_params` keys from `flowsheet_service._REGISTRY` are valid override keys.

### 8b. Adding a new species to ideal-gas enthalpies

Edit `pse_ecosystem/models/properties/ideal_gas.py`. Add a NIST Shomate entry to `_SHOMATE`:

```python
_SHOMATE["ethanol"] = {
    "A": 102.8, "B": -46.69, "C": 9.0, "D": -0.54,
    "E": 0.0, "F": -217.0, "G": 0.0, "H": -168.6,
    "T_range": (298.0, 1500.0),
    "T_ref": 298.15,
}
```

Keys match NIST Webbook format; units are J/(mol·K) for Cp, kJ/mol for H. The new species is immediately available to any HF unit that lists it in its `components` argument.

### 8c. Adding a new species to VLE K-values (Antoine)

Edit `pse_ecosystem/models/properties/vle.py`. Add to `ANTOINE`:

```python
ANTOINE["ethanol"] = {"A": 8.04494, "B": 1554.3, "C": 222.65}  # log10(P/mmHg), T in °C
```

Standard Antoine base-10 form. The species is then usable in `FlashVLHF`, `FlashSL`, `DistillationHF`, and `GibbsReactor`.

### 8d. Custom equation of state via subclassing

To replace the ideal-gas assumption in a single unit without touching the property module:

```python
from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig

class PengRobinsonCSTR(CSTRHF):
    def residual(self, x):
        # compute enthalpy departure with PR EOS here, then call super()
        ...
```

Only `residual()` and optionally `jacobian()` need overriding. The `LinearizedModel` contract
(`linearize()`) is inherited and calls your overridden `residual()` for the FD Jacobian.

**Layer boundary note:** All property edits stay inside `pse_ecosystem/models/properties/` (Layer 3). Neither the Orchestrator nor the SLP driver need to know — they only see the `LinearizedModel` returned by `linearize()`.

---

## 9. Flowsheet Merging / Composition

Two `BaseFlowsheet` objects can be composed into a single larger flowsheet by merging their unit lists and wiring the boundary ports.

### 9a. Merging two flowsheets

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.ui.flowsheet_service import load_template

fs_a = load_template("industrial.gasification_to_power")   # GasifierToy → Compressor
fs_b = load_template("industrial.green_hydrogen")           # PEMToy → MixerHF

# Combine unit lists (no shared units)
fs_merged = BaseFlowsheet(
    name="gasif_plus_pem",
    units=[*fs_a.units, *fs_b.units],
)

# Copy connections from both parent flowsheets
for conn in [*fs_a.connections, *fs_b.connections]:
    fs_merged.connections.append(conn)

# Merge extra_bounds (fs_b's bounds take precedence on conflicts)
fs_merged.extra_bounds = {**fs_a.extra_bounds, **fs_b.extra_bounds}
```

### 9b. Wiring a new cross-flowsheet connection

Use `fs_merged.connect()` to wire a port on a unit from `fs_a` to a port on a unit from `fs_b`:

```python
# Wire compressor outlet → PEM inlet (hypothetical syngas→electrolysis link)
comp_unit = next(u for u in fs_a.units if "comp" in u.unit_id)
pem_unit  = next(u for u in fs_b.units if "pem"  in u.unit_id)

fs_merged.connect(
    comp_unit.outlet_port,
    pem_unit.inlet_port,
    description="Syngas to PEM feed",
)
```

`connect()` generates `Connection` objects — each wiring one scalar port variable to another. It raises `ValueError` if both ports do not share the same component list.

### 9c. Registering a merged flowsheet in the UI

Add the merged template to `flowsheet_service.py`:

```python
# In _REGISTRY list:
TemplateSpec(
    key="industrial.gasif_plus_pem",
    display_name="Gasification + PEM Hub",
    category="Industrial",
    description="Biomass gasification feeding a PEM electrolysis buffer.",
    topology_diagram=("graph LR\n  Feed --> Gasif --> Comp --> PEM --> Out"),
    unit_labels=["GasifierToy", "Compressor", "PEMToy", "MixerHF"],
    default_params={},
)

# In _LOADER_MAP:
"industrial.gasif_plus_pem": _load_gasif_plus_pem,

# Loader function:
def _load_gasif_plus_pem(p: dict):
    fs_a = _load_gasification_to_power(p)
    fs_b = _load_green_hydrogen(p)
    # merge as shown in 9a + 9b
    ...
```

### 9d. Gotchas

| Issue | Fix |
|---|---|
| Port component mismatch | Both ports must list identical components (same strings, same order) |
| `extra_bounds` conflict | `fs_b.extra_bounds` wins in `{**fs_a.extra_bounds, **fs_b.extra_bounds}` — set explicitly if needed |
| KPI name collisions | Unit IDs from both flowsheets must be unique; KPIs are keyed by `unit_id.kpi_name` |
| SLP initial guess | `BaseFlowsheet.initial_guess()` calls `unit.initial_guess()` for all units — ensure each unit provides a sensible midpoint |
