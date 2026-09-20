"""Tests for the signal store and the transcript capture hook.

Run:  python -m unittest discover .github/retro/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from fixtures import HOOKS, SEED, SENTINEL, Transcript, make_project, read_signals

import _coograph_signals as sig  # noqa: E402
import _coograph_guard as guard  # noqa: E402


def _load_capture():
    spec = importlib.util.spec_from_file_location("capture_signals", HOOKS / "capture-signals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cap = _load_capture()


def _capture(root: Path, transcript: Path) -> list[dict]:
    rules = sig.load_rules(root)
    cap.capture_one(transcript, root, rules, sig.known_sessions(root))
    return read_signals(root)


def _by(records: list[dict], detector: str) -> list[dict]:
    return [r for r in records if r.get("detector") == detector]


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name) / "proj")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unknown_evidence_keys_dropped(self) -> None:
        rec = sig.make_record(tool="claude-code", session_id="s", kind="violation", rule="scope",
                              detector="scope-warning", confidence="deterministic",
                              evidence={"path": "a.ts", "secret": "nope"}, origin="hook")
        self.assertEqual(rec["evidence"], {"path": "a.ts"})
        self.assertTrue(sig.emit(self.root, rec))
        self.assertEqual(read_signals(self.root)[0]["evidence"], {"path": "a.ts"})

    def test_command_identity(self) -> None:
        program, digest = sig.command_identity("npm run build -- --watch")
        self.assertEqual(program, "npm")
        self.assertEqual(len(digest), 12)
        self.assertNotIn("watch", program + digest)

    def test_rel_path_external(self) -> None:
        # Windows drive and UNC paths are external on every host, including a
        # POSIX machine reading transcripts copied from Windows.
        self.assertEqual(sig.rel_path(self.root, r"C:\Users\someone\notes.md"), "external")
        self.assertEqual(sig.rel_path(self.root, "D:/other/notes.md"), "external")
        self.assertEqual(sig.rel_path(self.root, r"\\server\share\x.ts"), "external")
        self.assertEqual(sig.rel_path(self.root, "/etc/passwd"), "external")
        # Relative paths with backslashes come out in POSIX form on every host.
        self.assertEqual(sig.rel_path(self.root, r"src\b.ts"), "src/b.ts")
        inside = self.root / "src" / "a.ts"
        self.assertEqual(sig.rel_path(self.root, str(inside)), "src/a.ts")
        self.assertEqual(sig.rel_path(self.root, "src/b.ts"), "src/b.ts")
        self.assertEqual(sig.rel_path(self.root, "../up.ts"), "external")
        self.assertLessEqual(len(sig.rel_path(self.root, "x/" * 400)), 300)

    def test_guard_session_end_key(self) -> None:
        self.assertEqual(guard._event_key({"hook_event_name": "SessionEnd", "session_id": "abc"}),
                         "SessionEnd:abc")

    def test_replace_keeps_hook_origin(self) -> None:
        hook_rec = sig.make_record(tool="claude-code", session_id="s1", kind="violation", rule="scope",
                                   detector="scope-warning", confidence="deterministic",
                                   evidence={"path": "a.ts"}, origin="hook")
        sig.emit(self.root, hook_rec)
        session = sig.make_record(tool="claude-code", session_id="s1", kind="session", rule="none",
                                  detector="session", confidence="deterministic",
                                  evidence={"message_count": 3, "started": "2026-09-01"}, origin="transcript")
        sig.replace_session(self.root, "s1", [session])
        sig.replace_session(self.root, "s1", [session])
        recs = read_signals(self.root)
        self.assertEqual(len(recs), 2)
        self.assertEqual({r["origin"] for r in recs}, {"hook", "transcript"})

    def test_concurrent_writers(self) -> None:
        def writer(sid: str) -> None:
            rec = sig.make_record(tool="claude-code", session_id=sid, kind="session", rule="none",
                                  detector="session", confidence="deterministic",
                                  evidence={"message_count": 1, "started": f"2026-09-0{sid[-1]}"},
                                  origin="transcript")
            sig.replace_session(self.root, sid, [rec])

        threads = [threading.Thread(target=writer, args=(f"s{i}",)) for i in range(1, 6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        recs = read_signals(self.root)
        self.assertEqual({r["session_id"] for r in recs}, {"s1", "s2", "s3", "s4", "s5"})

    def test_sessions_since_is_anchored_not_counted(self) -> None:
        def s(sid: str, started: str) -> dict:
            return {"session_id": sid, "kind": "session", "evidence": {"started": started}}

        sessions = {f"s{i}": s(f"s{i}", f"2026-09-{i:02d}T10:00:00Z") for i in range(1, 6)}
        # Retro ran in s3; two sessions started after it.
        self.assertEqual(sig.sessions_since(sessions, {"date": "x", "session_id": "s3", "captured_sessions": 3}), 2)
        # Session record for the retro session missing: fall back to the UTC date.
        self.assertEqual(sig.sessions_since(sessions, {"date": "2026-09-04T00:00:00Z", "session_id": "gone",
                                                       "captured_sessions": 3}), 2)
        # At a retention cap the count never changes; the anchor still works.
        capped = {k: v for k, v in sessions.items() if k != "s1"}
        self.assertEqual(sig.sessions_since(capped, {"date": "x", "session_id": "s3", "captured_sessions": 4}), 2)
        self.assertEqual(sig.sessions_since(sessions, None), 5)

    def test_status_line_keeps_call_to_action(self) -> None:
        rules = json.loads((self.root / ".github" / "retro" / "rules.json").read_text())
        rules["rules"][0]["id"] = "graph-first-" + "x" * 150
        (self.root / ".github" / "retro" / "rules.json").write_text(json.dumps(rules))
        rid = rules["rules"][0]["id"]
        for i in range(3):
            rec = sig.make_record(tool="claude-code", session_id=f"s{i}", kind="violation", rule=rid,
                                  detector="graph-first", confidence="deterministic",
                                  evidence={"count": 1, "first_index": 0, "tools": ["Grep"], "proof": "mcp-later"},
                                  origin="transcript")
            ses = sig.make_record(tool="claude-code", session_id=f"s{i}", kind="session", rule="none",
                                  detector="session", confidence="deterministic",
                                  evidence={"message_count": 1, "started": f"2026-09-0{i + 1}"}, origin="transcript")
            sig.replace_session(self.root, f"s{i}", [rec, ses])
        line = sig.status_line(self.root)
        self.assertLessEqual(len(line), 160)
        self.assertTrue(line.endswith(", run /coograph-retro"))

    def test_retention_drops_oldest(self) -> None:
        for i in range(1, 5):
            rec = sig.make_record(tool="claude-code", session_id=f"s{i}", kind="session", rule="none",
                                  detector="session", confidence="deterministic",
                                  evidence={"message_count": 1, "started": f"2026-09-0{i}"},
                                  origin="transcript")
            sig.replace_session(self.root, f"s{i}", [rec], max_sessions=2)
        self.assertEqual({r["session_id"] for r in read_signals(self.root)}, {"s3", "s4"})

    def test_rules_validation(self) -> None:
        rules = json.loads((self.root / ".github" / "retro" / "rules.json").read_text())
        self.assertIsNone(sig.validate_rules(rules))
        rules["thresholds"]["deterministic_events"] = "3"
        self.assertEqual(sig.validate_rules(rules), "thresholds.deterministic_events")
        (self.root / ".github" / "retro" / "rules.json").write_text("{not json")
        self.assertIsNone(sig.load_rules(self.root))


class DetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = make_project(self.base / "proj")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _tpath(self, name: str = "t.jsonl") -> Path:
        return self.base / "transcripts" / name

    def test_sentinel_never_leaks(self) -> None:
        t = Transcript("sentinel")
        t.user(f"please {SENTINEL} do it")
        t.say(f"thinking about {SENTINEL}")
        tid = t.tool("Grep", pattern=SENTINEL, path="src")
        t.result(tid, content=f"found {SENTINEL}")
        tid = t.tool("Bash", command=f"echo {SENTINEL} && npm install {SENTINEL}")
        t.result(tid, content=SENTINEL, is_error=True)
        tid = t.tool("Edit", file_path=str(self.root / "src" / "a.ts"), old_string=SENTINEL, new_string=SENTINEL)
        t.result(tid)
        tid = t.tool("mcp__code-graph__query_graph", pattern="callers_of", node_name=SENTINEL)
        t.result(tid)
        t.user(f"No, {SENTINEL} again")
        path = t.write(self._tpath())
        _capture(self.root, path)
        raw = (self.root / ".coograph" / "signals.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, raw)
        self.assertTrue(raw.strip())

    def test_graph_first_mcp_later(self) -> None:
        t = Transcript("g1")
        t.result(t.tool("Grep", pattern="a"))
        t.result(t.tool("Glob", pattern="**/*.ts"))
        t.result(t.tool("Grep", pattern="b"))
        t.result(t.tool("mcp__code-graph__get_minimal_context", task="x"))
        t.result(t.tool("Grep", pattern="c"))
        recs = _by(_capture(self.root, t.write(self._tpath())), "graph-first")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["evidence"]["count"], 3)
        self.assertEqual(recs[0]["evidence"]["proof"], "mcp-later")
        self.assertEqual(recs[0]["evidence"]["first_index"], 0)
        self.assertEqual(recs[0]["rule"], "graph-first")
        self.assertEqual(recs[0]["confidence"], "deterministic")

    def test_graph_first_sqlite_first_is_fine(self) -> None:
        t = Transcript("g2")
        t.result(t.tool("Bash", command='sqlite3 .code-graph/graph.db "SELECT COUNT(*) FROM nodes;"'))
        t.result(t.tool("Grep", pattern="a"))
        t.result(t.tool("Grep", pattern="b"))
        self.assertEqual(_by(_capture(self.root, t.write(self._tpath())), "graph-first"), [])

    def test_graph_first_sqlite_later(self) -> None:
        t = Transcript("g3")
        t.result(t.tool("Grep", pattern="a"))
        t.result(t.tool("Grep", pattern="b"))
        t.result(t.tool("Bash", command='python3 -c "import sqlite3; sqlite3.connect(\'.code-graph/graph.db\')"'))
        recs = _by(_capture(self.root, t.write(self._tpath())), "graph-first")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["evidence"]["count"], 2)
        self.assertEqual(recs[0]["evidence"]["proof"], "sqlite-later")

    def test_graph_first_total_bypass(self) -> None:
        t = Transcript("g4")
        t.result(t.tool("Grep", pattern="a"))
        recs = _by(_capture(self.root, t.write(self._tpath())), "graph-first")
        self.assertEqual(recs[0]["evidence"]["proof"], "total-bypass")

    def test_graph_first_sidechain_ignored(self) -> None:
        t = Transcript("g5")
        t.result(t.tool("Grep", pattern="a", sidechain=True))
        t.result(t.tool("Grep", pattern="b", sidechain=True))
        t.result(t.tool("mcp__code-graph__query_graph", pattern="callers_of", node_name="x"))
        self.assertEqual(_by(_capture(self.root, t.write(self._tpath())), "graph-first"), [])

    def test_graph_absent_no_violation(self) -> None:
        root = make_project(self.base / "nograph", graph=False)
        t = Transcript("g6")
        t.result(t.tool("Grep", pattern="a"))
        recs = _capture(root, t.write(self._tpath()))
        self.assertEqual(_by(recs, "graph-first"), [])
        self.assertFalse(_by(recs, "session")[0]["evidence"]["graph_db_present"])

    def test_openspec_gate_heuristic(self) -> None:
        t = Transcript("o1")
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "a.ts")))
        t.result(t.tool("Write", file_path=str(self.root / "src" / "b.ts")))
        recs = _by(_capture(self.root, t.write(self._tpath())), "openspec-gate")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["confidence"], "heuristic")
        self.assertEqual(sorted(recs[0]["evidence"]["files"]), ["src/a.ts", "src/b.ts"])

    def test_openspec_gate_exempt_when_archived_at_end(self) -> None:
        t = Transcript("o2")
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "a.ts")))
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "b.ts")))
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "c.ts")))
        t.result(t.tool("Bash", command="mv openspec/changes/x openspec/changes/archive/x"))
        self.assertEqual(_by(_capture(self.root, t.write(self._tpath())), "openspec-gate"), [])

    def test_openspec_gate_exempt_when_active_spec_exists(self) -> None:
        root = make_project(self.base / "active", active_openspec=True)
        t = Transcript("o3")
        t.result(t.tool("Edit", file_path=str(root / "src" / "a.ts")))
        t.result(t.tool("Edit", file_path=str(root / "src" / "b.ts")))
        self.assertEqual(_by(_capture(root, t.write(self._tpath())), "openspec-gate"), [])

    def test_build_retry(self) -> None:
        t = Transcript("b1")
        for err in (True, True, False):
            t.result(t.tool("Bash", command="npm run build"), is_error=err)
        t.result(t.tool("Bash", command="npm test"), is_error=True)
        t.result(t.tool("Bash", command="npm test"), is_error=True)
        recs = _by(_capture(self.root, t.write(self._tpath())), "build-retry")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["evidence"]["program"], "npm")
        self.assertEqual(recs[0]["evidence"]["runs"], 3)
        self.assertEqual(recs[0]["evidence"]["errors"], 2)
        self.assertEqual(recs[0]["kind"], "event")

    def test_user_correction(self) -> None:
        t = Transcript("c1")
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "a.ts")))
        t.user("No, that is the wrong file")
        t.say("ok")
        t.user("thanks")
        recs = _by(_capture(self.root, t.write(self._tpath())), "user-correction")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["evidence"], {"pattern": "no", "after_tool": True})
        self.assertEqual(recs[0]["confidence"], "heuristic")
        # A violation against a real rule, so repeated corrections can cluster
        # and reach a proposal instead of being reported as colour.
        self.assertEqual(recs[0]["kind"], "violation")
        self.assertEqual(recs[0]["rule"], "user-correction")

    def test_new_dependency(self) -> None:
        t = Transcript("d1")
        t.result(t.tool("Bash", command="npm install left-pad --save"))
        t.result(t.tool("Bash", command="npm install"))
        t.result(t.tool("Bash", command="uv pip install requests"))
        t.result(t.tool("Bash", command="npm run build"))
        t.result(t.tool("Edit", file_path=str(self.root / "package.json")))
        recs = _by(_capture(self.root, t.write(self._tpath())), "new-dependency")
        self.assertEqual(len(recs), 3)
        self.assertEqual(recs[0]["evidence"], {"program": "npm", "manifest": "", "via": "command"})
        self.assertEqual(recs[1]["evidence"]["program"], "uv")
        self.assertEqual(recs[2]["evidence"], {"program": "", "manifest": "package.json", "via": "edit"})
        self.assertTrue(all(r["rule"] == "no-new-deps" for r in recs))

    def test_usage_dedupe_and_session_summary(self) -> None:
        t = Transcript("u1")
        usage = {"input_tokens": 5, "output_tokens": 100, "cache_read_input_tokens": 1000,
                 "cache_creation_input_tokens": 50}
        t.say("a", usage=usage, message_id="m1")
        t.say("b", usage=usage, message_id="m1")
        t.result(t.tool("Skill", skill="coograph-review", usage=usage, message_id="m1"))
        t.say("c", usage=usage, message_id="m2")
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "a.ts")))
        recs = _by(_capture(self.root, t.write(self._tpath())), "session")
        ev = recs[0]["evidence"]
        self.assertEqual(ev["usage"], {"input": 10, "output": 200, "cache_read": 2000, "cache_create": 100})
        self.assertEqual(ev["skills_invoked"], ["coograph-review"])
        self.assertEqual(ev["edited_files"], 1)
        self.assertEqual(ev["tool_calls_total"], 2)
        self.assertTrue(ev["started"] <= ev["ended"])
        self.assertEqual(ev["tools_used"], {"Skill": 1, "Edit": 1})

    def test_malformed_line_skipped(self) -> None:
        t = Transcript("m1")
        t.result(t.tool("Grep", pattern="a"))
        t.raw("{this is not json")
        t.raw("")
        t.result(t.tool("Grep", pattern="b"))
        recs = _capture(self.root, t.write(self._tpath()))
        self.assertEqual(_by(recs, "session")[0]["evidence"]["message_count"], 4)
        self.assertEqual(_by(recs, "graph-first")[0]["evidence"]["count"], 2)

    def test_idempotent_and_replace(self) -> None:
        t = Transcript("i1")
        t.result(t.tool("Grep", pattern="a"))
        path = t.write(self._tpath())
        rules = sig.load_rules(self.root)
        self.assertEqual(cap.capture_one(path, self.root, rules, sig.known_sessions(self.root)), "captured")
        self.assertEqual(cap.capture_one(path, self.root, rules, sig.known_sessions(self.root)), "skipped")
        t.result(t.tool("Grep", pattern="b"))
        t.write(path)
        self.assertEqual(cap.capture_one(path, self.root, rules, sig.known_sessions(self.root)), "captured")
        recs = read_signals(self.root)
        self.assertEqual(len(_by(recs, "session")), 1)
        self.assertEqual(_by(recs, "session")[0]["evidence"]["message_count"], 4)
        self.assertEqual(_by(recs, "graph-first")[0]["evidence"]["count"], 2)

    def test_pip_requirements_and_editable_are_not_new_dependencies(self) -> None:
        t = Transcript("d2")
        t.result(t.tool("Bash", command="pip install -r requirements.txt"))
        t.result(t.tool("Bash", command="pip install -e ."))
        t.result(t.tool("Bash", command="uv pip install --requirement .github/code-graph/requirements.txt"))
        t.result(t.tool("Bash", command="npm install"))
        t.result(t.tool("Bash", command="pip install -r requirements.txt requests"))
        recs = _by(_capture(self.root, t.write(self._tpath())), "new-dependency")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["evidence"]["program"], "pip")

    def test_session_record_carries_source_bytes(self) -> None:
        t = Transcript("sb1")
        t.result(t.tool("Grep", pattern="a"))
        path = t.write(self._tpath())
        recs = _by(_capture(self.root, path), "session")
        self.assertEqual(recs[0]["evidence"]["source_bytes"], path.stat().st_size)
        self.assertEqual(sig.known_sources(self.root), {"sb1": path.stat().st_size})

    def test_catchup_newest_first_and_known_skipped_without_parse(self) -> None:
        d = self.base / "transcripts"
        # 25 old, already-captured transcripts (oldest mtimes) ...
        old = []
        for i in range(25):
            t = Transcript(f"old{i:02d}")
            t.result(t.tool("Grep", pattern="a"))
            p = t.write(d / f"old{i:02d}.jsonl")
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
            old.append(p)
        cap.backfill(d, self.root)
        self.assertEqual(len(sig.known_sessions(self.root)), 25)
        # ... then one killed session, newest.
        killed = Transcript("killed-new")
        killed.result(killed.tool("Grep", pattern="z"))
        kp = killed.write(d / "killed-new.jsonl")
        os.utime(kp, (1_700_001_000, 1_700_001_000))
        # Corrupt an old file's content but keep its size: it must NOT be re-parsed.
        raw = old[0].read_bytes()
        old[0].write_bytes(b"x" * len(raw))
        captured, skipped, failed = cap.backfill(
            d, self.root, budget_seconds=2.0, max_files=cap.CATCHUP_MAX_FILES,
        )
        self.assertEqual((captured, skipped, failed), (1, 25, 0))
        self.assertIn("killed-new", sig.known_sessions(self.root))

    def test_backfill_cli_twice(self) -> None:
        d = self.base / "transcripts"
        for i in range(3):
            t = Transcript(f"bf{i}")
            t.result(t.tool("Grep", pattern="a"))
            t.write(d / f"bf{i}.jsonl")
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)}
        cmd = [sys.executable, str(self.root / ".claude" / "hooks" / "capture-signals.py"),
               "--backfill", str(d), "--cwd", str(self.root)]
        out1 = subprocess.run(cmd, capture_output=True, text=True, env=env)
        out2 = subprocess.run(cmd, capture_output=True, text=True, env=env)
        self.assertEqual(out1.returncode, 0, out1.stderr)
        self.assertIn("captured 3 sessions", out1.stdout)
        self.assertIn("captured 0 sessions", out2.stdout)
        self.assertIn("skipped 3", out2.stdout)


def _isolated_env(root: Path, base: Path) -> dict[str, str]:
    """Hook subprocess env: project dir set, and the guard's lock directory
    (tempfile.gettempdir()) pointed at this test's temp dir so claims from
    a previous run never make should_skip() return True."""
    lock_tmp = base / "locks"
    lock_tmp.mkdir(exist_ok=True)
    return {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(root),
        "TMP": str(lock_tmp), "TEMP": str(lock_tmp), "TMPDIR": str(lock_tmp),
    }


class HookModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = make_project(self.base / "proj")
        self.env = _isolated_env(self.root, self.base)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.root / ".claude" / "hooks" / script)],
            input=json.dumps(payload), capture_output=True, text=True, env=self.env,
            cwd=str(self.root),
        )

    def test_session_end_captures(self) -> None:
        t = Transcript("end-1")
        t.result(t.tool("Grep", pattern="a"))
        path = t.write(self.base / "tx" / "end-1.jsonl")
        proc = self._run("capture-signals.py", {
            "hook_event_name": "SessionEnd", "session_id": "end-1",
            "transcript_path": str(path), "cwd": str(self.root), "reason": "exit",
        })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len([r for r in read_signals(self.root) if r["kind"] == "session"]), 1)

    def test_session_end_silent_when_retro_disabled(self) -> None:
        root = make_project(self.base / "optout", rules=False)
        t = Transcript("opt-1")
        t.result(t.tool("Grep", pattern="a"))
        path = t.write(self.base / "tx" / "opt-1.jsonl")
        env = _isolated_env(root, self.base)
        proc = subprocess.run(
            [sys.executable, str(root / ".claude" / "hooks" / "capture-signals.py")],
            input=json.dumps({"hook_event_name": "SessionEnd", "session_id": "opt-1",
                              "transcript_path": str(path), "cwd": str(root)}),
            capture_output=True, text=True, env=env, cwd=str(root),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((root / ".coograph" / "signals.jsonl").exists())

    def test_hooks_silent_when_retro_dir_missing(self) -> None:
        root = make_project(self.base / "noretro")
        shutil.rmtree(root / ".github" / "retro")
        env = _isolated_env(root, self.base)
        proc = subprocess.run(
            [sys.executable, str(root / ".claude" / "hooks" / "capture-signals.py")],
            input=json.dumps({"hook_event_name": "SessionStart", "session_id": "x", "source": "startup",
                              "transcript_path": str(self.base / "tx" / "x.jsonl"), "cwd": str(root)}),
            capture_output=True, text=True, env=env, cwd=str(root),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")
        proc = subprocess.run(
            [sys.executable, str(root / ".claude" / "hooks" / "block-generated.py")],
            input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write", "session_id": "bgx",
                              "tool_use_id": "t9", "cwd": str(root),
                              "tool_input": {"file_path": str(root / "dist" / "bundle.js")}}),
            capture_output=True, text=True, env=env, cwd=str(root),
        )
        self.assertEqual(proc.returncode, 2)  # still blocks without Retro

    def test_session_end_missing_transcript_exits_zero(self) -> None:
        proc = self._run("capture-signals.py", {
            "hook_event_name": "SessionEnd", "session_id": "end-2",
            "transcript_path": str(self.base / "nope.jsonl"), "cwd": str(self.root),
        })
        self.assertEqual(proc.returncode, 0)

    def test_session_start_catches_up_siblings_not_self(self) -> None:
        d = self.base / "tx"
        killed = Transcript("killed")
        killed.result(killed.tool("Grep", pattern="a"))
        killed.write(d / "killed.jsonl")
        own = Transcript("own")
        own.result(own.tool("Grep", pattern="b"))
        own_path = own.write(d / "own.jsonl")
        proc = self._run("capture-signals.py", {
            "hook_event_name": "SessionStart", "session_id": "own", "source": "startup",
            "transcript_path": str(own_path), "cwd": str(self.root),
        })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sessions = {r["session_id"] for r in read_signals(self.root) if r["kind"] == "session"}
        self.assertEqual(sessions, {"killed"})
        self.assertIn("[retro] 1 sessions captured", proc.stdout)

    def test_session_start_compact_prints_status_without_parsing(self) -> None:
        d = self.base / "tx"
        killed = Transcript("killed")
        killed.result(killed.tool("Grep", pattern="a"))
        killed.write(d / "killed.jsonl")
        own_path = Transcript("own").write(d / "own.jsonl")
        proc = self._run("capture-signals.py", {
            "hook_event_name": "SessionStart", "session_id": "own", "source": "compact",
            "transcript_path": str(own_path), "cwd": str(self.root),
        })
        self.assertEqual(read_signals(self.root), [])
        self.assertIn("[retro] enabled, no sessions captured yet", proc.stdout)

    def test_status_line_silent_without_rules(self) -> None:
        root = make_project(self.base / "norules", rules=False)
        env = _isolated_env(root, self.base)
        proc = subprocess.run(
            [sys.executable, str(root / ".claude" / "hooks" / "capture-signals.py")],
            input=json.dumps({"hook_event_name": "SessionStart", "session_id": "x", "source": "startup",
                              "transcript_path": str(self.base / "tx" / "x.jsonl"), "cwd": str(root)}),
            capture_output=True, text=True, env=env, cwd=str(root),
        )
        self.assertEqual(proc.stdout.strip(), "")

    def test_status_line_bootstrap_hint(self) -> None:
        root = make_project(self.base / "heavy", rules=False, archives=12)
        self.assertEqual(
            sig.status_line(root),
            "[retro] not enabled, 12 archived changes found, run /coograph-retro to bootstrap",
        )
        light = make_project(self.base / "light", rules=False, archives=3)
        self.assertIsNone(sig.status_line(light))

    def test_status_line_over_threshold(self) -> None:
        for i in range(3):
            t = Transcript(f"ot{i}")
            t.result(t.tool("Grep", pattern="a"))
            t.result(t.tool("mcp__code-graph__query_graph", pattern="x", node_name="y"))
            _capture(self.root, t.write(self.base / "tx" / f"ot{i}.jsonl"))
        line = sig.status_line(self.root)
        self.assertEqual(line, "[retro] 3 sessions captured, 1 rules over threshold (graph-first 3x), run /coograph-retro")
        self.assertLessEqual(len(line), 160)

    def test_warn_scope_emits(self) -> None:
        root = make_project(self.base / "scoped", active_openspec=True)
        env = _isolated_env(root, self.base)
        proc = subprocess.run(
            [sys.executable, str(root / ".claude" / "hooks" / "warn-scope.py")],
            input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "session_id": "ws1",
                              "tool_use_id": "t1", "cwd": str(root),
                              "tool_input": {"file_path": str(root / "src" / "b.ts")}}),
            capture_output=True, text=True, env=env, cwd=str(root),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[warn-scope]", proc.stderr)
        recs = read_signals(root)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["rule"], "scope")
        self.assertEqual(recs[0]["origin"], "hook")
        self.assertEqual(recs[0]["evidence"]["path"], "src/b.ts")
        self.assertEqual(recs[0]["evidence"]["openspec"], "2026-09-01-active")

    def test_block_generated_emits(self) -> None:
        proc = self._run("block-generated.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Write", "session_id": "bg1",
            "tool_use_id": "t2", "cwd": str(self.root),
            "tool_input": {"file_path": str(self.root / "dist" / "bundle.js")},
        })
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BLOCKED", proc.stderr)
        recs = read_signals(self.root)
        self.assertEqual(recs[0]["rule"], "generated-files")
        self.assertEqual(recs[0]["evidence"], {"path": "dist/bundle.js", "reason": "directory"})


class CompactCaptureTests(unittest.TestCase):
    """A session that never ends still has to report."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name) / "proj")
        self.tdir = Path(self.tmp.name) / "transcripts"
        self.tdir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _hook(self, source: str, transcript: Path) -> None:
        cap._hook({
            "hook_event_name": "SessionStart",
            "source": source,
            "transcript_path": str(transcript),
            "cwd": str(self.root),
        })

    def _transcript(self, sid: str, says: int) -> Path:
        t = Transcript(sid)
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "a.ts")))
        for i in range(says):
            t.say(f"step {i}")
        return t.write(self.tdir / f"{sid}.jsonl")

    def test_compact_captures_own_transcript(self) -> None:
        path = self._transcript("live-1", 2)
        self._hook("compact", path)
        sids = {r["session_id"] for r in read_signals(self.root)}
        self.assertIn("live-1", sids)

    def test_compact_replaces_as_the_session_grows(self) -> None:
        path = self._transcript("live-2", 2)
        self._hook("compact", path)
        first = [r for r in read_signals(self.root) if r["kind"] == "session"]
        self.assertEqual(len(first), 1)
        grown = self._transcript("live-2", 6)
        self._hook("compact", grown)
        second = [r for r in read_signals(self.root) if r["kind"] == "session"]
        self.assertEqual(len(second), 1, "a growing session replaces its own records")
        self.assertGreater(
            second[0]["evidence"]["message_count"], first[0]["evidence"]["message_count"]
        )

    def test_startup_still_skips_its_own_transcript(self) -> None:
        path = self._transcript("live-3", 2)
        self._hook("startup", path)
        sids = {r["session_id"] for r in read_signals(self.root)}
        self.assertNotIn("live-3", sids, "catch-up captures siblings, not the live session")

    def test_no_registry_means_no_capture(self) -> None:
        (self.root / ".github" / "retro" / "rules.json").unlink()
        path = self._transcript("live-4", 2)
        self._hook("compact", path)
        self.assertEqual(read_signals(self.root), [])


class DefectDetectorTests(unittest.TestCase):
    """A fix landing on a file a recent change touched."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name) / "proj")
        self.tdir = Path(self.tmp.name) / "transcripts"
        self.tdir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _git(self, root: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=False)

    def _repo(self, root: Path | None = None) -> None:
        root = root or self.root
        self._git(root, "init", "-q")
        self._git(root, "config", "user.email", "t@example.com")
        self._git(root, "config", "user.name", "t")
        self._git(root, "config", "commit.gpgsign", "false")

    def _commit(self, root: Path, path: str, subject: str, body: str = "x") -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        self._git(root, "add", path)
        self._git(root, "commit", "-q", "-m", subject)

    def _parsed(self, sid: str = "g1"):
        t = Transcript(sid)
        t.result(t.tool("Edit", file_path=str(self.root / "src" / "a.ts")))
        t.say("done")
        path = t.write(self.tdir / f"{sid}.jsonl")
        return cap.parse_transcript(path, cap.DEFAULT_CORRECTION_PATTERNS)

    def test_fix_after_feature_is_a_defect(self) -> None:
        self._repo()
        self._commit(self.root, "src/thing.ts", "feat: add thing")
        self._commit(self.root, "src/thing.ts", "fix(thing): wrong region", body="y")
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"  # whole history in window
        found = cap.detect_defects(self.root, parsed, 14)
        self.assertEqual(len(found), 1)
        evidence = found[0]
        self.assertEqual(evidence["files"], ["src/thing.ts"])
        self.assertEqual(evidence["count"], 1)
        self.assertEqual(set(evidence), {"fix", "origin", "files", "count", "days"})

    def test_fix_on_a_file_no_feature_touched_is_not(self) -> None:
        self._repo()
        self._commit(self.root, "src/other.ts", "feat: add other")
        self._commit(self.root, "src/fresh.ts", "fix: unrelated")
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        self.assertEqual(cap.detect_defects(self.root, parsed, 14), [])

    def test_feature_only_history_is_not(self) -> None:
        self._repo()
        self._commit(self.root, "src/a.ts", "feat: one")
        self._commit(self.root, "src/a.ts", "feat: two", body="y")
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        self.assertEqual(cap.detect_defects(self.root, parsed, 14), [])

    def test_without_git_there_is_no_signal(self) -> None:
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        self.assertEqual(cap.detect_defects(self.root, parsed, 14), [])

    def test_one_fix_touching_many_files_is_one_signal(self) -> None:
        self._repo(self.root)
        for name in ("a", "b", "c"):
            self._commit(self.root, f"src/{name}.ts", f"feat: add {name}")
        for name in ("a", "b", "c"):
            (self.root / "src" / f"{name}.ts").write_text("patched", encoding="utf-8")
        self._git(self.root, "add", "-A")
        self._git(self.root, "commit", "-q", "-m", "fix: repair all three")
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        found = cap.detect_defects(self.root, parsed, 14)
        self.assertEqual(len(found), 3, "one signal per origin commit, not per file")
        self.assertEqual(sorted(f for e in found for f in e["files"]),
                         ["src/a.ts", "src/b.ts", "src/c.ts"])

    def test_files_sharing_one_origin_collapse(self) -> None:
        self._repo(self.root)
        for name in ("a", "b"):
            (self.root / "src").mkdir(parents=True, exist_ok=True)
            (self.root / "src" / f"{name}.ts").write_text("1", encoding="utf-8")
        self._git(self.root, "add", "-A")
        self._git(self.root, "commit", "-q", "-m", "feat: add both")
        for name in ("a", "b"):
            (self.root / "src" / f"{name}.ts").write_text("2", encoding="utf-8")
        self._git(self.root, "add", "-A")
        self._git(self.root, "commit", "-q", "-m", "fix: repair both")
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        found = cap.detect_defects(self.root, parsed, 14)
        self.assertEqual(len(found), 1, "same fix, same origin, one signal")
        self.assertEqual(found[0]["count"], 2)
        self.assertEqual(found[0]["files"], ["src/a.ts", "src/b.ts"])

    def test_origin_must_predate_the_fix(self) -> None:
        """A change that landed after the fix cannot be its cause."""
        self._repo(self.root)
        self._commit(self.root, "src/thing.ts", "feat: first", body="1")
        self._commit(self.root, "src/thing.ts", "fix: the bug", body="2")
        self._commit(self.root, "src/thing.ts", "feat: later work", body="3")
        head = subprocess.run(["git", "log", "--pretty=%h", "-n", "3"], cwd=str(self.root),
                              capture_output=True, text=True).stdout.split()
        newest, _fix, oldest = head  # log is newest first
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        found = cap.detect_defects(self.root, parsed, 14)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["origin"], oldest)
        self.assertNotEqual(found[0]["origin"], newest)

    def test_subrepos_when_the_root_is_not_one(self) -> None:
        """gastarbajter's shape: the project root holds app/ and admin/."""
        for name in ("app", "admin"):
            sub = self.root / name
            sub.mkdir(parents=True, exist_ok=True)
            self._repo(sub)
            self._commit(sub, "src/thing.ts", "feat: add thing")
            self._commit(sub, "src/thing.ts", f"fix({name}): broke it", body="y")
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        found = cap.detect_defects(self.root, parsed, 14)
        paths = sorted(f for e in found for f in e["files"])
        self.assertEqual(paths, ["admin/src/thing.ts", "app/src/thing.ts"],
                         "paths carry the sub-repo so they stay project-relative")

    def test_root_repo_wins_over_subrepos(self) -> None:
        self._repo(self.root)
        self._commit(self.root, "src/a.ts", "feat: a")
        self._commit(self.root, "src/a.ts", "fix: a", body="y")
        sub = self.root / "app"
        sub.mkdir(parents=True, exist_ok=True)
        self._repo(sub)
        self._commit(sub, "src/b.ts", "feat: b")
        self._commit(sub, "src/b.ts", "fix: b", body="y")
        self.assertEqual(cap.git_roots(self.root), [(self.root, "")])
        parsed = self._parsed()
        parsed.started = "1970-01-01T00:00:00Z"
        paths = sorted(f for e in cap.detect_defects(self.root, parsed, 14) for f in e["files"])
        self.assertEqual(paths, ["src/a.ts"])

    def test_subrepo_scan_is_bounded(self) -> None:
        for i in range(cap.DEFECT_MAX_REPOS + 3):
            sub = self.root / f"r{i}"
            sub.mkdir(parents=True, exist_ok=True)
            self._repo(sub)
        self.assertEqual(len(cap.git_roots(self.root)), cap.DEFECT_MAX_REPOS)

    def test_no_repo_anywhere_is_silent(self) -> None:
        (self.root / "plain").mkdir(parents=True, exist_ok=True)
        self.assertEqual(cap.git_roots(self.root), [])

    def test_no_session_start_means_no_window(self) -> None:
        self._repo()
        self._commit(self.root, "src/thing.ts", "feat: add thing")
        self._commit(self.root, "src/thing.ts", "fix: broke it", body="y")
        parsed = self._parsed()
        parsed.started = ""
        self.assertEqual(cap.detect_defects(self.root, parsed, 14), [])


class EpisodeFromRealCaptureTests(unittest.TestCase):
    """The stamps a real capture produces, not hand-built records.

    A synthetic record can carry any timestamp. Capture stamping every record
    with the session end would collapse a week into one episode, and a unit
    test over hand-built records would never notice.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name) / "proj")
        self.tdir = Path(self.tmp.name) / "transcripts"
        self.tdir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_one_session_over_three_days_is_three_episodes(self) -> None:
        t = Transcript("marathon")
        for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
            t.at = f"{day}T10:00:00.000Z"
            t.result(t.tool("Bash", command="npm install left-pad"))
        path = t.write(self.tdir / "marathon.jsonl")
        rules = sig.load_rules(self.root)
        cap.capture_one(path, self.root, rules, sig.known_sessions(self.root))
        recs = [r for r in read_signals(self.root) if r["rule"] == "no-new-deps"]
        self.assertEqual(len(recs), 3)
        self.assertEqual(len(sig.episodes_of(recs)), 3, "one session, three days, three episodes")
        self.assertEqual(len({r["session_id"] for r in recs}), 1)


class EpisodeTests(unittest.TestCase):
    """Thresholds count session-days, so long sessions can cross them."""

    def _rec(self, sid: str, ts: str) -> dict:
        return sig.make_record(
            tool="claude-code", session_id=sid, kind="violation", rule="graph-first",
            detector="graph-first", confidence="deterministic", origin="transcript", ts=ts,
            evidence={"count": 1, "first_index": 0, "tools": ["Grep"], "proof": "mcp-later"},
        )

    def test_one_session_across_days_is_several_episodes(self) -> None:
        recs = [
            self._rec("long", "2026-09-01T10:00:00Z"),
            self._rec("long", "2026-09-02T10:00:00Z"),
            self._rec("long", "2026-09-03T10:00:00Z"),
        ]
        self.assertEqual(len(sig.episodes_of(recs)), 3)
        self.assertEqual(len({r["session_id"] for r in recs}), 1)

    def test_same_day_is_one_episode(self) -> None:
        recs = [
            self._rec("long", "2026-09-01T10:00:00Z"),
            self._rec("long", "2026-09-01T18:00:00Z"),
        ]
        self.assertEqual(len(sig.episodes_of(recs)), 1)

    def test_long_session_can_cross_a_threshold(self) -> None:
        rules = json.loads(SEED.read_text(encoding="utf-8"))
        rules["last_retro"] = None
        recs = [self._rec("long", f"2026-09-0{i}T10:00:00Z") for i in (1, 2, 3)]
        summary = sig.summarize(recs, rules)
        row = next(e for e in summary["per_rule"] if e["id"] == "graph-first")
        self.assertEqual(row["sessions"], 1)
        self.assertEqual(row["episodes"], 3)
        self.assertEqual(row["status"], "over_threshold")

    def test_episodes_since_advances_inside_a_session(self) -> None:
        sessions = {"long": {"evidence": {"started": "2026-09-01T09:00:00Z"}}}
        episodes = sig.episodes_of([
            self._rec("long", "2026-09-01T10:00:00Z"),
            self._rec("long", "2026-09-02T10:00:00Z"),
            self._rec("long", "2026-09-03T10:00:00Z"),
        ])
        last_retro = {"session_id": "long", "date": "2026-09-01T09:30:00Z", "captured_sessions": 1}
        # sessions_since sees one session it has already reviewed: zero forever.
        self.assertEqual(sig.sessions_since(sessions, last_retro), 0)
        # episodes_since keeps counting the days that followed.
        self.assertEqual(sig.episodes_since(episodes, sessions, last_retro), 3)


if __name__ == "__main__":
    unittest.main()
