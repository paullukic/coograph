"""Swift parser with classes, structs, protocols, enums, and actors."""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid

STACK = "swift"
EXTENSIONS = frozenset({".swift"})

_IMPORT_RE = re.compile(r'^import\s+(\w+)', re.MULTILINE)

_TYPE_RE = re.compile(
    r'(?:(?:public|private|internal|open|fileprivate|final)\s+)*'
    r'(class|struct|enum|protocol|actor)\s+'
    r'(\w+)'
    r'(?:\s*:\s*([\w,\s.]+))?',
    re.MULTILINE,
)

_FUNC_RE = re.compile(
    r'(?:(?:public|private|internal|open|fileprivate|static|class|override|mutating)\s+)*'
    r'func\s+(\w+)\s*[(<]',
    re.MULTILINE,
)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _IMPORT_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    for m in _TYPE_RE.finditer(text):
        decl_type, name, conformance = m.group(1), m.group(2), m.group(3)
        line = text[:m.start()].count('\n') + 1

        kind = "class"
        if decl_type == "protocol":
            kind = "interface"
        elif decl_type == "enum":
            kind = "enum"

        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))

        if conformance:
            for base in conformance.split(","):
                base = base.strip()
                if base:
                    edges.append((node_id, base, "inherits"))

    for m in _FUNC_RE.finditer(text):
        fname = m.group(1)
        if fname and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, f"{fname}_{line}")
            nodes.append((func_id, "function", fname, rel, line, None))
            edges.append((fid, func_id, "contains"))
