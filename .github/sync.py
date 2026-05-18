#!/usr/bin/env python3
"""Sync coograph updates to all registered projects.

Run from the coograph root (executed automatically by post-merge hook).
Reads projects.json, copies pure-template files to each registered project,
and rebuilds the code-graph + visualizer for projects with code_graph: true.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).parent.parent  # .github/sync.py -> root
PROJECTS_FILE = TEMPLATE_ROOT / "projects.json"
LOG_FILE = Path(__file__).parent / "sync.log"

# Skip these when recursively copying directories
SKIP_DIRS = {"node_modules", "__pycache__", ".code-graph"}
SKIP_SUFFIXES = {".bak", ".pyc", ".db"}

# Never overwrite these - user has customized them during initialization
SKIP_FILES = {"CLAUDE.md", "copilot-instructions.md", "config.yaml"}

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
    # (Claude Code, VS Code Copilot, Codex CLI, OpenCode, Cursor, Windsurf,
    # Aider, Cline). Mirror what coograph-init does at install time.
    skills_src = TEMPLATE_ROOT / ".github" / "skills"
    if skills_src.exists():
        n = _copy_dir(skills_src, path / ".github" / "skills", dry_run=dry_run)
        log.info("  %s.github/skills  %d files", prefix, n)
        total += n

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
