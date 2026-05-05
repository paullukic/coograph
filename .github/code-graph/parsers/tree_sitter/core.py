"""Tree-sitter language loader + AST helpers.

Two responsibilities:

1. Probe which tree-sitter language packages are installed at import time
   and expose them via `supported_extensions()` and `get_lang(ext)`.
2. Provide tiny AST helpers (`txt`, `field`, `ancestor`, `walk`) used by
   every extractor / pass in the package.

`AVAILABLE` is False when the core `tree_sitter` package itself cannot be
imported. Downstream code (the package `__init__`) uses this to decide
whether to register at all.
"""

from __future__ import annotations

import importlib

# Try to load the tree-sitter runtime. If absent, AVAILABLE stays False and
# the package becomes a no-op; regex fallbacks then handle every extension.
try:
    from tree_sitter import Language, Parser  # noqa: F401  (re-exported)
    AVAILABLE = True
except ImportError:
    Language = None  # type: ignore[assignment]
    Parser = None    # type: ignore[assignment]
    AVAILABLE = False

# ---------------------------------------------------------------------------
# Language package probe
# ---------------------------------------------------------------------------

# ext -> (pip package name, function-name on package that returns the language)
PKG_MAP: dict[str, tuple[str, str]] = {
    ".py":   ("tree_sitter_python",     "language"),
    ".js":   ("tree_sitter_javascript", "language"),
    ".jsx":  ("tree_sitter_javascript", "language"),
    ".ts":   ("tree_sitter_typescript", "language_typescript"),
    ".tsx":  ("tree_sitter_typescript", "language_tsx"),
    ".java": ("tree_sitter_java",       "language"),
    ".kt":   ("tree_sitter_kotlin",     "language"),
    ".go":   ("tree_sitter_go",         "language"),
    ".rs":   ("tree_sitter_rust",       "language"),
    ".rb":   ("tree_sitter_ruby",       "language"),
    ".cs":   ("tree_sitter_c_sharp",    "language"),
    ".php":  ("tree_sitter_php",        "language_php"),
}

_lang_cache: dict[str, "Language | None"] = {}


def get_lang(ext: str):
    """Return a cached `Language` object for ext, or None if unavailable."""
    if not AVAILABLE:
        return None
    if ext not in _lang_cache:
        entry = PKG_MAP.get(ext)
        if not entry:
            _lang_cache[ext] = None
        else:
            pkg, fn = entry
            try:
                mod = importlib.import_module(pkg)
                _lang_cache[ext] = Language(getattr(mod, fn)())  # type: ignore[misc]
            except Exception:
                _lang_cache[ext] = None
    return _lang_cache[ext]


_supported_cache: set[str] | None = None


def supported_extensions() -> set[str]:
    """Set of extensions whose tree-sitter language packages loaded successfully.

    Cached on first call. Returns an empty set when AVAILABLE is False.
    """
    global _supported_cache
    if _supported_cache is None:
        _supported_cache = {ext for ext in PKG_MAP if get_lang(ext) is not None}
    return _supported_cache


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def txt(node, src: bytes) -> str:
    """UTF-8 decoded text of `node` from `src`."""
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def field(node, name: str, src: bytes) -> str | None:
    """Text of `node`'s named child field, or None if absent."""
    child = node.child_by_field_name(name)
    return txt(child, src) if child else None


def ancestor(node, types: frozenset[str]):
    """Nearest ancestor whose `.type` is in `types`, or None."""
    p = node.parent
    while p:
        if p.type in types:
            return p
        p = p.parent
    return None


def walk(root):
    """Iterative depth-first traversal yielding every descendant of root."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))