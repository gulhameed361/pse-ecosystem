"""v1.6.1 P.8 — end-to-end parity tests for the four bundled case studies.

For each of the four case-study CSVs under
``pse_ecosystem/validation/case_studies/``:

* The matching template factory in
  ``pse_ecosystem.flowsheets.case_studies`` instantiates a solvable
  flowsheet.
* The flowsheet solves to converged status under the default
  ``FIXED_LP`` mode.
* The ``predicted_streams`` callable returns a dict shaped like the
  reference CSV (same stream names, same column layout).
* Overall MAPE between predicted and measured stream tables sits below
  the per-template ceiling documented in
  :mod:`pse_ecosystem.flowsheets.case_studies` (loose v1.6.1 acceptance
  — three templates hit < 10 %, SMR is structurally limited at ~30 %
  pending the v1.7 GibbsReactor).
"""

from __future__ import annotations

from typing import Dict

import pytest

from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.flowsheets.case_studies import CASE_STUDIES
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.validation.case_studies import load_case_study
from pse_ecosystem.validation.parity import compute_metrics


def _column_wise(meas: Dict[str, Dict[str, float]], pred: Dict[str, Dict[str, float]]):
    cols = sorted({k for s in meas.values() for k, v in s.items() if isinstance(v, (int, float))})
    m = {
        c: [meas[s].get(c, 0.0) for s in meas if isinstance(meas[s].get(c), (int, float))]
        for c in cols
    }
    p = {
        c: [pred.get(s, {}).get(c, 0.0) for s in meas if isinstance(meas[s].get(c), (int, float))]
        for c in cols
    }
    return m, p


_MAPE_CEILINGS = {
    "smr":              35.0,   # CSV reference is mass-balance-inconsistent
    "mea_absorber":     10.0,
    "propane_splitter": 10.0,
    "ammonia_loop":     10.0,
}


@pytest.mark.parametrize("name", list(CASE_STUDIES))
def test_template_instantiates(name):
    fs, predict = CASE_STUDIES[name]()
    assert fs is not None
    assert callable(predict)
    assert fs.units, "Template has no units"


@pytest.mark.parametrize("name", list(CASE_STUDIES))
def test_template_solves_to_converged(name):
    fs, _ = CASE_STUDIES[name]()
    result = Orchestrator(fs, SolveMode.FIXED_LP).solve()
    assert result.status.value == "converged", (
        f"{name} did not converge: {result.message}"
    )


@pytest.mark.parametrize("name", list(CASE_STUDIES))
def test_predict_streams_align_with_csv(name):
    fs, predict = CASE_STUDIES[name]()
    res = Orchestrator(fs, SolveMode.FIXED_LP).solve()
    pred = predict(fs, dict(res.x))
    meas = load_case_study(name)
    # Same stream names, same columns:
    assert set(pred) >= set(meas), (
        f"{name}: predicted streams missing {set(meas) - set(pred)}"
    )
    # Each predicted stream must carry at least the column names the CSV does
    for stream in meas:
        pred_keys = set(pred[stream])
        meas_keys = {
            k for k, v in meas[stream].items() if isinstance(v, (int, float))
        }
        assert pred_keys >= meas_keys, (
            f"{name}/{stream}: predicted is missing {meas_keys - pred_keys}"
        )


@pytest.mark.parametrize("name", list(CASE_STUDIES))
def test_overall_mape_under_ceiling(name):
    fs, predict = CASE_STUDIES[name]()
    res = Orchestrator(fs, SolveMode.FIXED_LP).solve()
    pred = predict(fs, dict(res.x))
    meas = load_case_study(name)
    m, p = _column_wise(meas, pred)
    metrics = compute_metrics(m, p)
    ceiling = _MAPE_CEILINGS[name]
    assert metrics.overall_mape_pct < ceiling, (
        f"{name} overall MAPE {metrics.overall_mape_pct:.2f}% exceeds "
        f"the {ceiling}% v1.6.1 acceptance ceiling. Worst variable: "
        f"{metrics.worst_variable}"
    )
