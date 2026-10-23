"""JS/TS functions and calls, Kotlin calls, minified files skipped.

Built by the real builder over a real (tiny) tree, like test_python_calls.py.
One test per scenario in
openspec/changes/2026-10-23-js-ts-kotlin-calls/specs/code-graph/spec.md.

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

for _ext in (".ts", ".js", ".kt", ".py"):
    if not core.AVAILABLE or core.get_lang(_ext) is None:  # pragma: no cover
        raise unittest.SkipTest(f"tree-sitter grammar for {_ext} not installed")


MINIFIED = "var a=function(){return 1};" * 400  # one 10 KB line

PROJECT = {
    "web/src/api.ts": '''
export const fetchPlan = async (id: number) => {
  return id;
};

export function savePlan(id: number) {
  return id;
}
''',
    "web/src/legacy/api.js": '''
export const fetchPlan = () => 0;
''',
    "web/src/usePlan.ts": '''
import { fetchPlan } from './api';
import { savePlan as sp } from './api';
import * as api from './api';
import { useState } from 'react';

export const usePlan = () => {
  const [p] = useState(0);
  const local = () => helper();
  fetchPlan(1);
  return p;
};

export function useSave() {
  sp(1);
  api.savePlan(2);
  console.log("x");
}

function helper() {
  return 1;
}
''',
    "web/src/store.ts": '''
export class Store {
  load = () => {
    this.reset();
  };

  reset() {
    return 0;
  }
}
''',
    "web/src/timers.js": '''
export function wait() {
  sleep(1);
}
''',
    "web/src/components/index.ts": '''
export { Button } from './Button';
''',
    "web/src/components/Button.tsx": '''
export const Button = () => {
  return null;
};
''',
    "web/src/page.tsx": '''
import { Button } from './components';

export function Page() {
  return Button();
}
''',
    "web/dist-like/main-es2015.3d77.js": MINIFIED,
    "web/src/vendor.min.js": "export function shouldNotAppear() { return 1; }\n",
    "web/src/plain.js": "export function plainFn() {\n  return 1;\n}\n",
    "py/tools.py": '''
def sleep(n):
    return n
''',
    "android/app/UserRepository.kt": '''
class UserRepository {
    fun loadUser(id: Int): Int {
        return id
    }
}
''',
    "android/app/Screen.kt": '''
class Screen(val repo: UserRepository) {
    fun render() {
        bind()
        repo.loadUser(1)
        this.clearAll()
    }

    fun bind() {}

    fun clearAll() {}
}
''',
}


class JsKotlinCallTests(unittest.TestCase):
    tmp: Path
    conn: sqlite3.Connection

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="coograph-js-"))
        for rel, body in PROJECT.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.lstrip("\n"), encoding="utf-8")
        with cls.assertLogs_ctx() as cls.logs:
            db = builder.build(cls.tmp)
        cls.conn = sqlite3.connect(db)

    @classmethod
    def assertLogs_ctx(cls):
        return unittest.TestCase().assertLogs("code-graph.builder", level="INFO")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def callees(self, caller: str, file: str) -> set[tuple[str, str]]:
        return set(self.conn.execute(
            "SELECT t.name, t.file FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes t ON t.id = e.dst "
            "WHERE e.kind='calls' AND s.name=? AND s.file=?", (caller, file)))

    def functions(self, file: str) -> set[tuple[str, str]]:
        return set(self.conn.execute(
            "SELECT name, kind FROM nodes WHERE kind IN ('function','method') AND file=?",
            (file,)))

    # -- arrow and expression functions are nodes --------------------------

    def test_const_arrow_is_a_function(self):
        self.assertIn(("fetchPlan", "function"), self.functions("web/src/api.ts"))

    def test_class_field_arrow_is_a_method(self):
        self.assertIn(("load", "method"), self.functions("web/src/store.ts"))

    def test_arrow_inside_a_function_is_not_a_node(self):
        names = {n for n, _ in self.functions("web/src/usePlan.ts")}
        self.assertNotIn("local", names)

    # -- JS/TS calls resolve through imports -------------------------------

    def test_named_import(self):
        self.assertIn(("fetchPlan", "web/src/api.ts"),
                      self.callees("usePlan", "web/src/usePlan.ts"))

    def test_aliased_and_namespace_imports(self):
        self.assertEqual({("savePlan", "web/src/api.ts")},
                         self.callees("useSave", "web/src/usePlan.ts"))

    def test_import_decides_between_same_names(self):
        self.assertNotIn(("fetchPlan", "web/src/legacy/api.js"),
                         self.callees("usePlan", "web/src/usePlan.ts"))

    def test_library_import_creates_no_edge(self):
        names = {n for n, _ in self.callees("usePlan", "web/src/usePlan.ts")}
        self.assertNotIn("useState", names)

    def test_local_call_inside_nested_arrow_counts_for_the_outer_function(self):
        self.assertIn(("helper", "web/src/usePlan.ts"),
                      self.callees("usePlan", "web/src/usePlan.ts"))

    def test_this_call_in_class_field(self):
        self.assertEqual({("reset", "web/src/store.ts")},
                         self.callees("load", "web/src/store.ts"))

    def test_barrel_reexport(self):
        self.assertEqual({("Button", "web/src/components/Button.tsx")},
                         self.callees("Page", "web/src/page.tsx"))

    def test_never_into_python(self):
        self.assertEqual(set(), self.callees("wait", "web/src/timers.js"))

    # -- Kotlin -------------------------------------------------------------

    def test_kotlin_bare_this_and_qualified(self):
        self.assertEqual(
            {("bind", "android/app/Screen.kt"), ("clearAll", "android/app/Screen.kt"),
             ("loadUser", "android/app/UserRepository.kt")},
            self.callees("render", "android/app/Screen.kt"))

    # -- minified files skipped ---------------------------------------------

    def test_minified_bundle_and_min_js_skipped(self):
        files = {f for (f,) in self.conn.execute("SELECT file FROM nodes WHERE kind='file'")}
        self.assertNotIn("web/dist-like/main-es2015.3d77.js", files)
        self.assertNotIn("web/src/vendor.min.js", files)
        self.assertTrue(any("Skipped 2 minified" in m for m in self.logs.output))

    def test_normal_js_still_parsed(self):
        self.assertIn(("plainFn", "function"), self.functions("web/src/plain.js"))


if __name__ == "__main__":
    unittest.main()
