#!/usr/bin/env python3
"""log-bash: Codex CLI PreToolUse hook that audits every Bash command.

Mirror of `.claude/hooks/log-bash.py` — same `.coograph/` output layout,
different `agent` prefix in the log lines so cross-tool incident response
can grep by agent.

Wire it into Codex CLI by adding to `~/.codex/config.toml` (user-global
config — Codex does not read project-local config.toml for hooks):

    [[hooks.PreToolUse]]
    matcher = "^Bash$"

    [[hooks.PreToolUse.hooks]]
    type = "command"
    command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/log-bash.py"'
    timeout = 5

The hook never blocks the tool call. Write failures are swallowed silently.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

AGENT = "codex-cli"


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
