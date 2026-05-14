# PSE Ecosystem — Investor Showcase Walkthrough
**Version:** v1.2.1  |  **Date:** 2026-05-14  |  **Audience:** Funders / Industrial Partners

---

## Pre-Meeting Setup (2 minutes)

```powershell
# Activate venv and launch
& C:\Users\gh00616\.venvs\pse_ecosystem\Scripts\Activate.ps1
cd "C:\Users\gh00616\OneDrive - University of Surrey\Desktop\PhD Folder\IMP\PSE_ECOSYSTEM"
streamlit run pse_ecosystem/ui/app_streamlit.py
```

Open `http://localhost:8501`. Confirm the **Dashboard** shows green solver metrics. If no green, run:

```powershell
pip install -r requirements.txt
```

**What to have open:** Browser on Dashboard, text editor with this file for talking-point reference.

---

## Stage 1 — "The Engine Works" (5 minutes)

**What you are demonstrating:** The platform uses *exact, analytically-derived Jacobians* — not numerical finite differences. This means the physics are provably correct, not approximated.

### Step-by-step

1. Sidebar → **Flowsheet Builder**
2. Category: **Small** → select **"CSTR + Flash (NL)"** → click **Apply & Select**
3. Sidebar → **Solver Monitor** → Solver mode: **SLP** → click **Run Solve**
4. Point at the **Residual Norm** convergence chart — show residual dropping 3–4 orders of magnitude in 5–10 iterations

### Talking Points

> *"Each SLP iteration linearises the non-linear VLE physics at the current operating point. The linearisation uses an analytically-derived Jacobian — not finite differences — so there is no truncation error. You are seeing exact gradient information from the physics equations, not an approximation."*

> *"The flash unit uses rigorous Antoine K-values: K_i(T, P) = P_sat_i(T) / P, where P_sat is from the Antoine correlation. The vapour-liquid split solves the Rachford-Rice equation:*

$$\sum_i \frac{z_i (K_i - 1)}{1 + \psi(K_i - 1)} = 0$$

> *where ψ is the vapour fraction. This is an industry-standard formulation — the same physics used in Aspen, except here you can inspect every residual and every Jacobian entry directly."*

### What success looks like
- Convergence in ≤ 10 SLP iterations
- V_frac KPI displayed (typical range 0.2–0.8 for benzene/toluene mix)
- Residual norm chart shown on screen

---

## Stage 2 — "Real-World Scale" (7 minutes)

**What you are demonstrating:** A 4-unit industrial process chain solving coupled, non-linear thermochemical equilibrium equations — with the ability to extend it live with a custom unit.

### Step 2a — Load the industrial template

1. Sidebar → **Flowsheet Builder**
2. Category: **Hydrogen** → select **"Biomass → H₂ (Gasification)"**
3. Note the 4-unit topology: **BiomassStorage → BiomassGasifier → WGSReactor → PSA Separator**
4. Optionally adjust `T_gasifier_C` (default 800 °C) and `feed_wet_kg_s` (default 1.0 kg/s)
5. Click **Apply & Select**
6. Sidebar → **Solver Monitor** → **Run Solve**

### Talking Points (while solver runs)

> *"The gasifier solves two coupled equilibrium equations simultaneously. The Water-Gas Shift equilibrium:*

$$K_{WGS}(T) = \frac{n_{CO_2} \cdot n_{H_2}}{n_{CO} \cdot n_{H_2O}}$$

> *And the methanation equilibrium (van't Hoff):*

$$\ln K_{met}(T) = \frac{\Delta H°_{met}}{R} \left(\frac{1}{T_{ref}} - \frac{1}{T}\right)$$

> *These are exact thermochemical equilibrium expressions — not regression fits, not lookup tables. The solver finds the unique operating point where both equilibria are satisfied simultaneously."*

### What success looks like
- Convergence in ≤ 20 SLP iterations
- KPI cards displayed: **H₂ production (kg/h)**, **Cold Gas Efficiency (%)**, **H₂ purity (%)**

### Step 2b — Extend with a custom unit (live demo of extensibility)

1. Sidebar → **Flowsheet Builder** → scroll down to **Custom Flowsheet**
2. Shared component set: `H2, CO, CO2`
3. Number of units: **1** → Unit type: **Compressor** → ID: `comp`
4. Add a connection: From `comp`, To `comp` (single unit, no inter-unit connection)
5. Click **Build & Select** → then **Solver Monitor → Run Solve**

> *"In a real deployment, you would wire the Compressor outlet to the downstream distribution network. The layered architecture means this unit was added without touching the Biomass gasifier code — full separation of concerns."*

---

## Stage 3 — "The Decision Tool" (5 minutes)

**What you are demonstrating:** Parameter sensitivity sweeps that produce the investor's actual decision curve — LCOH vs. electricity price.

### Step-by-step

1. Sidebar → **Flowsheet Builder** → Category: **Hydrogen** → **"PEM Electrolysis"** → **Apply & Select**
2. In the Flowsheet Builder page, expand **"1D Parameter Sensitivity Sweep"**
3. Parameter: `pem.electricity_price_per_kWh`
4. Min: `0.02`, Max: `0.15`, Points: `12`
5. Click **Run Sweep**
6. Multi-trace Plotly chart appears: **LCOH (£/kg H₂) vs. Electricity Price (£/kWh)**

### Talking Points

> *"This is the investor's decision curve. The levelised cost of hydrogen crosses grid parity — typically £4–6/kg — at a specific electricity price. This chart was generated in under 2 seconds by the analytical solver. Aspen would require a separate sensitivity study job that runs for minutes."*

> *"The slope of this curve is the derivative of LCOH with respect to electricity price — which we can compute analytically from the Jacobian. That is the value of having exact, symbolic physics."*

### What success looks like
- Plotly chart with 12-point sweep rendered
- LCOH curve clearly shows price sensitivity (typical: 2–8 £/kg range across sweep)
- Data table with exact values downloadable

---

## Stage 4 — "The Architecture" (optional, 3 minutes)

Only include this if the audience is technical (engineering or deep-tech VC).

> *"The platform has three strict layers: Layer 1 (Streamlit UI), Layer 2 (SLP/NLP/Trust-Region solvers), Layer 3 (unit physics). Layers only communicate via the Handshake Protocol — a typed contract that enforces separation of concerns. This means the solver can be replaced without touching the physics, and the UI can be replaced without touching the solver."*

Show `docs/ARCHITECTURE.md` briefly if asked.

---

## Q&A Preparation

### "Can it handle recycle loops?"
> "Yes. The SLP driver supports Wegstein tear-stream acceleration for recycle convergence — the same algorithm used in steady-state process simulators. It is not demonstrated in the gallery today but is in the codebase and documented in `docs/THEORY_REFERENCE.md`."

### "How does this compare to Aspen Plus?"
> "Aspen Plus is proprietary, opaque, and priced at £30,000+/seat. PSE Ecosystem exposes the full algebraic residual system and Jacobian — regulators, auditors, and research partners can inspect every equation. It runs on a £500 laptop with zero licence cost. And because the Jacobian is analytical, it converges faster on well-initialised problems."

### "What's the IP moat?"
> Three things: **(1)** the three-layer handshake architecture that decouples UI/solver/physics; **(2)** the analytical Jacobian protocol — every unit model ships its exact ∂f/∂x alongside its residual; **(3)** the B-HYPSYS corrections — 16 physics defects in the published benchmark were identified and corrected in v1.1.0, producing a validated equilibrium thermochemistry library."

### "What sectors beyond hydrogen?"
> "The solver is sector-agnostic. The unit library currently covers hydrogen production, DAC (direct air capture), combined heat-and-power, and VLE separation. Any process expressible as a system of algebraic equations — CO₂ utilisation, e-fuels, ammonia — is a direct extension."

### "What's your go-to-market?"
> "SaaS licensing to engineering consultancies and national laboratories who need explainable, auditable process simulation without the Aspen licence cost. Pilot discussions are in progress — details available under NDA."

---

## Known Limitations (Disclose Honestly)

These should be presented proactively — it builds credibility:

| Limitation | Status | Roadmap |
|------------|--------|---------|
| VLE limited to Raoult's Law (Antoine) | Current | Cubic EOS (PR/SRK) in v1.3 |
| No recycle loop in gallery | Implemented in solver, no demo | Add CSTR-recycle template v1.3 |
| FlashVLHF terminal only (no multi-outlet wiring in custom builder) | Known | Multi-port connection UI v1.3 |
| IPOPT requires `idaes-pse` install (optional) | Not required for SLP | Documented in USER_MANUAL |
| Biomass template tested at T ≥ 650 °C only | Physics-valid constraint | Add T warning in UI |

---

## Appendix — Key Equations for Slide Deck

### Rachford-Rice (Flash VLE)

$$f(\psi) = \sum_{i=1}^{N_c} \frac{z_i (K_i - 1)}{1 + \psi(K_i - 1)} = 0, \qquad K_i = \frac{P_{sat,i}(T)}{P}$$

Solved by the Illinois bracket method; ψ ∈ (0, 1) guaranteed by construction.

### Water-Gas Shift Equilibrium (Biomass Gasifier)

$$K_{WGS}(T) = \exp\!\left(\frac{-\Delta G°_{WGS}(T)}{RT}\right), \qquad \Delta G°(T) = \Delta H° - T \Delta S°$$

At 800 °C: K_WGS ≈ 1.8 (mild forward bias → significant CO conversion).

### SLP Linearisation

At iteration k, the non-linear residual f(x) is replaced by:

$$f(x^k) + J(x^k)(x - x^k) = 0, \qquad J_{ij} = \frac{\partial f_i}{\partial x_j}\bigg|_{x^k}$$

J is computed analytically (not by finite differences). The resulting LP is:

$$\min_{x} \; c^T x \quad \text{s.t.} \quad Ax = b,\; x_{\ell} \le x \le x_u$$
