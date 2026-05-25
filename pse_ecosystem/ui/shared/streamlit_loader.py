"""Optional-dependency loader for Streamlit.

The PSE Ecosystem package can be imported without Streamlit installed
(e.g. for solver-only deployments, CI, or library use). UI pages defer
the import until the page is actually rendered.
"""

from __future__ import annotations


def _require_streamlit():
    try:
        import streamlit as st  # type: ignore
        return st
    except ImportError as exc:
        raise ImportError(
            "streamlit is required. Install with: pip install 'pse_ecosystem[gui]'"
        ) from exc


__all__ = ["_require_streamlit"]
