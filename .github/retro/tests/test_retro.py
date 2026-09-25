"""Tests for the analyzer CLI (retro.py): validate, merge-seed, status, report.

Run:  python -m unittest discover .github/retro/tests
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import SEED, Transcript, make_project, read_signals

import _coograph_signals as sig  # noqa: E402


def _run_retro(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / ".github" / "retro" / "retro.py"), "--cwd", str(root), *args],
        capture_output=True, text=True, env={**os.environ}, cwd=str(root),
    )


_DETECTOR = {"graph-first": "graph-first", "openspec-gate": "openspec-gate",
             "scope": "scope-warning", "no-new-deps": "new-dependency"}
_EVIDENCE = {
    "graph-first": {"count": 1, "first_index": 0, "tools": ["Grep"], "proof": "mcp-later"},
    "openspec-gate": {"files": ["src/api/a.ts", "src/api/b.ts"], "count": 2},
    "scope": {"path": "src/api/x.ts", "openspec": "s"},
    "no-new-deps": {"program": "npm", "manifest": "", "via": "command"},
}


def _session(root: Path, sid: str, started: str, *, edits: int = 0, review: bool = False,
             usage_total: int = 0, violations: int = 0, rule: str = "graph-first") -> None:
    """Write one synthetic session straight into the store."""
    recs = []
    for _ in range(violations):
        recs.append(sig.make_record(
            tool="claude-code", session_id=sid, kind="violation", rule=rule,
            detector=_DETECTOR[rule],
            confidence="heuristic" if rule == "openspec-gate" else "deterministic",
            evidence=_EVIDENCE[rule],
            origin="transcript", ts=started,
        ))
    recs.append(sig.make_record(
        tool="claude-code", session_id=sid, kind="session", rule="none", detector="session",
        confidence="deterministic", origin="transcript", ts=started,
        evidence={
            "message_count": 10, "tools_used": {"Edit": edits}, "tool_calls_total": edits,
            "edited_files": edits, "skills_invoked": ["coograph-review"] if review else [],
            "graph_db_present": True, "started": started, "ended": started,
            "usage": {"input": 0, "output": usage_total // 2, "cache_read": usage_total // 2, "cache_create": 0},
        },
    ))
    sig.replace_session(root, sid, recs)


def _outcomes(root: Path, sid: str, rule: str, *, repeated: list[int], reconciled: object = None) -> None:
    """One warned decision plus its outcome per entry in `repeated`. Call after _session:
    replace_session drops transcript-origin records, and outcomes are transcript-origin."""
    for i, count in enumerate(repeated):
        tid = f"{sid}-t{i}"
        sig.emit(root, sig.make_record(
            tool="claude-code", session_id=sid, kind="decision", rule=rule, detector="decision",
            confidence="deterministic", origin="hook",
            evidence={"action": "warned", "tool_use_id": tid, "hook": "x-warn.py", "path": ""},
        ))
        sig.emit(root, sig.make_record(
            tool="claude-code", session_id=sid, kind="outcome", rule=rule, detector="outcome",
            confidence="deterministic", origin="transcript",
            evidence={"tool_use_id": tid, "action": "warned", "proceeded": True,
                      "corrected": False, "reconciled": reconciled, "repeated": count},
        ))


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = make_project(self.base / "proj")
        self.rules_path = self.root / ".github" / "retro" / "rules.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_validate_ok_and_broken(self) -> None:
        self.assertEqual(_run_retro(self.root, "--validate").returncode, 0)
        data = json.loads(self.rules_path.read_text())
        data["rules"][0]["enforcement"] = "shout"
        self.rules_path.write_text(json.dumps(data))
        proc = _run_retro(self.root, "--validate")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("rules[0].enforcement", proc.stderr)

    def test_merge_seed_keeps_local_edits(self) -> None:
        data = json.loads(self.rules_path.read_text())
        for r in data["rules"]:
            if r["id"] == "no-new-deps":
                r["title"] = "LOCAL EDIT"
        data["thresholds"]["deterministic_events"] = 7
        self.rules_path.write_text(json.dumps(data))
        seed = json.loads(SEED.read_text(encoding="utf-8-sig"))
        seed["seed_version"] = 2
        seed["rules"].append({
            "id": "secrets-in-logs", "title": "x", "source": {"file": "CLAUDE.md", "anchor": "Security"},
            "enforcement": "prose", "hard": False, "detector": None,
            "added": "2026-09-19", "last_triggered": None, "last_changed": None,
        })
        seed_path = self.base / "seed.json"
        seed_path.write_text(json.dumps(seed))
        proc = _run_retro(self.root, "--merge-seed", str(seed_path))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = json.loads(self.rules_path.read_text())
        ids = [r["id"] for r in merged["rules"]]
        self.assertIn("secrets-in-logs", ids)
        self.assertEqual(next(r for r in merged["rules"] if r["id"] == "no-new-deps")["title"], "LOCAL EDIT")
        self.assertEqual(merged["thresholds"]["deterministic_events"], 7)
        self.assertEqual(merged["seed_version"], 2)
        self.assertEqual(_run_retro(self.root, "--validate").returncode, 0)

    def test_merge_seed_creates_when_absent(self) -> None:
        root = make_project(self.base / "fresh", rules=False)
        proc = _run_retro(root, "--merge-seed", str(SEED))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((root / ".github" / "retro" / "rules.json").exists())
        self.assertEqual(_run_retro(root, "--validate").returncode, 0)

    def test_merge_seed_default_uses_shipped_seed_file(self) -> None:
        """Bootstrap path: no rules.json, bare --merge-seed must work."""
        root = make_project(self.base / "boot", rules=False)
        proc = _run_retro(root, "--merge-seed")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("added graph-first", proc.stdout)
        self.assertEqual(_run_retro(root, "--validate").returncode, 0)

    def test_merge_seed_reports_invalid_json_in_one_line(self) -> None:
        self.rules_path.write_text("{broken")
        proc = _run_retro(self.root, "--merge-seed", str(SEED))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_validate_rejects_bad_prefixes_and_rate(self) -> None:
        root = make_project(Path(self.tmp.name) / "v")
        path = root / ".github" / "retro" / "rules.json"
        data = json.loads(path.read_text())
        data["ignore_session_prefixes"] = "x"
        path.write_text(json.dumps(data))
        proc = _run_retro(root, "--validate")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("ignore_session_prefixes", proc.stderr)
        data["ignore_session_prefixes"] = ["p-"]
        data["thresholds"]["escalate_ignored_rate"] = 2
        path.write_text(json.dumps(data))
        proc = _run_retro(root, "--validate")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("thresholds.escalate_ignored_rate", proc.stderr)

    def test_merge_seed_adds_prefixes_and_rate_without_touching_values(self) -> None:
        root = make_project(Path(self.tmp.name) / "m")
        path = root / ".github" / "retro" / "rules.json"
        data = json.loads(path.read_text())
        data.pop("ignore_session_prefixes")
        data["thresholds"].pop("escalate_ignored_rate")
        data["thresholds"]["deterministic_events"] = 7
        path.write_text(json.dumps(data))
        proc = _run_retro(root, "--merge-seed")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = json.loads(path.read_text())
        self.assertEqual(merged["ignore_session_prefixes"], ["11111111-aaaa-4bbb-8ccc-"])
        self.assertEqual(merged["thresholds"]["escalate_ignored_rate"], 0.5)
        self.assertEqual(merged["thresholds"]["deterministic_events"], 7)

    def test_mark_retro(self) -> None:
        for i in range(3):
            _session(self.root, f"m{i}", f"2026-09-0{i + 1}T10:00:00Z")
        proc = _run_retro(self.root, "--mark-retro", "m1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(self.rules_path.read_text())
        self.assertEqual(data["last_retro"]["session_id"], "m1")
        self.assertEqual(data["last_retro"]["captured_sessions"], 3)
        self.assertTrue(data["last_retro"]["date"].endswith("Z"))
        proc = _run_retro(self.root, "--status")
        self.assertIn("1 episodes since last retro", proc.stdout)  # only m2 started after m1

    def test_analyzer_works_without_claude_hooks(self) -> None:
        """A project set up for a tool other than Claude Code has no .claude/hooks."""
        root = make_project(self.base / "copilot-only")
        shutil.rmtree(root / ".claude")
        self.assertEqual(_run_retro(root, "--validate").returncode, 0)
        proc = _run_retro(root, "--status")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("no signals captured", proc.stdout)


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_not_enabled_light_and_heavy(self) -> None:
        light = make_project(self.base / "light", rules=False, archives=3)
        proc = _run_retro(light, "--status")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("not enabled", proc.stdout)
        heavy = make_project(self.base / "heavy", rules=False, archives=12)
        proc = _run_retro(heavy, "--status")
        self.assertEqual(proc.returncode, 4)
        self.assertIn("12 archived changes", proc.stdout)

    def test_no_signals(self) -> None:
        root = make_project(self.base / "empty")
        proc = _run_retro(root, "--status")
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(proc.stdout.strip(), "retro: no signals captured")

    def test_threshold_and_last_retro(self) -> None:
        root = make_project(self.base / "p")
        for i in range(3):
            _session(root, f"s{i}", f"2026-09-0{i + 1}")
        proc = _run_retro(root, "--status")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(proc.stdout.strip(), "retro: 3 episodes since last retro (never); threshold 3")
        rules_path = root / ".github" / "retro" / "rules.json"
        data = json.loads(rules_path.read_text())
        data["last_retro"] = {"date": "2026-09-05", "session_id": "s2", "captured_sessions": 3}
        rules_path.write_text(json.dumps(data))
        proc = _run_retro(root, "--status")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("0 episodes since last retro (2026-09-05)", proc.stdout)


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = make_project(self.base / "proj", archives=4)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _report(self) -> tuple[dict, str]:
        proc = _run_retro(self.root, "--report")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.root / ".coograph" / "retro"
        return json.loads((out / "report.json").read_text()), (out / "report.md").read_text()

    def test_below_threshold_is_honest(self) -> None:
        _session(self.root, "a", "2026-09-01", violations=1)
        _session(self.root, "b", "2026-09-02")
        report, md = self._report()
        self.assertTrue(all(e["status"] in ("below_threshold", "no_detector") for e in report["per_rule"]))
        self.assertIn("2 sessions observed; thresholds not met for any rule.", md.splitlines()[2])

    def test_escalation_flagged(self) -> None:
        for i in range(3):
            _session(self.root, f"s{i}", f"2026-09-0{i + 1}", violations=1)
        report, md = self._report()
        gf = next(e for e in report["per_rule"] if e["id"] == "graph-first")
        self.assertEqual(gf["status"], "over_threshold")
        self.assertEqual(gf["escalate_to"], "hook-warn")
        self.assertEqual(report["over_threshold"], ["graph-first"])
        self.assertIn("3 sessions observed; 1 rules over threshold (graph-first).", md)

    def test_heuristic_is_supporting_only(self) -> None:
        for i in range(5):
            _session(self.root, f"h{i}", f"2026-09-0{i + 1}", violations=1, rule="openspec-gate")
        report, _ = self._report()
        og = next(e for e in report["per_rule"] if e["id"] == "openspec-gate")
        self.assertEqual(og["status"], "supporting_only")
        self.assertEqual(report["supporting_only"], ["openspec-gate"])
        self.assertNotIn("openspec-gate", report["over_threshold"])
        self.assertEqual(report["path_clusters"][0]["pattern"], "src/api/")

    def test_prune_candidate(self) -> None:
        for i in range(10):
            _session(self.root, f"p{i}", f"2026-09-{i + 1:02d}")
        report, md = self._report()
        self.assertIn("user-correction", report["prune_candidates"])
        self.assertNotIn("graph-first", report["prune_candidates"])  # hard rules never prune
        # Rules enforced by a hook are not prose, so they are never prune candidates
        # however quiet they are.
        self.assertNotIn("no-new-deps", report["prune_candidates"])
        self.assertNotIn("defect", report["prune_candidates"])
        self.assertIn("Prune candidates", md)

    def test_tokens_before_after_and_adherence(self) -> None:
        rules_path = self.root / ".github" / "retro" / "rules.json"
        data = json.loads(rules_path.read_text())
        data["rules"][0]["last_changed"] = "2026-09-05"
        rules_path.write_text(json.dumps(data))
        for i in range(4):
            _session(self.root, f"b{i}", f"2026-09-0{i + 1}", usage_total=90000, edits=1, review=(i < 3))
        for i in range(4):
            _session(self.root, f"a{i}", f"2026-09-0{i + 6}", usage_total=60000)
        report, md = self._report()
        self.assertEqual(report["tokens"]["before_after"]["rate_before"], 90000)
        self.assertEqual(report["tokens"]["before_after"]["rate_after"], 60000)
        self.assertIn("went down from 90 000 to 60 000", md)
        self.assertEqual(report["workflow_adherence"], {"editing_sessions": 4, "reviewed_sessions": 3, "rate": 0.75})
        gf = next(e for e in report["per_rule"] if e["id"] == "graph-first")
        self.assertIsNotNone(gf["before_after"])

    def _rule(self, report: dict, rid: str) -> dict:
        return next(e for e in report["per_rule"] if e["id"] == rid)

    def test_hook_warn_holds_without_outcomes(self) -> None:
        for i in range(3):
            _session(self.root, f"n{i}", f"2026-09-0{i + 1}", violations=1, rule="no-new-deps")
        report, md = self._report()
        nd = self._rule(report, "no-new-deps")
        self.assertEqual(nd["enforcement"], "hook-warn")
        self.assertEqual(nd["status"], "over_threshold")
        self.assertIsNone(nd["escalate_to"])
        self.assertEqual(nd["hold_reason"], "no_outcomes")
        self.assertIn("| hold: no_outcomes |", md)
        self.assertNotIn("## Decisions", md)

    def test_hook_warn_holds_when_warnings_change_behaviour(self) -> None:
        for i in range(3):
            _session(self.root, f"n{i}", f"2026-09-0{i + 1}", violations=1, rule="no-new-deps")
            _outcomes(self.root, f"n{i}", "no-new-deps", repeated=[0])
        report, md = self._report()
        nd = self._rule(report, "no-new-deps")
        self.assertEqual(nd["status"], "over_threshold")
        self.assertIsNone(nd["escalate_to"])
        self.assertEqual(nd["hold_reason"], "warnings_change_behaviour")
        self.assertEqual(nd["decisions"], {"warned": 3, "blocked": 0, "suppressed": 0})
        self.assertEqual(nd["outcomes"]["n"], 3)
        self.assertEqual(nd["outcomes"]["ignored_rate"], 0.0)
        self.assertEqual(report["decisions_recorded"], 3)
        self.assertIn("## Decisions", md)
        self.assertIn("| no-new-deps | 3 | 0 | 0 | 3 | 100% | 0% | n/a | 0% |", md)

    def test_hook_warn_escalates_when_warnings_are_ignored(self) -> None:
        for i in range(3):
            _session(self.root, f"n{i}", f"2026-09-0{i + 1}", violations=1, rule="no-new-deps")
            _outcomes(self.root, f"n{i}", "no-new-deps", repeated=[1, 0])
        report, md = self._report()
        nd = self._rule(report, "no-new-deps")
        self.assertEqual(nd["escalate_to"], "hook-block")
        self.assertNotIn("hold_reason", nd)
        self.assertEqual(nd["outcomes"]["ignored_rate"], 0.5)
        self.assertIn("| hook-block |", md)

    def test_reconciled_outcomes_are_not_ignored(self) -> None:
        for i in range(3):
            _session(self.root, f"n{i}", f"2026-09-0{i + 1}", violations=1, rule="no-new-deps")
            _outcomes(self.root, f"n{i}", "no-new-deps", repeated=[2], reconciled=True)
        report, _ = self._report()
        nd = self._rule(report, "no-new-deps")
        self.assertEqual(nd["hold_reason"], "warnings_change_behaviour")
        self.assertEqual(nd["outcomes"]["reconciled_rate"], 1.0)
        self.assertEqual(nd["outcomes"]["ignored_rate"], 0.0)

    def test_prose_rule_still_escalates_to_warn_without_outcomes(self) -> None:
        for i in range(3):
            _session(self.root, f"s{i}", f"2026-09-0{i + 1}", violations=1)
        report, _ = self._report()
        self.assertEqual(self._rule(report, "graph-first")["escalate_to"], "hook-warn")

    def test_ignored_prefixes_drop_probe_sessions(self) -> None:
        _session(self.root, "11111111-aaaa-4bbb-8ccc-000000000005", "2026-09-05", violations=1, rule="no-new-deps")
        _session(self.root, "abc", "2026-09-06", violations=1, rule="no-new-deps")
        report, md = self._report()
        self.assertEqual(report["window"]["sessions"], 1)
        self.assertEqual(report["window"]["ignored_sessions"], 1)
        self.assertEqual(self._rule(report, "no-new-deps")["events"], 1)
        self.assertIn("Ignored sessions (ignore_session_prefixes): 1", md)
        status = _run_retro(self.root, "--status")
        self.assertIn("1 episodes since last retro", status.stdout)
        mark = _run_retro(self.root, "--mark-retro", "abc")
        self.assertIn("(1 sessions captured)", mark.stdout)

    def test_archive_stats(self) -> None:
        report, md = self._report()
        a = report["archive_stats"]
        self.assertEqual(a["archived_changes"], 4)
        self.assertEqual(a["review_fixes_share"], 0.5)
        self.assertEqual(a["most_referenced_paths"][0]["path"], "src/core/thing.ts")
        self.assertIn("Archived changes: 4", md)

    def test_instruction_tokens_and_budget(self) -> None:
        report, _ = self._report()
        files = [r["file"] for r in report["instruction_tokens"]]
        self.assertIn("CLAUDE.md", files)
        self.assertFalse(report["over_budget"])
        (self.root / "CLAUDE.md").write_text("x" * 40000)
        report, md = self._report()
        self.assertTrue(report["over_budget"])
        self.assertIn("OVER budget", md)

    def test_end_to_end_from_transcript(self) -> None:
        t = Transcript("e2e")
        t.result(t.tool("Grep", pattern="a"))
        t.result(t.tool("mcp__code-graph__query_graph", pattern="callers_of", node_name="f"))
        path = t.write(self.base / "tx" / "e2e.jsonl")
        proc = subprocess.run(
            [sys.executable, str(self.root / ".claude" / "hooks" / "capture-signals.py"),
             "--backfill", str(path.parent), "--cwd", str(self.root)],
            capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)},
        )
        self.assertIn("captured 1 sessions", proc.stdout)
        report, _ = self._report()
        self.assertEqual(report["window"]["sessions"], 1)
        gf = next(e for e in report["per_rule"] if e["id"] == "graph-first")
        self.assertEqual(gf["events"], 1)
        self.assertEqual(len(read_signals(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
