#!/usr/bin/env python3
"""Sync coograph updates to all registered projects.

Run from the coograph root (executed automatically by post-merge hook).
Reads projects.json, copies pure-template files to each registered project,
and rebuilds the code-graph + visualizer for projects with code_graph: true.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).parent.parent  # .github/sync.py -> root
PROJECTS_FILE = TEMPLATE_ROOT / "projects.json"
LOG_FILE = Path(__file__).parent / "sync.log"

# Skip these when recursively copying directories. "tests" is here for
# .github/retro/tests/ (unit tests stay in the coograph repo); no other
# synced tree has a directory by that name.
SKIP_DIRS = {"node_modules", "__pycache__", ".code-graph", "tests"}
SKIP_SUFFIXES = {".bak", ".pyc", ".db"}

# Never overwrite these - user has customized them during initialization.
# rules.json is the per-project Retro registry: local edits, thresholds and
# last_retro must survive a sync. New seeded rules reach it from
# rules.seed.json (which IS synced) through `retro.py --merge-seed`, see
# _sync_retro. Applies to every synced tree; only .github/retro/ has one.
SKIP_FILES = {"CLAUDE.md", "copilot-instructions.md", "config.yaml", "rules.json"}

# Paths a previous template version placed in consumer projects but that
# have since been renamed or removed. Each sync run deletes these so the
# rename surfaces cleanly on git pull. Adding entries here is the canonical
# way to propagate a rename / removal — see MIGRATION.md for the matching
# user-facing notes.
OBSOLETE_PATHS = (
    # 2026-05-18 coograph-skill-rename — old skill dirs
    ".github/skills/openspec-propose",
    ".github/skills/openspec-apply",
    ".github/skills/openspec-archive",
    ".github/skills/openspec-explore",
    ".github/skills/new-ticket",
    ".github/skills/rebuild-code-graph",
    # 2026-05-18 coograph-skill-rename — old slash command wrappers
    ".claude/commands/project/new-ticket.md",
    ".claude/commands/project/plan.md",
    ".claude/commands/project/review.md",
    ".claude/commands/project/verify.md",
    ".claude/commands/project/debug.md",
    ".claude/commands/project/explore.md",
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s code-graph.sync %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("code-graph.sync")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_uv() -> Path | None:
    uv = shutil.which("uv")
    if uv:
        return Path(uv)
    candidate = Path.home() / ".local" / "bin" / "uv"
    return candidate if candidate.exists() else None


def _copy_dir(src: Path, dst: Path, dry_run: bool = False) -> int:
    """Recursively copy src to dst, skipping excluded items. Returns file count."""
    if not dry_run:
        dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src.iterdir():
        if item.name in SKIP_DIRS:
            continue
        if item.suffix in SKIP_SUFFIXES:
            continue
        if item.name in SKIP_FILES:
            continue
        if item.is_dir():
            count += _copy_dir(item, dst / item.name, dry_run=dry_run)
        else:
            if not dry_run:
                shutil.copy2(item, dst / item.name)
            count += 1
    return count


MODELS_BLOCK = """
# Per-task models (optional, opt-in)
# Which model each Coograph agent runs on. `unset` means Coograph asks once, on
# the next ticket, and never again whatever you answer. `off` means every agent
# inherits your session model and nothing is suggested. `preset` applies the map
# below. `per-task` suggests a map for each ticket before using it.
#   /coograph-suggest-multi-models   propose or change a mapping
#   /coograph-disable-multi-models   turn it off for good
#
# `catalog` is yours. It binds each alias `preset` uses to the model id your
# tool actually loads, plus rough per-million-token rates so a suggestion can
# state a cost delta. Coograph ships none: the ids below are an example for
# Anthropic models, not a default. Every supported tool wants a different id
# form -- Cursor `composer-2`, OpenCode `provider/model-id`, Copilot only its
# own vendor -- so the catalog is the project's to declare and to keep correct.
# With no catalog, nothing changes: the built-in Anthropic aliases still work
# on Claude Code exactly as before.
models:
  mode: unset          # unset | off | preset | per-task
  # catalog:           # yours to declare: alias -> model id + rough rates
  #   cheap:   { id: claude-haiku-4-5, in: 1,  out: 5  }
  #   mid:     { id: claude-sonnet-5,  in: 2,  out: 10 }
  #   capable: { id: claude-opus-5,    in: 5,  out: 25 }
  #   top:     { id: claude-fable-5-1, in: 10, out: 50 }
  # preset:            # role -> catalog alias
  #   explore: cheap
  #   search: cheap
  #   verifier: mid
  #   reviewer: capable
  #   debugger: capable
  #   planner: capable
  #   retro: capable
"""


def _seed_models_block(path: Path, prefix: str, dry_run: bool = False) -> int:
    """Append the opt-in `models` block to an existing openspec/config.yaml.

    config.yaml is in SKIP_FILES because it holds the user's own project
    context, so a project initialised before this feature would never see the
    block and could not discover the commands. Appending is safe: the file is
    YAML, the block is a new top-level key, and an existing `models:` key means
    the user already has it and nothing is touched.
    """
    target = path / "openspec" / "config.yaml"
    if not target.exists():
        return 0
    try:
        body = target.read_text(encoding="utf-8")
    except OSError:
        return 0
    if "models:" in body:
        return 0
    if dry_run:
        log.info("  %sopenspec/config.yaml  would seed models block", prefix)
        return 0
    try:
        target.write_text(body.rstrip("\n") + "\n" + MODELS_BLOCK, encoding="utf-8")
    except OSError as e:
        log.warning("  models block not seeded: %s", e)
        return 0
    log.info("  %sopenspec/config.yaml  models block seeded", prefix)
    return 1


CATALOG_LINES = """  # catalog:           # yours to declare: alias -> model id + rough rates
  #   cheap:   { id: claude-haiku-4-5, in: 1,  out: 5  }
  #   mid:     { id: claude-sonnet-5,  in: 2,  out: 10 }
  #   capable: { id: claude-opus-5,    in: 5,  out: 25 }
  #   top:     { id: claude-fable-5-1, in: 10, out: 50 }
"""


def _seed_catalog_block(path: Path, prefix: str, dry_run: bool = False) -> int:
    """Add the commented `catalog` example to a config that already has `models`.

    _seed_models_block returns early once `models:` exists, so a project that
    got the models block before the catalog existed would never see it. The
    lines are inserted inside the block, right after `mode:`, so uncommenting
    them lands at the right indentation rather than at the end of the file.
    """
    target = path / "openspec" / "config.yaml"
    if not target.exists():
        return 0
    try:
        body = target.read_text(encoding="utf-8")
    except OSError:
        return 0
    if "models:" not in body or "catalog:" in body:
        return 0

    lines = body.splitlines(keepends=True)
    out, inserted = [], False
    in_models = False
    for line in lines:
        out.append(line)
        if line.startswith("models:"):
            in_models = True
            continue
        if in_models and not inserted and re.match(r"\s+mode:", line):
            out.append(CATALOG_LINES)
            inserted = True
    if not inserted:
        return 0

    if dry_run:
        log.info("  %sopenspec/config.yaml  would seed catalog block", prefix)
        return 0
    try:
        target.write_text("".join(out), encoding="utf-8")
    except OSError as e:
        log.warning("  catalog block not seeded: %s", e)
        return 0
    log.info("  %sopenspec/config.yaml  catalog block seeded", prefix)
    return 1


def _sync_retro(path: Path, prefix: str, dry_run: bool = False) -> int:
    """Copy .github/retro/ (analyzer + README, never tests/) and merge the
    seeded registry into the project's rules.json without overwriting it."""
    src = TEMPLATE_ROOT / ".github" / "retro"
    if not src.exists():
        return 0
    dst = path / ".github" / "retro"
    n = _copy_dir(src, dst, dry_run=dry_run)
    log.info("  %s.github/retro  %d files", prefix, n)
    seed = src / "rules.seed.json"
    target = dst / "rules.json"
    if not dry_run and seed.exists():
        if not target.exists():
            shutil.copy2(seed, target)
            log.info("  %s.github/retro/rules.json  seeded", prefix)
            n += 1
        else:
            try:
                out = subprocess.run(
                    [sys.executable, str(dst / "retro.py"), "--cwd", str(path),
                     "--merge-seed", str(seed)],
                    capture_output=True, text=True, timeout=30,
                )
                log.info("  %s%s", prefix, (out.stdout or out.stderr).strip())
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("  retro --merge-seed failed: %s", e)
    elif dry_run and seed.exists():
        log.info("  %s.github/retro/rules.json  %s", prefix,
                 "would seed" if not target.exists() else "would merge seed")
    return n


def _cleanup_obsolete(project_path: Path, dry_run: bool = False) -> int:
    """Remove paths in OBSOLETE_PATHS from project_path. Returns removed count."""
    removed = 0
    prefix = "[DRY-RUN] " if dry_run else ""
    for rel in OBSOLETE_PATHS:
        target = project_path / rel
        if not target.exists():
            continue
        if not dry_run:
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except OSError as e:
                log.warning("  CLEANUP failed to remove %s: %s", rel, e)
                continue
        log.info("  %sCLEANUP removed obsolete %s", prefix, rel)
        removed += 1
    return removed


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_project(project: dict, dry_run: bool = False) -> bool:
    path = Path(project["path"])
    if not path.exists():
        log.warning("SKIP %s (path not found)", path)
        return False

    tools = set(project.get("tools", []))
    code_graph = project.get("code_graph", False)
    prefix = "[DRY-RUN] " if dry_run else ""
    log.info("  %sconfig: tools=%s, code_graph=%s", prefix, sorted(tools), code_graph)
    total = 0

    # Always-copy: .github/skills/ is consumed by every supported tool
    # (Claude Code, VS Code Copilot, Codex CLI, OpenCode, Cursor, Devin Desktop,
    # Aider, Cline). Mirror what coograph-init does at install time.
    skills_src = TEMPLATE_ROOT / ".github" / "skills"
    if skills_src.exists():
        n = _copy_dir(skills_src, path / ".github" / "skills", dry_run=dry_run)
        log.info("  %s.github/skills  %d files", prefix, n)
        total += n

    # Retro analyzer + registry: every tool runs the /coograph-retro skill,
    # so this is always-copy too. Capture hooks are Claude-only (below).
    total += _sync_retro(path, prefix, dry_run=dry_run)
    total += _seed_models_block(path, prefix, dry_run=dry_run)

    # Claude Code commands
    if "claude" in tools:
        # Top-level coograph-* slash command wrappers (coograph-init,
        # coograph-new-ticket, coograph-plan, etc.). These live at the
        # top of .claude/commands/, not under project/.
        top_src = TEMPLATE_ROOT / ".claude" / "commands"
        if top_src.exists():
            top_dst = path / ".claude" / "commands"
            if not dry_run:
                top_dst.mkdir(parents=True, exist_ok=True)
            n = 0
            for item in top_src.glob("coograph-*.md"):
                if not dry_run:
                    shutil.copy2(item, top_dst / item.name)
                n += 1
            if n:
                log.info("  %s.claude/commands/coograph-*.md  %d files", prefix, n)
                total += n

        # User-authored project-specific commands live under project/.
        # No coograph commands ship there as of 2026-05-18 — sync still
        # mirrors the dir for backwards compatibility with older templates.
        src = TEMPLATE_ROOT / ".claude" / "commands" / "project"
        if src.exists() and any(src.iterdir()):
            n = _copy_dir(src, path / ".claude" / "commands" / "project", dry_run=dry_run)
            log.info("  %s.claude/commands/project  %d files", prefix, n)
            total += n

        # Claude Code lifecycle hooks (block generated files, log bash, etc.)
        hooks_src = TEMPLATE_ROOT / ".claude" / "hooks"
        if hooks_src.exists():
            n = _copy_dir(hooks_src, path / ".claude" / "hooks", dry_run=dry_run)
            log.info("  %s.claude/hooks  %d files", prefix, n)
            total += n

        # Committed settings.json wires the hooks. Downstream users put
        # personal overrides in settings.local.json (not synced).
        settings_src = TEMPLATE_ROOT / ".claude" / "settings.json"
        if settings_src.exists():
            if not dry_run:
                shutil.copy2(settings_src, path / ".claude" / "settings.json")
            log.info("  %s.claude/settings.json  1 file", prefix)
            total += 1

    # VS Code Copilot files (skills handled by always-copy block above)
    if "vscode" in tools:
        for subdir in ("agents", "prompts", "instructions"):
            src = TEMPLATE_ROOT / ".github" / subdir
            if src.exists():
                n = _copy_dir(src, path / ".github" / subdir, dry_run=dry_run)
                log.info("  %s.github/%s  %d files", prefix, subdir, n)
                total += n
        agents_md = TEMPLATE_ROOT / "AGENTS.md"
        if agents_md.exists():
            if not dry_run:
                shutil.copy2(agents_md, path / "AGENTS.md")
            log.info("  %sAGENTS.md  1 file", prefix)
            total += 1

    # Code graph server + parsers + MCP config
    if code_graph:
        src = TEMPLATE_ROOT / ".github" / "code-graph"
        if src.exists():
            n = _copy_dir(src, path / ".github" / "code-graph", dry_run=dry_run)
            log.info("  %s.github/code-graph  %d files", prefix, n)
            total += n

        mcp_src = TEMPLATE_ROOT / ".mcp.json"
        if mcp_src.exists():
            if not dry_run:
                shutil.copy2(mcp_src, path / ".mcp.json")
            log.info("  %s.mcp.json  1 file", prefix)
            total += 1
    elif (path / ".github" / "code-graph").exists():
        log.warning("  code_graph is false but %s has .github/code-graph/ "
                     "- set code_graph: true in projects.json to sync updates", path)

    # Remove paths that previous template versions placed but have since
    # been renamed / removed. See OBSOLETE_PATHS at the top of the module.
    obsolete = _cleanup_obsolete(path, dry_run=dry_run)

    log.info("%sSYNC %s - %d files updated, %d obsolete removed",
             prefix, path, total, obsolete)

    # Rebuild graph + regenerate visualizer (skipped on dry-run)
    if code_graph and not dry_run:
        _rebuild_graph(path)

    return True


def _is_wsl_path(path: Path) -> bool:
    """Detect if a path lives on a WSL filesystem."""
    s = str(path)
    return s.startswith("\\\\wsl") or s.startswith("//wsl")


def _wsl_native_path(path: Path) -> str:
    """Convert a Windows-accessible WSL path to its native Linux path.

    \\\\wsl.localhost\\Ubuntu\\home\\paul\\project -> /home/paul/project
    //wsl.localhost/Ubuntu/home/paul/project   -> /home/paul/project
    """
    s = str(path).replace("\\", "/")
    # Strip //wsl.localhost/Distro or //wsl$/Distro prefix
    parts = s.split("/")
    # Find the distro name (first non-empty segment after wsl.localhost or wsl$)
    idx = None
    for i, p in enumerate(parts):
        if p.lower() in ("wsl.localhost", "wsl$"):
            idx = i + 1  # distro name
            break
    if idx is not None and idx < len(parts):
        return "/" + "/".join(parts[idx + 1:])
    return s


def _wsl_distro(path: Path) -> str:
    """Extract the WSL distro name from a path."""
    s = str(path).replace("\\", "/")
    parts = s.split("/")
    for i, p in enumerate(parts):
        if p.lower() in ("wsl.localhost", "wsl$"):
            if i + 1 < len(parts):
                return parts[i + 1]
    return "Ubuntu"


def _rebuild_graph(project_path: Path) -> None:
    uv = _find_uv()
    server = project_path / ".github" / "code-graph" / "server.py"
    reqs = project_path / ".github" / "code-graph" / "requirements.txt"

    if not server.exists():
        log.warning("SKIP graph rebuild - server.py not found in %s", project_path)
        return

    # WSL paths need to run natively inside WSL to avoid SQLite locking issues
    if _is_wsl_path(project_path):
        distro = _wsl_distro(project_path)
        native = _wsl_native_path(project_path)
        native_server = native + "/.github/code-graph/server.py"
        log.info("BUILD graph (WSL %s)...", distro)

        for flag, label in [("--build", "graph.db"), ("--visualize", "graph.html")]:
            t0 = time.perf_counter()
            result = subprocess.run(
                ["wsl", "-d", distro, "--", "bash", "-c",
                 f"cd {native} && python3 {native_server} {flag}"],
                capture_output=True, text=True,
            )
            elapsed = time.perf_counter() - t0
            if result.returncode != 0:
                log.error("%s failed (%.2fs):\n%s", label, elapsed, result.stderr.strip())
                if flag == "--build":
                    return  # skip visualize if build failed
            else:
                if flag == "--build":
                    db = project_path / ".code-graph" / "graph.db"
                    size = f"{db.stat().st_size // 1024}KB" if db.exists() else "?"
                    log.info("%s built: %s in %.2fs", label, size, elapsed)
                else:
                    log.info("%s generated in %.2fs", label, elapsed)
        return

    if uv and reqs.exists():
        cmd_base = [str(uv), "run", "--with-requirements", str(reqs), str(server)]
        log.info("BUILD graph (uv + tree-sitter)...")
    else:
        cmd_base = [sys.executable, str(server)]
        log.info("BUILD graph (python fallback)...")

    t0 = time.perf_counter()
    result = subprocess.run(cmd_base + ["--build"], cwd=project_path, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0

    if result.returncode != 0:
        log.error("Graph build failed (%.2fs):\n%s", elapsed, result.stderr.strip())
        return

    db = project_path / ".code-graph" / "graph.db"
    size = f"{db.stat().st_size // 1024}KB" if db.exists() else "?"
    log.info("graph.db built: %s in %.2fs", size, elapsed)

    t0 = time.perf_counter()
    result = subprocess.run(cmd_base + ["--visualize"], cwd=project_path, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0

    if result.returncode != 0:
        log.error("Visualizer failed (%.2fs):\n%s", elapsed, result.stderr.strip())
    else:
        log.info("graph.html generated in %.2fs", elapsed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _ensure_hooks() -> None:
    """Point git to .github/hooks/ so post-merge runs automatically."""
    hooks_dir = TEMPLATE_ROOT / ".github" / "hooks"
    if not hooks_dir.exists():
        return
    result = subprocess.run(
        ["git", "config", "--local", "core.hooksPath", ".github/hooks"],
        cwd=TEMPLATE_ROOT, capture_output=True, text=True,
    )
    if result.returncode == 0:
        log.info("Git hooks configured (core.hooksPath = .github/hooks)")
    else:
        log.warning("Failed to set core.hooksPath: %s", result.stderr.strip())


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        log.info("=== DRY-RUN: no files will be written or removed ===")

    if not dry_run:
        _ensure_hooks()

    if not PROJECTS_FILE.exists():
        log.info("projects.json not found - no projects registered.")
        return

    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read projects.json: %s", e)
        sys.exit(1)

    projects = data.get("projects", [])
    if not projects:
        log.info("No projects registered in projects.json.")
        return

    log.info("Starting sync for %d registered project(s)...", len(projects))
    t_start = time.perf_counter()
    ok = 0
    for p in projects:
        log.info("=> %s", p.get("path", "(no path)"))
        if sync_project(p, dry_run=dry_run):
            ok += 1

    log.info("Sync complete: %d/%d project(s) updated in %.2fs",
             ok, len(projects), time.perf_counter() - t_start)


if __name__ == "__main__":
    main()
