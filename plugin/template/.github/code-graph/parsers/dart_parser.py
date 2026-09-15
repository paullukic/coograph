"""Dart / Flutter parser."""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid

STACK = "dart"
EXTENSIONS = frozenset({".dart"})

_IMPORT_RE = re.compile(r"import\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_EXPORT_RE = re.compile(r"export\s+['\"]([^'\"]+)['\"]", re.MULTILINE)

_CLASS_RE = re.compile(
    r'(?:abstract\s+)?'
    r'(class|mixin|enum|extension)\s+'
    r'(\w+)'
    r'(?:\s+extends\s+(\w+))?'
    r'(?:\s+with\s+([\w,\s]+))?'
    r'(?:\s+implements\s+([\w,\s]+))?',
    re.MULTILINE,
)

_FUNC_RE = re.compile(
    r'(?:Future|Stream|void|int|String|bool|double|var|dynamic|List|Map|Set|[\w<>?]+)\s+'
    r'(\w+)\s*\(',
    re.MULTILINE,
)

_TOP_FUNC_RE = re.compile(
    r'^(?:[\w<>?]+\s+)?(\w+)\s*\([^)]*\)\s*(?:async\s*)?[{=]',
    re.MULTILINE,
)

_DART_KEYWORDS = frozenset({
    'if', 'for', 'while', 'switch', 'catch', 'return', 'new', 'throw',
    'class', 'import', 'void', 'null', 'true', 'false', 'try', 'finally',
    'default', 'do', 'break', 'continue', 'case', 'else', 'assert',
    'this', 'super', 'const', 'final', 'var', 'late', 'required',
})


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _IMPORT_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))
    for m in _EXPORT_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    for m in _CLASS_RE.finditer(text):
        decl_type, name = m.group(1), m.group(2)
        extends, mixins, implements = m.group(3), m.group(4), m.group(5)
        line = text[:m.start()].count('\n') + 1

        kind = "class"
        if decl_type == "enum":
            kind = "enum"
        elif decl_type == "mixin":
            kind = "interface"

        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))

        if extends:
            edges.append((node_id, extends.strip(), "inherits"))
        if mixins:
            for mx in mixins.split(","):
                mx = mx.strip()
                if mx:
                    edges.append((node_id, mx, "implements"))
        if implements:
            for iface in implements.split(","):
                iface = iface.strip()
                if iface:
                    edges.append((node_id, iface, "implements"))

    for m in _FUNC_RE.finditer(text):
        fname = m.group(1)
        if fname and len(fname) > 1 and fname not in _DART_KEYWORDS:
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, f"{fname}_{line}")
            nodes.append((func_id, "function", fname, rel, line, None))
            edges.append((fid, func_id, "contains"))
