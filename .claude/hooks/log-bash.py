#!/usr/bin/env python3
"""log-bash: PreToolUse hook that appends Bash commands to .claude/session.log.

Audit trail for every shell command the agent runs in this project. The log
is per-project, gitignored, and never blocks the tool call - failures to
write are swallowed silently.
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

    cwd = Path(payload.get("cwd") or ".")
    log_dir = cwd / ".claude"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "session.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {command}\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
