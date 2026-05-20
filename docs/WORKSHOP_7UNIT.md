# 7-Unit Aspen-Style Workshop — Biomass → H₂

**Version:** 1.5.2 | **Date:** 2026-05-20 | **Status:** Canonical Workshop (synchronized with v1.5.2)

> Step-by-step build of the validated 7-unit biomass-to-hydrogen chain using the
> Custom Flowsheet builder. Use this file as the answer key: the input matrices
> and expected KPIs below are reproduced from the test fixture
> `tests/test_ui_assembly_logic.py::SEVEN_UNIT_CONFIG` and the symbolic
> derivations in `THEORY_REFERENCE.md` §11.

---

## 1. Chain Topology

```
[1] BiomassStorageHF
        │  dry biomass (Pine Wood, MC = 0.17)
        ▼
[2] BiomassGasifierHF        (steam-gasification, 800 °C)
        │  raw syngas + char/ash
        ▼
[3] SeparatorHF (Cyclone)    (99 % particulate removal)
        │  clean syngas
        ▼
[4] WGSReactorHF             (400 °C, K_WGS ≈ 8.9, X_CO ≈ 0.75)
        │  shifted syngas (H₂-enriched)
        ▼
[5] CoolerHF                 (T_out = 310 K)
        │  cool gas
        ▼
[6] SeparatorHF (PSA proxy)  (H₂ split = 0.85, others = 0.05)
        │  high-purity H₂ stream
        ▼
[7] Compressor               (P_out = 5 MPa, η_is = 0.78)
        │
        ▼
     H₂ product
```

Shared component set: `H2, CO, CO2, H2O, CH4, N2` (6 species).

---

## 2. Per-Unit Input Matrix

| # | Unit Type             | Unit ID    | Key Parameters                                   |
|---|-----------------------|------------|--------------------------------------------------|
| 1 | `BiomassStorageHF`    | `storage`  | (defaults; Pine Wood feedstock, MC = 0.17)       |
| 2 | `BiomassGasifierHF`   | `gasifier` | `T_gasifier_C = 800.0`, `gasifying_agent = Steam`|
| 3 | `SeparatorHF`         | `cyclone`  | `components = [H2,CO,CO2,H2O,CH4,N2]`, `n_outlets = 2` |
| 4 | `WGSReactorHF`        | `wgs`      | `T_wgs_C = 400.0`                                |
| 5 | `CoolerHF`            | `cooler`   | `components = [...]`, `T_out_K = 310.0`          |
| 6 | `SeparatorHF`         | `psa`      | `components = [...]`, `n_outlets = 2`            |
| 7 | `Compressor`          | `comp`     | `components = [...]`, `P_out_Pa = 5e6`           |

Connections (sequential, one outlet per unit):

```
storage → gasifier → cyclone → wgs → cooler → psa → comp
```

UI headline: **7 units, 6 connection(s).**
Internal port-variable equalities: **33** (see `THEORY_REFERENCE.md` §11.8 for the exact breakdown — the final `psa → comp` link contributes 8 equalities because both ports carry T and P).

### Port Translation Layer

The 7-unit chain crosses a physical phase boundary: Unit 1 (`BiomassStorageHF`) exposes
a **1-species solid stream** (`dry_out.F_Biomass`), while all downstream units handle
a **6-species syngas mixture** (`H2, CO, CO2, H2O, CH4, N2`).

The connection `storage → gasifier` is a 1-to-1 exact match because
`gasifier.biomass_in_port` is also a 1-species solid port. The gasifier
*internally* converts the 1-component Biomass feed into a 6-component syngas outlet.
No translation layer is needed for the standard chain.

**Zero-fill padder (v1.5.2)** — if you build a *non-standard* path that directly
connects a 1-species storage outlet to a 6-species inlet (e.g. `storage → cyclone`
without the gasifier), the assembler now applies an automatic zero-fill padder instead
of skipping the connection:

- Species present in both ports are wired with equality constraints.
- Species present only in the inlet are pinned to zero via `extra_equalities`.
- A non-fatal warning is recorded and displayed in the UI under the connection table.

This allows topologically incomplete flowsheets to be explored without a hard crash,
while the non-zero warning cues the user that a phase-conversion unit is missing.

---

## 3. UI Walkthrough — Build It Step by Step

1. **Open** the app → **Flowsheet Builder** page.
2. In the template selector pick **"Custom — User-defined"**.
3. **Shared component set:** type `H2, CO, CO2, H2O, CH4, N2`.
4. **Number of units:** `7`.
5. For each unit expander (Unit 1 … Unit 7):
   - Pick the **Type** from row 2 of the matrix above.
   - The **Unit ID** dropdown re-seeds when you change the Type — pick the suggested slug (`storage`, `gasifier_1`, etc.) or choose *custom…* to type the canonical id from the matrix.
   - Set the parameters listed in the matrix (defaults are already pre-filled).
6. **Connections:** the assembler defaults to a sequential chain (`Unit 1 → Unit 2 → … → Unit 7`). Leave the dropdowns as-is.
7. Click **Build & Select**. The success banner should read **"7 units, 6 connection(s)"** with the internal equality count underneath.
8. (Optional, recommended) Switch to the **Objective Function** sub-tab and pick **Maximize H₂ Yield** → click **Apply Objective**.
9. Switch to the **Solver Monitor** page. The active objective should mirror at the top.
10. Solver Mode: leave on **Adaptive (SLP → NLP → Trust-Region cascade)**; ensure **Progressive tightening** is checked (it is by default in v1.4.0).
11. **Max iterations:** 200 is plenty for this chain; raise to 600+ only if convergence stalls.
12. Click **Run Solve**. Watch the live residual / objective chart.
13. After convergence, click **⬇ Download Results (XLSX)** to export the 3-sheet ledger (Stream Table / Unit Performance / Optimization Summary).

---

## 4. Theoretical Answer Key

For 1.0 kg/s wet Pine Wood feed (Moisture content 0.17 → 0.83 kg/s dry):

| Quantity                                  | Symbol             | Expected value           | Source                                    |
|-------------------------------------------|--------------------|--------------------------|-------------------------------------------|
| Dry biomass to gasifier                   | Ḟ_dry              | 0.83 kg/s                | `THEORY_REFERENCE.md` §11.1               |
| Gasifier outlet H₂ (steam-gasification)   | ṅ_H₂,gas           | ≈ 0.022 kmol/s           | §11.2 (element balance + K_WGS at 1073 K) |
| Cyclone H₂ split to clean syngas (Unit 3) | s_H₂               | 0.99                     | §11.3                                     |
| WGS CO conversion at 673 K                | X_CO               | ≈ 0.75                   | §11.4 (K_WGS(673) ≈ 8.9)                  |
| Cooler outlet temperature                 | T_out              | 310 K (fixed parameter)  | §11.5                                     |
| PSA H₂ enrichment split                   | s_H₂,PSA           | 0.85 to outlet_0         | §11.6                                     |
| Compressor outlet (P_out / P_in)^((γ−1)/γ)| (P_r)^0.286        | ≈ 3.35                   | §11.7 (γ ≈ 1.4 mixture)                   |
| Compressor outlet temperature             | T_out,comp         | ≈ 1243 K (multi-species) | §11.7                                     |
| Total connection equalities (LP)          | n_eq               | 33                       | §11.8                                     |
| User-visible connection count             | n_streams          | 6                        | Builder display                           |

H₂ overall yield depends on the gasifier element balance, the WGS conversion, and the PSA split. Treat this column as the analytical reference; small deviations (< 2 %) from solver output are expected because the LP linearises the equilibrium constraints.

---

## §3 Financial Results Interpretation (v1.5.0.dev)

This section walks through configuring and reading the Project Economics
output for the 7-unit biomass → H₂ chain.

### Step 1 — Set the Technoeconomic objective

1. Load the 7-unit flowsheet in the Custom Builder (use `SEVEN_UNIT_CONFIG`
   from `tests/test_ui_assembly_logic.py` as the reference).
2. Navigate to **Flowsheet Builder → Objective Function**.
3. Select tier: **Technoeconomic**.
4. Select objective: **Minimize LCOH (Levelized Cost of H₂)**.
5. In the "Project Economics" expander set:
   - Plant life: 20 years
   - WACC: 8%
   - Electricity price: 0.05 USD/kWh
   - Annual operating hours: 8 000 h/yr
   - Biomass price: 60 USD/tonne
6. Click **Apply Objective**.

### Step 2 — Run the solve

On the Solver Monitor page, select **SLP (Fixed LP)** and click **Run Solve**.
The solver minimises `TAC + (-1) × F_H2_outlet`, the LCOH proxy.

### Step 3 — Download and read the Excel report

| Sheet | Key result |
|---|---|
| Stream Table | All unit port variables in SI units |
| Unit Performance | Per-unit KPIs — look for `Y_H2_kg_per_h` on the PSA, `duty_kW` on the Cooler, `W_shaft_kW` on the Compressor |
| Optimization Summary | Converged / iterations / objective value |
| Bound Saturation | Any variable at a non-physics bound (empty = clean solve) |
| **Project Economics** | LCOH [USD/kg H₂], NPV, IRR, CRF, TAC |

### Step 4 — Understanding the KPI feed to Project Economics

The "Project Economics" sheet reads three KPI keys from `SolveResult.kpis`:

| KPI key | Source unit | Meaning |
|---|---|---|
| `capex_annual_USD` | Units that override `capex()` + EconomicEngine | Annualised installed CAPEX [USD/yr] |
| `opex_annual_USD` | `objective_contribution()` total | Annual operating cost [USD/yr] |
| `h2_kg_per_s` | PSA or most-downstream H₂ unit | Net H₂ production rate [kg/s] |

If these keys are absent from `kpis`, the corresponding financial rows will
show 0 or NaN. For units without a `capex()` override (e.g., a simple
`MixerHF`), their CAPEX contribution is zero; add SSLW correlations via
`EquipmentScalingRule` if a cost estimate is needed (see `DEVELOPER_GUIDE.md §12`).

### Typical financial outputs for the reference 7-unit case

The values below are indicative for the default parameters above.
Your run may differ depending on solver convergence and flowsheet parameters.

| Metric | Indicative range |
|---|---|
| LCOH | 2–8 USD/kg H₂ (process-dependent) |
| NPV | Negative if feedstock costs dominate |
| IRR | `nan` when NPV < 0 at all positive rates |
| TAC | Dominated by biomass feedstock cost for steam-gasification routes |

---

## 5. Common Issues

- **"Connection skipped: missing port"** — the flow-only fallback engaged because two adjacent units exposed different port-variable counts. Fine for this chain; the link is still established on the shared species flows.
- **Solver stalls past iteration 150** — turn **Progressive tightening** off if you suspect the loose-stage tolerances are masking a residual, or raise the iteration ceiling (1500 max in v1.4.0).
- **"Inconsistent component set"** — every unit's `components` parameter must equal the shared component list. The Cyclone, Cooler, PSA, and Compressor matrices above all spell out the same 6-species list explicitly to prevent drift.

---

## 6. Reproducing the Workshop Programmatically

The canonical configuration is encoded in
[`tests/test_ui_assembly_logic.py`](../tests/test_ui_assembly_logic.py)
as the `SEVEN_UNIT_CONFIG` dict (lines 21–58). Re-run the workshop end-to-end
without the UI:

```python
from pse_ecosystem.ui.flowsheet_service import build_custom_flowsheet
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.core.contracts import SolveMode
from tests.test_ui_assembly_logic import SEVEN_UNIT_CONFIG

fs = build_custom_flowsheet(SEVEN_UNIT_CONFIG)
result = Orchestrator(fs, SolveMode.ADAPTIVE).solve()
print(result.status, result.objective)
```

---

---

## Step 8 — Industrial Safety Assessment (Industrial Persona, v1.5.0)

After the solve converges, switch the sidebar toggle to **Industrial** to see the
Safety Margin table on the Solver Monitor page.

### ASME Wall Thickness — Compressor [7]

The PSA hydrogen outlet is compressed from ≈ 5 bar to ≈ 70 bar. Using the default
vessel radius of R = 0.5 m and SA-516-70 carbon steel (S = 138 MPa, E = 1.0):

$$t = \frac{P \cdot R}{S \cdot E - 0.6\,P}
    = \frac{70 \times 10^5 \times 0.5}{138 \times 10^6 - 0.6 \times 70 \times 10^5}
    \approx \frac{3.5 \times 10^6}{133.8 \times 10^6}
    \approx 26.2 \text{ mm}$$

Status: **OK** (26.2 mm >> 3 mm minimum; note that radius_source = "default"
because Compressor has no `vessel_radius_m` parameter — size confirmed by design).

### Flammability Check — BiomassGasifierHF [2]

Syngas outlet composition (approximate): H₂ = 28 mol%, CO = 33 mol%, CO₂ = 21 mol%,
CH₄ = 4 mol%, H₂O = 14 mol%.

Flammable species after excluding H₂O and CO₂: H₂ = 0.43 (renorm), CO = 0.51, CH₄ = 0.06.

$$\text{LFL}_\text{mix} = \frac{1}{0.43/4.0 + 0.51/12.5 + 0.06/5.0}
    \approx \frac{1}{0.108 + 0.041 + 0.012} = \frac{1}{0.161} \approx 6.2 \text{ vol\%}$$

Mixture flammable fraction = 0.65 (65 mol% of stream is combustible) → well within
the flammable range → status **WARNING** (margin_to_LFL = 6.2 − 65 = −58.8 vol%).
This is expected: the gasifier outlet IS a fuel stream. The warning is informational;
appropriate piping isolation and inerting procedures apply per site ATEX/NEC assessment.

---

*Workshop v1.5.0 — PSE Ecosystem | Private — University of Surrey*
