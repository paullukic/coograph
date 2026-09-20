#!/usr/bin/env python3
"""capture-signals: turns Claude Code transcripts into Retro signals.

Three modes, one parser:

  SessionEnd hook      Parse this session's transcript (transcript_path in
                       the payload) and write its records.
  SessionStart hook    source startup/resume: catch up sibling transcripts
                       that were never captured (killed sessions), time-boxed.
                       source compact: capture this session's own transcript,
                       because a session that runs for a day compacts many
                       times and would otherwise report nothing until it ends.
                       Either way, print one status line so the user and the
                       agent see whether Retro has something to say.
  --backfill <dir>     Parse every *.jsonl in a directory, idempotently.
                       Gives a project data on day one.

What gets written is metadata only: tool names, counts, rule ids, repo-
relative paths, command hashes, timestamps, token usage. Never prompt text,
code, tool output, or full commands. See _coograph_signals.ALLOWED_EVIDENCE.

The hook never blocks and always exits 0. Any parse problem means fewer
signals, not a failed session.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__/ out of .claude/hooks/
try:
    from _coograph_guard import should_skip
except ImportError:  # guard not copied next to this hook: run unguarded
    def should_skip(payload: dict, hook_file: str) -> bool:
        return False

try:
    import _coograph_signals as signals  # shim in this directory -> .github/retro/
except ImportError:  # Retro not installed in this project: hook is a no-op
    signals = None

AGENT = "claude-code"

CATCHUP_MAX_FILES = 20
CATCHUP_BUDGET_SECONDS = 2.0
TRANSCRIPT_MAX_BYTES = 200 * 1024 * 1024
CATCHUP_SOURCES = {"", "startup", "resume", "clear"}
# /clear and /new start a fresh transcript, leaving the one you just left
# uncaptured until some later session happens to catch it; both fire here with
# source "clear", so the catch-up runs then too.
# Compaction is the only hook event a marathon session fires repeatedly, so it
# is where a long session gets to report. Capture is idempotent on message
# count and replaces the session's records, so re-capturing never double-counts.
SELF_CAPTURE_SOURCES = {"compact"}

# Defect detector: a fix landing on a file a recent non-fix commit touched.
FIX_SUBJECT_RE = re.compile(r"^(?:fix|hotfix|revert)\b", re.IGNORECASE)
DEFECT_LOOKBACK_DAYS_DEFAULT = 14
DEFECT_MAX_SIGNALS = 20
# A project root that is not a repository usually holds a few: app/, admin/,
# functions/. Bounded so a directory full of checkouts cannot stall a capture.
DEFECT_MAX_REPOS = 5
DEFECT_MAX_FILES = 20
SKIP_REPO_DIRS = {"node_modules", "dist", "build", "vendor", "__pycache__", "openspec"}
GIT_TIMEOUT_SECONDS = 5.0

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SEARCH_TOOLS = {"Grep", "Glob"}
SHELL_TOOLS = {"Bash", "PowerShell"}
GRAPH_PREFIX = "mcp__code-graph__"

DEP_PROGRAMS = {"npm", "pnpm", "yarn", "pip", "pip3", "uv", "cargo", "go", "composer", "bun"}
DEP_VERBS = {"install", "i", "add", "get", "require"}
DEP_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "go.mod",
    "Cargo.toml", "composer.json", "Gemfile",
}

DEFAULT_CORRECTION_PATTERNS = [
    {"id": "no", "regex": r"^\s*no[,.! ]", "enabled": True},
    {"id": "i-said", "regex": r"\bI said\b", "enabled": True},
    {"id": "again", "regex": r"\bagain\b", "enabled": True},
    {"id": "stop", "regex": r"\bstop\b", "enabled": True},
    {"id": "wrong", "regex": r"\bwrong\b", "enabled": True},
    {"id": "not-what-i", "regex": r"\bnot what I\b", "enabled": True},
]


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

class Parsed:
    """Everything the detectors need, and nothing that could leak."""

    def __init__(self) -> None:
        self.session_id = ""
        self.source_bytes = 0
        self.message_count = 0
        # Timestamp of the message currently being parsed, stamped onto each
        # tool use and correction. A violation has to carry the moment it
        # happened: stamping everything with the session end collapses a
        # week-long session into one episode and hides its own history.
        self.at = ""
        self.started = ""
        self.ended = ""
        self.tool_uses: list[dict] = []          # {index,name,sidechain,file,command,skill,id}
        self.results: dict[str, bool] = {}       # tool_use_id -> is_error
        self.usage_by_message: dict[str, dict] = {}
        self.corrections: list[dict] = []        # {pattern, after_tool}
        # True once any non-sidechain tool_use happened since the last user
        # text. A correction usually follows a turn of tool activity that
        # ended in plain text, so "the immediately preceding message had a
        # tool" would almost never be true.
        self._tool_since_user_text = False
        self._next_index = 0

    # -- assistant ---------------------------------------------------------
    def assistant(self, obj: dict) -> None:
        message = obj.get("message") or {}
        sidechain = bool(obj.get("isSidechain"))
        content = message.get("content")
        had_tool = False
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                had_tool = True
                inp = block.get("input") or {}
                if not isinstance(inp, dict):
                    inp = {}
                self.tool_uses.append({
                    "index": self._next_index,
                    "ts": self.at,
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "sidechain": sidechain,
                    "file": inp.get("file_path") or inp.get("notebook_path") or "",
                    "command": inp.get("command") if isinstance(inp.get("command"), str) else "",
                    "skill": str(inp.get("skill") or "") if block.get("name") == "Skill" else "",
                })
                self._next_index += 1
        mid = str(message.get("id") or "")
        usage = message.get("usage")
        if mid and isinstance(usage, dict) and mid not in self.usage_by_message:
            self.usage_by_message[mid] = {
                "input": _int(usage.get("input_tokens")),
                "output": _int(usage.get("output_tokens")),
                "cache_read": _int(usage.get("cache_read_input_tokens")),
                "cache_create": _int(usage.get("cache_creation_input_tokens")),
            }
        if had_tool and not sidechain:
            self._tool_since_user_text = True

    # -- user --------------------------------------------------------------
    def user(self, obj: dict, patterns: list[dict]) -> None:
        message = obj.get("message") or {}
        content = message.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    tid = str(block.get("tool_use_id") or "")
                    if tid:
                        self.results[tid] = block.get("is_error") is True
                elif btype == "text" and isinstance(block.get("text"), str):
                    texts.append(block["text"])
        if texts and not obj.get("isSidechain") and not obj.get("isMeta"):
            joined = "\n".join(texts)
            if not joined.lstrip().startswith("<"):  # skip system-injected blocks
                for pat in patterns:
                    if not pat.get("enabled", True):
                        continue
                    try:
                        if re.search(pat["regex"], joined, re.IGNORECASE):
                            self.corrections.append({
                                "pattern": str(pat["id"])[:40],
                                "after_tool": self._tool_since_user_text,
                                # Dropped from stored evidence by the
                                # allow-list; read by detect() for the stamp.
                                "_ts": self.at,
                            })
                            break
                    except re.error:
                        continue
            self._tool_since_user_text = False


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_transcript(path: Path, patterns: list[dict]) -> Parsed | None:
    """Stream a transcript. Unknown or malformed lines are skipped."""
    parsed = Parsed()
    try:
        parsed.source_bytes = path.stat().st_size
        if parsed.source_bytes > TRANSCRIPT_MAX_BYTES:
            return None
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                kind = obj.get("type")
                if kind not in ("assistant", "user"):
                    continue
                parsed.message_count += 1
                sid = obj.get("sessionId") or obj.get("session_id")
                if sid and not parsed.session_id:
                    parsed.session_id = str(sid)
                ts = obj.get("timestamp")
                if isinstance(ts, str) and ts:
                    parsed.at = ts
                    if not parsed.started or ts < parsed.started:
                        parsed.started = ts
                    if ts > parsed.ended:
                        parsed.ended = ts
                if kind == "assistant":
                    parsed.assistant(obj)
                else:
                    parsed.user(obj, patterns)
    except OSError:
        return None
    if not parsed.session_id:
        parsed.session_id = path.stem
    return parsed


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def _touches_openspec_changes(parsed: Parsed, cwd: Path) -> bool:
    for use in parsed.tool_uses:
        if use["file"] and "openspec/changes" in signals.rel_path(cwd, use["file"]):
            return True
        if use["command"] and "openspec/changes" in use["command"].replace("\\", "/"):
            return True
    return False


def _active_openspec_exists(cwd: Path) -> bool:
    changes = cwd / "openspec" / "changes"
    try:
        return any(p.is_dir() and p.name != "archive" for p in changes.iterdir())
    except OSError:
        return False


DEP_FILE_FLAGS = {"-r", "--requirement", "--requirements", "-c", "--constraint"}


def _dep_command(command: str) -> bool:
    """True for commands that add a dependency, not for ones that install
    what a manifest already lists (`pip install -r requirements.txt`,
    `pip install -e .`, `npm install`)."""
    tokens = [t for t in command.replace("&&", " ").replace("||", " ").split() if t]
    if not tokens:
        return False
    program = tokens[0].replace("\\", "/").rsplit("/", 1)[-1]
    if program not in DEP_PROGRAMS:
        return False
    rest: list[str] = []
    skip_next = False
    for t in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if t in DEP_FILE_FLAGS:
            skip_next = True
            continue
        if t.startswith("-"):
            continue
        if t in {".", ".."} or t.endswith((".txt", ".in", ".lock")):
            continue
        rest.append(t)
    if program == "uv" and rest[:1] == ["pip"]:
        rest = rest[1:]
    if not rest or rest[0] not in DEP_VERBS:
        return False
    return len(rest) >= 2


# ---------------------------------------------------------------------------
# Defect detector
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> str:
    """git output, or '' for any failure. Never raises, never blocks capture."""
    try:
        out = subprocess.run(
            ["git", "--no-pager", *args],
            cwd=str(cwd), capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _commits(cwd: Path, since: str) -> list[tuple[str, str, list[str]]]:
    """[(short_sha, subject, [paths])] for commits since an ISO timestamp."""
    raw = _git(cwd, "log", f"--since={since}", "--name-only", "--no-merges",
               "--pretty=format:%x00%h%x1f%s")
    if not raw:
        return []
    out: list[tuple[str, str, list[str]]] = []
    for chunk in raw.split("\x00"):
        if not chunk.strip():
            continue
        head, _, body = chunk.partition("\n")
        sha, _, subject = head.partition("\x1f")
        paths = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if sha:
            out.append((sha.strip(), subject.strip(), paths))
    return out


def git_roots(cwd: Path) -> list[tuple[Path, str]]:
    """Repositories to scan, as (path, prefix).

    A project root is often not the repository. `gastarbajter` holds `app/`
    and `admin/`, each its own repo, and a scan of the root alone finds
    nothing. When the root is a repo it is the only one scanned; otherwise its
    immediate subdirectories that are repos are, and their name becomes the
    prefix so evidence paths stay project-relative and unambiguous.
    """
    if (cwd / ".git").exists():  # a file for worktrees and submodules
        return [(cwd, "")]
    out: list[tuple[Path, str]] = []
    try:
        children = sorted(p for p in cwd.iterdir() if p.is_dir())
    except OSError:
        return []
    for child in children:
        if child.name.startswith(".") or child.name in SKIP_REPO_DIRS:
            continue
        if (child / ".git").exists():
            out.append((child, child.name + "/"))
            if len(out) >= DEFECT_MAX_REPOS:
                break
    return out


def _defects_in(root: Path, prefix: str, started: str, lookback_days: int,
                budget: int) -> list[dict]:
    """Defect signals for one repository, at most `budget` of them.

    One signal per fix commit and origin pair, not per file. A fix touching
    twenty files is one defect, and counting it twenty times would let this
    rule drown out every other in the report.

    The origin has to be the newest non-fix commit *older than the fix*. Taking
    the newest one overall reports a change that landed after the fix as its
    cause, which reads as nonsense in a report. `git log` is newest first, so
    the origin is the first non-fix entry that follows the fix in the list.
    """
    window = {sha for sha, _subject, _paths in _commits(root, started)}
    if not window:
        return []
    history = _commits(root, f"{lookback_days + 1}.days.ago")
    found: list[dict] = []
    for i, (sha, subject, paths) in enumerate(history):
        if sha not in window or not FIX_SUBJECT_RE.match(subject):
            continue
        by_origin: dict[str, list[str]] = {}
        for path in paths:
            for older_sha, older_subject, older_paths in history[i + 1:]:
                if FIX_SUBJECT_RE.match(older_subject) or path not in older_paths:
                    continue
                by_origin.setdefault(older_sha, []).append(prefix + path)
                break
        for origin_sha, files in by_origin.items():
            found.append({
                "fix": sha, "origin": origin_sha,
                "files": sorted(files)[:DEFECT_MAX_FILES], "count": len(files),
                "days": lookback_days,
            })
            if len(found) >= budget:
                return found
    return found


def detect_defects(cwd: Path, parsed: Parsed, lookback_days: int) -> list[dict]:
    """A fix commit landing on a file a recent non-fix commit touched.

    Scoped to the session's own window so a signal is attributable to the work
    that produced it, and to every repository the project holds. Evidence is
    paths and abbreviated hashes only: never a commit message, never a diff.
    """
    if not parsed.started:
        return []
    found: list[dict] = []
    for root, prefix in git_roots(cwd):
        found.extend(_defects_in(root, prefix, parsed.started, lookback_days,
                                 DEFECT_MAX_SIGNALS - len(found)))
        if len(found) >= DEFECT_MAX_SIGNALS:
            break
    return found


def detect(parsed: Parsed, cwd: Path, rules: dict | None) -> list[dict]:
    sid = parsed.session_id
    records: list[dict] = []
    graph_db_present = (cwd / ".code-graph" / "graph.db").exists()

    def rec(kind: str, rule: str, detector: str, confidence: str, evidence: dict,
            at: str = "") -> None:
        r = signals.make_record(
            tool=AGENT, session_id=sid, kind=kind, rule=rule, detector=detector,
            confidence=confidence, evidence=evidence, origin="transcript",
            ts=at or parsed.ended or None,
        )
        if r:
            records.append(r)

    # graph-first -------------------------------------------------------
    # The rule is about order: touch the graph (MCP tool, or the documented
    # sqlite3 fallback) before any Grep/Glob. Any search call that happens
    # before the first graph access counts. Proof records what eventually
    # happened so the report can tell "used the graph late" from "never
    # used it at all".
    graph_calls = [u for u in parsed.tool_uses if u["name"].startswith(GRAPH_PREFIX)]
    sqlite_calls = [
        u for u in parsed.tool_uses
        if u["name"] in SHELL_TOOLS and "sqlite3" in u["command"] and ".code-graph" in u["command"]
    ]
    if graph_db_present:
        accesses = [u["index"] for u in graph_calls] + [u["index"] for u in sqlite_calls]
        first_access = min(accesses) if accesses else None
        early = [
            u for u in parsed.tool_uses
            if u["name"] in SEARCH_TOOLS and not u["sidechain"]
            and (first_access is None or u["index"] < first_access)
        ]
        proof = None
        if early and graph_calls:
            proof = "mcp-later"
        elif early and sqlite_calls:
            proof = "sqlite-later"
        elif early:
            proof = "total-bypass"
        if proof:
            rec("violation", "graph-first", "graph-first", "deterministic", {
                "count": len(early),
                "first_index": early[0]["index"],
                "tools": sorted({u["name"] for u in early}),
                "proof": proof,
            }, at=early[0].get("ts", ""))

    # edited files ------------------------------------------------------
    edited: list[str] = []
    for u in parsed.tool_uses:
        if u["name"] in EDIT_TOOLS and u["file"]:
            rel = signals.rel_path(cwd, u["file"])
            if rel not in edited:
                edited.append(rel)

    # openspec-gate (heuristic) -----------------------------------------
    source_edits = [p for p in edited if p != "external" and not p.startswith("openspec/")]
    last_edit_ts = ""
    for u in parsed.tool_uses:
        if u["name"] in EDIT_TOOLS and u["file"]:
            last_edit_ts = u.get("ts", "") or last_edit_ts
    if (
        len(source_edits) >= 2
        and not _touches_openspec_changes(parsed, cwd)
        and not _active_openspec_exists(cwd)
    ):
        rec("violation", "openspec-gate", "openspec-gate", "heuristic", {
            "files": source_edits[:20],
            "count": len(source_edits),
        }, at=last_edit_ts)

    # build-retry -------------------------------------------------------
    runs: Counter = Counter()
    errors: Counter = Counter()
    program_of: dict[str, str] = {}
    last_run_ts: dict[str, str] = {}
    for u in parsed.tool_uses:
        if u["name"] in SHELL_TOOLS and u["command"]:
            program, digest = signals.command_identity(u["command"])
            if not digest:
                continue
            runs[digest] += 1
            program_of[digest] = program
            last_run_ts[digest] = u.get("ts", "") or last_run_ts.get(digest, "")
            if parsed.results.get(u["id"]):
                errors[digest] += 1
    for digest, count in runs.items():
        if count >= 3 and errors[digest] >= 2:
            rec("event", "none", "build-retry", "deterministic", {
                "program": program_of[digest], "hash": digest,
                "runs": count, "errors": errors[digest],
            }, at=last_run_ts.get(digest, ""))

    # user-correction (heuristic) ----------------------------------------
    # A violation, not a bare event: the analyzer clusters per rule, so a
    # correction recorded against rule "none" could never reach a proposal.
    # Heuristic confidence still means it needs the higher thresholds.
    for c in parsed.corrections:
        rec("violation", "user-correction", "user-correction", "heuristic", c,
            at=str(c.get("_ts") or ""))

    # defect -------------------------------------------------------------
    # Git is the only place a shipped bug is visible: a fix landing on a file
    # a recent non-fix commit touched. Absent git, absent repo or any failure
    # means no signal, never a failed capture.
    lookback = DEFECT_LOOKBACK_DAYS_DEFAULT
    if rules:
        raw = (rules.get("thresholds") or {}).get("defect_lookback_days")
        if isinstance(raw, int) and raw > 0:
            lookback = raw
    for evidence in detect_defects(cwd, parsed, lookback):
        rec("violation", "defect", "defect", "deterministic", evidence)

    # new-dependency ----------------------------------------------------
    for u in parsed.tool_uses:
        if u["name"] in SHELL_TOOLS and u["command"] and _dep_command(u["command"]):
            program, _ = signals.command_identity(u["command"])
            rec("violation", "no-new-deps", "new-dependency", "deterministic", {
                "program": program, "manifest": "", "via": "command",
            }, at=u.get("ts", ""))
        elif u["name"] in EDIT_TOOLS and u["file"]:
            name = Path(str(u["file"])).name
            if name in DEP_MANIFESTS:
                rec("violation", "no-new-deps", "new-dependency", "deterministic", {
                    "program": "", "manifest": signals.rel_path(cwd, u["file"]), "via": "edit",
                }, at=u.get("ts", ""))

    # session summary ---------------------------------------------------
    tools_used = Counter(u["name"] for u in parsed.tool_uses if u["name"])
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    for entry in parsed.usage_by_message.values():
        for key in usage:
            usage[key] += entry.get(key, 0)
    skills = sorted({u["skill"][:60] for u in parsed.tool_uses if u["skill"]})
    rec("session", "none", "session", "deterministic", {
        "message_count": parsed.message_count,
        "tools_used": dict(tools_used.most_common(40)),
        "tool_calls_total": len(parsed.tool_uses),
        "edited_files": len(edited),
        "skills_invoked": skills,
        "graph_db_present": graph_db_present,
        "started": parsed.started,
        "ended": parsed.ended,
        "usage": usage,
        "source_bytes": parsed.source_bytes,
    })
    return records


# ---------------------------------------------------------------------------
# Capture orchestration
# ---------------------------------------------------------------------------

def _patterns(rules: dict | None) -> list[dict]:
    if rules and isinstance(rules.get("correction_patterns"), list):
        return rules["correction_patterns"]
    return DEFAULT_CORRECTION_PATTERNS


def capture_one(path: Path, cwd: Path, rules: dict | None, known: dict[str, int],
                force: bool = False) -> str:
    """Returns 'captured', 'skipped', or 'failed'."""
    parsed = parse_transcript(path, _patterns(rules))
    if parsed is None or parsed.message_count == 0:
        return "failed"
    sid = signals.safe_session_id(parsed.session_id)
    if not force and known.get(sid) == parsed.message_count:
        return "skipped"
    records = detect(parsed, cwd, rules)
    if not signals.replace_session(cwd, sid, records):
        return "failed"
    known[sid] = parsed.message_count
    return "captured"


def backfill(directory: Path, cwd: Path, budget_seconds: float | None = None,
             max_files: int | None = None, skip_stem: str = "",
             force: bool = False) -> tuple[int, int, int]:
    """Capture every *.jsonl in directory, newest first.

    Newest first because the catch-up exists for recently killed sessions.
    Transcripts whose size matches the recorded source_bytes are skipped
    without being opened, and only parsed files count toward max_files, so
    a directory with hundreds of old transcripts never starves the new one.
    """
    rules = signals.load_rules(cwd)
    known = signals.known_sessions(cwd)
    sizes = signals.known_sources(cwd)
    captured = skipped = failed = 0
    started = time.monotonic()
    try:
        files = sorted(
            (p for p in directory.iterdir() if p.is_file() and p.suffix == ".jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return 0, 0, 0
    parsed_files = 0
    for path in files:
        if skip_stem and path.stem == skip_stem:
            continue
        if not force:
            try:
                sid = signals.safe_session_id(path.stem)
                if sid in sizes and sizes[sid] == path.stat().st_size:
                    skipped += 1
                    continue
            except OSError:
                continue
        if max_files is not None and parsed_files >= max_files:
            break
        if budget_seconds is not None and time.monotonic() - started > budget_seconds:
            break
        parsed_files += 1
        result = capture_one(path, cwd, rules, known, force=force)
        if result == "captured":
            captured += 1
        elif result == "skipped":
            skipped += 1
        else:
            failed += 1
    return captured, skipped, failed


def _hook(payload: dict) -> int:
    if should_skip(payload, __file__):
        return 0
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    event = str(payload.get("hook_event_name") or "")
    transcript = payload.get("transcript_path")
    rules = signals.load_rules(cwd)

    if event == "SessionEnd":
        # Retro disabled (no registry) means no capture at all. The user
        # said no at init; the opt-out has to mean something.
        if transcript and rules is not None:
            capture_one(Path(transcript), cwd, rules, signals.known_sessions(cwd))
        return 0

    if event == "SessionStart":
        source = str(payload.get("source") or "")
        if transcript and rules is not None:
            tpath = Path(transcript)
            if source in CATCHUP_SOURCES:
                backfill(
                    tpath.parent, cwd,
                    budget_seconds=CATCHUP_BUDGET_SECONDS,
                    max_files=CATCHUP_MAX_FILES,
                    skip_stem=tpath.stem,
                )
            elif source in SELF_CAPTURE_SOURCES:
                # A session that runs for a day compacts repeatedly and
                # reaches SessionEnd late or never. Capture it as it stands:
                # capture_one skips an unchanged message count and
                # replace_session swaps this session's records atomically.
                capture_one(tpath, cwd, rules, signals.known_sessions(cwd))
        line = signals.status_line(cwd)
        if line:
            # Plain stdout from SessionStart reaches the model and nobody else,
            # so the line has to travel as structured output: `systemMessage`
            # for the terminal, `additionalContext` for the model. The
            # alternative, exit 2 with stderr, does reach the user but Claude
            # Code labels it "hook error", and a nudge that looks like a
            # failure trains people to ignore it.
            #
            # It always prints, including "nothing over threshold". Silence is
            # indistinguishable from broken: a user who sees nothing cannot
            # tell a healthy project from a hook that never ran, and goes
            # looking for a fault that isn't there. The code-graph line next
            # to it prints every session for the same reason. One short line
            # is a heartbeat, not noise.
            print(json.dumps({
                "systemMessage": line,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": line,
                },
            }))
        return 0

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--backfill", metavar="DIR", help="capture every *.jsonl in DIR")
    parser.add_argument("--cwd", metavar="PROJECT", help="project root (default: current dir)")
    parser.add_argument("--force", action="store_true",
                        help="re-capture sessions already present (after detector changes)")
    parser.add_argument("--plugin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if signals is None:
        if args.backfill:
            print("backfill: Retro is not installed here (.github/retro/_coograph_signals.py missing)",
                  file=sys.stderr)
            return 2
        return 0

    if args.backfill:
        cwd = Path(args.cwd or os.getcwd())
        directory = Path(args.backfill)
        if not directory.is_dir():
            print(f"backfill: not a directory: {directory}", file=sys.stderr)
            return 2
        captured, skipped, failed = backfill(directory, cwd, force=args.force)
        print(f"captured {captured} sessions, skipped {skipped} (already present), failed {failed}")
        return 0

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        payload = {}
    try:
        return _hook(payload if isinstance(payload, dict) else {})
    except Exception:  # a hook must never fail the session
        return 0


if __name__ == "__main__":
    sys.exit(main())
