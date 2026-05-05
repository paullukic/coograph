"""Angular parser — extends TS parsing with Angular-specific patterns.

Detects:
  - Decorators: @Component, @Injectable, @NgModule, @Directive, @Pipe, @Guard
  - Module imports/exports/declarations arrays
  - Services, resolvers, interceptors, guards
  - Angular-specific file conventions (.component.ts, .service.ts, etc.)
  - Template and style file references in @Component metadata
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid

STACK = "angular"
EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx"})

# ---------------------------------------------------------------------------
# Import patterns (same as React parser — ES imports)
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(
    r"""(?:"""
    r"""import\s+(?:[\w{}\s,*]+\s+from\s+)?['"]([^'"]+)['"]"""
    r"""|export\s+(?:[\w{}\s,*]+\s+from\s+)['"]([^'"]+)['"]"""
    r""")""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Angular decorator patterns
# ---------------------------------------------------------------------------

# Match @Component, @Injectable, @NgModule, etc.
_DECORATOR_RE = re.compile(
    r'@(Component|Injectable|NgModule|Directive|Pipe|Guard|Resolver|Interceptor)\s*\(',
    re.MULTILINE,
)

# Template/style file references in @Component metadata
_TEMPLATE_URL_RE = re.compile(r"templateUrl\s*:\s*['\"]([^'\"]+)['\"]")
_STYLE_URLS_RE = re.compile(r"styleUrls?\s*:\s*\[([^\]]*)\]")
_STYLE_URL_ITEM_RE = re.compile(r"['\"]([^'\"]+)['\"]")

# ---------------------------------------------------------------------------
# Declaration patterns
# ---------------------------------------------------------------------------

_FUNC_RE = re.compile(
    r'(?:^|[^.\w])'
    r'(?:export\s+)?(?:default\s+)?(?:async\s+)?'
    r'function\s+(\w+)',
    re.MULTILINE,
)

_ARROW_RE = re.compile(
    r'(?:export\s+)?(?:const|let|var)\s+'
    r'(\w+)\s*'
    r'(?::\s*[\w<>\[\]|&,\s.()=>]+?)?\s*'
    r'=\s*'
    r'(?:'
    r'(?:\([^)]*\)|[\w<>\[\]|&,\s.]*)\s*(?:=>|:\s*\w)'
    r'|function\s*[\(<]'
    r')',
    re.MULTILINE,
)

_CLASS_RE = re.compile(
    r'(?:^|[^.\w])'
    r'(?:export\s+)?(?:default\s+)?(?:abstract\s+)?'
    r'class\s+(\w+)'
    r'(?:\s+extends\s+([\w.]+))?'
    r'(?:\s+implements\s+([\w,\s.]+))?',
    re.MULTILINE,
)

_INTERFACE_RE = re.compile(
    r'(?:export\s+)?interface\s+(\w+)'
    r'(?:\s+extends\s+([\w,\s.<>]+))?',
    re.MULTILINE,
)

_TYPE_RE = re.compile(
    r'(?:export\s+)?type\s+(\w+)\s*(?:<[^=]*>)?\s*=',
    re.MULTILINE,
)

_ENUM_RE = re.compile(
    r'(?:export\s+)?(?:const\s+)?enum\s+(\w+)',
    re.MULTILINE,
)

_SKIP_NAMES = frozenset({
    'id', 'key', 'ref', 'value', 'result', 'data', 'error', 'response',
    'config', 'options', 'params', 'args', 'props', 'state', 'context',
    'i', 'j', 'k', 'n', 'x', 'y', 'cb', 'fn', 'el', 'ev', 'err',
})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # ---- Imports ----
    for m in _IMPORT_RE.finditer(text):
        val = next((g for g in m.groups() if g), None)
        if val:
            edges.append((fid, val.strip(), "imports"))

    # ---- Angular decorators → annotation nodes ----
    decorators: set[str] = set()
    for m in _DECORATOR_RE.finditer(text):
        decorators.add(m.group(1))

    if decorators:
        aid = nid("annotation", rel, ",".join(sorted(decorators)))
        nodes.append((aid, "annotation", ",".join(sorted(decorators)), rel, None, None))

    # ---- Template/style file references → imports ----
    for m in _TEMPLATE_URL_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))
    for m in _STYLE_URLS_RE.finditer(text):
        for sm in _STYLE_URL_ITEM_RE.finditer(m.group(1)):
            edges.append((fid, sm.group(1), "imports"))

    # ---- Functions ----
    seen_names: set[str] = set()
    for m in _FUNC_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen_names:
            seen_names.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # ---- Arrow functions ----
    for m in _ARROW_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen_names and name not in _SKIP_NAMES:
            seen_names.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # ---- Classes ----
    for m in _CLASS_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            class_id = nid("class", rel, name)
            nodes.append((class_id, "class", name, rel, line, None))
            edges.append((fid, class_id, "contains"))
            if m.group(2):
                base = m.group(2).strip().rsplit(".", 1)[-1]
                edges.append((class_id, base, "inherits"))
            if m.group(3):
                for iface in m.group(3).split(","):
                    iface = iface.strip().rsplit(".", 1)[-1]
                    if iface:
                        edges.append((class_id, iface, "implements"))

    # ---- Interfaces ----
    for m in _INTERFACE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            iface_id = nid("interface", rel, name)
            nodes.append((iface_id, "interface", name, rel, line, None))
            edges.append((fid, iface_id, "contains"))
            if m.group(2):
                for base in m.group(2).split(","):
                    base = base.strip().split("<")[0].strip()
                    if base:
                        edges.append((iface_id, base, "inherits"))

    # ---- Types ----
    for m in _TYPE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            type_id = nid("interface", rel, name)
            nodes.append((type_id, "interface", name, rel, line, None))
            edges.append((fid, type_id, "contains"))

    # ---- Enums ----
    for m in _ENUM_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            enum_id = nid("enum", rel, name)
            nodes.append((enum_id, "enum", name, rel, line, None))
            edges.append((fid, enum_id, "contains"))
