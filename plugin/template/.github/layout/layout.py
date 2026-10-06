#!/usr/bin/env python3
"""layout: measure instruction files by tier, and guard docs against drift.

Instruction files are read by an agent before it reads any code, so their size
is paid on every task. This script holds them to a declared layout:

    always-loaded   root files every session loads, @ imports resolved
    routers         <workspace>/AGENTS.md, loaded when the agent enters it
    docs            docs/features/<area>.md, read on demand, `paths:` frontmatter
    gotchas         GOTCHAS.md entries, surfaced by a hook when their paths match

The layout is declared in .github/layout/layout.json (project-owned, seeded once
from layout.seed.json, never overwritten by sync).

    python3 .github/layout/layout.py --budget             exit 1 when any tier is over budget
    python3 .github/layout/layout.py --json               full measurement, for retro
    python3 .github/layout/layout.py --guard BASE HEAD    exit 1 when covered code changed but its doc did not
    python3 .github/layout/layout.py --merge-seed [SEED]  create layout.json, or add new seed keys to it

Tokens are bytes // 4, the same estimate retro.py uses. Stdlib only.

Exit codes: 0 ok, 1 over budget / guard failed, 2 bad config or git error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SEED = SCRIPT_DIR / "layout.seed.json"
CONFIG_REL = Path(".github") / "layout" / "layout.json"

# Used when neither layout.json nor the seed can be read. Kept equal to
# layout.seed.json; a test pins that.
DEFAULTS: dict = {
    "version": 1,
    "always_loaded": ["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"],
    "routers": ["*/AGENTS.md", "*/*/AGENTS.md"],
    "docs": ["docs/features/*.md"],
    "gotchas": ["GOTCHAS.md", "*/GOTCHAS.md", "*/*/GOTCHAS.md"],
    "budgets": {"always_loaded": 9000, "router": 2000, "doc": 8000, "gotchas": 8000},
    "guard": {
        "ignore": ["**/*.lock", "**/package-lock.json", "**/pnpm-lock.yaml", "openspec/**", "**/*.md"],
        "skip_marker": "[skip docs]",
    },
    "structural_factor": 1.25,
}

MAX_IMPORT_HOPS = 4  # Claude Code's documented limit for @ imports
GOTCHA_ENTRY_MAX_BYTES = 800
GOTCHA_REQUIRED = ("symptom", "cause", "fix", "paths", "confirmed")
DUPLICATE_MIN_CHARS = 120
PADDING_REPORT_BYTES = 1024
STRUCTURAL_DATED_HEADINGS = 3
WALK_SKIP = {".git", "node_modules", ".code-graph", ".coograph", "__pycache__", ".venv", "venv", "dist", "build"}

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
DATED_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b|\(openspec\s", re.IGNORECASE)
INLINE_CODE_RE = re.compile(r"(`+).*?\1")  # `x` and ``x`` spans alike
IMPORT_RE = re.compile(r"(?<![\w@`])@([A-Za-z0-9_.~/\\-][^\s`]*)")
FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*([^*:]+?):?\*\*:?\s*(.*)$")
PADDING_RE = re.compile(r" {3,}")
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(config: object) -> str | None:
    """Return the first invalid field, or None."""
    if not isinstance(config, dict):
        return "<root>"
    for key in ("always_loaded", "routers", "docs", "gotchas"):
        value = config.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return key
    budgets = config.get("budgets")
    if not isinstance(budgets, dict):
        return "budgets"
    for key in ("always_loaded", "router", "doc", "gotchas"):
        value = budgets.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return f"budgets.{key}"
    guard = config.get("guard")
    if not isinstance(guard, dict):
        return "guard"
    if not isinstance(guard.get("ignore"), list) or not all(isinstance(v, str) for v in guard["ignore"]):
        return "guard.ignore"
    if not isinstance(guard.get("skip_marker"), str) or not guard["skip_marker"]:
        return "guard.skip_marker"
    factor = config.get("structural_factor")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or factor < 1:
        return "structural_factor"
    return None


def _fill(config: dict, defaults: dict) -> dict:
    """Missing keys take defaults, nested one level (budgets, guard)."""
    out = dict(config)
    for key, value in defaults.items():
        if key not in out:
            out[key] = json.loads(json.dumps(value))
        elif isinstance(value, dict) and isinstance(out[key], dict):
            merged = dict(value)
            merged.update(out[key])
            out[key] = merged
    return out


def load_config(cwd: Path) -> tuple[dict, str]:
    """Returns (config, source). Raises ValueError naming a bad field."""
    path = cwd / CONFIG_REL
    if path.is_file():
        try:
            data = _read_json(path)
        except (OSError, ValueError) as e:
            raise ValueError(f"{CONFIG_REL.as_posix()} is not valid JSON: {e}") from e
        data = _fill(data, DEFAULTS) if isinstance(data, dict) else data
        field = validate(data)
        if field:
            raise ValueError(f"{CONFIG_REL.as_posix()} invalid at {field}")
        return data, CONFIG_REL.as_posix()
    try:
        seed = _fill(_read_json(DEFAULT_SEED), DEFAULTS)
        if validate(seed) is None:
            return seed, "seed defaults"
    except (OSError, ValueError):
        pass
    return json.loads(json.dumps(DEFAULTS)), "built-in defaults"


def merge_seed(target: Path, seed_path: Path) -> list[str]:
    """Create target from seed, or add seed keys it lacks. Returns added keys."""
    seed = _read_json(seed_path)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
        return sorted(seed)
    try:
        current = _read_json(target)
    except ValueError as e:
        raise ValueError(f"{target} is not valid JSON, fix or delete it: {e}") from e
    added: list[str] = []
    for key, value in seed.items():
        if key not in current:
            current[key] = value
            added.append(key)
        elif isinstance(value, dict) and isinstance(current[key], dict):
            for sub, sub_value in value.items():
                if sub not in current[key]:
                    current[key][sub] = sub_value
                    added.append(f"{key}.{sub}")
    target.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return added


# ---------------------------------------------------------------------------
# Files and globs
# ---------------------------------------------------------------------------

def glob_regex(pattern: str) -> re.Pattern:
    """`**` crosses directories, `*` and `?` do not. Anchored at the repo root."""
    pattern = pattern.strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(pattern: str, rel: str) -> bool:
    """Root-anchored glob; a pattern without `/` also matches a basename at any depth."""
    pattern = pattern.strip().strip("`").strip()
    if not pattern:
        return False
    if glob_regex(pattern).match(rel):
        return True
    if "/" not in pattern:
        return bool(glob_regex(pattern).match(rel.rsplit("/", 1)[-1]))
    if pattern.endswith("/"):
        return rel.startswith(pattern)
    return False


def list_files(cwd: Path) -> list[str]:
    """Files git would commit (tracked + untracked-not-ignored); a walk without git."""
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
        if out.returncode == 0:
            files = sorted({p for p in out.stdout.decode("utf-8", "replace").split("\0") if p})
            return [f for f in files if (cwd / f).is_file()]
    except (OSError, subprocess.SubprocessError):
        pass
    found: list[str] = []
    for root, dirs, names in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in WALK_SKIP]
        for name in names:
            found.append((Path(root) / name).relative_to(cwd).as_posix())
    return sorted(found)


def find_files(cwd: Path, patterns: list[str]) -> list[str]:
    """Files matching root-anchored globs, found without git and without ever
    entering WALK_SKIP directories (node_modules, .git, ...).

    For hooks that run on every tool call: `git ls-files` costs a process, and
    Path.glob("*/*/X") lists every package under node_modules first.
    """
    found: set[str] = set()
    for pattern in patterns:
        pattern = pattern.strip().replace("\\", "/")
        while pattern.startswith("./"):
            pattern = pattern[2:]
        regex = glob_regex(pattern)
        if "**" in pattern:
            for root, dirs, names in os.walk(cwd):
                dirs[:] = [d for d in dirs if d not in WALK_SKIP]
                for name in names:
                    rel = (Path(root) / name).relative_to(cwd).as_posix()
                    if regex.match(rel):
                        found.add(rel)
            continue
        level = [""]
        parts = pattern.split("/")
        for i, part in enumerate(parts):
            part_re = glob_regex(part)
            last = i == len(parts) - 1
            nxt = []
            for prefix in level:
                try:
                    entries = list(os.scandir(cwd / prefix if prefix else cwd))
                except OSError:
                    continue
                for e in entries:
                    if e.name in WALK_SKIP or not part_re.match(e.name):
                        continue
                    rel = f"{prefix}/{e.name}" if prefix else e.name
                    if last and e.is_file():
                        found.add(rel)
                    elif not last and e.is_dir():
                        nxt.append(rel)
            level = nxt
    return sorted(found)


def discover(patterns: list[str], files: list[str]) -> list[str]:
    regexes = [glob_regex(p) for p in patterns]
    return [f for f in files if any(r.match(f) for r in regexes)]


def tokens_of(path: Path) -> int:
    try:
        return path.stat().st_size // 4
    except OSError:
        return 0


def _read(path: Path) -> str:
    try:
        # utf-8-sig: a BOM would otherwise hide a leading `---` frontmatter line.
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _unfenced_lines(text: str):
    """Yield (line, in_fence) so callers can skip fenced code.

    A fence closes only on the same character, at least as long as the opener
    (CommonMark), so ``` ... ~~~ ... ``` stays one block.
    """
    opener = ""
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if not opener:
                opener = marker
            elif marker[0] == opener[0] and len(marker) >= len(opener) and not line.strip()[len(marker):].strip():
                opener = ""
            yield line, True
            continue
        yield line, bool(opener)


# ---------------------------------------------------------------------------
# @ imports
# ---------------------------------------------------------------------------

def imports_of(text: str) -> list[str]:
    """@path references outside code spans and fences, in order."""
    found: list[str] = []
    for line, fenced in _unfenced_lines(text):
        if fenced:
            continue
        for m in IMPORT_RE.finditer(INLINE_CODE_RE.sub("", line)):
            target = m.group(1).rstrip(".,;:)]}!?'\"")
            if target:
                found.append(target)
    return found


def resolve_always_loaded(cwd: Path, roots: list[str]) -> tuple[list[dict], list[dict]]:
    """Breadth-first over @ imports, each file once, at most MAX_IMPORT_HOPS deep.

    Returns (files, missing). A reference counts as an import only when it
    resolves to a file inside the project; a missing one is reported when it
    looks like a path (has a `.` or `/`), so `@Reviewer` in a table is noise
    Claude Code also ignores, not an error.
    """
    root_resolved = cwd.resolve()
    seen: dict[str, dict] = {}
    missing: list[dict] = []
    queue: list[tuple[str, int, str]] = [(r, 0, "") for r in roots]
    while queue:
        rel, hops, via = queue.pop(0)
        if rel in seen:
            continue
        path = cwd / rel
        if not path.is_file():
            if via:
                missing.append({"file": via, "import": rel})
            continue
        seen[rel] = {"file": rel, "tokens": tokens_of(path), "via": via}
        if hops >= MAX_IMPORT_HOPS:
            continue
        for target in imports_of(_read(path)):
            if target.startswith("~"):
                continue
            candidate = (path.parent / target.replace("\\ ", " ")).resolve()
            try:
                child = candidate.relative_to(root_resolved).as_posix()
            except ValueError:
                continue
            if candidate.is_file():
                queue.append((child, hops + 1, rel))
            elif "." in Path(target).name or "/" in target:
                missing.append({"file": rel, "import": target})
    return list(seen.values()), missing


# ---------------------------------------------------------------------------
# Frontmatter, gotchas
# ---------------------------------------------------------------------------

def _split_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = [v.strip().strip("`").strip().strip("'\"").strip() for v in value.split(",")]
    return [v for v in items if v]


def frontmatter_paths(text: str) -> list[str] | None:
    """`paths:` from a leading --- block, as a flow list, a comma list, or `- item` lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    out: list[str] | None = None
    collecting = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if collecting:
            m = re.match(r"^\s*-\s+(.*)$", line)  # YAML allows the list at column 0
            if m:
                out.extend(_split_list(m.group(1)))
                continue
            collecting = False
        if re.match(r"^paths\s*:", line):
            value = line.split(":", 1)[1]
            out = _split_list(value)
            collecting = not value.strip()
    return out


def slug(value: str, limit: int = 80) -> str:
    return SLUG_RE.sub("-", value.strip().lower()).strip("-")[:limit]


def parse_gotchas(text: str, file: str = "") -> list[dict]:
    """One entry per `##` heading outside fences; text before the first is a header."""
    entries: list[dict] = []
    current: dict | None = None
    body: list[str] = []

    def close() -> None:
        if current is None:
            return
        current["text"] = "\n".join(body).strip()
        current["bytes"] = len(current["text"].encode("utf-8"))
        entries.append(current)

    for line, fenced in _unfenced_lines(text):
        m = HEADING_RE.match(line) if not fenced else None
        if m and len(m.group(1)) == 2:
            close()
            current = {"id": slug(m.group(2)), "file": file, "fields": {}, "paths": [], "commands": []}
            body = [line]
            continue
        if current is None:
            continue
        body.append(line)
        if fenced:
            continue
        f = FIELD_RE.match(line)
        if not f:
            continue
        name = f.group(1).strip().lower()
        value = f.group(2).strip()
        key = "fix" if name.startswith("fix") else name
        current["fields"][key] = value
        if key == "paths":
            current["paths"] = _split_list(value)
        elif key == "commands":
            current["commands"] = _split_list(value)
    close()
    for e in entries:
        e["missing"] = [k for k in GOTCHA_REQUIRED if not e["fields"].get(k)]
    return entries


def load_gotchas(cwd: Path, config: dict, files: list[str] | None = None) -> list[dict]:
    files = list_files(cwd) if files is None else files
    out: list[dict] = []
    for rel in discover(config["gotchas"], files):
        out.extend(parse_gotchas(_read(cwd / rel), rel))
    return out


def gotcha_matches(entry: dict, rel_path: str | None = None, command: str | None = None) -> bool:
    if rel_path and any(path_matches(p, rel_path) for p in entry.get("paths", [])):
        return True
    if command:
        return any(c and c in command for c in entry.get("commands", []))
    return False


# ---------------------------------------------------------------------------
# Structure signals
# ---------------------------------------------------------------------------

def dated_headings(text: str) -> list[str]:
    out = []
    for line, fenced in _unfenced_lines(text):
        if fenced:
            continue
        m = HEADING_RE.match(line)
        if m and DATED_RE.search(m.group(2)):
            out.append(m.group(2)[:120])
    return out


def paragraphs(text: str) -> list[str]:
    out, cur = [], []
    for line, fenced in _unfenced_lines(text):
        if not line.strip():
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        cur.append(line.strip())
    if cur:
        out.append(" ".join(cur))
    return [re.sub(r"\s+", " ", p) for p in out]


def table_padding(text: str) -> int:
    return sum(
        len(m.group(0))
        for line in text.splitlines() if line.lstrip().startswith("|")
        for m in PADDING_RE.finditer(line)
    )


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def measure(cwd: Path, config: dict, source: str = "") -> dict:
    files = list_files(cwd)
    budgets = config["budgets"]

    always, missing = resolve_always_loaded(cwd, config["always_loaded"])
    always_set = {f["file"] for f in always}
    always_total = sum(f["tokens"] for f in always)

    def tier(patterns: list[str], budget: int, name: str) -> list[dict]:
        rows = []
        for rel in discover(patterns, files):
            if rel in always_set:
                continue
            t = tokens_of(cwd / rel)
            rows.append({"file": rel, "tier": name, "tokens": t, "budget": budget, "over": t > budget})
        return rows

    routers = tier(config["routers"], budgets["router"], "router")
    docs = tier(config["docs"], budgets["doc"], "doc")
    gotcha_files = tier(config["gotchas"], budgets["gotchas"], "gotchas")

    over: list[dict] = []
    if always_total > budgets["always_loaded"]:
        over.append({"file": "(always-loaded total)", "tier": "always_loaded",
                     "tokens": always_total, "budget": budgets["always_loaded"]})
    over += [r for r in routers + docs + gotcha_files if r["over"]]

    gotchas = []
    for rel in discover(config["gotchas"], files):
        gotchas.extend(parse_gotchas(_read(cwd / rel), rel))
    # A duplicate id is invalid too: the hook marks entries shown per id, so
    # the second of two `## a-b` / `## A B` entries would never surface.
    seen_ids: set[str] = set()
    for g in gotchas:
        if g["id"] in seen_ids:
            g["missing"] = g["missing"] + ["unique id"]
        seen_ids.add(g["id"])
    invalid = [{"id": g["id"], "file": g["file"], "missing": g["missing"]} for g in gotchas if g["missing"]]
    for g in gotchas:
        if g["bytes"] > GOTCHA_ENTRY_MAX_BYTES:
            over.append({"file": f"{g['file']}#{g['id']}", "tier": "gotcha_entry",
                         "tokens": g["bytes"] // 4, "budget": GOTCHA_ENTRY_MAX_BYTES // 4})
    stale = [
        g["id"] for g in gotchas
        if g["paths"] and not any(path_matches(p, f) for p in g["paths"] for f in files)
    ]

    undocumented = []
    for d in docs:
        if not frontmatter_paths(_read(cwd / d["file"])):
            undocumented.append(d["file"])

    scanned = sorted(always_set | {r["file"] for r in routers + docs + gotcha_files})
    dated = []
    padding = []
    for rel in scanned:
        text = _read(cwd / rel)
        heads = dated_headings(text)
        if heads:
            dated.append({"file": rel, "count": len(heads), "examples": heads[:3]})
        pad = table_padding(text)
        if pad >= PADDING_REPORT_BYTES:
            padding.append({"file": rel, "bytes": pad})

    seen_para: dict[str, set[str]] = {}
    for rel in sorted(always_set):
        for p in paragraphs(_read(cwd / rel)):
            if len(p) >= DUPLICATE_MIN_CHARS:
                seen_para.setdefault(p, set()).add(rel)
    duplicates = [
        {"chars": len(p), "files": sorted(fs), "preview": p[:80]}
        for p, fs in seen_para.items() if len(fs) >= 2
    ]
    duplicates.sort(key=lambda d: -d["chars"])

    reasons = []
    if always_total > budgets["always_loaded"] * config["structural_factor"]:
        reasons.append("always-loaded over budget x structural_factor")
    for r in routers + docs:
        if r["tokens"] > 2 * r["budget"]:
            reasons.append(f"{r['file']} over twice its budget")
    for d in dated:
        if d["count"] >= STRUCTURAL_DATED_HEADINGS:
            reasons.append(f"{d['file']} has {d['count']} dated headings")

    return {
        "config": source,
        "tiers": {
            "always_loaded": {"files": always, "total": always_total, "budget": budgets["always_loaded"],
                              "over": always_total > budgets["always_loaded"], "missing_imports": missing},
            "router": {"files": routers, "budget": budgets["router"]},
            "doc": {"files": docs, "budget": budgets["doc"], "without_paths": undocumented},
            "gotchas": {"files": gotcha_files, "budget": budgets["gotchas"]},
        },
        "over": over,
        "dated_headings": dated,
        "duplicate_paragraphs": duplicates[:20],
        "table_padding": padding,
        "gotchas": [{"id": g["id"], "file": g["file"], "paths": g["paths"], "commands": g["commands"],
                     "bytes": g["bytes"]} for g in gotchas],
        "invalid_gotchas": invalid,
        "stale_gotchas": stale,
        "structural": bool(reasons),
        "structural_reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

def changed_files(cwd: Path, base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(cwd), "diff", "--name-only", f"{base}...{head}"],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git diff exited {out.returncode}")
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def guard(cwd: Path, config: dict, changed: list[str]) -> dict:
    files = list_files(cwd)
    always, _ = resolve_always_loaded(cwd, config["always_loaded"])
    doc_files = discover(config["docs"], files)
    gotcha_files = discover(config["gotchas"], files)
    instruction = (
        {f["file"] for f in always} | set(doc_files) | set(gotcha_files)
        | set(discover(config["routers"], files))
    )
    # Only feature docs cover code. A gotcha describes a trap, not the current
    # state of an area, so most code changes leave it true; counting it would
    # force meaningless GOTCHAS.md edits, and one such edit would then satisfy
    # every gotcha-covered path at once. Stale gotchas are caught by
    # `stale_gotchas` instead.
    covers = [(rel, frontmatter_paths(_read(cwd / rel)) or []) for rel in doc_files]

    changed_set = set(changed)
    failures, uncovered, ok = [], [], []
    for rel in changed:
        if rel in instruction or any(path_matches(p, rel) for p in config["guard"]["ignore"]):
            continue
        covering = sorted({doc for doc, pats in covers if any(path_matches(p, rel) for p in pats)})
        if not covering:
            uncovered.append(rel)
        elif changed_set.isdisjoint(covering):
            failures.append({"path": rel, "docs": covering})
        else:
            ok.append(rel)
    return {"failures": failures, "uncovered": uncovered, "covered_ok": ok}


def _skip_requested(config: dict) -> bool:
    marker = config["guard"]["skip_marker"]
    if os.environ.get("COOGRAPH_LAYOUT_SKIP", "").strip().lower() not in ("", "0", "false", "no"):
        return True
    return marker in os.environ.get("COOGRAPH_PR_TITLE", "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_budget(m: dict) -> None:
    t = m["tiers"]
    a = t["always_loaded"]
    print(f"layout: config from {m['config']}")
    print(f"always-loaded  {a['total']} / {a['budget']} tokens  "
          f"({', '.join(f['file'] for f in a['files']) or 'no files'})")
    for name in ("router", "doc", "gotchas"):
        rows = t[name]["files"]
        biggest = max((r["tokens"] for r in rows), default=0)
        print(f"{name:<14} {len(rows)} files, largest {biggest} / {t[name]['budget']} tokens")
    for o in m["over"]:
        print(f"OVER  {o['tier']}  {o['file']}  {o['tokens']} > {o['budget']}")
    for g in m["invalid_gotchas"]:
        print(f"INVALID gotcha {g['file']}#{g['id']}: missing {', '.join(g['missing'])}")
    for miss in a["missing_imports"]:
        print(f"MISSING import @{miss['import']} in {miss['file']}")
    if m["structural"]:
        print("STRUCTURAL: " + "; ".join(m["structural_reasons"]) + ". Run /coograph-docs-restructure.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coograph instruction layout")
    parser.add_argument("--cwd", metavar="PROJECT", help="project root (default: current dir)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--budget", action="store_true")
    group.add_argument("--json", action="store_true")
    group.add_argument("--guard", nargs=2, metavar=("BASE", "HEAD"))
    group.add_argument("--merge-seed", metavar="SEED", nargs="?", const=str(DEFAULT_SEED))
    args = parser.parse_args(argv)
    cwd = Path(args.cwd or os.getcwd()).resolve()

    if args.merge_seed is not None:
        seed = Path(args.merge_seed)
        if not seed.is_file():
            print(f"layout: seed not found: {seed}", file=sys.stderr)
            return 2
        try:
            added = merge_seed(cwd / CONFIG_REL, seed)
        except ValueError as e:
            print(f"layout: {e}", file=sys.stderr)
            return 2
        print(f"layout: {CONFIG_REL.as_posix()} ({'added ' + ', '.join(added) if added else 'up to date'})")
        return 0

    try:
        config, source = load_config(cwd)
    except ValueError as e:
        print(f"layout: {e}", file=sys.stderr)
        return 2

    if args.guard:
        print(f"layout guard: config from {source}")
        if _skip_requested(config):
            print("layout guard: skipped")
            return 0
        try:
            changed = changed_files(cwd, *args.guard)
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            print(f"layout guard: {e}", file=sys.stderr)
            return 2
        result = guard(cwd, config, changed)
        for f in result["failures"]:
            print(f"FAIL  {f['path']} -> {', '.join(f['docs'])}")
        for u in result["uncovered"]:
            print(f"uncovered  {u}")
        if result["failures"]:
            print(f"layout guard: {len(result['failures'])} covered path(s) changed without their doc. "
                  f"Update the doc, or put {config['guard']['skip_marker']} in the PR title.")
            return 1
        print(f"layout guard: ok ({len(result['covered_ok'])} covered, {len(result['uncovered'])} uncovered)")
        return 0

    m = measure(cwd, config, source)
    if args.json:
        print(json.dumps(m, indent=2))
        return 0
    _print_budget(m)
    # Invalid gotchas and missing imports fail too: the hook never shows an
    # invalid entry, and Claude Code skips a missing import without a word, so
    # both are rules that silently stopped applying.
    failed = m["over"] or m["invalid_gotchas"] or m["tiers"]["always_loaded"]["missing_imports"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
