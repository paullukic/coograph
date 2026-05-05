#!/usr/bin/env python3
"""warn-scope: PreToolUse hook that warns on edits outside the active OpenSpec.

Finds the most-recently-modified OpenSpec in openspec/changes/<slug>/ (not
archive). Parses its tasks.md for file paths referenced in backticks, then
prints a warning to stderr if the current edit target isn't among them.

Never blocks - exits 1 so the warning surfaces to the user without stopping
the tool call. Silent when no active OpenSpec exists.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKTICK_PATH_RE = re.compile(r"`([^`\s]+)`")
PATH_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt", ".rb", ".php",
    ".cs", ".swift", ".dart", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".md", ".sh",
    ".css", ".scss", ".sql",
}


def _extract_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input") or {}
    return tool_input.get("file_path") or tool_input.get("notebook_path")


def _looks_like_path(token: str) -> bool:
    token = token.strip().lstrip("./")
    if not token or token.startswith(("http://", "https://", "-")):
        return False
    if "/" in token:
        return True
    suffix = Path(token).suffix.lower()
    return suffix in PATH_SUFFIXES


def _active_openspec(cwd: Path) -> tuple[str, set[str]] | None:
    changes_dir = cwd / "openspec" / "changes"
    if not changes_dir.exists():
        return None

    candidates = [
        d for d in changes_dir.iterdir()
        if d.is_dir() and d.name != "archive"
    ]
    if not candidates:
        return None

    active = max(candidates, key=lambda d: d.stat().st_mtime)
    tasks = active / "tasks.md"
    if not tasks.exists():
        return active.name, set()

    try:
        text = tasks.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return active.name, set()

    paths: set[str] = set()
    for match in BACKTICK_PATH_RE.finditer(text):
        token = match.group(1).strip().lstrip("./")
        if _looks_like_path(token):
            paths.add(token)
    return active.name, paths


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return 0

    raw = _extract_path(payload)
    if not raw:
        return 0

    cwd = Path(payload.get("cwd") or ".")
    target = Path(raw)
    try:
        rel = target.resolve().relative_to(cwd.resolve()).as_posix()
    except (ValueError, OSError):
        rel = target.as_posix()

    active = _active_openspec(cwd)
    if active is None:
        return 0

    slug, scope = active

    if rel.startswith(f"openspec/changes/{slug}"):
        return 0

    if not scope:
        return 0

    target_name = target.name
    for scoped in scope:
        if rel == scoped or rel.endswith("/" + scoped) or scoped.endswith("/" + rel):
            return 0
        if Path(scoped).name == target_name:
            return 0

    print(
        f"[warn-scope] editing {rel} but active OpenSpec "
        f"'{slug}' does not reference this path in tasks.md. "
        f"Confirm intent or update tasks.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
