"""JS/TS imports resolve through the nearest tsconfig and the real default export.

Built by the real builder over a real (tiny) tree, like test_js_kotlin_calls.py.
One test per scenario in
openspec/changes/2026-10-23-js-import-resolution/specs/code-graph/spec.md.

Run:  python -m unittest discover .github/code-graph/tests
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

CODE_GRAPH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_GRAPH))

import builder  # noqa: E402
from parsers.tree_sitter import core  # noqa: E402

for _ext in (".ts", ".js"):
    if not core.AVAILABLE or core.get_lang(_ext) is None:  # pragma: no cover
        raise unittest.SkipTest(f"tree-sitter grammar for {_ext} not installed")


PROJECT = {
    # Root config: applies wherever no nearer config exists.
    "tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./other/*"]}}}',
    "other/a.ts": "import { b1 } from '@/b';\nexport function a1() {\n  return b1();\n}\n",
    "other/b.ts": "export function b1() {\n  return 1;\n}\n",
    "other/x.ts": "export function x1() {\n  return 1;\n}\n",

    # A root-level file's relative import (eslint.config.js -> ./svelte.config.js).
    "eslint.config.js": "import cfg from './svelte.config.js';\nexport default [cfg];\n",
    "svelte.config.js": "const config = {};\nexport default config;\n",

    # A nested repo with its own config (wisehosting Panel/).
    "web/tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}',
    "web/src/lib/util.ts": "export function helper() {\n  return 1;\n}\n",
    "web/src/app.ts": (
        "import { helper } from '@/lib/util';\n"
        "export function app() {\n  return helper();\n}\n"
    ),

    # Nearest config wins over the root one.
    "near/tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}',
    "near/src/x.ts": "export function x1() {\n  return 2;\n}\n",
    "near/src/main.ts": "import { x1 } from '@/x';\nexport function nearMain() {\n  return x1();\n}\n",

    # SvelteKit: $lib only through extends, with comments and trailing commas.
    "kit/tsconfig.json": '{\n  // svelte-kit sync writes the real config\n  "extends": "./.svelte-kit/tsconfig.json",\n}\n',
    "kit/.svelte-kit/tsconfig.json": (
        '{"compilerOptions": {"paths": {"$lib": ["../src/lib"], '
        '"$lib/*": ["../src/lib/*"],},},}'
    ),
    "kit/src/lib/api.ts": "export function load1() {\n  return 1;\n}\n",
    "kit/src/lib/index.ts": "export function root1() {\n  return 1;\n}\n",
    "kit/src/routes/page.ts": (
        "import { load1 } from '$lib/api';\nimport { root1 } from '$lib';\n"
        "export function page() {\n  load1();\n  return root1();\n}\n"
    ),

    # Longest prefix and multi-target.
    "multi/tsconfig.json": (
        '{"compilerOptions": {"paths": {"@/*": ["./src/*", "./gen/*"], '
        '"@/models/*": ["./pkg/models/*"]}}}'
    ),
    "multi/pkg/models/user.ts": "export function mkUser() {\n  return 1;\n}\n",
    "multi/src/models/user.ts": "export function mkUser() {\n  return 2;\n}\n",
    "multi/gen/client.ts": "export function call1() {\n  return 1;\n}\n",
    "multi/src/main.ts": (
        "import { mkUser } from '@/models/user';\nimport { call1 } from '@/client';\n"
        "export function run() {\n  mkUser();\n  return call1();\n}\n"
    ),

    # extends: a child's paths override the parent's; a child without paths
    # inherits them (anchored at the parent's folder); package entries and
    # cycles are skipped.
    "base/tsconfig.base.json": '{"compilerOptions": {"paths": {"@/*": ["./old/*"]}}}',
    "base/old/w.ts": "export function w1() {\n  return 1;\n}\n",
    "ovr/tsconfig.json": (
        '{"extends": "../base/tsconfig.base", '
        '"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}'
    ),
    "ovr/src/w.ts": "export function w1() {\n  return 2;\n}\n",
    "ovr/src/main.ts": "import { w1 } from '@/w';\nexport function omain() {\n  return w1();\n}\n",
    "inh/tsconfig.json": '{"extends": ["expo/tsconfig.base", "./tsconfig.base.json"]}',
    "inh/tsconfig.base.json": (
        '{"extends": "./tsconfig.json", "compilerOptions": {"paths": {"@/*": ["./lib/*"]}}}'
    ),
    "inh/lib/v.ts": "export function v1() {\n  return 1;\n}\n",
    "inh/main.ts": "import { v1 } from '@/v';\nexport function imain() {\n  return v1();\n}\n",

    # paths anchored at baseUrl, and a `*` in the middle of a target.
    "anch/tsconfig.json": (
        '{"compilerOptions": {"baseUrl": "./src", "paths": {"~/*": ["lib/*"], '
        '"#feat/*": ["features/*/index.ts"]}}}'
    ),
    "anch/src/lib/q.ts": "export function q1() {\n  return 1;\n}\n",
    "anch/src/features/auth/index.ts": "export function login() {\n  return 1;\n}\n",
    "anch/src/main.ts": (
        "import { q1 } from '~/q';\nimport { login } from '#feat/auth';\n"
        "export function amain() {\n  q1();\n  return login();\n}\n"
    ),

    # Other languages never read tsconfig.
    "mixed/tsconfig.json": '{"compilerOptions": {"baseUrl": "."}}',
    "mixed/config.ts": "export function cfg() {\n  return 1;\n}\n",
    "mixed/svc/app.py": "import config\n\n\ndef run():\n    return config.cfg\n",

    # depends_on and calls agree: `./lib/a` is a.ts when a.js sits beside it.
    "dup/lib/a.ts": "export function ff() {\n  return 1;\n}\n",
    "dup/lib/a.js": "export function ff() {\n  return 2;\n}\n",
    "dup/m.ts": "import { ff } from './lib/a';\nexport function gg() {\n  return ff();\n}\n",

    # baseUrl-only imports.
    "based/tsconfig.json": '{"compilerOptions": {"baseUrl": "src"}}',
    "based/src/components/Button.tsx": "export function Button() {\n  return 1;\n}\n",
    "based/src/utils.ts": "export function util1() {\n  return 1;\n}\n",
    "based/src/main.ts": (
        "import { Button } from 'components/Button';\nimport { util1 } from 'utils';\n"
        "import { useState } from 'react';\n"
        "export function bmain() {\n  Button();\n  useState();\n  return util1();\n}\n"
    ),

    # Default exports.
    "dflt/lib/a.ts": "export default function bar() {\n  return 1;\n}\n",
    "dflt/b.ts": "function qux() {\n  return 1;\n}\nexport { qux as default };\n",
    "dflt/c.ts": "const Baz = () => 1;\nexport default Baz;\n",
    "dflt/d.js": "function quux() {\n  return 1;\n}\nmodule.exports = quux;\n",
    "dflt/e.ts": "export default () => 1;\n",
    "dflt/same.ts": "export default function same() {\n  return 1;\n}\n",
    "dflt/main.ts": (
        "import Foo from './lib/a';\nimport Bee from './b';\nimport Cee from './c';\n"
        "import Eee from './e';\nimport same from './same';\nconst xmod = require('./d');\n"
        "export function dmain() {\n  Foo();\n  Bee();\n  Cee();\n  Eee();\n  same();\n"
        "  return xmod();\n}\n"
    ),
}


class JsResolutionTests(unittest.TestCase):
    tmp: Path
    conn: sqlite3.Connection

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="coograph-jsres-"))
        for rel, body in PROJECT.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        with unittest.TestCase().assertLogs("code-graph.builder", level="INFO"):
            db = builder.build(cls.tmp)
        cls.conn = sqlite3.connect(db)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def callees(self, caller: str, file: str) -> set[tuple[str, str]]:
        return set(self.conn.execute(
            "SELECT t.name, t.file FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes t ON t.id = e.dst "
            "WHERE e.kind='calls' AND s.name=? AND s.file=?", (caller, file)))

    def deps(self, file: str) -> set[str]:
        return {f for (f,) in self.conn.execute(
            "SELECT t.file FROM edges e JOIN nodes s ON s.id = e.src "
            "JOIN nodes t ON t.id = e.dst "
            "WHERE e.kind='depends_on' AND s.kind='file' AND s.file=?", (file,))}

    def default_exports(self) -> dict[str, str]:
        return dict(self.conn.execute(
            "SELECT n.file, e.dst FROM edges e JOIN nodes n ON n.id = e.src "
            "WHERE e.kind='exports_default'"))

    # -- tsconfig per importing file ---------------------------------------

    def test_nested_repo_tsconfig_applies(self):
        self.assertIn("web/src/lib/util.ts", self.deps("web/src/app.ts"))
        self.assertEqual({("helper", "web/src/lib/util.ts")},
                         self.callees("app", "web/src/app.ts"))

    def test_nearest_config_wins(self):
        self.assertEqual({("x1", "near/src/x.ts")},
                         self.callees("nearMain", "near/src/main.ts"))
        self.assertNotIn("other/x.ts", self.deps("near/src/main.ts"))

    def test_root_config_still_applies(self):
        self.assertIn("other/b.ts", self.deps("other/a.ts"))
        self.assertEqual({("b1", "other/b.ts")}, self.callees("a1", "other/a.ts"))

    def test_root_level_relative_import(self):
        """Found by the hand check: "" as the folder made "./x" read as "/x"."""
        self.assertIn("svelte.config.js", self.deps("eslint.config.js"))

    def test_sveltekit_lib_through_extends(self):
        deps = self.deps("kit/src/routes/page.ts")
        self.assertIn("kit/src/lib/api.ts", deps)
        self.assertIn("kit/src/lib/index.ts", deps)
        self.assertEqual({("load1", "kit/src/lib/api.ts"), ("root1", "kit/src/lib/index.ts")},
                         self.callees("page", "kit/src/routes/page.ts"))

    def test_longest_prefix_and_multi_target(self):
        self.assertEqual({("mkUser", "multi/pkg/models/user.ts"), ("call1", "multi/gen/client.ts")},
                         self.callees("run", "multi/src/main.ts"))

    def test_child_paths_override_extended_parent(self):
        self.assertEqual({("w1", "ovr/src/w.ts")}, self.callees("omain", "ovr/src/main.ts"))

    def test_inherited_paths_skip_package_and_cyclic_extends(self):
        self.assertEqual({("v1", "inh/lib/v.ts")}, self.callees("imain", "inh/main.ts"))

    def test_paths_anchor_at_base_url_and_mid_star_target(self):
        self.assertEqual({("q1", "anch/src/lib/q.ts"), ("login", "anch/src/features/auth/index.ts")},
                         self.callees("amain", "anch/src/main.ts"))

    def test_other_languages_ignore_tsconfig(self):
        self.assertNotIn("mixed/config.ts", self.deps("mixed/svc/app.py"))

    def test_depends_on_and_calls_pick_the_same_file(self):
        self.assertEqual({"dup/lib/a.ts"}, self.deps("dup/m.ts"))
        self.assertEqual({("ff", "dup/lib/a.ts")}, self.callees("gg", "dup/m.ts"))

    def test_base_url_only_imports(self):
        deps = self.deps("based/src/main.ts")
        self.assertEqual({"based/src/components/Button.tsx", "based/src/utils.ts"}, deps)
        self.assertEqual({("Button", "based/src/components/Button.tsx"),
                          ("util1", "based/src/utils.ts")},
                         self.callees("bmain", "based/src/main.ts"))

    # -- default exports ---------------------------------------------------

    def test_default_export_under_another_name(self):
        self.assertIn(("bar", "dflt/lib/a.ts"), self.callees("dmain", "dflt/main.ts"))
        self.assertEqual("bar", self.default_exports().get("dflt/lib/a.ts"))

    def test_other_default_forms(self):
        callees = self.callees("dmain", "dflt/main.ts")
        self.assertIn(("qux", "dflt/b.ts"), callees)
        self.assertIn(("Baz", "dflt/c.ts"), callees)
        self.assertIn(("quux", "dflt/d.js"), callees)

    def test_anonymous_and_same_name_defaults(self):
        self.assertNotIn("dflt/e.ts", self.default_exports())
        callees = self.callees("dmain", "dflt/main.ts")
        self.assertFalse([c for c in callees if c[1] == "dflt/e.ts"])
        self.assertIn(("same", "dflt/same.ts"), callees)


class DefaultExportUpdateTests(unittest.TestCase):
    """update() replaces a call whose default export was renamed."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="coograph-jsupd-"))
        (self.tmp / "lib").mkdir()
        (self.tmp / "lib" / "a.ts").write_text(
            "export default function bar() {\n  return 1;\n}\n", encoding="utf-8")
        (self.tmp / "m.ts").write_text(
            "import Foo from './lib/a';\nexport function gg() {\n  return Foo();\n}\n",
            encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def callees(self, db: Path) -> set[str]:
        conn = sqlite3.connect(db)
        try:
            return {n for (n,) in conn.execute(
                "SELECT t.name FROM edges e JOIN nodes s ON s.id = e.src "
                "JOIN nodes t ON t.id = e.dst WHERE e.kind='calls' AND s.name='gg'")}
        finally:
            conn.close()

    def test_renamed_default_replaces_the_old_call(self):
        db = builder.build(self.tmp)
        self.assertEqual({"bar"}, self.callees(db))
        (self.tmp / "lib" / "a.ts").write_text(
            "export function bar() {\n  return 1;\n}\n"
            "export default function baz() {\n  return 2;\n}\n", encoding="utf-8")
        builder.update(self.tmp)
        self.assertEqual({"baz"}, self.callees(db))


if __name__ == "__main__":
    unittest.main()
