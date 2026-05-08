# User Manual

> A practical guide for academics, supervisors, and industry partners
> who want to *use* the PSE Ecosystem platform without reading the
> source. For the maths see [`THEORY_REFERENCE.md`](THEORY_REFERENCE.md);
> for code-level extension see [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md).

---

## 1. What This Platform Is (and Isn't)

### 1.1 The three-layer idea, in one paragraph

The platform is organised in three layers. The **Application Layer**
lets you pick a *theme* (Hydrogen for v0) and an *application* (e.g.
electrolysis, gasification), then choose between fixed-technology or
flexible-technology optimisation modes. The **Decision Layer** is a
Pyomo-based solver that handles LP and MILP problems and falls back on
Successive Linear Programming (SLP) when units are non-linear. The
**Knowledge Layer** is a library of unit models — toy in v0, ML-backed
later — that supply both their physics (residual equations) and the
gradients the solver needs.

### 1.2 When this tool helps you (and when it doesn't)

**Helpful for:**
- Preliminary techno-economic comparison of hydrogen routes.
- Teaching: built-in flowsheets with toggles for parameters.
- Rapid scenario sweeps (electricity price, demand, technology mix).
- Reproducible studies — runs are deterministic given inputs.

**Not (yet) a replacement for:**
- Detailed unit simulation (Aspen Plus, gPROMS, DWSIM).
- Heat-and-material balances at the level Aspen produces.
- Equilibrium / kinetics modelling.
- Dynamic / unsteady simulation.

### 1.3 v0 capability snapshot

- Two unit models: linear toy PEM electrolyser, mildly non-linear toy
  gasifier.
- Two flowsheets: PEM-only (Mode 1 demo) and PEM-vs-gasifier (Mode 2 demo).
- LP solve in one iteration when all units are linear; SLP iteration
  for non-linear models; MILP for technology choice.
- KPIs: annual H₂, OPEX, CAPEX, LCOH per unit.
- CLI entry point. **No web UI yet** — that lands in v1.

---

## 2. Getting Started

### 2.1 Python and a virtual environment

You need Python 3.10 or newer. The recommended layout (especially on
Windows with OneDrive-synced project folders) is to keep the venv
**outside** OneDrive:

```powershell
# Windows (PowerShell)
python -m venv $HOME\.venvs\pse_ecosystem
& $HOME\.venvs\pse_ecosystem\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python -m venv ~/.venvs/pse_ecosystem
source ~/.venvs/pse_ecosystem/bin/activate
```

### 2.2 Cloning the (private) repo

The repository is private. You'll need either a GitHub invitation or a
direct copy from the founder. Once you have it:

```bash
cd path/to/PSE_ECOSYSTEM
```

### 2.3 Installing the package

With the venv activated:

```bash
pip install -e ".[dev,solvers]"
```

This installs:
- The `pse_ecosystem` package itself (editable, so your changes are
  picked up live).
- `numpy`, `pyomo` — core dependencies.
- `pytest`, `pytest-cov` — for the test suite.
- `highspy` — the HiGHS LP/MILP back-end (no system install needed).

### 2.4 Sanity check

```bash
pytest
python examples/electrolysis_v0.py --mode 1 --demand 100
python examples/electrolysis_v0.py --mode 2 --demand 80
```

You should see 8 tests pass and two solved cases printed. If anything
fails, see [`DEVELOPER_GUIDE.md` §7.3](DEVELOPER_GUIDE.md#73-running-tests-inside-the-venv).

---

## 3. The Hydrogen Theme

### 3.1 What "Theme" means

A *theme* is a domain area with its own library of unit models and
pre-built flowsheets. Hydrogen is the only theme in v0; ammonia, methanol,
and CCS are on the roadmap.

### 3.2 Applications shipped in v0

| Application | Mode | What it does |
|---|---|---|
| `electrolysis_only` | 1 | One PEM electrolyser meets a fixed H₂ demand. Reports LCOH and electricity use. |
| `electrolysis_or_gasification` | 2 | MILP picks PEM, gasifier, or both at minimum total annual cost. Reports the chosen mix and per-route LCOH. |

### 3.3 The toy PEM electrolyser

Models a PEM stack as a fixed-efficiency device: hydrogen output is a
constant ratio of electrical input.

| Parameter | Default | Units | Meaning |
|---|---|---|---|
| `eta_kg_per_kWh` | 0.018 | kg H₂ / kWh | Conversion efficiency (≈ 55 kWh/kg, optimistic-modern) |
| `capacity_kW` | 10 000 | kW | Installed electrical capacity |
| `electricity_price_per_kWh` | 0.05 | £/kWh | Flat tariff |
| `capex_annual_per_kW` | 100 | £/kW/yr | Annualised CAPEX |
| `operating_hours_per_year` | 8 000 | h/yr | Capacity factor surrogate |

What's modelled: linear capacity → output relation, fixed CAPEX, OPEX
proportional to electricity. **Not** modelled: load-dependent efficiency,
electricity-price profiles, ramping, degradation. See
[`THEORY_REFERENCE.md` §3](THEORY_REFERENCE.md#3-toy-pem-electrolyser--unit-model)
for the equations.

### 3.4 The toy gasifier

Models a gasification island as a single block with a quadratic yield
curve in feed throughput, plus a stoichiometric steam requirement.

| Parameter | Default | Units | Meaning |
|---|---|---|---|
| `a` | 0.10 | kg H₂ / kg feed | Linear yield coefficient |
| `b` | 1.0 × 10⁻⁷ | kg H₂ / (kg feed)² | Quadratic loss term |
| `c` | 0.5 | kg steam / kg feed | Stoichiometric ratio |
| `feed_max_kg_per_h` | 50 000 | kg/h | Capacity |
| `feed_price_per_kg` | 0.05 | £/kg | Biomass cost |
| `steam_price_per_kg` | 0.02 | £/kg | Steam cost |
| `capex_annual_GBP` | 5 000 000 | £/yr | Annualised CAPEX |
| `operating_hours_per_year` | 8 000 | h/yr | Capacity factor surrogate |

The quadratic `−b · feed²` term acts as a stand-in for off-design
losses — yield-per-tonne falls as throughput grows. See
[`THEORY_REFERENCE.md` §4](THEORY_REFERENCE.md#4-toy-gasifier--unit-model).

### 3.5 Default parameters table at a glance

```
PEM defaults                 Gasifier defaults
  η      = 0.018 kg/kWh        a    = 0.10 kg H₂/kg feed
  cap    = 10 000 kW           b    = 1e-7 kg H₂/(kg feed)²
  £elec  = 0.05 £/kWh          c    = 0.5  kg steam/kg feed
  CAPEX  = 100 £/kW/yr         feed_max = 50 000 kg/h
  hrs    = 8 000 h/yr          £feed = 0.05 £/kg
                               £steam= 0.02 £/kg
                               CAPEX = 5 000 000 £/yr
                               hrs   = 8 000 h/yr
```

### 3.6 Overriding defaults

Both `PEMToyParams` and `GasifierToyParams` are dataclasses. Override
fields you care about:

```python
from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only

cheap_grid = PEMToyParams(electricity_price_per_kWh=0.03)
flowsheet = make_electrolysis_only(h2_demand_kg_per_h=100.0, pem_params=cheap_grid)
```

---

## 4. Choosing a Mode

### 4.1 Mode 1 — Fixed Technology (LP)

You decide *which* technology will meet the demand; the optimiser
decides the operating point.

- **Solver:** LP. If every unit in the flowsheet is linear (e.g.
  PEM-only), the SLP driver short-circuits to a single Pyomo solve.
- **Use it when:** the technology choice is already made, and you want
  best-in-class operating conditions, or you want to benchmark a
  specific route.

### 4.2 Mode 2 — Flexible Choice (MILP)

You provide a list of *candidate* technologies, each with a binary
on/off decision and an annualised fixed cost. The MILP picks the mix.

- **Solver:** MILP at the linearisation point. If the chosen mix is
  all-linear, you get the answer in one shot. If a non-linear unit is
  selected, the platform refines operations with SLP on the fixed
  topology (sequential MILP → SLP decomposition).
- **Use it when:** comparing routes, sizing a portfolio, or testing
  whether a new technology displaces an existing one.

### 4.3 Decision tree

```
Are you comparing technologies?
├─ No  → Mode 1
│        Run with the technology you've committed to.
│
└─ Yes → Mode 2
         Define one TechnologyChoice per candidate.
         Inspect result.technology_selection to see which won.
```

### 4.4 Behaviour when units are non-linear

- **Mode 1, all linear units:** 1 LP iteration. Status `converged`.
  Message: *"Linear flowsheet solved in a single LP iteration."*
- **Mode 1, ≥1 non-linear unit:** SLP loop runs until all three
  convergence criteria (step, residual, KPI) are met. Typically 3–10
  iterations for the toy gasifier.
- **Mode 2, MILP picks all-linear mix:** 1 MILP solve. Message:
  *"MILP solved as a single shot (all selected units linear)."*
- **Mode 2, MILP picks any non-linear unit:** MILP solve, then SLP
  refines the operating point on the fixed topology. Message:
  *"MILP selected technology mix; SLP refined operations to convergence
  on the fixed topology."*

---

## 5. Running a Study

### 5.1 The CLI

After `pip install -e .`, the entry point is on your `$PATH` as
`pse-ecosystem` (or invoke it as `python examples/electrolysis_v0.py`).

```bash
pse-ecosystem --theme hydrogen --application electrolysis_only --mode 1 --demand 100
pse-ecosystem --theme hydrogen --application electrolysis_or_gasification --mode 2 --demand 80
```

| Flag | Default | Notes |
|---|---|---|
| `--theme` | `hydrogen` | Choices come from the theme registry. |
| `--application` | `electrolysis_only` | Must exist in the chosen theme. |
| `--mode` | `1` | `1` (LP/SLP) or `2` (MILP→SLP). |
| `--demand` | `100.0` | Hydrogen demand in kg/h. |
| `--verbose` | off | Print SLP iteration log to stderr. |

Output is JSON on stdout — easy to pipe into `jq`, store, or post-process.

### 5.2 The Python entry point

`examples/electrolysis_v0.py` is a friendlier human-readable variant of
the CLI: same flags, prettier output. Use this when iterating
interactively.

### 5.3 Verbose mode — the per-iteration log

```bash
python examples/electrolysis_v0.py --mode 1 --demand 100 --verbose
```

You'll see one line per SLP iteration with objective, step norm,
residual norm, and trust-region radius. Useful for diagnosing
"why didn't it converge?" cases.

### 5.4 Programmatic use

```python
from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
    make_electrolysis_or_gasification,
)
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig

flowsheet, choices = make_electrolysis_or_gasification(h2_demand_kg_per_h=80.0)
orch = Orchestrator(
    flowsheet=flowsheet,
    mode=SolveMode.FLEXIBLE_MILP,
    technology_choices=choices,
    slp_config=SLPConfig(verbose=True),
)
result = orch.solve()
print(result.status, result.objective, result.technology_selection)
```

---

## 6. Interpreting Results

### 6.1 The `SolveResult` object

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | `converged`, `max_iter`, `infeasible`, `unbounded`, or `numerical_error` |
| `mode` | enum | `mode_1` or `mode_2` (echo of input) |
| `iterations` | int | LP / SLP iterations performed |
| `objective` | float | Annualised total cost (£/yr) at the optimum |
| `x` | dict | Variable values at the optimum, keyed by `unit_id.varname` |
| `kpis` | dict | Aggregated KPIs across units |
| `technology_selection` | dict | Mode-2 only: `{tech_name: bool}` |
| `history` | list | Per-iteration log (verbose mode populates this) |
| `message` | str | One-line plain-English summary |

### 6.2 LCOH (£/kg H₂)

Per the toy unit definitions:

```
LCOH = (annual_capex + annual_opex) / annual_h2
```

with each term computed by the unit's `kpis()` method. Sanity bands for
toy defaults at full utilisation:

| Route | Toy default LCOH | Industry benchmark range (informational) |
|---|---|---|
| PEM electrolysis | ~£4–5 / kg H₂ | £3–8 / kg (varies enormously with electricity price) |
| Biomass gasification | depends on demand | £2–6 / kg |

The toy values **are not industry-validated** — they are deliberately
round numbers to make the architecture testable. Don't quote them in a
report.

### 6.3 Annual H₂ / OPEX / CAPEX

- `<unit>.annual_h2_kg`: hourly H₂ output × `operating_hours_per_year`.
- `<unit>.annual_opex_GBP`: hourly OPEX × hours; PEM only counts
  electricity, gasifier counts feed + steam.
- `<unit>.annual_capex_GBP`: PEM = `capex_annual_per_kW × capacity_kW`,
  gasifier = `capex_annual_GBP` directly.

### 6.4 Reading `technology_selection` in Mode 2

Each entry is the value of the binary at the optimum:

```json
{"pick_pem": true, "pick_gasifier": false}
```

If a binary is `False`, that unit's flow variables in `result.x` will
be 0 (or near 0, modulo solver tolerances). Don't divide by them when
computing per-route metrics.

### 6.5 Diagnosing common outcomes

| `status` | `iterations` | What it usually means |
|---|---|---|
| `converged` | 1 | Linear short-circuit fired (Mode 1, all linear). |
| `converged` | 2–10 | Standard SLP convergence on a non-linear unit. |
| `converged` | 1, mode 2, "MILP solved as a single shot" | All selected units are linear. |
| `converged` | k+1 (mode 2) | MILP picked a non-linear mix; SLP refined for k iterations. |
| `max_iter` | 50 (default) | SLP didn't converge — bump `max_iter` or tune `eps_*` |
| `infeasible` | 0 | Demand cannot be met by any feasible operating point. Check bounds and capacity. |
| `infeasible` | k>0 | Trust region drove the LP infeasible at minimum radius. Set `use_trust_region=False` or relax bounds. |

### 6.6 Emissions reporting (placeholder for v1)

The contract surface already has room for emissions: any unit's
`kpis()` can return an `emissions_kg_co2_per_h` field, and the
aggregator will sum them. v0 ships **no emissions accounting** because
the toy units don't model carbon intensity.

In v1 we will add:
- An emissions factor on the PEM `electricity_price_per_kWh` partner
  (kg CO₂ / kWh).
- Gasifier feedstock emissions (biomass: counted as net-zero by
  convention or +ve for fossil), process emissions, optional CCS toggle.
- A "carbon price" multiplier so emissions feed into the LCOH-equivalent
  objective.

---

## 7. Worked Examples

The numbers below come from verified runs in the v0 codebase
(`pytest` + `python examples/electrolysis_v0.py`).

### 7.1 Demand 100 kg/h, Mode 1, default PEM

```bash
python examples/electrolysis_v0.py --mode 1 --demand 100
```

| Result | Value |
|---|---|
| `status` | `converged` |
| `iterations` | 1 (linear short-circuit) |
| `objective` | 2.222 × 10⁶ £/yr |
| `pem.electricity_kW` | 5 555.6 kW |
| `pem.h2_kg_per_h` | 100.0 |
| `pem.LCOH_GBP_per_kg` | 4.03 £/kg |
| Annual H₂ | 800 000 kg |
| Annual OPEX | 2 222 222 £ |
| Annual CAPEX | 1 000 000 £ |

Reading: at η = 0.018 kg/kWh, 100 kg/h H₂ requires 100 / 0.018 = 5 555.6
kW. Annual LCOH ≈ £4.03/kg.

### 7.2 Mode-2 trade-off at demand 80 kg/h

```bash
python examples/electrolysis_v0.py --mode 2 --demand 80
```

| Result | Value |
|---|---|
| `status` | `converged` |
| `iterations` | 1 (selected mix is all-linear) |
| `objective` | 2.778 × 10⁶ £/yr |
| `technology_selection` | `{"pick_pem": true, "pick_gasifier": false}` |
| `pem.electricity_kW` | 4 444.4 kW |
| `pem.h2_kg_per_h` | 80.0 |
| `gasifier.feed_kg_per_h` | 0 |
| `pem.LCOH_GBP_per_kg` | 4.34 £/kg |

Reading: at this demand, PEM's £1M annual CAPEX beats the gasifier's
£5M fixed annual CAPEX. The MILP picks PEM only. PEM's per-unit LCOH
rises slightly vs §7.1 because the same fixed CAPEX is now amortised
over less hydrogen (640 000 kg/yr vs 800 000 kg/yr).

### 7.3 Sensitivity sketch — sweep the electricity price

```python
from pse_ecosystem.models.electrolysis.pem_toy import PEMToyParams
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import (
    make_electrolysis_only,
)
from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.solvers.orchestrator import Orchestrator

for price in [0.03, 0.04, 0.05, 0.06, 0.07, 0.08]:
    params = PEMToyParams(electricity_price_per_kWh=price)
    fs = make_electrolysis_only(h2_demand_kg_per_h=100.0, pem_params=params)
    res = Orchestrator(fs, SolveMode.FIXED_LP).solve()
    lcoh = res.kpis["pem.LCOH_GBP_per_kg"]
    print(f"£{price:.2f}/kWh → LCOH £{lcoh:.2f}/kg")
```

LCOH scales linearly with electricity price under v0 PEM assumptions
(efficiency is constant, so OPEX is a linear multiple of price). The
slope tells you the electricity intensity of LCOH.

---

## 8. FAQ

### 8.1 Why did my LP converge in one iteration?

You ran Mode 1 on a flowsheet where every unit is linear. The SLP
driver detected `is_exact=True` on every `LinearizedModel` and
short-circuited to a single Pyomo solve. This is correct and fast.

### 8.2 The MILP picked PEM and zero gasifier — is that real?

Yes — at the v0 default parameters, PEM's annualised CAPEX (£100/kW ×
10 000 kW = £1M) is much cheaper than the gasifier's fixed £5M. To force
the gasifier into the answer, lower its CAPEX, raise the demand, or
raise the electricity price. The MILP is doing the right thing — it's
the parameters that make the trade-off lopsided.

### 8.3 Why is my gasifier LCOH NaN?

If the gasifier's `annual_h2_kg` is below 1e-9 (effectively zero, e.g.
because the MILP didn't pick it), LCOH is undefined and reported as
`NaN`. Filter on `result.technology_selection` before computing
per-route metrics.

### 8.4 Can I add my own electrolyser model?

Yes. Subclass `BaseUnit`, implement `variables()`, `bounds()`,
`residual()`, and `objective_contribution()`. The finite-difference
fallback gives you a working Jacobian for free. Full walk-through in
[`DEVELOPER_GUIDE.md` §3](DEVELOPER_GUIDE.md#3-layer-3--adding-a-unit-model).

---

## 9. Future Roadmap (Placeholders)

**v0.1.0 additions (now implemented):**

---

## v0.1.0 New Features

### Expanded Unit Library

| Unit | Key equation | Jacobian |
|---|---|---|
| `IdealMixer(n_inlets, components)` | F_out_c = Σ F_in_j_c (linear) | Analytical |
| `BoilerToy` | Q = η·LHV·F_fuel = F_steam·h_steam | Analytical |
| `HeatExchangerToy` | Q = m·Cp·ΔT = U·A·LMTD (non-linear) | FD |
| `CSTRToy(k, F_total_nom)` | F_A_in - F_A_out = k·V·(F_A_out/F_nom) | Analytical |
| `FlashToy(K_A_ref)` | K-value + Rachford-Rice (constant K) | FD |
| `HDAPFRUnit` | HDA adiabatic PFR (ODE) | FD |
| `HDAFlashUnit` | HDA VLE flash (Wilson K + RR) | FD |
| `HDADistillationUnit` | HDA FUG shortcut columns | FD |

**Important:** For units with FD Jacobians or when `extra_equalities` pin
variables far from bounds midpoints, always supply an explicit `x0` to
`SLPDriver.run(x0=...)`. The default midpoint guess will cause an infeasible
LP if the pinned values are far from the midpoints.

### HDA Case Study (`examples/hda_case_study.py`)

The classic Hydrodealkylation (HDA) process — toluene + H2 → benzene + CH4 —
is available as a complete worked example. It exercises the PFR reactor,
isothermal flash, and two-column distillation train, connected via a toluene
recycle loop.

```bash
python examples/hda_case_study.py
```

### Weather-Driven Optimisation

Optimise PEM electrolysis across a day or year using a real solar profile:

```python
from pse_ecosystem.data.weather import (
    SiteData, fetch_solar_profile, electricity_price_from_solar,
    WeatherDrivenFlowsheet, generate_demand_profile,
)
from pse_ecosystem.flowsheets.hydrogen.electrolysis_grid import make_electrolysis_only

# Surrey, UK solar profile for 2023
site   = SiteData(51.24, -0.59, 50, "Europe/London")
ghi    = fetch_solar_profile(site, 2023)
prices = electricity_price_from_solar(ghi, base_price=0.10, solar_discount=0.05)

wdf = WeatherDrivenFlowsheet(
    name="solar_pem",
    base_flowsheet=make_electrolysis_only(100.0),
    solar_ghi=ghi,
    electricity_prices=prices,
    h2_demand=generate_demand_profile(50.0),
)

# Cheapest hour (peak solar)
from pse_ecosystem.solvers.slp import SLPDriver, SLPConfig
import numpy as np
solar_hour = int(np.argmax(ghi))
fs = wdf.make_pem_snapshot_flowsheet(hour=solar_hour)
result = SLPDriver(fs, SLPConfig()).run()
print(f"LCOH at peak solar: {result.kpis['pem.LCOH_GBP_per_kg']:.3f} £/kg")
```

Requires `pip install 'pse_ecosystem[weather]'` (pvlib).

### Streamlit GUI (Stub)

```bash
pip install 'pse_ecosystem[gui]'
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Sidebar: theme, application, mode, demand, verbose toggle.
Main panel: KPIs, solution variables, technology selection.
Current version connects to the existing Hydrogen theme only.

---

## Future Roadmap

The capabilities below are targeted for v1+. They are listed here so
you can understand the trajectory rather than assume they are missing
forever.

- **Web-based UI** (Streamlit first, FastAPI for industry partners).
- **Electricity price profiles** — hourly, with optional carbon
  intensity series.
- **Temporal optimisation** — multi-period operation under variable
  demand and prices.
- **CCS toggle** on the gasification route, with capture rate and
  capture-CAPEX as decision variables.
- **Additional themes** — ammonia, methanol, CCS networks.
- **Visualisations** — flowsheet diagrams, Pareto fronts for
  multi-objective runs, sensitivity tornado plots.
- **ML-backed unit models** — surrogates trained on Aspen / gPROMS runs,
  exposed through the same handshake protocol so no UI or solver
  changes are required.
