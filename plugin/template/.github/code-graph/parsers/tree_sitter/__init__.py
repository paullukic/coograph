"""Tree-sitter parser package.

Splits the previous monolithic `tree_sitter_parser.py` into:
  - `core`       : language-loader probe + AST traversal helpers.
  - `languages`  : per-language extractors (imports, calls) + config table.
  - `parser`     : `_parse_file` orchestrator (3 passes: classes, fns, calls).

Registers a single parser under stack `"tree_sitter"` for every extension
whose tree-sitter language package is actually installed and importable. The
parent `parsers.get_parsers` then uses ext_map override to make tree-sitter
win over any regex fallback registered for the same extension.

If neither `tree-sitter` nor any language package is installed, registration
is silently skipped — the regex parsers in `parsers._fallback` then carry the
load.
"""

from __future__ import annotations

from .. import register
from .core import AVAILABLE, supported_extensions
from .parser import parse_file


STACK = "tree_sitter"

if AVAILABLE and supported_extensions():
    register(STACK, frozenset(supported_extensions()))(parse_file)