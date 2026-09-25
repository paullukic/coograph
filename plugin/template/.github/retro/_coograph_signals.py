"""Shared signal store for Coograph Retro.

This is the one canonical copy, at .github/retro/_coograph_signals.py, so
the analyzer works in every project that has .github/retro/, whichever AI
tool the project was set up for. The Claude Code hooks reach it through a
thin shim at .claude/hooks/_coograph_signals.py that locates this file via
CLAUDE_PROJECT_DIR (plugin mode) or the hook's own project root.

Every Retro signal lives in one local, gitignored, append-mostly file:

  .coograph/signals.jsonl

One JSON object per line. Records are metadata only: tool names, counts,
rule ids, repo-relative paths, command hashes, timestamps. Never prompt
text, code, tool output, or full commands. That property is enforced here
through a per-detector evidence allow-list, and tested with a sentinel
transcript in .github/retro/tests/.

Writers:
  - .claude/hooks/capture-signals.py   (transcript-derived records, origin "transcript",
                                        including one "outcome" per hook decision)
  - .claude/hooks/warn-scope.py        (origin "hook": a "scope" violation and a decision)
  - .claude/hooks/block-generated.py   (origin "hook": a "generated-files" violation and a decision)
  - .claude/hooks/no-new-deps-warn.py  (origin "hook": decisions only)
  - .claude/hooks/defect-warn.py       (origin "hook": decisions only)
  - .claude/hooks/openspec-gate-warn.py (origin "hook": decisions only)

Record kinds: "session" (one per session), "violation" (rule-bound, the only
kind thresholds count), "event" (not rule-bound), "decision" (what a hook did
about one tool call), "outcome" (what the transcript shows happened after that
decision, joined by tool_use_id).

Readers:
  - .github/retro/retro.py             (analyzer, report, status)
  - capture-signals.py                 (session-start status line)

Not a hook itself. Imported by the scripts next to it. Every public function
fails closed on I/O errors: it returns False / None / empty and never raises
into a hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

SIGNALS_REL = Path(".coograph") / "signals.jsonl"
LOCK_REL = Path(".coograph") / "signals.lock"
RULES_REL = Path(".github") / "retro" / "rules.json"

LOCK_WAIT_SECONDS = 2.0
LOCK_STALE_SECONDS = 60
LOCK_POLL_SECONDS = 0.05
# Windows refuses a rename or a delete while another process (Defender, the
# search indexer) holds the file. The refusal is transient; a bounded retry is
# the difference between a lost session and a 25 ms delay. POSIX never refuses,
# so the loops exit on the first attempt there.
REPLACE_RETRIES = 20
REPLACE_RETRY_SECONDS = 0.025
UNLINK_RETRIES = 20
UNLINK_RETRY_SECONDS = 0.025
# An empty lock file is a released one (see _Lock); this grace only covers the
# microseconds between creating the file and writing the owner's pid into it.
LOCK_EMPTY_BREAK_SECONDS = 0.25
PATH_MAX_CHARS = 300
DEFAULT_MAX_SESSIONS = 500

TOOLS = {"claude-code", "codex", "opencode", "unknown"}
KINDS = {"session", "violation", "event", "decision", "outcome"}
DECISION_ACTIONS = {"warned", "blocked", "suppressed"}
ORIGINS = {"transcript", "hook"}
CONFIDENCES = {"deterministic", "heuristic"}
ENFORCEMENTS = {"prose", "hook-warn", "hook-block"}

# Evidence keys each detector may write. Anything else is dropped at emit
# time. This list is the privacy boundary: no key here can hold free text.
# ---------------------------------------------------------------------------
# Dependency detection
#
# One implementation, imported by both capture-signals.py (which records the
# violation) and no-new-deps-warn.py (which warns about it as it happens). Two
# hand-maintained copies of this rule drifted apart the first time they existed,
# so the hook now cannot disagree with the detector by construction.

DEP_PROGRAMS = {"npm", "pnpm", "yarn", "pip", "pip3", "uv", "cargo", "go", "composer", "bun"}
DEP_VERBS = {"install", "i", "add", "get", "require"}
DEP_FILE_FLAGS = {"-r", "--requirement", "--requirements", "-c", "--constraint"}
DEP_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml",
    "go.mod", "Cargo.toml", "composer.json", "Gemfile",
}


def dep_command(command: str) -> bool:
    """True for commands that add a dependency, not for ones that install
    what a manifest already lists (`pip install -r requirements.txt`,
    `pip install -e .`, `npm install`).

    Anchored on the first token, so a dependency command quoted inside another
    command -- `git commit -m "npm install x"` -- is not one.
    """
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


ALLOWED_EVIDENCE: dict[str, set[str]] = {
    "graph-first": {"count", "first_index", "tools", "proof"},
    "openspec-gate": {"files", "count"},
    "scope-warning": {"path", "openspec"},
    "generated-file-block": {"path", "reason"},
    "build-retry": {"program", "hash", "runs", "errors"},
    "user-correction": {"pattern", "after_tool"},
    "defect": {"fix", "origin", "files", "count", "days"},
    "new-dependency": {"program", "manifest", "via"},
    "decision": {"action", "tool_use_id", "hook", "path"},
    "outcome": {"tool_use_id", "action", "proceeded", "corrected", "reconciled", "repeated"},
    "session": {
        "message_count", "tools_used", "tool_calls_total", "edited_files",
        "skills_invoked", "graph_db_present", "started", "ended", "usage",
        "source_bytes",
    },
}

REQUIRED_THRESHOLDS = {
    "deterministic_events", "deterministic_sessions",
    "heuristic_events", "heuristic_sessions",
    "prune_sessions", "instruction_token_budget", "retro_prompt_min_sessions",
    "bootstrap_min_archives",
}
DEFAULT_BOOTSTRAP_MIN_ARCHIVES = 10
# A hook-warn rule climbs to hook-block only when this share of its outcomes
# were ignored (the rule fired again later and nothing reconciled it).
DEFAULT_ESCALATE_IGNORED_RATE = 0.5
HOLD_NO_OUTCOMES = "no_outcomes"
HOLD_WARNINGS_WORK = "warnings_change_behaviour"

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")
_WIN_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def safe_session_id(raw: object) -> str:
    cleaned = _SAFE_ID_RE.sub("", str(raw or ""))[:64]
    return cleaned or "unknown"


def rel_path(cwd: Path, raw: object) -> str:
    """Repo-relative POSIX path, or the literal 'external' when outside cwd.

    Absolute paths can carry usernames; they never reach the signals file.
    """
    if not raw:
        return "external"
    text = str(raw).strip()
    if not text:
        return "external"
    try:
        # A Windows drive or UNC path handled on a POSIX host (transcripts
        # copied between machines) is not "absolute" to pathlib there and
        # would resolve as a relative name inside cwd, leaking the username.
        # It can never be inside a POSIX project root, so it is external.
        if os.name != "nt" and _WIN_ABS_RE.match(text):
            return "external"
        if os.name != "nt":
            text = text.replace("\\", "/")
        candidate = Path(text)
        base = Path(cwd).resolve()
        # On Windows Path("/etc/passwd").is_absolute() is False; treat any
        # leading slash as absolute so it resolves against the drive root
        # and lands outside cwd. Relative paths resolve against cwd so that
        # "../up.ts" lands outside too.
        if candidate.is_absolute() or text.startswith(("/", "\\")):
            full = candidate.resolve()
        else:
            full = (base / candidate).resolve()
        rel = full.relative_to(base).as_posix()
        return rel[:PATH_MAX_CHARS] or "external"
    except (ValueError, OSError, RuntimeError):
        return "external"


def command_identity(command: object) -> tuple[str, str]:
    """(program, 12-char sha1) for a shell command. Program only, never args."""
    text = str(command or "").strip()
    if not text:
        return "", ""
    digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]
    first = text.split()[0] if text.split() else ""
    # "C:\\path\\python.exe" or "/usr/bin/npm" -> basename only.
    program = first.replace("\\", "/").rsplit("/", 1)[-1][:40]
    return program, digest


def make_record(
    *,
    tool: str,
    session_id: str,
    kind: str,
    rule: str,
    detector: str,
    confidence: str,
    evidence: dict,
    origin: str,
    ts: str | None = None,
) -> dict | None:
    """Build a schema-valid record or None. Drops evidence keys not allowed."""
    if kind not in KINDS or confidence not in CONFIDENCES or origin not in ORIGINS:
        return None
    allowed = ALLOWED_EVIDENCE.get(detector)
    if allowed is None:
        return None
    clean = {k: v for k, v in (evidence or {}).items() if k in allowed}
    return {
        "v": SCHEMA_VERSION,
        "ts": ts or now_iso(),
        "tool": tool if tool in TOOLS else "unknown",
        "session_id": safe_session_id(session_id),
        "kind": kind,
        "rule": rule or "none",
        "detector": detector,
        "confidence": confidence,
        "origin": origin,
        "evidence": clean,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def validate_rules(data: object) -> str | None:
    """Return the failing field name, or None when the registry is valid."""
    if not isinstance(data, dict):
        return "root"
    if not isinstance(data.get("version"), int):
        return "version"
    if not isinstance(data.get("seed_version"), int):
        return "seed_version"
    rules = data.get("rules")
    if not isinstance(rules, list):
        return "rules"
    seen: set[str] = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            return f"rules[{i}]"
        rid = rule.get("id")
        if not isinstance(rid, str) or not rid or rid in seen:
            return f"rules[{i}].id"
        seen.add(rid)
        if rule.get("enforcement") not in ENFORCEMENTS:
            return f"rules[{i}].enforcement"
        if not isinstance(rule.get("hard"), bool):
            return f"rules[{i}].hard"
        det = rule.get("detector")
        if det is not None and (not isinstance(det, str) or det not in ALLOWED_EVIDENCE):
            return f"rules[{i}].detector"
        source = rule.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("file"), str):
            return f"rules[{i}].source"
    thresholds = data.get("thresholds")
    if not isinstance(thresholds, dict):
        return "thresholds"
    for key in REQUIRED_THRESHOLDS:
        value = thresholds.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return f"thresholds.{key}"
    rate = thresholds.get("escalate_ignored_rate")
    if rate is not None and (
        isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 <= rate <= 1
    ):
        return "thresholds.escalate_ignored_rate"
    patterns = data.get("correction_patterns")
    if not isinstance(patterns, list):
        return "correction_patterns"
    for i, pat in enumerate(patterns):
        if not isinstance(pat, dict) or not isinstance(pat.get("id"), str):
            return f"correction_patterns[{i}].id"
        if not isinstance(pat.get("regex"), str):
            return f"correction_patterns[{i}].regex"
        if not isinstance(pat.get("enabled"), bool):
            return f"correction_patterns[{i}].enabled"
        try:
            re.compile(pat["regex"])
        except re.error:
            return f"correction_patterns[{i}].regex"
    retention = data.get("retention")
    if not isinstance(retention, dict):
        return "retention"
    max_sessions = retention.get("max_sessions")
    if not isinstance(max_sessions, int) or isinstance(max_sessions, bool) or max_sessions < 1:
        return "retention.max_sessions"
    prefixes = data.get("ignore_session_prefixes")
    if prefixes is not None:
        if not isinstance(prefixes, list) or any(not isinstance(p, str) or not p for p in prefixes):
            return "ignore_session_prefixes"
    last = data.get("last_retro")
    if last is not None:
        if not isinstance(last, dict) or not isinstance(last.get("date"), str):
            return "last_retro"
        if not isinstance(last.get("captured_sessions"), int):
            return "last_retro.captured_sessions"
    return None


def load_rules(cwd: Path) -> dict | None:
    """Validated registry, or None when absent or malformed (hooks go silent)."""
    path = Path(cwd) / RULES_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if validate_rules(data) is not None:
        return None
    return data


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def active_openspec_exists(cwd: Path) -> bool:
    """A change directory other than archive/ exists under openspec/changes/.

    Shared by the openspec-gate detector and openspec-gate-warn.py so the hook
    cannot disagree with the detector about what "an active change" means.
    """
    changes = Path(cwd) / "openspec" / "changes"
    try:
        return any(p.is_dir() and p.name != "archive" for p in changes.iterdir())
    except OSError:
        return False


def ignore_prefixes(rules: dict | None) -> tuple[str, ...]:
    raw = (rules or {}).get("ignore_session_prefixes")
    if not isinstance(raw, list):
        return ()
    return tuple(p for p in raw if isinstance(p, str) and p)


def ignored_session(session_id: object, rules: dict | None) -> bool:
    """True for sessions the registry says to leave out of every count.

    Verification probes started by the retro skill are real captured sessions
    whose only purpose is to trip a hook; counted, they escalate the rule they
    test.
    """
    sid = str(session_id or "")
    return any(sid.startswith(p) for p in ignore_prefixes(rules))


def drop_ignored(records: list[dict], rules: dict | None) -> list[dict]:
    return [r for r in records if not ignored_session(r.get("session_id"), rules)]


def escalate_ignored_rate(rules: dict | None) -> float:
    raw = ((rules or {}).get("thresholds") or {}).get("escalate_ignored_rate")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return DEFAULT_ESCALATE_IGNORED_RATE
    return float(raw)


def _os_replace(src: Path, dst: Path) -> None:
    os.replace(src, dst)


def _unlink(path: Path) -> None:
    path.unlink()


class _Lock:
    """Cross-process lock via O_CREAT|O_EXCL. Same shape as _coograph_guard.

    The lock file holds the owner's pid while held. A release that cannot
    delete the file (Windows sharing violation) truncates it to empty instead,
    and an empty lock is breakable after LOCK_EMPTY_BREAK_SECONDS; a non-empty
    one, left by a crashed process, only after LOCK_STALE_SECONDS.
    """

    def __init__(self, cwd: Path) -> None:
        self.path = Path(cwd) / LOCK_REL
        self.held = False

    def __enter__(self) -> "_Lock":
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                if self._breakable():
                    try:
                        _unlink(self.path)
                        continue
                    except OSError:
                        pass
                if time.monotonic() >= deadline:
                    return self
                time.sleep(LOCK_POLL_SECONDS)

    def _breakable(self) -> bool:
        try:
            st = self.path.stat()
        except OSError:
            return False
        age = time.time() - st.st_mtime
        if age > LOCK_STALE_SECONDS:
            return True
        return st.st_size == 0 and age > LOCK_EMPTY_BREAK_SECONDS

    def __exit__(self, *exc: object) -> None:
        if not self.held:
            return
        self.held = False
        for _ in range(UNLINK_RETRIES):
            try:
                _unlink(self.path)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(UNLINK_RETRY_SECONDS)
        # Released but not deletable: mark it so waiters break it soon.
        try:
            with self.path.open("w", encoding="utf-8"):
                pass
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _read_lines(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("session_id"):
                    records.append(obj)
    except OSError:
        return []
    return records


def load(cwd: Path) -> list[dict]:
    return _read_lines(Path(cwd) / SIGNALS_REL)


def known_sessions(cwd: Path) -> dict[str, int]:
    """{session_id: message_count} from session records."""
    out: dict[str, int] = {}
    for rec in load(cwd):
        if rec.get("kind") == "session":
            count = (rec.get("evidence") or {}).get("message_count")
            if isinstance(count, int):
                out[str(rec["session_id"])] = count
    return out


def known_sources(cwd: Path) -> dict[str, int]:
    """{session_id: source_bytes} from session records.

    Lets the SessionStart catch-up skip a transcript without parsing it:
    Claude Code names transcripts <session_id>.jsonl, so a file whose size
    still matches the recorded size has nothing new in it.
    """
    out: dict[str, int] = {}
    for rec in load(cwd):
        if rec.get("kind") == "session":
            size = (rec.get("evidence") or {}).get("source_bytes")
            if isinstance(size, int):
                out[str(rec["session_id"])] = size
    return out


def emit(cwd: Path, record: dict | None) -> bool:
    """Append one record. False on any failure; never raises."""
    if not record:
        return False
    path = Path(cwd) / SIGNALS_REL
    try:
        with _Lock(cwd) as lock:
            if not lock.held:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
        return True
    except OSError:
        return False


def emit_decision(cwd: Path, payload: dict, rule: str, action: str, hook: str,
                  path: str = "") -> bool:
    """Record what a hook decided about one tool call. Never raises.

    Every rule hook calls this at the moment it warns, blocks, or would have
    warned again in the same session ("suppressed"). The record is joined to
    the transcript by tool_use_id at capture time to learn what followed. It
    is never counted as a violation; thresholds read kind == "violation" only.
    """
    if action not in DECISION_ACTIONS:
        return False
    try:
        record = make_record(
            tool="claude-code",
            session_id=str(payload.get("session_id") or "unknown"),
            kind="decision",
            rule=rule,
            detector="decision",
            confidence="deterministic",
            origin="hook",
            evidence={
                "action": action,
                "tool_use_id": str(payload.get("tool_use_id") or "")[:64],
                "hook": Path(hook).name[:60],
                "path": rel_path(cwd, path) if path else "",
            },
        )
        return emit(Path(cwd), record)
    except Exception:
        return False


def replace_session(
    cwd: Path,
    session_id: str,
    records: list[dict],
    max_sessions: int | None = None,
) -> bool:
    """Replace the transcript-origin records of one session atomically.

    Hook-origin records for the same session are kept (they were emitted live
    and the transcript parser cannot reconstruct them). Applies retention:
    at most max_sessions sessions with a session record are kept, oldest
    dropped by their started timestamp.
    """
    session_id = safe_session_id(session_id)
    path = Path(cwd) / SIGNALS_REL
    clean = [r for r in (records or []) if r]
    if max_sessions is None:
        rules = load_rules(cwd)
        max_sessions = DEFAULT_MAX_SESSIONS
        if rules:
            max_sessions = int(rules["retention"]["max_sessions"])
    try:
        with _Lock(cwd) as lock:
            if not lock.held:
                return False
            existing = _read_lines(path)
            kept = [
                r for r in existing
                if not (r.get("session_id") == session_id and r.get("origin") == "transcript")
            ]
            merged = kept + clean

            # Retention: rank sessions that have a session record.
            starts: dict[str, str] = {}
            for rec in merged:
                if rec.get("kind") == "session":
                    ev = rec.get("evidence") or {}
                    starts[str(rec["session_id"])] = str(ev.get("started") or rec.get("ts") or "")
            if len(starts) > max_sessions:
                ordered = sorted(starts, key=lambda sid: starts[sid])
                drop = set(ordered[: len(starts) - max_sessions])
                merged = [r for r in merged if r.get("session_id") not in drop]

            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                with tmp.open("w", encoding="utf-8") as fh:
                    for rec in merged:
                        fh.write(json.dumps(rec, ensure_ascii=True, separators=(",", ":")) + "\n")
                if not _replace_with_retry(tmp, path):
                    return False
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        return True
    except OSError:
        return False


def _replace_with_retry(tmp: Path, path: Path) -> bool:
    for attempt in range(REPLACE_RETRIES):
        try:
            _os_replace(tmp, path)
            return True
        except OSError:
            if attempt + 1 < REPLACE_RETRIES:
                time.sleep(REPLACE_RETRY_SECONDS)
    return False


# ---------------------------------------------------------------------------
# Summary (shared by the status line and the analyzer)
# ---------------------------------------------------------------------------

def _started_of(session_rec: dict) -> str:
    return str((session_rec.get("evidence") or {}).get("started") or session_rec.get("ts") or "")


def episode_key(rec: dict) -> str:
    """The threshold unit: one session on one calendar day.

    A session id alone cannot carry a threshold. A user who works in long
    sessions produces one id per several days, so "3 sessions" is unreachable
    no matter how often a rule breaks; a user who restarts constantly crosses
    it on noise. The day is taken from the record's own timestamp, so the
    stored records never change and old signal files keep working.
    """
    sid = str(rec.get("session_id") or "")
    day = str(rec.get("ts") or "")[:10]
    return f"{sid}:{day}" if day else sid


def episodes_of(records: list[dict]) -> dict[str, str]:
    """Episode key -> the latest timestamp seen in that episode."""
    out: dict[str, str] = {}
    for r in records:
        key = episode_key(r)
        ts = str(r.get("ts") or "")
        if ts > out.get(key, ""):
            out[key] = ts
    return out


def episodes_since(episodes: dict[str, str], sessions: dict[str, dict],
                   last_retro: dict | None) -> int:
    """Episodes that happened after the last retro.

    Anchored like `sessions_since`, on the start of the session the retro ran
    in, falling back to the recorded date. Episodes are what makes this work
    inside a long session: the day the retro ran is not counted, and every
    later day of that same session is, so the counter advances instead of
    reading 0 until the session finally ends.
    """
    if not last_retro:
        return len(episodes)
    anchor = ""
    sid = str(last_retro.get("session_id") or "")
    if sid and sid in sessions:
        anchor = _started_of(sessions[sid])
    if not anchor:
        anchor = str(last_retro.get("date") or "")
    if not anchor:
        return len(episodes)
    return sum(1 for ts in episodes.values() if ts > anchor)


def sessions_since(sessions: dict[str, dict], last_retro: dict | None) -> int:
    """Sessions that started after the last retro.

    Anchored on a timestamp, never on a count: at the retention cap the
    session count stops growing, so a count difference would read 0 forever.
    The anchor is the start of the session the retro ran in when that record
    exists, else last_retro.date (ISO-8601 UTC, written by retro.py
    --mark-retro). Timestamps compare lexicographically; both are ISO.
    """
    if not last_retro:
        return len(sessions)
    anchor = ""
    sid = str(last_retro.get("session_id") or "")
    if sid and sid in sessions:
        anchor = _started_of(sessions[sid])
    if not anchor:
        anchor = str(last_retro.get("date") or "")
    if not anchor:
        return len(sessions)
    return sum(1 for rec in sessions.values() if _started_of(rec) > anchor)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def outcome_rates(outcomes: list[dict]) -> dict:
    """Rates over one rule's outcome records. All None when there are none.

    ignored: the rule fired again later in the session and nothing reconciled
    it. Built from deterministic fields only; corrected (heuristic patterns)
    is reported but never gates an escalation.
    """
    n = len(outcomes)
    if n == 0:
        return {"n": 0, "proceeded_rate": None, "corrected_rate": None,
                "reconciled_rate": None, "ignored_rate": None}
    evs = [o.get("evidence") or {} for o in outcomes]
    proceeded = sum(1 for e in evs if e.get("proceeded") is True)
    corrected = sum(1 for e in evs if e.get("corrected") is True)
    applicable = [e for e in evs if e.get("reconciled") is not None]
    reconciled = sum(1 for e in applicable if e.get("reconciled") is True)
    ignored = sum(1 for e in evs if _count(e.get("repeated")) > 0 and e.get("reconciled") is not True)
    return {
        "n": n,
        "proceeded_rate": round(proceeded / n, 2),
        "corrected_rate": round(corrected / n, 2),
        "reconciled_rate": round(reconciled / len(applicable), 2) if applicable else None,
        "ignored_rate": round(ignored / n, 2),
    }


def summarize(records: list[dict], rules: dict) -> dict:
    """Per-rule counts against thresholds. Pure; no I/O.

    Sessions matching ignore_session_prefixes are dropped first. Decisions and
    outcomes are summarised per rule but never counted as violations.
    """
    thresholds = rules["thresholds"]
    records = drop_ignored(records, rules)
    sessions = {
        str(r["session_id"]): r for r in records if r.get("kind") == "session"
    }
    total_sessions = len(sessions)
    episodes = episodes_of(records)
    total_episodes = len(episodes)
    # Thresholds count episodes; sessions stay in the report so a reader can
    # tell three short sessions from one long one.
    since_last_retro = episodes_since(episodes, sessions, rules.get("last_retro"))

    per_rule: list[dict] = []
    over: list[dict] = []
    for rule in rules["rules"]:
        rid = rule["id"]
        hits = [r for r in records if r.get("kind") == "violation" and r.get("rule") == rid]
        events = len(hits)
        rule_sessions = len({r.get("session_id") for r in hits})
        rule_episodes = len({episode_key(r) for r in hits})
        deterministic = any(r.get("confidence") == "deterministic" for r in hits)
        confidence = "deterministic" if deterministic or not hits else "heuristic"
        det_hits = [r for r in hits if r.get("confidence") == "deterministic"]
        det_events = len(det_hits)
        det_sessions = len({r.get("session_id") for r in det_hits})
        det_episodes = len({episode_key(r) for r in det_hits})
        decisions = [r for r in records if r.get("kind") == "decision" and r.get("rule") == rid]
        outcomes = [r for r in records if r.get("kind") == "outcome" and r.get("rule") == rid]
        decision_counts = {
            action: sum(1 for d in decisions if (d.get("evidence") or {}).get("action") == action)
            for action in ("warned", "blocked", "suppressed")
        }
        rates = outcome_rates(outcomes)

        if rule.get("detector") is None:
            status = "no_detector"
        elif (
            det_events >= thresholds["deterministic_events"]
            and det_episodes >= thresholds["deterministic_sessions"]
        ):
            status = "over_threshold"
        elif (
            events >= thresholds["heuristic_events"]
            and rule_episodes >= thresholds["heuristic_sessions"]
        ):
            status = "supporting_only"
        elif (
            events == 0
            and rule["enforcement"] == "prose"
            and not rule["hard"]
            and total_episodes >= thresholds["prune_sessions"]
        ):
            status = "prune_candidate"
        else:
            status = "below_threshold"

        entry = {
            "id": rid,
            "enforcement": rule["enforcement"],
            "hard": rule["hard"],
            "events": events,
            "sessions": rule_sessions,
            "episodes": rule_episodes,
            "confidence": confidence,
            "status": status,
            "decisions": decision_counts,
            "outcomes": rates,
        }
        if status == "over_threshold":
            rung = {
                "prose": "hook-warn",
                "hook-warn": "hook-block",
                "hook-block": None,
            }[rule["enforcement"]]
            # Warn becomes block on evidence that warning changed nothing, not
            # on the count alone. The count is what the hook's own presence
            # inflates; the ignored rate is what only a failing hook produces.
            if rung == "hook-block":
                if rates["n"] < thresholds["deterministic_events"]:
                    rung = None
                    entry["hold_reason"] = HOLD_NO_OUTCOMES
                elif rates["ignored_rate"] < escalate_ignored_rate(rules):
                    rung = None
                    entry["hold_reason"] = HOLD_WARNINGS_WORK
            entry["escalate_to"] = rung
            over.append(entry)
        per_rule.append(entry)

    over.sort(key=lambda e: (-e["events"], e["id"]))
    return {
        "total_sessions": total_sessions,
        "total_episodes": total_episodes,
        "since_last_retro": since_last_retro,
        "per_rule": per_rule,
        "over_threshold": over,
    }


def archived_changes(cwd: Path) -> int:
    """Number of archived OpenSpec change directories in this project."""
    archive = Path(cwd) / "openspec" / "changes" / "archive"
    try:
        return sum(1 for p in archive.iterdir() if p.is_dir())
    except OSError:
        return 0


def transcripts_dir_for(cwd: Path) -> Path | None:
    """Claude Code's transcript directory for a project, when it exists.

    Claude Code names it after the absolute project path with every
    character outside [A-Za-z0-9] replaced by '-'. Used only as a default
    for backfill; the user can always pass an explicit directory.
    """
    try:
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))
        candidate = Path.home() / ".claude" / "projects" / slug
        return candidate if candidate.is_dir() else None
    except (OSError, RuntimeError):
        return None


# The words that mean "there is something for you to do". The hook tests for
# this to decide whether the line is worth putting in front of the user.
CALL_TO_ACTION = "run /coograph-retro"


def status_line(cwd: Path) -> str | None:
    """One line for SessionStart, or None when there is nothing to say."""
    rules = load_rules(cwd)
    if rules is None:
        archives = archived_changes(cwd)
        if archives >= DEFAULT_BOOTSTRAP_MIN_ARCHIVES:
            return (
                f"[retro] not enabled, {archives} archived changes found, "
                f"{CALL_TO_ACTION} to bootstrap"
            )
        return None
    records = load(cwd)
    summary = summarize(records, rules)
    n = summary["total_sessions"]
    if n == 0:
        return "[retro] enabled, no sessions captured yet"
    over = summary["over_threshold"]
    if not over:
        return f"[retro] {n} sessions captured, nothing over threshold"
    top = over[0]
    call = f", {CALL_TO_ACTION}"
    head = f"[retro] {n} sessions captured, {len(over)} rules over threshold ({top['id']} {top['events']}x)"
    # Never truncate the call to action; shorten the rule part instead.
    return head[: 160 - len(call)] + call
