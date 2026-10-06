"""Tests for .github/sync.py: a project's local edits survive a sync.

Run:  python -m unittest discover -s .github/layout/tests

Each test points sync at a throwaway template root with its own git history,
so the result does not depend on the coograph checkout's depth (CI clones
with --depth 1).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
sys.dont_write_bytecode = True

HOOK = ".claude/hooks/warn-scope.py"
SETTINGS = ".claude/settings.json"
WORKFLOW_SRC = ".github/layout/coograph-layout.yml"
WORKFLOW_DST = ".github/workflows/coograph-layout.yml"
DASH = "—"


def _load_sync():
    root = logging.getLogger()
    before = list(root.handlers)
    spec = importlib.util.spec_from_file_location("coograph_sync_edits", REPO / ".github" / "sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # sync.py logs to stdout and the real .github/sync.log at import: detach.
    for handler in [h for h in root.handlers if h not in before]:
        root.removeHandler(handler)
        handler.close()
    return module


sync = _load_sync()


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _rmtree(path: Path) -> None:
    """git marks objects read-only; Windows refuses to delete those."""
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


class _SyncCase(unittest.TestCase):
    """A template root with its own git history, and an empty project."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-test-")).resolve()
        self.template = self.tmp / "template"
        self.project = self.tmp / "project"
        (self.project / "openspec").mkdir(parents=True)
        self.template.mkdir()
        _git(self.template, "init", "-q")
        self._saved = (sync.TEMPLATE_ROOT, sync._HISTORY)
        sync.TEMPLATE_ROOT = self.template

    def tearDown(self) -> None:
        sync.TEMPLATE_ROOT, sync._HISTORY = self._saved
        _rmtree(self.tmp)

    # helpers ---------------------------------------------------------------

    def release(self, files: dict[str, str]) -> None:
        """Commit a template version; history is re-read on the next sync."""
        for rel, text in files.items():
            path = self.template / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        _git(self.template, "add", "-A", "-f")  # a global excludesfile may drop .claude/
        _git(self.template, "commit", "-qm", "release")
        sync._HISTORY = sync._History(self.template)

    def run_sync(self, dry_run: bool = False) -> list[str]:
        project = {"path": str(self.project), "tools": ["claude"], "code_graph": False}
        with self.assertLogs("code-graph.sync", level="INFO") as logs:
            self.assertTrue(sync.sync_project(project, dry_run=dry_run))
        return logs.output

    def read(self, rel: str) -> str:
        return (self.project / rel).read_bytes().decode("utf-8")

    def write(self, rel: str, text: str) -> None:
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def kept_lines(self, output: list[str]) -> list[str]:
        return [line for line in output if "KEPT " in line]


@unittest.skipUnless(shutil.which("git"), "git not installed")
class SyncKeepsLocalEditsTests(_SyncCase):
    def setUp(self) -> None:
        super().setUp()
        self.release({HOOK: "hook v1\n", SETTINGS: '{"v": 1}\n', WORKFLOW_SRC: "# coograph:managed\nv1\n"})


    def test_untouched_file_refreshed(self) -> None:
        self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v1\n")
        manifest = json.loads((self.project / ".coograph/sync-manifest.json").read_text(encoding="utf-8"))
        self.assertIn(HOOK, manifest["files"])
        self.release({HOOK: "hook v2\n"})
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v2\n")
        self.assertEqual(self.kept_lines(out), [])

    def test_edited_file_kept_and_reported(self) -> None:
        self.run_sync()
        self.write(HOOK, "hook v1 with a local fix\n")
        self.release({HOOK: "hook v2\n"})
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v1 with a local fix\n")
        self.assertEqual(self.read(f".coograph/upstream/{HOOK}"), "hook v2\n")
        kept = self.kept_lines(out)
        self.assertEqual(len(kept), 1)
        self.assertIn(f"KEPT {HOOK} (local edit)", kept[0])
        self.assertIn(f".coograph/upstream/{HOOK}", kept[0])
        self.assertTrue(any("1 kept (local edits)" in line for line in out))
        # Kept again on the next run, still reported: never silently dropped.
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v1 with a local fix\n")
        self.assertEqual(len(self.kept_lines(out)), 1)

    def test_taking_upstream_clears_the_report(self) -> None:
        self.run_sync()
        self.write(HOOK, "local\n")
        self.release({HOOK: "hook v2\n"})
        self.run_sync()
        shutil.copyfile(self.project / ".coograph/upstream" / HOOK, self.project / HOOK)
        out = self.run_sync()
        self.assertEqual(self.kept_lines(out), [])
        self.assertFalse((self.project / ".coograph/upstream" / HOOK).exists())
        self.release({HOOK: "hook v3\n"})
        self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v3\n")

    def test_first_sync_onto_customised_file_keeps_it(self) -> None:
        self.write(SETTINGS, '{"mine": true}\n')
        out = self.run_sync()
        self.assertEqual(self.read(SETTINGS), '{"mine": true}\n')
        self.assertEqual(len(self.kept_lines(out)), 1)
        self.assertEqual(self.read(f".coograph/upstream/{SETTINGS}"), '{"v": 1}\n')

    def test_first_sync_onto_outdated_untouched_file_refreshes_it(self) -> None:
        """No manifest yet (a project synced before this change): a file equal to
        an earlier upstream version is outdated, not edited."""
        self.write(HOOK, "hook v1\r\n")  # autocrlf checkout of v1
        self.release({HOOK: "hook v2\n"})
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v2\n")
        self.assertEqual(self.kept_lines(out), [])

    def test_crlf_checkout_is_not_an_edit(self) -> None:
        self.run_sync()
        self.write(HOOK, "hook v1\r\n")
        self.release({HOOK: "hook v2\n"})
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "hook v2\n")
        self.assertEqual(self.kept_lines(out), [])

    def test_deleted_marker_respected(self) -> None:
        self.write(WORKFLOW_DST, "name: mine\non: push\n")
        out = self.run_sync()
        self.assertEqual(self.read(WORKFLOW_DST), "name: mine\non: push\n")
        self.assertTrue(any("kept (customized" in line for line in out))

    def test_managed_workflow_refreshed_and_edit_with_marker_kept(self) -> None:
        self.write(WORKFLOW_DST, "# coograph:managed\nv1\n")
        self.release({WORKFLOW_SRC: "# coograph:managed\nv2\n"})
        self.run_sync()
        self.assertEqual(self.read(WORKFLOW_DST), "# coograph:managed\nv2\n")
        self.write(WORKFLOW_DST, "# coograph:managed\nv2 plus a local step\n")
        self.release({WORKFLOW_SRC: "# coograph:managed\nv3\n"})
        out = self.run_sync()
        self.assertEqual(self.read(WORKFLOW_DST), "# coograph:managed\nv2 plus a local step\n")
        self.assertEqual(len(self.kept_lines(out)), 1)

    def test_dry_run_writes_nothing(self) -> None:
        self.write(SETTINGS, '{"mine": true}\n')
        out = self.run_sync(dry_run=True)
        self.assertEqual(len(self.kept_lines(out)), 1)
        self.assertFalse((self.project / HOOK).exists())
        self.assertFalse((self.project / ".coograph").exists())

    def test_without_git_history_edits_are_still_kept(self) -> None:
        nogit = self.tmp / "nogit"  # not a repository: no history to read
        nogit.mkdir()
        sync._HISTORY = sync._History(nogit)
        self.write(HOOK, "something else\n")
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "something else\n")
        self.assertEqual(len(self.kept_lines(out)), 1)

    def test_unreadable_file_is_never_overwritten(self) -> None:
        """A path sync cannot read is not "missing": it is left alone, and the
        rest of the run goes on."""
        (self.project / HOOK).mkdir(parents=True)  # reading a directory fails everywhere
        out = self.run_sync()
        self.assertTrue((self.project / HOOK).is_dir())
        self.assertTrue(any(f"SKIPPED {HOOK}" in line for line in out))
        self.assertEqual(self.read(SETTINGS), '{"v": 1}\n')  # the run continued

    def test_unwritable_file_does_not_abort_the_run(self) -> None:
        saved = sync.ProjectSync._write

        def failing(state, src, dst, data, raw):
            if dst.name == "warn-scope.py":
                raise PermissionError("locked")
            return saved(state, src, dst, data, raw)

        sync.ProjectSync._write = failing
        try:
            out = self.run_sync()
        finally:
            sync.ProjectSync._write = saved
        self.assertTrue(any(f"SKIPPED {HOOK}" in line for line in out))
        self.assertFalse((self.project / HOOK).exists())
        self.assertEqual(self.read(SETTINGS), '{"v": 1}\n')
        manifest = json.loads((self.project / ".coograph/sync-manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn(HOOK, manifest["files"])  # never record what is not on disk

    def test_history_reader_skips_non_blob_objects(self) -> None:
        """git cat-file --batch prints a body for every object type; a commit
        in the input must not knock the parser out of step."""
        commit = _git(self.template, "rev-parse", "HEAD")
        blob = _git(self.template, "rev-parse", f"HEAD:{HOOK}")
        found = sync._History(self.template)._cat([commit, "0" * 40, blob])
        self.assertEqual(found, {blob: b"hook v1\n"})

    @unittest.skipIf(os.name == "nt", "no executable bit on Windows")
    def test_mode_kept_on_rendered_write(self) -> None:
        (self.template / HOOK).chmod(0o755)
        self.write("openspec/config.yaml", "sync:\n  em_dash: hyphen\n")
        self.release({HOOK: f"a {DASH} b\n"})
        self.run_sync()
        self.assertTrue(os.stat(self.project / HOOK).st_mode & stat.S_IXUSR)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class EmDashSettingTests(_SyncCase):
    def config(self, text: str) -> None:
        self.write("openspec/config.yaml", text)

    def test_setting_parsed(self) -> None:
        self.assertEqual(sync._project_em_dash(self.project), "keep")
        self.config("context: x\nsync:\n  # house style\n  em_dash: hyphen  # no U+2014\nmodels:\n  mode: off\n")
        self.assertEqual(sync._project_em_dash(self.project), "hyphen")
        self.config("sync:\n  em_dash: keep\n")
        self.assertEqual(sync._project_em_dash(self.project), "keep")
        self.config("sync:\nother:\n  em_dash: hyphen\n")
        self.assertEqual(sync._project_em_dash(self.project), "keep")

    def test_hyphen_normalises_and_keeps_syncing(self) -> None:
        self.config("sync:\n  em_dash: hyphen\n")
        self.release({HOOK: f"a {DASH} b\n", SETTINGS: f'{{"t": "x{DASH}y"}}\n'})
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "a - b\n")
        self.assertEqual(self.read(SETTINGS), '{"t": "x-y"}\n')
        self.release({HOOK: f"a {DASH} c\n"})
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "a - c\n")
        self.assertEqual(self.kept_lines(out), [])

    def test_hyphen_recognises_a_hand_normalised_old_version(self) -> None:
        """A project that normalised synced files by hand, before the setting."""
        self.release({HOOK: f"a {DASH} b\n"})
        self.write(HOOK, "a - b\n")
        self.release({HOOK: f"a {DASH} c\n"})
        self.config("sync:\n  em_dash: hyphen\n")
        out = self.run_sync()
        self.assertEqual(self.read(HOOK), "a - c\n")
        self.assertEqual(self.kept_lines(out), [])

    def test_hyphen_leaves_binary_files_alone(self) -> None:
        self.config("sync:\n  em_dash: hyphen\n")
        blob = b"\xff\xfe" + DASH.encode("utf-8") + b"\x00"
        path = self.template / ".claude/hooks/blob.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        self.release({})
        self.run_sync()
        self.assertEqual((self.project / ".claude/hooks/blob.bin").read_bytes(), blob)

    def test_keep_copies_bytes(self) -> None:
        self.release({HOOK: f"a {DASH} b\n"})
        self.run_sync()
        self.assertEqual(self.read(HOOK), f"a {DASH} b\n")


class ProjectFlagTests(unittest.TestCase):
    def test_unregistered_project_exits_2(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="sync-flag-")).resolve()
        saved = sync.PROJECTS_FILE
        try:
            sync.PROJECTS_FILE = tmp / "projects.json"
            sync.PROJECTS_FILE.write_text(json.dumps({"projects": []}), encoding="utf-8")
            with self.assertLogs("code-graph.sync", level="ERROR"):
                self.assertEqual(sync.main(["--project", str(tmp), "--dry-run"]), 2)
        finally:
            sync.PROJECTS_FILE = saved
            shutil.rmtree(tmp, ignore_errors=True)

    def test_registered_project_only(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="sync-flag-")).resolve()
        saved = (sync.PROJECTS_FILE, sync.sync_project)
        seen: list[str] = []
        try:
            (tmp / "a").mkdir()
            (tmp / "b").mkdir()
            sync.PROJECTS_FILE = tmp / "projects.json"
            sync.PROJECTS_FILE.write_text(json.dumps({"projects": [
                {"path": str(tmp / "a")}, {"path": str(tmp / "b")}]}), encoding="utf-8")
            sync.sync_project = lambda p, dry_run=False: seen.append(p["path"]) or True
            with self.assertLogs("code-graph.sync", level="INFO"):
                self.assertEqual(sync.main(["--project", str(tmp / "b" / ".." / "b"), "--dry-run"]), 0)
            self.assertEqual(seen, [str(tmp / "b")])
        finally:
            sync.PROJECTS_FILE, sync.sync_project = saved
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
