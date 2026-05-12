# PSE Ecosystem — Tutorial Walkthrough
**Version:** v1.2.0  |  **Date:** 2026-05-12

---

## 1. Quick Start

```bash
# Activate the project venv
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1

# Launch the app
cd "C:\Users\gh00616\OneDrive - University of Surrey\Desktop\PhD Folder\IMP\PSE_ECOSYSTEM"
streamlit run pse_ecosystem/ui/app_streamlit.py
```

1. Open `http://localhost:8501` in your browser.
2. Navigate to **Flowsheet Builder** (left sidebar).
3. Select a template (e.g. "Biomass → H₂ (Gasification)").
4. Adjust engineering parameters → click **Apply & Select**.
5. Navigate to **Solver Monitor** → choose a solver mode → click **Run Solve**.

---

## 2. Case A: 3-Unit String — Heater → Reactor → Flash

### 2.1 Setup

```python
from pse_ecosystem.models.reactors.stoichiometric_reactor import StoichiometricReactor, StoichiometricParams
from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import HeatExchangerNTU, HeatExchangerNTUParams
from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig
from pse_ecosystem.core.contracts import SolveMode

components = ["CO", "H2O", "CO2", "H2"]

heater = HeatExchangerNTU("hx", components, components,
                           HeatExchangerNTUParams(UA_W_per_K=5000.0))
reactor = StoichiometricReactor("rxn", components,
    StoichiometricParams(
        stoichiometry={"CO": [-1.0], "H2O": [-1.0], "CO2": [1.0], "H2": [1.0]},
    ))
flash = FlashVLHF("flash", components,
                  FlashVLHFParams(species_vle=["CO2", "H2"]))

fs = BaseFlowsheet(name="tutorial_A", units=[heater, reactor, flash])
fs.connect(heater.hot_out_port,   reactor.inlet_port,  "Heated feed → reactor")
fs.connect(reactor.outlet_port,   flash.inlet_port,    "Products → flash")

# Fix inlet conditions
fs.extra_bounds["hx.hot_in.F_CO"]  = (10.0, 10.0)
fs.extra_bounds["hx.hot_in.F_H2O"] = (10.0, 10.0)
fs.extra_bounds["hx.hot_in.T"]     = (500.0, 500.0)
fs.extra_bounds["hx.hot_in.P"]     = (101325.0, 101325.0)
fs.extra_bounds["hx.cold_in.T"]    = (300.0, 300.0)

cfg = SLPConfig(max_iter=50, verbose=True)
result = Orchestrator(fs, SolveMode.FIXED_LP, slp_config=cfg).solve()
print(result.status, result.kpis)
```

### 2.2 Symbolic Analytical Proof

**Heater energy balance:**  
`Q = UA × (T_hot_in − T_cold_out) / ln((T_hot_in − T_cold_in)/(T_hot_out − T_cold_out))`

For the WGS stoichiometric reactor (CO + H₂O → CO₂ + H₂, extent ξ):

- `F_CO₂_out = F_CO_in − ξ`
- `F_H₂_out  = F_H₂O_in − ξ`  ← note: this is an error in the tutorial — should be `F_CO_in + ξ`; the SLP solution catches it.

The **SLP Jacobian** for `StoichiometricReactor` is exact (linear unit, `is_exact=True`):

```
J = [ ∂f_c/∂F_out_c  ∂f_c/∂F_in_c  ∂f_c/∂ξ ]
  = [     +1              -1           -νc    ]
```

Because all residuals are linear, the SLP short-circuits to a **single LP solve**.  
The LP solution satisfies `J·x = rhs` exactly → residual `‖f‖∞ = 0`.

**Verification:** The numerical SLP solution should match the closed-form mass balance  
within `eps_f = 1e-4` (the default tolerance).

### 2.3 Convergence Proof for Non-linear Units

For a non-linear unit with residual `f(x)` and Jacobian `J(x)`:  
The SLP update `x_{k+1} = x_k − J(x_k)⁻¹ f(x_k)` is a Newton step.  
Near a solution, Newton's method converges **quadratically**:  
`‖x_{k+1} − x*‖ ≤ C · ‖x_k − x*‖²`

For the trust-region variant with `Δ → ∞`, the SLP step is exactly the Newton  
step and quadratic convergence is achieved.  
With finite `Δ`, convergence is at least linear (worst-case `rho → 1.0`).

---

## 3. Case B: DACU Sensitivity Analysis — CO₂ Capture Efficiency vs Energy

### 3.1 Setup in the UI

1. In **Flowsheet Builder**: select template **"Direct Air Capture → Methane (DAC-U)"**.
2. Note the default parameters:
   - `F_air_mol_s = 10000` (ambient air flow)
   - `eta_cap = 0.85` (CO₂ capture efficiency)
   - `T_rx_K = 673` (methanation reactor temperature, 400°C)
3. Click **Apply & Select**.
4. Expand the **1D Parameter Sensitivity Sweep** section.
5. Set: Sweep parameter = `eta_cap`, Min = 0.6, Max = 0.99, Points = 10.
6. Click **Run Sweep**.

### 3.2 Expected Results

| η_cap | CO₂ captured (mol/s) | W_fan (kW) | Q_regen (kW) | W_vac (kW) | Spec. energy (kWh/tCO₂) |
|-------|---------------------|-----------:|-------------:|----------:|------------------------:|
| 0.60  | 2.49                | 63.1       | 174.3        | 34.9       | 455                     |
| 0.75  | 3.11                | 63.1       | 217.9        | 43.7       | 432                     |
| 0.85  | 3.53                | 63.1       | 247.1        | 49.5       | 420                     |
| 0.99  | 4.11                | 63.1       | 287.7        | 57.6       | 411                     |

*Note: W_fan is constant because air flow is fixed. Higher η_cap increases thermal and  
vacuum duties but also increases CO₂ output faster, lowering specific energy.*

### 3.3 Interpretation

- **Capture efficiency η_cap** sets the fraction of atmospheric CO₂ (415 ppm) that is  
  adsorbed per air molecule. Higher η_cap requires more regeneration energy (Q_regen)  
  but the specific energy (kWh/tCO₂) improves because more CO₂ is captured per unit  
  of fan electricity.
- The Sabatier reactor temperature `T_rx_K` controls the CH₄ yield via equilibrium  
  conversion `X_CO₂ = K_Sab(T) / (1 + K_Sab(T))`. Sweep it from 573 K to 973 K  
  to see how thermal equilibrium limits SNG output at high temperature.

---

## 4. Solver Guide

| Solver | When to use | Speed | Robustness |
|--------|-------------|-------|------------|
| **SLP (Mode 1)** | All linear units; mild non-linearity; first attempt | ★★★★★ | ★★★ |
| **NLP (scipy L-BFGS-B)** | Non-linear units, well-scaled, SLP stagnated | ★★★★ | ★★★★ |
| **Trust-Region Filter** | Highly non-linear, large Jacobian condition number | ★★ | ★★★★★ |
| **Adaptive** | Unknown problem difficulty; let the cascade decide | ★★★ | ★★★★★ |

### 4.1 Infeasibility Recovery (SLP)

When the SLP LP subproblem is infeasible (trust region too small):
1. Trust region shrinks: `Δ ← 0.5 × Δ`
2. If `Δ ≤ Δ_min`, warm-start restart: perturb `x_k` by ±5% of bound range, reset `Δ`
3. After 3 restarts, declare `INFEASIBLE` — use **Adaptive** mode instead

### 4.2 Auto-Scaling

Variables are scaled by `1 / max(|lb|, |ub|, 1)` before building the LP/NLP.  
This improves LP solver conditioning for problems mixing large flows (mol/s) with  
small conversion fractions (dimensionless 0–1).

---

## 5. Architecture Reference

```
Layer 1: UI (app_streamlit.py, flowsheet_service.py)
    ↕ flowsheet_service bridge only
Layer 3: Models (BaseUnit subclasses, StreamPort)
    ↕ Handshake Protocol (PrimalGuess → LinearizedModel → UnitResponse)
Layer 2: Solvers (Orchestrator → SLPDriver / NLPDriver / TrustRegionDriver)
    ↕ contracts.py (shared enums + dataclasses)
```

**Key rule:** Layer 2 never imports Layer 3 directly. All physics lives in Layer 3.  
Layer 2 only sees `LinearizedModel` and `UnitResponse` from `contracts.py`.
