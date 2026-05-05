"""Java / Kotlin / Scala parser with inheritance, annotations, and enums."""

from __future__ import annotations

import re
from pathlib import Path

from .. import register, nid, find_scope, brace_end

STACK = "java"
EXTENSIONS = frozenset({".java", ".kt", ".scala"})

# ---------------------------------------------------------------------------
# Java-specific patterns
# ---------------------------------------------------------------------------

_JAVA_KEYWORDS = frozenset({
    'if', 'for', 'while', 'switch', 'catch', 'return', 'new', 'throw',
    'class', 'interface', 'enum', 'import', 'package', 'assert', 'super',
    'this', 'void', 'null', 'true', 'false', 'try', 'finally', 'default',
    'do', 'break', 'continue', 'case', 'else', 'instanceof', 'synchronized',
})

# Lines starting with these tokens are statements, not method declarations
_STMT_PREFIX_RE = re.compile(
    r'^\s*(?:'
    r'(?:return|new|throw|if|for|while|switch|catch|try|else|do|break|continue|case|assert|yield)\b'
    r'|[.*/]'  # chained calls, Javadoc, comments
    r'|[\w<>\[\]?]+\s+\w+\s*='  # variable assignments (val x =, String x =)
    r')'
)

_JAVA_CLASS_RE = re.compile(
    r'(?:(?:public|private|protected|abstract|final|static|strictfp)\s+)*'
    r'(class|interface|enum|@interface)\s+'
    r'(\w+)'
    r'(?:\s*<[^{]*?>)?'
    r'((?:\s+extends\s+[\w.<>,\s]+?)?)'
    r'((?:\s+implements\s+[\w.<>,\s]+?)?)'
    r'\s*\{',
    re.MULTILINE | re.DOTALL,
)

_JAVA_METHOD_RE = re.compile(
    r'(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|override)\s+)*'
    r'(?:<[^>]+>\s+)?'
    r'([\w<>\[\]?.]+)\s+'
    r'(\w+)\s*\(',
    re.MULTILINE,
)

# Matches method calls: identifier followed by '(' — used for call extraction
_JAVA_CALL_RE = re.compile(r'\b(\w+)\s*\(', re.MULTILINE)

_JAVA_ANNOTATION_RE = re.compile(r'^\s*@(\w+)', re.MULTILINE)

# ---------------------------------------------------------------------------
# Kotlin-specific patterns
# ---------------------------------------------------------------------------

_KT_CLASS_RE = re.compile(
    r'(?:(?:data|sealed|abstract|open|inner|private|internal|protected|public)\s+)*'
    r'(class|interface|enum\s+class|object)\s+'
    r'(\w+)',
    re.MULTILINE,
)

_KT_FUN_RE = re.compile(
    r'(?:(?:private|internal|protected|public|override|suspend|inline|operator)\s+)*'
    r'fun\s+(?:<[^>]+>\s+)?(\w+)\s*[(<]',
    re.MULTILINE,
)

_KT_IMPORT_RE = re.compile(r'^import\s+([\w.]+)', re.MULTILINE)

# ---------------------------------------------------------------------------
# Scala-specific patterns
# ---------------------------------------------------------------------------

_SCALA_CLASS_RE = re.compile(
    r'(?:(?:case|abstract|sealed|final|private|protected)\s+)*'
    r'(class|trait|object)\s+(\w+)',
    re.MULTILINE,
)

_SCALA_DEF_RE = re.compile(r'def\s+(\w+)\s*[\[(<]', re.MULTILINE)
_SCALA_IMPORT_RE = re.compile(r'^import\s+([\w.{}*]+)', re.MULTILINE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_generics(s: str) -> str:
    depth, result = 0, []
    for ch in s:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth = max(0, depth - 1)
        elif depth == 0:
            result.append(ch)
    return "".join(result).strip()


def _split_java_types(raw: str) -> list[str]:
    stripped = _strip_generics(raw)
    return [t.strip().rsplit(".", 1)[-1] for t in stripped.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_java(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    # Imports
    for m in re.finditer(r'^import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;', text, re.MULTILINE):
        edges.append((fid, m.group(1).strip(), "imports"))

    # Classes / interfaces / enums — build scope list for method attribution
    scopes = []  # (node_id, open_brace_pos, close_brace_pos)
    for m in _JAVA_CLASS_RE.finditer(text):
        decl_type, name = m.group(1), m.group(2)
        extends_raw, implements_raw = m.group(3), m.group(4)
        line = text[:m.start()].count('\n') + 1

        kind = "class"
        if decl_type in ("interface", "@interface"):
            kind = "interface"
        elif decl_type == "enum":
            kind = "enum"

        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))

        if extends_raw and extends_raw.strip():
            raw = extends_raw.strip()
            if raw.startswith("extends"):
                raw = raw[7:].strip()
            for base in _split_java_types(raw):
                if base:
                    edges.append((node_id, base, "inherits"))

        if implements_raw and implements_raw.strip():
            raw = implements_raw.strip()
            if raw.startswith("implements"):
                raw = raw[10:].strip()
            for iface in _split_java_types(raw):
                if iface:
                    edges.append((node_id, iface, "implements"))

        # Regex ends with \s*\{ so m.end()-1 is the opening brace
        open_pos = m.end() - 1
        scopes.append((node_id, open_pos, brace_end(text, open_pos)))

    # Precompute line start offsets for position-based scope lookup
    line_starts = [0]
    for ln in text.splitlines():
        line_starts.append(line_starts[-1] + len(ln) + 1)

    # Methods
    method_scopes = []  # (method_nid, open_brace_pos, close_brace_pos)
    # Types that appear as return-type but should disqualify a method match
    _BAD_TYPES = frozenset({
        'new', 'return', 'throw', 'if', 'for', 'while', 'switch', 'catch',
        'try', 'else', 'do', 'break', 'continue', 'case', 'assert', 'super',
        'this', 'null', 'true', 'false', 'import', 'package', 'instanceof',
    })
    for lineno, line_text in enumerate(text.splitlines(), 1):
        if _STMT_PREFIX_RE.match(line_text):
            continue
        for m in _JAVA_METHOD_RE.finditer(line_text):
            mtype = m.group(1)
            mname = m.group(2)
            if not mname or len(mname) <= 1 or mname in _JAVA_KEYWORDS:
                continue
            if mtype in _BAD_TYPES:
                continue
            pos = line_starts[lineno - 1] + m.start()
            owner = find_scope(pos, scopes)
            kind = "method" if owner else "function"
            mid = nid(kind, rel, f"{mname}_{lineno}")
            nodes.append((mid, kind, mname, rel, lineno, None))
            edges.append((owner or fid, mid, "contains"))
            # Find method body braces for call extraction
            abs_pos = line_starts[lineno - 1] + m.end()
            brace_open = text.find('{', abs_pos)
            if brace_open != -1 and (brace_open - abs_pos) < 200:
                method_scopes.append((mid, brace_open, brace_end(text, brace_open)))

    # Call extraction — scan each method body for callee names
    for mid, body_start, body_end in method_scopes:
        if body_end <= body_start:
            continue
        body = text[body_start + 1:body_end]
        seen: set[str] = set()
        for cm in _JAVA_CALL_RE.finditer(body):
            callee = cm.group(1)
            if callee and len(callee) > 1 and callee not in _JAVA_KEYWORDS and callee not in seen:
                if callee[0].islower():  # skip constructors (PascalCase)
                    seen.add(callee)
                    edges.append((mid, callee, "calls"))

    # Notable annotations
    annotations = set()
    for m in _JAVA_ANNOTATION_RE.finditer(text):
        annotations.add(m.group(1))
    notable = annotations & {
        'Service', 'Repository', 'Controller', 'RestController',
        'Component', 'Configuration', 'Entity', 'Mapper',
        'SpringBootApplication', 'Audited',
    }
    if notable:
        aid = nid("annotation", rel, ",".join(sorted(notable)))
        nodes.append((aid, "annotation", ",".join(sorted(notable)), rel, None, None))


def _parse_kotlin(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _KT_IMPORT_RE.finditer(text):
        edges.append((fid, m.group(1).strip(), "imports"))

    scopes = []
    for m in _KT_CLASS_RE.finditer(text):
        decl_type, name = m.group(1).strip(), m.group(2)
        kind = "interface" if decl_type == "interface" else "class"
        if "enum" in decl_type:
            kind = "enum"
        line = text[:m.start()].count('\n') + 1
        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))
        open_pos = text.find('{', m.end())
        if open_pos != -1:
            scopes.append((node_id, open_pos, brace_end(text, open_pos)))

    for m in _KT_FUN_RE.finditer(text):
        fname = m.group(1)
        if fname and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            owner = find_scope(m.start(), scopes)
            kind = "method" if owner else "function"
            func_id = nid(kind, rel, f"{fname}_{line}")
            nodes.append((func_id, kind, fname, rel, line, None))
            edges.append((owner or fid, func_id, "contains"))


def _parse_scala(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for m in _SCALA_IMPORT_RE.finditer(text):
        edges.append((fid, m.group(1).strip(), "imports"))

    scopes = []
    for m in _SCALA_CLASS_RE.finditer(text):
        decl_type, name = m.group(1), m.group(2)
        kind = "interface" if decl_type == "trait" else "class"
        line = text[:m.start()].count('\n') + 1
        node_id = nid(kind, rel, name)
        nodes.append((node_id, kind, name, rel, line, None))
        edges.append((fid, node_id, "contains"))
        open_pos = text.find('{', m.end())
        if open_pos != -1:
            scopes.append((node_id, open_pos, brace_end(text, open_pos)))

    for m in _SCALA_DEF_RE.finditer(text):
        fname = m.group(1)
        if fname and len(fname) > 1:
            line = text[:m.start()].count('\n') + 1
            owner = find_scope(m.start(), scopes)
            kind = "method" if owner else "function"
            func_id = nid(kind, rel, f"{fname}_{line}")
            nodes.append((func_id, kind, fname, rel, line, None))
            edges.append((owner or fid, func_id, "contains"))


# ---------------------------------------------------------------------------
# Entry point — dispatches by extension
# ---------------------------------------------------------------------------

@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    ext = path.suffix.lower()
    if ext == ".java":
        _parse_java(path, rel, nodes, edges)
    elif ext == ".kt":
        _parse_kotlin(path, rel, nodes, edges)
    elif ext == ".scala":
        _parse_scala(path, rel, nodes, edges)
