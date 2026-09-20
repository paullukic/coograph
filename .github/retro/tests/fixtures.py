"""Fixture helpers for the Retro tests.

Builds Claude Code transcript JSONL files with the shape the parser depends
on (one line per content block, usage repeated per line, sessionId and
timestamp on every message, isSidechain on subagent lines). Keeping this in
one place means a format change breaks one file, not twenty tests.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
HOOKS = REPO / ".claude" / "hooks"
RETRO = REPO / ".github" / "retro"
SEED = RETRO / "rules.seed.json"

SENTINEL = "SECRET_SENTINEL_9f3a"

# Tests import the canonical module directly from .github/retro/; the hook
# shim is exercised by the subprocess tests, which run the real hooks.
if str(RETRO) not in sys.path:
    sys.path.insert(0, str(RETRO))
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))


class Transcript:
    """Fluent builder for a transcript file."""

    def __init__(self, session_id: str = "sess-0001") -> None:
        self.session_id = session_id
        self.lines: list[dict] = []
        self._n = 0
        self._tool_n = 0
        self.at = ""  # pin every following line to this moment when set

    # -- internals ----------------------------------------------------------
    def _ts(self) -> str:
        # Set `.at` to pin every following line to one moment, for tests that
        # need a session to span several days.
        if self.at:
            return self.at
        self._n += 1
        return f"2026-09-{10 + self._n // 1000:02d}T10:{(self._n // 60) % 60:02d}:{self._n % 60:02d}.000Z"

    def _line(self, kind: str, message: dict, sidechain: bool = False, **extra) -> "Transcript":
        self.lines.append({
            "type": kind,
            "sessionId": self.session_id,
            "timestamp": self._ts(),
            "isSidechain": sidechain,
            "message": message,
            **extra,
        })
        return self

    # -- assistant ----------------------------------------------------------
    def tool(self, name: str, sidechain: bool = False, usage: dict | None = None,
             message_id: str | None = None, **inp) -> str:
        """Append one tool_use block; returns its id."""
        self._tool_n += 1
        tid = f"toolu_{self._tool_n:04d}"
        mid = message_id or f"msg_{self._n + 1:04d}"
        self._line("assistant", {
            "id": mid, "role": "assistant",
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}],
            "usage": usage or {},
        }, sidechain=sidechain)
        return tid

    def say(self, text: str, usage: dict | None = None, message_id: str | None = None) -> "Transcript":
        mid = message_id or f"msg_{self._n + 1:04d}"
        return self._line("assistant", {
            "id": mid, "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "usage": usage or {},
        })

    # -- user ---------------------------------------------------------------
    def result(self, tool_id: str, content: str = "ok", is_error: bool = False) -> "Transcript":
        block = {"type": "tool_result", "tool_use_id": tool_id, "content": content}
        if is_error:
            block["is_error"] = True
        return self._line("user", {"role": "user", "content": [block]})

    def user(self, text: str) -> "Transcript":
        return self._line("user", {"role": "user", "content": text})

    def raw(self, text: str) -> "Transcript":
        """Append a raw (possibly malformed) line."""
        self.lines.append({"__raw__": text})
        return self

    # -- output -------------------------------------------------------------
    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for obj in self.lines:
                if "__raw__" in obj:
                    fh.write(obj["__raw__"] + "\n")
                else:
                    fh.write(json.dumps(obj) + "\n")
        return path


def make_project(root: Path, *, graph: bool = True, rules: bool = True,
                 active_openspec: bool = False, archives: int = 0) -> Path:
    """A minimal Coograph project directory under root."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
    for name in ("_coograph_signals.py", "_coograph_guard.py", "capture-signals.py",
                 "warn-scope.py", "block-generated.py",
                 "no-new-deps-warn.py", "defect-warn.py"):
        shutil.copyfile(HOOKS / name, root / ".claude" / "hooks" / name)
    (root / ".github" / "skills" / "coograph-init").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "skills" / "coograph-init" / "SKILL.md").write_text("marker\n")
    (root / ".github" / "retro").mkdir(parents=True, exist_ok=True)
    for name in ("retro.py", "_coograph_signals.py", "rules.seed.json"):
        shutil.copyfile(RETRO / name, root / ".github" / "retro" / name)
    if rules:
        shutil.copyfile(SEED, root / ".github" / "retro" / "rules.json")
    if graph:
        (root / ".code-graph").mkdir(exist_ok=True)
        (root / ".code-graph" / "graph.db").write_bytes(b"")
    changes = root / "openspec" / "changes"
    (changes / "archive").mkdir(parents=True, exist_ok=True)
    if active_openspec:
        (changes / "2026-09-01-active").mkdir()
        (changes / "2026-09-01-active" / "tasks.md").write_text("- [ ] edit `src/a.ts`\n")
    for i in range(archives):
        d = changes / "archive" / f"2026-08-{i + 1:02d}-change-{i}"
        d.mkdir()
        body = "# Tasks\n\n- [x] edit `src/core/thing.ts`\n- [x] edit `src/api/route.ts`\n"
        if i % 2 == 0:
            body += "\n## Review Fixes\n\n- [x] fix `src/core/thing.ts`\n"
        if i % 3 == 0:
            body += "- [ ] leftover\n"
        (d / "tasks.md").write_text(body)
    (root / "CLAUDE.md").write_text("# rules\n" * 50)
    return root


def read_signals(root: Path) -> list[dict]:
    path = root / ".coograph" / "signals.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
