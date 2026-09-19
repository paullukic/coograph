#!/usr/bin/env python3
"""log-bash: PreToolUse hook that audits every Bash command the agent runs.

Two layers of trail, both per-project and gitignored, under the unified
`.coograph/` directory so every supported agent writes to the same place:

  .coograph/session.log
      Chronological tail of every command across every session, each line
      prefixed with the tool name and a short session-id so you can grep
      one session out of the combined stream.

  .coograph/sessions/<session_id>.log
      One file per agent session. No prefix in the lines because the
      filename already carries it. Easy to attach to an incident report
      or share a single conversation's command history.

This script is the Claude Code variant. The Codex CLI variant lives at
`.codex/hooks/log-bash.py` and writes to the same files. The OpenCode
plugin at `.opencode/plugin/log-bash.ts` does the same in TypeScript.

The hook never blocks the tool call. Write failures are swallowed silently.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__/ out of .claude/hooks/
try:
    from _coograph_guard import should_skip
except ImportError:  # guard not copied next to this hook: run unguarded
    def should_skip(payload: dict, hook_file: str) -> bool:
        return False

AGENT = "claude-code"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    if should_skip(payload, __file__):
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return 0

    raw_sid = str(payload.get("session_id") or "unknown")
    # Defensive: Claude Code session ids are UUIDs, but other agent payloads
    # may differ. Strip anything that is not safe in a filename.
    safe_sid = "".join(c for c in raw_sid if c.isalnum() or c in "-_")[:64] or "unknown"
    short_sid = safe_sid[:8]

    cwd = Path(payload.get("cwd") or os.getcwd())
    log_dir = cwd / ".coograph"
    sessions_dir = log_dir / "sessions"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    global_line = f"[{timestamp}] [{AGENT}] [{short_sid}] {command}\n"
    per_session_line = f"[{timestamp}] [{AGENT}] {command}\n"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "session.log").open("a", encoding="utf-8") as fh:
            fh.write(global_line)
        with (sessions_dir / f"{safe_sid}.log").open("a", encoding="utf-8") as fh:
            fh.write(per_session_line)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
