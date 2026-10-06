#!/usr/bin/env python3
"""Sync coograph updates to all registered projects.

Run from the coograph root (executed automatically by post-merge hook).
Reads projects.json, copies pure-template files to each registered project,
and rebuilds the code-graph + visualizer for projects with code_graph: true.

A template-managed file is overwritten only when the project has not edited
it (see _write_managed): a locally edited file is kept, the upstream version
goes to .coograph/upstream/<path>, and sync logs one KEPT line per file.

    python3 .github/sync.py                    # every registered project
    python3 .github/sync.py --dry-run          # decide and log, write nothing
    python3 .github/sync.py --project PATH     # one registered project
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent  # .github/sync.py -> root
PROJECTS_FILE = TEMPLATE_ROOT / "projects.json"
LOG_FILE = Path(__file__).parent / "sync.log"

# Per project, under the gitignored local state directory: the hash of every
# file as sync last left it, and the upstream copy of every file sync kept.
MANIFEST_REL = Path(".coograph") / "sync-manifest.json"
UPSTREAM_REL = Path(".coograph") / "upstream"
EM_DASH = "—"

# Skip these when recursively copying directories. "tests" is here for
# .github/retro/tests/ (unit tests stay in the coograph repo); no other
# synced tree has a directory by that name.
SKIP_DIRS = {"node_modules", "__pycache__", ".code-graph", "tests"}
SKIP_SUFFIXES = {".bak", ".pyc", ".db"}

# Interpreter `uv run` is pinned to. Without it uv resolves against the machine's
# default Python, and on a default older than 3.10 the graph build dies with
# "your requirements are unsatisfiable" (mcp requires 3.10+). uv downloads a
# managed interpreter on demand, so this needs nothing installed. Keep in step
# with the pin in .mcp.json and in coograph-init's SKILL.md.
UV_PYTHON = "3.12"

# Never overwrite these - user has customized them during initialization.
# rules.json is the per-project Retro registry: local edits, thresholds and
# last_retro must survive a sync. New seeded rules reach it from
# rules.seed.json (which IS synced) through `retro.py --merge-seed`, see
# _sync_retro. Applies to every synced tree; only .github/retro/ has one.
# layout.json is the same idea for .github/layout/ (see _sync_layout), and
# GOTCHAS.md is project knowledge, seeded once by init and never touched again.
SKIP_FILES = {
    "CLAUDE.md", "copilot-instructions.md", "config.yaml", "rules.json",
    "layout.json", "GOTCHAS.md",
}

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


# ---------------------------------------------------------------------------
# Local-edit protection
# ---------------------------------------------------------------------------

def _digest(data: bytes) -> str:
    """sha256 after CRLF -> LF, so an autocrlf checkout is not an edit."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _render(data: bytes, em_dash: str) -> bytes:
    """What sync writes for a template file, given the project's setting."""
    if em_dash != "hyphen":
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data  # binary: never rewritten
    if EM_DASH not in text:
        return data
    return text.replace(EM_DASH, "-").encode("utf-8")


_SYNC_BLOCK_RE = re.compile(r"^sync:\s*(#.*)?$")
_EM_DASH_RE = re.compile(r"^\s+em_dash:\s*([A-Za-z]+)\s*(#.*)?$")


def _project_em_dash(path: Path) -> str:
    """`sync: em_dash:` from the project's openspec/config.yaml: keep | hyphen.

    A line regex, not a YAML parser (stdlib only): the key must sit indented
    under a top-level `sync:` line. Anything unknown means `keep`.
    """
    try:
        lines = (path / "openspec" / "config.yaml").read_text(
            encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return "keep"
    in_block = False
    for line in lines:
        if _SYNC_BLOCK_RE.match(line):
            in_block = True
            continue
        if in_block:
            if line.strip() == "" or line.lstrip().startswith("#"):
                continue
            if not line[:1].isspace():
                break  # next top-level key
            m = _EM_DASH_RE.match(line)
            if m:
                return "hyphen" if m.group(1).lower() == "hyphen" else "keep"
    return "keep"


class _History:
    """Every earlier version of each template file, from the coograph git history.

    Lets a project file that equals an upstream version ever shipped count as
    untouched (only outdated) even with no manifest entry. Read once per run,
    lazily, with one `git log` and one `git cat-file --batch`. No git, or no
    history: empty, and sync falls back to the manifest (keeps more, loses none).
    """

    ROOTS = (".github", ".claude", ".mcp.json")

    def __init__(self, root: Path) -> None:
        self.root = root
        self._blobs: dict[str, set[str]] | None = None
        self._content: dict[str, bytes] = {}
        self._digests: dict[tuple[str, str], set[str]] = {}

    def _load(self) -> dict[str, set[str]]:
        if self._blobs is not None:
            return self._blobs
        self._blobs = {}
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "log", "--raw", "--no-abbrev", "--no-renames",
                 "--format=", "--", *self.ROOTS],
                capture_output=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return self._blobs
        if out.returncode != 0:
            return self._blobs
        for line in out.stdout.decode("utf-8", "replace").splitlines():
            # :100644 100644 <old> <new> M\t<path>
            if not line.startswith(":") or "\t" not in line:
                continue
            meta, rel = line.split("\t", 1)
            parts = meta.split()
            if len(parts) < 4:
                continue
            for blob in (parts[2], parts[3]):
                if blob.strip("0"):
                    self._blobs.setdefault(rel, set()).add(blob)
        wanted = sorted({b for blobs in self._blobs.values() for b in blobs})
        if wanted:
            self._content = self._cat(wanted)
        return self._blobs

    def _cat(self, blobs: list[str]) -> dict[str, bytes]:
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "cat-file", "--batch"],
                input=("\n".join(blobs) + "\n").encode(), capture_output=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if out.returncode != 0:
            return {}
        data, pos, found = out.stdout, 0, {}
        while pos < len(data):
            end = data.find(b"\n", pos)
            if end < 0:
                break
            header = data[pos:end].split()
            pos = end + 1
            if len(header) != 3:
                continue  # "<sha> missing": no body follows
            try:
                size = int(header[2])
            except ValueError:
                break  # out of step with the stream: keep what was read
            if header[1] == b"blob":
                found[header[0].decode()] = data[pos:pos + size]
            pos += size + 1  # skip the body of any object type
        return found

    def digests(self, template_rel: str, em_dash: str) -> set[str]:
        key = (template_rel, em_dash)
        if key not in self._digests:
            blobs = self._load().get(template_rel, set())
            self._digests[key] = {
                _digest(_render(self._content[b], em_dash)) for b in blobs if b in self._content
            }
        return self._digests[key]


_HISTORY = _History(TEMPLATE_ROOT)


class ProjectSync:
    """Per-project state for one run: manifest, setting, kept files."""

    def __init__(self, path: Path, dry_run: bool = False) -> None:
        self.path = path
        self.dry_run = dry_run
        self.em_dash = _project_em_dash(path)
        self.kept: list[str] = []
        self.written = 0
        self._manifest_path = path / MANIFEST_REL
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            files = data.get("files") if isinstance(data, dict) else None
            self.manifest: dict[str, str] = {
                k: v for k, v in (files or {}).items() if isinstance(k, str) and isinstance(v, str)
            }
        except (OSError, ValueError):
            self.manifest = {}
        self._dirty = False

    def _rel(self, dst: Path) -> str:
        return dst.relative_to(self.path).as_posix()

    def _record(self, rel: str, digest: str) -> None:
        if self.manifest.get(rel) != digest:
            self.manifest[rel] = digest
            self._dirty = True

    def _drop_upstream_copy(self, rel: str) -> None:
        stale = self.path / UPSTREAM_REL / rel
        if stale.is_file() and not self.dry_run:
            try:
                stale.unlink()
            except OSError:
                pass

    def _write(self, src: Path, dst: Path, data: bytes, raw: bool) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if raw:
            shutil.copy2(src, dst)
        else:
            dst.write_bytes(data)
            shutil.copymode(src, dst)

    def write_managed(self, src: Path, dst: Path) -> str:
        """Write one template file unless the project edited it.

        Returns "written", "same" or "kept". In order: missing -> write;
        equal to upstream -> record; equal to the manifest hash or to any
        upstream version in git history -> untouched, overwrite; else kept.
        """
        rel = self._rel(dst)
        raw_src = src.read_bytes()
        new = _render(raw_src, self.em_dash)
        new_digest = _digest(new)
        exists = dst.exists()
        try:
            current = dst.read_bytes() if exists else None
        except OSError as e:
            # Unreadable is not missing: never overwrite what cannot be checked.
            log.warning("  SKIPPED %s (cannot read it: %s); left as is", rel, e)
            return "kept"
        if current is not None:
            cur_digest = _digest(current)
            if cur_digest == new_digest:
                self._record(rel, new_digest)
                self._drop_upstream_copy(rel)
                return "same"
            try:
                template_rel = src.resolve().relative_to(TEMPLATE_ROOT).as_posix()
            except ValueError:
                template_rel = ""
            untouched = (
                cur_digest == self.manifest.get(rel)
                or (template_rel and cur_digest in _HISTORY.digests(template_rel, self.em_dash))
            )
            if not untouched:
                upstream = UPSTREAM_REL / rel
                if not self.dry_run:
                    try:
                        (self.path / upstream).parent.mkdir(parents=True, exist_ok=True)
                        (self.path / upstream).write_bytes(new)
                    except OSError as e:
                        log.warning("  could not write %s: %s", upstream.as_posix(), e)
                self.kept.append(rel)
                log.warning("  KEPT %s (local edit). Upstream: %s. To take it, copy that file "
                            "over yours and sync again.", rel, upstream.as_posix())
                return "kept"
        if not self.dry_run:
            try:
                self._write(src, dst, new, raw=new is raw_src)
            except OSError as e:
                # One locked file must not abort this project or the next ones.
                log.warning("  SKIPPED %s (cannot write it: %s)", rel, e)
                return "kept"
            self._record(rel, new_digest)
            self._drop_upstream_copy(rel)
        self.written += 1
        return "written"

    def save(self) -> None:
        if self.dry_run or not self._dirty:
            return
        try:
            self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
            body = {"version": 1, "files": dict(sorted(self.manifest.items()))}
            tmp = self._manifest_path.with_name(self._manifest_path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, self._manifest_path)
        except OSError as e:
            log.warning("  sync manifest not saved: %s", e)


def _copy_dir(src: Path, dst: Path, state: ProjectSync) -> int:
    """Recursively sync src to dst, skipping excluded items. Returns file count."""
    count = 0
    for item in src.iterdir():
        if item.name in SKIP_DIRS:
            continue
        if item.suffix in SKIP_SUFFIXES:
            continue
        if item.name in SKIP_FILES:
            continue
        if item.is_dir():
            count += _copy_dir(item, dst / item.name, state)
        else:
            state.write_managed(item, dst / item.name)
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


def _sync_retro(path: Path, prefix: str, state: ProjectSync) -> int:
    """Copy .github/retro/ (analyzer + README, never tests/) and merge the
    seeded registry into the project's rules.json without overwriting it."""
    src = TEMPLATE_ROOT / ".github" / "retro"
    if not src.exists():
        return 0
    dry_run = state.dry_run
    dst = path / ".github" / "retro"
    n = _copy_dir(src, dst, state)
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


WORKFLOW_MARKER = "coograph:managed"


def _sync_layout(path: Path, prefix: str, state: ProjectSync) -> int:
    """Copy .github/layout/ (checker, seed, CI assets; never tests/ or
    layout.json), seed or merge the project's layout.json, and refresh the
    layout workflow only in projects that opted into it at init."""
    src = TEMPLATE_ROOT / ".github" / "layout"
    if not src.exists():
        return 0
    dry_run = state.dry_run
    dst = path / ".github" / "layout"
    n = _copy_dir(src, dst, state)
    log.info("  %s.github/layout  %d files", prefix, n)
    seed = src / "layout.seed.json"
    if seed.exists():
        if dry_run:
            log.info("  %s.github/layout/layout.json  would seed or merge", prefix)
        else:
            try:
                out = subprocess.run(
                    [sys.executable, str(dst / "layout.py"), "--cwd", str(path),
                     "--merge-seed", str(seed)],
                    capture_output=True, text=True, timeout=30,
                )
                log.info("  %s%s", prefix, (out.stdout or out.stderr).strip())
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("  layout --merge-seed failed: %s", e)
    workflow = path / ".github" / "workflows" / "coograph-layout.yml"
    workflow_src = src / "coograph-layout.yml"
    if workflow.exists() and workflow_src.exists():
        # Refreshed only while it still carries the managed marker: a project
        # that deleted the line has edited the workflow and owns it now. With
        # the marker it is still a template file: an edit is kept (KEPT line).
        try:
            managed = WORKFLOW_MARKER in workflow.read_text(encoding="utf-8", errors="replace")
        except OSError:
            managed = False
        if managed:
            if state.write_managed(workflow_src, workflow) != "kept":
                log.info("  %s.github/workflows/coograph-layout.yml  1 file", prefix)
                n += 1
        else:
            log.info("  %s.github/workflows/coograph-layout.yml  kept (customized: no %s line)",
                     prefix, WORKFLOW_MARKER)
    return n


def _sync_agents_md(path: Path, prefix: str, dry_run: bool = False) -> int:
    """Create AGENTS.md when absent; never overwrite it. Project-owned once it
    exists: init fills it and treats it as customized (Step 1b)."""
    src = TEMPLATE_ROOT / "AGENTS.md"
    if not src.exists():
        return 0
    if (path / "AGENTS.md").exists():
        log.info("  %sAGENTS.md  kept (project-owned)", prefix)
        return 0
    if not dry_run:
        shutil.copy2(src, path / "AGENTS.md")
    log.info("  %sAGENTS.md  1 file (created)", prefix)
    return 1


def _imports_agents_md(path: Path) -> bool:
    try:
        text = (path / "CLAUDE.md").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    return any(line.strip() == "@AGENTS.md" for line in text.splitlines())


def _sync_mcp_config(src: Path, dst: Path, prefix: str, dry_run: bool = False) -> bool:
    """Write the project's .mcp.json, merging rather than replacing.

    A project's MCP config is not template-owned: it can carry other servers and
    local edits (an interpreter pin, a different transport). Sync used to
    `shutil.copy2` over it, which silently reverted all of that on every pull.
    Only the `code-graph` entry belongs to the template, so only that key is
    written; everything else in the file is left exactly as it was.

    Returns True when the file was written (or would be, on a dry run).
    """
    key = "code-graph"
    try:
        template = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("  template .mcp.json unreadable, skipped: %s", e)
        return False
    entry = template.get("mcpServers", {}).get(key)
    if entry is None:
        log.warning("  template .mcp.json has no '%s' server, skipped", key)
        return False

    if not dst.exists():
        if not dry_run:
            dst.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        log.info("  %s.mcp.json  1 file (created)", prefix)
        return True

    # A malformed project config is the user's file, not ours: warn and move on
    # rather than aborting this project's sync (or overwriting their edits).
    try:
        current = json.loads(dst.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("  %s.mcp.json unparseable, left untouched: %s", prefix, e)
        return False
    if not isinstance(current, dict):
        log.warning("  %s.mcp.json is not a JSON object, left untouched", prefix)
        return False

    servers = current.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        log.warning("  %s.mcp.json has a non-object 'mcpServers', left untouched",
                    prefix)
        return False
    if servers.get(key) == entry:
        log.info("  %s.mcp.json  up to date", prefix)
        return False

    servers[key] = entry
    if not dry_run:
        dst.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    log.info("  %s.mcp.json  '%s' entry merged", prefix, key)
    return True


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
    state = ProjectSync(path, dry_run=dry_run)
    if state.em_dash != "keep":
        log.info("  %sem dashes: %s (openspec/config.yaml sync.em_dash)", prefix, state.em_dash)
    total = 0

    # Always-copy: .github/skills/ is consumed by every supported tool
    # (Claude Code, VS Code Copilot, Codex CLI, OpenCode, Cursor, Devin Desktop,
    # Aider, Cline). Mirror what coograph-init does at install time.
    skills_src = TEMPLATE_ROOT / ".github" / "skills"
    if skills_src.exists():
        n = _copy_dir(skills_src, path / ".github" / "skills", state)
        log.info("  %s.github/skills  %d files", prefix, n)
        total += n

    # Retro analyzer + registry: every tool runs the /coograph-retro skill,
    # so this is always-copy too. Capture hooks are Claude-only (below).
    total += _sync_retro(path, prefix, state)
    # Layout checker: tool-neutral like retro, so always-copy.
    total += _sync_layout(path, prefix, state)
    total += _seed_models_block(path, prefix, dry_run=dry_run)

    # Claude Code commands
    if "claude" in tools:
        # Top-level coograph-* slash command wrappers (coograph-init,
        # coograph-new-ticket, coograph-plan, etc.). These live at the
        # top of .claude/commands/, not under project/.
        top_src = TEMPLATE_ROOT / ".claude" / "commands"
        if top_src.exists():
            top_dst = path / ".claude" / "commands"
            n = 0
            for item in top_src.glob("coograph-*.md"):
                state.write_managed(item, top_dst / item.name)
                n += 1
            if n:
                log.info("  %s.claude/commands/coograph-*.md  %d files", prefix, n)
                total += n

        # User-authored project-specific commands live under project/.
        # No coograph commands ship there as of 2026-05-18 — sync still
        # mirrors the dir for backwards compatibility with older templates.
        src = TEMPLATE_ROOT / ".claude" / "commands" / "project"
        if src.exists() and any(src.iterdir()):
            n = _copy_dir(src, path / ".claude" / "commands" / "project", state)
            log.info("  %s.claude/commands/project  %d files", prefix, n)
            total += n

        # Claude Code lifecycle hooks (block generated files, log bash, etc.)
        hooks_src = TEMPLATE_ROOT / ".claude" / "hooks"
        if hooks_src.exists():
            n = _copy_dir(hooks_src, path / ".claude" / "hooks", state)
            log.info("  %s.claude/hooks  %d files", prefix, n)
            total += n

        # The tiered CLAUDE.md gets every hard rule through `@AGENTS.md`;
        # without the file Claude Code skips the import silently. Projects
        # still on a self-contained CLAUDE.md do not import it and get nothing.
        if _imports_agents_md(path):
            total += _sync_agents_md(path, prefix, dry_run=dry_run)

        # Committed settings.json wires the hooks. Downstream users put
        # personal overrides in settings.local.json (not synced).
        settings_src = TEMPLATE_ROOT / ".claude" / "settings.json"
        if settings_src.exists():
            state.write_managed(settings_src, path / ".claude" / "settings.json")
            log.info("  %s.claude/settings.json  1 file", prefix)
            total += 1

    # VS Code Copilot files (skills handled by always-copy block above)
    if "vscode" in tools:
        for subdir in ("agents", "prompts", "instructions"):
            src = TEMPLATE_ROOT / ".github" / subdir
            if src.exists():
                n = _copy_dir(src, path / ".github" / subdir, state)
                log.info("  %s.github/%s  %d files", prefix, subdir, n)
                total += n
        total += _sync_agents_md(path, prefix, dry_run=dry_run)

    # Code graph server + parsers + MCP config
    if code_graph:
        src = TEMPLATE_ROOT / ".github" / "code-graph"
        if src.exists():
            n = _copy_dir(src, path / ".github" / "code-graph", state)
            log.info("  %s.github/code-graph  %d files", prefix, n)
            total += n

        mcp_src = TEMPLATE_ROOT / ".mcp.json"
        if mcp_src.exists():
            if _sync_mcp_config(mcp_src, path / ".mcp.json", prefix, dry_run=dry_run):
                total += 1
    elif (path / ".github" / "code-graph").exists():
        log.warning("  code_graph is false but %s has .github/code-graph/ "
                     "- set code_graph: true in projects.json to sync updates", path)

    # Remove paths that previous template versions placed but have since
    # been renamed / removed. See OBSOLETE_PATHS at the top of the module.
    obsolete = _cleanup_obsolete(path, dry_run=dry_run)
    state.save()

    log.info("%sSYNC %s - %d files checked, %d written, %d kept (local edits), %d obsolete removed",
             prefix, path, total, state.written, len(state.kept), obsolete)
    if state.kept:
        log.warning("%s%d locally edited file(s) kept in %s; upstream copies are under %s/",
                    prefix, len(state.kept), path, UPSTREAM_REL.as_posix())

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
        cmd_base = [str(uv), "run", "-p", UV_PYTHON,
                    "--with-requirements", str(reqs), str(server)]
        log.info("BUILD graph (uv + tree-sitter, python %s)...", UV_PYTHON)
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


def _same_path(a: str, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Sync coograph to registered projects")
    parser.add_argument("--dry-run", action="store_true", help="decide and log, write nothing")
    parser.add_argument("--project", metavar="PATH", help="sync only this registered project")
    args = parser.parse_args(argv)
    dry_run = args.dry_run
    if dry_run:
        log.info("=== DRY-RUN: no files will be written or removed ===")

    if not dry_run and args.project is None:
        _ensure_hooks()

    if not PROJECTS_FILE.exists():
        log.info("projects.json not found - no projects registered.")
        return 2 if args.project else 0

    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to read projects.json: %s", e)
        return 1

    projects = data.get("projects", [])
    if args.project is not None:
        projects = [p for p in projects if _same_path(p.get("path", ""), Path(args.project))]
        if not projects:
            log.error("%s is not registered in projects.json (coograph-init registers it)",
                      args.project)
            return 2
    if not projects:
        log.info("No projects registered in projects.json.")
        return 0

    log.info("Starting sync for %d registered project(s)...", len(projects))
    t_start = time.perf_counter()
    ok = 0
    for p in projects:
        log.info("=> %s", p.get("path", "(no path)"))
        if sync_project(p, dry_run=dry_run):
            ok += 1

    log.info("Sync complete: %d/%d project(s) updated in %.2fs",
             ok, len(projects), time.perf_counter() - t_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
