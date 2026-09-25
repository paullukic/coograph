#!/usr/bin/env python3
"""openspec-gate-warn: PreToolUse hook that warns when a session edits a second
source file without an OpenSpec.

`OPENSPEC OR STOP` is the loudest rule in CLAUDE.md and, until this hook, had
no enforcement: its detector in capture-signals.py is heuristic and runs after
the session ends. This hook mirrors that detector live, at the moment the
second distinct source file is about to be edited.

Same classification as the detector, on purpose. A path is a source edit when
`signals.rel_path` puts it inside the project and outside `openspec/`. An edit
under `openspec/changes/`, or a shell command naming `openspec/changes`, counts
as touching an OpenSpec. `signals.active_openspec_exists` is the detector's own
check for an active change directory.

Records a decision (warned / suppressed) through `_coograph_signals` and never
a violation: `openspec-gate` has a transcript detector, and a hook-emitted
violation would be counted twice.

Never blocks: exits 1 so the warning surfaces without stopping the edit, at
most once per session. Markers under .coograph/markers/, keyed by session id:
  openspec-edited-<sid>   distinct source paths edited so far, one per line
  openspec-touched-<sid>  an OpenSpec change directory was edited or created
  openspec-warned-<sid>   the warning has already been shown
If `.coograph/` is unwritable the edited marker cannot grow, so the hook
stays silent rather than warning on every edit.
"""

from __future__ import annotations

import json
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
except ImportError:  # without the shared module there is no detector to agree with
    signals = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
MARKER_DIR = "markers"
MARKER_TTL_SECONDS = 7 * 86400
RULE = "openspec-gate"


def _marker(cwd: Path, kind: str, sid: str) -> Path:
    return cwd / ".coograph" / MARKER_DIR / f"openspec-{kind}-{sid}"


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


def _remember_edit(cwd: Path, sid: str, rel: str) -> set[str]:
    """Add rel to the session's edited set; return the set as stored."""
    marker = _marker(cwd, "edited", sid)
    try:
        edited = set(marker.read_text(encoding="utf-8").split("\n")) - {""}
    except OSError:
        edited = set()
    if rel in edited:
        return edited
    edited.add(rel)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("\n".join(sorted(edited)) + "\n", encoding="utf-8")
    except OSError:
        return set()
    return edited


def _decide(cwd: Path, payload: dict, action: str, path: str) -> None:
    """Record the decision for Retro. Never affects the hook's own behavior."""
    try:
        signals.emit_decision(cwd, payload, RULE, action, __file__, path)
    except Exception:
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

    if tool in SHELL_TOOLS:
        command = str(tool_input.get("command") or "").replace("\\", "/")
        if "openspec/changes" in command:
            _touch(_marker(cwd, "touched", sid))
        return 0

    if tool not in EDIT_TOOLS:
        return 0

    raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not raw:
        return 0
    rel = signals.rel_path(cwd, raw)
    if rel == "openspec/changes" or rel.startswith("openspec/changes/"):
        _touch(_marker(cwd, "touched", sid))
        return 0
    if rel == "external" or rel.startswith("openspec/"):
        return 0

    edited = _remember_edit(cwd, sid, rel)
    if len(edited) < 2:
        return 0
    if _marker(cwd, "touched", sid).exists():
        return 0
    if signals.active_openspec_exists(cwd):
        return 0
    if _marker(cwd, "warned", sid).exists():
        _decide(cwd, payload, "suppressed", rel)
        return 0

    print(
        f"[openspec-gate] second source file this session ({rel}) with no OpenSpec touched "
        "and no active change under openspec/changes/. CLAUDE.md OPENSPEC OR STOP: "
        "propose first, or name the literal exemption.",
        file=sys.stderr,
    )
    _touch(_marker(cwd, "warned", sid))
    _decide(cwd, payload, "warned", rel)
    return 1


if __name__ == "__main__":
    sys.exit(main())
