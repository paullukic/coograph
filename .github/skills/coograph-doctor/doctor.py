#!/usr/bin/env python3
"""coograph-doctor: read-only health check of a Coograph install.

Prints one PASS / WARN / FAIL / SKIP line per check, a `fix:` line under every
WARN and FAIL, and a summary. Never writes to the project. stdlib only
(PyYAML is used for openspec/config.yaml when it happens to be installed).

    python3 .github/skills/coograph-doctor/doctor.py                  # this folder
    python3 .github/skills/coograph-doctor/doctor.py --project PATH
    python3 .github/skills/coograph-doctor/doctor.py --registry <coograph>/projects.json
    python3 .github/skills/coograph-doctor/doctor.py --json

Run from a coograph checkout, `projects.json` next to it is the registry.
Exit 0 with no FAIL, 1 with any FAIL, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import yaml  # optional: a stricter openspec/config.yaml parse
except ImportError:  # pragma: no cover - depends on the machine
    yaml = None

NO_CALLS_FUNCTIONS = 50      # this many functions and 0 calls: no tree-sitter
GIT_TIMEOUT = 10
# Folders the graph builder never walks (.github/code-graph/builder.py
# _IGNORE_DIRS, plus every dot-folder). A commit there leaves the graph as is.
BUILDER_SKIPS_DIRS = frozenset({
    "node_modules", "venv", "env", "__pycache__", "target", "dist", "build",
    "coverage", "out", "vendor", "tmp", "log", "Pods", "DerivedData",
})
# builder.py _is_minified: scripts it leaves out of the graph
MINIFIABLE_EXTS = frozenset({".js", ".mjs", ".cjs"})
MINIFIED_AVG_LINE = 300
MINIFIED_SAMPLE = 64 * 1024

# Tool ids as `projects.json` records them (coograph-init Step 8).
TOOL_ALIASES = {"windsurf": "devin"}
TOOL_FILES = {
    # AGENTS.md only when CLAUDE.md imports it (`@AGENTS.md`), see _tool_files:
    # an older self-contained CLAUDE.md holds the hard rules itself.
    "claude": ["CLAUDE.md", ".claude/settings.json", ".claude/hooks/",
               ".claude/commands/coograph-init.md"],
    "vscode": [".github/agents/", "AGENTS.md"],
    "codex": [".agents/skills/coograph-init/SKILL.md", "AGENTS.md"],
    "opencode": [".opencode/commands/coograph-init.md", "AGENTS.md"],
    "cursor": [".cursor/rules/coograph.mdc"],
    "devin": [".windsurfrules"],
    "aider": ["CONVENTIONS.md"],
    "cline": [".clinerules"],
}
CORE_FILES = [".github/copilot-instructions.md", ".github/skills/"]
# Where each tool's code-graph MCP entry lives: (file, key holding the servers)
MCP_CONFIGS = {
    "claude": (".mcp.json", "mcpServers"),
    "vscode": (".vscode/mcp.json", "servers"),
    "cursor": (".cursor/mcp.json", "mcpServers"),
    "opencode": ("opencode.json", "mcp"),
}
MARKER_FILES = [".github/copilot-instructions.md", "CLAUDE.md", "AGENTS.md"]
# A marker in backticks is the template guard talking about markers, not one.
MARKER_RE = re.compile(r"(?<!`)(_TBD_|<!-- FILL)")
GIT_HOOKS = ("post-commit", "post-merge", "post-rewrite")
CLAUDE_HOOK_RE = re.compile(
    r"\$\{?CLAUDE_PROJECT_DIR\}?[/\\]+\.claude[/\\]+hooks[/\\]+([\w.-]+)")
# Tools that expand `${workspaceFolder}` in their MCP config; others pass it on literally.
EXPANDS_WORKSPACE = frozenset({"vscode", "cursor"})
# Configs these tools read as JSONC: comments and trailing commas are fine.
JSONC_TOOLS = frozenset({"vscode", "cursor", "opencode"})
# Variables each tool expands in its MCP config, other than the workspace folder.
ENV_VAR_RE = {
    "claude": re.compile(r"\$\{(\w+)(?::-([^}]*))?\}"),   # ${VAR}, ${VAR:-default}
    "vscode": re.compile(r"\$\{env:(\w+)\}"),
    "cursor": re.compile(r"\$\{env:(\w+)\}"),
    "opencode": re.compile(r"\{env:(\w+)\}"),
}
WORKSPACE_VARS = ("${workspaceFolder}", "${workspaceRoot}")
_CMD = "uv run -p \">=3.10\" --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py"
BUILD_CMD = _CMD + " --build"
UPDATE_CMD = _CMD + " --update"
REBUILD = "run /coograph-rebuild-graph, or: " + BUILD_CMD
REINIT = ("re-run /coograph-init for this project: it adds what is missing, and also offers to "
          "refresh template-managed files that differ from the template (skills, agents, "
          ".claude/hooks/, .claude/settings.json), so name the ones to keep")


@dataclass
class Result:
    status: str
    check: str
    detail: str
    fix: str = ""


def _which(name: str) -> str | None:
    return shutil.which(name)


def _git(project: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(project), *args], capture_output=True,
                             text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


def _own_registry() -> Path | None:
    """`projects.json` of the coograph checkout this script sits in, if any."""
    root = Path(__file__).resolve().parents[3]
    reg = root / "projects.json"
    if (root / "templates").is_dir() and (root / "setup.sh").is_file() and reg.is_file():
        return reg
    return None


def _exists(project: Path, rel: str) -> bool:
    p = project / rel.rstrip("/")
    return p.is_dir() if rel.endswith("/") else p.is_file()


def _ago(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


# ---------------------------------------------------------------------------
# Context: what this install is supposed to have
# ---------------------------------------------------------------------------


COOGRAPH_AGENTS = ("debugger", "explore", "planner", "retro", "reviewer", "verifier")


def _mentions(path: Path, *words: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return any(w in text for w in words)


def _detect_tools(project: Path) -> set[str]:
    """Tools whose coograph files are on disk. Only coograph's own files count:
    `.agents/skills/` or `.github/agents/` may hold another tool's or the
    user's own files (Firebase skills, hand-written agents)."""
    found = set()
    if any((project / ".claude" / "commands").glob("coograph-*.md")) \
            or (project / ".claude" / "hooks" / "_coograph_guard.py").is_file():
        found.add("claude")
    if any((project / ".github" / "agents" / f"{a}.agent.md").is_file() for a in COOGRAPH_AGENTS):
        found.add("vscode")
    if any(p.is_dir() for p in (project / ".agents" / "skills").glob("coograph-*")):
        found.add("codex")
    if any((project / ".opencode" / "commands").glob("coograph-*.md")) \
            or _mentions(project / "opencode.json", ".github/skills", "code-graph"):
        found.add("opencode")
    if (project / ".cursor" / "rules" / "coograph.mdc").is_file():
        found.add("cursor")
    if _mentions(project / ".windsurfrules", "coograph"):
        found.add("devin")
    if _mentions(project / "CONVENTIONS.md", "coograph"):
        found.add("aider")
    if _mentions(project / ".clinerules", "coograph"):
        found.add("cline")
    return found


@dataclass
class Context:
    project: Path
    registry: Path | None
    entry: dict | None
    tools: set[str]
    unknown_tools: list[str]
    detected: set[str]
    code_graph: bool
    template: bool


def _context(project: Path, registry: Path | None) -> Context:
    entry = None
    if registry is not None:
        data = json.loads(registry.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("projects", []), list):
            raise ValueError('expected {"projects": [...]}')
        for e in data.get("projects", []):
            if isinstance(e, dict) and _norm(e.get("path", "")) == _norm(project):
                entry = e
                break
    detected = _detect_tools(project)
    unknown: list[str] = []
    if entry is not None:
        tools = set()
        for t in entry.get("tools", []):
            t = TOOL_ALIASES.get(str(t).lower(), str(t).lower())
            (tools.add(t) if t in TOOL_FILES else unknown.append(str(t)))
    else:
        tools = set(detected)
    # Off only when nothing says on: no .github/code-graph/ and no registry `true`.
    code_graph = (project / ".github" / "code-graph").is_dir() or (
        entry is not None and entry.get("code_graph") is True)
    template = (project / "templates").is_dir() and (project / "setup.sh").is_file()
    return Context(project, registry, entry, tools, unknown, detected, code_graph, template)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_graph(ctx: Context) -> Result:
    if not ctx.code_graph:
        return Result("SKIP", "graph", "code-graph not enabled")
    db = ctx.project / ".code-graph" / "graph.db"
    if not db.is_file():
        return Result("FAIL", "graph", ".code-graph/graph.db is missing", REBUILD)
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            one = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
            nodes = one("SELECT COUNT(*) FROM nodes")
            edges = one("SELECT COUNT(*) FROM edges")
            files = one("SELECT COUNT(*) FROM nodes WHERE kind='file'")
            fns = one("SELECT COUNT(*) FROM nodes WHERE kind IN ('function','method')")
            calls = one("SELECT COUNT(*) FROM edges WHERE kind='calls'")
        finally:
            conn.close()
    except sqlite3.Error as e:
        return Result("FAIL", "graph", f".code-graph/graph.db is unreadable ({e})", REBUILD)
    age = _ago(max(0.0, time.time() - db.stat().st_mtime))
    summary = f"{nodes} nodes, {edges} edges, {files} files, {calls} calls; built {age} ago"
    if nodes == 0 or edges == 0:
        return Result("FAIL", "graph", f"graph is empty: {summary}", REBUILD)
    if fns > NO_CALLS_FUNCTIONS and calls == 0:
        return Result("WARN", "graph",
                      f"{fns} functions but 0 call edges: built without tree-sitter? ({summary})",
                      "rebuild through uv with the requirements file, so the tree-sitter "
                      "parsers are installed: " + BUILD_CMD)
    return Result("PASS", "graph", summary)


def _repos(project: Path) -> list[tuple[Path, str]]:
    """(repo dir, path prefix) for the project, or for its child repos when it
    is a multi-repo workspace that is no repo itself."""
    if _git(project, "rev-parse", "--is-inside-work-tree") == "true":
        return [(project, "")]
    try:
        return [(d, d.name + "/") for d in sorted(project.iterdir())
                if d.is_dir() and (d / ".git").exists()]
    except OSError:
        return []


def _stored_hashes(db: Path) -> dict[str, str] | None:
    """{file: sha1} the builder recorded (file_hashes), None when unreadable."""
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return {f.replace("\\", "/"): h for (f, h) in
                    conn.execute("SELECT file, sha1 FROM file_hashes")}
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _sha1(path: Path) -> str | None:
    """The hash builder.py _sha1_file stores, or None for an unreadable file."""
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _builder_walks(rel: str) -> bool:
    """False for a path under a folder the builder skips (dot-folders,
    build output, vendored code), so a commit there cannot stale the graph."""
    parts = rel.split("/")[:-1]
    if any(d.startswith(".") or d in BUILDER_SKIPS_DIRS for d in parts):
        return False
    return "bootstrap/cache/" not in rel


def _minified(path: Path) -> bool:
    """builder.py _is_minified: a script the builder leaves out of the graph."""
    if path.suffix.lower() not in MINIFIABLE_EXTS:
        return False
    if ".min." in path.name.lower():
        return True
    try:
        with path.open("rb") as fh:
            head = fh.read(MINIFIED_SAMPLE)
    except OSError:
        return False
    return len(head) >= 2048 and len(head) / (head.count(b"\n") + 1) > MINIFIED_AVG_LINE


def _git_paths(repo: Path, *args: str) -> set[str]:
    out = _git(repo, "-c", "core.quotepath=off", *args, "-z")
    return {f for f in (out or "").split("\0") if f}


def check_graph_age(ctx: Context) -> Result:
    """A graph is stale when the committed content of a file differs from what
    the graph holds. Compared by content, not dates: a pull brings commits with
    old dates, and `--update` leaves the db untouched when nothing changed.
    Uncommitted edits are left out: no git hook could have seen them yet."""
    db = ctx.project / ".code-graph" / "graph.db"
    if not ctx.code_graph:
        return Result("SKIP", "graph-age", "code-graph not enabled")
    if not db.is_file():
        return Result("SKIP", "graph-age", "no graph to date")
    repos = _repos(ctx.project)
    if not repos:
        return Result("SKIP", "graph-age", "not a git repo")
    stored = _stored_hashes(db)
    if not stored:
        return Result("WARN", "graph-age", "the graph holds no file hashes to compare with",
                      "rebuild it, so the builder records them: " + REBUILD)
    exts = {Path(f).suffix.lower() for f in stored if Path(f).suffix}
    stale: set[str] = set()
    for repo, prefix in repos:
        tracked = _git_paths(repo, "ls-files")
        uncommitted = _git_paths(repo, "diff", "--name-only", "HEAD") | _git_paths(
            repo, "ls-files", "--others", "--exclude-standard")
        for rel in tracked - uncommitted:
            full = prefix + rel
            path = repo / rel
            if full in stored:
                if _sha1(path) != stored[full]:
                    stale.add(full)
            elif (Path(rel).suffix.lower() in exts and _builder_walks(full)
                  and path.is_file() and not _minified(path)):
                stale.add(full)  # a new file of a kind the graph indexes
        for full in stored:
            if full.startswith(prefix) and full[len(prefix):] not in uncommitted \
                    and not (ctx.project / full).is_file():
                stale.add(full)  # deleted, still in the graph
    if stale:
        return Result("WARN", "graph-age",
                      f"{len(stale)} indexed file(s) differ from the graph, e.g. {sorted(stale)[0]}",
                      "run /coograph-rebuild-graph update, or: " + UPDATE_CMD + "; and install "
                      "the git hooks (see hooks:git) so it follows every commit")
    return Result("PASS", "graph-age", "every committed indexed file matches the graph")


def _strip_jsonc(text: str) -> str:
    """JSONC to JSON: drop // and /* */ comments outside strings, and
    trailing commas before } or ]."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            if c in "}]":
                while out and out[-1].isspace():
                    out.pop()
                if out and out[-1] == ",":
                    out.pop()
            out.append(c)
            i += 1
    return "".join(out)


def _mcp_entry(ctx: Context, tool: str):
    rel, key = MCP_CONFIGS[tool]
    path = ctx.project / rel
    if not path.is_file():
        return rel, None, f"{rel} is missing"
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(_strip_jsonc(text) if tool in JSONC_TOOLS else text)
    except (OSError, ValueError) as e:
        return rel, None, f"{rel} is not valid JSON ({e})"
    entry = (data.get(key) or {}).get("code-graph") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return rel, None, f"{rel} has no code-graph entry under \"{key}\""
    return rel, (data, entry), ""


def _looks_like_path(arg: str) -> bool:
    return (not arg.startswith("-") and not arg.startswith(">") and not arg.startswith("<")
            and (arg.endswith((".py", ".txt")) or "/" in arg or "\\" in arg))


def _mcp_command(entry: dict, tool: str) -> tuple[str, list[str]]:
    if tool == "opencode":
        cmd = entry.get("command")
        if isinstance(cmd, list) and cmd:
            return str(cmd[0]), [str(a) for a in cmd[1:]] + [str(a) for a in entry.get("args", [])]
        return str(cmd or ""), [str(a) for a in entry.get("args", [])]
    return str(entry.get("command", "")), [str(a) for a in entry.get("args", [])]


def _bare_uv(command: str) -> bool:
    """`uv` by name, found through PATH. A path to uv is checked as a path."""
    return command.lower() in ("uv", "uv.exe")


def _expand(raw: str, tool: str, project: Path) -> tuple[str, list[str], list[str]]:
    """(raw with the tool's variables expanded, variables the tool passes on
    literally, variables not set where the doctor runs)."""
    literal: list[str] = []
    unknown: list[str] = []
    out = raw
    for var in WORKSPACE_VARS:
        if var in out:
            if tool in EXPANDS_WORKSPACE:
                out = out.replace(var, str(project))
            else:
                literal.append(var)
    if tool in EXPANDS_WORKSPACE:
        out = out.replace("${userHome}", str(Path.home()))

    def env(m: re.Match) -> str:
        if m.group(0) in WORKSPACE_VARS:
            return m.group(0)
        value = os.environ.get(m.group(1))
        if value is None and m.lastindex and m.lastindex > 1 and m.group(2) is not None:
            value = m.group(2)
        if value is None:
            unknown.append(m.group(0))
            return m.group(0)
        return value
    out = ENV_VAR_RE[tool].sub(env, out)
    return out, literal, unknown


def check_mcp(ctx: Context) -> tuple[list[Result], list[str]]:
    """One result per installed tool that has an MCP config, plus the
    commands those configs run (for the server check)."""
    results, commands = [], []
    for tool in sorted(t for t in ctx.tools if t in MCP_CONFIGS):
        check = f"mcp:{tool}"
        if not ctx.code_graph:
            results.append(Result("SKIP", check, "code-graph not enabled"))
            continue
        rel, found, problem = _mcp_entry(ctx, tool)
        fix = (f"re-run /coograph-init (Step 6e writes the code-graph entry into {rel} "
               "and keeps every other key)")
        if "is not valid JSON" in problem:
            fix = (f"fix the syntax of {rel} by hand: init merges into it and cannot "
                   "read it either")
        if ctx.template and not (ctx.project / rel).is_file():
            # .opencode/ and .github/agents/ are template sources here, not installs
            results.append(Result("SKIP", check, f"template checkout, no {rel}"))
            continue
        if found is None:
            results.append(Result("FAIL", check, problem, fix))
            continue
        data, entry = found
        command, args = _mcp_command(entry, tool)
        commands.append(command)
        base = ctx.project / str(entry.get("cwd") or ".")
        missing, unverified = [], []
        for raw in ([command] if ("/" in command or "\\" in command) else []) + args:
            if not _looks_like_path(raw):
                continue
            expanded, literal, unknown = _expand(raw, tool, ctx.project)
            if literal:
                missing.append(raw + " (not expanded by this tool)")
                continue
            if unknown:
                unverified.append(raw)
                continue
            p = Path(expanded)
            if not (p if p.is_absolute() else base / p).exists():
                missing.append(raw)
        if missing:
            results.append(Result("FAIL", check,
                                  f"{rel}: code-graph points at missing {', '.join(missing)}", fix))
            continue
        if unverified:
            results.append(Result("WARN", check,
                                  f"{rel}: cannot verify {', '.join(unverified)}: the variable is "
                                  "not set where the doctor runs",
                                  "check that the variable is set in the environment the tool "
                                  "starts from, or write the path out"))
            continue
        if tool == "opencode":
            paths = (data.get("skills") or {}).get("paths") or []
            if ".github/skills" not in [str(p).rstrip("/") for p in paths]:
                results.append(Result("FAIL", check,
                                      "opencode.json: skills.paths lacks .github/skills, so "
                                      "OpenCode sees none of the coograph skills", fix))
                continue
        results.append(Result("PASS", check, f"{rel}: code-graph via {Path(command).name or '?'}"))
    return results, commands


def check_server(ctx: Context, commands: list[str]) -> Result:
    if not ctx.code_graph:
        return Result("SKIP", "server", "code-graph not enabled")
    cg = ctx.project / ".github" / "code-graph"
    missing = [n for n in ("server.py", "requirements.txt") if not (cg / n).is_file()]
    if missing:
        return Result("FAIL", "server", ".github/code-graph/ lacks " + ", ".join(missing),
                      "re-run /coograph-init (Step 6a copies .github/code-graph/), or wait "
                      "for the next coograph sync")
    uv = _which("uv")
    if uv:
        return Result("PASS", "server", f".github/code-graph/server.py present; uv at {uv}")
    if any(_bare_uv(c) for c in commands):
        return Result("FAIL", "server", "the MCP config runs uv by name, but uv is not on PATH",
                      "install uv (https://docs.astral.sh/uv/) or point the MCP config at "
                      "a Python with the requirements installed")
    detail = ("uv is not on PATH; the MCP configs launch the server by path or another "
              "launcher" if commands else "uv is not on PATH")
    return Result("WARN", "server", detail,
                  "install uv (https://docs.astral.sh/uv/) so the graph builds with the "
                  "pinned requirements")


def check_markers(ctx: Context) -> Result:
    if ctx.template:
        return Result("SKIP", "markers", "template checkout: placeholders are meant to be there")
    hits = []
    for rel in MARKER_FILES:
        p = ctx.project / rel
        if not p.is_file():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if MARKER_RE.search(line):
                hits.append(f"{rel}:{n}")
    if hits:
        more = f" (+{len(hits) - 10} more)" if len(hits) > 10 else ""
        return Result("FAIL", "markers", "unfilled placeholders at " + ", ".join(hits[:10]) + more,
                      "fill them in, or re-run /coograph-init, which fills untouched files")
    return Result("PASS", "markers", "no _TBD_ or <!-- FILL markers left")


def _tool_files(project: Path, tool: str) -> list[str]:
    files = list(TOOL_FILES[tool])
    if tool == "claude":
        claude_md = project / "CLAUDE.md"
        text = claude_md.read_text(encoding="utf-8", errors="ignore") if claude_md.is_file() else ""
        if "@AGENTS.md" in text:
            files.insert(1, "AGENTS.md")  # without it every imported hard rule is gone
    return files


def check_tools(ctx: Context) -> Result:
    problems, warnings = [], []
    for rel in CORE_FILES:
        if not _exists(ctx.project, rel):
            problems.append(f"core: {rel}")
    for tool in sorted(ctx.tools):
        for rel in _tool_files(ctx.project, tool):
            if not _exists(ctx.project, rel):
                problems.append(f"{tool}: {rel}")
    if ctx.unknown_tools:
        warnings.append("unknown tool id(s) in projects.json: " + ", ".join(ctx.unknown_tools))
    if ctx.entry is not None:
        extra = sorted(ctx.detected - ctx.tools)
        if extra:
            warnings.append("on disk but not in projects.json: " + ", ".join(extra))
        source = "registered: " + (", ".join(sorted(ctx.tools)) or "none")
    else:
        why = "not in projects.json" if ctx.registry is not None else "no registry"
        source = f"detected from disk ({why}): " + (", ".join(sorted(ctx.tools)) or "none")
    if problems:
        return Result("FAIL", "tools", f"{source}; missing " + "; ".join(problems), REINIT)
    if warnings:
        return Result("WARN", "tools", f"{source}; " + "; ".join(warnings),
                      "update the project's tools in projects.json (ids: "
                      + ", ".join(TOOL_FILES) + "), or remove the stray files")
    return Result("PASS", "tools", source)


def check_git_hooks(ctx: Context) -> Result:
    if not ctx.code_graph:
        return Result("SKIP", "hooks:git", "code-graph not enabled")
    hooks_rel = _git(ctx.project, "rev-parse", "--git-path", "hooks")
    if hooks_rel is None:
        return Result("SKIP", "hooks:git", "not a git repo")
    hooks = Path(hooks_rel)
    hooks = hooks if hooks.is_absolute() else ctx.project / hooks
    missing, foreign = [], []
    for name in GIT_HOOKS:
        try:
            text = (hooks / name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            missing.append(name)
            continue
        if "server.py" not in text or "--update" not in text:
            foreign.append(name)
    if not (missing or foreign):
        return Result("PASS", "hooks:git", "post-commit, post-merge, post-rewrite update the graph")
    detail, fix = [], []
    if missing:
        detail.append(", ".join(missing) + " missing")
        fix.append(f"copy the missing ones: for h in {' '.join(missing)}; do cp "
                   ".github/code-graph/$h \"$(git rev-parse --git-path hooks)/$h\"; "
                   "chmod +x \"$(git rev-parse --git-path hooks)/$h\"; done")
    if foreign:
        one = len(foreign) == 1
        detail.append(f"{', '.join(foreign)} {'belongs' if one else 'belong'} to something else "
                      f"and {'does' if one else 'do'} not update the graph")
        fix.append(f"do not replace {', '.join(foreign)}: add the line "
                   "sh \"$(git rev-parse --show-toplevel)/.github/code-graph/<hook>\" || true "
                   "once to each, at the end, or just before the last line when that line "
                   "starts with exec")
    return Result("WARN", "hooks:git", "; ".join(detail), "; ".join(fix))


def _yaml_structure_error(text: str) -> str | None:
    """A stdlib stand-in for a YAML parse: tabs, and lines that are neither
    `key: value`, a list item, nor inside a block scalar."""
    block_parent: int | None = None
    key_re = re.compile(r"""^(-(\s.*)?|[^\s:#'"][^:]*:(\s.*)?|["'][^"']+["']:(\s.*)?)$""")
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        lead = line[:len(line) - len(line.lstrip())]
        if "\t" in lead:
            return f"line {n}: tab in indentation"
        indent = len(lead)
        if block_parent is not None:
            if indent > block_parent:
                continue
            block_parent = None
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not key_re.match(stripped):
            return f"line {n}: not a key, list item or block scalar: {stripped[:40]}"
        if re.search(r":\s*[|>][-+]?\d*\s*(#.*)?$", stripped):
            block_parent = indent
    return None


def check_openspec(ctx: Context) -> Result:
    p = ctx.project / "openspec" / "config.yaml"
    fix = "restore openspec/config.yaml from the template (coograph-init Step 3) and re-add your context"
    if not p.is_file():
        return Result("FAIL", "openspec", "openspec/config.yaml is missing", fix)
    text = p.read_text(encoding="utf-8", errors="ignore")
    if not any(line.strip() and not line.lstrip().startswith("#") for line in text.splitlines()):
        return Result("FAIL", "openspec", "openspec/config.yaml is empty", fix)
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            return Result("FAIL", "openspec", f"openspec/config.yaml does not parse: {e}", fix)
        if not isinstance(data, dict):
            return Result("FAIL", "openspec", "openspec/config.yaml is not a mapping", fix)
        return Result("PASS", "openspec", "openspec/config.yaml parses")
    error = _yaml_structure_error(text)
    if error:
        return Result("FAIL", "openspec", f"openspec/config.yaml: {error}", fix)
    return Result("PASS", "openspec",
                  "openspec/config.yaml parses (structural check; PyYAML not installed)")


def check_claude_hooks(ctx: Context) -> Result:
    if "claude" not in ctx.tools:
        return Result("SKIP", "hooks:claude", "Claude Code not installed")
    p = ctx.project / ".claude" / "settings.json"
    if not p.is_file():
        return Result("FAIL", "hooks:claude", ".claude/settings.json is missing", REINIT)
    text = p.read_text(encoding="utf-8-sig", errors="ignore")
    try:
        json.loads(text)
    except ValueError as e:
        return Result("FAIL", "hooks:claude", f".claude/settings.json is not valid JSON ({e})",
                      "fix the JSON; Claude Code ignores every hook in an invalid file")
    wired = sorted(set(CLAUDE_HOOK_RE.findall(text)))
    missing = [h for h in wired if not (ctx.project / ".claude" / "hooks" / h).is_file()]
    if missing:
        return Result("FAIL", "hooks:claude",
                      ".claude/settings.json wires missing hook(s): " + ", ".join(missing),
                      "re-run /coograph-init or wait for the next coograph sync, which "
                      "copies .claude/hooks/")
    return Result("PASS", "hooks:claude", f"{len(wired)} wired hook(s) present")


def check_sync(ctx: Context) -> Result:
    upstream = ctx.project / ".coograph" / "upstream"
    parked = sorted(p.relative_to(upstream).as_posix() for p in upstream.rglob("*")
                    if p.is_file()) if upstream.is_dir() else []
    if parked:
        more = f" (+{len(parked) - 5} more)" if len(parked) > 5 else ""
        return Result("WARN", "sync",
                      f"{len(parked)} template file(s) kept as local edits, newer upstream "
                      "waiting in .coograph/upstream/: " + ", ".join(parked[:5]) + more,
                      "compare each with your copy; to take upstream, copy it over yours "
                      "and run coograph's sync.py --project again")
    if (ctx.project / ".coograph" / "sync-manifest.json").is_file():
        return Result("PASS", "sync", "no upstream copies waiting")
    return Result("SKIP", "sync", "never synced (plugin or unregistered install)")


def run(project: Path, registry: Path | None = None) -> list[Result]:
    project = Path(project)
    ctx = _context(project, registry if registry is not None else _own_registry())
    mcp, commands = check_mcp(ctx)
    return [
        check_graph(ctx),
        check_graph_age(ctx),
        check_server(ctx, commands),
        *mcp,
        check_markers(ctx),
        check_tools(ctx),
        check_git_hooks(ctx),
        check_openspec(ctx),
        check_claude_hooks(ctx),
        check_sync(ctx),
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only health check of a Coograph install.")
    ap.add_argument("--project", default=".", help="project folder (default: current folder)")
    ap.add_argument("--registry", help="coograph projects.json (default: the one next to "
                                       "this script, in a coograph checkout)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(f"doctor: no such folder: {project}", file=sys.stderr)
        return 2
    registry = None
    if args.registry:
        registry = Path(args.registry)
        if not registry.is_file():
            print(f"doctor: no such registry: {registry}", file=sys.stderr)
            return 2
    try:
        results = run(project, registry)
    except ValueError as e:  # an unparseable projects.json
        print(f"doctor: cannot read the registry: {e}", file=sys.stderr)
        return 2

    summary = {s: sum(1 for r in results if r.status == s) for s in ("PASS", "WARN", "FAIL", "SKIP")}
    if args.json:
        print(json.dumps({"project": str(project.resolve()), "results": [asdict(r) for r in results],
                          "summary": summary}, indent=1))
    else:
        print(f"coograph doctor: {project.resolve()}")
        for r in results:
            print(f"{r.status:<5} {r.check:<13} {r.detail}")
            if r.fix and r.status in ("WARN", "FAIL"):
                print(f"      fix: {r.fix}")
        print(f"Summary: {summary['PASS']} PASS, {summary['WARN']} WARN, "
              f"{summary['FAIL']} FAIL, {summary['SKIP']} SKIP")
    return 1 if summary["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
