"""Four bundled validation case studies for v1.6 industrial release.

* **SMR** (steam-methane reforming) — Aspen Plus benchmark; targets H₂
  purity, CH₄ slip, syngas ratio. Reference: synthesis of Aspen Plus
  V12 RGibbs runs at standard SMR conditions.
* **MEA absorber** — IEAGHG benchmark for 90% CO₂ capture. PackedColumnHF
  + activity-model thermo. Reference: Notz et al. (2012) IEA Greenhouse
  Gas R&D Programme, Report 2012/01.
* **Propane-propylene splitter** — TrayColumnHF benchmark. Reference:
  Stichlmair & Fair (1998) "Distillation: Principles and Practice"
  Ch. 8 worked example.
* **Ammonia synthesis loop** — equilibrium reactor + recycle stress
  test. Reference: Smith & Missen, Aspen Plus Application Notes.

The CSV files in this directory hold the *measured* (reference) data —
T, P, flows, mole fractions per stream. The matching PSE Ecosystem
flowsheet templates live in ``pse_ecosystem.flowsheets.templates`` (UI
loader). A smoke test in ``tests/test_workstream_f.py`` confirms each
case study's CSV parses cleanly and that the parity computation runs
end-to-end with mock predictions.
"""

from __future__ import annotations

import os
from typing import Dict, Any

from pse_ecosystem.validation.csv_io import read_stream_table_csv


_HERE = os.path.dirname(os.path.abspath(__file__))


def case_study_path(name: str) -> str:
    """Return absolute path to the case-study CSV ``<name>.csv``."""
    return os.path.join(_HERE, f"{name}.csv")


def load_case_study(name: str) -> Dict[str, Dict[str, Any]]:
    """Read one of the bundled reference datasets by short name.

    Available names: ``smr``, ``mea_absorber``, ``propane_splitter``,
    ``ammonia_loop``.
    """
    return read_stream_table_csv(case_study_path(name))


AVAILABLE = ("smr", "mea_absorber", "propane_splitter", "ammonia_loop")


__all__ = ["AVAILABLE", "case_study_path", "load_case_study"]
