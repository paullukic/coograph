"""Standalone code-graph MCP server.

Exposes code graph tools to AI coding assistants via the Model Context Protocol.
Ships inside the project at .github/code-graph/ — no external pip install needed.

Usage:
    python server.py              # start MCP server over stdio
    python server.py --build      # build/rebuild graph then exit

Requirements:
    pip install "mcp>=1.0.0,<2"
    — or with uv (auto-installs) —
    uv run --with "mcp>=1.0.0,<2" server.py
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

# Configure logging early so builder output is visible during --build/--update.
# MCP-server mode (stdio) reconfigures to file below — writing to stderr will
# fill Windows' ~4KB pipe buffer (the host doesn't drain it) and block forever.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Resolve repo root via git (works from any cwd after initialization)
# ---------------------------------------------------------------------------

try:
    _git = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
        stdin=subprocess.DEVNULL, timeout=5,
    )
    ROOT = Path(_git.stdout.strip()) if _git.returncode == 0 else Path.cwd()
except (subprocess.TimeoutExpired, OSError):
    ROOT = Path.cwd()
DB_PATH = ROOT / ".code-graph" / "graph.db"

# Ensure builder.py (sibling file) is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# Handle --build / --update / --visualize BEFORE importing mcp
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--build" in sys.argv:
        from builder import build  # type: ignore[import]
        db = build(ROOT)
        print(f"Done. Run 'python {__file__}' to start the MCP server.")
        sys.exit(0)
    if "--update" in sys.argv:
        from builder import update  # type: ignore[import]
        db, changed = update(ROOT)
        if changed:
            print(f"Updated {len(changed)} file(s).")
        sys.exit(0)
    if "--visualize" in sys.argv:
        from visualize import generate_html  # type: ignore[import]
        out = generate_html(DB_PATH, ROOT / ".code-graph" / "graph.html")
        print(f"Visualization: {out}")
        sys.exit(0)

# ---------------------------------------------------------------------------
# MCP server (only reached when running as server, not --build/--update)
# ---------------------------------------------------------------------------

# Redirect logging to a file. The MCP host pipes stdio for protocol traffic;
# stderr is unread and its OS pipe buffer fills (~4KB on Windows), blocking
# the next log call indefinitely and hanging the server.
_log_path = ROOT / ".code-graph" / "server.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)
_root_logger = logging.getLogger()
for _h in list(_root_logger.handlers):
    _root_logger.removeHandler(_h)
_file_handler = logging.FileHandler(_log_path, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S"
))
_root_logger.addHandler(_file_handler)
_root_logger.setLevel(logging.INFO)

import sqlite3

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    # Also raised by MCP SDK 2.x, which renamed mcp.server.fastmcp. Surface the
    # real error instead of assuming the package is absent.
    sys.exit(
        f"Cannot import mcp.server.fastmcp: {e}\n"
        "  Install: pip install 'mcp>=1.0.0,<2'\n"
        "  Or run:  uv run --with-requirements .github/code-graph/requirements.txt "
        ".github/code-graph/server.py"
    )

mcp = FastMCP("code-graph")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            "Graph not built yet. Run: python .github/code-graph/server.py --build"
        )
    return sqlite3.connect(DB_PATH)


def _impact_radius_internal(files: list[str]) -> tuple[list[str], int, dict[str, int]]:
    """BFS through reverse import edges.

    Returns (sorted affected_files, blast_radius, distances) where distances
    maps each affected file to its BFS depth from the nearest seed file
    (seeds are 0, direct dependents 1, and so on).
    """
    conn = _conn()

    seeds: set[str] = set()
    for f in files:
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (f,)
        ).fetchone()
        if row:
            seeds.add(row[0])

    visited: set[str] = set(seeds)
    queue: list[tuple[str, int]] = [(s, 0) for s in seeds]
    affected: set[str] = set(files)
    distances: dict[str, int] = {f: 0 for f in files}

    while queue:
        node_id, depth = queue.pop(0)
        for (dep_id,) in conn.execute(
            "SELECT src FROM edges WHERE dst=? AND kind='depends_on'", (node_id,)
        ):
            if dep_id not in visited:
                visited.add(dep_id)
                queue.append((dep_id, depth + 1))
                row = conn.execute(
                    "SELECT file FROM nodes WHERE id=?", (dep_id,)
                ).fetchone()
                if row:
                    affected.add(row[0])
                    distances.setdefault(row[0], depth + 1)

    conn.close()
    return sorted(affected), len(affected), distances


def _approx_tokens(rel_path: str) -> int:
    """Approximate token count for a repo-relative file: size_bytes // 4.

    Same convention as the coograph bench harness. Missing files count as 0.
    """
    try:
        return (ROOT / rel_path).stat().st_size // 4
    except OSError:
        return 0


# Words that carry no symbol information in a task description. Kept small on
# purpose: a stopword list that grows starts eating real identifiers.
_TASK_STOPWORDS = frozenset("""
add fix the and for with from into that this then than but not out off new old
use using update change make made set get put run call called calls when what
why how where which while should would could must need needs want wants
bug bugs issue issues error errors feature support handle handling
code file files function method class test tests line lines
""".split())

_NON_IDENT = re.compile(r"[^A-Za-z0-9_]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Node kinds that represent a definition worth seeding from.
_DEF_KINDS = ("function", "method", "class", "interface", "enum")

# Ceilings. The point of this tool is to be the cheap first call, so every
# widening step is bounded and the caller is told which tool to use to go wider.
_MAX_SEEDS = 3
_MAX_FILES = 6
_FORWARD_DEPTH = 2


def _identifiers(task: str) -> list[str]:
    """Candidate symbol names in a task string, longest first.

    Splits on non-identifier characters, then again on camelCase and snake_case
    boundaries, keeping the whole identifier as well as its parts so that
    "OrderService.place_order()" yields place_order before order.
    """
    seen: dict[str, None] = {}
    for raw in _NON_IDENT.split(task):
        if not raw:
            continue
        parts = [raw]
        parts.extend(_CAMEL_BOUNDARY.sub(" ", raw).split())
        parts.extend(raw.split("_"))
        for part in parts:
            token = part.strip().lower()
            if len(token) >= 3 and token not in _TASK_STOPWORDS:
                seen.setdefault(token, None)
    # Longest first so a specific name outranks the generic word inside it.
    return sorted(seen, key=lambda t: (-len(t), t))


def _file_id(conn: sqlite3.Connection, file: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM nodes WHERE file=? AND kind='file'", (file,)
    ).fetchone()
    return row[0] if row else None


def _is_test_file(conn: sqlite3.Connection, file: str, file_id: str | None) -> bool:
    """True when this file tests something else.

    Prefers the graph: a tests_for edge has the test file as src. Falls back to
    the path for repositories whose parsers emit no tests_for edges.
    """
    if file_id is not None:
        row = conn.execute(
            "SELECT 1 FROM edges WHERE src=? AND kind='tests_for' LIMIT 1", (file_id,)
        ).fetchone()
        if row:
            return True
    lowered = "/" + file.replace("\\", "/").lower()
    if "/test/" in lowered or "/tests/" in lowered or "/__tests__/" in lowered:
        return True
    name = lowered.rsplit("/", 1)[-1]
    return name.startswith("test_") or ".test." in name or ".spec." in name


def _resolve_seeds(conn: sqlite3.Connection, task: str) -> tuple[list[str], str]:
    """Map a task description onto the files most likely to define it.

    Returns (files, reason). An empty file list always carries a reason, since
    a tool that silently returns nothing is indistinguishable from one that was
    never wired up.
    """
    identifiers = _identifiers(task)
    if not identifiers:
        return [], "no usable identifier in the task description"

    # (-len(identifier), tier, is_test, file) — deterministic for a given graph.
    # Identifier specificity outranks match tier: "SearchSuggest" matching a
    # file name must beat "search" prefix-matching a function, or a task about
    # a Svelte component resolves to whatever else shares its first six letters.
    candidates: list[tuple[int, int, int, str]] = []
    for ident in identifiers:
        rows = conn.execute(
            "SELECT DISTINCT file FROM nodes "
            f"WHERE kind IN ({','.join('?' * len(_DEF_KINDS))}) AND LOWER(name)=?",
            (*_DEF_KINDS, ident),
        ).fetchall()
        tier = 0
        if not rows:
            rows = conn.execute(
                "SELECT DISTINCT file FROM nodes "
                f"WHERE kind IN ({','.join('?' * len(_DEF_KINDS))}) "
                "AND LOWER(name) LIKE ? LIMIT 20",
                (*_DEF_KINDS, ident + "%"),
            ).fetchall()
            tier = 1
        if not rows:
            rows = conn.execute(
                "SELECT DISTINCT file FROM nodes WHERE kind='file' "
                "AND (LOWER(file) LIKE ? OR LOWER(file) LIKE ?) LIMIT 20",
                (ident + ".%", "%/" + ident + ".%"),
            ).fetchall()
            tier = 2
        for (file,) in rows:
            is_test = 1 if _is_test_file(conn, file, _file_id(conn, file)) else 0
            candidates.append((-len(ident), tier, is_test, file))

    if not candidates:
        return [], "no symbol or file in the task matched the graph"

    candidates.sort()
    # Strongest signal wins outright, in this order: the most specific
    # identifier in the task, then exact match over prefix over file name, then
    # a definition over a test. "service" exact-matches a pytest fixture in
    # tests/test_order_service.py, which would otherwise seed the walk from the
    # test and invert the whole result.
    best_ident, best_tier = candidates[0][0], candidates[0][1]
    candidates = [c for c in candidates if c[0] == best_ident and c[1] == best_tier]
    if any(c[2] == 0 for c in candidates):
        candidates = [c for c in candidates if c[2] == 0]

    seeds: list[str] = []
    for _, _, _, file in candidates:
        if file not in seeds:
            seeds.append(file)
        if len(seeds) >= _MAX_SEEDS:
            break

    # An exact symbol match is an answer. A prefix or a file-name match is a
    # guess, and a caller that cannot tell them apart will trust both equally.
    notes: list[str] = []
    if -best_ident < len(identifiers[0]):
        # The most specific thing named in the task is absent from the graph,
        # so this answer comes from a broader word in the same sentence. Often
        # it means the parser does not cover that file type at all.
        notes.append(
            f"{identifiers[0]!r} is not in the graph; matched on "
            f"{-best_ident}-character fallback"
        )
    if best_tier == 1:
        notes.append("name prefix, not an exact symbol")
    elif best_tier == 2:
        notes.append("file name, no symbol")
    return seeds, "; ".join(notes)


def _dependencies_of(
    files: list[str], max_depth: int = _FORWARD_DEPTH
) -> tuple[list[str], dict[str, int]]:
    """BFS forward through depends_on: what these files need.

    The mirror of _impact_radius_internal, which walks the same edges backwards
    to answer what would break. "Which files do I have to read" is mostly this
    direction; on the sample-app fixture, forward from order_service.py gives
    three files and backward gives ten, four of them tests.
    """
    conn = _conn()

    seed_ids: dict[str, str] = {}
    for f in files:
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (f,)
        ).fetchone()
        if row:
            seed_ids[row[0]] = f

    visited: set[str] = set(seed_ids)
    queue: list[tuple[str, int]] = [(nid, 0) for nid in seed_ids]
    found: dict[str, int] = {}

    while queue:
        node_id, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for (dep_id,) in conn.execute(
            "SELECT dst FROM edges WHERE src=? AND kind='depends_on'", (node_id,)
        ):
            if dep_id in visited:
                continue
            visited.add(dep_id)
            row = conn.execute(
                "SELECT file FROM nodes WHERE id=?", (dep_id,)
            ).fetchone()
            if row and row[0] not in files:
                found.setdefault(row[0], depth + 1)
            queue.append((dep_id, depth + 1))

    conn.close()
    return sorted(found, key=lambda f: (found[f], f)), found


def _risk_score_file(conn: sqlite3.Connection, file: str) -> float:
    """Compute risk score (0.0–1.0) for a single file."""
    risk = 0.0

    # Blast radius contribution (capped at 0.3)
    _, radius, _ = _impact_radius_internal([file])
    risk += min((radius - 1) * 0.05, 0.3)

    # Test gap (0.3 if no test covers this file)
    fid_row = conn.execute(
        "SELECT id FROM nodes WHERE file=? AND kind='file'", (file,)
    ).fetchone()
    has_test = False
    if fid_row:
        has_test = conn.execute(
            "SELECT 1 FROM edges WHERE dst=? AND kind='tests_for' LIMIT 1",
            (fid_row[0],),
        ).fetchone() is not None
    if not has_test:
        risk += 0.3

    # Fan-in: callers of functions in this file (capped at 0.2)
    caller_count = 0
    if fid_row:
        for (nid,) in conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind IN ('function','method')",
            (file,),
        ):
            caller_count += conn.execute(
                "SELECT COUNT(*) FROM edges WHERE dst=? AND kind='calls'", (nid,)
            ).fetchone()[0]
    risk += min(caller_count * 0.02, 0.2)

    return round(min(risk, 1.0), 3)


def _assemble_context(
    conn: sqlite3.Connection, seeds: list[str]
) -> tuple[list[str], dict[str, int]]:
    """Seeds, then what they depend on, then one tier of what depends on them.

    Ranked with the same order get_review_context uses — distance ascending,
    files missing on disk last, risk descending, path — and capped at
    _MAX_FILES. Returns (ranked, forward_distances) so the caller can tell an
    isolated seed from one with real edges.
    """
    forward, forward_distances = _dependencies_of(seeds)

    # Multi-project checkouts (app/ beside admin/) produce cross-tree edges that
    # are real but almost never what the task is about. Same tree first.
    seed_trees = {f.replace("\\", "/").split("/", 1)[0] for f in seeds}

    def _same_tree(file: str) -> int:
        return 0 if file.replace("\\", "/").split("/", 1)[0] in seed_trees else 1

    ranked: list[str] = list(seeds)
    seen = set(seeds)

    def _rank(files: list[str], distances: dict[str, int]) -> list[str]:
        scored = sorted(files, key=lambda f: (distances.get(f, 1 << 30), f))
        risks = {f: _risk_score_file(conn, f) for f in scored[:20]}
        tests = {f: _is_test_file(conn, f, _file_id(conn, f)) for f in scored}
        return sorted(scored, key=lambda f: (
            _same_tree(f),
            1 if tests[f] else 0,
            distances.get(f, 1 << 30),
            1 if _approx_tokens(f) == 0 else 0,
            -risks.get(f, 0.0),
            f,
        ))

    for f in _rank([f for f in forward if f not in seen], forward_distances):
        if len(ranked) >= _MAX_FILES:
            return ranked, forward_distances
        ranked.append(f)
        seen.add(f)

    if len(ranked) < _MAX_FILES:
        affected, _, back_distances = _impact_radius_internal(seeds)
        dependents = [
            f for f in affected
            if f not in seen and back_distances.get(f, 0) == 1
        ]
        for f in _rank(dependents, back_distances):
            if len(ranked) >= _MAX_FILES:
                break
            ranked.append(f)
            seen.add(f)

    return ranked, forward_distances


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def build_graph() -> str:
    """Full rebuild of the code graph.

    Parses every source file and rewrites .code-graph/graph.db from scratch.
    Use this after a large refactor, module rename, or when graph_stats looks wrong.
    For day-to-day changes, prefer update_graph() — it is much faster.
    """
    from builder import build  # type: ignore[import]
    db = build(ROOT)
    conn = _conn()
    nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()
    return f"Graph built at {db} — {nodes} nodes, {edges} edges."


@mcp.tool()
def update_graph() -> str:
    """Incremental update of the code graph.

    Re-parses only files that changed since the last build or update (SHA-1 hash comparison).
    Removes stale nodes/edges for deleted files automatically.
    Safe to call at any time — exits immediately if nothing changed.
    Call this mid-session whenever you suspect the architecture has shifted.
    """
    from builder import update  # type: ignore[import]
    db, changed = update(ROOT)
    if not changed:
        return "Graph is already up to date — no file changes detected."
    return f"Graph updated: {len(changed)} file(s) re-parsed → {db}"


@mcp.tool()
def graph_stats() -> dict:
    """Return statistics about the current code graph.

    Use this to confirm the graph is up to date before relying on other tools.
    """
    conn = _conn()
    result = {
        "nodes":    conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges":    conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "files":    conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='file'").fetchone()[0],
        "functions": conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind IN ('function','method')"
        ).fetchone()[0],
        "test_files": conn.execute(
            "SELECT COUNT(DISTINCT src) FROM edges WHERE kind='tests_for'"
        ).fetchone()[0],
        "db_path": str(DB_PATH),
    }
    conn.close()
    return result


@mcp.tool()
def detect_changes(base: str = "HEAD") -> dict:
    """Return files and graph nodes changed since base commit, with risk scores.

    Each affected node gets a risk score (0.0–1.0) based on:
      - blast_radius: how many files transitively depend on it
      - test_gap:     whether the file has a tests_for edge (0.3 if missing)
      - fan_in:       number of callers (capped contribution of 0.2)

    Examples:
        detect_changes()                  # changes since last commit
        detect_changes("origin/main")     # changes vs main branch
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base],
            capture_output=True, text=True, cwd=ROOT,
            stdin=subprocess.DEVNULL, timeout=5,
        )
        changed_files = [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, OSError):
        changed_files = []
    if not changed_files:
        return {"changed_files": [], "affected_nodes": [], "risk_score": 0.0,
                "message": "No changes detected."}

    conn = _conn()
    affected_nodes: list[dict] = []
    for f in changed_files:
        for row in conn.execute(
            "SELECT id, kind, name, start_line, end_line FROM nodes WHERE file=?", (f,)
        ):
            affected_nodes.append({
                "file": f, "id": row[0], "kind": row[1],
                "name": row[2], "start_line": row[3], "end_line": row[4],
            })

    file_risks = {f: _risk_score_file(conn, f) for f in changed_files}
    overall_risk = max(file_risks.values()) if file_risks else 0.0

    conn.close()
    return {
        "changed_files": changed_files,
        "affected_nodes": affected_nodes,
        "file_risks": file_risks,
        "risk_score": overall_risk,
    }


@mcp.tool()
def get_impact_radius(files: list[str]) -> dict:
    """Blast-radius analysis: which files are affected if any of files change?

    Traverses the import graph in reverse to find all dependents.
    Use this at review time to know the full surface area of a change.
    Each affected file's BFS distance from the nearest seed is reported in
    distances (seeds are 0, direct dependents 1, ...).
    """
    affected, radius, distances = _impact_radius_internal(files)
    return {
        "seed_files":    files,
        "affected_files": affected,
        "blast_radius":  radius,
        "distances":     distances,
    }


@mcp.tool()
def get_review_context(files: list[str], budget_tokens: int | None = None) -> dict:
    """Return a ranked, token-estimated file set for reviewing a change.

    files_to_read is ranked by relevance: the changed files first, then
    affected files by BFS distance (ascending) and risk score (descending),
    then related test files. Every entry carries an approximate token count
    (file bytes / 4) in approx_tokens; estimated_tokens is the total.

    Pass budget_tokens to cap the read list: the longest ranked prefix that
    fits is returned (changed files are always kept), truncated is set, and
    files_omitted lists what was cut so you can pull more explicitly.

    Call this FIRST at the start of any review — read files_to_read in order.
    """
    affected, radius, distances = _impact_radius_internal(files)

    conn = _conn()
    test_files: set[str] = set()
    for f in affected:
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (f,)
        ).fetchone()
        if row:
            for (tid,) in conn.execute(
                "SELECT src FROM edges WHERE dst=? AND kind='tests_for'", (row[0],)
            ):
                trow = conn.execute(
                    "SELECT file FROM nodes WHERE id=?", (tid,)
                ).fetchone()
                if trow:
                    test_files.add(trow[0])

    seeds = list(dict.fromkeys(files))
    seed_set = set(seeds)
    dependents = [f for f in affected if f not in seed_set]

    # Risk-score at most 50 dependents (perf guard); pick deterministically:
    # nearest first, then path. Unscored files rank as risk 0.0.
    score_order = sorted(dependents, key=lambda f: (distances.get(f, 1 << 30), f))
    risks = {f: _risk_score_file(conn, f) for f in score_order[:50]}
    conn.close()

    tokens: dict[str, int] = {}
    for f in seeds + dependents + sorted(test_files):
        if f not in tokens:
            tokens[f] = _approx_tokens(f)

    # Rank within the affected tier: distance asc, deleted-on-disk last,
    # risk desc, path asc.
    dependents.sort(key=lambda f: (
        distances.get(f, 1 << 30),
        1 if tokens[f] == 0 else 0,
        -risks.get(f, 0.0),
        f,
    ))
    listed = seed_set | set(dependents)
    tests_tail = sorted(t for t in test_files if t not in listed)
    ranked = seeds + dependents + tests_tail

    truncated = False
    files_omitted: list[str] = []
    if budget_tokens is not None:
        seed_cost = sum(tokens[f] for f in seeds)
        kept = list(seeds)
        used = seed_cost
        rest = ranked[len(seeds):]
        cut_idx = len(rest)
        for i, f in enumerate(rest):
            if used + tokens[f] > budget_tokens:
                cut_idx = i
                break
            kept.append(f)
            used += tokens[f]
        if cut_idx < len(rest):
            truncated = True
            files_omitted = rest[cut_idx:]
        if seed_cost > budget_tokens:
            truncated = True
        ranked = kept

    return {
        "changed_files":  files,
        "files_to_read":  ranked,
        "approx_tokens":  {f: tokens[f] for f in ranked},
        "estimated_tokens": sum(tokens[f] for f in ranked),
        "related_tests":  sorted(test_files),
        "total_files":    len(ranked),
        "blast_radius":   radius,
        "truncated":      truncated,
        "files_omitted":  files_omitted,
    }


@mcp.tool()
def query_graph(pattern: str, node_name: str) -> list[dict]:
    """Query the graph with a named pattern.

    Patterns:
        callers_of   — nodes that call node_name (function/method)
        callees_of   — functions/methods called by node_name
        tests_for    — test files that cover a given source file path
        imports_of   — what a given source file imports
        importers_of — files that import from the given source file
        file_summary — all nodes (classes, functions) in a file
    """
    conn = _conn()
    results: list[dict] = []

    if pattern == "callers_of":
        row = conn.execute("SELECT id FROM nodes WHERE name=?", (node_name,)).fetchone()
        if row:
            for name, kind, file in conn.execute(
                "SELECT n.name, n.kind, n.file "
                "FROM edges e JOIN nodes n ON n.id=e.src "
                "WHERE e.dst=? AND e.kind='calls'",
                (row[0],),
            ):
                results.append({"name": name, "kind": kind, "file": file})

    elif pattern == "callees_of":
        row = conn.execute("SELECT id FROM nodes WHERE name=?", (node_name,)).fetchone()
        if row:
            for name, kind, file in conn.execute(
                "SELECT n.name, n.kind, n.file "
                "FROM edges e JOIN nodes n ON n.id=e.dst "
                "WHERE e.src=? AND e.kind='calls'",
                (row[0],),
            ):
                results.append({"name": name, "kind": kind, "file": file})

    elif pattern == "tests_for":
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (node_name,)
        ).fetchone()
        if row:
            for (tid,) in conn.execute(
                "SELECT src FROM edges WHERE dst=? AND kind='tests_for'", (row[0],)
            ):
                trow = conn.execute(
                    "SELECT file FROM nodes WHERE id=?", (tid,)
                ).fetchone()
                if trow:
                    results.append({"file": trow[0]})

    elif pattern == "imports_of":
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (node_name,)
        ).fetchone()
        if row:
            for (dst,) in conn.execute(
                "SELECT dst FROM edges WHERE src=? AND kind='imports'", (row[0],)
            ):
                results.append({"import": dst})

    elif pattern == "importers_of":
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (node_name,)
        ).fetchone()
        if row:
            # imports edges keep the raw import string as dst; the resolved
            # file->file relation lives in depends_on edges.
            for (src_id,) in conn.execute(
                "SELECT src FROM edges WHERE dst=? AND kind='depends_on'", (row[0],)
            ):
                srow = conn.execute(
                    "SELECT file FROM nodes WHERE id=?", (src_id,)
                ).fetchone()
                if srow:
                    results.append({"file": srow[0]})

    elif pattern == "file_summary":
        for nid, kind, name, start, end in conn.execute(
            "SELECT id, kind, name, start_line, end_line FROM nodes "
            "WHERE file=? AND kind!='file'", (node_name,)
        ):
            results.append({
                "name": name, "kind": kind,
                "start_line": start, "end_line": end,
            })

    conn.close()
    return results


@mcp.tool()
def get_minimal_context(task: str = "") -> dict:
    """Ultra-compact entry point — call this FIRST before any other graph tool.

    Resolves the symbols named in `task` against the graph and returns
    files_to_read: the defining files, then what they depend on, then one tier
    of what depends on them, ranked and capped at 6. Also returns graph stats,
    the risk of the uncommitted changes, and which tool to reach for next.
    Keeps output under ~150 tokens, which is why there is no per-file token
    map — pass files_to_read to get_review_context for that and for more files.

    files_to_read is empty whenever the task names nothing the graph knows, or
    the graph holds no dependency edges for what it matched; files_reason says
    which. An empty list is a real answer, not a failure.

    Args:
        task: What you are doing (e.g. "add caching to OrderService.place_order()",
            "review PR #42", "debug login timeout").
    """
    conn = _conn()
    stats = {
        "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "files": conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='file'").fetchone()[0],
    }

    # Quick risk from uncommitted changes.
    # subprocess: stdin=DEVNULL + timeout so git can't block on stdin/pager.
    risk = "unknown"
    changed: list[str] = []
    try:
        git_result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=ROOT,
            stdin=subprocess.DEVNULL, timeout=5,
        )
        changed = [f for f in git_result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, OSError):
        pass

    if not changed:
        risk = "clean"
    elif stats["edges"] == 0:
        # No dep edges yet — radius BFS would just count seeds. Skip the work.
        risk = "low"
    else:
        total_radius = 0
        for f in changed[:20]:
            _, r, _ = _impact_radius_internal([f])
            total_radius += r
        if total_radius > 20:
            risk = "high"
        elif total_radius > 5:
            risk = "medium"
        else:
            risk = "low"

    # Resolve the task onto files while the connection is open.
    files_to_read: list[str] = []
    files_reason = "no task given"
    if task.strip():
        seeds, files_reason = _resolve_seeds(conn, task)
        if seeds:
            files_to_read, forward_distances = _assemble_context(conn, seeds)
            if len(files_to_read) == len(seeds) and not forward_distances:
                no_edges = ("matched the task but the graph holds no dependency "
                            "edges for those files")
                files_reason = (
                    f"{files_reason}; {no_edges}" if files_reason else no_edges
                )

    conn.close()

    # Suggest tools based on task keywords
    task_lower = task.lower()
    if any(w in task_lower for w in ("review", "pr", "merge", "diff")):
        suggestions = ["detect_changes", "get_review_context", "get_impact_radius"]
    elif any(w in task_lower for w in ("debug", "bug", "error", "fix")):
        suggestions = ["query_graph(callers_of)", "detect_changes", "get_impact_radius"]
    elif any(w in task_lower for w in ("refactor", "rename", "move")):
        suggestions = ["get_impact_radius", "query_graph(importers_of)", "query_graph(callers_of)"]
    else:
        suggestions = ["detect_changes", "graph_stats", "get_review_context"]

    return {
        "stats": stats,
        "uncommitted_risk": risk,
        "changed_file_count": len(changed),
        "files_to_read": files_to_read,
        "files_reason": files_reason,
        "next_tool_suggestions": suggestions,
    }


@mcp.tool()
def find_large_functions(min_lines: int = 50) -> list[dict]:
    """Find functions and methods exceeding a line-count threshold.

    Useful during review to spot complexity hotspots.
    Defaults to 50 lines.  Only reports nodes where end_line is known
    (Python files have exact ranges; other languages report start_line only).
    """
    conn = _conn()
    results = []
    for _, kind, name, file, start, end in conn.execute(
        "SELECT id, kind, name, file, start_line, end_line FROM nodes "
        "WHERE kind IN ('function','method') AND start_line IS NOT NULL "
        "AND end_line IS NOT NULL AND (end_line - start_line + 1) >= ?",
        (min_lines,),
    ):
        results.append({
            "name": name, "kind": kind, "file": file,
            "start_line": start, "end_line": end,
            "lines": end - start + 1,
        })
    conn.close()
    results.sort(key=lambda r: r["lines"], reverse=True)
    return results


@mcp.tool()
def visualize_graph() -> str:
    """Generate a standalone HTML visualization of the code graph.

    Creates .code-graph/graph.html — open it in a browser to explore
    the interactive force-directed graph with zoom, search, and filters.
    """
    from visualize import generate_html  # type: ignore[import]
    output = ROOT / ".code-graph" / "graph.html"
    generate_html(DB_PATH, output)
    return f"Visualization written to {output}"


# ---------------------------------------------------------------------------
# Entrypoint (server mode — CLI flags already handled above)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
