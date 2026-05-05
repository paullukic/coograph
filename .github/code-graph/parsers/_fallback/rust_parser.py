"""Rust parser with structs, enums, traits, impls, and modules."""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid, find_scope, brace_end

STACK = "rust"
EXTENSIONS = frozenset({".rs"})

_USE_RE = re.compile(r'^use\s+([\w:]+)', re.MULTILINE)
_MOD_RE = re.compile(r'^(?:pub\s+)?mod\s+(\w+)\s*;', re.MULTILINE)

_STRUCT_RE = re.compile(
    r'(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)', re.MULTILINE
)
_ENUM_RE = re.compile(
    r'(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)', re.MULTILINE
)
_TRAIT_RE = re.compile(
    r'(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)', re.MULTILINE
)
_IMPL_RE = re.compile(
    r'impl\s+(?:<[^>]+>\s+)?(?:(\w+)\s+for\s+)?(\w+)', re.MULTILINE
)
_FN_RE = re.compile(
    r'(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)',
    re.MULTILINE,
)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _USE_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    for m in _MOD_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))

    for m in _STRUCT_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        sid = nid("class", rel, name)
        nodes.append((sid, "class", name, rel, line, None))
        edges.append((fid, sid, "contains"))

    for m in _ENUM_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        eid = nid("enum", rel, name)
        nodes.append((eid, "enum", name, rel, line, None))
        edges.append((fid, eid, "contains"))

    for m in _TRAIT_RE.finditer(text):
        name = m.group(1)
        line = text[:m.start()].count('\n') + 1
        tid = nid("interface", rel, name)
        nodes.append((tid, "interface", name, rel, line, None))
        edges.append((fid, tid, "contains"))

    # impl blocks — implements edges + scope list for method attribution
    impl_scopes = []  # (struct_nid, open_brace_pos, close_brace_pos)
    for m in _IMPL_RE.finditer(text):
        trait_name, struct_name = m.group(1), m.group(2)
        struct_nid = nid("class", rel, struct_name)
        if trait_name and struct_name:
            edges.append((struct_nid, trait_name, "implements"))
        open_pos = text.find('{', m.end())
        if open_pos != -1:
            impl_scopes.append((struct_nid, open_pos, brace_end(text, open_pos)))

    for m in _FN_RE.finditer(text):
        fname = m.group(1)
        if fname and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            owner = find_scope(m.start(), impl_scopes)
            kind = "method" if owner else "function"
            func_id = nid(kind, rel, f"{fname}_{line}")
            nodes.append((func_id, kind, fname, rel, line, None))
            edges.append((owner or fid, func_id, "contains"))
