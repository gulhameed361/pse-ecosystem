"""Docs/ folder loader — used by Help Center + Scenario Manager pages.

Resolves the absolute ``docs/`` folder regardless of CWD and reads
markdown files with a content-hash-keyed Streamlit cache (so symlinks
and copies don't break caching).
"""

from __future__ import annotations


def _docs_dir():
    """Resolve the absolute docs/ folder regardless of CWD."""
    from pathlib import Path
    # shared/docs_loader.py  →  shared/  →  ui/  →  pse_ecosystem/  →  repo root
    return Path(__file__).resolve().parent.parent.parent.parent / "docs"


def _load_doc(rel_name: str) -> str:
    """Read a markdown file from ``docs/`` with cache keyed on content hash.

    v1.4.0 audit N26 — pre-fix the cache key was ``path.stat().st_mtime``,
    which is unreliable for docs symlinked from a git checkout (some POSIX
    filesystems don't propagate mtime through symlinks; Windows preserves
    NTFS metadata but the value can lag by the filesystem's resolution).
    Use a SHA-1 of the file content instead so the cache is invariant
    under copies / symlinks but invalidates when the bytes actually change.

    Audit N27 — validate ``rel_name`` against directory traversal even
    though the Help Center only calls this with hardcoded names today;
    future API callers must not be able to escape ``docs/``.
    """
    import hashlib
    from pathlib import Path
    import streamlit as st  # already imported by caller; safe re-import for cache scope

    docs_root = _docs_dir().resolve()
    try:
        candidate = (docs_root / rel_name).resolve()
        candidate.relative_to(docs_root)
    except (ValueError, RuntimeError):
        return (
            f"_Refused to load `{rel_name}` — path escapes the docs/ "
            f"directory. Only filenames inside the workspace docs/ folder "
            f"are accepted by the Help Center loader._"
        )

    if not candidate.exists():
        return f"_Document `{rel_name}` is not yet available in this build._"

    @st.cache_data(show_spinner=False)
    def _read(path_str: str, content_hash: str) -> str:
        return Path(path_str).read_text(encoding="utf-8")

    raw = candidate.read_bytes()
    digest = hashlib.sha1(raw).hexdigest()
    return _read(str(candidate), digest)


__all__ = ["_docs_dir", "_load_doc"]
