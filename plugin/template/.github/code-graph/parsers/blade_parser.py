"""Laravel Blade template parser.

Detects template-to-template and template-to-component dependencies that
plain PHP parsing misses:

  - @extends('layouts.app')      -> resources/views/layouts/app.blade.php
  - @include('partials.foo')     -> resources/views/partials/foo.blade.php
  - @component('comp')           -> resources/views/comp.blade.php
  - @each('partials.row', ...)   -> resources/views/partials/row.blade.php
  - @livewire('foo-bar')         -> app/Livewire/FooBar.php
  - <x-foo.bar />                -> resources/views/components/foo/bar.blade.php
                                    (and app/View/Components/Foo/Bar.php as alt)
  - <livewire:foo-bar />         -> app/Livewire/FooBar.php

Each match is emitted as an `imports` edge with a fully-qualified relative path.
The builder's `_resolve_file_deps` then turns the path into a `depends_on`
edge if the target file exists in the graph.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import register, nid

STACK = "blade"
EXTENSIONS = frozenset({".blade.php"})

VIEWS_ROOT = "resources/views"
COMPONENTS_VIEW_ROOT = "resources/views/components"
COMPONENTS_CLASS_ROOT = "app/View/Components"
LIVEWIRE_CLASS_ROOT = "app/Livewire"

# Blade @directive('view.name', ...)
_DIRECTIVE_RE = re.compile(
    r"@(extends|include|includeIf|includeWhen|includeUnless|includeFirst|"
    r"component|each|livewire)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)

# <x-foo.bar /> or <x-foo.bar attr="..."> — exclude reserved x-slot/x-show etc.
_X_TAG_RE = re.compile(r"<x-([a-z][a-z0-9._-]*)", re.IGNORECASE)

# <livewire:foo-bar />
_LW_TAG_RE = re.compile(r"<livewire:([a-z][a-z0-9._-]*)", re.IGNORECASE)

# Reserved x- prefixes that are NOT components (Alpine/Laravel built-ins)
_X_RESERVED = frozenset({"slot", "show", "data", "init", "bind", "on", "if",
                         "for", "model", "text", "html", "ref", "cloak"})


def _view_to_path(name: str) -> str:
    """`foo.bar.baz` -> `resources/views/foo/bar/baz.blade.php`."""
    return f"{VIEWS_ROOT}/{name.replace('.', '/')}.blade.php"


def _component_view_path(name: str) -> str:
    """`foo.bar` -> `resources/views/components/foo/bar.blade.php`."""
    return f"{COMPONENTS_VIEW_ROOT}/{name.replace('.', '/').replace('-', '-')}.blade.php"


def _kebab_to_pascal(name: str) -> str:
    """`foo-bar.baz-qux` -> `FooBar/BazQux` (PHP class file path segments)."""
    parts = []
    for seg in name.split('.'):
        parts.append(''.join(w.capitalize() for w in seg.split('-')))
    return '/'.join(parts)


def _component_class_path(name: str) -> str:
    """`foo-bar.baz` -> `app/View/Components/FooBar/Baz.php`."""
    return f"{COMPONENTS_CLASS_ROOT}/{_kebab_to_pascal(name)}.php"


def _livewire_class_path(name: str) -> str:
    """`foo-bar` -> `app/Livewire/FooBar.php`."""
    return f"{LIVEWIRE_CLASS_ROOT}/{_kebab_to_pascal(name)}.php"


@register(STACK, EXTENSIONS)
def parse(path: Path, rel: str, nodes: list, edges: list) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fid = nid("file", rel, rel)
    nodes.append((fid, "file", rel, rel, None, None))

    seen: set[str] = set()

    def _emit(target: str) -> None:
        if target and target not in seen:
            seen.add(target)
            edges.append((fid, target, "imports"))

    # Blade @directives
    for m in _DIRECTIVE_RE.finditer(text):
        directive, name = m.group(1), m.group(2)
        if directive == "livewire":
            _emit(_livewire_class_path(name))
        else:
            _emit(_view_to_path(name))

    # <x-...> components
    for m in _X_TAG_RE.finditer(text):
        name = m.group(1).lower()
        # Skip Alpine/built-in directives (x-show, x-data, x-slot, etc.)
        first = name.split('.', 1)[0].split('-', 1)[0]
        if first in _X_RESERVED:
            continue
        _emit(_component_view_path(name))
        _emit(_component_class_path(name))

    # <livewire:...> components
    for m in _LW_TAG_RE.finditer(text):
        _emit(_livewire_class_path(m.group(1).lower()))
