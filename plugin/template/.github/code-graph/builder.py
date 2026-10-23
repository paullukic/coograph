"""Standalone code graph builder.

Parses a repository into a SQLite graph using stack-aware parsers.
Each language/framework has its own parser module in ``parsers/``.

At build time the builder:
  1. Detects the project's tech stack (package.json, go.mod, pom.xml, etc.)
  2. Loads only the parsers relevant to that stack
  3. Parses files through the matching parser
  4. Links tests, resolves file dependencies, and resolves inheritance

No external dependencies required beyond Python 3.10+ stdlib.
Output: .code-graph/graph.db

Supported stacks: Python, React/Next.js, Angular, Vue, Svelte,
    Java/Kotlin/Scala, C#/F# (.NET), Go, Rust, PHP/Laravel,
    Ruby/Rails, Swift, Dart/Flutter, CSS/SCSS/LESS.
    TODO: Add more support.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable

log = logging.getLogger("code-graph.builder")

# Ensure parsers package is importable (sibling directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parsers import detect_stack, get_parsers, nid, is_test  # noqa: E402


@contextmanager
def _timed(label: str):
    """Context manager that logs elapsed time for a phase."""
    t0 = time.perf_counter()
    yield
    log.info("%s completed in %.2fs", label, time.perf_counter() - t0)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,   -- file | function | method | class
    name       TEXT NOT NULL,
    file       TEXT NOT NULL,
    start_line INTEGER,
    end_line   INTEGER
);
CREATE TABLE IF NOT EXISTS edges (
    src  TEXT NOT NULL,
    dst  TEXT NOT NULL,
    kind TEXT NOT NULL          -- imports | contains | calls | tests_for
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_edges    ON edges(src, dst, kind);
CREATE INDEX       IF NOT EXISTS idx_edge_dst ON edges(dst);
CREATE INDEX       IF NOT EXISTS idx_node_file ON nodes(file);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS file_hashes (
    file TEXT PRIMARY KEY,
    sha1 TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IGNORE_DIRS = frozenset({
    "node_modules", ".git", ".venv", "venv", "env",
    "__pycache__", "target", "dist", "build", ".gradle",
    ".idea", ".vscode", "coverage", ".code-graph",
    ".next", ".nuxt", "out", ".turbo", ".pytest_cache",
    # PHP/Laravel
    "vendor", "bootstrap/cache",
    # Ruby/Rails
    "tmp", "log",
    # Misc cache / generated
    "Pods", "DerivedData", ".bundle", ".cache",
})

_TEST_MARKERS = ("test", "spec", "__tests__", "_test", "_spec")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ext_for(path: Path) -> str:
    """Return the parser key for a file. Composite suffixes (e.g. .blade.php) win
    over plain suffixes so dedicated parsers can target them."""
    name = path.name.lower()
    if name.endswith(".blade.php"):
        return ".blade.php"
    return path.suffix.lower()


_MINIFIABLE_EXTS = frozenset({".js", ".mjs", ".cjs"})
_MINIFIED_AVG_LINE = 300   # chars per line in the first 64 KB
_MINIFIED_SAMPLE = 64 * 1024


def _is_minified(path: Path) -> bool:
    """A bundled/minified script: `.min.` in the name, or very long lines.

    Committed build output (`main-es2015.<hash>.js`, Gatsby `public/`) holds
    thousands of mangled functions that drown the real code in the graph.
    """
    if path.suffix.lower() not in _MINIFIABLE_EXTS:
        return False
    if ".min." in path.name.lower():
        return True
    try:
        with path.open("rb") as fh:
            head = fh.read(_MINIFIED_SAMPLE)
    except OSError:
        return False
    if len(head) < 2048:
        return False
    return len(head) / (head.count(b"\n") + 1) > _MINIFIED_AVG_LINE


def _walk(root: Path, extensions: frozenset[str],
          skipped: list[str] | None = None) -> Generator[Path, None, None]:
    """Walk the repo yielding source files matching the given extensions.

    Minified scripts are left out; their paths go to `skipped` when given.
    """
    for dp, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in _IGNORE_DIRS and not d.startswith(".")
        ]
        for f in files:
            p = Path(dp) / f
            if _ext_for(p) in extensions:
                if _is_minified(p):
                    if skipped is not None:
                        skipped.append(str(p))
                    continue
                yield p


def _sha1_file(path: Path) -> str:
    """SHA-1 content hash for change detection."""
    h = hashlib.sha1(usedforsecurity=False)
    h.update(path.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Test association
# ---------------------------------------------------------------------------


def _link_tests(conn: sqlite3.Connection) -> None:
    """Add tests_for edges: test_file -> source_file it imports/references."""
    file_map: dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute("SELECT file, id FROM nodes WHERE kind='file'")
    }
    by_stem: dict[str, list[tuple[str, str]]] = {}
    for rel, fid in file_map.items():
        by_stem.setdefault(Path(rel).stem, []).append((rel, fid))

    inserts: list[tuple[str, str, str]] = []

    for rel, fid in file_map.items():
        if not is_test(rel):
            continue
        for (imp,) in conn.execute(
            "SELECT dst FROM edges WHERE src=? AND kind='imports'", (fid,)
        ):
            imp_parts = re.split(r"[./\\]", imp)
            imp_stem = imp_parts[-1] if imp_parts else imp
            for known_rel, known_id in by_stem.get(imp_stem, []):
                if known_id != fid:
                    inserts.append((fid, known_id, "tests_for"))
                    break

    conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", inserts)


# ---------------------------------------------------------------------------
# Path alias loading (tsconfig.json / jsconfig.json)
# ---------------------------------------------------------------------------

# Well-known npm scopes / packages that should never resolve to local files
_NPM_PREFIXES = frozenset({
    "react", "next", "vue", "nuxt", "svelte", "@angular", "@tanstack",
    "@emotion", "@mui", "@chakra-ui", "@radix-ui", "@hookform", "@lukemorales",
    "tailwindcss", "yup", "zod", "axios", "lodash", "date-fns", "dayjs",
    "react-hook-form", "react-toastify", "react-dom", "react-router",
    "framer-motion", "classnames", "clsx", "uuid", "sharp", "prisma",
})


def _is_npm_import(imp: str, alias_keys: Iterable[str]) -> bool:
    """Return True if the import looks like an npm package (not local)."""
    # Java/Kotlin/Scala qualified names use dots, not slashes — never npm
    if re.match(r'^[a-z][a-z0-9]*\.', imp) and '/' not in imp:
        return False
    # PHP / .NET / PSR-4 namespaces: PascalCase dotted segments — never npm
    if '.' in imp and '/' not in imp and imp[:1].isupper():
        return False
    if imp.endswith(".*"):
        return False
    if imp.startswith(".") or imp.startswith("/"):
        return False
    # Check if it matches a known path alias first — those are local
    for prefix in alias_keys:
        if imp.startswith(prefix):
            return False
    # Scoped package: @scope/name
    if imp.startswith("@"):
        scope = imp.split("/")[0]
        if scope in _NPM_PREFIXES:
            return True
        # Generic scoped packages (e.g. @some-org/lib)
        # Must have @scope/name format to be npm — bare "@" alone is not
        if "/" in imp and len(scope) > 1:
            return True
        return False
    # Bare specifier — check first segment
    first = imp.split("/")[0]
    if first in _NPM_PREFIXES:
        return True
    # PascalCase bare identifier (e.g. PHP `Foo::class` ref) — treat as local class
    if "/" not in imp and "." not in imp and imp[:1].isupper():
        return False
    # Heuristic: no path separators and no file extension -> likely npm
    if "/" not in imp and not any(imp.endswith(e) for e in (".ts", ".tsx", ".js", ".jsx", ".css", ".scss")):
        return True
    return False


_TSCONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
_EXTENDS_DEPTH = 5
# A JSON string (kept), a comment (dropped) or a trailing comma (dropped):
# tsconfig is JSONC, and `json.loads` rejects both.
_JSONC_RE = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*.*?\*/|,(?=\s*[}\]])', re.DOTALL)


def _read_jsonc(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        data = json.loads(_JSONC_RE.sub(
            lambda m: m.group() if m.group().startswith('"') else "", text))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _tsconfig_options(cfg_path: Path, depth: int = 0,
                      seen: frozenset = frozenset()) -> tuple[dict, Path | None, Path | None]:
    """(paths, folder of the config declaring them, absolute baseUrl) for one
    config, after its relative `extends` chain. A child's `paths` / `baseUrl`
    override the parent's; package `extends` (`expo/tsconfig.base`) are skipped.
    """
    if depth > _EXTENDS_DEPTH or cfg_path in seen:
        return {}, None, None
    cfg = _read_jsonc(cfg_path)
    if cfg is None:
        return {}, None, None
    paths: dict = {}
    paths_dir: Path | None = None
    base_url: Path | None = None
    parents = cfg.get("extends")
    for parent in parents if isinstance(parents, list) else [parents]:
        if not isinstance(parent, str) or not parent.startswith("."):
            continue
        p = (cfg_path.parent / parent).resolve()
        if not p.is_file() and p.with_name(p.name + ".json").is_file():
            p = p.with_name(p.name + ".json")
        pp, pdir, pbase = _tsconfig_options(p, depth + 1, seen | {cfg_path})
        if pdir is not None:
            paths, paths_dir = pp, pdir
        if pbase is not None:
            base_url = pbase
    opts = cfg.get("compilerOptions")
    if isinstance(opts, dict):
        if isinstance(opts.get("paths"), dict):
            paths, paths_dir = opts["paths"], cfg_path.parent
        if isinstance(opts.get("baseUrl"), str):
            base_url = (cfg_path.parent / opts["baseUrl"]).resolve()
    return paths, paths_dir, base_url


class _TsConfig:
    """One folder's effective aliases and baseUrl, as root-relative paths.

    `aliases` holds (text before the key's `*`, text after it or None for an
    exact key, target templates joined to their anchor), longest prefix first,
    which is the key TypeScript picks. A target's `*` takes what the key's `*`
    matched; a target without `*` is used as is.
    """

    def __init__(self, root: Path, cfg_path: Path) -> None:
        paths, paths_dir, base_url = _tsconfig_options(cfg_path.resolve())
        root = root.resolve()
        anchor = base_url or paths_dir
        self.base_url = self._rel(root, base_url) if base_url else None
        self.aliases: list[tuple[str, str | None, list[str]]] = []
        if anchor is not None:
            anchor_rel = self._rel(root, anchor)
            for key, targets in paths.items():
                if not isinstance(targets, list) or key.count("*") > 1:
                    continue
                pre, star, post = key.partition("*")
                outs = [anchor_rel + "/" + t for t in targets
                        if isinstance(t, str) and t.count("*") <= 1]
                if outs:
                    self.aliases.append((pre, post if star else None, outs))
        self.aliases.sort(key=lambda a: -len(a[0]))
        # Keys mark a specifier as local, never a package; a bare `*` key
        # would mark every import, so it does not count here.
        self.prefixes = [a[0] for a in self.aliases if a[0]]

    def match(self, spec: str) -> tuple[list[str], str] | None:
        """(targets, what `*` matched) for the longest key matching `spec`."""
        for pre, post, targets in self.aliases:
            if post is None:
                if spec == pre:
                    return targets, ""
            elif (spec.startswith(pre) and spec.endswith(post)
                  and len(spec) >= len(pre) + len(post)):
                return targets, spec[len(pre):len(spec) - len(post)]
        return None

    @staticmethod
    def _rel(root: Path, p: Path) -> str:
        try:
            return os.path.relpath(os.path.normpath(p), root).replace("\\", "/")
        except ValueError:  # another drive on Windows: matches no file
            return str(p).replace("\\", "/")


class _JsResolver:
    """Resolves a JS/TS specifier the way the importing file's nearest
    tsconfig.json / jsconfig.json says to, cached per folder."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._by_dir: dict[str, _TsConfig | None] = {}

    def config_for(self, file_rel: str) -> _TsConfig | None:
        if self.root is None:
            return None
        d = os.path.dirname(file_rel.replace("\\", "/"))
        visited: list[str] = []
        found: _TsConfig | None = None
        while True:
            if d in self._by_dir:
                found = self._by_dir[d]
                break
            visited.append(d)
            cfg = next((self.root / d / n for n in _TSCONFIG_NAMES
                        if (self.root / d / n).is_file()), None)
            if cfg is not None:
                found = _TsConfig(self.root, cfg)
                break
            if not d:
                break
            d = os.path.dirname(d)
        for v in visited:
            self._by_dir[v] = found
        return found

    def resolve(self, spec: str, file_rel: str,
                by_path: dict[str, str]) -> tuple[str | None, bool]:
        """(target, is_package) for `spec` imported from `file_rel`.

        Order: relative path; for a JS/TS importer, the longest matching alias
        (each target in turn) and then `baseUrl` (only when a file is there);
        a package; a root-relative path. Other languages never read tsconfig:
        a Python `import config` must not land on `config.ts`.
        """
        if spec.startswith("."):
            # "." for a root-level file: "" + "/x" would read as an absolute path
            src_dir = os.path.dirname(file_rel.replace("\\", "/")) or "."
            return _try_js_resolve(os.path.normpath(src_dir + "/" + spec).replace("\\", "/"),
                                   by_path), False
        cfg = None
        if _lang_family(file_rel) == ".js" and not spec.startswith("/"):
            cfg = self.config_for(file_rel)
        if cfg is not None:
            found = cfg.match(spec)
            if found is not None:
                targets, rest = found
                for t in targets:
                    hit = _try_js_resolve(
                        os.path.normpath(t.replace("*", rest)).replace("\\", "/"), by_path)
                    if hit is not None:
                        return hit, False
            if cfg.base_url is not None:
                hit = _try_js_resolve(
                    os.path.normpath(cfg.base_url + "/" + spec).replace("\\", "/"), by_path)
                if hit is not None:
                    return hit, False
        if _is_npm_import(spec, cfg.prefixes if cfg else ()):
            return None, True
        return _try_js_resolve(spec.replace("\\", "/"), by_path), False


# ---------------------------------------------------------------------------
# File dependency resolution
# ---------------------------------------------------------------------------

# Extensions to try when resolving TS/JS imports (import './foo' -> foo.ts, foo.tsx, etc.)
_JS_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".svelte", ".vue",
                    ".css", ".scss", ".less", ".json")
_JS_INDEX_EXTS = _JS_RESOLVE_EXTS + (".mjs", ".cjs")


def _js_path_index(files) -> dict[str, str]:
    """Normalised path, and the same path without its extension, -> path.

    One index for `depends_on` and `calls`, so both resolve a specifier to the
    same file. `lib/a.ts` beside `lib/a.js`: `./lib/a` is `a.ts`, the
    extension `tsc` tries first.
    """
    by_path: dict[str, str] = {}
    rank: dict[str, int] = {}
    for rel in files:
        norm = rel.replace("\\", "/")
        by_path[norm] = norm
    for norm in list(by_path):
        for i, ext in enumerate(_JS_INDEX_EXTS):
            if norm.endswith(ext):
                key = norm[:-len(ext)]
                if key not in rank and key in by_path:
                    break  # a real extensionless file wins
                if i < rank.get(key, len(_JS_INDEX_EXTS)):
                    by_path[key], rank[key] = norm, i
                break
    return by_path


def _resolve_file_deps(conn: sqlite3.Connection, root: Path,
                       resolver: "_JsResolver | None" = None) -> None:
    """Resolve import strings to file->file depends_on edges.

    Handles:
      - TS/JS path aliases and baseUrl from the importing file's nearest
        tsconfig.json / jsconfig.json (@/app/foo -> src/app/foo)
      - TS/JS module resolution (try .ts, .tsx, /index.ts, etc.)
      - Java qualified class names and wildcards
      - Stem-based fallback for other languages
    """
    resolver = resolver or _JsResolver(root)

    file_nodes: dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute("SELECT file, id FROM nodes WHERE kind='file'")
    }

    # Path index shared with _link_calls; values are mapped to file ids here
    fid_by_norm = {rel.replace("\\", "/"): fid for rel, fid in file_nodes.items()}
    by_path: dict[str, str] = {
        key: fid_by_norm[norm] for key, norm in _js_path_index(file_nodes).items()
    }

    by_stem: dict[str, list[tuple[str, str]]] = {}
    for rel, fid in file_nodes.items():
        by_stem.setdefault(Path(rel).stem, []).append((rel, fid))

    # Source file -> its relative path (for resolving relative imports)
    fid_to_rel: dict[str, str] = {fid: rel for rel, fid in file_nodes.items()}

    # Java package-path index
    java_qualified: dict[str, str] = {}
    for rel, fid in file_nodes.items():
        if not rel.endswith(".java"):
            continue
        parts = Path(rel).parts
        java_marker = None
        for i, p in enumerate(parts):
            if p == "java" and i > 0 and parts[i - 1] in ("main", "test"):
                java_marker = i + 1
                break
        if java_marker and java_marker < len(parts):
            pkg_parts = list(parts[java_marker:-1])
            class_name = Path(rel).stem
            qualified = ".".join(pkg_parts + [class_name])
            java_qualified[qualified] = fid

    inserts: list[tuple[str, str, str]] = []
    for src_id, imp_str in conn.execute(
        "SELECT src, dst FROM edges WHERE kind='imports'"
    ):
        # -- TS/JS: relative, the importing file's tsconfig aliases and
        # baseUrl, root-relative; npm/external packages are skipped --
        src_rel = fid_to_rel.get(src_id, "")
        if imp_str.startswith(".") and not src_rel:
            target_fid = None
        else:
            target_fid, is_package = resolver.resolve(imp_str, src_rel, by_path)
            if is_package:
                continue

        # -- Java exact qualified match --
        if not target_fid:
            target_fid = java_qualified.get(imp_str)

        # -- Java static import --
        if not target_fid and "." in imp_str:
            parent = imp_str.rsplit(".", 1)[0]
            target_fid = java_qualified.get(parent)

        # -- Java wildcard --
        if not target_fid and imp_str.endswith(".*"):
            pkg_prefix = imp_str[:-2] + "."
            for qn, fid in java_qualified.items():
                if qn.startswith(pkg_prefix) and fid != src_id:
                    inserts.append((src_id, fid, "depends_on"))
            continue

        # -- Stem-based fallback --
        if not target_fid:
            parts = re.split(r"[./\\]", imp_str)
            stem = parts[-1] if parts else imp_str
            if stem and len(stem) >= 2:
                candidates = by_stem.get(stem, [])
                if candidates and len(candidates) <= 20:
                    imp_path = "/".join(parts)
                    best = None
                    for known_rel, known_id in candidates:
                        if known_id == src_id:
                            continue
                        if imp_path in known_rel.replace("\\", "/"):
                            best = known_id
                            break
                    if not best:
                        for known_rel, known_id in candidates:
                            if known_id != src_id:
                                best = known_id
                                break
                    target_fid = best

        if target_fid and target_fid != src_id:
            inserts.append((src_id, target_fid, "depends_on"))

    conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", inserts)


def _try_js_resolve(candidate: str, by_path: dict[str, str]) -> str | None:
    """Try TS/JS module resolution strategies for a candidate path.

    Tries: exact, with extensions, /index, /index with extensions.
    """
    # Exact match (already has extension, or extensionless match)
    if candidate in by_path:
        return by_path[candidate]

    # Try adding extensions
    for ext in _JS_RESOLVE_EXTS:
        if candidate + ext in by_path:
            return by_path[candidate + ext]

    # Try /index
    idx = candidate.rstrip("/") + "/index"
    if idx in by_path:
        return by_path[idx]
    for ext in _JS_RESOLVE_EXTS:
        if idx + ext in by_path:
            return by_path[idx + ext]

    return None


# ---------------------------------------------------------------------------
# Inheritance resolution
# ---------------------------------------------------------------------------


def _link_inheritance(conn: sqlite3.Connection) -> None:
    """Resolve inherits/implements edges: class names -> file-level edges."""
    class_index: dict[str, list[tuple[str, str]]] = {}
    for nid_val, name, file in conn.execute(
        "SELECT id, name, file FROM nodes WHERE kind IN ('class','interface','enum')"
    ):
        class_index.setdefault(name, []).append((nid_val, file))

    file_to_fid: dict[str, str] = {}
    for fid, file in conn.execute("SELECT id, file FROM nodes WHERE kind='file'"):
        file_to_fid[file] = fid

    inserts: list[tuple[str, str, str]] = []

    for src_id, target_name, kind in conn.execute(
        "SELECT src, dst, kind FROM edges WHERE kind IN ('inherits', 'implements')"
    ):
        candidates = class_index.get(target_name, [])
        if not candidates:
            continue

        src_row = conn.execute("SELECT file FROM nodes WHERE id=?", (src_id,)).fetchone()
        if not src_row:
            continue
        src_file = src_row[0]
        src_fid = file_to_fid.get(src_file)

        src_service = src_file.split("/")[0] if "/" in src_file else ""
        best_fid = None
        for target_nid, target_file in candidates:
            if target_file == src_file:
                continue
            target_fid = file_to_fid.get(target_file)
            if not target_fid:
                continue
            target_service = target_file.split("/")[0] if "/" in target_file else ""
            best_fid = target_fid
            if target_service == src_service:
                break

        if best_fid and src_fid and src_fid != best_fid:
            inserts.append((src_fid, best_fid, kind))

    conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", inserts)


# ---------------------------------------------------------------------------
# Calls resolution
# ---------------------------------------------------------------------------


# Method names too generic to link on name alone: on an object call
# (`session.commit()`) they are almost always a library method.
_COMMON_CALL_NAMES = frozenset({
    "get", "set", "create", "filter", "add", "update", "delete", "remove",
    "first", "all", "one", "query", "commit", "rollback", "close", "open",
    "run", "send", "save", "load", "read", "write", "append", "extend", "pop",
    "items", "keys", "values", "join", "split", "strip", "format", "replace",
    "copy", "clear", "count", "index", "find", "execute", "flush", "refresh",
    "start", "stop", "call", "apply", "parse", "dumps", "loads", "info",
    "debug", "warning", "error", "exception", "encode", "decode", "lower",
    "upper", "startswith", "endswith", "json", "post", "put", "patch",
    # JS / Kotlin
    "map", "forEach", "then", "catch", "finally", "push", "slice", "splice",
    "includes", "reduce", "some", "every", "toString", "trim", "concat",
    "sort", "resolve", "reject", "log", "warn", "has", "entries", "setState",
    "addEventListener", "removeEventListener", "querySelector", "emit", "on",
    "off", "subscribe", "dispatch", "next", "setValue", "getValue", "let",
    "also", "invoke", "launch", "collect", "observe",
    # Android SDK / React Navigation methods a project often shadows
    "select", "getString", "getInt", "getLong", "getBoolean", "putString",
    "putInt", "putBoolean", "edit", "show", "dismiss", "setText", "getText",
    "setVisibility", "findViewById", "startActivity", "finish", "notify",
    "setOnClickListener", "postValue", "setAdapter", "navigate", "goBack",
})


_JS_FAMILY = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts",
                        ".cts", ".vue", ".svelte"})


def _norm_ident(name: str) -> str:
    return name.replace("_", "").replace("-", "").lower()


def _lang_family(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in (".py", ".pyi"):
        return ".py"
    return ".js" if ext in _JS_FAMILY else ext


def _shared_prefix(a: str, b: str) -> int:
    """Number of leading path segments two files share."""
    n = 0
    for x, y in zip(a.replace("\\", "/").split("/"), b.replace("\\", "/").split("/")):
        if x != y:
            break
        n += 1
    return n


def _closest(candidates: list[tuple[str, str]], file_of_src: str) -> str:
    """Candidate whose file shares the longest leading path with the caller.

    In a multi-repo workspace that is the caller's own repo. Ties keep the
    first candidate, as before.
    """
    return max(candidates, key=lambda c: _shared_prefix(c[0], file_of_src))[1]


def _resolve_qualified(chain: list[str], candidates: list[tuple[str, str]],
                       file_of_src: str, class_of: dict[str, str]) -> str | None:
    """Pick the target of `a.b.name()` among same-named candidates, or None.

    Only candidates in the caller's language count. One whose file stem or
    class matches the last object part (`iap_service`, or `user_preferences`
    for `crud_user_preferences.py` / `CRUDUserPreferences`) wins; a candidate
    in the caller's own file matches only with an earlier-part hint. Ties go to
    the one whose path also holds the earlier parts (`crud`), then to the
    exact match, then to the shortest name, then to the closest file. With no
    match, the only candidate
    links unless its name is in `_COMMON_CALL_NAMES`.
    """
    name = chain[-1]
    qualifier = chain[-2]
    family = _lang_family(file_of_src)
    candidates = [c for c in candidates if _lang_family(c[0]) == family]
    if not candidates:
        return None

    q = _norm_ident(qualifier)
    hints = {_norm_ident(p) for p in chain[:-2] if len(p) >= 3} - {"self", "cls"}
    scored = []
    for file, node_id in candidates:
        stem = Path(file).stem
        sn, cn = _norm_ident(stem), _norm_ident(class_of.get(node_id, ""))
        if stem == qualifier or (cn and cn == q):
            match, extra = 2, 0
        elif len(q) >= 3 and sn.endswith(q):
            match, extra = 1, len(sn) - len(q)
        elif len(q) >= 3 and cn and cn.endswith(q):
            match, extra = 1, len(cn) - len(q)
        else:
            continue
        segments = {_norm_ident(s) for s in file.replace("\\", "/").split("/")[:-1]}
        hits = sum(1 for h in hints if h in segments or sn.startswith(h))
        if file == file_of_src and not hits:
            # `session.close()` inside async_session.py is a field of another
            # type; a file reaches itself through `self`/`this`, or through a
            # full path like `crud.business_ai_result.x()` (hits > 0).
            continue
        # `extra`: `crud_fcm.py` is a closer match for `fcm` than `crud_business_fcm.py`
        scored.append(((hits, match, -extra, _shared_prefix(file, file_of_src)), node_id))
    if scored:
        return max(scored, key=lambda s: s[0])[1]
    if len(candidates) == 1 and name not in _COMMON_CALL_NAMES:
        return candidates[0][1]
    return None


def _resolve_js_import(spec: str, name: str, file_of_src: str,
                       by_path: dict[str, str], resolver: _JsResolver,
                       by_name: dict[str, list[tuple[str, str]]],
                       default_of: dict[str, str]) -> str | None:
    """Target of a call to `name` imported from `spec` in `file_of_src`, or None.

    The specifier resolves like `_resolve_file_deps` does it (relative paths,
    the importing file's tsconfig aliases and baseUrl, extensions, index
    files). The target is the function or method called `name` in that file;
    for a barrel (`index.*`) re-export, the closest one under the barrel's
    folder. `default:<local>` is a default import: the target file's
    default-exported name comes first, the local name second. Package
    imports resolve to nothing.
    """
    target, _ = resolver.resolve(spec, file_of_src, by_path)
    if target is None:
        return None
    if name.startswith("default:"):
        local = name[len("default:"):]
        names = [n for n in (default_of.get(target), local) if n]
    else:
        names = [name]
    for n in dict.fromkeys(names):
        candidates = by_name.get(n, [])
        same = [c for c in candidates if c[0] == target]
        if same:
            return same[0][1]
        if Path(target).stem == "index":
            folder = str(Path(target).parent).replace("\\", "/") + "/"
            family = _lang_family(target)
            under = [c for c in candidates
                     if c[0].startswith(folder) and _lang_family(c[0]) == family]
            if under:
                return _closest(under, target)
    return None


def _link_calls(conn: sqlite3.Connection, root: Path | None = None,
                resolver: _JsResolver | None = None) -> None:
    """Resolve raw callee-name 'calls' edges to function/method node IDs.

    Parsers emit (fn_nid, callee_name_string, 'calls') edges.
    This step resolves the name strings to actual node IDs where possible:
    - `js:<specifier>#<name>`: a JS/TS imported call, via `_resolve_js_import`;
    - `jsl:<name>`: a JS/TS local call, same file only;
    - `a.b.name`: a module or object call, via `_resolve_qualified`;
    - bare `name`: same file first, then the closest file in the same language.
    Unresolvable edges are deleted.

    Only *unresolved* rows are considered: a row whose `dst` is already a node ID
    was resolved by an earlier run. Re-processing those would delete them, because
    a node ID never matches a function name — which is how an incremental update
    used to wipe the whole call graph. `build()` is unaffected either way; it
    starts from an empty edges table, so every row it sees is unresolved.
    """
    # Index: name -> list of (file, nid) for all callable nodes
    by_name: dict[str, list[tuple[str, str]]] = {}
    for fn_id, name, file in conn.execute(
        "SELECT id, name, file FROM nodes WHERE kind IN ('function', 'method')"
    ):
        by_name.setdefault(name, []).append((file, fn_id))

    # Source function -> its file (for same-file preference)
    src_file: dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT id, file FROM nodes WHERE kind IN ('function', 'method')"
        )
    }

    # Method -> name of the class that contains it (for qualified calls)
    class_of: dict[str, str] = {
        method_id: cls_name
        for method_id, cls_name in conn.execute(
            "SELECT e.dst, c.name FROM edges e JOIN nodes c ON c.id = e.src "
            "WHERE e.kind='contains' AND c.kind != 'file'"
        )
    }

    # Path index for JS/TS import specifiers, shared with _resolve_file_deps
    by_path = _js_path_index(
        rel for (rel,) in conn.execute("SELECT file FROM nodes WHERE kind='file'"))
    resolver = resolver or _JsResolver(root)
    # JS/TS file -> the name its default export binds (`export default bar`)
    default_of: dict[str, str] = {
        file.replace("\\", "/"): name
        for file, name in conn.execute(
            "SELECT n.file, e.dst FROM edges e JOIN nodes n ON n.id = e.src "
            "WHERE e.kind='exports_default'"
        )
    }

    inserts: list[tuple[str, str, str]] = []
    deletions: list[tuple[str, str, str]] = []

    for src_id, callee_name in list(conn.execute(
        "SELECT src, dst FROM edges "
        "WHERE kind='calls' AND dst NOT IN (SELECT id FROM nodes)"
    )):
        deletions.append((src_id, callee_name, 'calls'))
        file_of_src = src_file.get(src_id, "")
        if callee_name.startswith("js:"):
            spec, _, name = callee_name[3:].rpartition("#")
            target_nid = _resolve_js_import(spec, name, file_of_src, by_path, resolver,
                                            by_name, default_of) if spec and name else None
            if target_nid is None:
                continue
        elif callee_name.startswith("jsl:"):
            same = [n for f, n in by_name.get(callee_name[4:], []) if f == file_of_src]
            if not same:
                continue
            target_nid = same[0]
        elif "." in callee_name:
            chain = callee_name.split(".")
            candidates = by_name.get(chain[-1], [])
            if not candidates or not all(chain):
                continue
            target_nid = _resolve_qualified(chain, candidates, file_of_src, class_of)
            if target_nid is None:
                continue
        else:
            family = _lang_family(file_of_src)
            candidates = [c for c in by_name.get(callee_name, [])
                          if _lang_family(c[0]) == family]
            if not candidates:
                continue
            # Prefer same-file match, then the closest file
            same = [(f, n) for f, n in candidates if f == file_of_src]
            target_nid = same[0][1] if same else _closest(candidates, file_of_src)
        if target_nid != src_id:
            inserts.append((src_id, target_nid, 'calls'))

    conn.executemany(
        "DELETE FROM edges WHERE src=? AND dst=? AND kind=?", deletions
    )
    conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", inserts)


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------


def _find_dependents(conn: sqlite3.Connection, rels: list[str]) -> list[str]:
    """Find files that depend on any of the given files (1-hop reverse)."""
    seed_ids: set[str] = set()
    for rel in rels:
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (rel,)
        ).fetchone()
        if row:
            seed_ids.add(row[0])

    if not seed_ids:
        return []

    dependent_rels: set[str] = set()
    for sid in seed_ids:
        for (src_id,) in conn.execute(
            "SELECT src FROM edges WHERE dst=? AND kind='depends_on'", (sid,)
        ):
            row = conn.execute(
                "SELECT file FROM nodes WHERE id=?", (src_id,)
            ).fetchone()
            if row and row[0] not in rels:
                dependent_rels.add(row[0])

    return list(dependent_rels)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build(root: Path) -> Path:
    """Full rebuild: parse every source file in root into .code-graph/graph.db."""
    build_start = time.perf_counter()
    log.info("Starting full graph build for %s", root)

    # Detect stack and get parsers
    stacks = detect_stack(root)
    parsers = get_parsers(stacks)
    extensions = frozenset(parsers.keys())
    log.info("Detected stacks: %s (%d extensions)", ", ".join(sorted(stacks)), len(extensions))
    print(f"Detected stacks: {', '.join(sorted(stacks))}")

    db_dir = root / ".code-graph"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / "graph.db"

    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    # Full rebuild: clear existing data
    conn.execute("DELETE FROM nodes")
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM file_hashes")
    conn.commit()

    all_nodes: list[tuple] = []
    all_edges: list[tuple] = []
    all_hashes: list[tuple] = []
    file_count = 0

    skipped: list[str] = []
    with _timed("parse files"):
        for path in _walk(root, extensions, skipped):
            rel = str(path.relative_to(root)).replace("\\", "/")
            ext = _ext_for(path)
            parser = parsers.get(ext)
            if parser:
                parser(path, rel, all_nodes, all_edges)
                all_hashes.append((rel, _sha1_file(path)))
                file_count += 1
    log.info("Parsed %d files (%d nodes, %d edges)", file_count, len(all_nodes), len(all_edges))
    if skipped:
        log.info("Skipped %d minified file(s)", len(skipped))

    with _timed("write nodes/edges"):
        conn.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?)", all_nodes)
        conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", all_edges)
        conn.executemany("INSERT OR REPLACE INTO file_hashes VALUES (?,?)", all_hashes)

    with _timed("link tests"):
        _link_tests(conn)

    resolver = _JsResolver(root)  # one tsconfig cache for both phases
    with _timed("resolve file deps"):
        _resolve_file_deps(conn, root, resolver)

    with _timed("link inheritance"):
        _link_inheritance(conn)

    with _timed("link calls"):
        _link_calls(conn, root, resolver)

    conn.execute("INSERT OR REPLACE INTO meta VALUES ('root',?)", (str(root),))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('files_parsed',?)", (str(file_count),))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('stacks',?)", (",".join(sorted(stacks)),))
    conn.commit()
    conn.close()

    elapsed = time.perf_counter() - build_start
    log.info("Graph built: %d files -> %s (%.2fs total)", file_count, db_path, elapsed)
    print(f"Graph built: {file_count} files -> {db_path} ({elapsed:.2f}s)")
    return db_path


def update(root: Path) -> tuple[Path, list[str]]:
    """Incremental update: re-parse changed files + their 1-hop dependents.

    Uses SHA-1 content hashes to detect changes (not timestamps).
    Removes nodes/edges for deleted files automatically.
    Also re-parses files that import from any changed file so that
    cross-file edges (calls, tests_for) stay accurate.

    Returns (db_path, list_of_updated_relative_paths).
    """
    update_start = time.perf_counter()
    db_path = root / ".code-graph" / "graph.db"
    if not db_path.exists():
        return build(root), []

    # Detect stack and get parsers
    stacks = detect_stack(root)
    parsers = get_parsers(stacks)
    extensions = frozenset(parsers.keys())

    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    stored: dict[str, str] = {
        row[0]: row[1] for row in conn.execute("SELECT file, sha1 FROM file_hashes")
    }

    current_rels: set[str] = set()
    changed: list[str] = []

    for path in _walk(root, extensions):
        rel = str(path.relative_to(root)).replace("\\", "/")
        current_rels.add(rel)
        if stored.get(rel) != _sha1_file(path):
            changed.append(rel)

    deleted = set(stored) - current_rels

    if not changed and not deleted:
        conn.close()
        print("Graph up to date — no changes detected.")
        return db_path, []

    # Expand: also re-parse files that import from changed/deleted files
    dependents = _find_dependents(conn, changed + list(deleted))
    dependents = [d for d in dependents if d in current_rels and d not in changed]

    to_reparse = changed + dependents

    # Remove old data for changed + deleted + dependent files
    for rel in (*to_reparse, *deleted):
        fid_rows = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (rel,)
        ).fetchall()
        for (fid,) in fid_rows:
            conn.execute("DELETE FROM edges WHERE src=? OR dst=?", (fid, fid))
        # Resolved edges out of the file's functions and classes too: node ids
        # are stable, so a re-parse would keep a call the new code no longer
        # makes (a renamed default export, a dropped import) next to the new one.
        conn.execute("DELETE FROM edges WHERE src IN (SELECT id FROM nodes WHERE file=?)", (rel,))
        conn.execute("DELETE FROM nodes WHERE file=?", (rel,))
        conn.execute("DELETE FROM file_hashes WHERE file=?", (rel,))

    all_nodes: list[tuple] = []
    all_edges: list[tuple] = []

    for rel in to_reparse:
        path = root / rel
        if not path.exists():
            continue
        ext = _ext_for(path)
        parser = parsers.get(ext)
        if parser:
            parser(path, rel, all_nodes, all_edges)
            conn.execute(
                "INSERT OR REPLACE INTO file_hashes VALUES (?,?)", (rel, _sha1_file(path))
            )

    conn.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?)", all_nodes)
    conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", all_edges)

    _link_tests(conn)
    resolver = _JsResolver(root)
    _resolve_file_deps(conn, root, resolver)
    _link_inheritance(conn)
    _link_calls(conn, root, resolver)

    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('files_parsed',?)",
        (str(len(current_rels)),),
    )
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('stacks',?)", (",".join(sorted(stacks)),))
    conn.commit()
    conn.close()

    elapsed = time.perf_counter() - update_start
    summary = f"updated {len(changed)}, dependents {len(dependents)}, deleted {len(deleted)}"
    log.info("Graph updated: %s (%.2fs)", summary, elapsed)
    print(f"Graph updated: {summary} -> {db_path} ({elapsed:.2f}s)")
    return db_path, changed
