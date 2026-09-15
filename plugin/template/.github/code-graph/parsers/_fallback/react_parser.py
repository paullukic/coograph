"""React / TypeScript / JavaScript parser.

Handles modern frontend patterns that the old generic regex missed:
  - Arrow function components: ``export const Button = () => ...``
  - forwardRef / memo wrappers: ``export const Input = forwardRef(...)``
  - Hooks: ``export function useAuth()``
  - Default exports: ``export default function Page()``
  - Interfaces / types: ``export interface Props { ... }``
  - Re-exports: ``export { Foo } from './bar'``
  - Dynamic imports: ``import('./chunk')``
  - CSS module imports: ``import styles from './Foo.module.css'``
  - Enums: ``export enum Status { ... }``

Also serves as the generic TS/JS parser for non-React projects.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid

STACK = "react"
EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx"})

# ---------------------------------------------------------------------------
# Import patterns
# ---------------------------------------------------------------------------

# Standard ES imports:  import X from 'y'  /  import { X } from 'y'  /  import 'y'
_IMPORT_RE = re.compile(
    r"""(?:"""
    r"""import\s+(?:[\w{}\s,*]+\s+from\s+)?['"]([^'"]+)['"]"""   # ES import
    r"""|require\s*\(\s*['"]([^'"]+)['"]\s*\)"""                  # CommonJS require
    r"""|import\s*\(\s*['"]([^'"]+)['"]\s*\)"""                   # dynamic import()
    r"""|export\s+(?:[\w{}\s,*]+\s+from\s+)['"]([^'"]+)['"]"""   # re-export
    r""")""",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Declaration patterns
# ---------------------------------------------------------------------------

# function keyword declarations (named + default)
_FUNC_RE = re.compile(
    r'(?:^|[^.\w])'
    r'(?:export\s+)?(?:default\s+)?(?:async\s+)?'
    r'function\s+(\w+)',
    re.MULTILINE,
)

# Arrow function / const declarations:
#   export const Foo = () => ...
#   export const Foo = function ...
#   export const Foo = React.memo(...)
#   export const Foo = forwardRef(...)
#   const Foo = styled.div`...`
_ARROW_RE = re.compile(
    r'(?:export\s+)?(?:const|let|var)\s+'
    r'(\w+)\s*'
    r'(?::\s*[\w<>\[\]|&,\s.()=>]+?)?\s*'  # optional type annotation
    r'=\s*'
    r'(?:'
    r'(?:React\.)?(?:memo|forwardRef|lazy)\s*\('           # wrapper HOCs
    r'|(?:styled(?:\.\w+|\([^)]*\))`)'                     # styled-components
    r'|(?:\([^)]*\)|[\w<>\[\]|&,\s.]*)\s*(?:=>|:\s*\w)'   # arrow function
    r'|function\s*[\(<]'                                    # function expression
    r')',
    re.MULTILINE,
)

# Class declarations
_CLASS_RE = re.compile(
    r'(?:^|[^.\w])'
    r'(?:export\s+)?(?:default\s+)?(?:abstract\s+)?'
    r'class\s+(\w+)'
    r'(?:\s+extends\s+([\w.]+))?'
    r'(?:\s+implements\s+([\w,\s.]+))?',
    re.MULTILINE,
)

# Interface declarations
_INTERFACE_RE = re.compile(
    r'(?:export\s+)?interface\s+(\w+)'
    r'(?:\s+extends\s+([\w,\s.<>]+))?',
    re.MULTILINE,
)

# Type alias declarations
_TYPE_RE = re.compile(
    r'(?:export\s+)?type\s+(\w+)\s*(?:<[^=]*>)?\s*=',
    re.MULTILINE,
)

# Enum declarations
_ENUM_RE = re.compile(
    r'(?:export\s+)?(?:const\s+)?enum\s+(\w+)',
    re.MULTILINE,
)

# Default export of identifier: export default Foo
_DEFAULT_EXPORT_RE = re.compile(
    r'^export\s+default\s+(\w+)\s*;?\s*$',
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Skip list — avoid false positive arrow function matches
# ---------------------------------------------------------------------------

_SKIP_NAMES = frozenset({
    # Common non-component variable names
    'id', 'key', 'ref', 'value', 'result', 'data', 'error', 'response',
    'config', 'options', 'params', 'args', 'props', 'state', 'context',
    'i', 'j', 'k', 'n', 'x', 'y', 'cb', 'fn', 'el', 'ev', 'err',
})

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # ---- Imports ----
    for m in _IMPORT_RE.finditer(text):
        val = next((g for g in m.groups() if g), None)
        if val:
            edges.append((fid, val.strip(), "imports"))

    # ---- Function declarations ----
    seen_names: set[str] = set()
    for m in _FUNC_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen_names:
            seen_names.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # ---- Arrow function / const component declarations ----
    for m in _ARROW_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1 and name not in seen_names and name not in _SKIP_NAMES:
            seen_names.add(name)
            line = text[:m.start()].count('\n') + 1
            func_id = nid("function", rel, name)
            nodes.append((func_id, "function", name, rel, line, None))
            edges.append((fid, func_id, "contains"))

    # ---- Classes ----
    for m in _CLASS_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            class_id = nid("class", rel, name)
            nodes.append((class_id, "class", name, rel, line, None))
            edges.append((fid, class_id, "contains"))
            # extends
            if m.group(2):
                base = m.group(2).strip().rsplit(".", 1)[-1]
                edges.append((class_id, base, "inherits"))
            # implements
            if m.group(3):
                for iface in m.group(3).split(","):
                    iface = iface.strip().rsplit(".", 1)[-1]
                    if iface:
                        edges.append((class_id, iface, "implements"))

    # ---- Interfaces ----
    for m in _INTERFACE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            iface_id = nid("interface", rel, name)
            nodes.append((iface_id, "interface", name, rel, line, None))
            edges.append((fid, iface_id, "contains"))
            # extends
            if m.group(2):
                for base in m.group(2).split(","):
                    base = base.strip().split("<")[0].strip()
                    if base:
                        edges.append((iface_id, base, "inherits"))

    # ---- Type aliases ----
    for m in _TYPE_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            type_id = nid("interface", rel, name)  # store types as interface kind
            nodes.append((type_id, "interface", name, rel, line, None))
            edges.append((fid, type_id, "contains"))

    # ---- Enums ----
    for m in _ENUM_RE.finditer(text):
        name = m.group(1)
        if name and len(name) > 1:
            line = text[:m.start()].count('\n') + 1
            enum_id = nid("enum", rel, name)
            nodes.append((enum_id, "enum", name, rel, line, None))
            edges.append((fid, enum_id, "contains"))
