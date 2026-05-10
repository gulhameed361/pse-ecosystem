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
