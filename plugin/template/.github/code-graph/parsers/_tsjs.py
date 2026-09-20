"""Shared TS/JS declaration patterns for single-file-component parsers.

Extracted from vue_parser so the Svelte parser does not duplicate a hundred
lines of regex. Underscore-prefixed, so the package auto-loader skips it and it
never registers as a stack of its own.

Used by parsers that extract a `<script>` block from a component file and then
need the same function / class / interface / type / enum extraction a plain
`.ts` file would get.
"""

from __future__ import annotations

import re

from . import nid

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

IMPORT_RE = re.compile(
    r"""(?:"""
    r"""import\s+(?:[\w{}\s,*]+\s+from\s+)?['"]([^'"]+)['"]"""
    r"""|export\s+(?:[\w{}\s,*]+\s+from\s+)['"]([^'"]+)['"]"""
    r""")""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

FUNC_RE = re.compile(
    r'(?:^|[^.\w])(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)',
    re.MULTILINE,
)

ARROW_RE = re.compile(
    r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*'
    r'(?::\s*[\w<>\[\]|&,\s.()=>]+?)?\s*=\s*'
    r'(?:(?:\([^)]*\)|[\w<>\[\]|&,\s.]*)\s*(?:=>|:\s*\w)|function\s*[\(<])',
    re.MULTILINE,
)

CLASS_RE = re.compile(
    r'(?:^|[^.\w])(?:export\s+)?(?:abstract\s+)?class\s+(\w+)'
    r'(?:\s+extends\s+([\w.]+))?',
    re.MULTILINE,
)

INTERFACE_RE = re.compile(
    r'(?:export\s+)?interface\s+(\w+)',
    re.MULTILINE,
)

TYPE_RE = re.compile(
    r'(?:export\s+)?type\s+(\w+)\s*(?:<[^=]*>)?\s*=',
    re.MULTILINE,
)

ENUM_RE = re.compile(
    r'(?:export\s+)?(?:const\s+)?enum\s+(\w+)',
    re.MULTILINE,
)

# Names too generic to be worth a node: they collide across every file and
# would make a symbol lookup ambiguous rather than useful.
SKIP_NAMES = frozenset({
    'id', 'key', 'ref', 'value', 'result', 'data', 'error', 'response',
    'config', 'options', 'params', 'args', 'props', 'state', 'context',
    'i', 'j', 'k', 'n', 'x', 'y', 'cb', 'fn', 'el', 'ev', 'err',
})


def parse_script_block(text: str, rel: str, fid: str, nodes: list, edges: list) -> None:
    """Parse the content of a `<script>` block, or a whole .ts/.js file.

    Appends to *nodes* and *edges* in place. Import targets are emitted as the
    raw specifier; the builder resolves them to file-level `depends_on` edges
    once every file is known.
    """
    for m in IMPORT_RE.finditer(text):
        val = next((g for g in m.groups() if g), None)
        if val:
            edges.append((fid, val.strip(), "imports"))

    seen: set[str] = set()

    for m in FUNC_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen:
            seen.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    for m in ARROW_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen and name not in SKIP_NAMES:
            seen.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    for m in CLASS_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            class_id = nid("class", rel, name)
            nodes.append((class_id, "class", name, rel, line, None))
            edges.append((fid, class_id, "contains"))
            if m.group(2):
                edges.append((class_id, m.group(2).strip().rsplit(".", 1)[-1], "inherits"))

    for m in INTERFACE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            iface_id = nid("interface", rel, name)
            nodes.append((iface_id, "interface", name, rel, line, None))
            edges.append((fid, iface_id, "contains"))

    for m in TYPE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            type_id = nid("interface", rel, name)
            nodes.append((type_id, "interface", name, rel, line, None))
            edges.append((fid, type_id, "contains"))

    for m in ENUM_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            enum_id = nid("enum", rel, name)
            nodes.append((enum_id, "enum", name, rel, line, None))
            edges.append((fid, enum_id, "contains"))
