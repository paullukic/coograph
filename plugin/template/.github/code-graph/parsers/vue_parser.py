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
from ._tsjs import parse_script_block

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

# Import and declaration patterns live in _tsjs, shared with the Svelte parser.
_parse_script_block = parse_script_block


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
