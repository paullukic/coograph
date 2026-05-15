#!/usr/bin/env python3
"""log-bash: PreToolUse hook that audits every Bash command the agent runs.

Two layers of trail, both per-project and gitignored:

  .claude/session.log
      Chronological tail of every command across every session, each line
      prefixed with a short session-id (`[<sid8>]`) so you can grep one
      session out of the combined stream. Easiest place to scan a long
      history.

  .claude/sessions/<session_id>.log
      One file per Claude Code session. No session-id prefix in the lines
      because the filename already carries it. Easy to share or attach to
      an incident report when you only want the scope of a single session.

The hook never blocks the tool call. Write failures are swallowed silently
so a broken disk or a permission glitch can never wedge the agent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return 0

    raw_sid = str(payload.get("session_id") or "unknown")
    # Defensive: Claude Code session ids are UUIDs, but other agent payloads
    # may differ. Strip anything that is not safe in a filename.
    safe_sid = "".join(c for c in raw_sid if c.isalnum() or c in "-_")[:64] or "unknown"
    short_sid = safe_sid[:8]

    cwd = Path(payload.get("cwd") or ".")
    log_dir = cwd / ".claude"
    sessions_dir = log_dir / "sessions"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    global_line = f"[{timestamp}] [{short_sid}] {command}\n"
    per_session_line = f"[{timestamp}] {command}\n"

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
