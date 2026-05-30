"""PSE Ecosystem — three-layer platform for hydrogen process design and optimisation.

Layers
------
- Layer 1 (UI)      : ``pse_ecosystem.ui``       — Streamlit app, pages, bridges.
- Layer 2 (Solvers) : ``pse_ecosystem.solvers``  — SLP / TRF / NLP / MILP drivers.
- Layer 3 (Models)  : ``pse_ecosystem.models``   — physics, thermo, costing.

Layer 2 communicates with Layer 3 only through ``pse_ecosystem.core.contracts``;
it must never import physics models directly.

The per-release changelog lives in ``CHANGELOG.md`` at the repo root — refer to it
rather than this docstring so the two never drift out of sync.
"""

__version__ = "1.6.1"
