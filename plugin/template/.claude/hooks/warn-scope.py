#!/usr/bin/env python3
"""warn-scope: PreToolUse hook that warns on edits outside the active OpenSpec.

The active OpenSpec is the open change in openspec/changes/<slug>/ (not
archive) whose tasks.md was modified most recently (the change directory's
own mtime only when no open change has a tasks.md). Paths referenced in
backticks in that tasks.md are in scope; a token ending in '/' covers every
file under it. Warns if the current edit target isn't covered.

Silent for: no active OpenSpec, a tasks.md with no paths, targets outside the
project root, and anything under openspec/. Warns once per path per session
(marker .coograph/markers/scope-warned-<sid>); a repeat records a
`suppressed` decision and no violation.

Never blocks: the warning goes to the model as additionalContext (and to the
user as systemMessage) with exit 0, without stopping the tool call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__/ out of .claude/hooks/
try:
    from _coograph_guard import should_skip, warn_model
except ImportError:  # guard not copied next to this hook: run unguarded
    def should_skip(payload: dict, hook_file: str) -> bool:
        return False

    def warn_model(payload: dict, text: str) -> None:
        # Same JSON as _coograph_guard.warn_model: stderr with exit 1 never
        # reaches the model, additionalContext does.
        try:
            print(json.dumps({"systemMessage": text, "hookSpecificOutput": {
                "hookEventName": str(payload.get("hook_event_name") or "PreToolUse"),
                "additionalContext": text}}))
        except Exception:
            pass
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
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MARKER_DIR = "markers"
_SAFE_SID = re.compile(r"[^A-Za-z0-9_-]")


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


def _tasks_mtime(d: Path) -> float:
    try:
        return (d / "tasks.md").stat().st_mtime
    except OSError:
        return -1.0


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

    # The change being worked on is the one whose tasks.md moved last. A
    # directory's own mtime changes whenever any file is added inside it
    # (notes/, a new spec), which picks the wrong change.
    with_tasks = [d for d in candidates if _tasks_mtime(d) >= 0]
    if with_tasks:
        active = max(with_tasks, key=_tasks_mtime)
    else:
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


def _covered(rel: str, target_name: str, scope: set[str]) -> bool:
    for scoped in scope:
        if rel == scoped or rel.endswith("/" + scoped) or scoped.endswith("/" + rel):
            return True
        if scoped.endswith("/") and rel.startswith(scoped):
            return True  # a directory token covers everything under it
        if Path(scoped).name == target_name:
            return True
    return False


def _already_warned(cwd: Path, sid: str, rel: str) -> bool:
    """True when this path was warned about earlier in the session; else
    remember it. An unwritable .coograph/ degrades to warning every time."""
    marker = cwd / ".coograph" / MARKER_DIR / f"scope-warned-{sid}"
    key = hashlib.sha1(rel.encode("utf-8", "replace")).hexdigest()[:12]
    try:
        seen = set(marker.read_text(encoding="utf-8").split())
    except OSError:
        seen = set()
    if key in seen:
        return True
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        with marker.open("a", encoding="utf-8") as fh:
            fh.write(key + "\n")
    except OSError:
        pass
    return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") not in EDIT_TOOLS:
        return 0

    if should_skip(payload, __file__):
        return 0

    raw = _extract_path(payload)
    if not raw:
        return 0

    cwd = Path(payload.get("cwd") or ".")
    # The project root, as the other hooks resolve it: a session whose cwd is a
    # subdirectory still edits files of the whole project.
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    target = Path(raw)
    if not target.is_absolute():
        target = cwd / target
    try:
        rel = target.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return 0  # outside the project: no OpenSpec of this project scopes it

    if rel == "openspec" or rel.startswith("openspec/"):
        return 0  # writing or updating OpenSpec files is never out of scope

    active = _active_openspec(root)
    if active is None:
        return 0

    slug, scope = active
    if not scope:
        return 0

    if _covered(rel, target.name, scope):
        return 0

    sid = _SAFE_SID.sub("", str(payload.get("session_id") or "unknown"))[:64] or "unknown"
    if _already_warned(root, sid, rel):
        _decide(payload, root, rel, "suppressed")
        return 0

    warn_model(payload, (
        f"[warn-scope] editing {rel} but active OpenSpec "
        f"'{slug}' does not reference this path in tasks.md. "
        f"Confirm intent or update tasks.md."
    ))
    _emit_signal(payload, root, rel, slug)
    return 0


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
    _decide(payload, cwd, rel, "warned")


def _decide(payload: dict, cwd: Path, rel: str, action: str) -> None:
    if signals is None:
        return
    try:
        signals.emit_decision(cwd, payload, "scope", action, __file__, rel)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
