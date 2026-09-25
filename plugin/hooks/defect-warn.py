#!/usr/bin/env python3
"""defect-warn: warns before committing source that no review saw.

The `defect` detector in capture-signals.py finds a fix commit landing on a file
a recent non-fix commit touched. That is only knowable after the fact, so a hook
cannot detect a defect. What it can do is fire at the last moment before one
becomes likely: a commit of source edits that no review ever saw.

This is a proxy, deliberately. It warns about the step that was skipped, not
about the defect that may follow.

Three ways a review is recognised, because coograph offers three ways to run
one: the `Skill` tool, a delegation to the reviewer or verifier agent, and the
`/coograph-review` slash command a human types (seen through UserPromptSubmit,
which is the only event that carries it - a typed command is a user message,
not a tool call).

This hook records decisions, never violations. `defect` already has a
transcript detector, and a hook-emitted copy would be counted alongside real
fix-commit findings by `summarize`, letting the hook's own warnings push its
rule toward `hook-block` with no defect ever observed. The detector measures
the rule; the decision record (warned / suppressed, with the tool_use_id) lets
capture-signals.py learn whether a review followed the warning.

Markers under .coograph/markers/, keyed by session id:
  defect-edited-<sid>    a source file was edited this session
  defect-reviewed-<sid>  a review ran this session
  defect-warned-<sid>    the warning has already been shown

Never blocks - exits 1 so the warning surfaces without stopping the commit, and
at most once per session. If `.coograph/` is unwritable the markers cannot be
written: the "edited" marker failing silences the hook, the "warned" marker
failing degrades it to once per commit.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__/ out of .claude/hooks/
try:
    from _coograph_guard import should_skip
except ImportError:  # guard not copied next to this hook: run unguarded
    def should_skip(payload: dict, hook_file: str) -> bool:
        return False
try:
    import _coograph_signals as signals  # shim in this directory -> .github/retro/
except ImportError:  # without the store the hook still warns, it just records nothing
    signals = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
DELEGATION_TOOLS = {"Task", "Agent"}
REVIEW_NAME_RE = re.compile(r"coograph[-:]?(ultra-)?(review|verif)", re.IGNORECASE)
REVIEW_PROMPT_RE = re.compile(r"/\s*coograph[-:]?(ultra-)?(review|verify)", re.IGNORECASE)
GIT_COMMIT_RE = re.compile(r"(^|[;&|]\s*)git\s+(-[^\s]+\s+)*commit\b")
SOURCE_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".svelte", ".vue",
    ".py", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".swift",
    ".dart", ".css", ".scss", ".sql",
}
MARKER_DIR = "markers"
MARKER_TTL_SECONDS = 7 * 86400


def _marker(cwd: Path, kind: str, sid: str) -> Path:
    return cwd / ".coograph" / MARKER_DIR / f"defect-{kind}-{sid}"


def _touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        _prune(path.parent)
    except OSError:
        pass


def _prune(directory: Path) -> None:
    """Markers are per-session and worthless once the session is gone."""
    cutoff = time.time() - MARKER_TTL_SECONDS
    try:
        for stale in directory.iterdir():
            if stale.is_file() and stale.stat().st_mtime < cutoff:
                stale.unlink(missing_ok=True)
    except OSError:
        pass


def _is_source(raw: str) -> bool:
    """Docs and spec work are not what the defect rule is about."""
    path = Path(raw)
    if "openspec/" in path.as_posix():
        return False
    return path.suffix.lower() in SOURCE_SUFFIXES


def _review_started(tool: str, tool_input: dict) -> bool:
    if tool == "Skill":
        # `skill` is what this Claude Code version sends, `skill_name` is what the
        # published reference documents; accept both rather than depend on which.
        name = str(tool_input.get("skill") or tool_input.get("skill_name") or "")
        return bool(REVIEW_NAME_RE.search(name))
    if tool in DELEGATION_TOOLS:
        name = str(tool_input.get("subagent_type") or tool_input.get("description") or "")
        return bool(REVIEW_NAME_RE.search(name))
    return False


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

    # A typed slash command never reaches a tool, so this is the only place a
    # human-driven review can be observed.
    if payload.get("hook_event_name") == "UserPromptSubmit" or (not tool and payload.get("prompt")):
        if REVIEW_PROMPT_RE.search(str(payload.get("prompt") or "")):
            _touch(_marker(cwd, "reviewed", sid))
        return 0

    if tool in EDIT_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if raw and _is_source(str(raw)):
            _touch(_marker(cwd, "edited", sid))
        return 0

    if _review_started(str(tool or ""), tool_input):
        _touch(_marker(cwd, "reviewed", sid))
        return 0

    if tool not in SHELL_TOOLS:
        return 0

    if not GIT_COMMIT_RE.search(str(tool_input.get("command") or "")):
        return 0

    if not _marker(cwd, "edited", sid).exists():
        return 0
    if _marker(cwd, "reviewed", sid).exists():
        return 0
    if _marker(cwd, "warned", sid).exists():
        _decide(cwd, payload, "suppressed")
        return 0

    print(
        "[defect-warn] committing source edits that no review saw this session. "
        "Run /coograph-review or /coograph-verify before declaring this done.",
        file=sys.stderr,
    )
    _touch(_marker(cwd, "warned", sid))
    _decide(cwd, payload, "warned")
    return 1


def _decide(cwd: Path, payload: dict, action: str) -> None:
    """Record the decision for Retro. Never affects the hook's own behavior."""
    if signals is None:
        return
    try:
        signals.emit_decision(cwd, payload, "defect", action, __file__)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
