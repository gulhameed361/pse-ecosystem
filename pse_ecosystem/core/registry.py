"""Light registry for themes, applications, and unit-model classes.

Themes (e.g. Hydrogen) and Applications (Electrolysis, Gasification) are looked
up by short string handles in Layer 1. Keeping the registry tiny means we can
swap in a more elaborate plugin discovery system later without anything in the
solver layer caring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class ApplicationSpec:
    name: str
    description: str
    flowsheet_factory: Callable[..., "object"]


@dataclass
class ThemeSpec:
    name: str
    description: str
    applications: Dict[str, ApplicationSpec] = field(default_factory=dict)


_THEMES: Dict[str, ThemeSpec] = {}


def register_theme(theme: ThemeSpec) -> None:
    _THEMES[theme.name] = theme


def get_theme(name: str) -> ThemeSpec:
    if name not in _THEMES:
        raise KeyError(f"Unknown theme '{name}'. Registered: {list(_THEMES)}")
    return _THEMES[name]


def list_themes() -> List[str]:
    return sorted(_THEMES)
