"""v1.6 Workstream F — parity / Aspen interop / case-study tests.

Coverage:
* F.1 parity metrics: MAPE / RMSE / R² kernels, perfect-match limit
  (MAPE=0, R²=1), missing-variable soft-fail, worst_variable detection.
* F.2 CSV I/O: round-trip read / write preserves data, Aspen-compatible
  column order, numeric / string coercion edge cases.
* F.3 Aspen .bkp parser: tolerant to missing ASCII section, extracts
  stream + block names from synthetic test files.
* F.4 kinetic tuner: smoke test with a 1-parameter quadratic ⇒
  optimiser reduces parity error.
* F.5 case studies: each bundled CSV parses, has the expected stream
  names, and round-trips through parity vs itself with MAPE = 0.
"""

from __future__ import annotations

import math
import os
import tempfile
from typing import Dict

import pytest

from pse_ecosystem.validation import (
    KineticParam,
    compute_metrics,
    parse_aspen_bkp,
    read_stream_table_csv,
    scatter_data,
    tune_kinetics,
    write_stream_table_csv,
)
from pse_ecosystem.validation.case_studies import (
    AVAILABLE,
    case_study_path,
    load_case_study,
)


# ─────────────────────────────────────────────────────────────────────────────
# F.1 — Parity metrics
# ─────────────────────────────────────────────────────────────────────────────


class TestParityMetrics:
    def test_perfect_match_zero_error(self):
        measured = {"x": [1.0, 2.0, 3.0]}
        predicted = {"x": [1.0, 2.0, 3.0]}
        r = compute_metrics(measured, predicted)
        assert r.per_variable["x"].mape_pct == pytest.approx(0.0)
        assert r.per_variable["x"].rmse == pytest.approx(0.0)
        assert r.per_variable["x"].r_squared == pytest.approx(1.0)
        assert r.overall_mape_pct == pytest.approx(0.0)

    def test_constant_offset_mape(self):
        # m = 10, p = 11 ⇒ MAPE = 10%
        measured = {"x": [10.0, 20.0, 30.0]}
        predicted = {"x": [11.0, 22.0, 33.0]}
        r = compute_metrics(measured, predicted)
        assert r.per_variable["x"].mape_pct == pytest.approx(10.0)

    def test_zero_measured_skipped(self):
        # Variables where m=0 must not blow up MAPE.
        measured = {"x": [0.0, 1.0]}
        predicted = {"x": [0.0, 1.1]}
        r = compute_metrics(measured, predicted)
        assert r.per_variable["x"].mape_pct == pytest.approx(10.0)

    def test_missing_predicted_variable_skipped(self):
        measured = {"x": [1.0], "y": [2.0]}
        predicted = {"x": [1.0]}  # no y
        r = compute_metrics(measured, predicted)
        assert "y" not in r.per_variable

    def test_worst_variable_detection(self):
        measured = {"good": [1.0], "bad": [1.0]}
        predicted = {"good": [1.01], "bad": [2.0]}
        r = compute_metrics(measured, predicted)
        assert r.worst_variable == "bad"

    def test_mape_threshold_check(self):
        measured = {"x": [1.0]}
        predicted = {"x": [1.03]}
        r = compute_metrics(measured, predicted)
        assert r.mape_threshold_passed(5.0)
        assert not r.mape_threshold_passed(1.0)

    def test_to_dict_serialisable(self):
        r = compute_metrics({"x": [1.0]}, {"x": [1.0]})
        d = r.to_dict()
        assert "per_variable" in d
        assert "overall_mape_pct" in d


class TestScatterData:
    def test_flat_arrays(self):
        m = {"a": [1.0, 2.0], "b": [3.0]}
        p = {"a": [1.1, 2.1], "b": [3.3]}
        s = scatter_data(m, p)
        assert s["measured"] == [1.0, 2.0, 3.0]
        assert s["predicted"] == [1.1, 2.1, 3.3]
        assert s["variable"] == ["a", "a", "b"]


# ─────────────────────────────────────────────────────────────────────────────
# F.2 — CSV I/O
# ─────────────────────────────────────────────────────────────────────────────


class TestCsvIO:
    def test_round_trip_preserves_data(self, tmp_path):
        streams = {
            "feed": {"T_K": 300.0, "P_Pa": 1.0e5, "y_H2": 0.5, "y_CH4": 0.5},
            "out": {"T_K": 500.0, "P_Pa": 9.5e4, "y_H2": 0.7, "y_CH4": 0.3},
        }
        path = tmp_path / "test.csv"
        write_stream_table_csv(str(path), streams)
        loaded = read_stream_table_csv(str(path))
        assert set(loaded) == {"feed", "out"}
        assert loaded["feed"]["T_K"] == 300.0
        assert loaded["out"]["y_H2"] == 0.7

    def test_empty_cell_becomes_zero_for_composition(self, tmp_path):
        # Composition columns coerce empty → 0.0 (Aspen convention).
        path = tmp_path / "sparse.csv"
        path.write_text("Stream,y_H2,y_CO\nf1,0.5,\n")
        loaded = read_stream_table_csv(str(path))
        assert loaded["f1"]["y_CO"] == 0.0

    def test_column_order_reserved_first(self, tmp_path):
        # T_K / P_Pa should precede composition columns in output.
        streams = {"f": {"y_X": 1.0, "T_K": 300.0, "P_Pa": 1e5}}
        path = tmp_path / "ord.csv"
        write_stream_table_csv(str(path), streams)
        first_line = path.read_text().splitlines()[0]
        cols = first_line.split(",")
        # T_K and P_Pa must appear before y_X
        assert cols.index("T_K") < cols.index("y_X")
        assert cols.index("P_Pa") < cols.index("y_X")


# ─────────────────────────────────────────────────────────────────────────────
# F.3 — Aspen .bkp parser
# ─────────────────────────────────────────────────────────────────────────────


class TestAspenImporter:
    def test_missing_ascii_section_warns(self, tmp_path):
        # Pure binary file → parser returns empty result + warning.
        path = tmp_path / "binary.bkp"
        path.write_bytes(b"\x00\x01\x02\x03\x04")
        result = parse_aspen_bkp(str(path))
        assert result.streams == []
        assert result.block_names == []
        assert any("ASCII summary" in w for w in result.warnings)

    def test_block_extraction_from_synthetic_ascii(self, tmp_path):
        path = tmp_path / "synthetic.bkp"
        path.write_text(
            "Aspen Plus Backup File\n"
            "BLOCK NAME TYPE\n"
            "  B1  RSTOIC reactor\n"
            "  B2  FLASH2 separator\n"
            "  PUMP1 PUMP pressure_changer\n"
            "STREAM ID: feed\n"
            "  TEMP 350.0 K\n"
            "  PRES 1.5e5 Pa\n"
            "  MOLE FLOW 10.0 mol/s\n"
            "  MOLE FRAC H2 0.5\n"
            "  MOLE FRAC CH4 0.5\n"
        )
        result = parse_aspen_bkp(str(path))
        assert "B1" in result.block_names
        assert "B2" in result.block_names
        assert result.block_types.get("B1") == "RSTOIC"
        assert len(result.streams) == 1
        s = result.streams[0]
        assert s.name == "feed"
        assert s.T_K == pytest.approx(350.0)
        assert s.composition == {"H2": 0.5, "CH4": 0.5}


# ─────────────────────────────────────────────────────────────────────────────
# F.4 — Kinetic tuner
# ─────────────────────────────────────────────────────────────────────────────


class TestKineticTuner:
    def test_smoke_quadratic(self):
        """Toy problem: predict = param × ones; measured = 5 × ones.
        Optimiser should drive param to 5."""

        def predict(params: Dict[str, float]) -> Dict[str, list]:
            k = params["k"]
            return {"y": [k, k, k]}

        params = [KineticParam(name="k", initial=1.0, lower=0.0, upper=20.0)]
        measured = {"y": [5.0, 5.0, 5.0]}
        result = tune_kinetics(params, measured, predict)
        assert result.converged
        # k should land near 5
        assert abs(result.tuned["k"] - 5.0) < 1e-3
        # Parity should improve (overall MAPE drops to ~0)
        assert result.parity_after.overall_mape_pct <= result.parity_before.overall_mape_pct

    def test_log_scale_param(self):
        """Log-scale tuning for an Arrhenius-style pre-exponential."""

        def predict(params: Dict[str, float]) -> Dict[str, list]:
            A = params["A"]
            return {"r": [A / 1e6]}

        params = [
            KineticParam(name="A", initial=1.0, lower=1e-3, upper=1e9, log_scale=True),
        ]
        measured = {"r": [5.0]}
        result = tune_kinetics(params, measured, predict)
        # A should approach 5e6
        assert 1e6 < result.tuned["A"] < 1e8


# ─────────────────────────────────────────────────────────────────────────────
# F.5 — Bundled case studies
# ─────────────────────────────────────────────────────────────────────────────


class TestCaseStudies:
    def test_all_available_parseable(self):
        for name in AVAILABLE:
            data = load_case_study(name)
            assert len(data) >= 2  # at least feed + one outlet

    def test_smr_has_expected_streams(self):
        d = load_case_study("smr")
        assert {"feed", "reformer_out", "psa_h2_product"} <= set(d)

    def test_mea_has_expected_streams(self):
        d = load_case_study("mea_absorber")
        assert {"flue_gas_in", "cleaned_gas_out", "rich_amine_out"} <= set(d)

    def test_propane_splitter_purity(self):
        d = load_case_study("propane_splitter")
        # Distillate should be >99% propylene (industrial-grade C3=)
        assert d["distillate"]["y_propylene"] > 0.99

    def test_ammonia_loop_has_recycle(self):
        d = load_case_study("ammonia_loop")
        assert {"makeup", "recycle", "reactor_in", "nh3_product"} <= set(d)

    def test_parity_self_round_trip(self):
        """A case study compared to itself must yield MAPE = 0."""
        for name in AVAILABLE:
            d = load_case_study(name)
            # Extract one composition variable per stream into the parity
            # format
            measured_T = {s: [d[s]["T_K"]] for s in d}
            predicted_T = {s: [d[s]["T_K"]] for s in d}
            r = compute_metrics(measured_T, predicted_T)
            assert r.overall_mape_pct == pytest.approx(0.0), f"Case {name}"

    def test_case_study_path_exists(self):
        for name in AVAILABLE:
            assert os.path.isfile(case_study_path(name))
