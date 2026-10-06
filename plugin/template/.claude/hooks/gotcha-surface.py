#!/usr/bin/env python3
"""gotcha-surface: PreToolUse hook that shows the GOTCHAS.md entries matching
the file about to be edited or the command about to run.

Gotchas are traps learned the hard way ("env vars in the shell do not override
.env for `expo export`"). Buried in a map, agents find them too late. Loaded on
every task, they cost tokens on every task. This hook puts an entry in front of
the model exactly when it applies: an edit under one of its `paths:`, or a shell
command containing one of its `commands:`.

Entries are read from the files `.github/layout/layout.json` declares (or the
seed defaults) by `.github/layout/layout.py`, so the hook and `--budget` parse
the same format. Without that module the hook does nothing.

Output is `hookSpecificOutput.additionalContext` on stdout with exit 0: Claude
Code's non-blocking way to add context on PreToolUse. It never blocks, never
warns, and sets no permission decision.

Each entry is shown once per session (marker
.coograph/markers/gotcha-<id>-<sid>). Every showing records a decision
(`surfaced`, rule `gotchas`, with the entry id) through `_coograph_signals`, so
Retro can count which gotchas fire. Never a violation: a gotcha is knowledge,
not a broken rule.
"""

from __future__ import annotations

import importlib.util
import json
import os
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
except ImportError:  # Retro not installed: surface entries, record nothing
    signals = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
LAYOUT_REL = Path(".github") / "layout" / "layout.py"
MARKER_DIR = "markers"
MARKER_TTL_SECONDS = 7 * 86400
RULE = "gotchas"
_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _project_root(payload: dict) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / LAYOUT_REL).is_file():
        return Path(env)
    return Path(payload.get("cwd") or ".")


def _load_layout(root: Path):
    path = root / LAYOUT_REL
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("coograph_layout", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _marker(cwd: Path, gotcha_id: str, sid: str) -> Path:
    return cwd / ".coograph" / MARKER_DIR / f"gotcha-{_SAFE.sub('', gotcha_id)[:80]}-{sid}"


def _touch(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        _prune(path.parent)
        return True
    except OSError:
        return False


def _prune(directory: Path) -> None:
    """Markers are per-session and worthless once the session is gone."""
    cutoff = time.time() - MARKER_TTL_SECONDS
    try:
        for stale in directory.iterdir():
            if stale.is_file() and stale.name.startswith("gotcha-") and stale.stat().st_mtime < cutoff:
                stale.unlink(missing_ok=True)
    except OSError:
        pass


def _rel(root: Path, raw: str) -> str:
    if signals is not None:
        return signals.rel_path(root, raw)
    try:
        return Path(raw).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return "external"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    tool = payload.get("tool_name")
    if tool not in EDIT_TOOLS and tool not in SHELL_TOOLS:
        return 0
    if should_skip(payload, __file__):
        return 0

    root = _project_root(payload)
    layout = _load_layout(root)
    if layout is None:
        return 0
    try:
        config, _ = layout.load_config(root)
        entries = layout.load_gotchas(root, config, layout.find_files(root, config["gotchas"]))
    except Exception:
        return 0
    if not entries:
        return 0

    tool_input = payload.get("tool_input") or {}
    rel_path = command = None
    if tool in EDIT_TOOLS:
        raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if not raw:
            return 0
        rel_path = _rel(root, raw)
        if rel_path == "external":
            return 0
    else:
        command = str(tool_input.get("command") or "")
        if not command:
            return 0

    sid = _SAFE.sub("", str(payload.get("session_id") or "unknown"))[:64] or "unknown"
    shown: list[str] = []
    for entry in entries:
        if entry.get("missing") or not layout.gotcha_matches(entry, rel_path, command):
            continue
        marker = _marker(root, entry["id"], sid)
        if marker.exists() or not _touch(marker):
            continue
        shown.append(entry["text"])
        if signals is not None:
            try:
                signals.emit_decision(root, payload, RULE, "surfaced", __file__,
                                      rel_path or "", gotcha=entry["id"])
            except Exception:
                pass

    if not shown:
        return 0
    target = f"`{rel_path}`" if rel_path else "this command"
    context = (
        f"[gotcha] GOTCHAS.md entries that apply to {target}. Follow their Fix / rule:\n\n"
        + "\n\n".join(shown)
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": context,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
