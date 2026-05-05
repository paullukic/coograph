"""C# / F# (.NET) parser.

Detects:
  - Classes, records, structs, interfaces, enums
  - Namespaces
  - Methods and properties
  - Attributes: [ApiController], [HttpGet], [Authorize], etc.
  - Inheritance and interface implementation
  - using directives (imports)
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid, find_scope, brace_end

STACK = "dotnet"
EXTENSIONS = frozenset({".cs", ".fs"})

# ---------------------------------------------------------------------------
# C# patterns
# ---------------------------------------------------------------------------

_CS_USING_RE = re.compile(r'^using\s+([\w.]+)\s*;', re.MULTILINE)

_CS_NAMESPACE_RE = re.compile(
    r'namespace\s+([\w.]+)',
    re.MULTILINE,
)

_CS_CLASS_RE = re.compile(
    r'(?:(?:public|private|protected|internal|abstract|sealed|static|partial|readonly)\s+)*'
    r'(class|record|struct|interface|enum)\s+'
    r'(\w+)'
    r'(?:\s*<[^{]*?>)?'
    r'((?:\s*:\s*[\w.<>,\s]+)?)',
    re.MULTILINE | re.DOTALL,
)

_CS_METHOD_RE = re.compile(
    r'(?:(?:public|private|protected|internal|static|virtual|override|abstract|async|sealed|new|extern)\s+)+'
    r'(?:[\w<>\[\]?.]+\s+)'
    r'(\w+)\s*[(<]',
    re.MULTILINE,
)

_CS_PROPERTY_RE = re.compile(
    r'(?:(?:public|private|protected|internal|static|virtual|override|abstract|required)\s+)+'
    r'[\w<>\[\]?.]+\s+'
    r'(\w+)\s*\{',
    re.MULTILINE,
)

_CS_ATTRIBUTE_RE = re.compile(r'^\s*\[(\w+)', re.MULTILINE)

_CS_KEYWORDS = frozenset({
    'if', 'for', 'foreach', 'while', 'switch', 'catch', 'return', 'new',
    'throw', 'class', 'interface', 'enum', 'struct', 'using', 'namespace',
    'void', 'null', 'true', 'false', 'try', 'finally', 'default', 'do',
    'break', 'continue', 'case', 'else', 'is', 'as', 'in', 'out', 'ref',
    'base', 'this', 'typeof', 'sizeof', 'lock', 'fixed', 'checked', 'get',
    'set', 'value', 'var', 'await', 'yield', 'where', 'select', 'from',
})

# ---------------------------------------------------------------------------
# F# patterns
# ---------------------------------------------------------------------------

_FS_OPEN_RE = re.compile(r'^open\s+([\w.]+)', re.MULTILINE)
_FS_MODULE_RE = re.compile(r'^module\s+([\w.]+)', re.MULTILINE)
_FS_TYPE_RE = re.compile(r'^type\s+(\w+)', re.MULTILINE)
_FS_LET_RE = re.compile(r'^let\s+(?:rec\s+)?(?:inline\s+)?(\w+)', re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_cs_bases(raw: str) -> tuple[list[str], list[str]]:
    """Parse ': BaseClass, IFoo, IBar' into (bases, interfaces)."""
    if not raw or not raw.strip():
        return [], []
    raw = raw.strip().lstrip(":")
    # Strip generics for splitting
    depth, clean = 0, []
    for ch in raw:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth = max(0, depth - 1)
        elif depth == 0:
            clean.append(ch)
    parts = [p.strip() for p in "".join(clean).split(",") if p.strip()]
    bases, ifaces = [], []
    for p in parts:
        name = p.rsplit(".", 1)[-1]
        if name.startswith("I") and len(name) > 1 and name[1].isupper():
            ifaces.append(name)
        else:
            bases.append(name)
    return bases, ifaces


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    ext = path.suffix.lower()
    if ext == ".cs":
        _parse_cs(path, rel, nodes, edges)
    elif ext == ".fs":
        _parse_fs(path, rel, nodes, edges)


def _parse_cs(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # Using directives
    for m in _CS_USING_RE.finditer(text):
        edges.append((fid, m.group(1).strip(), "imports"))

    # Classes / records / structs / interfaces / enums — build scope list
    scopes = []
    for m in _CS_CLASS_RE.finditer(text):
        decl_type, name, bases_raw = m.group(1), m.group(2), m.group(3)
        line = text[:m.start()].count('\n') + 1

        kind = "class"
        if decl_type == "interface":
            kind = "interface"
        elif decl_type == "enum":
            kind = "enum"
        elif decl_type in ("record", "struct"):
            kind = "class"

        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))

        bases, ifaces = _parse_cs_bases(bases_raw)
        for base in bases:
            edges.append((node_id, base, "inherits"))
        for iface in ifaces:
            edges.append((node_id, iface, "implements"))

        open_pos = text.find('{', m.end())
        if open_pos != -1:
            scopes.append((node_id, open_pos, brace_end(text, open_pos)))

    # Methods
    for m in _CS_METHOD_RE.finditer(text):
        mname = m.group(1)
        if mname and len(mname) > 1 and mname not in _CS_KEYWORDS:
            line = text[:m.start()].count('\n') + 1
            owner = find_scope(m.start(), scopes)
            kind = "method" if owner else "function"
            mid = nid(kind, rel, f"{mname}_{line}")
            nodes.append((mid, kind, mname, rel, line, None))
            edges.append((owner or fid, mid, "contains"))

    # Notable attributes
    attrs = set()
    for m in _CS_ATTRIBUTE_RE.finditer(text):
        attrs.add(m.group(1))
    notable = attrs & {
        'ApiController', 'Controller', 'HttpGet', 'HttpPost', 'HttpPut',
        'HttpDelete', 'HttpPatch', 'Authorize', 'AllowAnonymous',
        'Route', 'Area', 'ValidateAntiForgeryToken', 'ServiceFilter',
        'Table', 'Column', 'Key', 'ForeignKey', 'Required',
    }
    if notable:
        aid = nid("annotation", rel, ",".join(sorted(notable)))
        nodes.append((aid, "annotation", ",".join(sorted(notable)), rel, None, None))


def _parse_fs(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _FS_OPEN_RE.finditer(text):
        edges.append((fid, m.group(1).strip(), "imports"))

    for m in _FS_MODULE_RE.finditer(text):
        name = m.group(1).rsplit(".", 1)[-1]
        line = text[:m.start()].count('\n') + 1
        mid = nid("class", rel, name)
        nodes.append((mid, "class", name, rel, line, None))
        edges.append((fid, mid, "contains"))

    for m in _FS_TYPE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            tid = nid("class", rel, name)
            nodes.append((tid, "class", name, rel, line, None))
            edges.append((fid, tid, "contains"))

    for m in _FS_LET_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name != "_":
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))
