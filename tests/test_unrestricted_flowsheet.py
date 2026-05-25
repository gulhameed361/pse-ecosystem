"""v1.4.0 unrestricted-flowsheet test suite.

Covers:
- Custom flowsheet builder accepts arbitrarily large unit counts (N = 15).
- Sequential N-unit chain produces exactly N-1 user-visible connection links.
- 3-sheet Excel export round-trips through openpyxl with all sheets present.
- Custom-path determinism (build/solve twice → identical KPI within tolerance).
- Iteration slider in app_streamlit.py reads min=1, max=1500.
- Version string is consistent across __init__.py, pyproject.toml,
  and the app_streamlit.py caption import.

Layer-boundary note: this test imports from ``pse_ecosystem.ui.flowsheet_service``
(the only Layer-3 bridge), ``pse_ecosystem.solvers.*``, and
``pse_ecosystem.core.contracts`` — same envelope as the UI.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import pytest

from pse_ecosystem import __version__ as PSE_VERSION
from pse_ecosystem.core.contracts import SolveMode
from pse_ecosystem.solvers.orchestrator import Orchestrator
from pse_ecosystem.solvers.slp import SLPConfig
from pse_ecosystem.ui.flowsheet_service import (
    build_custom_flowsheet,
    from_native,
    si_baseline_of,
    supported_display_units,
    to_native,
)

# ── Reuse the canonical 7-unit fixture from the assembly-logic suite ──────────
from tests.test_ui_assembly_logic import SEVEN_UNIT_CONFIG, SYNGAS_6


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_linear_chain(n: int) -> dict:
    """Build an N-unit chain of CoolerHFs (linear, single inlet → single outlet).

    Each cooler shares the SYNGAS_6 component list and a fixed T_out_K.
    Returns the config dict consumed by ``build_custom_flowsheet``.
    """
    units = [
        {
            "type": "CoolerHF",
            "id": f"cooler_{i}",
            "params": {"components": list(SYNGAS_6), "T_out_K": 300.0 + i},
        }
        for i in range(n)
    ]
    connections = [
        {"from_unit": f"cooler_{i}", "to_unit": f"cooler_{i + 1}"}
        for i in range(n - 1)
    ]
    return {"units": units, "connections": connections}


def _build_xlsx_bytes(result, flowsheet) -> bytes:
    """Mirror of the Streamlit Excel exporter in app_streamlit.py.

    Kept inline here (not factored out of the UI) so this test can run headless
    without booting Streamlit. Any change to the UI exporter should be mirrored
    here — this test exists to catch round-trip regressions.
    """
    from pse_ecosystem.ui.app_streamlit import _infer_si_unit

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        stream_rows = []
        for k, v in result.x.items():
            parts = k.split(".")
            var_name = ".".join(parts[2:]) if len(parts) >= 3 else k
            stream_rows.append({
                "Equipment": parts[0] if len(parts) >= 3 else "",
                "Port":      parts[1] if len(parts) >= 3 else "",
                "Variable":  var_name,
                "Value":     v,
                "SI Unit":   _infer_si_unit(var_name),
            })
        pd.DataFrame(stream_rows).to_excel(writer, sheet_name="Stream Table", index=False)

        perf_rows = []
        for unit in flowsheet.units:
            try:
                for kk, vv in unit.kpis(result.x).items():
                    perf_rows.append({
                        "Equipment": unit.unit_id,
                        "KPI":       kk,
                        "Value":     vv,
                        "SI Unit":   _infer_si_unit(kk),
                    })
            except Exception:
                pass
        if not perf_rows:
            perf_rows = [
                {"Equipment": "all", "KPI": k, "Value": v, "SI Unit": _infer_si_unit(k)}
                for k, v in result.kpis.items()
            ]
        pd.DataFrame(perf_rows).to_excel(writer, sheet_name="Unit Performance", index=False)

        summary = [
            {"Field": "Status",     "Value": str(result.status).split(".")[-1]},
            {"Field": "Iterations", "Value": result.iterations},
            {"Field": "Objective",  "Value": result.objective},
            {"Field": "Converged",  "Value": result.converged},
            {"Field": "Message",    "Value": result.message},
        ]
        pd.DataFrame(summary).to_excel(writer, sheet_name="Optimization Summary", index=False)

    return buf.getvalue()


# ── Tests: unrestricted scaling ───────────────────────────────────────────────


@pytest.mark.parametrize("n_units", [8, 12, 15])
def test_custom_builder_accepts_large_chain(n_units: int):
    """The v1.3.2 hard cap was N=10; v1.4.0 must accept N>=15."""
    fs = build_custom_flowsheet(_make_linear_chain(n_units))
    assert len(fs.units) == n_units


@pytest.mark.parametrize("n_units", [2, 7, 15])
def test_sequential_chain_yields_n_minus_one_stream_links(n_units: int):
    """The user-visible 'connection count' equals N-1 for a sequential chain.

    Internal port-variable equalities (fs.connections) are higher (one per
    species + T + P per link); they are correct but cosmetically demoted to
    a caption in the v1.4.0 UI.
    """
    cfg = _make_linear_chain(n_units)
    n_streams = len(cfg["connections"])
    assert n_streams == n_units - 1

    fs = build_custom_flowsheet(cfg)
    assert len(fs.connections) >= n_streams, (
        f"Backend produced {len(fs.connections)} variable equalities for "
        f"{n_streams} stream links — expected >= n_streams."
    )


# ── Tests: Excel export round-trip ────────────────────────────────────────────


def test_excel_export_3_sheets_roundtrip():
    """Build a 7-unit chain, solve it, export to xlsx, reopen via openpyxl.

    Also asserts the v1.4.0 UMS-tagged columns: every numeric sheet carries
    an explicit 'SI Unit' column so values are never ambiguous.
    """
    openpyxl = pytest.importorskip("openpyxl")

    fs = build_custom_flowsheet(SEVEN_UNIT_CONFIG)
    result = Orchestrator(fs, SolveMode.FIXED_LP, slp_config=SLPConfig(max_iter=20)).solve()
    data = _build_xlsx_bytes(result, fs)

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    expected = {"Stream Table", "Unit Performance", "Optimization Summary"}
    assert expected.issubset(set(wb.sheetnames)), (
        f"Missing sheets. Got {wb.sheetnames}, expected superset of {expected}."
    )
    for name in expected:
        ws = wb[name]
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) >= 2, (
            f"Sheet '{name}' has only {len(rows)} row(s) (header + data expected)."
        )

    # UMS: Stream Table must carry an SI Unit column.
    ws = wb["Stream Table"]
    header = [c for c in next(ws.iter_rows(values_only=True))]
    assert "SI Unit" in header, (
        f"Stream Table missing 'SI Unit' column (v1.4.0 UMS). Header: {header}"
    )
    assert "Equipment" in header, (
        f"Stream Table missing 'Equipment' column. Header: {header}"
    )

    # UMS: Unit Performance must also carry an SI Unit column.
    ws = wb["Unit Performance"]
    header = [c for c in next(ws.iter_rows(values_only=True))]
    assert "SI Unit" in header, (
        f"Unit Performance missing 'SI Unit' column (v1.4.0 UMS). Header: {header}"
    )


# ── Tests: custom-path determinism (parity surrogate) ─────────────────────────


def test_custom_path_is_deterministic_on_seven_unit_chain():
    """Building + solving the same custom config twice yields identical results.

    The user brief asks for 'verification parity' between custom-built and
    pre-built industrial templates. Per the v1.4.0 plan, no pre-built 7-unit
    template exists — instead we assert the custom path is itself deterministic
    via Orchestrator.solve(), which is the single compile entry both paths use.

    The 7-unit chain mixes linear and non-linear units; at the low iteration
    cap used here the solver may not converge to a finite objective, but the
    determinism property (same config → bit-identical solution variables)
    must hold regardless of convergence.
    """
    import math

    cfg_a = SEVEN_UNIT_CONFIG
    cfg_b = {**SEVEN_UNIT_CONFIG}  # same dict; two independent builds

    fs_a = build_custom_flowsheet(cfg_a)
    fs_b = build_custom_flowsheet(cfg_b)

    cfg = SLPConfig(max_iter=20)
    res_a = Orchestrator(fs_a, SolveMode.FIXED_LP, slp_config=cfg).solve()
    res_b = Orchestrator(fs_b, SolveMode.FIXED_LP, slp_config=cfg).solve()

    # Determinism: identical variable vector (NaN-aware: NaN counts as equal).
    assert set(res_a.x.keys()) == set(res_b.x.keys()), (
        "Variable name sets differ between two builds of the same config."
    )
    mismatches = []
    for name, value_a in res_a.x.items():
        value_b = res_b.x[name]
        both_nan = (
            isinstance(value_a, float) and isinstance(value_b, float)
            and math.isnan(value_a) and math.isnan(value_b)
        )
        if both_nan:
            continue
        if not (abs(value_a - value_b) <= max(1e-9, 1e-9 * max(abs(value_a), abs(value_b)))):
            mismatches.append((name, value_a, value_b))
    assert not mismatches, (
        f"Custom path non-deterministic on {len(mismatches)} variables. "
        f"First few: {mismatches[:5]}"
    )

    # Convergence status must also be identical.
    assert res_a.status == res_b.status, (
        f"Solver status differs: {res_a.status} vs {res_b.status}"
    )


# ── Tests: source-level guards on UI widgets ──────────────────────────────────


def _ui_sources_concat() -> str:
    """Concatenate every Python source file under pse_ecosystem/ui/ so v1.6.1
    page-module splits don't break content-grep tests."""
    ui_root = REPO_ROOT / "pse_ecosystem" / "ui"
    return "\n".join(
        p.read_text(encoding="utf-8") for p in ui_root.rglob("*.py")
    )


def test_iteration_slider_bounds_in_source():
    """The Solver Monitor slider must read min=1, max=1500 (v1.4.0 lift).

    Searches across the entire ``pse_ecosystem/ui/`` tree since v1.6.1
    moved page bodies into ``pages/``.
    """
    src = _ui_sources_concat()
    m = re.search(r'st\.slider\(\s*"Max iterations",\s*(\d+)\s*,\s*(\d+)\s*,\s*\d+\s*\)', src)
    assert m, "Could not locate the 'Max iterations' slider in pse_ecosystem/ui/."
    lo, hi = int(m.group(1)), int(m.group(2))
    assert lo == 1,    f"Expected slider min_value=1, got {lo}"
    assert hi == 1500, f"Expected slider max_value=1500, got {hi}"


def test_custom_builder_has_no_unit_count_cap():
    """The number_input for unit count must not declare a max_value."""
    src = _ui_sources_concat()
    m = re.search(r'st\.number_input\(\s*"Number of units"[^)]*\)', src)
    assert m, "Could not locate the 'Number of units' input in pse_ecosystem/ui/."
    assert "max_value" not in m.group(0), (
        f"Unit count input still declares max_value (v1.4.0 must be uncapped). "
        f"Found: {m.group(0)}"
    )


def test_progressive_tightening_default_on():
    """v1.4.0 ships progressive tightening checkbox defaulted to True."""
    src = _ui_sources_concat()
    m = re.search(
        r'st\.checkbox\(\s*"Progressive tightening"[^)]*?value=(True|False)',
        src,
        flags=re.DOTALL,
    )
    assert m, "Could not locate the 'Progressive tightening' checkbox."
    assert m.group(1) == "True", "Progressive tightening must default to True in v1.4.0."


# ── Tests: version consistency ────────────────────────────────────────────────


def test_version_is_v153():
    assert PSE_VERSION == "1.5.3", f"pse_ecosystem.__version__ = {PSE_VERSION!r}"


def test_pyproject_version_matches_package():
    toml_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', toml_text, flags=re.MULTILINE)
    assert m, "Could not parse version from pyproject.toml"
    assert m.group(1) == PSE_VERSION, (
        f"pyproject.toml version ({m.group(1)!r}) != pse_ecosystem.__version__ ({PSE_VERSION!r})"
    )


def test_app_streamlit_caption_uses_imported_version():
    """The Dashboard caption must derive from pse_ecosystem.__version__, not a literal.

    v1.6.1: searches across the whole ``pse_ecosystem/ui/`` tree since the
    Dashboard moved into ``pages/dashboard.py``.
    """
    src = _ui_sources_concat()
    assert "from pse_ecosystem import __version__" in src, (
        "pse_ecosystem/ui must import __version__ from the package "
        "(single source of truth)."
    )
    assert 'st.caption("v1.3.2' not in src, (
        "Stale 'v1.3.2' literal still present in pse_ecosystem/ui."
    )


# ── Tests: Unit Management System (UMS) ───────────────────────────────────────


class TestUnitConversions:
    """Round-trip checks for the Layer-1 display↔native conversion helpers."""

    def test_temperature_celsius_to_kelvin(self):
        assert to_native(25.0, "°C", "K") == pytest.approx(298.15, abs=1e-9)

    def test_temperature_kelvin_to_celsius(self):
        assert to_native(298.15, "K", "°C") == pytest.approx(25.0, abs=1e-9)

    def test_temperature_fahrenheit_to_kelvin(self):
        # 32 °F = 273.15 K, 212 °F = 373.15 K
        assert to_native(32.0,  "°F", "K") == pytest.approx(273.15, abs=1e-9)
        assert to_native(212.0, "°F", "K") == pytest.approx(373.15, abs=1e-9)

    def test_temperature_round_trip_through_three_units(self):
        v0 = 800.0  # °C, like T_gasifier_C default
        v_k = to_native(v0, "°C", "K")
        v_f = from_native(v_k, "K", "°F")
        v_back = to_native(v_f, "°F", "°C")
        assert v_back == pytest.approx(v0, abs=1e-6)

    def test_pressure_atm_to_pa(self):
        assert to_native(1.0, "atm", "Pa") == pytest.approx(101325.0, abs=1e-6)

    def test_pressure_bar_to_pa(self):
        assert to_native(5.0, "bar", "Pa") == pytest.approx(5e5, abs=1e-6)

    def test_pressure_psi_to_bar(self):
        # 14.5038 psi ≈ 1 bar
        assert to_native(14.5038, "psi", "bar") == pytest.approx(1.0, rel=1e-4)

    def test_mass_flow_t_per_h_to_kg_per_s(self):
        assert to_native(3.6, "t/h", "kg/s") == pytest.approx(1.0, abs=1e-9)

    def test_power_kw_to_w(self):
        assert to_native(5.0, "kW", "W") == pytest.approx(5000.0, abs=1e-9)

    def test_energy_mj_to_kj(self):
        assert to_native(1.0, "MJ", "kJ") == pytest.approx(1000.0, abs=1e-9)

    def test_same_unit_is_identity(self):
        for u, val in [("K", 350.0), ("Pa", 101325.0), ("kg/s", 2.5), ("kW", 100.0)]:
            assert to_native(val, u, u) == val

    def test_no_conversion_path_returns_value(self):
        # "—" (dimensionless), "W/K" (UA product), "mol/s" — not in any family.
        assert to_native(0.78, "—",      "—")      == 0.78
        assert to_native(5000.0, "W/K",  "W/K")    == 5000.0
        assert to_native(50.0, "mol/s",  "mol/s")  == 50.0


class TestSupportedDisplayUnits:
    def test_temperature_family_has_three_units(self):
        units = supported_display_units("°C")
        assert set(units) == {"K", "°C", "°F"}

    def test_pressure_family_has_five_units(self):
        units = supported_display_units("Pa")
        assert set(units) == {"Pa", "kPa", "bar", "atm", "psi"}

    def test_dimensionless_has_no_alternatives(self):
        assert supported_display_units("—") == []
        assert supported_display_units("W/K") == []
        assert supported_display_units("mol/s") == []

    def test_si_baseline_for_celsius_is_kelvin(self):
        assert si_baseline_of("°C") == "K"

    def test_si_baseline_for_atm_is_pa(self):
        assert si_baseline_of("atm") == "Pa"

    def test_si_baseline_for_unknown_is_none(self):
        assert si_baseline_of("—") is None
        assert si_baseline_of("W/K") is None


class TestExcelUnitInference:
    """The Excel exporter's _infer_si_unit() heuristic for variable names."""

    def test_inference_for_canonical_names(self):
        from pse_ecosystem.ui.app_streamlit import _infer_si_unit
        cases = {
            "T":         "K",
            "T_in":      "K",
            "T_out":     "K",
            "P":         "Pa",
            "P_out":     "Pa",
            "P_out_Pa":  "Pa",
            "T_out_K":   "K",
            "F_H2":      "kg/s",
            "F_CO2":     "kg/s",
            "n_H2":      "mol/s",
            "X_CO":      "—",
            "W_shaft":   "W",
            "duty_kW":   "kW",
            "Y_H2_kg_per_h": "kg/h",
        }
        for var, expected in cases.items():
            assert _infer_si_unit(var) == expected, (
                f"_infer_si_unit({var!r}) returned {_infer_si_unit(var)!r}, expected {expected!r}"
            )

    def test_inference_empty_for_unrecognised(self):
        from pse_ecosystem.ui.app_streamlit import _infer_si_unit
        assert _infer_si_unit("foo") == ""
        assert _infer_si_unit("") == ""


# ── v1.4.0 audit — extended UMS edge cases (M14) ─────────────────────────────


class TestUMSEdgeCases:
    """NaN / Inf / extreme-value behaviour of the conversion helpers."""

    def test_nan_input_propagates_nan(self):
        import math
        assert math.isnan(to_native(float("nan"), "°C", "K"))
        assert math.isnan(from_native(float("nan"), "K", "°F"))

    def test_inf_input_propagates_sign(self):
        import math
        assert math.isinf(to_native(float("inf"),  "°C", "K"))
        assert math.isinf(to_native(float("-inf"), "°C", "K"))

    def test_absolute_zero_round_trip(self):
        # 0 K is the absolute zero floor; check the round-trip closes exactly.
        assert to_native(0.0, "K", "K") == 0.0
        assert from_native(0.0, "K", "°C") == pytest.approx(-273.15, abs=1e-9)
        assert from_native(0.0, "K", "°F") == pytest.approx(-459.67, abs=1e-2)

    def test_high_pressure_round_trip(self):
        # 1e8 Pa = 1000 bar; well above any realistic process condition.
        v = 1.0e8
        b = from_native(v, "Pa", "bar")
        assert b == pytest.approx(1000.0, rel=1e-9)
        assert to_native(b, "bar", "Pa") == pytest.approx(v, rel=1e-9)


# ── v1.4.0 audit — solver-mode smoke tests (H12) ──────────────────────────────
#
# Pre-v1.4.0 only FIXED_LP and FLEXIBLE_MILP were exercised by the test suite;
# NLP_IPOPT / TRUST_REGION / ADAPTIVE shipped without an end-to-end guard
# (which is how the TRF step_norm inversion in trust_region_driver.py:209
# went unnoticed). These smoke tests are intentionally permissive: they
# accept either CONVERGED or MAX_ITER as a successful run — the goal is to
# guarantee the dispatch path executes without raising.


def _simple_linear_fs():
    """Single-unit linear flowsheet (BiomassStorageHF). Cheapest possible NLP
    target — every solver mode should at minimum return a SolveResult."""
    return build_custom_flowsheet({
        "units": [
            {"type": "BiomassStorageHF", "id": "storage", "params": {}},
        ],
        "connections": [],
    })


def _assert_returns_result(result, mode_name: str):
    from pse_ecosystem.core.contracts import SolverStatus
    assert result is not None, f"{mode_name}: Orchestrator returned None"
    # CONVERGED or MAX_ITER are both acceptable — the bug we're guarding
    # against is a code-path exception or a NUMERICAL_ERROR status.
    acceptable = {SolverStatus.CONVERGED, SolverStatus.MAX_ITER}
    assert result.status in acceptable, (
        f"{mode_name} returned status={result.status}; expected one of {acceptable}. "
        f"Message: {result.message!r}"
    )


def test_solver_mode_nlp_ipopt_smoke():
    pytest.importorskip("scipy.optimize")
    fs = _simple_linear_fs()
    result = Orchestrator(fs, SolveMode.NLP_IPOPT,
                          slp_config=SLPConfig(max_iter=5)).solve()
    _assert_returns_result(result, "NLP_IPOPT")


def test_solver_mode_trust_region_smoke():
    fs = _simple_linear_fs()
    result = Orchestrator(fs, SolveMode.TRUST_REGION,
                          slp_config=SLPConfig(max_iter=5)).solve()
    _assert_returns_result(result, "TRUST_REGION")


def test_solver_mode_adaptive_smoke():
    fs = _simple_linear_fs()
    result = Orchestrator(fs, SolveMode.ADAPTIVE,
                          slp_config=SLPConfig(max_iter=5)).solve()
    _assert_returns_result(result, "ADAPTIVE")


def test_trf_convergence_not_spurious_on_first_accepted_step():
    """Guards against the v1.3.x TRF bug where the convergence check fired on
    the first accepted step because step_norm was forced to 0 (audit C1).

    A flowsheet that genuinely needs > 1 iteration must not return after one.
    """
    fs = build_custom_flowsheet({
        "units": [
            {"type": "BiomassStorageHF", "id": "storage", "params": {}},
            {"type": "BiomassGasifierHF", "id": "gas",
             "params": {"T_gasifier_C": 800.0, "gasifying_agent": "Steam"}},
        ],
        "connections": [{"from_unit": "storage", "to_unit": "gas"}],
    })
    result = Orchestrator(fs, SolveMode.TRUST_REGION,
                          slp_config=SLPConfig(max_iter=20)).solve()
    # The fix forces step_norm = +inf on rejected steps and the real step
    # magnitude on accepted ones. Genuine convergence in 1 iteration on a
    # 2-unit non-linear chain is unrealistic; demand at least 2.
    if result.status.name == "CONVERGED":
        assert result.iterations >= 2, (
            f"TRF reported CONVERGED after only {result.iterations} iteration(s) — "
            f"the spurious-convergence guard (audit C1) regressed."
        )


# ── v1.4.0 audit — progressive-tightening behaviour test (M13) ────────────────


def test_progressive_tightening_loose_tolerances_in_early_iterations():
    """The pre-v1.4.0 source-level check only asserted the default is True.

    This test exercises the runtime schedule: at low iteration count under
    progressive_tightening the SLP effective tolerances are an order of
    magnitude looser than the cfg defaults (audit M13).
    """
    from pse_ecosystem.solvers.slp import _tighten, SLPConfig
    cfg = SLPConfig(max_iter=100, eps_x=1e-4, eps_f=1e-4, eps_kpi=1e-3)

    # Phase 1: k < 20% of max_iter (here k=5 of 100). Tolerances 100× looser.
    eps_x_early, eps_f_early, eps_kpi_early = _tighten(cfg, k=5)
    assert eps_x_early == pytest.approx(cfg.eps_x * 100.0)
    assert eps_f_early == pytest.approx(cfg.eps_f * 100.0)

    # Phase 2: 20% ≤ k < 60% (here k=30). Tolerances 10× looser.
    eps_x_mid, eps_f_mid, _ = _tighten(cfg, k=30)
    assert eps_x_mid == pytest.approx(cfg.eps_x * 10.0)
    assert eps_f_mid == pytest.approx(cfg.eps_f * 10.0)

    # Phase 3: k ≥ 60% (here k=80). Tolerances at the cfg defaults.
    eps_x_tight, eps_f_tight, eps_kpi_tight = _tighten(cfg, k=80)
    assert eps_x_tight == pytest.approx(cfg.eps_x)
    assert eps_f_tight == pytest.approx(cfg.eps_f)
    assert eps_kpi_tight == pytest.approx(cfg.eps_kpi)


# ── v1.4.0 audit — UI registry coverage (H11) ─────────────────────────────────
#
# Every entry in AVAILABLE_UNITS must be instantiable via _instantiate_unit
# with empty params (i.e. defaults must exist and be self-consistent). This
# is the regression guard for the H11 expansion that added Pump, Valve,
# ShellTubeHX, H2SeparatorPSA, GibbsReactor, EquilibriumReactor, and
# DistillationHF to the UI catalogue.


def test_every_available_unit_instantiates_with_defaults():
    from pse_ecosystem.ui.flowsheet_service import AVAILABLE_UNITS, _instantiate_unit

    failures = []
    for utype in AVAILABLE_UNITS:
        try:
            obj = _instantiate_unit(utype, f"{utype.lower()}_test", {})
            assert obj is not None
        except Exception as exc:  # noqa: BLE001
            failures.append((utype, repr(exc)))

    assert not failures, (
        "AVAILABLE_UNITS entries that failed to instantiate with empty params:\n"
        + "\n".join(f"  - {u}: {e}" for u, e in failures)
    )


# ── v1.4.0 audit — template-vs-custom numerical parity (M12) ──────────────────


def test_template_path_and_custom_path_yield_identical_solution():
    """A flowsheet built via direct Layer-3 factory and one built via
    ``build_custom_flowsheet`` with matching params must produce a
    bit-identical solver result.

    Pre-v1.4.0 the audit only checked custom-path determinism (build the
    same custom config twice → same output). This is a stronger test:
    the two *different* construction paths converge at the same
    ``BaseFlowsheet`` and so must yield identical Orchestrator output.
    Confirms the audit M12 guarantee that the docs claim is structural.
    """
    import math
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
    from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF, CoolerHFParams

    components = ["H2", "CO", "CO2"]

    # Path A — pre-built / direct factory construction (what load_template does).
    cooler_direct = CoolerHF(
        "cooler_A", components, CoolerHFParams(T_out_K=310.0, feed_max=1_000.0),
    )
    fs_direct = BaseFlowsheet(
        name="parity.direct", units=[cooler_direct], connections=[],
    )

    # Path B — Custom Builder route through _instantiate_unit + build_custom_flowsheet.
    fs_custom = build_custom_flowsheet({
        "units": [{
            "type": "CoolerHF",
            "id": "cooler_A",
            "params": {"components": components, "T_out_K": 310.0, "feed_max": 1_000.0},
        }],
        "connections": [],
    })

    cfg = SLPConfig(max_iter=20)
    res_direct = Orchestrator(fs_direct, SolveMode.FIXED_LP, slp_config=cfg).solve()
    res_custom = Orchestrator(fs_custom, SolveMode.FIXED_LP, slp_config=cfg).solve()

    # Status, objective, and the full solution vector must agree.
    assert res_direct.status == res_custom.status, (
        f"status drift: direct={res_direct.status}, custom={res_custom.status}"
    )
    assert set(res_direct.x.keys()) == set(res_custom.x.keys()), (
        "Variable name sets diverge between template and custom paths — "
        "the Layer-3 unit instance was not configured identically."
    )
    mismatches = []
    for name, vd in res_direct.x.items():
        vc = res_custom.x[name]
        if isinstance(vd, float) and isinstance(vc, float) and math.isnan(vd) and math.isnan(vc):
            continue
        if not (abs(vd - vc) <= max(1e-9, 1e-9 * max(abs(vd), abs(vc)))):
            mismatches.append((name, vd, vc))
    assert not mismatches, (
        f"Template/custom parity broken on {len(mismatches)} variable(s). "
        f"First few: {mismatches[:5]}"
    )


# ── v1.4.0-HOTFIX: flowsheet connection validation (general fix) ──────────────


class TestFlowsheetValidateConnections:
    """validate() must reject connections whose variable names are not produced
    by any unit in the flowsheet.  This prevents silent phantom-connection
    failures where units solve independently and the SLP reports CONVERGED
    despite inter-unit mass/energy balances being completely violated.
    """

    def _single_cooler_fs(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
        unit = CoolerHF("cooler", ["H2", "CO"])
        return BaseFlowsheet(name="test_fs", units=[unit])

    def test_valid_flowsheet_with_no_connections_passes(self):
        fs = self._single_cooler_fs()
        fs.validate()  # must not raise

    def test_valid_connection_between_real_variables_passes(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
        a = CoolerHF("cooler_a", ["H2"])
        b = CoolerHF("cooler_b", ["H2"])
        fs = BaseFlowsheet(name="chain", units=[a, b])
        fs.connections.append(
            Connection(var_a="cooler_a.outlet.F_H2", var_b="cooler_b.inlet.F_H2")
        )
        fs.validate()  # must not raise — both vars exist in unit variable lists

    def test_phantom_var_a_raises_value_error(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
        unit = CoolerHF("cooler", ["H2"])
        fs = BaseFlowsheet(name="bad", units=[unit])
        fs.connections.append(
            Connection(var_a="phantom.outlet.F_H2", var_b="cooler.inlet.F_H2")
        )
        with pytest.raises(ValueError, match="connections"):
            fs.validate()

    def test_phantom_var_b_raises_value_error(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
        unit = CoolerHF("cooler", ["H2"])
        fs = BaseFlowsheet(name="bad", units=[unit])
        fs.connections.append(
            Connection(var_a="cooler.outlet.F_H2", var_b="phantom.inlet.F_H2")
        )
        with pytest.raises(ValueError, match="connections"):
            fs.validate()

    def test_error_message_names_the_bad_variable(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
        unit = CoolerHF("cooler", ["H2"])
        fs = BaseFlowsheet(name="bad", units=[unit])
        fs.connections.append(
            Connection(var_a="typo.outlet.F_H2", var_b="cooler.inlet.F_H2")
        )
        with pytest.raises(ValueError) as exc_info:
            fs.validate()
        assert "typo.outlet.F_H2" in str(exc_info.value)

    def test_multiple_bad_connections_all_reported(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet, Connection
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF
        unit = CoolerHF("cooler", ["H2"])
        fs = BaseFlowsheet(name="bad", units=[unit])
        fs.connections.append(Connection(var_a="ghost_a.outlet.F_H2", var_b="ghost_b.inlet.F_H2"))
        with pytest.raises(ValueError) as exc_info:
            fs.validate()
        msg = str(exc_info.value)
        assert "ghost_a.outlet.F_H2" in msg or "ghost_b.inlet.F_H2" in msg


# ── v1.4.0-HOTFIX: on_change unit auto-conversion callback logic ──────────────


class TestUnitAutoConversionCallback:
    """Verify the conversion logic that backs the on_change callback.

    The callback does:
        nat_v  = to_native(old_v,  old_unit, native_unit)
        new_v  = from_native(nat_v, native_unit, new_unit)

    These tests confirm the composition is correct for the cases that
    matter in the Custom Flowsheet Builder (temperature, pressure, mass flow).
    """

    def test_celsius_to_kelvin_800(self):
        nat = to_native(800.0, "°C", "°C")    # native_unit == display_unit → no-op
        new = from_native(nat, "°C", "K")
        assert new == pytest.approx(1073.15, abs=1e-9)

    def test_kelvin_to_celsius_1073(self):
        nat = to_native(1073.15, "K", "°C")   # K displayed, native is °C
        new = from_native(nat, "°C", "°C")    # going back to °C
        assert new == pytest.approx(800.0, abs=1e-9)

    def test_bar_to_pa_5bar(self):
        nat = to_native(5.0, "bar", "Pa")
        new = from_native(nat, "Pa", "Pa")
        assert new == pytest.approx(500_000.0, abs=1.0)

    def test_pa_to_bar_500000(self):
        nat = to_native(500_000.0, "Pa", "Pa")
        new = from_native(nat, "Pa", "bar")
        assert new == pytest.approx(5.0, rel=1e-6)

    def test_kgh_to_kgs_3600(self):
        nat = to_native(3600.0, "kg/h", "kg/s")
        new = from_native(nat, "kg/s", "kg/s")
        assert new == pytest.approx(1.0, abs=1e-9)

    def test_kgs_to_kgh_1(self):
        nat = to_native(1.0, "kg/s", "kg/s")
        new = from_native(nat, "kg/s", "kg/h")
        assert new == pytest.approx(3600.0, abs=1e-6)

    def test_same_unit_no_change(self):
        for val, unit in [(800.0, "°C"), (101325.0, "Pa"), (1.0, "kg/s")]:
            nat = to_native(val, unit, unit)
            new = from_native(nat, unit, unit)
            assert new == pytest.approx(val, rel=1e-9)


# ── v1.4.1: Physics Safety Net — bound-saturation guard ──────────────────────


class TestBoundSaturationGuard:
    """Guard against the v1.4.0 Excel anomaly pattern: the LP saturates a
    variable at a default unit bound (e.g. CoolerHFParams.feed_max=1000) and
    the SLP reports CONVERGED on what is actually a bound-capped, possibly
    non-physical solution. The SLP now populates SolveResult.bound_active
    with the offending names; SLPConfig.fail_on_bound_saturation=True
    upgrades that warning to a NUMERICAL_ERROR status.
    """

    def _saturated_cooler_fs(self):
        from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
        from pse_ecosystem.models.heat_exchangers.cooler_hf import (
            CoolerHF, CoolerHFParams,
        )
        unit = CoolerHF("c", ["H2"], CoolerHFParams(feed_max=10.0))
        fs = BaseFlowsheet(name="sat", units=[unit])
        fs.extra_bounds = {"c.inlet.F_H2": (10.0, 10.0)}  # pin inlet at the cap
        return fs

    def test_solveresult_field_defaults_to_empty(self):
        from pse_ecosystem.core.contracts import SolveResult, SolverStatus, SolveMode
        r = SolveResult(status=SolverStatus.CONVERGED, mode=SolveMode.FIXED_LP)
        assert r.bound_active == []

    def test_outlet_at_feed_max_is_flagged(self):
        """Cooler inlet pinned at 10 (lb==ub) forces outlet up to ub=10 via
        the mass-balance equality. Outlet is flagged; inlet is excluded
        because intentionally-fixed variables don't count as physics
        violations."""
        result = Orchestrator(self._saturated_cooler_fs(), SolveMode.FIXED_LP).solve()
        assert result.status.name == "CONVERGED"
        assert "c.outlet.F_H2" in result.bound_active
        assert "c.inlet.F_H2" not in result.bound_active  # lb == ub excluded

    def test_fail_on_bound_saturation_opt_in(self):
        """With the opt-in flag, the same scenario returns NUMERICAL_ERROR
        and the message names the offending variable so the user can act."""
        from pse_ecosystem.solvers.slp import SLPConfig
        cfg = SLPConfig(fail_on_bound_saturation=True)
        result = Orchestrator(
            self._saturated_cooler_fs(), SolveMode.FIXED_LP, slp_config=cfg
        ).solve()
        assert result.status.name == "NUMERICAL_ERROR"
        assert "c.outlet.F_H2" in result.message
        # bound_active is still populated so the UI can show details.
        assert "c.outlet.F_H2" in result.bound_active
