"""CI wrappers for the script-style audit suites.

Pre-v1.4.0 these audits lived in `tests/*_audit.py` files without a
`def test_*` entry point — pytest could not pick them up and they only
ran when invoked manually with ``python tests/ui_audit.py``.

This module runs each script as a subprocess and asserts exit code 0,
so the full audit fleet now executes under ``pytest tests/``. Audit
runtime varies (industrial_audit calls the full solver on every
template) so each test is allowed a generous timeout.

The biomass_audit suite is already pytest-native (`def test_*`) and is
collected directly via the `python_files = ["test_*.py", "*_audit.py"]`
config in `pyproject.toml`; it does not need a subprocess wrapper.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS = REPO_ROOT / "tests"


def _run_script(rel_path: str, timeout_s: int) -> subprocess.CompletedProcess:
    """Invoke a script-style audit via the current Python interpreter."""
    return subprocess.run(
        [sys.executable, str(TESTS / rel_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


@pytest.mark.parametrize(
    "script,timeout",
    [
        ("ui_audit.py",        120),
        ("system_audit.py",     90),
        ("industrial_audit.py", 300),
    ],
)
def test_audit_script_exits_zero(script: str, timeout: int):
    result = _run_script(script, timeout_s=timeout)
    assert result.returncode == 0, (
        f"{script} exited with status {result.returncode}.\n"
        f"--- stdout (tail) ---\n{result.stdout[-1500:]}\n"
        f"--- stderr (tail) ---\n{result.stderr[-1500:]}"
    )
