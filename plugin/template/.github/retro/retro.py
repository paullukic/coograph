#!/usr/bin/env python3
"""retro: the deterministic half of Coograph Retro.

Reads .coograph/signals.jsonl (written by the Claude Code hooks), the rule
registry at .github/retro/rules.json, and the archived OpenSpec changes, and
produces a report the /coograph-retro skill turns into proposals.

    python3 .github/retro/retro.py --report            write .coograph/retro/report.{json,md}
    python3 .github/retro/retro.py --status            one line + exit code for the archive prompt
    python3 .github/retro/retro.py --validate          check rules.json, exit 2 on the failing field
    python3 .github/retro/retro.py --merge-seed [PATH] add seeded rules missing from rules.json
                                                       (default seed: rules.seed.json next to this file)
    python3 .github/retro/retro.py --mark-retro SID    record that a retro ran in session SID

No LLM in here. Judgment lives in the skill, where the user can argue with
it. Stdlib only, same as the hooks.

Exit codes for --status:
    0  enough sessions since the last retro to run one
    3  not yet (or no signals, or Retro not enabled)
    4  Retro not enabled here, but enough archived changes to bootstrap
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
# rules.seed.json is refreshed by sync and the plugin; rules.json is the
# project's live registry and is never overwritten. Seeding copies one to
# the other; merging adds rules the live file lacks.
DEFAULT_SEED = SCRIPT_DIR / "rules.seed.json"

INSTRUCTION_FILES = ["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"]
REVIEW_SKILLS = {"coograph-review", "coograph-verify", "coograph:coograph-review", "coograph:coograph-verify"}
BACKTICK_PATH_RE = re.compile(r"`([^`\s]+)`")
PATH_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".cs", ".swift", ".dart", ".vue", ".svelte", ".json",
    ".yaml", ".yml", ".toml", ".md", ".sh", ".css", ".scss", ".sql", ".astro", ".mdx",
}


# ---------------------------------------------------------------------------
# Locate the shared signals module (lives next to the Claude Code hooks)
# ---------------------------------------------------------------------------

def _import_signals(cwd: Path):
    # The canonical module lives next to this script. The other entries are
    # fallbacks for a checkout where only the hook shim was copied.
    candidates = [
        SCRIPT_DIR,
        cwd / ".github" / "retro",
        cwd / ".claude" / "hooks",
    ]
    for directory in candidates:
        if (directory / "_coograph_signals.py").is_file():
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
            try:
                import _coograph_signals  # type: ignore
                return _coograph_signals
            except ImportError:
                continue
    return None


# ---------------------------------------------------------------------------
# Archive statistics (works without any captured signals)
# ---------------------------------------------------------------------------

def _looks_like_path(token: str) -> bool:
    token = token.strip()
    if token.startswith("./"):
        token = token[2:]
    if not token or token.startswith(("http://", "https://", "-", "$", "<", "..")):
        return False
    if "/" in token:
        return True
    return Path(token).suffix.lower() in PATH_SUFFIXES


def archive_stats(cwd: Path) -> dict:
    archive = cwd / "openspec" / "changes" / "archive"
    changes: list[dict] = []
    paths: Counter = Counter()
    try:
        dirs = sorted(p for p in archive.iterdir() if p.is_dir())
    except OSError:
        dirs = []
    for d in dirs:
        tasks = d / "tasks.md"
        done = todo = 0
        review_fixes = False
        try:
            text = tasks.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("- [x]"):
                done += 1
            elif stripped.startswith("- [ ]"):
                todo += 1
            if line.lstrip().startswith("#") and "review fixes" in stripped:
                review_fixes = True
        seen_here: set[str] = set()
        for m in BACKTICK_PATH_RE.finditer(text):
            token = m.group(1).strip()
            if token.startswith("./"):
                token = token[2:]
            if _looks_like_path(token) and token not in seen_here:
                seen_here.add(token)
                paths[token] += 1
        changes.append({
            "name": d.name, "tasks_done": done, "tasks_todo": todo,
            "review_fixes": review_fixes,
        })
    n = len(changes)
    total_tasks = sum(c["tasks_done"] + c["tasks_todo"] for c in changes)
    return {
        "archived_changes": n,
        "mean_tasks_per_change": round(total_tasks / n, 1) if n else 0.0,
        "review_fixes_share": round(sum(1 for c in changes if c["review_fixes"]) / n, 2) if n else 0.0,
        "incomplete_share": round(sum(1 for c in changes if c["tasks_todo"]) / n, 2) if n else 0.0,
        "most_referenced_paths": [
            {"path": p, "changes": c} for p, c in paths.most_common(10)
        ],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _approx_tokens(path: Path) -> int:
    try:
        return path.stat().st_size // 4
    except OSError:
        return 0


def instruction_tokens(cwd: Path) -> tuple[list[dict], int]:
    files = [cwd / f for f in INSTRUCTION_FILES]
    files += sorted((cwd / ".github" / "instructions").glob("*.md"))
    rows = []
    total = 0
    for f in files:
        if f.exists():
            n = _approx_tokens(f)
            total += n
            rows.append({"file": f.relative_to(cwd).as_posix(), "approx_tokens": n})
    return rows, total


def _session_map(records: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in records:
        if r.get("kind") == "session":
            out[str(r["session_id"])] = r.get("evidence") or {}
    return out


def _rate_split(records: list[dict], sessions: dict[str, dict], rule_id: str, date: str) -> dict | None:
    before = {sid for sid, ev in sessions.items() if str(ev.get("started", ""))[:10] < date}
    after = {sid for sid, ev in sessions.items() if str(ev.get("started", ""))[:10] >= date}
    if not before or not after:
        return None
    hits = [r for r in records if r.get("kind") == "violation" and r.get("rule") == rule_id]
    ev_before = sum(1 for r in hits if r.get("session_id") in before)
    ev_after = sum(1 for r in hits if r.get("session_id") in after)
    return {
        "rate_before": round(ev_before / len(before), 3),
        "rate_after": round(ev_after / len(after), 3),
        "sessions_before": len(before),
        "sessions_after": len(after),
    }


def _path_clusters(records: list[dict]) -> list[dict]:
    counts: dict[tuple[str, str], set] = defaultdict(set)
    events: Counter = Counter()
    for r in records:
        if r.get("kind") != "violation":
            continue
        ev = r.get("evidence") or {}
        rule = r.get("rule")
        paths: list[str] = []
        if r.get("detector") == "scope-warning" and ev.get("path"):
            paths = [str(ev["path"])]
        elif r.get("detector") in ("openspec-gate", "defect"):
            paths = [str(p) for p in ev.get("files") or []]
        for p in paths:
            if p == "external":
                continue
            parts = p.split("/")[:-1][:3]
            if not parts:
                continue
            prefix = "/".join(parts) + "/"
            key = (prefix, str(rule))
            counts[key].add(r.get("session_id"))
            events[key] += 1
    rows = [
        {"pattern": k[0], "rule": k[1], "events": events[k], "sessions": len(v)}
        for k, v in counts.items()
    ]
    rows.sort(key=lambda x: (-x["events"], x["pattern"]))
    return rows[:10]


def _build_retry(records: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for r in records:
        if r.get("detector") != "build-retry":
            continue
        ev = r.get("evidence") or {}
        key = str(ev.get("hash"))
        row = agg.setdefault(key, {
            "program": ev.get("program", ""), "hash": key, "runs": 0, "errors": 0, "sessions": set(),
        })
        row["runs"] += int(ev.get("runs", 0))
        row["errors"] += int(ev.get("errors", 0))
        row["sessions"].add(r.get("session_id"))
    rows = [{**v, "sessions": len(v["sessions"])} for v in agg.values()]
    rows.sort(key=lambda x: (-x["errors"], -x["runs"]))
    return rows[:10]


def _tokens(sessions: dict[str, dict], last_changed: str | None) -> dict:
    with_usage = {sid: ev for sid, ev in sessions.items() if isinstance(ev.get("usage"), dict)}
    keys = ["input", "output", "cache_read", "cache_create"]

    def mean(subset: dict[str, dict]) -> dict:
        n = len(subset)
        out = {k: 0 for k in keys}
        if not n:
            return {**out, "total": 0}
        for ev in subset.values():
            for k in keys:
                out[k] += int(ev["usage"].get(k, 0))
        out = {k: round(v / n) for k, v in out.items()}
        out["total"] = sum(out.values())
        return out

    before_after = None
    if last_changed:
        before = {s: e for s, e in with_usage.items() if str(e.get("started", ""))[:10] < last_changed}
        after = {s: e for s, e in with_usage.items() if str(e.get("started", ""))[:10] >= last_changed}
        if before and after:
            before_after = {
                "rate_before": mean(before)["total"],
                "rate_after": mean(after)["total"],
                "sessions_before": len(before),
                "sessions_after": len(after),
                "since": last_changed,
            }
    return {
        "sessions_with_usage": len(with_usage),
        "mean_per_session": mean(with_usage),
        "before_after": before_after,
    }


def _adherence(sessions: dict[str, dict]) -> dict:
    editing = {s: e for s, e in sessions.items() if int(e.get("edited_files", 0) or 0) >= 1}
    reviewed = sum(
        1 for e in editing.values()
        if any(str(s) in REVIEW_SKILLS or str(s).endswith("coograph-review") or str(s).endswith("coograph-verify")
               for s in e.get("skills_invoked") or [])
    )
    n = len(editing)
    return {
        "editing_sessions": n,
        "reviewed_sessions": reviewed,
        "rate": round(reviewed / n, 2) if n else 0.0,
    }


def build_report(cwd: Path, sig, rules: dict, records: list[dict]) -> dict:
    summary = sig.summarize(records, rules)
    sessions = _session_map(records)
    starts = sorted(str(e.get("started", "")) for e in sessions.values() if e.get("started"))
    per_rule = []
    by_id = {r["id"]: r for r in rules["rules"]}
    latest_change: str | None = None
    for entry in summary["per_rule"]:
        rule = by_id[entry["id"]]
        lc = rule.get("last_changed")
        entry = dict(entry)
        entry["before_after"] = _rate_split(records, sessions, entry["id"], lc) if lc else None
        entry["detector"] = rule.get("detector")
        entry["source"] = rule.get("source")
        entry["title"] = rule.get("title", "")
        per_rule.append(entry)
        if lc and (latest_change is None or lc > latest_change):
            latest_change = lc
    rows, total = instruction_tokens(cwd)
    budget = int(rules["thresholds"]["instruction_token_budget"])
    heuristics = Counter(r.get("detector") for r in records if r.get("kind") == "event")
    return {
        "generated": sig.now_iso(),
        "window": {
            "sessions": summary["total_sessions"],
            "episodes": summary["total_episodes"],
            "since_last_retro": summary["since_last_retro"],
            "first": starts[0] if starts else None,
            "last": starts[-1] if starts else None,
        },
        "thresholds": rules["thresholds"],
        "per_rule": per_rule,
        "over_threshold": [e["id"] for e in summary["over_threshold"]],
        "supporting_only": [e["id"] for e in per_rule if e["status"] == "supporting_only"],
        "prune_candidates": [e["id"] for e in per_rule if e["status"] == "prune_candidate"],
        "unmeasured_rules": [e["id"] for e in per_rule if e["status"] == "no_detector"],
        "path_clusters": _path_clusters(records),
        "build_retry": _build_retry(records),
        "user_corrections": int(heuristics.get("user-correction", 0)),
        "instruction_tokens": rows,
        "instruction_tokens_total": total,
        "instruction_token_budget": budget,
        "over_budget": total > budget,
        "tokens": _tokens(sessions, latest_change),
        "workflow_adherence": _adherence(sessions),
        "archive_stats": archive_stats(cwd),
    }


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def render_markdown(report: dict) -> str:
    w = report["window"]
    n = w["sessions"]
    over = report["over_threshold"]
    lines: list[str] = ["# Retro report", ""]

    # Plain-language opener, at most four sentences.
    opener: list[str] = []
    if n == 0:
        opener.append("No sessions captured yet.")
    elif over:
        opener.append(f"{n} sessions observed; {len(over)} rules over threshold ({', '.join(over)}).")
    else:
        opener.append(f"{n} sessions observed; thresholds not met for any rule.")
    worst = max(report["per_rule"], key=lambda e: e["events"], default=None)
    if worst and worst["events"]:
        opener.append(
            f"The rule broken most often is {worst['id']}: {_plural(worst['events'], 'event')} across "
            f"{_plural(worst['sessions'], 'session')}, currently enforced as {worst['enforcement']}."
        )
    elif n:
        opener.append("No rule violations were recorded.")
    tok = report["tokens"]
    if tok["sessions_with_usage"]:
        mean = tok["mean_per_session"]
        opener.append(
            f"Sessions average {_fmt_int(mean['output'])} output tokens and "
            f"{_fmt_int(mean['cache_read'] + mean['input'] + mean['cache_create'])} context tokens "
            f"read back into the model across the session."
        )
        ba = tok.get("before_after")
        if ba:
            direction = "down" if ba["rate_after"] < ba["rate_before"] else "up"
            opener.append(
                f"Since the last rule change on {ba['since']}, tokens per session went {direction} "
                f"from {_fmt_int(ba['rate_before'])} to {_fmt_int(ba['rate_after'])}."
            )
    lines.append(" ".join(opener[:4]))
    lines.append("")

    lines += ["## Window", "",
              f"- Sessions captured: {n}",
              f"- Episodes (session-days): {w.get('episodes', '?')}",
              f"- Episodes since last retro: {w['since_last_retro']}",
              f"- First: {w['first'] or 'n/a'}",
              f"- Last: {w['last'] or 'n/a'}", ""]

    lines += ["## Rules", "",
              "| rule | enforcement | events | episodes | sessions | status | escalate to | before / after (events per session) |",
              "|---|---|---|---|---|---|---|---|"]
    for e in report["per_rule"]:
        ba = e.get("before_after")
        ba_txt = f"{ba['rate_before']} / {ba['rate_after']}" if ba else ""
        lines.append(
            f"| {e['id']} | {e['enforcement']}{' (hard)' if e['hard'] else ''} | {e['events']} | "
            f"{e.get('episodes', e['sessions'])} | {e['sessions']} | {e['status']} | "
            f"{e.get('escalate_to') or ''} | {ba_txt} |"
        )
    lines.append("")

    if report["path_clusters"]:
        lines += ["## Path clusters", "", "| pattern | rule | events | sessions |", "|---|---|---|---|"]
        for c in report["path_clusters"]:
            lines.append(f"| {c['pattern']} | {c['rule']} | {c['events']} | {c['sessions']} |")
        lines.append("")

    if report["build_retry"]:
        lines += ["## Build retries", "", "| program | hash | runs | errors | sessions |", "|---|---|---|---|---|"]
        for b in report["build_retry"]:
            lines.append(f"| {b['program']} | {b['hash']} | {b['runs']} | {b['errors']} | {b['sessions']} |")
        lines.append("")

    lines += ["## Tokens", "",
              f"- Sessions with usage: {tok['sessions_with_usage']}",
              f"- Mean per session: {_fmt_int(tok['mean_per_session']['total'])} total, "
              f"{_fmt_int(tok['mean_per_session']['input'])} input, "
              f"{_fmt_int(tok['mean_per_session']['output'])} output, "
              f"{_fmt_int(tok['mean_per_session']['cache_read'])} cache read, "
              f"{_fmt_int(tok['mean_per_session']['cache_create'])} cache create"]
    if tok.get("before_after"):
        ba = tok["before_after"]
        lines.append(
            f"- Before / after {ba['since']}: {_fmt_int(ba['rate_before'])} / {_fmt_int(ba['rate_after'])} "
            f"({ba['sessions_before']} / {ba['sessions_after']} sessions)"
        )
    lines.append("")

    adh = report["workflow_adherence"]
    lines += ["## Workflow adherence", "",
              f"- Editing sessions: {adh['editing_sessions']}",
              f"- Of those, reviewed or verified with a coograph skill: {adh['reviewed_sessions']} "
              f"({int(adh['rate'] * 100)}%)",
              f"- User corrections detected (heuristic, supporting only): {report['user_corrections']}", ""]

    lines += ["## Instruction files", "",
              f"- Total approx tokens: {_fmt_int(report['instruction_tokens_total'])} "
              f"(budget {_fmt_int(report['instruction_token_budget'])}, "
              f"{'OVER' if report['over_budget'] else 'within'} budget)"]
    for row in report["instruction_tokens"]:
        lines.append(f"- {row['file']}: {_fmt_int(row['approx_tokens'])}")
    lines.append("")

    a = report["archive_stats"]
    lines += ["## Archived changes", "",
              f"- Archived changes: {a['archived_changes']}",
              f"- Mean tasks per change: {a['mean_tasks_per_change']}",
              f"- Share with a Review Fixes section: {int(a['review_fixes_share'] * 100)}%",
              f"- Share archived with unchecked tasks: {int(a['incomplete_share'] * 100)}%"]
    if a["most_referenced_paths"]:
        lines.append("- Most referenced paths:")
        for p in a["most_referenced_paths"]:
            lines.append(f"  - {p['path']} ({p['changes']} changes)")
    lines.append("")

    if report["unmeasured_rules"]:
        lines += ["## Unmeasured rules", "",
                  "No detector exists for: " + ", ".join(report["unmeasured_rules"]) + ".", ""]
    if report["prune_candidates"]:
        lines += ["## Prune candidates", "",
                  "Prose rules with zero events over the prune window: "
                  + ", ".join(report["prune_candidates"]) + ".", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_validate(cwd: Path, sig) -> int:
    path = cwd / sig.RULES_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        print(f"retro: rules.json not found at {path}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"retro: rules.json is not valid JSON: {e}", file=sys.stderr)
        return 2
    field = sig.validate_rules(data)
    if field:
        print(f"retro: rules.json invalid at {field}", file=sys.stderr)
        return 2
    print("retro: rules.json valid")
    return 0


def merge_seed(target: Path, seed_path: Path) -> tuple[int, list[str]]:
    """Returns (exit code, added rule ids). Creates target from seed if absent.

    Raises ValueError with a readable message when either file is not JSON,
    so the caller can print one line instead of a traceback.
    """
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ValueError(f"seed {seed_path} is not valid JSON: {e}") from e
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
        return 0, [r["id"] for r in seed.get("rules", [])]
    try:
        current = json.loads(target.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ValueError(f"{target} is not valid JSON, fix or delete it: {e}") from e
    have = {r["id"] for r in current.get("rules", []) if isinstance(r, dict)}
    added: list[str] = []
    for rule in seed.get("rules", []):
        if rule["id"] not in have:
            current.setdefault("rules", []).append(rule)
            added.append(rule["id"])
    # New threshold keys are added with seed defaults; existing values stay.
    for key, value in (seed.get("thresholds") or {}).items():
        current.setdefault("thresholds", {}).setdefault(key, value)
    for key, value in (seed.get("retention") or {}).items():
        current.setdefault("retention", {}).setdefault(key, value)
    current.setdefault("correction_patterns", seed.get("correction_patterns", []))
    current.setdefault("last_retro", None)
    current.setdefault("version", seed.get("version", 1))
    current["seed_version"] = int(seed.get("seed_version", 1))
    target.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return 0, added


def mark_retro(cwd: Path, sig, session_id: str) -> int:
    """Record that a retro ran: last_retro = {date, session_id, captured_sessions}.

    date is ISO-8601 UTC so it compares against transcript timestamps
    (also UTC). session_id anchors the count when its session record exists.
    """
    path = cwd / sig.RULES_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print(f"retro: cannot read rules.json: {e}", file=sys.stderr)
        return 2
    if sig.validate_rules(data) is not None:
        print("retro: rules.json invalid; run --validate", file=sys.stderr)
        return 2
    records = sig.load(cwd)
    captured = sum(1 for r in records if r.get("kind") == "session")
    from datetime import datetime, timezone
    data["last_retro"] = {
        "date": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "session_id": sig.safe_session_id(session_id),
        "captured_sessions": captured,
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"retro: marked retro in session {data['last_retro']['session_id']} at {data['last_retro']['date']} "
          f"({captured} sessions captured)")
    return 0


def cmd_status(cwd: Path, sig) -> int:
    rules = sig.load_rules(cwd)
    if rules is None:
        archives = sig.archived_changes(cwd)
        minimum = sig.DEFAULT_BOOTSTRAP_MIN_ARCHIVES
        if archives >= minimum:
            print(f"retro: not enabled; {archives} archived changes found, bootstrap available")
            return 4
        print("retro: not enabled")
        return 3
    records = sig.load(cwd)
    if not any(r.get("kind") == "session" for r in records):
        print("retro: no signals captured")
        return 3
    summary = sig.summarize(records, rules)
    n = summary["since_last_retro"]
    m = int(rules["thresholds"]["retro_prompt_min_sessions"])
    last = rules.get("last_retro")
    when = last["date"] if last else "never"
    print(f"retro: {n} episodes since last retro ({when}); threshold {m}")
    return 0 if n >= m else 3


def cmd_report(cwd: Path, sig) -> int:
    rules = sig.load_rules(cwd)
    if rules is None:
        print("retro: rules.json missing or invalid; run --validate or --merge-seed", file=sys.stderr)
        return 2
    records = sig.load(cwd)
    report = build_report(cwd, sig, rules, records)
    out_dir = cwd / ".coograph" / "retro"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = render_markdown(report)
    (out_dir / "report.md").write_text(md + "\n", encoding="utf-8")
    print(md.split("\n", 2)[2].split("\n", 1)[0])  # the opener paragraph
    print(f"report: {(out_dir / 'report.md').as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coograph Retro analyzer")
    parser.add_argument("--cwd", metavar="PROJECT", help="project root (default: current dir)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--validate", action="store_true")
    group.add_argument("--merge-seed", metavar="SEED", nargs="?", const=str(DEFAULT_SEED))
    group.add_argument("--mark-retro", metavar="SESSION_ID")
    args = parser.parse_args(argv)

    cwd = Path(args.cwd or os.getcwd()).resolve()
    sig = _import_signals(cwd)
    if sig is None:
        print(
            "retro: .claude/hooks/_coograph_signals.py not found. Retro needs the Claude Code "
            "hooks installed by coograph-init.", file=sys.stderr,
        )
        return 2

    if args.validate:
        return cmd_validate(cwd, sig)
    if args.merge_seed is not None:
        seed = Path(args.merge_seed)
        if not seed.is_file():
            print(f"retro: seed not found: {seed}", file=sys.stderr)
            return 2
        target = cwd / sig.RULES_REL
        try:
            code, added = merge_seed(target, seed)
        except ValueError as e:
            print(f"retro: {e}", file=sys.stderr)
            return 2
        print(f"retro: registry {target.as_posix()} ({'added ' + ', '.join(added) if added else 'no new rules'})")
        return code
    if args.mark_retro:
        return mark_retro(cwd, sig, args.mark_retro)
    if args.status:
        return cmd_status(cwd, sig)
    return cmd_report(cwd, sig)


if __name__ == "__main__":
    sys.exit(main())
