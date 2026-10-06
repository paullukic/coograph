"""Tests for .github/layout/layout.py and the sync rules that protect project files.

Run:  python -m unittest discover -s .github/layout/tests
"""
from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUT_DIR = HERE.parent
REPO = LAYOUT_DIR.parent.parent
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


layout = _load("coograph_layout", LAYOUT_DIR / "layout.py")


class Project:
    """A throwaway project directory. No git unless git() is called."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="layout-test-"))

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def git(self, *args: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t",
             "-c", "commit.gpgsign=false", *args],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    def config(self) -> dict:
        return layout.load_config(self.root)[0]

    def measure(self) -> dict:
        return layout.measure(self.root, self.config(), "test")

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


GOTCHA = """# Gotchas

```markdown
## example-entry
- **Symptom:** inside a fence, never parsed
```

## expo-env
- **Symptom:** `expo export` uses the old API URL
- **Cause:** `.env` wins over the shell for `expo export`.
- **Fix / rule:** change `.env.production`, never the shell.
- **paths:** `apps/mobile/**`, `app.config.ts`
- **commands:** `expo export`
- **confirmed:** 2026-10-01
"""


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()

    def tearDown(self) -> None:
        self.p.close()


class ConfigTests(Base):
    def test_defaults_equal_seed(self) -> None:
        seed = json.loads((LAYOUT_DIR / "layout.seed.json").read_text(encoding="utf-8"))
        self.assertEqual(seed, layout.DEFAULTS)

    def test_merge_keeps_local_values(self) -> None:
        target = self.p.write(".github/layout/layout.json", json.dumps({
            "budgets": {"always_loaded": 12000}, "always_loaded": ["CLAUDE.md"],
        }))
        added = layout.merge_seed(target, LAYOUT_DIR / "layout.seed.json")
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["budgets"]["always_loaded"], 12000)
        self.assertEqual(data["always_loaded"], ["CLAUDE.md"])
        self.assertEqual(data["structural_factor"], 1.25)
        self.assertIn("structural_factor", added)
        self.assertIn("budgets.router", added)

    def test_merge_leaves_complete_file_byte_identical(self) -> None:
        target = self.p.root / ".github/layout/layout.json"
        target.parent.mkdir(parents=True)
        body = b"\xef\xbb\xbf" + json.dumps(layout.DEFAULTS, indent=4).encode("utf-8") + b"\r\n"
        target.write_bytes(body)
        self.assertEqual(layout.merge_seed(target, LAYOUT_DIR / "layout.seed.json"), [])
        self.assertEqual(target.read_bytes(), body)

    def test_merge_creates_from_seed(self) -> None:
        target = self.p.root / ".github/layout/layout.json"
        layout.merge_seed(target, LAYOUT_DIR / "layout.seed.json")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), layout.DEFAULTS)

    def test_invalid_config_exits_2(self) -> None:
        self.p.write(".github/layout/layout.json", json.dumps({"budgets": {"router": -1}}))
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 2)

    def test_no_config_uses_seed(self) -> None:
        self.assertEqual(layout.load_config(self.p.root)[1], "seed defaults")


class GlobTests(unittest.TestCase):
    def test_globs(self) -> None:
        cases = [
            ("apps/mobile/**", "apps/mobile/app.json", True),
            ("apps/mobile/**", "apps/web/x.ts", False),
            ("*/AGENTS.md", "apps/AGENTS.md", True),
            ("*/AGENTS.md", "AGENTS.md", False),
            ("*/AGENTS.md", "apps/web/AGENTS.md", False),
            ("**/*.lock", "yarn.lock", True),
            ("**/*.lock", "a/b/Cargo.lock", True),
            ("app.config.ts", "apps/mobile/app.config.ts", True),
            ("docs/features/*.md", "docs/features/auth.md", True),
            ("apps/web/src/**/*.{ts,tsx}", "apps/web/src/a/b.tsx", True),
            ("apps/web/src/**/*.{ts,tsx}", "apps/web/src/a.ts", True),
            ("apps/web/src/**/*.{ts,tsx}", "apps/web/src/a.js", False),
            ("{apps,packages}/*/AGENTS.md", "packages/core/AGENTS.md", True),
            ("odd{brace.md", "odd{brace.md", True),
        ]
        for pattern, rel, want in cases:
            with self.subTest(pattern=pattern, rel=rel):
                self.assertEqual(layout.path_matches(pattern, rel), want)


class BudgetTests(Base):
    def test_imports_followed_once_and_cycle_ends(self) -> None:
        self.p.write("CLAUDE.md", "@AGENTS.md\n@.github/copilot-instructions.md\n")
        self.p.write("AGENTS.md", "rules\n@CLAUDE.md\n")
        self.p.write(".github/copilot-instructions.md", "conventions\n")
        files = [f["file"] for f in self.p.measure()["tiers"]["always_loaded"]["files"]]
        self.assertEqual(sorted(files), sorted(["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"]))
        self.assertEqual(len(files), len(set(files)))

    def test_import_outside_always_loaded_list_is_counted(self) -> None:
        self.p.write("CLAUDE.md", "See @docs/extra.md for more.\n")
        self.p.write("docs/extra.md", "x" * 400)
        m = self.p.measure()
        a = m["tiers"]["always_loaded"]
        self.assertIn("docs/extra.md", [f["file"] for f in a["files"]])
        self.assertEqual(a["total"], 100 + len("See @docs/extra.md for more.\n") // 4)

    def test_fenced_and_inline_code_imports_ignored(self) -> None:
        self.p.write("CLAUDE.md", "```\n@secret.md\n```\nuse `@inline.md` literally\n")
        self.p.write("secret.md", "s")
        self.p.write("inline.md", "i")
        files = [f["file"] for f in self.p.measure()["tiers"]["always_loaded"]["files"]]
        self.assertEqual(files, ["CLAUDE.md"])

    def test_import_depth_capped(self) -> None:
        self.p.write("CLAUDE.md", "@a1.md\n")
        for i in range(1, 7):
            self.p.write(f"a{i}.md", f"@a{i + 1}.md\n")
        files = {f["file"] for f in self.p.measure()["tiers"]["always_loaded"]["files"]}
        self.assertIn("a4.md", files)
        self.assertNotIn("a5.md", files)

    def test_agent_mentions_are_not_missing_imports(self) -> None:
        self.p.write("AGENTS.md", "| `@Reviewer` | x |\nask @Planner, see @gone.md\n")
        missing = self.p.measure()["tiers"]["always_loaded"]["missing_imports"]
        self.assertEqual(missing, [{"file": "AGENTS.md", "import": "gone.md"}])

    def test_monorepo_router_over_budget(self) -> None:
        self.p.write("AGENTS.md", "root\n")
        self.p.write("apps/web/AGENTS.md", "x" * 12000)
        m = self.p.measure()
        over = [o for o in m["over"] if o["file"] == "apps/web/AGENTS.md"]
        self.assertEqual(over[0]["tokens"], 3000)
        self.assertEqual(over[0]["tier"], "router")
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 1)

    def test_within_budget_exits_0(self) -> None:
        self.p.write("CLAUDE.md", "small\n")
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 0)

    def test_always_loaded_over_budget(self) -> None:
        self.p.write("CLAUDE.md", "x" * 40000)  # 10 000 tokens: over 9000, under 9000 * 1.25
        m = self.p.measure()
        self.assertTrue(m["tiers"]["always_loaded"]["over"])
        self.assertEqual(m["over"][0]["tier"], "always_loaded")
        self.assertFalse(m["structural"])
        self.p.write("CLAUDE.md", "x" * 50000)  # 12 500 tokens: over the structural line
        self.assertTrue(self.p.measure()["structural"])

    def test_router_over_budget_is_named(self) -> None:
        self.p.write("apps/web/AGENTS.md", "x" * 12000)
        out = io.StringIO()
        with redirect_stdout(out):
            layout.main(["--cwd", str(self.p.root), "--budget"])
        self.assertIn("OVER  router  apps/web/AGENTS.md  3000 > 2000", out.getvalue())
        self.assertIn("config from seed defaults", out.getvalue())

    def test_missing_import_fails(self) -> None:
        self.p.write("CLAUDE.md", "@AGENTS.md\n")
        out = io.StringIO()
        with redirect_stdout(out):
            code = layout.main(["--cwd", str(self.p.root), "--budget"])
        self.assertEqual(code, 1)
        self.assertIn("MISSING import @AGENTS.md in CLAUDE.md", out.getvalue())

    def test_unparseable_config_exits_2(self) -> None:
        self.p.write(".github/layout/layout.json", "{not json")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 2)

    def test_mixed_fences_and_double_backticks(self) -> None:
        self.p.write("CLAUDE.md", "```\n~~~\n@hidden.md\n```\n@shown.md\nuse ``@literal.md`` here\n")
        for name in ("hidden.md", "shown.md", "literal.md"):
            self.p.write(name, "x")
        files = sorted(f["file"] for f in self.p.measure()["tiers"]["always_loaded"]["files"])
        self.assertEqual(files, ["CLAUDE.md", "shown.md"])

    def test_frontmatter_column_zero_list_and_bom(self) -> None:
        self.assertEqual(layout.frontmatter_paths("---\npaths:\n- apps/**\n- lib/**\ntitle: x\n---\n"),
                         ["apps/**", "lib/**"])
        path = self.p.root / "docs/features/a.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xef\xbb\xbf---\npaths: [\"a/**\"]\n---\n# A\n")
        self.assertEqual(self.p.measure()["tiers"]["doc"]["without_paths"], [])

    def test_package_names_in_prose_are_not_missing_imports(self) -> None:
        self.p.write(".github/copilot-instructions.md",
                     "Use @tanstack/react-query for server state and @angular/core v17. Ping @x.y.\n")
        self.assertEqual(self.p.measure()["tiers"]["always_loaded"]["missing_imports"], [])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 0)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_gitignored_router_is_still_measured(self) -> None:
        """Instruction files kept out of git (global excludesfile) still load."""
        self.p.git("init", "-q")
        self.p.write(".gitignore", "AGENTS.md\n")
        self.p.write("apps/web/AGENTS.md", "x" * 12000)
        self.assertNotIn("apps/web/AGENTS.md", layout.list_files(self.p.root))
        self.assertIn("apps/web/AGENTS.md", [o["file"] for o in self.p.measure()["over"]])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 1)

    def test_doc_without_paths_reported(self) -> None:
        self.p.write("docs/features/auth.md", "# Auth\n")
        self.p.write("docs/features/billing.md", "---\npaths:\n  - apps/billing/**\n---\n# Billing\n")
        m = self.p.measure()
        self.assertEqual(m["tiers"]["doc"]["without_paths"], ["docs/features/auth.md"])


class StructureTests(Base):
    def test_changelog_map_is_structural(self) -> None:
        self.p.write("apps/web/AGENTS.md", "\n".join([
            "# Web",
            "## Login (openspec 2026-09-01-login)",
            "## Signup (2026-09-03)",
            "## Reset (2026-09-05)",
            "```",
            "## 2026-01-01 inside a fence",
            "```",
        ]))
        m = self.p.measure()
        self.assertEqual(m["dated_headings"][0]["file"], "apps/web/AGENTS.md")
        self.assertEqual(m["dated_headings"][0]["count"], 3)
        self.assertTrue(m["structural"])

    def test_duplicate_paragraph_across_root_files(self) -> None:
        rule = "Any change that modifies two or more files must go through an approved OpenSpec " \
               "before code is written, with no exemptions beyond the literal list."
        self.p.write("CLAUDE.md", f"# C\n\n{rule}\n")
        self.p.write("AGENTS.md", f"# A\n\n{rule}\n")
        dup = self.p.measure()["duplicate_paragraphs"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0]["files"], ["AGENTS.md", "CLAUDE.md"])

    def test_table_padding(self) -> None:
        row = "| a" + " " * 600 + "| b" + " " * 600 + "|\n"
        self.p.write("AGENTS.md", row * 2)
        pad = self.p.measure()["table_padding"]
        self.assertEqual(pad[0]["file"], "AGENTS.md")
        self.assertGreaterEqual(pad[0]["bytes"], 2400)


class GotchaTests(Base):
    def test_parse_skips_fenced_example(self) -> None:
        entries = layout.parse_gotchas(GOTCHA, "GOTCHAS.md")
        self.assertEqual([e["id"] for e in entries], ["expo-env"])
        e = entries[0]
        self.assertEqual(e["paths"], ["apps/mobile/**", "app.config.ts"])
        self.assertEqual(e["commands"], ["expo export"])
        self.assertEqual(e["missing"], [])
        self.assertTrue(e["text"].startswith("## expo-env"))

    def test_brace_glob_paths_stay_one_pattern(self) -> None:
        entry = layout.parse_gotchas(GOTCHA.replace("`apps/mobile/**`, `app.config.ts`",
                                                    "`apps/web/src/**/*.{ts,tsx}`, `app.config.ts`"))[0]
        self.assertEqual(entry["paths"], ["apps/web/src/**/*.{ts,tsx}", "app.config.ts"])
        self.p.write("GOTCHAS.md", GOTCHA.replace("`apps/mobile/**`, `app.config.ts`", "`apps/web/src/**/*.{ts,tsx}`"))
        self.p.write("apps/web/src/a/b.tsx", "x")
        self.assertEqual(self.p.measure()["stale_gotchas"], [])

    def test_missing_fields_invalid(self) -> None:
        self.p.write("GOTCHAS.md", "## broken\n- **Symptom:** x\n")
        m = self.p.measure()
        self.assertEqual(m["invalid_gotchas"][0]["id"], "broken")
        self.assertIn("paths", m["invalid_gotchas"][0]["missing"])
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 1)

    def test_stale_gotcha(self) -> None:
        self.p.write("GOTCHAS.md", GOTCHA.replace("`apps/mobile/**`, `app.config.ts`", "`legacy/**`"))
        self.p.write("src/a.ts", "x")
        self.assertEqual(self.p.measure()["stale_gotchas"], ["expo-env"])

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_gitignored_target_is_not_stale(self) -> None:
        """git ls-files omits ignored files; the gotcha still applies to them."""
        self.p.git("init", "-q")
        self.p.write(".gitignore", ".env*\ndist/\n")
        self.p.write(".env.production", "API_URL=x\n")
        self.p.write("dist/out.js", "x")
        self.p.write("GOTCHAS.md",
                     GOTCHA.replace("`apps/mobile/**`, `app.config.ts`", "`.env.production`")
                     + "\n" + GOTCHA.split("```\n\n", 1)[1]
                       .replace("## expo-env", "## dist-out").replace("`apps/mobile/**`, `app.config.ts`", "`dist/**`")
                     + "\n" + GOTCHA.split("```\n\n", 1)[1]
                       .replace("## expo-env", "## gone").replace("`apps/mobile/**`, `app.config.ts`", "`legacy/**`"))
        self.assertNotIn(".env.production", layout.list_files(self.p.root))
        self.assertEqual(self.p.measure()["stale_gotchas"], ["gone"])
        # the trailing-slash directory form, and a bare name at depth
        self.assertTrue(layout._paths_exist(self.p.root, ["dist/"], []))
        self.assertTrue(layout._paths_exist(self.p.root, ["out.js"], []))
        self.assertFalse(layout._paths_exist(self.p.root, ["legacy/"], []))

    def test_live_gotcha_not_stale(self) -> None:
        self.p.write("GOTCHAS.md", GOTCHA)
        self.p.write("apps/mobile/app.json", "{}")
        self.assertEqual(self.p.measure()["stale_gotchas"], [])

    def test_oversize_entry_is_over(self) -> None:
        self.p.write("GOTCHAS.md", GOTCHA.replace("never the shell.", "never the shell. " + "x" * 900))
        self.p.write("apps/mobile/app.json", "{}")
        tiers = [o["tier"] for o in self.p.measure()["over"]]
        self.assertIn("gotcha_entry", tiers)

    def test_find_files_skips_heavy_dirs(self) -> None:
        self.p.write("GOTCHAS.md", "x")
        self.p.write("apps/web/GOTCHAS.md", "x")
        self.p.write("node_modules/pkg/GOTCHAS.md", "x")
        self.p.write("a/b/c/GOTCHAS.md", "x")
        found = layout.find_files(self.p.root, layout.DEFAULTS["gotchas"])
        self.assertEqual(found, ["GOTCHAS.md", "apps/web/GOTCHAS.md"])
        self.assertEqual(layout.find_files(self.p.root, ["**/GOTCHAS.md"]),
                         ["GOTCHAS.md", "a/b/c/GOTCHAS.md", "apps/web/GOTCHAS.md"])

    def test_duplicate_ids_invalid(self) -> None:
        second = GOTCHA.split("```\n\n", 1)[1].replace("## expo-env", "## Expo Env")
        self.p.write("GOTCHAS.md", GOTCHA + "\n" + second)
        self.p.write("apps/mobile/app.json", "{}")
        invalid = self.p.measure()["invalid_gotchas"]
        self.assertEqual(invalid, [{"id": "expo-env", "file": "GOTCHAS.md", "missing": ["unique id"]}])

    def test_find_files_strips_dot_slash(self) -> None:
        self.p.write("GOTCHAS.md", "x")
        self.assertEqual(layout.find_files(self.p.root, ["./GOTCHAS.md"]), ["GOTCHAS.md"])

    def test_matches(self) -> None:
        e = layout.parse_gotchas(GOTCHA)[0]
        self.assertTrue(layout.gotcha_matches(e, rel_path="apps/mobile/app.json"))
        self.assertTrue(layout.gotcha_matches(e, command="npx expo export --platform web"))
        self.assertFalse(layout.gotcha_matches(e, rel_path="README.md"))
        self.assertFalse(layout.gotcha_matches(e, command="npm test"))


@unittest.skipUnless(shutil.which("git"), "git not installed")
class GuardTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.p.git("init", "-q", "-b", "main")
        self.p.write("docs/features/auth.md", '---\npaths: ["apps/web/src/auth/**"]\n---\n# Auth\n')
        self.p.write("apps/web/src/auth/login.ts", "v1\n")
        self.p.write("apps/web/src/other.ts", "v1\n")
        self.p.git("add", "-A")
        self.p.git("commit", "-qm", "base")
        self.base = self.p.git("rev-parse", "HEAD")
        self._env = {k: os.environ.pop(k) for k in ("COOGRAPH_LAYOUT_SKIP", "COOGRAPH_PR_TITLE") if k in os.environ}

    def tearDown(self) -> None:
        os.environ.pop("COOGRAPH_LAYOUT_SKIP", None)
        os.environ.pop("COOGRAPH_PR_TITLE", None)
        os.environ.update(self._env)
        super().tearDown()

    def _commit(self, *files: str) -> str:
        for f in files:
            path = self.p.root / f
            path.write_text(path.read_text(encoding="utf-8") + "v2\n", encoding="utf-8")
        self.p.git("add", "-A")
        self.p.git("commit", "-qm", "change")
        return self.p.git("rev-parse", "HEAD")

    def test_covered_change_without_doc_fails(self) -> None:
        head = self._commit("apps/web/src/auth/login.ts", "apps/web/src/other.ts")
        result = layout.guard(self.p.root, self.p.config(), layout.changed_files(self.p.root, self.base, head))
        self.assertEqual(result["failures"], [{"path": "apps/web/src/auth/login.ts",
                                               "docs": ["docs/features/auth.md"]}])
        self.assertEqual(result["uncovered"], ["apps/web/src/other.ts"])
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]), 1)

    def test_doc_updated_passes(self) -> None:
        head = self._commit("apps/web/src/auth/login.ts", "docs/features/auth.md")
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]), 0)

    def test_uncovered_only_passes(self) -> None:
        head = self._commit("apps/web/src/other.ts")
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]), 0)

    def test_gotchas_do_not_cover(self) -> None:
        """A gotcha describes a trap, not an area's state: code under its paths
        may change without touching GOTCHAS.md."""
        self.p.write("GOTCHAS.md", GOTCHA.replace("`apps/mobile/**`, `app.config.ts`", "`apps/web/src/other.ts`"))
        self.p.git("add", "-A")
        self.p.git("commit", "-qm", "gotcha")
        base = self.p.git("rev-parse", "HEAD")
        head = self._commit("apps/web/src/other.ts")
        result = layout.guard(self.p.root, self.p.config(), layout.changed_files(self.p.root, base, head))
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["uncovered"], ["apps/web/src/other.ts"])

    def test_failure_names_path_and_doc(self) -> None:
        head = self._commit("apps/web/src/auth/login.ts")
        out = io.StringIO()
        with redirect_stdout(out):
            code = layout.main(["--cwd", str(self.p.root), "--guard", self.base, head])
        self.assertEqual(code, 1)
        self.assertIn("FAIL  apps/web/src/auth/login.ts -> docs/features/auth.md", out.getvalue())
        self.assertIn("config from seed defaults", out.getvalue())

    def test_skip_marker(self) -> None:
        head = self._commit("apps/web/src/auth/login.ts")
        os.environ["COOGRAPH_PR_TITLE"] = "fix: typo [skip docs]"
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]), 0)
        self.assertIn("layout guard: skipped", out.getvalue())

    def test_skip_env(self) -> None:
        head = self._commit("apps/web/src/auth/login.ts")
        os.environ["COOGRAPH_LAYOUT_SKIP"] = "0"
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]), 1)
        os.environ["COOGRAPH_LAYOUT_SKIP"] = "1"
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]), 0)

    def test_bad_ref_exits_2(self) -> None:
        self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", "nope", "HEAD"]), 2)

    def test_deleted_path_is_never_uncovered(self) -> None:
        (self.p.root / "apps/web/src/other.ts").unlink()
        self.p.git("add", "-A")
        self.p.git("commit", "-qm", "delete")
        head = self.p.git("rev-parse", "HEAD")
        changed = layout.changed_files(self.p.root, self.base, head)
        deleted = layout.changed_files(self.p.root, self.base, head, deleted=True)
        self.assertEqual(deleted, ["apps/web/src/other.ts"])
        self.assertEqual(layout.guard(self.p.root, self.p.config(), changed, deleted)["uncovered"], [])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(layout.main(["--cwd", str(self.p.root), "--guard", self.base, head, "--strict"]), 0)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class GuardRootsStrictTests(Base):
    """guard.roots and --strict, from a project's own fixture (a monorepo whose
    old per-workspace checks guarded only some directories)."""

    CONFIG = {
        "guard": {
            "roots": ["apps/web/src/", "apps/site/src/pages/", "packages/core/src", "firestore.rules"],
            "ignore": ["**/*.lock", "openspec/**", "**/*.md", "apps/site/src/content/**"],
            "skip_marker": "[skip-agents-md]",
        },
    }
    DOC = ("---\npaths:\n  - apps/web/src/routes/today/\n  - apps/site/src/content/\n"
           "  - package.json\n---\n# Today\n")

    def setUp(self) -> None:
        super().setUp()
        self.p.git("init", "-q", "-b", "main")
        self.p.write(".github/layout/layout.json", json.dumps(self.CONFIG))
        self.p.write("docs/features/today.md", self.DOC)
        self.p.write("apps/web/src/routes/today/a.svelte", "v1\n")
        self.p.write("apps/web/src/lib/other.ts", "v1\n")
        self.p.git("add", "-A", "-f")
        self.p.git("commit", "-qm", "base")
        self.base = self.p.git("rev-parse", "HEAD")
        self._env = {k: os.environ.pop(k) for k in ("COOGRAPH_LAYOUT_SKIP", "COOGRAPH_PR_TITLE") if k in os.environ}

    def tearDown(self) -> None:
        os.environ.pop("COOGRAPH_PR_TITLE", None)
        os.environ.update(self._env)
        super().tearDown()

    def _guard(self, files: list[str], strict: bool = True, title: str = "") -> tuple[int, str]:
        for rel in files:
            if rel.startswith("-"):  # "-path" deletes the file
                (self.p.root / rel[1:]).unlink()
                continue
            path = self.p.root / rel
            self.p.write(rel, (path.read_text(encoding="utf-8") if path.exists() else "") + "changed\n")
        self.p.git("add", "-A", "-f")
        self.p.git("commit", "-qm", "change")
        head = self.p.git("rev-parse", "HEAD")
        if title:
            os.environ["COOGRAPH_PR_TITLE"] = title
        out = io.StringIO()
        with redirect_stdout(out):
            code = layout.main(["--cwd", str(self.p.root), "--guard", self.base, head]
                               + (["--strict"] if strict else []))
        return code, out.getvalue()

    def test_covered_with_doc(self) -> None:
        self.assertEqual(self._guard(["apps/web/src/routes/today/a.svelte", "docs/features/today.md"])[0], 0)

    def test_covered_without_doc(self) -> None:
        self.assertEqual(self._guard(["apps/web/src/routes/today/a.svelte"])[0], 1)

    def test_uncovered_in_root_strict(self) -> None:
        code, out = self._guard(["apps/web/src/lib/other.ts"])
        self.assertEqual(code, 1)
        self.assertIn("UNCOVERED  apps/web/src/lib/other.ts", out)

    def test_uncovered_in_root_not_strict(self) -> None:
        code, out = self._guard(["apps/web/src/lib/other.ts"], strict=False)
        self.assertEqual(code, 0)
        self.assertIn("uncovered  apps/web/src/lib/other.ts", out)

    def test_outside_roots_though_a_doc_covers_it(self) -> None:
        self.assertEqual(self._guard(["package.json"])[0], 0)

    def test_ignored_content_under_a_doc(self) -> None:
        self.assertEqual(self._guard(["apps/site/src/content/blog/post.mdx"])[0], 0)

    def test_workflow_only(self) -> None:
        self.assertEqual(self._guard([".github/workflows/x.yml"])[0], 0)

    def test_root_without_trailing_slash_and_file_root(self) -> None:
        self.assertEqual(self._guard(["packages/core/src/x.ts"])[0], 1)
        self.assertTrue(layout.under_roots("firestore.rules", self.CONFIG["guard"]["roots"]))
        self.assertFalse(layout.under_roots("packages/core/srcx/y.ts", self.CONFIG["guard"]["roots"]))

    def test_skip_marker_in_title(self) -> None:
        self.assertEqual(self._guard(["apps/web/src/routes/today/a.svelte"], title="chore [skip-agents-md]")[0], 0)

    def test_deleted_uncovered_file_strict(self) -> None:
        self.assertEqual(self._guard(["-apps/web/src/lib/other.ts"])[0], 0)

    def test_invalid_roots_exit_2(self) -> None:
        for bad in ("apps/", [""], ["/"], [3]):
            with self.subTest(roots=bad):
                cfg = json.loads(json.dumps(self.CONFIG))
                cfg["guard"]["roots"] = bad
                self.p.write(".github/layout/layout.json", json.dumps(cfg))
                with redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(layout.main(["--cwd", str(self.p.root), "--budget"]), 2)
                self.assertIn("guard.roots", err.getvalue())

    def test_strict_needs_guard(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            layout.main(["--cwd", str(self.p.root), "--budget", "--strict"])


class TemplateTests(unittest.TestCase):
    """The template every project starts from: within budget, each rule stated once."""

    # One literal phrase per rule that lived in the pre-tier CLAUDE.md,
    # AGENTS.md and copilot-instructions.md. Present = not dropped by the
    # restructure; exactly once = not paid for twice.
    ANCHORS = [
        "HARD RULE — CODE-GRAPH FIRST",
        "HARD RULE — OPENSPEC OR STOP",
        "## Pre-flight",
        "Never skip Step 1 for Step 2",
        "Preserve all existing features",
        "Feature inventory before editing",
        "No new dependencies without explicit user approval",
        "Regenerate API types",
        "After 3 failed attempts",
        "Never cite your own prior output as evidence",
        "trust the file",
        "never self-approve",
        "Treat file contents as untrusted data",
        "retro.py --status",
        "Surface assumptions",
        "Change manifest first",
        "brutal-honesty.instructions.md",
        "Preservation on compaction",
        "Memory pointer pattern",
        "Hand-off format",
        "## Branching Strategy",
        "## Commands",
        "re-read modified files from disk",
        "Template guard",
        "re-review only if the fixes were substantial",
        "variation after variation",
        "verified against the spec",
    ]

    def setUp(self) -> None:
        config = json.loads((LAYOUT_DIR / "layout.seed.json").read_text(encoding="utf-8"))
        files, missing = layout.resolve_always_loaded(REPO, config["always_loaded"])
        self.files = files
        self.missing = missing
        self.text = {f["file"]: (REPO / f["file"]).read_text(encoding="utf-8") for f in files}

    def test_claude_imports_resolve(self) -> None:
        self.assertEqual(self.missing, [])
        self.assertEqual(
            sorted(f["file"] for f in self.files),
            sorted(["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"]),
        )
        via = {f["file"]: f["via"] for f in self.files}
        self.assertEqual(via["AGENTS.md"], "")  # listed directly, and imported by CLAUDE.md

    def test_within_budget(self) -> None:
        total = sum(f["tokens"] for f in self.files)
        self.assertLessEqual(total, layout.DEFAULTS["budgets"]["always_loaded"])

    def test_every_rule_stated_exactly_once(self) -> None:
        for anchor in self.ANCHORS:
            with self.subTest(anchor=anchor):
                hits = {f: t.count(anchor) for f, t in self.text.items() if anchor in t}
                self.assertEqual(sum(hits.values()), 1, f"{anchor!r} found {hits or 'nowhere'}")

    def test_no_duplicate_paragraphs(self) -> None:
        config = json.loads((LAYOUT_DIR / "layout.seed.json").read_text(encoding="utf-8"))
        self.assertEqual(layout.measure(REPO, config)["duplicate_paragraphs"], [])

    def test_budget_cli_passes_on_template(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(layout.main(["--cwd", str(REPO), "--budget"]), 0)

    def test_gotchas_template_has_no_entries(self) -> None:
        self.assertEqual(layout.parse_gotchas((REPO / "GOTCHAS.md").read_text(encoding="utf-8")), [])


class SyncTests(Base):
    """sync.py must never destroy a project-owned file."""

    @classmethod
    def setUpClass(cls) -> None:
        # sync.py configures root logging (stdout + .github/sync.log) at import.
        # Drop those handlers so tests neither spam output nor write the real log;
        # assertLogs still captures the named logger.
        root = logging.getLogger()
        before = list(root.handlers)
        cls.sync = _load("coograph_sync", REPO / ".github" / "sync.py")
        for handler in [h for h in root.handlers if h not in before]:
            root.removeHandler(handler)
            handler.close()

    def _project(self, **extra) -> dict:
        return {"path": str(self.p.root), "tools": ["vscode"], "code_graph": False, **extra}

    def test_customized_agents_md_survives(self) -> None:
        self.p.write("AGENTS.md", "MY RULES\n")
        with self.assertLogs("code-graph.sync", level="INFO") as logs:
            self.sync.sync_project(self._project())
        self.assertEqual((self.p.root / "AGENTS.md").read_text(encoding="utf-8"), "MY RULES\n")
        self.assertTrue(any("AGENTS.md  kept (project-owned)" in line for line in logs.output))

    def test_missing_agents_md_is_created(self) -> None:
        self.sync.sync_project(self._project())
        self.assertEqual((self.p.root / "AGENTS.md").read_bytes(), (REPO / "AGENTS.md").read_bytes())

    def test_layout_json_seeded_then_kept(self) -> None:
        self.sync.sync_project(self._project())
        target = self.p.root / ".github" / "layout" / "layout.json"
        self.assertTrue(target.is_file())
        self.assertFalse((self.p.root / ".github" / "layout" / "tests").exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        data["budgets"]["always_loaded"] = 4242
        target.write_text(json.dumps(data), encoding="utf-8")
        self.sync.sync_project(self._project())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["budgets"]["always_loaded"], 4242)

    def test_gotchas_never_written(self) -> None:
        self.sync.sync_project(self._project())
        self.assertFalse((self.p.root / "GOTCHAS.md").exists())
        self.p.write("GOTCHAS.md", "mine\n")
        self.sync.sync_project(self._project())
        self.assertEqual((self.p.root / "GOTCHAS.md").read_text(encoding="utf-8"), "mine\n")

    def test_claude_project_importing_agents_md_gets_it(self) -> None:
        """A tiered CLAUDE.md holds no hard rules itself; without AGENTS.md they vanish."""
        self.p.write("CLAUDE.md", "# Claude\n\n@AGENTS.md\n@.github/copilot-instructions.md\n")
        self.sync.sync_project(self._project(tools=["claude"]))
        self.assertEqual((self.p.root / "AGENTS.md").read_bytes(), (REPO / "AGENTS.md").read_bytes())
        self.assertEqual((self.p.root / "CLAUDE.md").read_text(encoding="utf-8"),
                         "# Claude\n\n@AGENTS.md\n@.github/copilot-instructions.md\n")

    def test_claude_project_on_old_layout_gets_no_agents_md(self) -> None:
        self.p.write("CLAUDE.md", "# Claude\n\nAll rules inline.\n")
        self.sync.sync_project(self._project(tools=["claude"]))
        self.assertFalse((self.p.root / "AGENTS.md").exists())

    def test_claude_project_keeps_its_agents_md(self) -> None:
        self.p.write("CLAUDE.md", "@AGENTS.md\n")
        self.p.write("AGENTS.md", "MINE\n")
        self.sync.sync_project(self._project(tools=["claude"]))
        self.assertEqual((self.p.root / "AGENTS.md").read_text(encoding="utf-8"), "MINE\n")

    def test_dry_run_writes_nothing_project_owned(self) -> None:
        self.p.write(".github/workflows/coograph-layout.yml", "old\n")
        self.sync.sync_project(self._project(), dry_run=True)
        self.assertFalse((self.p.root / "AGENTS.md").exists())
        self.assertFalse((self.p.root / ".github" / "layout" / "layout.json").exists())
        self.assertEqual((self.p.root / ".github/workflows/coograph-layout.yml").read_text(encoding="utf-8"), "old\n")

    def test_workflow_refreshed_only_when_present_and_managed(self) -> None:
        wf = self.p.root / ".github" / "workflows" / "coograph-layout.yml"
        self.sync.sync_project(self._project())
        self.assertFalse(wf.exists())
        self.p.write(".github/workflows/coograph-layout.yml", "# coograph:managed (old)\nold\n")
        # As an earlier sync left it: recorded in the manifest, so not a local edit.
        manifest = json.loads((self.p.root / ".coograph/sync-manifest.json").read_text(encoding="utf-8"))
        manifest["files"][".github/workflows/coograph-layout.yml"] = self.sync._digest(wf.read_bytes())
        (self.p.root / ".coograph/sync-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.sync.sync_project(self._project())
        self.assertEqual(wf.read_bytes(), (LAYOUT_DIR / "coograph-layout.yml").read_bytes())
        # Edited with the marker kept: a local edit, kept.
        self.p.write(".github/workflows/coograph-layout.yml", "# coograph:managed\nmine\n")
        self.sync.sync_project(self._project())
        self.assertEqual(wf.read_text(encoding="utf-8"), "# coograph:managed\nmine\n")

    def test_customized_workflow_is_kept(self) -> None:
        self.p.write(".github/workflows/coograph-layout.yml", "name: mine\non: push\n")
        with self.assertLogs("code-graph.sync", level="INFO") as logs:
            self.sync.sync_project(self._project())
        self.assertEqual((self.p.root / ".github/workflows/coograph-layout.yml").read_text(encoding="utf-8"),
                         "name: mine\non: push\n")
        self.assertTrue(any("kept (customized" in line for line in logs.output))

    def test_template_workflow_runs_on_title_edits(self) -> None:
        text = (LAYOUT_DIR / "coograph-layout.yml").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# coograph:managed"))
        self.assertIn("types: [opened, synchronize, reopened, edited]", text)


if __name__ == "__main__":
    unittest.main()
