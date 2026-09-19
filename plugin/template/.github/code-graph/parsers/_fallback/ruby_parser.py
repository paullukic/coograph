"""Ruby / Rails parser."""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid

STACK = "ruby"
EXTENSIONS = frozenset({".rb", ".rake"})

_REQUIRE_RE = re.compile(r"require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_CLASS_RE = re.compile(
    r'^\s*(class|module)\s+([\w:]+)(?:\s*<\s*([\w:]+))?',
    re.MULTILINE,
)
_DEF_RE = re.compile(r'^\s*def\s+(self\.)?(\w+[?!]?)', re.MULTILINE)

# Rails route patterns
_ROUTE_RE = re.compile(
    r"(?:get|post|put|patch|delete|resources?|match)\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _REQUIRE_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    for m in _CLASS_RE.finditer(text):
        decl_type, name, parent = m.group(1), m.group(2), m.group(3)
        # Use last part of nested name: Foo::Bar -> Bar
        short_name = name.rsplit("::", 1)[-1]
        line = text[:m.start()].count('\n') + 1
        kind = "class" if decl_type == "class" else "class"  # modules as class
        node_id = nid(kind, rel, short_name)
        nodes.append((node_id, kind, short_name, rel, line, None))
        edges.append((fid, node_id, "contains"))
        if parent:
            edges.append((node_id, parent.rsplit("::", 1)[-1], "inherits"))

    for m in _DEF_RE.finditer(text):
        fname = m.group(2)
        if fname and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            kind = "function" if m.group(1) else "method"
            func_id = nid(kind, rel, f"{fname}_{line}")
            nodes.append((func_id, kind, fname, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # Rails routes
    if "routes" in rel.lower():
        for m in _ROUTE_RE.finditer(text):
            route = m.group(1)
            line = text[:m.start()].count('\n') + 1
            eid = nid("endpoint", rel, route)
            nodes.append((eid, "endpoint", route, rel, line, None))
            edges.append((fid, eid, "contains"))
