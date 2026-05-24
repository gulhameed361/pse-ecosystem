"""Aspen Plus ``.bkp`` text-section parser.

Aspen ``.bkp`` files are mostly binary, but the leading sections of any
recent Aspen Plus version include human-readable ASCII blocks listing the
unit-operation hierarchy and the stream summary. This parser extracts:

* **Streams**: name, T, P, mole flow, and mole fraction per component
* **Unit list**: block names + Aspen-internal unit-operation types

Use this as a starting point for cross-validating a PSE Ecosystem
flowsheet against an existing Aspen study — drop the .bkp file into
``parse_aspen_bkp(path)`` and the returned data structures can be diffed
against PSE Ecosystem's :func:`compute_metrics`.

Limitations
-----------
* Only the human-readable ASCII portion is parsed; the binary block-data
  section is ignored. Aspen versions older than V8 may not write the
  ASCII summary at all, in which case the function returns empty lists.
* Composition variables are mole fractions; mass-fraction reports are
  not detected (file the issue if needed).
* No topology / connectivity import — only block names. Use the unit
  list to instantiate PSE Ecosystem units and wire them manually.

References
----------
* Aspen Plus User Guide, "Exporting Stream Data".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class AspenStreamRow:
    name: str
    T_K: float = 0.0
    P_Pa: float = 0.0
    F_total_mol_s: float = 0.0
    composition: Dict[str, float] = field(default_factory=dict)


@dataclass
class AspenImportResult:
    streams: List[AspenStreamRow] = field(default_factory=list)
    block_names: List[str] = field(default_factory=list)
    block_types: Dict[str, str] = field(default_factory=dict)
    file_format_detected: str = "unknown"
    warnings: List[str] = field(default_factory=list)


# Aspen ASCII block summary markers. Different Aspen versions use slightly
# different headings; we tolerate the major variants.
_BLOCK_MARKERS: Tuple[str, ...] = (
    "BLOCK NAME",
    "BLOCK TYPE",
    "BLOCK CATEGORY",
)
_STREAM_MARKERS: Tuple[str, ...] = (
    "STREAM ID",
    "STREAM NAME",
    "STREAM:",
)


def parse_aspen_bkp(path: str) -> AspenImportResult:
    """Read an Aspen ``.bkp`` file and extract streams + block list.

    Robust to encoding: tries UTF-8, then Latin-1; binary bytes are
    silently skipped. The parser walks the file line-by-line looking
    for the ASCII summary markers; if none are found, returns an empty
    result with a warning explaining why.
    """
    result = AspenImportResult()

    # Read with permissive encoding — Aspen on Windows is typically cp1252
    # for the ASCII portions.
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        result.file_format_detected = "utf-8"
    except OSError as exc:
        result.warnings.append(f"Could not open file: {exc}")
        return result

    # If no ASCII summary markers, fall back to cp1252.
    if not any(any(m in ln for m in _BLOCK_MARKERS + _STREAM_MARKERS)
               for ln in lines):
        try:
            with open(path, "r", encoding="cp1252", errors="ignore") as f:
                lines = f.readlines()
            result.file_format_detected = "cp1252"
        except OSError:
            pass

    # State machine: walk lines; collect blocks and streams.
    in_blocks = False
    in_streams = False
    current_stream: Dict[str, Any] = {}
    for ln in lines:
        stripped = ln.strip()

        if any(m in stripped.upper() for m in _BLOCK_MARKERS):
            in_blocks = True
            in_streams = False
            continue
        if any(m in stripped.upper() for m in _STREAM_MARKERS):
            in_blocks = False
            in_streams = True
            if current_stream and current_stream.get("name"):
                result.streams.append(_finalise_stream(current_stream))
                current_stream = {}
            # Capture the stream name from the marker line if present.
            m = re.search(r"STREAM\s+(?:ID|NAME)\s*[:=]?\s*(\S+)", stripped, re.I)
            if m:
                current_stream = {"name": m.group(1), "composition": {}}
            continue

        if in_blocks:
            # Lines like  "  B1   RSTOIC   reactor"
            m = re.match(r"^\s*([A-Z0-9_-]+)\s+([A-Z0-9_-]+)\b", stripped)
            if m:
                name = m.group(1)
                btype = m.group(2)
                if name not in result.block_names and name.upper() != "BLOCK":
                    result.block_names.append(name)
                    result.block_types[name] = btype

        if in_streams:
            # Look for "TEMP", "PRES", "FLOW", "MOLE-FRAC" lines under
            # the current stream marker.
            upper = stripped.upper()
            if upper.startswith("TEMP"):
                v = _extract_float(stripped)
                if v is not None:
                    current_stream["T_K"] = v
            elif upper.startswith("PRES"):
                v = _extract_float(stripped)
                if v is not None:
                    current_stream["P_Pa"] = v
            elif "MOLE FLOW" in upper or upper.startswith("FLOW"):
                v = _extract_float(stripped)
                if v is not None:
                    current_stream["F_total_mol_s"] = v
            elif "MOLE FRAC" in upper or upper.startswith("FRAC"):
                # Real number regex (must contain ≥1 digit) — avoids matching
                # bare 'E' or '.' as a number. The leading identifier must
                # not collide with the keywords MOLE / FRAC.
                m = re.search(
                    r"([A-Za-z][A-Za-z0-9_-]*)\s*[:=]?\s*"
                    r"([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)",
                    stripped,
                )
                if m and m.group(1).upper() not in ("MOLE", "FRAC", "FRACS"):
                    sp, val = m.group(1), m.group(2)
                    try:
                        current_stream.setdefault("composition", {})[sp] = float(val)
                    except ValueError:
                        pass

    if current_stream and current_stream.get("name"):
        result.streams.append(_finalise_stream(current_stream))

    if not result.streams and not result.block_names:
        result.warnings.append(
            "No ASCII summary section found — file may be older than Aspen "
            "V8 or fully binary. Re-export as 'streams.csv' instead."
        )

    return result


def _extract_float(s: str) -> Any:
    """Pull the first floating-point number out of a string."""
    m = re.search(r"([-+]?\d+\.?\d*([eE][-+]?\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _finalise_stream(d: Dict[str, Any]) -> AspenStreamRow:
    return AspenStreamRow(
        name=d.get("name", "?"),
        T_K=float(d.get("T_K", 0.0)),
        P_Pa=float(d.get("P_Pa", 0.0)),
        F_total_mol_s=float(d.get("F_total_mol_s", 0.0)),
        composition=dict(d.get("composition", {})),
    )


__all__ = ["AspenStreamRow", "AspenImportResult", "parse_aspen_bkp"]
