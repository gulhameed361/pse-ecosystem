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
from pse_ecosystem.ui.flowsheet_service import build_custom_flowsheet

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
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        stream_rows = []
        for k, v in result.x.items():
            parts = k.split(".")
            if len(parts) >= 3:
                stream_rows.append({
                    "Unit": parts[0],
                    "Port": parts[1],
                    "Variable": ".".join(parts[2:]),
                    "Value": v,
                })
            else:
                stream_rows.append({"Unit": "", "Port": "", "Variable": k, "Value": v})
        pd.DataFrame(stream_rows).to_excel(writer, sheet_name="Stream Table", index=False)

        perf_rows = []
        for unit in flowsheet.units:
            try:
                for kk, vv in unit.kpis(result.x).items():
                    perf_rows.append({"Unit": unit.unit_id, "KPI": kk, "Value": vv})
            except Exception:
                pass
        if not perf_rows:
            perf_rows = [{"Unit": "all", "KPI": k, "Value": v}
                         for k, v in result.kpis.items()]
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
    """Build a 7-unit chain, solve it, export to xlsx, reopen via openpyxl."""
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


def test_iteration_slider_bounds_in_source():
    """The Solver Monitor slider must read min=1, max=1500 (v1.4.0 lift)."""
    src = (REPO_ROOT / "pse_ecosystem" / "ui" / "app_streamlit.py").read_text(encoding="utf-8")
    m = re.search(r'st\.slider\(\s*"Max iterations",\s*(\d+)\s*,\s*(\d+)\s*,\s*\d+\s*\)', src)
    assert m, "Could not locate the 'Max iterations' slider in app_streamlit.py"
    lo, hi = int(m.group(1)), int(m.group(2))
    assert lo == 1,    f"Expected slider min_value=1, got {lo}"
    assert hi == 1500, f"Expected slider max_value=1500, got {hi}"


def test_custom_builder_has_no_unit_count_cap():
    """The number_input for unit count must not declare a max_value."""
    src = (REPO_ROOT / "pse_ecosystem" / "ui" / "app_streamlit.py").read_text(encoding="utf-8")
    m = re.search(r'st\.number_input\(\s*"Number of units"[^)]*\)', src)
    assert m, "Could not locate the 'Number of units' input in app_streamlit.py"
    assert "max_value" not in m.group(0), (
        f"Unit count input still declares max_value (v1.4.0 must be uncapped). "
        f"Found: {m.group(0)}"
    )


def test_progressive_tightening_default_on():
    """v1.4.0 ships progressive tightening checkbox defaulted to True."""
    src = (REPO_ROOT / "pse_ecosystem" / "ui" / "app_streamlit.py").read_text(encoding="utf-8")
    # match the checkbox declaration up to its value=... clause
    m = re.search(
        r'st\.checkbox\(\s*"Progressive tightening"[^)]*?value=(True|False)',
        src,
        flags=re.DOTALL,
    )
    assert m, "Could not locate the 'Progressive tightening' checkbox."
    assert m.group(1) == "True", "Progressive tightening must default to True in v1.4.0."


# ── Tests: version consistency ────────────────────────────────────────────────


def test_version_is_v140():
    assert PSE_VERSION == "1.4.0", f"pse_ecosystem.__version__ = {PSE_VERSION!r}"


def test_pyproject_version_matches_package():
    toml_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', toml_text, flags=re.MULTILINE)
    assert m, "Could not parse version from pyproject.toml"
    assert m.group(1) == PSE_VERSION, (
        f"pyproject.toml version ({m.group(1)!r}) != pse_ecosystem.__version__ ({PSE_VERSION!r})"
    )


def test_app_streamlit_caption_uses_imported_version():
    """The Dashboard caption must derive from pse_ecosystem.__version__, not a literal."""
    src = (REPO_ROOT / "pse_ecosystem" / "ui" / "app_streamlit.py").read_text(encoding="utf-8")
    assert "from pse_ecosystem import __version__" in src, (
        "app_streamlit.py must import __version__ from the package (single source of truth)."
    )
    # And the literal v1.3.2 caption must be gone.
    assert 'st.caption("v1.3.2' not in src, (
        "Stale 'v1.3.2' literal still present in app_streamlit.py caption."
    )
