"""CSS / SCSS / LESS parser.

Detects:
  - @import and @use directives
  - CSS custom properties (--variables)
  - SCSS/LESS variables ($var / @var)
  - Mixins (@mixin / .mixin())
  - Keyframe animations
  - Media queries (as annotations)
"""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid

STACK = "css"
EXTENSIONS = frozenset({".css", ".scss", ".sass", ".less", ".styl"})

# Imports
_IMPORT_RE = re.compile(
    r"""@(?:import|use|forward)\s+['"](.*?)['"]""",
    re.MULTILINE,
)
_URL_IMPORT_RE = re.compile(r'@import\s+url\(["\']?([^"\')\s]+)', re.MULTILINE)

# SCSS variables: $primary-color: ...
_SCSS_VAR_RE = re.compile(r'^\s*(\$[\w-]+)\s*:', re.MULTILINE)

# LESS variables: @primary-color: ...
_LESS_VAR_RE = re.compile(r'^\s*(@[\w-]+)\s*:', re.MULTILINE)

# CSS custom properties: --primary-color: ...
_CSS_VAR_RE = re.compile(r'^\s*(--[\w-]+)\s*:', re.MULTILINE)

# Mixins: @mixin name { ... }
_MIXIN_RE = re.compile(r'@mixin\s+([\w-]+)', re.MULTILINE)

# LESS mixins: .mixin() { ... }
_LESS_MIXIN_RE = re.compile(r'^\s*\.([\w-]+)\s*\([^)]*\)\s*\{', re.MULTILINE)

# Keyframes: @keyframes name { ... }
_KEYFRAMES_RE = re.compile(r'@keyframes\s+([\w-]+)', re.MULTILINE)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # Imports
    for m in _IMPORT_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))
    for m in _URL_IMPORT_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    # Variables (store as function nodes for searchability)
    seen: set[str] = set()
    for pattern in (_SCSS_VAR_RE, _LESS_VAR_RE, _CSS_VAR_RE):
        for m in pattern.finditer(text):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                line = text[:m.start()].count('\n') + 1
                vid = nid("function", rel, name)
                nodes.append((vid, "function", name, rel, line, None))
                edges.append((fid, vid, "contains"))

    # Mixins
    for m in _MIXIN_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        mid = nid("function", rel, name)
        nodes.append((mid, "function", name, rel, line, None))
        edges.append((fid, mid, "contains"))

    for m in _LESS_MIXIN_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        mid = nid("function", rel, name)
        nodes.append((mid, "function", name, rel, line, None))
        edges.append((fid, mid, "contains"))

    # Keyframes
    for m in _KEYFRAMES_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        kid = nid("function", rel, f"@keyframes_{name}")
        nodes.append((kid, "function", f"@keyframes {name}", rel, line, None))
        edges.append((fid, kid, "contains"))
