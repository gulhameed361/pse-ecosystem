"""PSE Ecosystem — three-layer platform for hydrogen process design and optimisation.

v1.5.2: Bug-fix + enhancement release.
- Fix TypeError when custom flowsheet is built (BaseFlowsheet not JSON serializable).
- Fix Pre-solve Validator crash for custom.user_flowsheet templates.
- Fix objective-selector tab disappearing (cascade of the serialization crash).
- Scenario Manager renamed to "Scenario Manager & Analysis" with per-scenario
  1D sensitivity sweep (economic parameters: no re-solve; engineering parameters:
  LP re-solve per point).
"""

__version__ = "1.5.2"
