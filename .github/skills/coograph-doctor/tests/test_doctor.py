"""coograph-doctor: every check, against real tiny projects.

One test per scenario in
openspec/changes/2026-10-23-coograph-doctor/specs/coograph-doctor/spec.md.
Each fault test starts from the passing fixture, breaks exactly one thing,
and asserts that only the named check changes.

Run:  python -m unittest discover -s .github/skills/coograph-doctor/tests -v
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))
# No __pycache__/ next to doctor.py: init copies .github/skills/ into projects.
sys.dont_write_bytecode = True

import doctor  # noqa: E402

HAS_GIT = shutil.which("git") is not None

FILLED_INSTRUCTIONS = (
    "# Copilot Instructions\n\n"
    "> **Template guard:** If any section below still contains `_TBD_` or "
    "`<!-- FILL -->`, stop and ask.\n\n"
    "## Stack\n\n| Component | Technology |\n|---|---|\n| Language | Python |\n"
)
HOOK = (
    "#!/bin/sh\nREPO_ROOT=$(git rev-parse --show-toplevel)\ncd \"$REPO_ROOT\" || exit 0\n"
    "if [ -f \".code-graph/graph.db\" ]; then\n"
    "    uv run --with-requirements .github/code-graph/requirements.txt "
    ".github/code-graph/server.py --update 2>/dev/null || true\nfi\n"
)
UV_ARGS = ["run", "-p", ">=3.10", "--with-requirements", ".github/code-graph/requirements.txt",
           ".github/code-graph/server.py"]


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _git(root: Path, *args: str, at: float | None = None) -> None:
    env = dict(os.environ)
    if at is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{int(at)} +0000"
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True, env=env)


def _commit(root: Path, rel: str, body: str, at: float) -> None:
    _write(root, rel, body)
    _git(root, "add", "-f", rel)  # -f: a global excludesfile may hide tooling folders
    _git(root, "commit", "-q", "-m", f"edit {rel}", at=at)


def build_graph(root: Path, functions: int = 3, calls: int = 2, edges: bool = True) -> Path:
    db = root / ".code-graph" / "graph.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, name TEXT, file TEXT, "
        "start_line INT, end_line INT);"
        "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT);"
    )
    conn.execute("INSERT INTO nodes VALUES ('f1','file','a.py','a.py',NULL,NULL)")
    for i in range(functions):
        conn.execute("INSERT INTO nodes VALUES (?, 'function', ?, 'a.py', 1, 2)",
                     (f"fn{i}", f"fn{i}"))
    if edges:
        conn.execute("INSERT INTO edges VALUES ('f1','fn0','contains')")
        for i in range(min(calls, functions - 1)):
            conn.execute("INSERT INTO edges VALUES (?, ?, 'calls')", (f"fn{i}", f"fn{i + 1}"))
    conn.commit()
    conn.close()
    return db


def make_project(base: Path, *, code_graph: bool = True, git: bool = True) -> tuple[Path, Path]:
    """A project as a fully enabled init leaves it (Claude Code + VS Code +
    OpenCode, code-graph, git hooks), and a registry listing it."""
    root = base / "proj"
    _write(root, ".github/copilot-instructions.md", FILLED_INSTRUCTIONS)
    _write(root, ".github/instructions/testing.instructions.md", "# Testing\n")
    _write(root, ".github/skills/coograph-init/SKILL.md", "---\nname: coograph-init\n---\n")
    _write(root, "AGENTS.md", "# Agent Context\n\nUse `make test`.\n")
    _write(root, "CLAUDE.md", "# Claude\n\n@AGENTS.md\n")
    _write(root, "openspec/config.yaml",
           "schema: spec-driven\n\nmodels:\n  mode: unset\n  # catalog:\n"
           "context: |\n  Tech stack: Python\n  : colon in a block scalar is fine\n")
    # Claude Code
    _write(root, ".claude/commands/coograph-init.md", "Follow the skill.\n")
    _write(root, ".claude/hooks/log-bash.py", "print('ok')\n")
    _write(root, ".claude/settings.json", json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command",
         "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/log-bash.py\""}]}]}}))
    # VS Code
    _write(root, ".github/agents/reviewer.agent.md", "# Reviewer\n")
    # OpenCode
    _write(root, ".opencode/commands/coograph-init.md", "Follow the skill.\n")
    if code_graph:
        _write(root, ".github/code-graph/server.py", "# server\n")
        _write(root, ".github/code-graph/requirements.txt", "mcp>=1.0.0,<2\n")
        _write(root, ".mcp.json", json.dumps({"mcpServers": {"code-graph": {
            "type": "stdio", "command": "uv", "args": UV_ARGS}}}))
        _write(root, ".vscode/mcp.json", json.dumps({"servers": {"code-graph": {
            "type": "stdio", "command": "uv",
            "args": [a.replace(".github", "${workspaceFolder}/.github") for a in UV_ARGS]}}}))
        _write(root, "opencode.json", json.dumps({
            "skills": {"paths": [".github/skills"]},
            "mcp": {"code-graph": {"type": "local", "command": ["uv", *UV_ARGS], "cwd": "."}}}))
    _write(root, ".coograph/sync-manifest.json", "{}")
    if git:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "init")
        hooks = root / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        if code_graph:
            for name in ("post-commit", "post-merge", "post-rewrite"):
                (hooks / name).write_text(HOOK, encoding="utf-8")
    if code_graph:
        build_graph(root)  # after the commit, so it is fresh
    registry = base / "projects.json"
    registry.write_text(json.dumps({"projects": [{
        "path": str(root), "tools": ["claude", "vscode", "opencode"],
        "code_graph": code_graph, "registered_at": "2026-10-23"}]}), encoding="utf-8")
    return root, registry


def statuses(results) -> dict[str, str]:
    return {r.check: r.status for r in results}


@unittest.skipUnless(HAS_GIT, "git not on PATH")
class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="coograph-doctor-"))
        self.root, self.registry = make_project(self.base)
        self.uv = mock.patch.object(doctor, "_which", lambda name: f"/usr/bin/{name}")
        self.uv.start()
        self.baseline = statuses(doctor.run(self.root, self.registry))

    def tearDown(self) -> None:
        self.uv.stop()
        shutil.rmtree(self.base, ignore_errors=True)

    def only(self, check: str, status: str) -> list:
        results = doctor.run(self.root, self.registry)
        got = statuses(results)
        self.assertEqual(status, got.get(check), [r for r in results if r.check == check])
        changed = {k for k in got if got[k] != self.baseline.get(k)}
        self.assertEqual({check}, changed, got)
        return [r for r in results if r.check == check]

    # -- the passing install ------------------------------------------------

    def test_fresh_full_init_passes(self):
        results = doctor.run(self.root, self.registry)
        bad = [r for r in results if r.status not in ("PASS", "SKIP")]
        self.assertEqual([], bad)
        for check in ("graph", "graph-age", "server", "mcp:claude", "mcp:vscode", "mcp:opencode",
                      "markers", "tools", "hooks:git", "openspec", "hooks:claude", "sync"):
            self.assertEqual("PASS", statuses(results).get(check), check)

    # -- one fault per category ---------------------------------------------

    def test_graph_missing(self):
        (self.root / ".code-graph" / "graph.db").unlink()
        got = statuses(doctor.run(self.root, self.registry))
        self.assertEqual("FAIL", got["graph"])
        self.assertEqual("SKIP", got["graph-age"])  # nothing left to date
        changed = {k for k in got if got[k] != self.baseline.get(k)}
        self.assertEqual({"graph", "graph-age"}, changed)

    def test_graph_without_edges(self):
        build_graph(self.root, edges=False)
        self.only("graph", "FAIL")

    def test_graph_without_calls_warns(self):
        build_graph(self.root, functions=60, calls=0)
        self.only("graph", "WARN")

    def test_code_commit_after_the_graph_warns(self):
        _commit(self.root, "a.py", "def fn0():\n    return 1\n", at=time.time() + 2 * 3600)
        (r,) = self.only("graph-age", "WARN")
        self.assertIn("a.py", r.detail)

    def test_docs_only_commit_after_the_graph_passes(self):
        """A docs-only commit leaves `--update` nothing to do: the db stays
        untouched and the graph is still current (review finding)."""
        _commit(self.root, "docs/guide.md", "# guide\n", at=time.time() + 2 * 3600)
        self.assertEqual("PASS", statuses(doctor.run(self.root, self.registry))["graph-age"])

    def test_commit_only_where_the_builder_never_looks_passes(self):
        """A coograph sync commit touches .github/ tooling and build output only;
        the builder skips both, so the graph is still current (review finding)."""
        later = time.time() + 2 * 3600
        _write(self.root, ".ci/tool.py", "x = 1\n")
        _write(self.root, "build/gen.py", "x = 1\n")
        _commit(self.root, ".github/retro/x.py", "x = 1\n", at=later)
        _git(self.root, "add", "-f", ".ci/tool.py", "build/gen.py")
        _git(self.root, "commit", "-q", "-m", "tooling", at=later)
        self.assertEqual("PASS", statuses(doctor.run(self.root, self.registry))["graph-age"])

    def test_commit_to_a_file_already_in_the_graph_warns(self):
        later = time.time() + 2 * 3600
        conn = sqlite3.connect(self.root / ".code-graph" / "graph.db")
        conn.execute("INSERT INTO nodes VALUES ('f2','file','gen.py','build/gen.py',NULL,NULL)")
        conn.commit()
        conn.close()
        os.utime(self.root / ".code-graph" / "graph.db", (time.time(), time.time()))
        _write(self.root, "build/gen.py", "x = 1\n")
        _git(self.root, "add", "-f", "build/gen.py")
        _git(self.root, "commit", "-q", "-m", "gen", at=later)
        (r,) = self.only("graph-age", "WARN")
        self.assertIn("build/gen.py", r.detail)

    def test_code_commit_within_tolerance_passes(self):
        _commit(self.root, "a.py", "def fn0():\n    return 1\n", at=time.time() + 600)
        self.assertEqual("PASS", statuses(doctor.run(self.root, self.registry))["graph-age"])

    def test_server_missing(self):
        (self.root / ".github" / "code-graph" / "server.py").unlink()
        results = doctor.run(self.root, self.registry)
        got = statuses(results)
        self.assertEqual("FAIL", got["server"])
        # every MCP config points at it, so they fail too; nothing else moves
        changed = {k for k in got if got[k] != self.baseline.get(k)}
        self.assertEqual({"server", "mcp:claude", "mcp:vscode", "mcp:opencode"}, changed)

    def test_uv_missing_fails_when_configs_use_it(self):
        with mock.patch.object(doctor, "_which", lambda name: None):
            got = statuses(doctor.run(self.root, self.registry))
        self.assertEqual("FAIL", got["server"])

    def test_mcp_claude_without_code_graph(self):
        _write(self.root, ".mcp.json", json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        self.only("mcp:claude", "FAIL")

    def test_workspace_variable_outside_vscode_fails(self):
        """Claude Code passes `${workspaceFolder}` on literally (review finding)."""
        _write(self.root, ".mcp.json", json.dumps({"mcpServers": {"code-graph": {
            "command": "python", "args": ["${workspaceFolder}/.github/code-graph/server.py"]}}}))
        (r,) = self.only("mcp:claude", "FAIL")
        self.assertIn("not expanded", r.detail)

    def test_mcp_opencode_dead_absolute_path(self):
        dead = str(self.base / "gone" / "server.py")
        _write(self.root, "opencode.json", json.dumps({
            "skills": {"paths": [".github/skills"]},
            "mcp": {"code-graph": {"type": "local", "command": ["uv", "run", dead]}}}))
        (r,) = self.only("mcp:opencode", "FAIL")
        self.assertIn("gone", r.detail)

    def test_marker_left_in_agents_md(self):
        _write(self.root, "AGENTS.md", "# Agent Context\n\n| Build | _TBD_ |\n")
        (r,) = self.only("markers", "FAIL")
        self.assertIn("AGENTS.md:3", r.detail)

    def test_registered_tool_files_missing(self):
        shutil.rmtree(self.root / ".github" / "agents")
        (r,) = self.only("tools", "FAIL")
        self.assertIn("vscode", r.detail)

    def test_claude_md_import_needs_agents_md(self):
        (self.root / "AGENTS.md").unlink()
        (r,) = self.only("tools", "FAIL")
        self.assertIn("claude: AGENTS.md", r.detail)

    def test_self_contained_claude_md_needs_no_agents_md(self):
        """Found on 4 registered projects: an older CLAUDE.md holds the rules itself."""
        data = json.loads(self.registry.read_text(encoding="utf-8"))
        data["projects"][0]["tools"] = ["claude"]
        self.registry.write_text(json.dumps(data), encoding="utf-8")
        shutil.rmtree(self.root / ".github" / "agents")
        shutil.rmtree(self.root / ".opencode")
        (self.root / "opencode.json").unlink()
        (self.root / ".vscode" / "mcp.json").unlink()
        (self.root / "AGENTS.md").unlink()
        _write(self.root, "CLAUDE.md", "# Claude\n\n> HARD RULE: code-graph first.\n")
        got = statuses(doctor.run(self.root, self.registry))
        self.assertEqual("PASS", got["tools"])

    def test_unregistered_tool_on_disk_warns(self):
        _write(self.root, ".cursor/rules/coograph.mdc", "# rules\n")
        (r,) = self.only("tools", "WARN")
        self.assertIn("cursor", r.detail)

    def test_other_tools_skills_are_not_a_codex_install(self):
        """Found on coograph-website: .agents/skills/ held Firebase skills."""
        _write(self.root, ".agents/skills/firebase-basics/SKILL.md", "# firebase\n")
        _write(self.root, ".github/agents/my-own.agent.md", "# mine\n")
        self.assertEqual(self.baseline, statuses(doctor.run(self.root, self.registry)))
        _write(self.root, ".agents/skills/coograph-init/SKILL.md", "# coograph\n")
        (r,) = self.only("tools", "WARN")
        self.assertIn("codex", r.detail)

    def test_unknown_tool_id_warns(self):
        data = json.loads(self.registry.read_text(encoding="utf-8"))
        data["projects"][0]["tools"].append("emacs")
        self.registry.write_text(json.dumps(data), encoding="utf-8")
        (r,) = self.only("tools", "WARN")
        self.assertIn("emacs", r.detail)

    def test_post_merge_hook_missing_warns(self):
        (self.root / ".git" / "hooks" / "post-merge").unlink()
        self.only("hooks:git", "WARN")

    def test_openspec_config_with_tab_fails(self):
        _write(self.root, "openspec/config.yaml", "schema: spec-driven\nmodels:\n\tmode: unset\n")
        with mock.patch.object(doctor, "yaml", None):
            self.only("openspec", "FAIL")

    def test_openspec_config_passes_without_pyyaml(self):
        with mock.patch.object(doctor, "yaml", None):
            results = doctor.run(self.root, self.registry)
        (r,) = [r for r in results if r.check == "openspec"]
        self.assertEqual("PASS", r.status)
        self.assertIn("structural check", r.detail)

    def test_openspec_config_missing_fails(self):
        (self.root / "openspec" / "config.yaml").unlink()
        self.only("openspec", "FAIL")

    def test_claude_settings_wire_a_missing_hook(self):
        (self.root / ".claude" / "hooks" / "log-bash.py").unlink()
        (r,) = self.only("hooks:claude", "FAIL")
        self.assertIn("log-bash.py", r.detail)

    def test_braced_hook_variable_is_checked_too(self):
        _write(self.root, ".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/hooks/gone.py\""},
            {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/log-bash.py\""},
        ]}]}}))
        (r,) = self.only("hooks:claude", "FAIL")
        self.assertIn("gone.py", r.detail)

    def test_registry_false_does_not_hide_an_installed_graph(self):
        """Spec R5: code-graph is off only with no .github/code-graph/ AND no `true`."""
        data = json.loads(self.registry.read_text(encoding="utf-8"))
        data["projects"][0]["code_graph"] = False
        self.registry.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.baseline, statuses(doctor.run(self.root, self.registry)))

    def test_unregistered_project_says_so(self):
        other = self.base / "other.json"
        other.write_text(json.dumps({"projects": []}), encoding="utf-8")
        (r,) = [r for r in doctor.run(self.root, other) if r.check == "tools"]
        self.assertIn("not in projects.json", r.detail)

    def test_parked_upstream_copy_warns(self):
        _write(self.root, ".coograph/upstream/.claude/hooks/warn-scope.py", "# upstream\n")
        (r,) = self.only("sync", "WARN")
        self.assertIn("warn-scope.py", r.detail)

    # -- output, exit codes, read-only --------------------------------------

    def test_every_problem_has_a_fix(self):
        (self.root / ".code-graph" / "graph.db").unlink()
        _write(self.root, "AGENTS.md", "_TBD_\n")
        for r in doctor.run(self.root, self.registry):
            if r.status in ("WARN", "FAIL"):
                self.assertTrue(r.fix, r)

    def test_text_output_and_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.main(["--project", str(self.root), "--registry", str(self.registry)])
        self.assertEqual(0, code)
        text = out.getvalue()
        self.assertRegex(text, r"(?m)^PASS\s+graph\s")
        self.assertRegex(text, r"(?m)^Summary: \d+ PASS, 0 WARN, 0 FAIL, \d+ SKIP$")

        (self.root / ".code-graph" / "graph.db").unlink()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.main(["--project", str(self.root), "--registry", str(self.registry)])
        self.assertEqual(1, code)
        self.assertRegex(out.getvalue(), r"(?m)^FAIL\s+graph\s.*\n\s+fix: ")

    def test_json_output(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            doctor.main(["--project", str(self.root), "--registry", str(self.registry), "--json"])
        data = json.loads(out.getvalue())
        self.assertEqual(0, data["summary"]["FAIL"])
        self.assertIn({"status", "check", "detail", "fix"}, [set(r) for r in data["results"]])

    def test_usage_errors_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, doctor.main(["--project", str(self.base / "nope")]))
            self.assertEqual(2, doctor.main(["--project", str(self.root),
                                             "--registry", str(self.base / "nope.json")]))
            bad = self.base / "bad.json"
            bad.write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(2, doctor.main(["--project", str(self.root), "--registry", str(bad)]))

    def test_read_only(self):
        def snapshot() -> dict[str, tuple[float, str]]:
            out = {}
            for p in self.root.rglob("*"):
                if p.is_file():
                    out[str(p)] = (p.stat().st_mtime, hashlib.sha1(p.read_bytes()).hexdigest())
            return out
        before = snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            doctor.main(["--project", str(self.root), "--registry", str(self.registry), "--json"])
        self.assertEqual(before, snapshot())


@unittest.skipUnless(HAS_GIT, "git not on PATH")
class ModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="coograph-doctor-mode-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_optional_features_off_skip(self):
        root, registry = make_project(self.base, code_graph=False, git=False)
        with mock.patch.object(doctor, "_which", lambda name: None):
            results = doctor.run(root, registry)
        got = statuses(results)
        for check in ("graph", "graph-age", "server", "hooks:git"):
            self.assertEqual("SKIP", got[check], check)
        self.assertFalse([k for k in got if k.startswith("mcp:") and got[k] != "SKIP"], got)
        self.assertFalse([r for r in results if r.status == "FAIL"], results)

    def test_template_checkout_skips_markers(self):
        root, registry = make_project(self.base)
        _write(root, "setup.sh", "#!/bin/sh\n")
        _write(root, "templates/aider/CONVENTIONS.md", "# conv\n")
        _write(root, "AGENTS.md", "| Build | _TBD_ |\n")
        (root / "opencode.json").unlink()  # .opencode/ is a template source here
        with mock.patch.object(doctor, "_which", lambda name: "/usr/bin/uv"):
            got = statuses(doctor.run(root, registry))
        self.assertEqual("SKIP", got["markers"])
        self.assertEqual("SKIP", got["mcp:opencode"])
        self.assertEqual("PASS", got["mcp:claude"])

    def test_no_registry_detects_tools_from_disk(self):
        root, _ = make_project(self.base)
        with mock.patch.object(doctor, "_which", lambda name: "/usr/bin/uv"), \
             mock.patch.object(doctor, "_own_registry", lambda: None):
            results = doctor.run(root, None)
        (r,) = [r for r in results if r.check == "tools"]
        self.assertEqual("PASS", r.status)
        self.assertIn("detected from disk", r.detail)
        self.assertIn("claude", r.detail)

    def test_multi_repo_workspace_dates_the_graph_by_its_child_repos(self):
        """wisehosting: a workspace root that is no repo, holding several."""
        ws = self.base / "ws"
        _write(ws, ".github/code-graph/server.py", "# server\n")
        _write(ws, ".github/code-graph/requirements.txt", "mcp\n")
        child = ws / "api"
        _write(child, "a.py", "def fn0():\n    return 1\n")
        subprocess.run(["git", "init", "-q", str(child)], check=True)
        _git(child, "add", "-A")
        _git(child, "commit", "-q", "-m", "init", at=time.time() - 3 * 3600)
        build_graph(ws)
        with mock.patch.object(doctor, "_which", lambda name: "/usr/bin/uv"):
            self.assertEqual("PASS", statuses(doctor.run(ws, None))["graph-age"])
            _commit(child, "a.py", "def fn0():\n    return 2\n", at=time.time() + 2 * 3600)
            results = doctor.run(ws, None)
        (r,) = [r for r in results if r.check == "graph-age"]
        self.assertEqual("WARN", r.status)
        self.assertIn("api/a.py", r.detail)

    def test_devin_and_windsurf_ids_are_one_tool(self):
        root, registry = make_project(self.base)
        _write(root, ".windsurfrules", "# rules\n")
        data = json.loads(registry.read_text(encoding="utf-8"))
        data["projects"][0]["tools"].append("windsurf")
        registry.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(doctor, "_which", lambda name: "/usr/bin/uv"):
            got = statuses(doctor.run(root, registry))
        self.assertEqual("PASS", got["tools"])


if __name__ == "__main__":
    unittest.main()
