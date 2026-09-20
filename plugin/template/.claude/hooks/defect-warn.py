#!/usr/bin/env python3
"""defect-warn: PreToolUse hook that warns before an unreviewed commit.

The `defect` detector in capture-signals.py finds a fix commit landing on a file
a recent non-fix commit touched. That is only knowable after the fact, so a hook
cannot detect a defect. What it can do is fire at the last moment before one
becomes likely: a commit of source edits that no review or verify skill ever saw.

This is a proxy, deliberately. It warns about the step that was skipped, not
about the defect that may follow.

Three markers under .coograph/, all keyed by session id:
  defect-edited-<sid>    a source file was edited this session
  defect-reviewed-<sid>  a coograph review or verify skill ran this session
  defect-warned-<sid>    the warning has already been shown

Never blocks - exits 1 so the warning surfaces without stopping the commit, and
at most once per session.
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

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
REVIEW_SKILLS = re.compile(r"coograph[-:]?(review|verify)", re.IGNORECASE)
GIT_COMMIT_RE = re.compile(r"\bgit\b[^\n]*\bcommit\b")
SOURCE_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".svelte", ".vue",
    ".py", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".swift",
    ".dart", ".css", ".scss", ".sql", ".json",
}


def _marker(cwd: Path, kind: str, sid: str) -> Path:
    return cwd / ".coograph" / f"defect-{kind}-{sid}"


def _touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        pass


def _is_source(raw: str) -> bool:
    """Docs and spec work are not what the defect rule is about."""
    path = Path(raw)
    if "openspec/" in path.as_posix() or path.name.lower().endswith(".md"):
        return False
    return path.suffix.lower() in SOURCE_SUFFIXES


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if should_skip(payload, __file__):
        return 0

    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = Path(payload.get("cwd") or ".")
    sid = str(payload.get("session_id") or "unknown")

    if tool in EDIT_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if raw and _is_source(str(raw)):
            _touch(_marker(cwd, "edited", sid))
        return 0

    if tool == "Skill":
        name = str(tool_input.get("skill") or "")
        if REVIEW_SKILLS.search(name):
            _touch(_marker(cwd, "reviewed", sid))
        return 0

    if tool != "Bash":
        return 0

    if not GIT_COMMIT_RE.search(str(tool_input.get("command") or "")):
        return 0

    if not _marker(cwd, "edited", sid).exists():
        return 0
    if _marker(cwd, "reviewed", sid).exists():
        return 0
    if _marker(cwd, "warned", sid).exists():
        return 0

    print(
        "[defect-warn] committing source edits that no review saw this session. "
        "Run /coograph-review or /coograph-verify before declaring this done.",
        file=sys.stderr,
    )
    _touch(_marker(cwd, "warned", sid))
    _emit_signal(payload, cwd, sid)
    return 1


def _emit_signal(payload: dict, cwd: Path, sid: str) -> None:
    """Record the warning for Retro. Never affects the hook's own behavior."""
    if signals is None:
        return
    try:
        signals.emit(cwd, signals.make_record(
            tool="claude-code",
            session_id=sid,
            kind="violation",
            rule="defect",
            detector="defect",
            confidence="deterministic",
            evidence={"count": 1, "days": 0, "files": [], "fix": "hook", "origin": "hook"},
            origin="hook",
        ))
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
