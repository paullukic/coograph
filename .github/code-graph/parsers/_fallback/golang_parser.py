"""Go parser with structs, interfaces, methods, and receivers."""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid, find_scope, brace_end

STACK = "golang"
EXTENSIONS = frozenset({".go"})

_IMPORT_SINGLE_RE = re.compile(r'^import\s+"([\w./\-]+)"', re.MULTILINE)
_IMPORT_BLOCK_RE = re.compile(r'^import\s*\((.*?)\)', re.MULTILINE | re.DOTALL)
_IMPORT_LINE_RE = re.compile(r'"([\w./\-]+)"')

_STRUCT_RE = re.compile(r'^type\s+(\w+)\s+struct\b', re.MULTILINE)
_INTERFACE_RE = re.compile(r'^type\s+(\w+)\s+interface\b', re.MULTILINE)
_TYPE_ALIAS_RE = re.compile(r'^type\s+(\w+)\s+\w', re.MULTILINE)

# func (r *Receiver) Method(...) or func Function(...)
_FUNC_RE = re.compile(
    r'^func\s+(?:\((\w+)\s+\*?(\w+)\)\s+)?(\w+)\s*[(\[]',
    re.MULTILINE,
)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # Single-line imports
    for m in _IMPORT_SINGLE_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    # Block imports
    for m in _IMPORT_BLOCK_RE.finditer(text):
        for im in _IMPORT_LINE_RE.finditer(m.group(1)):
            edges.append((fid, im.group(1), "imports"))

    # Structs
    for m in _STRUCT_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        sid = nid("class", rel, name)
        nodes.append((sid, "class", name, rel, line, None))
        edges.append((fid, sid, "contains"))

    # Interfaces
    for m in _INTERFACE_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        iid = nid("interface", rel, name)
        nodes.append((iid, "interface", name, rel, line, None))
        edges.append((fid, iid, "contains"))

    # Functions and methods
    for m in _FUNC_RE.finditer(text):
        receiver_type = m.group(2)  # e.g. "Server" from (s *Server)
        fname = m.group(3)
        if fname and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            if receiver_type:
                # Qualify name to avoid nid collisions between same-named methods
                func_id = nid("method", rel, f"{receiver_type}.{fname}")
                nodes.append((func_id, "method", fname, rel, line, None))
                struct_id = nid("class", rel, receiver_type)
                edges.append((struct_id, func_id, "contains"))
            else:
                func_id = nid("function", rel, fname)
                nodes.append((func_id, "function", fname, rel, line, None))
                edges.append((fid, func_id, "contains"))
