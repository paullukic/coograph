#!/usr/bin/env python3
"""build-plugin: assemble the Coograph Claude plugin (Claude Code + Cowork).

The sources stay where every other tool reads them (.github/skills/,
.github/agents/, .claude/commands/, .claude/hooks/). This script generates
plugin/ and .claude-plugin/marketplace.json from them, so the repo doubles as a
plugin marketplace. Never edit plugin/ by hand: edit the source, then rebuild.

stdlib only. Run from anywhere:
    python .github/scripts/build-plugin.py          # regenerate plugin/ + marketplace
    python .github/scripts/build-plugin.py --check  # exit 1 if committed output is stale
    python .github/scripts/build-plugin.py --zip    # also write dist/coograph.plugin

Exit 0 on success, 1 on drift (--check) or invalid source frontmatter.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Repo root = two levels up from this file (.github/scripts/build-plugin.py).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PLUGIN_NAME = "coograph"
VERSION = "1.2.0"  # bump on every release so marketplace Update picks it up
DESCRIPTION = (
    "Graph-first AI coding workflow: Plan, Propose, Apply, Review, Archive with "
    "OpenSpec gates, evidence-based agents, and guardrail hooks."
)
AUTHOR = {"name": "Paul Lukic", "url": "https://github.com/paullukic"}

PLUGIN_REL = Path("plugin")
MARKETPLACE_REL = Path(".claude-plugin") / "marketplace.json"
ZIP_REL = Path("dist") / f"{PLUGIN_NAME}.plugin"

# .claude/commands/<name>.md -> plugin/skills/<name>/SKILL.md. The commands carry
# no frontmatter, so each gets an explicit trigger-oriented description here.
# coograph-init / coograph-new-ticket are not listed: they only wrap skills the
# plugin already ships from .github/skills/.
COMMAND_SKILLS = {
    "coograph-plan": (
        "Interview-driven planning. Investigates the codebase with code-graph, asks "
        "clarifying questions one at a time, and produces a work plan with acceptance "
        "criteria. Never implements. Use for new tickets or unclear requirements."
    ),
    "coograph-review": (
        "Strict read-only review of the current changes for spec compliance, convention "
        "violations, logic bugs, and architecture. Every finding cites a verbatim quote "
        "from a fresh file read. Use after implementation, before declaring done."
    ),
    "coograph-verify": (
        "Evidence-based completion check. Runs build, tests, and diagnostics itself and "
        "validates acceptance criteria, ending in a PASS / FAIL / INCOMPLETE verdict. "
        "Use when work is claimed complete."
    ),
    "coograph-debug": (
        "Root-cause a bug or build error with minimal investigation, then apply the "
        "smallest fix. Reproduce, gather evidence, fix, verify, with a 3-attempt "
        "circuit breaker. Use for failing builds, tests, or runtime errors."
    ),
    "coograph-search": (
        "Fast read-only codebase search and Q&A with file:line evidence, code-graph "
        "first. Depth levels: quick, medium, thorough. Use to answer where/what/how "
        "questions about the code."
    ),
}

# Files coograph-init copies into target projects (SKILL.md Step 3 + Step 6a),
# relative to the repo root. Mirrored under plugin/template/ so plugin-mode init
# has the same template root layout as a coograph checkout.
TEMPLATE_PATHS = [
    ".github/copilot-instructions.md",
    ".github/instructions",
    ".github/skills",
    ".github/agents",
    ".github/code-graph",
    ".github/retro",
    ".claude/commands",
    ".claude/hooks",
    ".claude/settings.json",
    ".agents/skills/coograph-init",
    ".opencode/commands",
    "templates",
    "openspec/config.yaml",
    "CLAUDE.md",
    "AGENTS.md",
]

# "tests" keeps .github/retro/tests/ (fixtures + unittest files) out of the
# template. "rules.json" keeps this repo's live Retro registry out too:
# downstream projects seed theirs from rules.seed.json (init / sync /
# retro.py --merge-seed), and a live registry must never ship as a template.
SKIP_NAMES = {
    ".gitkeep", "__pycache__", "node_modules", "settings.local.json", ".DS_Store",
    "tests", "rules.json",
}
SKIP_SUFFIXES = {".pyc"}

HOOK_PATH_RE = re.compile(r'"\$CLAUDE_PROJECT_DIR/\.claude/hooks/([\w.-]+\.py)"')
BLOCK_SCALARS = {">", "|", ">-", "|-", ">+", "|+"}

# Repo paths git would commit (tracked + untracked-not-ignored); None when git is
# unavailable. Set by build() so local junk under source paths never ships.
_visible: set[str] | None = None


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_visible() -> set[str] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return {p for p in out.decode("utf-8", "replace").split("\0") if p}


def _shippable(path: Path) -> bool:
    return _visible is None or path.relative_to(REPO_ROOT).as_posix() in _visible


def _skipped(path: Path) -> bool:
    return any(part in SKIP_NAMES for part in path.parts) or path.suffix in SKIP_SUFFIXES


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy a repo file or directory byte-for-byte, dropping SKIP_NAMES entries
    and files git would not commit."""
    if src.is_file():
        if not _shippable(src):
            raise BuildError(f"{src.relative_to(REPO_ROOT).as_posix()} is ignored by git; it would not ship")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        if item.is_dir() or _skipped(rel) or not _shippable(item):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, data: dict) -> None:
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _frontmatter(text: str) -> tuple[dict[str, str], int] | None:
    """Parse a leading `---` block into flat key/value pairs.

    Returns (fields, index of the closing `---` line) or None when absent.
    Top-level scalars only; good enough for name/description without YAML.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fields, i
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return None


def _validate_skill(skill_md: Path) -> None:
    parsed = _frontmatter(skill_md.read_text(encoding="utf-8-sig"))
    rel = skill_md.relative_to(skill_md.parents[2])
    if parsed is None:
        raise BuildError(f"{rel}: missing frontmatter")
    fields, _ = parsed
    if fields.get("name") != skill_md.parent.name:
        raise BuildError(f"{rel}: name {fields.get('name')!r} != directory {skill_md.parent.name!r}")
    description = fields.get("description", "")
    if description in BLOCK_SCALARS:
        raise BuildError(f"{rel}: multi-line (block scalar) description is not supported; use one line")
    if not 1 <= len(description) <= 1024:
        raise BuildError(f"{rel}: description must be 1-1024 chars (got {len(description)})")


# ---------------------------------------------------------------------------
# Plugin components
# ---------------------------------------------------------------------------


def _build_manifest(plugin: Path) -> None:
    _write_json(plugin / ".claude-plugin" / "plugin.json", {
        "name": PLUGIN_NAME,
        "version": VERSION,
        "description": DESCRIPTION,
        "author": AUTHOR,
        "homepage": "https://coograph.com",
        "repository": "https://github.com/paullukic/coograph",
        "license": "MIT",
        "keywords": ["workflow", "openspec", "code-review", "code-graph", "agents"],
    })


def _build_skills(plugin: Path) -> None:
    skills_src = REPO_ROOT / ".github" / "skills"
    for skill_dir in sorted(p for p in skills_src.iterdir() if p.is_dir()):
        _copy_tree(skill_dir, plugin / "skills" / skill_dir.name)

    for name, description in COMMAND_SKILLS.items():
        if (skills_src / name).exists():
            raise BuildError(f"command {name} collides with .github/skills/{name}")
        src = REPO_ROOT / ".claude" / "commands" / f"{name}.md"
        body = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        if body.startswith("---"):
            raise BuildError(f"{src.relative_to(REPO_ROOT)}: unexpected frontmatter")
        _write_text(
            plugin / "skills" / name / "SKILL.md",
            f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        )

    for skill_md in sorted((plugin / "skills").glob("*/SKILL.md")):
        _validate_skill(skill_md)


def _build_agents(plugin: Path) -> None:
    """.github/agents/<x>.agent.md -> agents/<x>.md with a kebab-case name."""
    for src in sorted((REPO_ROOT / ".github" / "agents").glob("*.agent.md")):
        name = src.name.removesuffix(".agent.md").lower()
        text = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        parsed = _frontmatter(text)
        if parsed is None:
            raise BuildError(f"{src.relative_to(REPO_ROOT)}: missing frontmatter")
        _, end = parsed
        lines = text.split("\n")
        for i in range(1, end):
            if lines[i].startswith("name:"):
                lines[i] = f"name: {name}"
                break
        else:
            raise BuildError(f"{src.relative_to(REPO_ROOT)}: no name: field")
        _write_text(plugin / "agents" / f"{name}.md", "\n".join(lines))


def _build_hooks(plugin: Path) -> None:
    """Derive hooks/hooks.json from .claude/settings.json so wiring never drifts."""
    # utf-8-sig: settings.json may carry a BOM (Windows editors add one).
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8-sig"))
    hooks = settings.get("hooks") or {}
    for groups in hooks.values():
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command", "")
                if not HOOK_PATH_RE.search(command):
                    raise BuildError(f"cannot map hook command to plugin path: {command}")
                # --plugin makes the script defer to a project-level copy and stay
                # silent outside Coograph projects (see _plugin_should_skip).
                hook["command"] = HOOK_PATH_RE.sub(
                    r'"${CLAUDE_PLUGIN_ROOT}/hooks/\1"', command
                ) + " --plugin"
    _write_json(plugin / "hooks" / "hooks.json", {"hooks": hooks})

    for script in sorted((REPO_ROOT / ".claude" / "hooks").glob("*.py")):
        _copy_tree(script, plugin / "hooks" / script.name)


def _build_template(plugin: Path) -> None:
    for rel in TEMPLATE_PATHS:
        src = REPO_ROOT / rel
        if not src.exists():
            raise BuildError(f"template source missing: {rel}")
        _copy_tree(src, plugin / "template" / rel)


def _build_readme(plugin: Path) -> None:
    skills = ", ".join(sorted(p.parent.name for p in (plugin / "skills").glob("*/SKILL.md")))
    agents = ", ".join(sorted(p.stem for p in (plugin / "agents").glob("*.md")))
    _write_text(plugin / "README.md", f"""# Coograph plugin

{DESCRIPTION}

Generated by `.github/scripts/build-plugin.py` from the coograph repo. Do not edit
files here; edit the sources and rebuild. Docs: https://coograph.com/docs/

- **Skills** (`/{PLUGIN_NAME}:<skill>`): {skills}.
- **Agents**: {agents}.
- **Hooks**: block edits to generated files, bash audit log, code-graph status,
  OpenSpec scope warnings. Active only in projects set up with coograph-init.
  When a project also wires its own copies, each event is handled exactly once.

Start with `/{PLUGIN_NAME}:coograph-init` in a project folder. Marketplace Update
refreshes this plugin only; re-run init to refresh files it copied into a project.
""")


def build(plugin: Path, marketplace: Path) -> None:
    global _visible
    _visible = _git_visible()
    if plugin.exists():
        shutil.rmtree(plugin)
    plugin.mkdir(parents=True)
    _build_manifest(plugin)
    _build_skills(plugin)
    _build_agents(plugin)
    _build_hooks(plugin)
    _build_template(plugin)
    _build_readme(plugin)
    _copy_tree(REPO_ROOT / "LICENSE", plugin / "LICENSE")

    _write_json(marketplace, {
        "name": PLUGIN_NAME,
        "owner": AUTHOR,
        "metadata": {"description": "Coograph plugin marketplace", "version": VERSION},
        "plugins": [{
            "name": PLUGIN_NAME,
            "source": "./" + PLUGIN_REL.as_posix(),
            "description": DESCRIPTION,
            "version": VERSION,
            "author": AUTHOR,
            "homepage": "https://coograph.com",
            "license": "MIT",
        }],
    })


# ---------------------------------------------------------------------------
# --check / --zip
# ---------------------------------------------------------------------------


def _files(root: Path) -> dict[str, bytes]:
    """Map relative posix path -> content with CRLF normalized (autocrlf-safe)."""
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): p.read_bytes().replace(b"\r\n", b"\n")
        for p in root.rglob("*")
        if p.is_file() and not _skipped(p.relative_to(root))
    }


def check() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        fresh_plugin = Path(tmp) / "plugin"
        fresh_marketplace = Path(tmp) / "marketplace.json"
        build(fresh_plugin, fresh_marketplace)
        expected = _files(fresh_plugin)
        actual = _files(REPO_ROOT / PLUGIN_REL)
        problems = [f"missing  {PLUGIN_REL.as_posix()}/{p}" for p in sorted(expected.keys() - actual.keys())]
        problems += [f"extra    {PLUGIN_REL.as_posix()}/{p}" for p in sorted(actual.keys() - expected.keys())]
        problems += [
            f"stale    {PLUGIN_REL.as_posix()}/{p}"
            for p in sorted(expected.keys() & actual.keys())
            if expected[p] != actual[p]
        ]
        committed = REPO_ROOT / MARKETPLACE_REL
        if not committed.exists() or (
            committed.read_bytes().replace(b"\r\n", b"\n") != fresh_marketplace.read_bytes()
        ):
            problems.append(f"stale    {MARKETPLACE_REL.as_posix()}")

    for line in problems:
        print(line)
    if problems:
        print(f"FAIL: {len(problems)} path(s) out of date. Run: python .github/scripts/build-plugin.py")
        return 1
    print(f"PASS: {PLUGIN_REL.as_posix()}/ and {MARKETPLACE_REL.as_posix()} match sources")
    return 0


def write_zip(plugin: Path, out: Path) -> None:
    """Zip plugin/ contents with .claude-plugin/ at the archive root (Cowork upload)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in plugin.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(plugin).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = path.read_bytes()
            if b"\0" not in data:  # text: LF endings whatever the checkout's autocrlf
                data = data.replace(b"\r\n", b"\n")
            zf.writestr(info, data)


def main() -> int:
    args = set(sys.argv[1:])
    unknown = args - {"--check", "--zip"}
    if unknown:
        print(f"unknown argument(s): {' '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    try:
        if "--check" in args:
            return check()
        build(REPO_ROOT / PLUGIN_REL, REPO_ROOT / MARKETPLACE_REL)
        count = sum(1 for p in (REPO_ROOT / PLUGIN_REL).rglob("*") if p.is_file())
        print(f"Built {PLUGIN_REL.as_posix()}/ ({count} files) + {MARKETPLACE_REL.as_posix()} v{VERSION}")
        if "--zip" in args:
            write_zip(REPO_ROOT / PLUGIN_REL, REPO_ROOT / ZIP_REL)
            print(f"Wrote {ZIP_REL.as_posix()}")
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
