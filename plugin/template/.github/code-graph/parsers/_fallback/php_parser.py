"""PHP / Laravel parser.

Detects:
  - Classes, interfaces, traits, enums (PHP 8.1+)
  - Functions and methods
  - use/require/include imports
  - Namespace declarations
  - Laravel-specific: Route definitions, Eloquent models, middleware
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid, find_scope, brace_end

STACK = "php"
EXTENSIONS = frozenset({".php"})

_NAMESPACE_RE = re.compile(r'^namespace\s+([\w\\]+)\s*;', re.MULTILINE)
_USE_RE = re.compile(r'^use\s+([\w\\]+)', re.MULTILINE)
_REQUIRE_RE = re.compile(
    r"(?:require|include)(?:_once)?\s+['\"]([^'\"]+)['\"]", re.MULTILINE
)

_CLASS_RE = re.compile(
    r'(?:(?:abstract|final)\s+)?'
    r'(class|interface|trait|enum)\s+'
    r'(\w+)'
    r'(?:\s+extends\s+([\w\\]+))?'
    r'(?:\s+implements\s+([\w\\,\s]+))?',
    re.MULTILINE,
)

_FUNC_RE = re.compile(
    r'(?:(?:public|private|protected|static|abstract|final)\s+)*'
    r'function\s+(\w+)\s*\(',
    re.MULTILINE,
)

# Laravel route definitions
_ROUTE_RE = re.compile(
    r"Route::(?:get|post|put|patch|delete|any|match)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # Imports
    for m in _USE_RE.finditer(text):
        edges.append((fid, m.group(1).replace("\\", "."), "imports"))
    for m in _REQUIRE_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    # Classes / interfaces / traits / enums — build scope list
    scopes = []
    for m in _CLASS_RE.finditer(text):
        decl_type, name = m.group(1), m.group(2)
        extends, implements = m.group(3), m.group(4)
        line = text[:m.start()].count('\n') + 1

        kind = "class"
        if decl_type == "interface":
            kind = "interface"
        elif decl_type == "trait":
            kind = "interface"  # treat traits like interfaces
        elif decl_type == "enum":
            kind = "enum"

        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))

        if extends:
            base = extends.rsplit("\\", 1)[-1]
            edges.append((node_id, base, "inherits"))
        if implements:
            for iface in implements.split(","):
                iface = iface.strip().rsplit("\\", 1)[-1]
                if iface:
                    edges.append((node_id, iface, "implements"))

        open_pos = text.find('{', m.end())
        if open_pos != -1:
            scopes.append((node_id, open_pos, brace_end(text, open_pos)))

    # Functions / methods
    for m in _FUNC_RE.finditer(text):
        fname = m.group(1)
        if fname and fname != "__construct" and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            owner = find_scope(m.start(), scopes)
            kind = "method" if owner else "function"
            func_id = nid(kind, rel, f"{fname}_{line}")
            nodes.append((func_id, kind, fname, rel, line, None))
            edges.append((owner or fid, func_id, "contains"))

    # Laravel routes as endpoints
    for m in _ROUTE_RE.finditer(text):
        route = m.group(1)
        line = text[:m.start()].count('\n') + 1
        eid = nid("endpoint", rel, route)
        nodes.append((eid, "endpoint", route, rel, line, None))
        edges.append((fid, eid, "contains"))
