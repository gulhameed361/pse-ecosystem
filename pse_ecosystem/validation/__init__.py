"""Validation — parity dashboards, CSV / Aspen interop, kinetic tuning,
and the four bundled case studies (SMR, MEA absorber, propane splitter,
ammonia loop).

Public API
----------
* :class:`ParityResult` / :func:`compute_metrics` — MAPE, RMSE, R²
* :func:`read_stream_table_csv` / :func:`write_stream_table_csv` — CSV I/O
* :func:`parse_aspen_bkp` — Aspen Plus ``.bkp`` text-section parser
* :func:`tune_kinetics` — scipy.optimize wrapper for parameter fitting
* :mod:`case_studies` — bundled reference datasets

The validation layer is **post-solve** — it has no Layer 2 dependencies
and never enters the LP residual block.
"""

from pse_ecosystem.validation.aspen_importer import (
    AspenStreamRow,
    parse_aspen_bkp,
)
from pse_ecosystem.validation.csv_io import (
    read_stream_table_csv,
    write_stream_table_csv,
)
from pse_ecosystem.validation.kinetic_tuner import (
    KineticParam,
    TuneResult,
    tune_kinetics,
)
from pse_ecosystem.validation.parity import (
    ParityResult,
    compute_metrics,
    scatter_data,
)

__all__ = [
    "ParityResult",
    "compute_metrics",
    "scatter_data",
    "read_stream_table_csv",
    "write_stream_table_csv",
    "AspenStreamRow",
    "parse_aspen_bkp",
    "KineticParam",
    "TuneResult",
    "tune_kinetics",
]
