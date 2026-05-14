# PSE Ecosystem — Tutorial Walkthrough
**Version:** v1.2.1  |  **Date:** 2026-05-14

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

## 2. Case A: 3-Unit String — Heater → Reactor → Separator

Chain: **feed pre-conditioner** (StoichiometricReactor, ξ=0) → **P2M synthesis reactor**
(StoichiometricReactor, CO₂ + 3H₂ → MeOH + H₂O) → **separator** (SeparatorHF).

This chain is verified end-to-end by `tests/presentation_validation.py` (run it with
`pytest tests/presentation_validation.py -v` or as a standalone script).

> **Why not HeatExchangerNTU + FlashVLHF?** `HeatExchangerNTU` is a 2-stream unit
> (separate hot/cold components); it cannot be directly chained to a single-stream
> reactor with the same component list. `FlashVLHF` with CO₂/H₂ at 700 K extrapolates
> the Antoine equation far above the critical temperatures of both species (CO₂ Tc=304 K,
> H₂ Tc=33 K), making the LP infeasible from a cold start. Both are documented known
> limitations in `docs/SYSTEM_STATE.md`.

### 2.1 Setup

```python
from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.reactors.stoichiometric_reactor import (
    StoichiometricReactor, StoichiometricParams,
)
from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig
from pse_ecosystem.core.contracts import SolveMode

components = ["CO2", "H2", "methanol", "water"]
p2m_stoich = {"CO2": [-1.0], "H2": [-3.0], "methanol": [1.0], "water": [1.0]}

# Unit 1 — feed pre-conditioner ("Heater"): zero-extent pass-through at design T/P
heater = StoichiometricReactor("heater", components,
    StoichiometricParams(stoichiometry=p2m_stoich, feed_max=200.0))

# Unit 2 — P2M synthesis reactor ("Reactor")
reactor = StoichiometricReactor("reactor", components,
    StoichiometricParams(stoichiometry=p2m_stoich, feed_max=200.0, xi_max=[50.0]))

# Unit 3 — liquid-gas separator ("Flash"): 95% MeOH, 98% H₂O to liquid outlet
sep = SeparatorHF("sep", components, SeparatorHFParams(
    n_outlets=2,
    split_fractions=[[0.05, 0.95],   # CO2: 5% liq, 95% vap
                     [0.02, 0.98],   # H2:  2% liq, 98% vap
                     [0.95, 0.05],   # MeOH: 95% liq
                     [0.98, 0.02]],  # H2O: 98% liq
))

fs = BaseFlowsheet(name="tutorial_A", units=[heater, reactor, sep])
fs.connect(heater.outlet_port,  reactor.inlet_port, "Pre-conditioner -> reactor")
fs.connect(reactor.outlet_port, sep.inlet_port,     "Reactor -> separator")

# Fix feed (the "Heater" inlet): 10 mol/s CO2 + 30 mol/s H2, no products
fs.extra_bounds["heater.inlet.F_CO2"]     = (10.0, 10.0)
fs.extra_bounds["heater.inlet.F_H2"]      = (30.0, 30.0)
fs.extra_bounds["heater.inlet.F_methanol"] = (0.0, 0.0)
fs.extra_bounds["heater.inlet.F_water"]   = (0.0, 0.0)
fs.extra_bounds["heater.inlet.T"]         = (500.0, 500.0)
fs.extra_bounds["heater.inlet.P"]         = (3_000_000.0, 3_000_000.0)
fs.extra_bounds["heater.xi_0"]            = (0.0, 0.0)   # pass-through

cfg = SLPConfig(max_iter=5, verbose=True)
result = Orchestrator(fs, SolveMode.FIXED_LP, slp_config=cfg).solve()
print(result.status, result.iterations)   # CONVERGED, 1
```

### 2.2 Symbolic Analytical Proof

**P2M stoichiometry** (CO₂ + 3H₂ → CH₃OH + H₂O, extent ξ mol/s):

| Species | Balance | Feed (mol/s) | Product (mol/s) |
|---------|---------|-------------|-----------------|
| CO₂     | F_CO₂_out = F_CO₂_in − ξ | 10 | 10 − ξ |
| H₂      | F_H₂_out  = F_H₂_in  − 3ξ | 30 | 30 − 3ξ |
| MeOH    | F_MeOH_out = 0 + ξ | 0 | ξ |
| H₂O     | F_H₂O_out  = 0 + ξ | 0 | ξ |

**Jacobian** for `StoichiometricReactor` is exact (`is_exact=True`, `is_linear=True`):

```
J_row_c = [ ∂f_c/∂F_out_c   ∂f_c/∂F_in_c   ∂f_c/∂ξ ]
         = [      +1               -1            -νc   ]

where νc ∈ {−1, −3, +1, +1} for {CO₂, H₂, MeOH, H₂O}
```

Because every residual is linear in the variables, the SLP short-circuits to a
**single LP solve** (`is_exact=True` propagates to the driver). The LP solution
satisfies `J·x = rhs` exactly — residual `‖f‖∞ = 0`.

**Verification:** run `pytest tests/presentation_validation.py::test_3unit_chain_p2m_stoichiometry -v`
which asserts `|F_CO₂_in − F_CO₂_out − ξ| < 1e-6` and `|F_MeOH_out − ξ| < 1e-6`.

### 2.3 Convergence Proof for Non-linear Units

For a non-linear unit with residual `f(x)` and Jacobian `J(x)`, the SLP update
`x_{k+1} = x_k − J(x_k)⁻¹ f(x_k)` is a Newton step. Near a solution, Newton's
method converges **quadratically**: `‖x_{k+1} − x*‖ ≤ C · ‖x_k − x*‖²`

With finite trust region Δ, convergence is at least linear (worst-case ρ → 1.0).
For the Trust-Region Filter variant (SolveMode.TRUST_REGION), global convergence
to a KKT point is guaranteed under LICQ + second-order sufficiency — see
`docs/THEORY_REFERENCE.md §8b`.

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
    | flowsheet_service is the sole L1 bridge to L3 factories
    v
Layer 2: Solvers (Orchestrator -> SLPDriver / NLPDriver / TrustRegionDriver)
    | Handshake Protocol (PrimalGuess -> LinearizedModel -> UnitResponse)
    v
Layer 3: Models (BaseUnit subclasses, StreamPort, flowsheets/)
    |
    v
core/contracts.py  (shared enums + dataclasses — imported by all layers)
```

**Key rule:** Layer 2 never imports Layer 3 directly. All physics lives in Layer 3.
Layer 2 only sees `LinearizedModel` and `UnitResponse` from `contracts.py`.
