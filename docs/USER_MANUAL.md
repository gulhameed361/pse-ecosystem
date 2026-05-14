# PSE Ecosystem — User Manual

**Version:** 1.2.1 | **Date:** 2026-05-14

---

## 1. Getting Started

### Installation

```powershell
# Activate the project venv (outside OneDrive)
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1

# Install in editable mode with all extras (includes Streamlit + Plotly)
pip install -e ".[solvers,weather,gui,blackbox]"
```

### Launching the Streamlit UI (v1.2.1)

```powershell
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Opens a 4-page app at **http://localhost:8501**:

| Page | What it does |
|---|---|
| **Dashboard** | System status, LP solver check, 13-template gallery |
| **Flowsheet Builder** | Select template, view Mermaid topology, configure parameters. Built-in 1D Sensitivity Sweep. Custom flowsheet assembler. |
| **GPS Weather** | Fetch site-specific solar GHI + wind profiles via pvlib |
| **Solver Monitor** | Solver mode selector (SLP / NLP / Trust-Region / Adaptive) → live convergence → KPI cards |

See [`docs/UI_GUIDE.md`](UI_GUIDE.md) for a full page-by-page walkthrough.

### Verify Installation

```powershell
# UI audit — 15 checks covering service bridge, templates, layer boundaries
python tests/ui_audit.py

# Regression baseline — must show 17/17 passed
python tests/system_audit.py

# Full industrial test suite
python tests/industrial_audit.py

# Pytest suite
pytest tests/ -v
```

---

## 2. Pre-Built Flowsheet Templates

v1.2.0 ships 13 templates. Each can be loaded via the Flowsheet Builder UI or directly in Python:

```python
from pse_ecosystem.ui.flowsheet_service import load_template
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.core.contracts import SolveMode

fs = load_template("dac.power_to_methane", {"F_air_mol_s": 10000.0, "T_rx_K": 673.0})
result = Orchestrator(fs, SolveMode.FIXED_LP).solve()
print(result.status, result.kpis)
# → converged in 2 SLP iterations; KPIs: co2_capture_rate_tonne_per_day, CH4_production_mol_s, ...
```

| Template key | Process | Key units | Solver |
|---|---|---|---|
| `industrial.green_hydrogen` | PEM → H₂ buffer | PEMToy, MixerHF | LP |
| `industrial.power_to_methanol` | CO₂ + 3H₂ → MeOH | StoichiometricReactor, SeparatorHF | LP |
| `industrial.gasification_to_power` | Syngas + compression | StoichiometricReactor, Compressor | LP |
| `biomass.gasification_to_hydrogen` | Drying → gasification → WGS → PSA | BiomassStorageHF, BiomassGasifierHF, WGSReactorHF, H2SeparatorPSA | SLP |
| **`dac.power_to_methane`** | **TVSA DAC + electrolysis + Sabatier** | **TVSAContactor, ElectrolyserHF, MethanationReactor** | **SLP (2 iters)** |

For all 13 templates see [UI_GUIDE.md §4](UI_GUIDE.md#4-template-reference-13-templates).

For the MILP technology-selection template:

```python
from pse_ecosystem.ui.flowsheet_service import load_template_with_choices

fs, choices = load_template_with_choices(
    "hydrogen.electrolysis_or_gasification", {"h2_demand_kg_per_h": 100.0}
)
result = Orchestrator(fs, SolveMode.FLEXIBLE_MILP,
                      technology_choices=choices).solve()
print(result.technology_selection)   # {'pick_pem': True, 'pick_gasifier': False}
```

---

## 2b. Solver Modes (v1.2.0+)

```python
from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig

cfg = SLPConfig(max_iter=50, eps_f=1e-3)

# SLP (default — fast LP subproblems)
result = Orchestrator(fs, SolveMode.FIXED_LP, slp_config=cfg).solve()

# Full NLP (scipy L-BFGS-B with Jacobian from unit.linearize())
result = Orchestrator(fs, SolveMode.NLP_IPOPT, slp_config=cfg).solve()

# Trust-Region Filter/Funnel (Eason & Biegler 2016)
result = Orchestrator(fs, SolveMode.TRUST_REGION, slp_config=cfg).solve()

# Adaptive cascade: SLP → NLP → Trust-Region
result = Orchestrator(fs, SolveMode.ADAPTIVE, slp_config=cfg).solve()
```

| Mode | When to use |
|---|---|
| `FIXED_LP` | Default — fast, handles 90 % of flowsheets |
| `NLP_IPOPT` | Non-linear, poorly initialised, SLP stagnated |
| `TRUST_REGION` | Highly non-linear, large Jacobian condition number |
| `ADAPTIVE` | Unknown difficulty — auto-escalates on convergence failure |

---

## 3. Building a Flowsheet with `fs.connect()`

### Concept

Every HF unit exposes `inlet_port` and `outlet_port` attributes (instances of
`StreamPort`).  A `StreamPort` is a pure name-generator — it knows nothing
about values, only about variable naming conventions:

```
cstr.outlet.F_CO   from StreamPort("cstr", "outlet", ["CO","H2O",...]).F("CO")
cstr.outlet.T      from StreamPort("cstr", "outlet").T()
cstr.outlet.P      from StreamPort("cstr", "outlet").P()
```

`fs.connect(port_a, port_b)` generates one `Connection` equality constraint
per variable: `cstr.outlet.F_CO == flash.inlet.F_CO`, etc.

### Worked Example

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.reactors.cstr_hf import CSTRHF, CSTRHFParams, ReactionConfig
from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams

components = ["CO", "H2O", "CO2", "H2"]
species_vle = ["CO2", "H2"]   # species with Antoine data

rxn = ReactionConfig(
    stoichiometry={"CO": -1, "H2O": -1, "CO2": 1, "H2": 1},
    k0=1e4, Ea_J_per_mol=50_000,
    reaction_orders={"CO": 1.0, "H2O": 1.0},
    delta_H_J_per_mol=-41_000,    # WGS reaction (exothermic)
)
cstr  = CSTRHF("cstr",  components, CSTRHFParams(reactions=[rxn], volume_m3=2.0))
flash = FlashVLHF("flash", components, FlashVLHFParams(species_vle=species_vle))

fs = BaseFlowsheet(name="wgs_process", units=[cstr, flash])
fs.connect(cstr.outlet_port, flash.inlet_port, description="reactor to separator")

# Fix inlet conditions
fs.extra_bounds["cstr.inlet.F_CO"]  = (2.0, 2.0)
fs.extra_bounds["cstr.inlet.F_H2O"] = (2.0, 2.0)
fs.extra_bounds["cstr.inlet.T"]     = (700.0, 700.0)
fs.extra_bounds["cstr.inlet.P"]     = (101325.0, 101325.0)
fs.extra_bounds["cstr.Q"]           = (0.0, 0.0)   # adiabatic

from pse_ecosystem.solvers.slp import SLPConfig, SLPDriver
result = SLPDriver(fs, SLPConfig(max_iter=40, verbose=True)).run()
print(result.status, result.x)
```

### Chaining Multiple Units

```python
fs.connect(cstr.outlet_port,  flash.inlet_port,  description="CSTR to Flash")
fs.connect(flash.vapor_port,  sep.inlet_port,    description="Flash vapor to Sep")
```

---

## 4. Properties Module

### Ideal Gas Properties

```python
from pse_ecosystem.models.properties.ideal_gas import (
    cp_J_mol_K, enthalpy_J_mol, mixture_cp_J_mol_K, gamma
)

cp = cp_J_mol_K("CO2", 1000.0)       # 54.3 J/mol/K (NIST Shomate)
h  = enthalpy_J_mol("H2O", 500.0)   # includes formation enthalpy

flows = {"CO2": 2.0, "N2": 8.0}     # mol/s
Cp_mix = mixture_cp_J_mol_K(flows, T_K=600.0, basis="molar_flow")
```

**Available species:** H2, O2, N2, CO, CO2, CH4, H2O.
Coefficients from NIST WebBook, validated to <1% vs published tables.

### Adding a New Species

1. Add entry to `SHOMATE` dict in `ideal_gas.py` (A, B, C, D, E, F, H
   from NIST WebBook, Shomate equation tab).
2. Add MW to `MW` dict.
3. Add standard formation enthalpy to `H_REF_298` (= H field × 1000 J/mol).
4. Optionally add Antoine constants to `ANTOINE` in `vle.py`.

### VLE Properties

```python
from pse_ecosystem.models.properties.vle import K_value, rachford_rice, bubble_T

K = K_value("benzene", 353.15, 101325.0)   # ~1.0 at normal boiling point

import numpy as np
z = np.array([0.5, 0.5])
K_arr = np.array([K_value("benzene", 360.0, 101325.0),
                   K_value("toluene", 360.0, 101325.0)])
V_frac = rachford_rice(z, K_arr)          # returns NaN if single-phase

T_bub = bubble_T(z, 101325.0, ["benzene", "toluene"], T_guess=370.0)
```

---

## 5. Unit Catalog

### Reactors

| Unit | is_linear | Physics |
|---|---|---|
| `StoichiometricReactor` | Yes | F_out = F_in + v*xi (analytical J) |
| `CSTRHF` | No | Arrhenius kinetics + ideal-gas energy balance |
| `PFRHF` | No | ODE integration (scipy BDF) — generic reactions |
| `EquilibriumReactor` | No | van't Hoff Keq + Newton inner solve |
| `GibbsReactor` | No | Gibbs minimization (scipy SLSQP) + element balances |

### Separators

| Unit | is_linear | Physics |
|---|---|---|
| `FlashVLHF` | No | Antoine K-values + Rachford-Rice + energy balance |
| `FlashSL` | No | Solubility-limited dissolution (softmin) |
| `DistillationHF` | No | FUG shortcut: Fenske + Underwood + Gilliland-Molokanov |
| `SeparatorHF` | Yes | Split fractions (analytical J) |

### Mixers / Heat Exchangers / Pressure Changers

| Unit | is_linear | Physics |
|---|---|---|
| `MixerHF` | No | Material + ideal-gas energy balance |
| `HeatExchangerNTU` | No | Counter-flow NTU-effectiveness |
| `ShellTubeHX` | No | Corrected LMTD + F-factor (1-2 pass) |
| `HeatExchanger1D` | No | N-element analytical NTU solution |
| `Valve` | No | Isoenthalpic (ideal gas: T_out = T_in), Cv flow |
| `Pump` | No | Isentropic liquid pump |
| `Compressor` | No | Isentropic compressor + efficiency |

---

## 6. Recycle Handling

Declare recycle tear streams via `TearStreamConfig` in `SLPConfig`.
Wegstein acceleration is applied after each LP solve.

```python
from pse_ecosystem.solvers.slp import SLPConfig, TearStreamConfig

cfg = SLPConfig(
    max_iter=50,
    tear_streams=[
        TearStreamConfig(
            var_name="recycle.F_A",   # tear variable
            connected_to="feed.F_A",  # reconnection point
            q_min=-5.0,               # Wegstein damping bounds
            q_max=0.0,
        ),
    ],
)
```

| q value | Behaviour |
|---------|-----------|
| 0.0 | Direct substitution (safe, slow) |
| -5 to 0 | Wegstein acceleration (faster) |
| < -10 | May overshoot — use with caution |

The Wegstein state resets at the start of every `SLPDriver.run()` call.

---

## 7. Costing Guide

```python
from pse_ecosystem.models.costing.sslw_costing import (
    cstr_purchase_cost_USD, hx_purchase_cost_USD, annualized_capex
)

# Purchase cost of 5 m3 CS CSTR at CE500 basis (~year 2001 USD)
cost = cstr_purchase_cost_USD(5.0, material="CS")

# Annualise: installed cost * CRF (lang=5, rate=10%, CEPCI_now=800)
ann = annualized_capex(cost, lang_factor=5.0, crf=0.10, cepci_now=800.0)
```

CAPEX is reported as a KPI (`result.kpis["cstr:capex_USD"]`), not in the LP
objective.  OPEX (variable cost) enters the objective via `objective_contribution()`.

---

## 8. SLP Configuration Guide

```python
SLPConfig(
    max_iter=50,           # maximum SLP iterations
    eps_x=1e-4,            # step-norm convergence tolerance
    eps_f=1e-4,            # residual-norm convergence tolerance
    eps_kpi=1e-3,          # KPI-change convergence tolerance
    use_trust_region=False, # enable adaptive trust region
    trust_region_init=1e3,
    trust_region_min=10.0,
    trust_region_max=1e6,
    rho_shrink=0.1,        # shrink TR when rho < rho_shrink
    rho_grow=0.9,          # grow TR when rho > rho_grow
    solver_name="glpk",    # "glpk", "cbc", "highs"
    verbose=True,
)
```

---

## 9. Adding a Custom Unit

```python
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.core.contracts import StreamPort
import numpy as np

class MyUnit(BaseUnit):
    unit_id = "my"
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
        # f(x) = 0 at the operating point. Return numpy array shape (m,).
        F_in  = [x.get(f"{self.unit_id}.inlet.F_{c}",  0.0) for c in self.components]
        F_out = [x.get(f"{self.unit_id}.outlet.F_{c}", 0.0) for c in self.components]
        return np.array(F_out) - np.array(F_in)  # pass-through

    def objective_contribution(self, x):
        return {}   # no cost contribution
```

The base class `linearize()` builds a finite-difference Jacobian automatically.
Override with an analytical version for performance.

---

## 10. CompositeUnit — Hierarchical Flowsheet Composition (v1.2.1)

`CompositeUnit` wraps a `BaseFlowsheet` as a single `BaseUnit`, allowing hierarchical process decomposition. A sub-process (e.g. a gas-cleaning train) can be exposed to a parent flowsheet as an atomic unit.

```python
from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit
from pse_ecosystem.ui.flowsheet_service import load_template

# Wrap the DACU template as a sub-unit in a larger flowsheet
inner_fs = load_template("dac.power_to_methane", {"F_air_mol_s": 5000.0})
super_unit = CompositeUnit(
    unit_id="dacu",
    inner_flowsheet=inner_fs,
    exposed_inputs=["tvsa.air_in.F_Air"],      # parent can drive this
    exposed_outputs=["meth.product_out.F_CH4"], # parent reads this
)
```

The parent SLP solves the outer problem; `CompositeUnit.residual()` runs an inner SLP to solve the sub-flowsheet at each outer iteration. The Adaptive solver cascade is recommended when using composite units.

**In the UI:** Enable the "Add a built-in template as a super-unit" checkbox in the Custom Flowsheet assembler to wrap any registered template as a `CompositeUnit`.

---

## 11. Layer Architecture

```
Layer 1 (UI)      themes/, ui/           — Streamlit app, flowsheet_service.py, CLI
Layer 2 (Solver)  solvers/               — SLP engine, LP/MILP builders
Layer 3 (Models)  models/, flowsheets/   — unit physics, port connectivity
```

**Rules:**
- Layer 2 **must never** import concrete unit modules from Layer 3.
- Layer 3 may import from `core/` (contract surface) only.
- `ui/flowsheet_service.py` is the **sole** Layer-1 module authorised to import
  from Layer-3 factories — all imports are deferred inside loader functions.
- `ui/app_streamlit.py` imports only from `flowsheet_service`, `solvers/`, and `core/`.
- The test `test_solvers_do_not_import_concrete_unit_modules` in
  `tests/test_slp_convergence.py` and the layer checks in `tests/ui_audit.py`
  enforce boundaries automatically.

**Cross-layer communication:**
- Layer 2 → Layer 3: via `PrimalGuess` (linearization request)
- Layer 3 → Layer 2: via `LinearizedModel` and `UnitResponse`
- Layer 1 → Layer 3: via `flowsheet_service.load_template()` only
- `CompositeUnit` is the only sanctioned reverse call (deferred import)

---

*End of User Manual v0.3.0*
