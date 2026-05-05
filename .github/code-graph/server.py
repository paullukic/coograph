"""Standalone code-graph MCP server.

Exposes code graph tools to AI coding assistants via the Model Context Protocol.
Ships inside the project at .github/code-graph/ — no external pip install needed.

Usage:
    python server.py              # start MCP server over stdio
    python server.py --build      # build/rebuild graph then exit

Requirements:
    pip install "mcp>=1.0.0"
    — or with uv (auto-installs) —
    uv run --with "mcp>=1.0.0" server.py
"""

from __future__ import annotations

import logging
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
except ImportError:
    sys.exit(
        "mcp package not found.\n"
        "  Install: pip install 'mcp>=1.0.0'\n"
        "  Or run:  uv run --with 'mcp>=1.0.0' .github/code-graph/server.py"
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


def _impact_radius_internal(files: list[str]) -> tuple[list[str], int]:
    """BFS through reverse import edges. Returns (sorted affected_files, blast_radius)."""
    conn = _conn()

    seeds: set[str] = set()
    for f in files:
        row = conn.execute(
            "SELECT id FROM nodes WHERE file=? AND kind='file'", (f,)
        ).fetchone()
        if row:
            seeds.add(row[0])

    visited: set[str] = set(seeds)
    queue: list[str] = list(seeds)
    affected: set[str] = set(files)

    while queue:
        node_id = queue.pop(0)
        for (dep_id,) in conn.execute(
            "SELECT src FROM edges WHERE dst=? AND kind='depends_on'", (node_id,)
        ):
            if dep_id not in visited:
                visited.add(dep_id)
                queue.append(dep_id)
                row = conn.execute(
                    "SELECT file FROM nodes WHERE id=?", (dep_id,)
                ).fetchone()
                if row:
                    affected.add(row[0])

    conn.close()
    return sorted(affected), len(affected)


def _risk_score_file(conn: sqlite3.Connection, file: str) -> float:
    """Compute risk score (0.0–1.0) for a single file."""
    risk = 0.0

    # Blast radius contribution (capped at 0.3)
    _, radius = _impact_radius_internal([file])
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
    """
    affected, radius = _impact_radius_internal(files)
    return {
        "seed_files":    files,
        "affected_files": affected,
        "blast_radius":  radius,
    }


@mcp.tool()
def get_review_context(files: list[str]) -> dict:
    """Return the minimal, focused file set needed to review a change.

    Combines blast radius with related test files.
    Call this FIRST at the start of any review — use files_to_read
    to scope which files the reviewer should actually read.
    """
    affected, radius = _impact_radius_internal(files)

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
    conn.close()

    files_to_read = sorted(set(files) | set(affected))
    return {
        "changed_files":  files,
        "files_to_read":  files_to_read,
        "related_tests":  sorted(test_files),
        "total_files":    len(files_to_read),
        "blast_radius":   radius,
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
            for (src_id,) in conn.execute(
                "SELECT src FROM edges WHERE dst=? AND kind='imports'", (row[0],)
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

    Returns graph stats, overall risk of uncommitted changes, and suggested
    next tools based on task description. Keeps output under ~150 tokens.

    Args:
        task: What you are doing (e.g. "review PR #42", "debug login timeout").
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
            _, r = _impact_radius_internal([f])
            total_radius += r
        if total_radius > 20:
            risk = "high"
        elif total_radius > 5:
            risk = "medium"
        else:
            risk = "low"

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
