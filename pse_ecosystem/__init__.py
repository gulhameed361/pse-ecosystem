"""PSE Ecosystem — three-layer platform for hydrogen process design and optimisation.

v1.5.3: Comprehensive bug-fix and quality release (36 issues resolved).

Critical fixes
--------------
- Fix NPV/IRR cash flow sign error — add ProductionConfig revenue model; NPV/IRR
  cells now show "N/A (no revenue model)" when no product prices are configured.
- Fix Sankey diagram — T/P intensive variables excluded; flows aggregated per
  unit-pair to show correct molar totals.
- Fix _extract_power_out_kW returning max instead of sum across generators.

High-severity fixes
-------------------
- Add OBJECTIVE_LP_PROXY_NOTE dict flagging NPV/IRR modes as TAC-proxy in UI.
- H₂ yield objective: topology-aware most-downstream unit (not lexicographic).
- Electrolyser CAPEX coefficient moved to ProjectEconomicsConfig (1 200 USD/kW,
  NREL 2024), no longer hardcoded.
- LP/MILP solver preference: HiGHS before GLPK.
- ADAPTIVE mode only swallows ImportError/ModuleNotFoundError/RuntimeError/
  AttributeError from the NLP stage; physics exceptions now propagate.
- ASME vessel whitelist expanded: PFRHF, TVSAContactor, DistillationHF,
  ShellTubeHX, Pump, MethanationReactor, FlashSL.
- aggregate_kpis() emits RuntimeWarning instead of silently swallowing unit KPI
  failures.
- initial_x0 is now a proper BaseFlowsheet dataclass field (Optional[Dict]).
- CompositeUnit.kpis() and .capex() propagate inner flowsheet results via cached
  last-inner-solve solution.
- LP row scaling (scale_rows) enabled by default in SLPConfig.

Medium fixes
------------
- Energy variable matching uses suffix-based matching (not substring).
- ElectrolyserHF isinstance() check replaces type().__name__ string comparison.
- history.jsonl capped at 200 entries on disk (no more unbounded growth).
- Backward-compat opex_per_year TypeError shim removed.
- economics.json data file created; EconomicEngine now loads CEPCI from file.
- recycle_streams field documented as informational-only.

Low-severity fixes
------------------
- OPEXConvention string Enum replaces bare str class attribute.
- _StepNormStop defined once outside attempt loop in NLPDriver.
- HeatExchangerNTU effectiveness clamped to [0, 1].
- NLP_IPOPT / NLP_SCIPY docstrings clarify scipy backend.
- OBJECTIVE_LP_PROXY_NOTE dict exposes proxy warning for UI display.
"""

__version__ = "1.6.1"  # polish & activation release
