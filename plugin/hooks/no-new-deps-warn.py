#!/usr/bin/env python3
"""no-new-deps-warn: PreToolUse hook that warns when a dependency is added.

`no-new-deps` ships in rules.seed.json with a deterministic detector in
capture-signals.py and, until this hook, no enforcement. Retro could measure the
rule and escalate it, but the escalation had to be hand-written by every project
that hit the threshold.

Mirrors the `new-dependency` detector exactly, including what it does NOT count:
a command that only restores what a manifest already lists is not an addition.
A hook that disagreed with its detector would make the next report unreadable.

Never blocks - exits 1 so the warning surfaces without stopping the command, and
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

EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml",
    "go.mod", "Cargo.toml", "composer.json", "Gemfile",
}

# A named package follows the verb. Bare installs and manifest restores do not match.
INSTALL_RE = re.compile(
    r"\b("
    r"npm\s+(?:install|i|add)|pnpm\s+(?:install|add)|yarn\s+add|bun\s+add|"
    r"pip3?\s+install|uv\s+(?:add|pip\s+install)|poetry\s+add|"
    r"cargo\s+add|go\s+get|composer\s+require|gem\s+install"
    r")\s+(?P<rest>[^\n;&|]*)",
    re.IGNORECASE,
)
RESTORE_FLAGS = re.compile(
    r"(^|\s)(-r|--requirement|-e|--editable|--frozen|--from-lockfile)(\s|=|$)"
)


def _marker(cwd: Path, sid: str) -> Path:
    return cwd / ".coograph" / f"deps-warned-{sid}"


def _touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        pass


def _installs_named_package(command: str) -> str | None:
    """The package being added, or None when nothing is being added."""
    for match in INSTALL_RE.finditer(command):
        rest = (match.group("rest") or "").strip()
        if not rest:
            continue  # bare `npm install`: restores the manifest, adds nothing
        if RESTORE_FLAGS.search(rest):
            continue  # `pip install -r ...`, `pip install -e .`
        first = rest.split()[0]
        if first.startswith("-") or first in {".", "./"}:
            continue
        return first[:80]
    return None


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

    subject: str | None = None
    if tool == "Bash":
        subject = _installs_named_package(str(tool_input.get("command") or ""))
    elif tool in EDIT_TOOLS:
        raw = str(tool_input.get("file_path") or "")
        if raw and Path(raw).name in MANIFESTS:
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
    _emit_signal(payload, cwd, sid, subject)
    return 1


def _emit_signal(payload: dict, cwd: Path, sid: str, subject: str) -> None:
    """Record the warning for Retro. Never affects the hook's own behavior."""
    if signals is None:
        return
    try:
        signals.emit(cwd, signals.make_record(
            tool="claude-code",
            session_id=sid,
            kind="violation",
            rule="no-new-deps",
            detector="new-dependency",
            confidence="deterministic",
            evidence={"package": subject, "proof": "hook"},
            origin="hook",
        ))
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
