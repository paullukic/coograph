"""Per-language extractors + config table.

Holds the data and functions that vary by language so the orchestrator in
`parser.py` stays small. Three groups:

  * Builtins / magic name skip-lists.
  * Per-language `imports` extractors (file-level edges).
  * Per-language `calls` extractors (function-level edges).
  * `CFG` lookup: ext -> {class_types, fn_types, import_fn}.
  * `KIND_OVERRIDE`: AST node type -> graph node kind.

Add a new language by:
  1. Adding its package to `core.PKG_MAP`.
  2. Writing an `_imports_<lang>` function here.
  3. Adding a `CFG[".ext"]` entry.
"""

from __future__ import annotations

from .core import txt, field, walk

# ---------------------------------------------------------------------------
# Skip lists
# ---------------------------------------------------------------------------

BUILTINS_PY = frozenset({
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "hasattr", "getattr", "setattr",
    "super", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "open", "repr", "format", "any", "all", "min", "max", "sum", "abs",
    "vars", "dir", "id", "hash", "iter", "next", "callable",
    "staticmethod", "classmethod", "property", "object",
})

PHP_MAGIC = frozenset({
    "__construct", "__destruct", "__call", "__callStatic", "__get",
    "__set", "__isset", "__unset", "__sleep", "__wakeup", "__toString",
    "__invoke", "__set_state", "__clone", "__debugInfo",
})


# ---------------------------------------------------------------------------
# Call extractors
# ---------------------------------------------------------------------------

def calls_python(fn_node, src: bytes, fn_types: frozenset) -> set[str]:
    """Callee names invoked from inside a Python function/method body.

    Resolves bare identifiers and `self.method()` calls. Skips builtins and
    dunder names. Does not descend into nested function/class definitions.
    """
    calls: set[str] = set()

    def _visit(node):
        for child in node.children:
            if child.type in fn_types or child.type == "class_definition":
                continue
            if child.type == "call":
                fn_child = child.child_by_field_name("function")
                if fn_child:
                    if fn_child.type == "identifier":
                        name = txt(fn_child, src)
                        if (name
                                and not (name.startswith("__") and name.endswith("__"))
                                and name not in BUILTINS_PY):
                            calls.add(name)
                    elif fn_child.type == "attribute":
                        obj = fn_child.child_by_field_name("object")
                        attr = fn_child.child_by_field_name("attribute")
                        if obj and attr and txt(obj, src) == "self":
                            name = txt(attr, src)
                            if name and not (name.startswith("__") and name.endswith("__")):
                                calls.add(name)
            _visit(child)

    _visit(fn_node)
    return calls


def calls_php(fn_node, src: bytes, fn_types: frozenset, refs: set[str]) -> set[str]:
    """Callee names + class refs from a PHP method/function body.

    Mutates `refs` in place with class-name strings (treated as imports so
    `_resolve_file_deps` can wire `depends_on` edges between files).
    Returns the set of callee names for `calls` edges.
    """
    calls: set[str] = set()

    def _last_name(node) -> str | None:
        if node.type == "name":
            return txt(node, src)
        if node.type == "qualified_name":
            return txt(node, src).rsplit("\\", 1)[-1]
        return None

    def _visit(node):
        for child in node.children:
            if child.type in fn_types:
                continue
            t = child.type
            if t == "function_call_expression":
                fn = child.child_by_field_name("function")
                if fn is not None:
                    name = _last_name(fn)
                    if name and name not in PHP_MAGIC:
                        calls.add(name)
            elif t == "member_call_expression":
                nm = child.child_by_field_name("name")
                if nm is not None:
                    name = txt(nm, src)
                    if name and name not in PHP_MAGIC:
                        calls.add(name)
            elif t == "scoped_call_expression":
                scope = child.child_by_field_name("scope")
                nm = child.child_by_field_name("name")
                if scope is not None:
                    sc = _last_name(scope)
                    if sc:
                        refs.add(sc)
                if nm is not None:
                    name = txt(nm, src)
                    if name and name not in PHP_MAGIC:
                        calls.add(name)
            elif t == "object_creation_expression":
                for c2 in child.children:
                    sc = _last_name(c2)
                    if sc:
                        refs.add(sc)
                        break
            elif t == "class_constant_access_expression":
                # `Foo::class` — capture the scope identifier as a class ref
                scope = child.child_by_field_name("scope")
                if scope is not None:
                    sc = _last_name(scope)
                    if sc:
                        refs.add(sc)
            _visit(child)

    _visit(fn_node)
    return calls


# ---------------------------------------------------------------------------
# Import extractors
# ---------------------------------------------------------------------------

def imports_python(root, src, fid, edges):
    for node in walk(root):
        if node.type == "import_statement":
            for ch in node.children:
                if ch.type == "dotted_name":
                    edges.append((fid, txt(ch, src), "imports"))
                elif ch.type == "aliased_import":
                    n = ch.child_by_field_name("name")
                    if n:
                        edges.append((fid, txt(n, src), "imports"))
        elif node.type == "import_from_statement":
            m = node.child_by_field_name("module_name")
            if m:
                edges.append((fid, txt(m, src), "imports"))


def imports_js(root, src, fid, edges):
    for node in walk(root):
        if node.type == "import_statement":
            src_node = node.child_by_field_name("source")
            if src_node:
                for ch in src_node.children:
                    if ch.type == "string_fragment":
                        edges.append((fid, txt(ch, src), "imports"))
        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn and txt(fn, src) == "require":
                args = node.child_by_field_name("arguments")
                if args:
                    for ch in walk(args):
                        if ch.type == "string_fragment":
                            edges.append((fid, txt(ch, src), "imports"))
                            break


def imports_java(root, src, fid, edges):
    for node in walk(root):
        if node.type == "import_declaration":
            for ch in node.children:
                if ch.type in ("scoped_identifier", "identifier", "asterisk"):
                    if ch.type != "asterisk":
                        edges.append((fid, txt(ch, src), "imports"))


def imports_go(root, src, fid, edges):
    for node in walk(root):
        if node.type == "import_spec":
            path_node = node.child_by_field_name("path")
            if path_node:
                val = txt(path_node, src).strip("\"'`")
                edges.append((fid, val, "imports"))


def imports_rust(root, src, fid, edges):
    for node in walk(root):
        if node.type == "use_declaration":
            arg = node.child_by_field_name("argument")
            if arg:
                edges.append((fid, txt(arg, src), "imports"))


def imports_ruby(root, src, fid, edges):
    for node in walk(root):
        if node.type == "call" and field(node, "method", src) in ("require", "require_relative"):
            args = node.child_by_field_name("arguments")
            if args:
                for ch in walk(args):
                    if ch.type == "string_content":
                        edges.append((fid, txt(ch, src), "imports"))
                        break


def imports_cs(root, src, fid, edges):
    for node in walk(root):
        if node.type == "using_directive":
            name = node.child_by_field_name("name")
            if name:
                edges.append((fid, txt(name, src), "imports"))


def imports_php(root, src, fid, edges):
    for node in walk(root):
        if node.type == "namespace_use_declaration":
            for ch in walk(node):
                if ch.type == "namespace_use_clause":
                    n = ch.child_by_field_name("name")
                    if n:
                        edges.append((fid, txt(n, src).replace("\\", "."), "imports"))


def imports_kotlin(root, src, fid, edges):
    for node in walk(root):
        if node.type == "import_header":
            idn = node.child_by_field_name("identifier")
            if idn:
                edges.append((fid, txt(idn, src), "imports"))


# ---------------------------------------------------------------------------
# Language config table
# ---------------------------------------------------------------------------
# class_types: AST node types representing class/struct/interface/enum
# fn_types:    AST node types representing functions/methods
# import_fn:   callable(root, src, fid, edges)

CFG: dict[str, dict] = {
    ".py": dict(
        class_types=frozenset({"class_definition"}),
        fn_types=frozenset({"function_definition"}),
        import_fn=imports_python,
    ),
    ".js": dict(
        class_types=frozenset({"class_declaration", "class"}),
        fn_types=frozenset({"function_declaration", "method_definition"}),
        import_fn=imports_js,
    ),
    ".ts": dict(
        class_types=frozenset({"class_declaration", "class", "abstract_class_declaration"}),
        fn_types=frozenset({"function_declaration", "method_definition"}),
        import_fn=imports_js,
    ),
    ".java": dict(
        class_types=frozenset({"class_declaration", "interface_declaration",
                               "enum_declaration", "record_declaration",
                               "annotation_type_declaration"}),
        fn_types=frozenset({"method_declaration", "constructor_declaration"}),
        import_fn=imports_java,
    ),
    ".kt": dict(
        class_types=frozenset({"class_declaration", "object_declaration",
                               "interface_declaration"}),
        fn_types=frozenset({"function_declaration"}),
        import_fn=imports_kotlin,
    ),
    ".go": dict(
        class_types=frozenset({"type_declaration"}),
        fn_types=frozenset({"function_declaration", "method_declaration"}),
        import_fn=imports_go,
    ),
    ".rs": dict(
        class_types=frozenset({"struct_item", "enum_item", "trait_item"}),
        fn_types=frozenset({"function_item"}),
        import_fn=imports_rust,
    ),
    ".rb": dict(
        class_types=frozenset({"class", "module"}),
        fn_types=frozenset({"method", "singleton_method"}),
        import_fn=imports_ruby,
    ),
    ".cs": dict(
        class_types=frozenset({"class_declaration", "interface_declaration",
                               "enum_declaration", "struct_declaration",
                               "record_declaration"}),
        fn_types=frozenset({"method_declaration", "constructor_declaration",
                            "operator_declaration"}),
        import_fn=imports_cs,
    ),
    ".php": dict(
        class_types=frozenset({"class_declaration", "interface_declaration",
                               "trait_declaration", "enum_declaration"}),
        fn_types=frozenset({"method_declaration", "function_definition"}),
        import_fn=imports_php,
    ),
}
CFG[".jsx"] = CFG[".js"]
CFG[".tsx"] = CFG[".ts"]


KIND_OVERRIDE: dict[str, str] = {
    "interface_declaration":     "interface",
    "interface":                 "interface",
    "trait_item":                "interface",
    "trait_declaration":         "interface",
    "annotation_type_declaration": "interface",
    "enum_declaration":          "enum",
    "enum_item":                 "enum",
}