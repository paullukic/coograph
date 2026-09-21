#!/usr/bin/env python3
"""Cross-tool invocation drift check (issue #2).

Coograph ships per-tool config files for 8 tools. Each must point agents at the
canonical skill `.github/skills/coograph-init/SKILL.md` and advertise the same
trigger forms (`/coograph-init`, `$coograph-init` for Codex, plus natural-language
phrases). When one file's path or trigger phrasing changes, the others silently
drift. This script asserts they stay in lockstep.

stdlib only. Run from anywhere:
    uv run .github/scripts/check-invocations.py
    python .github/scripts/check-invocations.py

Exit 0 when every manifest file passes, exit 1 on any drift or missing file.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root = two levels up from this file (.github/scripts/check-invocations.py).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CANONICAL_SKILL_PATH = ".github/skills/coograph-init/SKILL.md"
SLASH_FORM = "/coograph-init"
CODEX_FORM = "$coograph-init"
# At least ONE of these must appear in every rule_config / codex description. Wording
# may vary across files as long as a shared phrase survives — this is the anti-drift
# anchor, not an exact-string mandate.
CANONICAL_PHRASES = ("initialize the project", "set up coograph")

# Roles drive which assertions apply. See openspec invocation-consistency spec.
CANONICAL = "canonical"        # the source-of-truth skill; others point at it
CODEX_SKILL = "codex_skill"    # Codex CLI skill: advertises $ trigger in frontmatter
RULE_CONFIG = "rule_config"    # human/agent-facing rule files that advertise triggers
SLASH_WRAPPER = "slash_wrapper"  # thin slash-command files invoked by the slash itself

# (path relative to repo root, role)
MANIFEST = [
    (".github/skills/coograph-init/SKILL.md", CANONICAL),
    (".agents/skills/coograph-init/SKILL.md", CODEX_SKILL),
    ("AGENTS.md", RULE_CONFIG),
    ("templates/aider/CONVENTIONS.md", RULE_CONFIG),
    ("templates/windsurf/.windsurfrules", RULE_CONFIG),
    ("templates/cline/.clinerules", RULE_CONFIG),
    ("templates/cursor/.cursor/rules/coograph.mdc", RULE_CONFIG),
    (".claude/commands/coograph-init.md", SLASH_WRAPPER),
    (".opencode/commands/coograph-init.md", SLASH_WRAPPER),
]


def _line_of(text: str, needle: str) -> int:
    """1-based line number of the first line containing needle, else 1."""
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    return 1


def _frontmatter(text: str) -> dict[str, str]:
    """Parse a leading YAML `---` frontmatter block into a flat dict.

    Only top-level `key: value` scalars are needed (name, description); good enough
    without a YAML dependency. Returns {} when no frontmatter block is present.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def _has_phrase(text: str) -> bool:
    return any(p in text for p in CANONICAL_PHRASES)


def check_file(rel_path: str, role: str) -> list[str]:
    """Return a list of failure reasons (empty == PASS) for one manifest file."""
    path = REPO_ROOT / rel_path
    if not path.exists():
        return [f"{rel_path}  missing file (expected {role} invocation carrier)"]

    text = path.read_text(encoding="utf-8")
    fails: list[str] = []

    # Reference to the canonical skill path — every role except canonical itself.
    if role != CANONICAL and CANONICAL_SKILL_PATH not in text:
        fails.append(f"{rel_path}:{_line_of(text, '## Invocation') or 1}  "
                     f"does not reference canonical path {CANONICAL_SKILL_PATH!r}")

    # Slash form — every role.
    if SLASH_FORM not in text:
        fails.append(f"{rel_path}:1  missing slash form {SLASH_FORM!r}")

    # Natural-language phrase — rule configs only (wrappers/canonical are exempt).
    if role == RULE_CONFIG and not _has_phrase(text):
        fails.append(f"{rel_path}:1  missing any canonical phrase "
                     f"(one of {list(CANONICAL_PHRASES)})")

    # Frontmatter name == parent dir — skill files.
    if role in (CANONICAL, CODEX_SKILL):
        fm = _frontmatter(text)
        expected = path.parent.name
        name = fm.get("name")
        if name != expected:
            ln = _line_of(text, "name:")
            fails.append(f"{rel_path}:{ln}  frontmatter name {name!r} "
                         f"does not match dir {expected!r}")

    # Codex skill description must carry the $ trigger and a phrase.
    if role == CODEX_SKILL:
        fm = _frontmatter(text)
        desc = fm.get("description", "")
        ln = _line_of(text, "description:")
        if CODEX_FORM not in desc:
            fails.append(f"{rel_path}:{ln}  description missing Codex trigger "
                         f"{CODEX_FORM!r}")
        if not _has_phrase(desc):
            fails.append(f"{rel_path}:{ln}  description missing any canonical phrase "
                         f"(one of {list(CANONICAL_PHRASES)})")

    return fails



# Number words the README and SETUP use for the tool count. A rename that drops
# or adds a tool must not leave "eight tools" behind, which is exactly what the
# Windsurf -> Devin Desktop rename nearly did.
COUNT_WORDS = {
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}

# Files that state the count in prose, and the invocation table they must agree
# with. The table is the source of truth; the prose is derived.
COUNT_SOURCES = ("README.md", "SETUP.md")


def _invocation_rows(text: str) -> int:
    """Count data rows in the per-tool invocation table.

    The table is the one whose header names the canonical skill trigger column;
    rows start with `| **` and are not the separator.
    """
    rows = 0
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and "Invoke with" in stripped:
            in_table = True
            continue
        if in_table:
            if not stripped.startswith("|"):
                break
            if set(stripped) <= set("|-: "):
                continue
            rows += 1
    return rows


def check_tool_count() -> list[str]:
    """The stated tool count must match the invocation table it describes."""
    fails: list[str] = []
    table_rows = _invocation_rows((REPO_ROOT / "README.md").read_text(encoding="utf-8"))
    if table_rows == 0:
        return ["README.md: could not find the invocation table to count"]

    expected = COUNT_WORDS.get(table_rows)
    for rel in COUNT_SOURCES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for n, word in COUNT_WORDS.items():
            if n == table_rows:
                continue
            for phrase in (f"{word} tools", f"{n} tools"):
                if phrase in text:
                    fails.append(
                        f"{rel}:{_line_of(text, phrase)} says {phrase!r} but the "
                        f"README invocation table has {table_rows} rows"
                    )
        if expected and f"{expected} tools" not in text and f"{table_rows} tools" not in text:
            continue  # the file need not state a count at all
    return fails


def main() -> int:
    total = len(MANIFEST)
    passed = 0
    all_fails: list[str] = []

    for rel_path, role in MANIFEST:
        fails = check_file(rel_path, role)
        if fails:
            for reason in fails:
                print(f"FAIL {reason}")
            all_fails.extend(fails)
        else:
            print(f"PASS {rel_path}")
            passed += 1

    count_fails = check_tool_count()
    for reason in count_fails:
        print(f"FAIL {reason}")
    if not count_fails:
        print("PASS tool count matches the invocation table")

    fail_count = total - passed + len(count_fails)
    print()
    print(f"checked {total + 1}  pass {passed + (0 if count_fails else 1)}  fail {fail_count}")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
