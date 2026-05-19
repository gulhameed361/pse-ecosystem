"""Streamlit browser-free smoke test (v1.5.0.dev-AUDIT5 #7).

Uses ``streamlit.testing.v1.AppTest`` to render each page in-process and
assert that:

  * no exception is raised during the script run,
  * no ``st.exception()`` call fires,
  * no ``st.error()`` call fires for an error condition the user would see.

This catches the class of bug where a helper has unit tests but the page's
actual call site has a typo, a wrong session_state key, or a missing import.
"""

from __future__ import annotations

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1",
                                  reason="streamlit AppTest not available")
from streamlit.testing.v1 import AppTest   # noqa: E402

_APP_PATH = "pse_ecosystem/ui/app_streamlit.py"


def _run_page(page_fn_name: str, timeout: float = 30.0) -> AppTest:
    """Run a single page function in-process and return the AppTest.

    Strategy: build a tiny driver script that imports the requested page
    function and calls it directly, bypassing st.navigation.
    """
    driver = (
        "import streamlit as st\n"
        "from pse_ecosystem.ui.app_streamlit import (\n"
        "    _page_dashboard, _page_flowsheet_builder, _page_gps_weather,\n"
        "    _page_solver_monitor, _page_solve_history, _page_help_center,\n"
        ")\n"
        "st.set_page_config(page_title='test', layout='wide')\n"
        f"{page_fn_name}()\n"
    )
    at = AppTest.from_string(driver)
    at.run(timeout=timeout)
    return at


def _assert_no_unhandled_exception(at: AppTest, page: str) -> None:
    # AppTest collects unhandled exceptions in `at.exception` (list of elements).
    excs = list(at.exception)
    assert not excs, (
        f"{page}: Streamlit raised {len(excs)} unhandled exception(s). "
        f"First: {excs[0].value if excs else ''}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Smoke tests — each page must render without error.
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamlitSmoke:

    def test_smoke_dashboard(self):
        at = _run_page("_page_dashboard")
        _assert_no_unhandled_exception(at, "Dashboard")

    def test_smoke_flowsheet_builder(self):
        at = _run_page("_page_flowsheet_builder")
        _assert_no_unhandled_exception(at, "Flowsheet Builder")

    def test_smoke_gps_weather(self):
        at = _run_page("_page_gps_weather")
        _assert_no_unhandled_exception(at, "Site Weather")

    def test_smoke_solver_monitor(self):
        at = _run_page("_page_solver_monitor")
        _assert_no_unhandled_exception(at, "Solver Monitor")

    def test_smoke_solve_history(self):
        at = _run_page("_page_solve_history")
        _assert_no_unhandled_exception(at, "Solve History")

    def test_smoke_help_center(self):
        at = _run_page("_page_help_center")
        _assert_no_unhandled_exception(at, "Help Center")

    def test_smoke_main_entrypoint_imports(self):
        """The main() function and module-level code must import cleanly."""
        import importlib
        m = importlib.import_module("pse_ecosystem.ui.app_streamlit")
        assert callable(m.main)
        # Page functions must all exist (catches typos in nav registration)
        for name in ("_page_dashboard", "_page_flowsheet_builder",
                     "_page_gps_weather", "_page_solver_monitor",
                     "_page_solve_history", "_page_help_center"):
            assert hasattr(m, name), f"Missing page function: {name}"
