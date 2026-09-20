#!/usr/bin/env python3
"""no-new-deps-warn: PreToolUse hook that warns when a dependency is added.

`no-new-deps` ships in rules.seed.json with a deterministic detector in
capture-signals.py and, until this hook, no enforcement. Retro could measure the
rule and escalate it, but the escalation had to be hand-written by every project
that hit the threshold.

Two properties are deliberate:

1. The decision comes from `_coograph_signals.dep_command`, the same function
   capture-signals.py uses. The hook cannot warn about something the detector
   would not count, or stay silent on something it would.

2. This hook records nothing. `no-new-deps` already has a transcript detector,
   and a hook-emitted copy of the same violation would be counted twice by
   `summarize`, halving the rule's escalation threshold against itself. The
   detector measures; this hook warns. Contrast warn-scope.py and
   block-generated.py, whose rules have no transcript detector and therefore
   must emit their own records.

Never blocks - exits 1 so the warning surfaces without stopping the command, and
at most once per session. If `.coograph/` is unwritable the marker cannot be
written, so the warning degrades to once per install rather than once per
session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__/ out of .claude/hooks/
try:
    from _coograph_guard import should_skip
except ImportError:  # guard not copied next to this hook: run unguarded
    def should_skip(payload: dict, hook_file: str) -> bool:
        return False
try:
    import _coograph_signals as signals  # shim in this directory -> .github/retro/
except ImportError:  # without the shared module there is no detector to agree with
    signals = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
MARKER_DIR = "markers"


def _marker(cwd: Path, sid: str) -> Path:
    return cwd / ".coograph" / MARKER_DIR / f"deps-warned-{sid}"


def _touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    if signals is None:
        return 0

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

    subject: str | None = None
    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        if signals.dep_command(command):
            subject = command.split()[0] if command.split() else "a package"
    elif tool in EDIT_TOOLS:
        raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if raw and Path(raw).name in signals.DEP_MANIFESTS:
            subject = Path(raw).name
    else:
        return 0

    if not subject:
        return 0
    if _marker(cwd, sid).exists():
        return 0

    print(
        f"[no-new-deps] adding a dependency ({subject}). This project's rules require "
        f"explicit user approval before a new dependency lands - confirm before continuing.",
        file=sys.stderr,
    )
    _touch(_marker(cwd, sid))
    return 1


if __name__ == "__main__":
    sys.exit(main())
