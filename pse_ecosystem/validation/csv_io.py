"""CSV I/O — stream-table import + Aspen-compatible export.

Industrial users routinely exchange flowsheet data via Excel or CSV stream
summaries because Aspen Plus, HYSYS, ProSim and other simulators have
incompatible native file formats but all export the same flat stream
table:

    Stream    , T_K  , P_Pa   , F_total_mol_s, y_H2 , y_CO , y_CO2, ...
    feed      , 300.0, 1.0e5  , 10.0         , 0.5  , 0.3  , 0.2  , ...
    reactor_out, 800.0, 9.5e4 , 9.8          , 0.1  , 0.3  , 0.6  , ...

The same convention is used by Hysys' "Workbook" CSV export and by
Aspen's "Streams Report" so this format is the *de facto* lingua franca
for cross-simulator validation.

Pure stdlib (``csv`` module) — no pandas dependency.
"""

from __future__ import annotations

import csv
from typing import Any, Dict, List, Mapping


# Reserved leading columns — anything else is treated as a composition
# variable. The user can opt out by passing ``known_cols=()``.
_DEFAULT_KNOWN_COLS = (
    "Stream", "T_K", "T_C", "P_Pa", "P_bar",
    "F_total_mol_s", "F_total_kg_s", "phase",
)


def read_stream_table_csv(
    path: str,
    known_cols: tuple = _DEFAULT_KNOWN_COLS,
    delimiter: str = ",",
) -> Dict[str, Dict[str, Any]]:
    """Read a stream-summary CSV → ``{stream_name: {var: value}}``.

    The first column must be the stream name. Numeric columns parse as
    ``float``; non-numeric columns parse as ``str``. Empty cells become
    ``0.0`` (numeric) or ``""`` (string) — same convention as Aspen's
    own CSV export.

    Parameters
    ----------
    path        : Path to CSV file.
    known_cols  : Tuple of reserved column names that are NOT composition
                  variables. Default covers T, P, F, phase under common
                  variants. Pass ``()`` to treat every column as composition.
    delimiter   : CSV delimiter (default ',' — Aspen also exports with ';'
                  in European locales).
    """
    streams: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if reader.fieldnames is None:
            return streams
        # First field is the stream-name column.
        name_col = reader.fieldnames[0]
        for row in reader:
            sname = row.get(name_col, "").strip()
            if not sname:
                continue
            entry: Dict[str, Any] = {}
            for col, val in row.items():
                if col == name_col:
                    continue
                if col in known_cols:
                    entry[col] = _try_float(val, default="")
                else:
                    # Treat as composition: empty → 0.0
                    entry[col] = _try_float(val, default=0.0)
            streams[sname] = entry
    return streams


def write_stream_table_csv(
    path: str,
    streams: Mapping[str, Mapping[str, Any]],
    column_order: List[str] | None = None,
    delimiter: str = ",",
) -> None:
    """Write ``{stream: {var: value}}`` → CSV in stream-summary layout.

    If ``column_order`` is None, the union of all variable keys is taken
    in alphabetical order, with the ``_DEFAULT_KNOWN_COLS`` listed first.

    The output is Aspen-readable: import into Aspen Plus via Tools →
    Import Data → CSV with stream-name as the row index.
    """
    if not streams:
        with open(path, "w", encoding="utf-8") as f:
            f.write("Stream\n")
        return

    all_vars: set = set()
    for s in streams.values():
        all_vars.update(s.keys())
    if column_order is None:
        # Reserved cols first (in the order they appear in _DEFAULT_KNOWN_COLS)
        order = [c for c in _DEFAULT_KNOWN_COLS if c in all_vars]
        # Then the rest alphabetically
        rest = sorted(all_vars - set(order))
        column_order = order + rest

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(["Stream"] + column_order)
        for sname, entry in streams.items():
            row = [sname]
            for col in column_order:
                v = entry.get(col, "")
                if isinstance(v, float):
                    row.append(_format_float(v))
                else:
                    row.append(str(v))
            writer.writerow(row)


def _try_float(s: str, default: Any) -> Any:
    """Parse ``s`` as float; fall back to ``default`` on empty / non-numeric."""
    if s is None:
        return default
    s = s.strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return s if default == "" else default


def _format_float(v: float) -> str:
    """Compact float formatting — avoids ``1e-05`` style for small numbers
    that round-trip badly across spreadsheet apps."""
    if v == 0.0:
        return "0"
    abs_v = abs(v)
    if 1e-3 <= abs_v < 1e6:
        return f"{v:.6g}"
    return f"{v:.6e}"


__all__ = ["read_stream_table_csv", "write_stream_table_csv"]
