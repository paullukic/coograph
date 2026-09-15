"""Shared guard for Coograph hooks: plugin gating + cross-copy dedupe.

The same hook script can be wired twice: by the Coograph Claude plugin
(its hooks.json passes --plugin) and by a project's own .claude/settings.json.
Hosts run every wired copy, and whether a host loads project settings at all
varies (Claude Code does; Cowork may not). should_skip() makes exactly one
copy act per event, whichever starts first, so hooks neither double-fire nor
go silent. The plugin copy also stays silent outside Coograph projects.

Not a hook itself; imported by the scripts next to it. Fails open: any error
here means "run the hook".
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Written by coograph-init into every initialized project (always-copy block).
# Unlike .github/copilot-instructions.md, nothing but Coograph creates it.
PROJECT_MARKER = Path(".github") / "skills" / "coograph-init" / "SKILL.md"

_USER = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
LOCK_ROOT = Path(tempfile.gettempdir()) / f"coograph-hooks-{_USER}"
LOCK_TTL_SECONDS = 86400
SESSION_START_WINDOW_SECONDS = 30


def _safe(value: str) -> str:
    return "".join(c for c in value if c.isalnum() or c in "-_")[:64]


def _event_key(payload: dict) -> str | None:
    """Identity that every copy of a hook sees for the same event, else None."""
    event = str(payload.get("hook_event_name") or "")
    if payload.get("tool_use_id"):
        return f"{event}:{payload['tool_use_id']}"
    if event == "SessionStart" and payload.get("session_id"):
        # Copies start within milliseconds; the window separates later
        # SessionStart events (resume, clear, compact) in the same session.
        bucket = int(time.time() // SESSION_START_WINDOW_SECONDS)
        return f"{event}:{payload.get('source', '')}:{bucket}"
    return None


def _prune(except_dir: Path) -> None:
    cutoff = time.time() - LOCK_TTL_SECONDS
    for entry in LOCK_ROOT.iterdir():
        if entry != except_dir and entry.is_dir() and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)


def _claim(key: str, hook: str, session: str) -> bool:
    """Atomically claim (event, hook). False when another copy already has."""
    session_dir = LOCK_ROOT / (_safe(session) or "no-session")
    first_in_session = not session_dir.exists()
    session_dir.mkdir(parents=True, exist_ok=True)
    lock = session_dir / hashlib.sha1(f"{key}|{hook}".encode()).hexdigest()
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    if first_in_session:
        _prune(session_dir)
    return True


def should_skip(payload: dict, hook_file: str) -> bool:
    """True when this copy of the hook must exit 0 without acting."""
    try:
        if "--plugin" in sys.argv[1:]:
            root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
            if not (root / PROJECT_MARKER).exists():
                return True
        key = _event_key(payload)
        if key is None:
            return False
        return not _claim(key, Path(hook_file).name, str(payload.get("session_id") or ""))
    except Exception:
        return False
