"""Parser registry with automatic stack detection.

Each parser lives in its own module and registers itself via the
``@register`` decorator.  At build time the builder calls
``detect_stack(root)`` to figure out which tech stacks are present,
then ``get_parsers(stack)`` to obtain a mapping of file-extension to
parser callable.

Parser callable signature (same as before)::

    def parse(path: Path, rel: str, nodes: list, edges: list) -> None
"""

from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from typing import Callable, Protocol

# ---------------------------------------------------------------------------
# Parser protocol
# ---------------------------------------------------------------------------

ParseFn = Callable[[Path, str, list, list], None]


class ParserModule(Protocol):
    """Each parser module must expose these attributes."""
    STACK: str                          # e.g. "react", "java", "python"
    EXTENSIONS: frozenset[str]          # e.g. frozenset({".ts", ".tsx"})
    def parse(self, path: Path, rel: str, nodes: list, edges: list) -> None: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, dict] = {}  # stack_name -> {"extensions": set, "parse": fn}


def register(stack: str, extensions: frozenset[str]):
    """Decorator to register a parser for a given stack and set of extensions."""
    def wrapper(parse_fn: ParseFn) -> ParseFn:
        _REGISTRY[stack] = {
            "extensions": extensions,
            "parse": parse_fn,
        }
        return parse_fn
    return wrapper


def get_all_extensions() -> frozenset[str]:
    """Return every file extension handled by at least one registered parser."""
    exts: set[str] = set()
    for entry in _REGISTRY.values():
        exts |= entry["extensions"]
    return frozenset(exts)


def get_parsers(stacks: set[str]) -> dict[str, ParseFn]:
    """Return extension -> parse function mapping for the detected stacks.

    If multiple stacks handle the same extension, the more specific stack wins
    (e.g. "react" beats "generic_ts" for .tsx).
    """
    # Priority: stack-specific parsers override generic ones
    PRIORITY = [
        # generic / broad stacks first (lowest priority)
        "structured", "css", "python", "golang", "rust", "php",
        "ruby", "swift", "dart",
        # language-family stacks
        "java", "dotnet",
        # framework-specific stacks (highest priority — override language parsers)
        "react", "angular", "vue", "svelte", "blade",
    ]

    ext_map: dict[str, ParseFn] = {}
    # Apply in priority order so higher-priority stacks overwrite lower
    for stack_name in PRIORITY:
        if stack_name not in stacks or stack_name not in _REGISTRY:
            continue
        entry = _REGISTRY[stack_name]
        for ext in entry["extensions"]:
            ext_map[ext] = entry["parse"]

    # Also include any registered stacks not in the priority list
    for stack_name in stacks:
        if stack_name in _REGISTRY and stack_name not in set(PRIORITY):
            entry = _REGISTRY[stack_name]
            for ext in entry["extensions"]:
                ext_map.setdefault(ext, entry["parse"])

    # Tree-sitter overrides all regex parsers for any extension it supports.
    # Runs unconditionally — tree_sitter_parser only registers extensions whose
    # language packages are actually installed, so uninstalled languages
    # keep their regex parser in ext_map.
    if "tree_sitter" in _REGISTRY:
        ts_entry = _REGISTRY["tree_sitter"]
        for ext in ts_entry["extensions"]:
            ext_map[ext] = ts_entry["parse"]

    return ext_map


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------

def detect_stack(root: Path) -> set[str]:
    """Detect which tech stacks are present in the project.

    Looks at manifest files (package.json, go.mod, pom.xml, etc.) and
    falls back to file-extension scanning for projects without manifests.
    """
    stacks: set[str] = set()

    # -- Always include structured file parser --
    stacks.add("structured")

    # -- Python --
    if _any_exist(root, "requirements.txt", "pyproject.toml", "setup.py",
                  "setup.cfg", "Pipfile", "poetry.lock"):
        stacks.add("python")

    # -- JavaScript / TypeScript ecosystems --
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pkg = {}

        all_deps = set()
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            all_deps |= set(pkg.get(key, {}).keys())

        # React (includes Next.js, Remix, Gatsby)
        if all_deps & {"react", "react-dom", "next", "remix", "gatsby",
                       "@remix-run/react", "preact"}:
            stacks.add("react")
            stacks.add("css")

        # Angular
        if all_deps & {"@angular/core", "@angular/common"}:
            stacks.add("angular")
            stacks.add("css")

        # Vue
        if all_deps & {"vue", "nuxt", "vue-router", "@vue/compiler-sfc"}:
            stacks.add("vue")
            stacks.add("css")

        # Svelte
        if all_deps & {"svelte", "@sveltejs/kit"}:
            stacks.add("svelte")
            stacks.add("css")

        # Generic Node/TS project (no framework detected)
        if not stacks & {"react", "angular", "vue", "svelte"}:
            stacks.add("react")  # use react parser as generic TS/JS parser
            # Check if CSS files are likely present
            if all_deps & {"tailwindcss", "sass", "less", "postcss",
                          "styled-components", "@emotion/react", "css-loader"}:
                stacks.add("css")

    # -- Java / Kotlin / Scala --
    if _any_exist(root, "pom.xml", "build.gradle", "build.gradle.kts",
                  "settings.gradle", "settings.gradle.kts", ".mvn"):
        stacks.add("java")

    # -- .NET (C#, F#) --
    if _any_glob(root, "*.sln") or _any_glob(root, "*.csproj") or \
       _any_glob(root, "*.fsproj") or _any_exist(root, "global.json"):
        stacks.add("dotnet")

    # -- Go --
    if _any_exist(root, "go.mod", "go.sum"):
        stacks.add("golang")

    # -- Rust --
    if _any_exist(root, "Cargo.toml", "Cargo.lock"):
        stacks.add("rust")

    # -- PHP --
    if _any_exist(root, "composer.json", "composer.lock", "artisan"):
        stacks.add("php")
        # Laravel projects ship Blade templates under resources/views
        if (root / "artisan").exists() or (root / "resources" / "views").exists():
            stacks.add("blade")

    # -- Ruby --
    if _any_exist(root, "Gemfile", "Gemfile.lock", "Rakefile"):
        stacks.add("ruby")

    # -- Swift --
    if _any_exist(root, "Package.swift") or _any_glob(root, "*.xcodeproj"):
        stacks.add("swift")

    # -- Dart / Flutter --
    if _any_exist(root, "pubspec.yaml", "pubspec.lock"):
        stacks.add("dart")

    # -- Fallback: scan for file extensions if no manifests found --
    if not stacks - {"structured"}:
        stacks |= _detect_by_extensions(root)

    return stacks


def _any_exist(root: Path, *names: str) -> bool:
    return any((root / n).exists() for n in names)


def _any_glob(root: Path, pattern: str) -> bool:
    return any(True for _ in root.glob(pattern))


def _detect_by_extensions(root: Path) -> set[str]:
    """Fallback: sample up to 200 files and detect stacks from extensions."""
    ext_counts: dict[str, int] = {}
    count = 0
    for dp, dirs, files in __import__("os").walk(root):
        dirs[:] = [d for d in dirs if d not in {
            "node_modules", ".git", ".venv", "venv", "__pycache__",
            "target", "dist", "build", ".gradle", ".next",
        }]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
                count += 1
                if count > 200:
                    break
        if count > 200:
            break

    stacks: set[str] = set()
    if ext_counts.get(".py", 0) > 0:
        stacks.add("python")
    if ext_counts.get(".java", 0) > 0 or ext_counts.get(".kt", 0) > 0:
        stacks.add("java")
    if ext_counts.get(".cs", 0) > 0 or ext_counts.get(".fs", 0) > 0:
        stacks.add("dotnet")
    if ext_counts.get(".go", 0) > 0:
        stacks.add("golang")
    if ext_counts.get(".rs", 0) > 0:
        stacks.add("rust")
    if ext_counts.get(".php", 0) > 0:
        stacks.add("php")
    if ext_counts.get(".rb", 0) > 0:
        stacks.add("ruby")
    if ext_counts.get(".swift", 0) > 0:
        stacks.add("swift")
    if ext_counts.get(".dart", 0) > 0:
        stacks.add("dart")
    if any(ext_counts.get(e, 0) > 0 for e in (".ts", ".tsx", ".js", ".jsx")):
        stacks.add("react")
    if any(ext_counts.get(e, 0) > 0 for e in (".css", ".scss", ".less")):
        stacks.add("css")
    return stacks


# ---------------------------------------------------------------------------
# Shared helpers (used by multiple parsers)
# ---------------------------------------------------------------------------

def nid(kind: str, file: str, name: str) -> str:
    """Generate a stable node ID."""
    return hashlib.sha1(f"{kind}\x00{file}\x00{name}".encode()).hexdigest()[:16]


def find_scope(pos: int, scopes: list) -> str | None:
    """Return the nid of the innermost scope (class/struct/impl block) that
    contains text byte-position *pos*, or None if *pos* is outside all scopes.

    *scopes*: list of ``(node_id, open_brace_pos, close_brace_pos)`` tuples
    built by each parser while scanning class/struct/impl declarations.
    """
    owner_nid, owner_start = None, -1
    for c_nid, start, end in scopes:
        if start < pos < end and start > owner_start:
            owner_nid, owner_start = c_nid, start
    return owner_nid


def brace_end(text: str, open_pos: int) -> int:
    """Given the position of an opening ``{``, return the position just after
    the matching closing ``}``.  Returns ``open_pos + 1`` on malformed input.
    """
    depth, pos = 1, open_pos + 1
    while pos < len(text) and depth > 0:
        if text[pos] == '{':
            depth += 1
        elif text[pos] == '}':
            depth -= 1
        pos += 1
    return pos


def is_test(rel: str) -> bool:
    """Check if a relative path looks like a test file."""
    lower = rel.lower()
    return any(m in lower for m in ("test", "spec", "__tests__", "_test", "_spec"))


# ---------------------------------------------------------------------------
# Auto-import all parser modules so they self-register
# ---------------------------------------------------------------------------

def _load_parsers():
    """Import all parser modules in this package.

    Loads in two phases so the registry ends up well-formed:
      1. Native top-level modules + the `tree_sitter` package (skipping any
         name starting with '_'). Registrations land directly in `_REGISTRY`.
      2. The `_fallback` package's `load_fallbacks()` -- regex parsers
         register under their own stack names; tree-sitter still wins via
         the ext_map override in `get_parsers` for any extension it supports.
    """
    import importlib
    import pkgutil
    pkg_path = str(Path(__file__).parent)
    for _, modname, _ispkg in pkgutil.iter_modules([pkg_path]):
        if modname.startswith("_"):
            continue
        importlib.import_module(f".{modname}", __package__)

    # Explicit fallback load -- `_fallback` is skipped by the loop above.
    from ._fallback import load_fallbacks
    load_fallbacks()


_load_parsers()
