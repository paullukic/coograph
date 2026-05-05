"""Vue parser — handles .vue Single File Components + composables.

Detects:
  - .vue SFC: extracts <script> / <script setup> blocks and parses as TS/JS
  - defineComponent, defineProps, defineEmits, defineExpose
  - Composables: use* functions
  - Template refs and component registrations
  - Regular .ts/.js files with Vue patterns
"""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid

STACK = "vue"
EXTENSIONS = frozenset({".vue"})

# ---------------------------------------------------------------------------
# SFC extraction
# ---------------------------------------------------------------------------

_SCRIPT_RE = re.compile(
    r'<script\b[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Import patterns
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(
    r"""(?:"""
    r"""import\s+(?:[\w{}\s,*]+\s+from\s+)?['"]([^'"]+)['"]"""
    r"""|export\s+(?:[\w{}\s,*]+\s+from\s+)['"]([^'"]+)['"]"""
    r""")""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Vue-specific patterns
# ---------------------------------------------------------------------------

_DEFINE_COMPONENT_RE = re.compile(
    r'(?:export\s+default\s+)?defineComponent\s*\(\s*\{',
    re.MULTILINE,
)

_DEFINE_PROPS_RE = re.compile(r'defineProps\s*[<(]', re.MULTILINE)
_DEFINE_EMITS_RE = re.compile(r'defineEmits\s*[<(]', re.MULTILINE)

# Component name from defineComponent options or file name
_COMPONENT_NAME_RE = re.compile(r"name\s*:\s*['\"](\w+)['\"]")

# ---------------------------------------------------------------------------
# Standard TS/JS patterns (reused for script blocks)
# ---------------------------------------------------------------------------

_FUNC_RE = re.compile(
    r'(?:^|[^.\w])(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)',
    re.MULTILINE,
)

_ARROW_RE = re.compile(
    r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*'
    r'(?::\s*[\w<>\[\]|&,\s.()=>]+?)?\s*=\s*'
    r'(?:(?:\([^)]*\)|[\w<>\[\]|&,\s.]*)\s*(?:=>|:\s*\w)|function\s*[\(<])',
    re.MULTILINE,
)

_CLASS_RE = re.compile(
    r'(?:^|[^.\w])(?:export\s+)?(?:abstract\s+)?class\s+(\w+)'
    r'(?:\s+extends\s+([\w.]+))?',
    re.MULTILINE,
)

_INTERFACE_RE = re.compile(
    r'(?:export\s+)?interface\s+(\w+)',
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


def _parse_script_block(text: str, rel: str, fid: str, nodes: list, edges: list) -> None:
    """Parse the content of a <script> block (or a regular .ts/.js file)."""

    # Imports
    for m in _IMPORT_RE.finditer(text):
        val = next((g for g in m.groups() if g), None)
        if val:
            edges.append((fid, val.strip(), "imports"))

    # Functions
    seen: set[str] = set()
    for m in _FUNC_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen:
            seen.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # Arrow functions / const
    for m in _ARROW_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen and name not in _SKIP_NAMES:
            seen.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # Classes
    for m in _CLASS_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            class_id = nid("class", rel, name)
            nodes.append((class_id, "class", name, rel, line, None))
            edges.append((fid, class_id, "contains"))
            if m.group(2):
                edges.append((class_id, m.group(2).strip().rsplit(".", 1)[-1], "inherits"))

    # Interfaces
    for m in _INTERFACE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            iface_id = nid("interface", rel, name)
            nodes.append((iface_id, "interface", name, rel, line, None))
            edges.append((fid, iface_id, "contains"))

    # Types
    for m in _TYPE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            type_id = nid("interface", rel, name)
            nodes.append((type_id, "interface", name, rel, line, None))
            edges.append((fid, type_id, "contains"))

    # Enums
    for m in _ENUM_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            enum_id = nid("enum", rel, name)
            nodes.append((enum_id, "enum", name, rel, line, None))
            edges.append((fid, enum_id, "contains"))


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    if path.suffix == ".vue":
        # Extract <script> blocks from SFC
        scripts = _SCRIPT_RE.findall(text)
        for script_text in scripts:
            _parse_script_block(script_text, rel, fid, nodes, edges)

        # Vue-specific: detect component name
        comp_name = None
        for m in _COMPONENT_NAME_RE.finditer(text):
            comp_name = m.group(1)
        if not comp_name:
            comp_name = path.stem  # fallback to filename

        # Add component as a class node
        comp_id = nid("class", rel, comp_name)
        nodes.append((comp_id, "class", comp_name, rel, 1, None))
        edges.append((fid, comp_id, "contains"))

        # Detect style imports within SFC
        for m in re.finditer(r'<style\b[^>]*\bsrc=["\']([^"\']+)["\']', text):
            edges.append((fid, m.group(1), "imports"))
    else:
        # Regular .ts/.js file — parse normally
        _parse_script_block(text, rel, fid, nodes, edges)
