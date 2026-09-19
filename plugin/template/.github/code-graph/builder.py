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
from typing import Generator

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


def _walk(root: Path, extensions: frozenset[str]) -> Generator[Path, None, None]:
    """Walk the repo yielding source files matching the given extensions."""
    for dp, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in _IGNORE_DIRS and not d.startswith(".")
        ]
        for f in files:
            p = Path(dp) / f
            if _ext_for(p) in extensions:
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


def _is_npm_import(imp: str, aliases: list[tuple[str, str]]) -> bool:
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
    for prefix, _ in aliases:
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


def _load_path_aliases(root: Path) -> list[tuple[str, str]]:
    """Load path aliases from tsconfig.json / jsconfig.json.

    Returns list of (prefix, replacement_dir) tuples.
    E.g. tsconfig paths {"@/*": ["./src/*"]} -> [("@/", "src/")]
    """
    aliases: list[tuple[str, str]] = []
    for name in ("tsconfig.json", "jsconfig.json"):
        cfg_path = root / name
        if not cfg_path.exists():
            continue
        try:
            # Strip comments (tsconfig allows them) while preserving
            # quoted strings that contain /*, //, etc. (e.g. "@/*": ["./src/*"])
            text = cfg_path.read_text(encoding="utf-8", errors="ignore")
            text = re.sub(
                r'"(?:[^"\\]|\\.)*"|//.*?$|/\*.*?\*/',
                lambda m: m.group() if m.group().startswith('"') else '',
                text, flags=re.MULTILINE | re.DOTALL,
            )
            cfg = json.loads(text)
        except (json.JSONDecodeError, OSError):
            continue

        base_url = cfg.get("compilerOptions", {}).get("baseUrl", ".")
        paths = cfg.get("compilerOptions", {}).get("paths", {})

        for pattern, targets in paths.items():
            if not targets or not pattern.endswith("/*"):
                continue
            prefix = pattern[:-1]  # "@/*" -> "@/"
            target = targets[0]    # take first mapping
            if target.endswith("/*"):
                target = target[:-1]  # "./src/*" -> "./src/"
            # Resolve relative to baseUrl
            resolved = str(Path(base_url) / target).replace("\\", "/")
            # Normalize: strip leading ./
            if resolved.startswith("./"):
                resolved = resolved[2:]
            if not resolved.endswith("/"):
                resolved += "/"
            aliases.append((prefix, resolved))
            log.info("Path alias: %s -> %s", prefix, resolved)
        break  # only read first found config

    return aliases


# ---------------------------------------------------------------------------
# File dependency resolution
# ---------------------------------------------------------------------------

# Extensions to try when resolving TS/JS imports (import './foo' -> foo.ts, foo.tsx, etc.)
_JS_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".less", ".json")


def _resolve_file_deps(conn: sqlite3.Connection, root: Path) -> None:
    """Resolve import strings to file->file depends_on edges.

    Handles:
      - TS/JS path aliases from tsconfig.json (@/app/foo -> src/app/foo)
      - TS/JS module resolution (try .ts, .tsx, /index.ts, etc.)
      - Java qualified class names and wildcards
      - Stem-based fallback for other languages
    """
    aliases = _load_path_aliases(root)

    file_nodes: dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute("SELECT file, id FROM nodes WHERE kind='file'")
    }

    # Normalized path -> fid index (forward slashes, lowercase for matching)
    by_path: dict[str, str] = {}
    for rel, fid in file_nodes.items():
        norm = rel.replace("\\", "/")
        by_path[norm] = fid
        # Also index without extension for extensionless imports
        for ext in _JS_RESOLVE_EXTS:
            if norm.endswith(ext):
                by_path[norm[:-len(ext)]] = fid
                break

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
        target_fid = None

        # Skip npm/external package imports
        if _is_npm_import(imp_str, aliases):
            continue

        # -- TS/JS path alias resolution --
        resolved_imp = imp_str
        for prefix, replacement in aliases:
            if imp_str.startswith(prefix):
                resolved_imp = replacement + imp_str[len(prefix):]
                break

        # -- TS/JS relative import resolution --
        if resolved_imp.startswith("."):
            src_rel = fid_to_rel.get(src_id, "")
            if src_rel:
                src_dir = str(Path(src_rel).parent).replace("\\", "/")
                # Resolve relative path
                candidate = os.path.normpath(src_dir + "/" + resolved_imp).replace("\\", "/")
                target_fid = _try_js_resolve(candidate, by_path)
        elif not resolved_imp.startswith("."):
            # Absolute alias-resolved path or other
            norm = resolved_imp.replace("\\", "/")
            target_fid = _try_js_resolve(norm, by_path)

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


def _link_calls(conn: sqlite3.Connection) -> None:
    """Resolve raw callee-name 'calls' edges to function/method node IDs.

    Parsers emit (fn_nid, callee_name_string, 'calls') edges.
    This step resolves the name strings to actual node IDs where possible.
    Same-file matches are preferred; unresolvable edges are deleted.
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

    inserts: list[tuple[str, str, str]] = []
    deletions: list[tuple[str, str, str]] = []

    for src_id, callee_name in list(conn.execute(
        "SELECT src, dst FROM edges WHERE kind='calls'"
    )):
        deletions.append((src_id, callee_name, 'calls'))
        candidates = by_name.get(callee_name, [])
        if not candidates:
            continue
        # Prefer same-file match, then any match
        file_of_src = src_file.get(src_id, "")
        same = [(f, n) for f, n in candidates if f == file_of_src]
        target_nid = (same or candidates)[0][1]
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

    with _timed("parse files"):
        for path in _walk(root, extensions):
            rel = str(path.relative_to(root)).replace("\\", "/")
            ext = _ext_for(path)
            parser = parsers.get(ext)
            if parser:
                parser(path, rel, all_nodes, all_edges)
                all_hashes.append((rel, _sha1_file(path)))
                file_count += 1
    log.info("Parsed %d files (%d nodes, %d edges)", file_count, len(all_nodes), len(all_edges))

    with _timed("write nodes/edges"):
        conn.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?)", all_nodes)
        conn.executemany("INSERT OR IGNORE INTO edges VALUES (?,?,?)", all_edges)
        conn.executemany("INSERT OR REPLACE INTO file_hashes VALUES (?,?)", all_hashes)

    with _timed("link tests"):
        _link_tests(conn)

    with _timed("resolve file deps"):
        _resolve_file_deps(conn, root)

    with _timed("link inheritance"):
        _link_inheritance(conn)

    with _timed("link calls"):
        _link_calls(conn)

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
    _resolve_file_deps(conn, root)
    _link_inheritance(conn)
    _link_calls(conn)

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
