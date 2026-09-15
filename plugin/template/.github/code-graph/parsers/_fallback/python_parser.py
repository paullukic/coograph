"""Python parser — uses stdlib ast for accurate parsing."""

from __future__ import annotations

import ast
from pathlib import Path

from .. import register, nid

STACK = "python"
EXTENSIONS = frozenset({".py"})

_BUILTINS = frozenset({
    'print', 'len', 'range', 'str', 'int', 'float', 'bool', 'list', 'dict',
    'set', 'tuple', 'type', 'isinstance', 'hasattr', 'getattr', 'setattr',
    'super', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
    'open', 'repr', 'format', 'any', 'all', 'min', 'max', 'sum', 'abs',
    'vars', 'dir', 'id', 'hash', 'iter', 'next', 'callable',
    'staticmethod', 'classmethod', 'property',
})


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except SyntaxError:
        return

    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # Stack entries: (class_name, class_nid)
    class_stack: list[tuple[str, str]] = []

    class _V(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                edges.append((fid, alias.name, "imports"))
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                edges.append((fid, node.module, "imports"))
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            cid = nid("class", rel, node.name)
            nodes.append((cid, "class", node.name, rel, node.lineno, node.end_lineno))
            edges.append((fid, cid, "contains"))
            for base in node.bases:
                base_name = _resolve_name(base)
                if base_name:
                    edges.append((cid, base_name, "inherits"))
            class_stack.append((node.name, cid))
            self.generic_visit(node)
            class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if class_stack:
                class_name, class_nid = class_stack[-1]
                # Qualify name to avoid nid collisions between same-named methods
                func_nid = nid("method", rel, f"{class_name}.{node.name}")
                nodes.append((func_nid, "method", node.name, rel, node.lineno, node.end_lineno))
                edges.append((class_nid, func_nid, "contains"))
            else:
                func_nid = nid("function", rel, node.name)
                nodes.append((func_nid, "function", node.name, rel, node.lineno, node.end_lineno))
                edges.append((fid, func_nid, "contains"))
            # Extract calls within this function body (stop at nested defs)
            call_names: set[str] = set()
            for stmt in node.body:
                _collect_calls(stmt, call_names)
            for callee in call_names:
                edges.append((func_nid, callee, "calls"))
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    _V().visit(tree)


def _resolve_call(node: ast.expr) -> str | None:
    """Extract callee name from a Call's func node (simple names and self.method only)."""
    if isinstance(node, ast.Name):
        name = node.id
        if name.startswith("__") and name.endswith("__"):
            return None
        if name in _BUILTINS:
            return None
        return name
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                return None
            return attr
    return None


def _collect_calls(node: ast.AST, out: set[str]) -> None:
    """Recursively collect call names, stopping at nested function/class boundaries."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return
    if isinstance(node, ast.Call):
        callee = _resolve_call(node.func)
        if callee:
            out.add(callee)
    for child in ast.iter_child_nodes(node):
        _collect_calls(child, out)


def _resolve_name(node: ast.expr) -> str | None:
    """Extract a dotted name from an AST node (e.g. base class)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _resolve_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None
