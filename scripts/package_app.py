"""PSE Ecosystem — Standalone Application Packaging Script.

Usage
-----
    # Check that all tools and dependencies are ready
    python scripts/package_app.py --check

    # Build a standalone executable (PyInstaller by default)
    python scripts/package_app.py --build

    # Build with Nuitka instead
    python scripts/package_app.py --build --backend nuitka

    # List known issues and mitigations
    python scripts/package_app.py --info

Output
------
PyInstaller  : dist/pse_ecosystem_ui/   (folder) or dist/pse_ecosystem_ui.exe (one-file)
Nuitka       : pse_ecosystem_ui.dist/   (folder with .exe)

Platform notes
--------------
* Windows : tested with Python 3.10-3.12.  Run from the project venv.
* macOS   : replace backslashes with forward slashes in the commands below.
            Use ``--target-arch arm64`` for Apple Silicon.
* Linux   : works as-is; produces an ELF binary.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENTRY = ROOT / "pse_ecosystem" / "ui" / "app_streamlit.py"
DIST  = ROOT / "dist"


# ── Checks ────────────────────────────────────────────────────────────────────

def _check_python() -> bool:
    major, minor = sys.version_info[:2]
    ok = (major == 3 and 10 <= minor <= 13)
    tag = "OK" if ok else "WARN"
    print(f"  [{tag}] Python {major}.{minor}  (supported: 3.10 – 3.13)")
    return ok


def _check_tool(name: str) -> bool:
    found = shutil.which(name) is not None
    tag = "OK" if found else "MISS"
    print(f"  [{tag}] {name}")
    return found


def _check_import(module: str) -> bool:
    try:
        __import__(module)
        print(f"  [OK]   import {module}")
        return True
    except ImportError:
        print(f"  [MISS] import {module}  — pip install {module}")
        return False


def check() -> int:
    print("\nPSE Ecosystem — packaging pre-flight check\n")

    ok = True
    ok &= _check_python()
    print()

    print("Build tools:")
    pi_ok  = _check_tool("pyinstaller")
    nk_ok  = _check_tool("nuitka")
    if not pi_ok and not nk_ok:
        print("  Install at least one:  pip install pyinstaller   OR   pip install nuitka")
        ok = False
    print()

    print("Required packages:")
    # v1.4.0 audit N29 — openpyxl is required for the Excel-export feature
    # (Solver Monitor → Download Results) and was previously not in the
    # pre-flight check; packaged apps without it crashed on download.
    for pkg in ["streamlit", "plotly", "pyomo", "numpy", "openpyxl", "pse_ecosystem"]:
        ok &= _check_import(pkg)
    print()

    print("Optional packages (needed at runtime if used):")
    for pkg in ["pvlib", "pandas", "scipy", "highspy"]:
        _check_import(pkg)

    print()
    if ok:
        print("Pre-flight: ALL CLEAR — run with --build to package.\n")
        return 0
    else:
        print("Pre-flight: ISSUES FOUND — fix above before building.\n")
        return 1


# ── Build commands ────────────────────────────────────────────────────────────

_PYINSTALLER_CMD = [
    "pyinstaller",
    "--name", "pse_ecosystem_ui",
    "--onedir",                      # folder bundle (more reliable than --onefile for Streamlit)
    "--noconfirm",
    # Collect all of Streamlit's static assets (HTML, JS, CSS)
    "--collect-all", "streamlit",
    # Collect plotly static
    "--collect-all", "plotly",
    # Hidden imports that PyInstaller's analyser misses
    "--hidden-import", "pyomo.environ",
    "--hidden-import", "pyomo.core",
    "--hidden-import", "pse_ecosystem.themes.hydrogen",
    "--hidden-import", "pse_ecosystem.ui.flowsheet_service",
    "--hidden-import", "scipy.optimize",
    "--hidden-import", "scipy.integrate",
    # Add the pse_ecosystem package as data so it is importable at runtime
    "--add-data", f"{ROOT / 'pse_ecosystem'}{';' if sys.platform == 'win32' else ':'}pse_ecosystem",
    str(ENTRY),
]

_NUITKA_CMD = [
    sys.executable, "-m", "nuitka",
    "--standalone",
    "--follow-imports",
    "--include-package=streamlit",
    "--include-package=plotly",
    "--include-package=pyomo",
    "--include-package=pse_ecosystem",
    "--include-package=scipy",
    "--output-dir=dist",
    "--output-filename=pse_ecosystem_ui",
    str(ENTRY),
]


def build(backend: str = "pyinstaller") -> int:
    print(f"\nBuilding with {backend} …\n")
    DIST.mkdir(exist_ok=True)

    if backend == "pyinstaller":
        cmd = _PYINSTALLER_CMD
    elif backend == "nuitka":
        cmd = _NUITKA_CMD
    else:
        print(f"Unknown backend: {backend}. Choose 'pyinstaller' or 'nuitka'.")
        return 1

    print("Command:\n  " + " ".join(str(c) for c in cmd) + "\n")
    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode == 0:
        print("\nBuild complete.")
        if backend == "pyinstaller":
            exe = DIST / "pse_ecosystem_ui"
            print(f"Output folder : {exe}")
            print(f"To run        : {exe / 'pse_ecosystem_ui'}")
            print(f"\nLaunch the UI : cd {exe} && ./pse_ecosystem_ui")
        return 0
    else:
        print(f"\nBuild FAILED (exit {result.returncode}).")
        print("See output above. Common fixes:")
        print("  - Missing hidden import: add --hidden-import <module> to _PYINSTALLER_CMD")
        print("  - Missing data file: add --add-data to _PYINSTALLER_CMD")
        print("  - Streamlit version mismatch: pip install 'streamlit>=1.28'")
        return result.returncode


# ── Info ──────────────────────────────────────────────────────────────────────

def info() -> None:
    print("""
Known Issues & Mitigations
===========================

1. Streamlit bootstrap
   Streamlit's entry point is `streamlit run`, not a direct Python call.
   PyInstaller wraps the Python call only. To launch the packaged app,
   users run the generated executable, which internally calls:
       streamlit run app_streamlit.py
   Alternatively, set the STREAMLIT_SERVER_PORT env var and open a browser.

2. Pyomo solver detection
   HiGHS / GLPK must be bundled or installed separately on the target machine.
   Add `--add-binary <path_to_highs.exe>;solvers/` to _PYINSTALLER_CMD.

3. Scipy / Cython extensions
   scipy ships compiled extensions. PyInstaller collects them automatically
   via `--collect-all scipy`, but the target machine must have the Visual C++
   Redistributable (Windows) or equivalent (macOS/Linux).

4. macOS code signing
   On macOS 13+, notarisation may be required for distribution outside
   the App Store. Use `codesign` after building.

5. Large bundle size
   The bundle will be ~300-500 MB due to Streamlit, Plotly, and scipy.
   Use `--onedir` (default here) rather than `--onefile` to avoid slow
   startup caused by extraction.

6. Testing the bundle
   Run `dist/pse_ecosystem_ui/pse_ecosystem_ui` and open a browser at
   http://localhost:8501. All 4 pages should load and solve correctly.
""")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PSE Ecosystem standalone app packaging helper"
    )
    parser.add_argument("--check",   action="store_true", help="Pre-flight check only")
    parser.add_argument("--build",   action="store_true", help="Build the executable")
    parser.add_argument("--info",    action="store_true", help="Print known issues")
    parser.add_argument(
        "--backend", choices=["pyinstaller", "nuitka"], default="pyinstaller",
        help="Packaging backend (default: pyinstaller)"
    )
    args = parser.parse_args()

    if args.info:
        info()
        return

    if args.check or not args.build:
        rc = check()
        if not args.build:
            sys.exit(rc)

    if args.build:
        sys.exit(build(args.backend))


if __name__ == "__main__":
    main()
