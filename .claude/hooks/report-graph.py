#!/usr/bin/env python3
"""report-graph: SessionStart hook that reports code-graph status.

Checks for .code-graph/graph.db. If present, prints node/edge counts, size,
and how long ago it was last updated. If absent but the project ships the
code-graph server, prints a hint to rebuild. Silent otherwise. Output is
injected into the session as additional context.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    cwd = Path(payload.get("cwd") or ".")
    db = cwd / ".code-graph" / "graph.db"
    server_dir = cwd / ".github" / "code-graph"

    if not db.exists():
        if server_dir.exists():
            print("[code-graph] graph.db missing - rebuild before querying:")
            print(
                "  uv run --with-requirements .github/code-graph/requirements.txt "
                ".github/code-graph/server.py --build"
            )
        return 0

    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        nodes = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges = cur.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        con.close()
    except sqlite3.Error as e:
        print(f"[code-graph] graph.db present but query failed: {e}")
        return 0

    stat = db.stat()
    age = _format_age(time.time() - stat.st_mtime)
    size_kb = stat.st_size // 1024
    print(
        f"[code-graph] {nodes} nodes, {edges} edges, {size_kb}KB, updated {age} ago"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
