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

sys.dont_write_bytecode = True  # keep __pycache__/ out of .claude/hooks/
try:
    from _coograph_guard import should_skip
except ImportError:  # guard not copied next to this hook: run unguarded
    def should_skip(payload: dict, hook_file: str) -> bool:
        return False
try:
    import _coograph_signals as signals
except ImportError:  # Retro store not copied next to this hook: warn only
    signals = None

BACKTICK_PATH_RE = re.compile(r"`([^`\s]+)`")
PATH_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt", ".rb", ".php",
    ".cs", ".swift", ".dart", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".md", ".sh",
    ".css", ".scss", ".sql",
}


def _strip_dot_slash(token: str) -> str:
    """Drop a leading './' (repeated if present). A leading '.' that names a
    dotfile directory stays: '.github/x' is '.github/x', not 'github/x'."""
    token = token.strip()
    while token.startswith("./"):
        token = token[2:]
    return token


def _extract_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input") or {}
    return tool_input.get("file_path") or tool_input.get("notebook_path")


def _looks_like_path(token: str) -> bool:
    token = _strip_dot_slash(token)
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
        token = _strip_dot_slash(match.group(1))
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

    if should_skip(payload, __file__):
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
    _emit_signal(payload, cwd, rel, slug)
    return 1


def _emit_signal(payload: dict, cwd: Path, rel: str, slug: str) -> None:
    """Record the warning for Retro. Never affects the hook's own behavior."""
    if signals is None:
        return
    try:
        signals.emit(cwd, signals.make_record(
            tool="claude-code",
            session_id=str(payload.get("session_id") or "unknown"),
            kind="violation",
            rule="scope",
            detector="scope-warning",
            confidence="deterministic",
            evidence={"path": signals.rel_path(cwd, rel), "openspec": slug[:120]},
            origin="hook",
        ))
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
