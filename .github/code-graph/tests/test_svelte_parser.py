"""Svelte components reach the graph, and detection finds them.

`svelte` used to be a detected stack with top priority and no registered
parser, so `.svelte` never reached the extension map: 135 components on disk,
zero in the graph, and detection still reporting the stack as found.

Run:  python -m unittest discover .github/code-graph/tests
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

CODE_GRAPH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_GRAPH))

import builder  # noqa: E402
from parsers import detect_stack, get_parsers  # noqa: E402


COMPONENT = """\
<script lang="ts">
  import { onMount } from 'svelte';
  import Chip from './Chip.svelte';
  import { formatQuery } from '../lib/query';

  export let placeholder = '';

  interface Suggestion {
    label: string;
  }

  function handleBlur(event: FocusEvent) {
    return event;
  }

  const commitBlur = () => handleBlur(new FocusEvent('blur'));

  onMount(() => commitBlur());
</script>

<input {placeholder} on:blur={handleBlur} />
<Chip />
"""

ROUTE = """\
<script>
  import SearchSuggest from '../../components/SearchSuggest.svelte';
</script>

<SearchSuggest />
"""

MODULE_SCRIPT = """\
<script context="module">
  export function load() {
    return {};
  }
</script>

<script>
  let count = $state(0);
</script>

<p>{count}</p>
"""

PROJECT = {
    "app/package.json": json.dumps({
        "name": "app",
        "devDependencies": {"svelte": "^5.0.0", "@sveltejs/kit": "^2.0.0"},
    }),
    "app/src/components/SearchSuggest.svelte": COMPONENT,
    "app/src/components/Chip.svelte": "<span>chip</span>\n",
    "app/src/lib/query.ts": "export function formatQuery(q: string) { return q; }\n",
    "app/src/routes/search/+page.svelte": ROUTE,
    "app/src/routes/about/+layout.svelte": MODULE_SCRIPT,
}


class SvelteGraphTests(unittest.TestCase):
    tmp: Path
    conn: sqlite3.Connection

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="coograph-svelte-"))
        for rel, body in PROJECT.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        db = builder.build(cls.tmp)
        cls.conn = sqlite3.connect(db)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _names(self, kind: str) -> set[str]:
        return {
            r[0] for r in self.conn.execute(
                "SELECT name FROM nodes WHERE kind=?", (kind,)
            )
        }

    # -- the reported bug ---------------------------------------------------

    def test_svelte_files_are_in_the_graph(self) -> None:
        count = self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind='file' AND file LIKE '%.svelte'"
        ).fetchone()[0]
        self.assertEqual(count, 4, "every .svelte file on disk must be a node")

    def test_component_is_reachable_by_its_own_name(self) -> None:
        """The name a person types is the file stem, not the path."""
        self.assertIn("SearchSuggest", self._names("class"))

    # -- SvelteKit routes ---------------------------------------------------

    def test_route_files_are_named_after_their_route(self) -> None:
        """'+page' would collide with every other route in the project."""
        names = self._names("class")
        self.assertIn("search", names)
        self.assertIn("about", names)
        self.assertNotIn("+page", names)
        self.assertNotIn("+layout", names)

    # -- script block contents ----------------------------------------------

    def test_declarations_inside_the_script_block(self) -> None:
        functions = self._names("function")
        self.assertIn("handleBlur", functions)
        self.assertIn("commitBlur", functions, "arrow functions count too")
        self.assertIn("Suggestion", self._names("interface"))

    def test_module_script_block_is_parsed(self) -> None:
        """Svelte 4 <script context="module"> and Svelte 5 <script module>."""
        self.assertIn("load", self._names("function"))

    # -- edges --------------------------------------------------------------

    def test_component_imports_resolve_to_file_edges(self) -> None:
        rows = self.conn.execute(
            "SELECT dep.file FROM edges e "
            "JOIN nodes src ON src.id = e.src "
            "JOIN nodes dep ON dep.id = e.dst "
            "WHERE e.kind='depends_on' AND src.file LIKE '%SearchSuggest.svelte'"
        ).fetchall()
        found = {r[0] for r in rows}
        self.assertIn("app/src/components/Chip.svelte", found,
                      "a .svelte import must resolve to the component file")
        self.assertIn("app/src/lib/query.ts", found)

    def test_route_depends_on_the_component_it_renders(self) -> None:
        rows = self.conn.execute(
            "SELECT dep.file FROM edges e "
            "JOIN nodes src ON src.id = e.src "
            "JOIN nodes dep ON dep.id = e.dst "
            "WHERE e.kind='depends_on' AND src.file LIKE '%search/+page.svelte'"
        ).fetchall()
        self.assertIn("app/src/components/SearchSuggest.svelte", {r[0] for r in rows})


class DetectionTests(unittest.TestCase):
    """Two ways a Svelte project gets missed, both of which happened."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="coograph-detect-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel: str, body: str) -> None:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_manifest_in_a_subdirectory_counts(self) -> None:
        """app/ beside admin/ leaves the root without a package.json."""
        self._write("app/package.json", json.dumps(
            {"devDependencies": {"@sveltejs/kit": "^2.0.0"}}))
        self._write("admin/package.json", json.dumps(
            {"dependencies": {"svelte": "^4.0.0"}}))
        self.assertIn("svelte", detect_stack(self.tmp))

    def test_extensions_alone_are_enough(self) -> None:
        """No manifest anywhere, just components on disk."""
        self._write("src/App.svelte", "<p>hi</p>\n")
        self.assertIn("svelte", detect_stack(self.tmp))

    def test_a_sibling_language_is_not_suppressed(self) -> None:
        """Detecting svelte from a manifest must not hide the Python scripts.

        The extension scan used to run only when nothing else was found.
        """
        self._write("app/package.json", json.dumps(
            {"devDependencies": {"svelte": "^5.0.0"}}))
        self._write("scripts/build_coords.py", "def main():\n    return 1\n")
        stacks = detect_stack(self.tmp)
        self.assertIn("svelte", stacks)
        self.assertIn("python", stacks)

    def test_the_extension_map_actually_gets_svelte(self) -> None:
        """Detection reporting the stack is not the same as parsing the files."""
        self._write("src/App.svelte", "<p>hi</p>\n")
        self.assertIn(".svelte", get_parsers(detect_stack(self.tmp)))


if __name__ == "__main__":
    unittest.main()
