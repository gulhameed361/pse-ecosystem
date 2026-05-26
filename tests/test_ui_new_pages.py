"""Smoke tests for the four new v1.6.1 P.7 Streamlit pages.

These verify that each page module imports cleanly, exposes its
``_page_*`` callable, and is registered in ``app_streamlit.main()`` /
``st.navigation`` so the user can actually reach it from the sidebar.
Full Streamlit interaction is exercised manually; tests here protect
against silent regressions in the wiring.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


_NEW_PAGES = [
    ("pse_ecosystem.ui.pages.validation",      "_page_validation"),
    ("pse_ecosystem.ui.pages.pinch_preview",   "_page_pinch_preview"),
    ("pse_ecosystem.ui.pages.dynamics_studio", "_page_dynamics_studio"),
    ("pse_ecosystem.ui.pages.relief_sizing",   "_page_relief_sizing"),
]


_APP_SRC = (
    Path(__file__).resolve().parent.parent
    / "pse_ecosystem" / "ui" / "app_streamlit.py"
).read_text(encoding="utf-8")


@pytest.mark.parametrize("module_path,callable_name", _NEW_PAGES)
def test_page_module_imports_and_exposes_callable(module_path, callable_name):
    mod = importlib.import_module(module_path)
    assert hasattr(mod, callable_name), (
        f"{module_path} must expose {callable_name}()"
    )
    assert callable(getattr(mod, callable_name))


@pytest.mark.parametrize("module_path,callable_name", _NEW_PAGES)
def test_page_imported_in_app_streamlit(module_path, callable_name):
    """The new page is imported at the top of app_streamlit.py."""
    assert callable_name in _APP_SRC, (
        f"{callable_name} is not imported in app_streamlit.py — sidebar "
        "navigation won't reach it."
    )


def test_st_navigation_lists_all_four_new_pages():
    """st.navigation([...]) must include a Page entry for each new page."""
    for title in ("Validation", "Pinch Preview", "Dynamics Studio", "Relief Sizing"):
        assert f'title="{title}"' in _APP_SRC, (
            f"'{title}' Page missing from st.navigation in app_streamlit.main()."
        )


def test_relief_sizing_uses_size_psv_helper():
    """The relief page wires up the v1.6 size_psv_for_vessel helper."""
    src = (
        Path(__file__).resolve().parent.parent
        / "pse_ecosystem" / "ui" / "pages" / "relief_sizing.py"
    ).read_text(encoding="utf-8")
    assert "size_psv_for_vessel" in src


def test_validation_uses_compute_metrics():
    """The validation page renders MAPE/RMSE via compute_metrics."""
    src = (
        Path(__file__).resolve().parent.parent
        / "pse_ecosystem" / "ui" / "pages" / "validation.py"
    ).read_text(encoding="utf-8")
    assert "compute_metrics" in src
    assert "scatter_data" in src


def test_dynamics_uses_DynamicSimulator_and_Perturbation():
    """The dynamics page wires up the v1.6 dynamics subpackage."""
    src = (
        Path(__file__).resolve().parent.parent
        / "pse_ecosystem" / "ui" / "pages" / "dynamics_studio.py"
    ).read_text(encoding="utf-8")
    assert "DynamicSimulator" in src
    assert "Perturbation" in src


def test_pinch_preview_extract_streams_and_problem_table_present():
    """The pinch page implements its own problem-table helper."""
    from pse_ecosystem.ui.pages.pinch_preview import (
        _extract_streams, _problem_table, _composite_curve,
    )
    assert callable(_extract_streams)
    assert callable(_problem_table)
    assert callable(_composite_curve)


def test_pinch_problem_table_minimal_two_stream_case():
    """Two-stream sanity check: one hot (400→300 K, 100 kW), one cold
    (290→390 K, 100 kW), ΔT_min=10 K → Q_h_min = Q_c_min = 0 in the
    fully integrated limit (CP_hot = CP_cold = 1 kW/K, no pinch deficit)."""
    from pse_ecosystem.ui.pages.pinch_preview import _HotColdStream, _problem_table
    streams = [
        _HotColdStream("HX1", "hot",  400.0, 300.0, 100_000.0, 1000.0),
        _HotColdStream("HX2", "cold", 290.0, 390.0, 100_000.0, 1000.0),
    ]
    Ts, cascade, feasible, Q_h, Q_c, T_pinch = _problem_table(streams, dT_min_K=10.0)
    assert Q_h == pytest.approx(0.0, abs=1.0)
    assert Q_c == pytest.approx(0.0, abs=1.0)
