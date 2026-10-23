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

def _dotted_parts(node, src: bytes) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; None if any link is not a plain identifier.

    A chained or computed object (`db.query(X).filter`, `x[0].y`) returns None,
    so calls on library results never become `calls` edges.
    """
    if node.type == "identifier":
        return [txt(node, src)]
    if node.type == "attribute":
        obj = node.child_by_field_name("object")
        attr = node.child_by_field_name("attribute")
        head = _dotted_parts(obj, src) if obj else None
        if head is None or attr is None:
            return None
        return head + [txt(attr, src)]
    return None


def python_import_aliases(root, src: bytes) -> dict[str, str]:
    """Local alias -> imported module/name, for `import a.b as z` and
    `from a import b as c`. Lets `z.func()` qualify as `b.func`."""
    aliases: dict[str, str] = {}
    for node in walk(root):
        if node.type not in ("import_statement", "import_from_statement"):
            continue
        for ch in node.children:
            if ch.type != "aliased_import":
                continue
            name = ch.child_by_field_name("name")
            alias = ch.child_by_field_name("alias")
            if name and alias:
                aliases[txt(alias, src)] = txt(name, src).rsplit(".", 1)[-1]
    return aliases


def calls_python(fn_node, src: bytes, fn_types: frozenset,
                 aliases: dict[str, str] | None = None) -> set[str]:
    """Callee names invoked from inside a Python function/method body.

    Bare `foo()` and `self.foo()` / `cls.foo()` give `foo`. A call through a
    module or object gives the dotted chain `a.b.foo`, with a one-part object
    expanded through import aliases (`iap_service.verify_receipt()` ->
    `iap_service.verify_receipt`, `crud.fcm.create()` -> `crud.fcm.create`).
    `builder._link_calls` resolves both forms. Skips builtins,
    dunder names and calls on chained objects. Does not descend into nested
    function/class definitions.
    """
    calls: set[str] = set()
    aliases = aliases or {}

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
                        parts = _dotted_parts(obj, src) if obj else None
                        name = txt(attr, src) if attr else ""
                        if parts and name and not (name.startswith("__") and name.endswith("__")):
                            if parts in (["self"], ["cls"]):
                                calls.add(name)
                            else:
                                if len(parts) == 1:
                                    parts = [aliases.get(parts[0], parts[0])]
                                calls.add(".".join(parts + [name]))
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


# --- JS / TS -----------------------------------------------------------------

JS_EXTS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
# `const f = () => {}`, `const f = function () {}`, class field `f = () => {}`
JS_BOUND_TYPES = frozenset({"variable_declarator", "public_field_definition",
                            "field_definition"})
JS_FN_VALUE_TYPES = frozenset({"arrow_function", "function_expression",
                               "function", "generator_function"})
# Roots of member calls that are platform globals, never project code.
JS_GLOBAL_ROOTS = frozenset({
    "console", "Math", "JSON", "Object", "Array", "String", "Number", "Promise",
    "Date", "Reflect", "Symbol", "window", "document", "navigator", "location",
    "history", "localStorage", "sessionStorage", "process", "module", "exports",
    "require", "chrome", "browser", "globalThis", "self", "Intl", "URL",
    "performance", "crypto", "fetch", "Buffer", "React",
})


def js_bound_fn_name(node, src: bytes) -> str | None:
    """Name of a function bound to a variable or class field, else None."""
    if node.type not in JS_BOUND_TYPES:
        return None
    value = node.child_by_field_name("value")
    if value is None or value.type not in JS_FN_VALUE_TYPES:
        return None
    name = node.child_by_field_name("name") or node.child_by_field_name("property")
    if name is None or name.type not in ("identifier", "property_identifier",
                                         "private_property_identifier"):
        return None
    return txt(name, src)


def _string_spec(node, src: bytes) -> str | None:
    for ch in walk(node):
        if ch.type == "string_fragment":
            return txt(ch, src)
    return None


def js_import_map(root, src: bytes) -> dict[str, tuple[str, str]]:
    """Local name -> (module specifier, imported name) for one JS/TS file.

    Imported name is the exported name for `{ a as b }` and destructured
    `require`, `default` for a default import, `*` for a namespace import or
    a whole-module `require`.
    """
    imap: dict[str, tuple[str, str]] = {}
    for node in walk(root):
        if node.type == "import_statement":
            source = node.child_by_field_name("source")
            spec = _string_spec(source, src) if source else None
            if not spec:
                continue
            for clause in node.children:
                if clause.type != "import_clause":
                    continue
                for ch in clause.children:
                    if ch.type == "identifier":
                        imap[txt(ch, src)] = (spec, "default")
                    elif ch.type == "namespace_import":
                        for n in ch.children:
                            if n.type == "identifier":
                                imap[txt(n, src)] = (spec, "*")
                    elif ch.type == "named_imports":
                        for sp in ch.children:
                            if sp.type != "import_specifier":
                                continue
                            name = sp.child_by_field_name("name")
                            alias = sp.child_by_field_name("alias")
                            if name:
                                imap[txt(alias or name, src)] = (spec, txt(name, src))
        elif node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is None or value.type != "call_expression":
                continue
            fn = value.child_by_field_name("function")
            if fn is None or txt(fn, src) != "require":
                continue
            args = value.child_by_field_name("arguments")
            spec = _string_spec(args, src) if args else None
            target = node.child_by_field_name("name")
            if not spec or target is None:
                continue
            if target.type == "identifier":
                imap[txt(target, src)] = (spec, "*")
            elif target.type == "object_pattern":
                for p in target.children:
                    if p.type == "shorthand_property_identifier_pattern":
                        imap[txt(p, src)] = (spec, txt(p, src))
                    elif p.type == "pair_pattern":
                        key = p.child_by_field_name("key")
                        val = p.child_by_field_name("value")
                        if key and val and val.type == "identifier":
                            imap[txt(val, src)] = (spec, txt(key, src))
    return imap


def _js_dotted(node, src: bytes) -> list[str] | None:
    if node.type in ("identifier", "this"):
        return [txt(node, src)]
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        prop = node.child_by_field_name("property")
        head = _js_dotted(obj, src) if obj else None
        if head is None or prop is None or prop.type != "property_identifier":
            return None
        return head + [txt(prop, src)]
    return None


def calls_js(fn_node, src: bytes, stop_types: frozenset,
             imap: dict[str, tuple[str, str]]) -> set[str]:
    """Callee references from a JS/TS function body.

    - imported `f()` / `ns.f()` -> `js:<specifier>#<name>` (resolved through
      the import in `builder._link_calls`);
    - local `f()` / `this.f()` -> `jsl:f` (same file only);
    - `a.b.f()` on a local object -> `a.b.f` (the Python dotted rules);
    - member calls on platform globals and chained calls -> nothing.
    Does not descend into nested function declarations or classes.
    """
    calls: set[str] = set()
    body = fn_node.child_by_field_name("value") if fn_node.type in JS_BOUND_TYPES else fn_node

    def _visit(node):
        for child in node.children:
            if child.type in stop_types:
                continue
            if child.type == "call_expression":
                fn = child.child_by_field_name("function")
                if fn is not None and fn.type == "identifier":
                    name = txt(fn, src)
                    if name in imap:
                        spec, imported = imap[name]
                        calls.add(f"js:{spec}#{name if imported in ('*', 'default') else imported}")
                    elif len(name) >= 2:
                        calls.add(f"jsl:{name}")
                elif fn is not None and fn.type == "member_expression":
                    obj = fn.child_by_field_name("object")
                    prop = fn.child_by_field_name("property")
                    parts = _js_dotted(obj, src) if obj else None
                    if parts and prop is not None and prop.type == "property_identifier":
                        name = txt(prop, src)
                        root = parts[0]
                        if parts == ["this"]:
                            calls.add(f"jsl:{name}")
                        elif root in imap:
                            if len(parts) == 1:
                                calls.add(f"js:{imap[root][0]}#{name}")
                        elif root not in JS_GLOBAL_ROOTS and root != "this":
                            calls.add(".".join(parts + [name]))
            _visit(child)

    if body is not None:
        _visit(body)
    return calls


# --- Kotlin ------------------------------------------------------------------

def _kt_dotted(node, src: bytes) -> list[str] | None:
    if node.type in ("identifier", "simple_identifier"):
        return [txt(node, src)]
    if node.type == "this_expression":
        return ["this"]
    if node.type == "navigation_expression" and node.children:
        head = _kt_dotted(node.children[0], src)
        last = node.children[-1]
        if last.type == "navigation_suffix":
            last = next((c for c in last.children
                         if c.type in ("identifier", "simple_identifier")), None)
        if head is None or last is None or last.type not in ("identifier", "simple_identifier"):
            return None
        return head + [txt(last, src)]
    return None


def calls_kotlin(fn_node, src: bytes, stop_types: frozenset) -> set[str]:
    """Callee names from a Kotlin function body: `f()` and `this.f()` give `f`,
    `a.b.f()` gives `a.b.f`. Chained calls give nothing."""
    calls: set[str] = set()

    def _visit(node):
        for child in node.children:
            if child.type in stop_types:
                continue
            if child.type == "call_expression" and child.children:
                parts = _kt_dotted(child.children[0], src)
                if parts and len(parts[-1]) >= 2:
                    if len(parts) == 1:
                        calls.add(parts[0])
                    elif parts[:-1] == ["this"]:
                        calls.add(parts[-1])
                    else:
                        calls.add(".".join(parts))
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
CFG[".mjs"] = CFG[".js"]
CFG[".cjs"] = CFG[".js"]
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