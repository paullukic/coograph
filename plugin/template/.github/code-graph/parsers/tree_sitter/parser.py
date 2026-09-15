"""Tree-sitter `_parse_file` orchestrator.

Three sequential passes per file:
  1. Classes / structs / interfaces / enums (+ inheritance edges).
  2. Functions / methods (+ contains edges; method-vs-function via class ancestor).
  3. Calls (Python and PHP only — emit `calls` edges + PHP `imports` for class refs).

Then runs the language-specific import extractor for file-level edges.

Per-language quirks (Go method receivers, Rust impl blocks, PHP base_clause,
PHP `Foo::class`) live here in small inline branches. Anything reusable across
languages goes into `core.py` (helpers) or `languages.py` (CFG / extractors).
"""

from __future__ import annotations

from pathlib import Path

from .. import nid
from .core import Parser, ancestor, get_lang, txt, walk
from .languages import CFG, KIND_OVERRIDE, calls_php, calls_python


def parse_file(path: Path, rel: str, nodes: list, edges: list) -> None:
    ext = path.suffix.lower()
    lang = get_lang(ext)
    cfg = CFG.get(ext)
    if lang is None or cfg is None:
        nodes.append((nid("file", rel, rel), "file", rel, rel, None, None))
        return

    try:
        src = path.read_bytes()
    except OSError:
        return

    tree = Parser(lang).parse(src)
    root = tree.root_node

    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    class_types: frozenset = cfg["class_types"]
    fn_types: frozenset = cfg["fn_types"]

    _pass_classes(root, src, ext, rel, fid, class_types, nodes, edges)
    _pass_functions(root, src, ext, rel, fid, class_types, fn_types, nodes, edges)
    _pass_calls(root, src, ext, rel, fid, class_types, fn_types, edges)

    cfg["import_fn"](root, src, fid, edges)


# ---------------------------------------------------------------------------
# Pass 1: classes
# ---------------------------------------------------------------------------

def _pass_classes(root, src, ext, rel, fid, class_types, nodes, edges):
    for node in walk(root):
        if node.type not in class_types:
            continue

        # Go: type_declaration wraps type_spec which wraps struct/interface
        if ext == ".go" and node.type == "type_declaration":
            for spec in node.children:
                if spec.type != "type_spec":
                    continue
                name_node = spec.child_by_field_name("name")
                type_node = spec.child_by_field_name("type")
                if not name_node or not type_node:
                    continue
                name = txt(name_node, src)
                kind = "interface" if type_node.type == "interface_type" else "class"
                cls_id = nid(kind, rel, name)
                nodes.append((cls_id, kind, name, rel,
                              node.start_point[0] + 1, node.end_point[0] + 1))
                edges.append((fid, cls_id, "contains"))
            continue

        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        name = txt(name_node, src)
        if not name or len(name) < 2:
            continue

        kind = KIND_OVERRIDE.get(node.type, "class")
        cls_id = nid(kind, rel, name)
        nodes.append((cls_id, kind, name, rel,
                      node.start_point[0] + 1, node.end_point[0] + 1))
        edges.append((fid, cls_id, "contains"))

        _emit_inheritance(node, src, ext, cls_id, edges)


def _emit_inheritance(node, src, ext, cls_id, edges):
    if ext == ".py":
        superclasses = node.child_by_field_name("superclasses")
        if superclasses:
            for ch in superclasses.children:
                if ch.type == "identifier":
                    edges.append((cls_id, txt(ch, src), "inherits"))
    elif ext == ".php":
        # PHP uses base_clause (extends) + class_interface_clause (implements).
        # Children are `name` or `qualified_name`; take the last segment.
        for ch in node.children:
            if ch.type in ("base_clause", "class_interface_clause"):
                edge_kind = "inherits" if ch.type == "base_clause" else "implements"
                for tn in ch.children:
                    if tn.type == "name":
                        edges.append((cls_id, txt(tn, src), edge_kind))
                    elif tn.type == "qualified_name":
                        edges.append((cls_id, txt(tn, src).rsplit("\\", 1)[-1], edge_kind))
    elif ext in (".java", ".kt", ".cs"):
        for ch in walk(node):
            if ch.type in ("super_interfaces", "extends_interfaces"):
                for tn in walk(ch):
                    if tn.type == "type_identifier":
                        edges.append((cls_id, txt(tn, src), "inherits"))
            elif ch.type == "superclass":
                for tn in walk(ch):
                    if tn.type == "type_identifier":
                        edges.append((cls_id, txt(tn, src), "inherits"))


# ---------------------------------------------------------------------------
# Pass 2: functions / methods
# ---------------------------------------------------------------------------

def _pass_functions(root, src, ext, rel, fid, class_types, fn_types, nodes, edges):
    for node in walk(root):
        if node.type not in fn_types:
            continue

        # Go method_declaration: receiver determines the struct owner
        if ext == ".go" and node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            recv = node.child_by_field_name("receiver")
            if not name_node or not recv:
                continue
            name = txt(name_node, src)
            receiver_type = None
            for ch in walk(recv):
                if ch.type == "type_identifier":
                    receiver_type = txt(ch, src)
                    break
            if receiver_type:
                fn_nid = nid("method", rel, f"{receiver_type}.{name}")
                nodes.append((fn_nid, "method", name, rel,
                              node.start_point[0] + 1, node.end_point[0] + 1))
                edges.append((nid("class", rel, receiver_type), fn_nid, "contains"))
            else:
                fn_nid = nid("function", rel, name)
                nodes.append((fn_nid, "function", name, rel,
                              node.start_point[0] + 1, node.end_point[0] + 1))
                edges.append((fid, fn_nid, "contains"))
            continue

        # Rust: functions inside impl blocks are methods
        if ext == ".rs":
            impl_anc = ancestor(node, frozenset({"impl_item"}))
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = txt(name_node, src)
            if not name or len(name) < 2:
                continue
            if impl_anc:
                type_node = impl_anc.child_by_field_name("type")
                struct_name = txt(type_node, src) if type_node else None
                if struct_name:
                    fn_nid = nid("method", rel, f"{struct_name}.{name}")
                    nodes.append((fn_nid, "method", name, rel,
                                  node.start_point[0] + 1, node.end_point[0] + 1))
                    edges.append((nid("class", rel, struct_name), fn_nid, "contains"))
                    continue
            fn_nid = nid("function", rel, f"{name}_{node.start_point[0]+1}")
            nodes.append((fn_nid, "function", name, rel,
                          node.start_point[0] + 1, node.end_point[0] + 1))
            edges.append((fid, fn_nid, "contains"))
            continue

        # General case: enclosing class ancestor -> method
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        name = txt(name_node, src)
        if not name or len(name) < 2:
            continue

        cls_anc = ancestor(node, class_types)
        if cls_anc is not None:
            cls_name_node = cls_anc.child_by_field_name("name")
            cls_name = txt(cls_name_node, src) if cls_name_node else None
            if cls_name:
                fn_nid = nid("method", rel, f"{cls_name}.{name}")
                nodes.append((fn_nid, "method", name, rel,
                              node.start_point[0] + 1, node.end_point[0] + 1))
                edges.append((nid("class", rel, cls_name), fn_nid, "contains"))
                continue

        fn_nid = nid("function", rel, f"{name}_{node.start_point[0]+1}")
        nodes.append((fn_nid, "function", name, rel,
                      node.start_point[0] + 1, node.end_point[0] + 1))
        edges.append((fid, fn_nid, "contains"))


# ---------------------------------------------------------------------------
# Pass 3: calls (Python + PHP)
# ---------------------------------------------------------------------------

def _pass_calls(root, src, ext, rel, fid, class_types, fn_types, edges):
    if ext == ".py":
        for fn_node in walk(root):
            if fn_node.type not in fn_types:
                continue
            fn_nid = _fn_nid_for(fn_node, src, ext, rel, class_types)
            if fn_nid is None:
                continue
            for callee in calls_python(fn_node, src, fn_types):
                edges.append((fn_nid, callee, "calls"))
    elif ext == ".php":
        file_refs: set[str] = set()
        for fn_node in walk(root):
            if fn_node.type not in fn_types:
                continue
            fn_nid = _fn_nid_for(fn_node, src, ext, rel, class_types)
            if fn_nid is None:
                continue
            for callee in calls_php(fn_node, src, fn_types, file_refs):
                edges.append((fn_nid, callee, "calls"))
        # File-level: emit class refs (Foo::class, new Foo()) as imports so
        # `_resolve_file_deps` can wire `depends_on` edges between files.
        for ref in file_refs:
            edges.append((fid, ref, "imports"))


def _fn_nid_for(fn_node, src, ext, rel, class_types) -> str | None:
    """Compute the same nid `_pass_functions` produced for this function/method."""
    name_node = fn_node.child_by_field_name("name")
    if not name_node:
        return None
    fn_name = txt(name_node, src)
    if not fn_name or len(fn_name) < 2:
        return None
    cls_anc = ancestor(fn_node, class_types)
    if cls_anc:
        cls_name_node = cls_anc.child_by_field_name("name")
        cls_name = txt(cls_name_node, src) if cls_name_node else None
        if not cls_name:
            return None
        return nid("method", rel, f"{cls_name}.{fn_name}")
    return nid("function", rel, f"{fn_name}_{fn_node.start_point[0]+1}")