"""Regex-based fallback parsers.

These run only when the corresponding tree-sitter language package is missing
or fails to load. Tree-sitter parsers in `parsers.tree_sitter` always win when
available because of the ext_map override in `parsers.get_parsers`.

The leading underscore in this package name keeps it out of the auto-discovery
loop in `parsers.__init__._load_parsers`. The parent module imports it
explicitly at the end of its own `_load_parsers` so registrations land in the
shared `_REGISTRY`.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path


def load_fallbacks() -> None:
    """Import every fallback module so its `@register` decorator runs."""
    pkg_path = str(Path(__file__).parent)
    for _, modname, _ in pkgutil.iter_modules([pkg_path]):
        if modname.startswith("_"):
            continue
        importlib.import_module(f".{modname}", __package__)