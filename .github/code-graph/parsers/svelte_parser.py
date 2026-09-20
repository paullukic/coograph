"""Svelte parser — .svelte single-file components, Svelte 4 and 5, SvelteKit.

Before this existed, `svelte` was a detected stack with top priority in the
parser registry and nothing registered under it, so `.svelte` never reached the
extension map and every component in a SvelteKit project was invisible to the
graph while detection still reported the stack as found.

Handles:
  - `<script>` and `<script module>` / `<script context="module">` blocks,
    parsed with the same declaration patterns a .ts file gets
  - a component node named after the file, so `SearchSuggest.svelte` is
    reachable by the name a person would type
  - SvelteKit route files (`+page.svelte`, `+layout.svelte`, ...), which are
    named after their route directory because "+page" is not a symbol anyone
    searches for
  - `<style src="...">` and `<svelte:component this={...}>` references

Not handled, deliberately: runes (`$state`, `$derived`, `$props`) declare
reactive values rather than callable symbols, and markup-level component usage,
which is already covered by the import that brought the component in.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid
from ._tsjs import parse_script_block

STACK = "svelte"
EXTENSIONS = frozenset({".svelte"})

# Matches <script>, <script lang="ts">, <script module>, and the Svelte 4
# <script context="module"> spelling.
_SCRIPT_RE = re.compile(r'<script\b[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)

# <style src="./theme.css">
_STYLE_SRC_RE = re.compile(r'<style\b[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)

# SvelteKit reserves a leading + for route files.
_ROUTE_PREFIX = "+"


def _component_name(path: Path, rel: str) -> str:
    """The name a person would use for this component.

    `SearchSuggest.svelte` is SearchSuggest. `routes/search/+page.svelte` is
    search, because the route is how people refer to it and "+page" would be a
    node name that collides with every other route in the project.
    """
    stem = path.stem
    if not stem.startswith(_ROUTE_PREFIX):
        return stem

    parent = Path(rel).parent.name
    # routes/+page.svelte and the like have nothing better to offer.
    return parent or stem.lstrip(_ROUTE_PREFIX)


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    for script_text in _SCRIPT_RE.findall(text):
        parse_script_block(script_text, rel, fid, nodes, edges)

    name = _component_name(path, rel)
    if name:
        comp_id = nid("class", rel, name)
        nodes.append((comp_id, "class", name, rel, 1, None))
        edges.append((fid, comp_id, "contains"))

    for m in _STYLE_SRC_RE.finditer(text):
        edges.append((fid, m.group(1), "imports"))
