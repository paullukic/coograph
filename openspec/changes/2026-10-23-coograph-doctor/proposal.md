# Proposal: `/coograph-doctor`, an install health check

Issue #1. Branch `feat/coograph-doctor` off `main` (1.8.8).

## Why

After `/coograph-init` nothing tells you whether the install still works. Problems seen in this repo's own history, each of which shows up only as an agent that quietly works with less context:

- **Stale or degraded graphs.** A venv without tree-sitter silently built with the regex parsers until 1.8.7, and a graph left untouched since the last commit misses every change since.
- **MCP configs pointing at moved or absolute paths.** `opencode.json` holds machine-specific absolute paths (MIGRATION 1.8.5).
- **Leftover `_TBD_` / `<!-- FILL` markers** after a partial init.
- **Hooks wired in `.claude/settings.json` whose script is missing.**
- **Tools registered in `projects.json` whose files were never copied**, or the reverse.

Init's own Step 9 checks only the graph, only once, and only as prose for the agent to follow.

The issue predates the plugin, `sync.py`, Retro and the layout checker. This proposal keeps the issue's checks and maps them onto the repo as it is now.

## Goals

- **A read-only check script**, `.github/skills/coograph-doctor/doctor.py`, stdlib only, run as `python3 .github/skills/coograph-doctor/doctor.py [--project PATH] [--registry PATH] [--json]`. It prints one `PASS` / `WARN` / `FAIL` / `SKIP` line per check; each non-PASS line has a `fix:` line under it. It ends with `Summary: N PASS, N WARN, N FAIL, N SKIP`. Exit codes: 0 with no FAIL, 1 with any FAIL, 2 on a usage error. It never writes to the project.
- **The checks from the issue**, plus three cheap ones (see Decisions):

  | id | Checks | FAIL | WARN | SKIP |
  |---|---|---|---|---|
  | `graph` | `.code-graph/graph.db` exists; node, edge and file counts | db missing, 0 nodes or 0 edges | more than 50 functions but 0 `calls` edges (built without tree-sitter) | code-graph not enabled |
  | `graph-age` | db age against the last commit (`git log -1`) | | db older than the last commit by more than 1 h | not a git repo, or code-graph off |
  | `server` | `.github/code-graph/server.py` and `requirements.txt` present; `uv` on PATH | server files missing; an MCP config runs `uv` but there is no `uv` | no `uv`, but the MCP configs use python or a venv | code-graph off |
  | `mcp:<tool>` | for Claude Code (`.mcp.json`), VS Code (`.vscode/mcp.json`), Cursor (`.cursor/mcp.json`), OpenCode (`opencode.json`): the file parses, has a `code-graph` entry, and every path in it resolves (`${workspaceFolder}` expanded); OpenCode also needs `skills.paths` to contain `.github/skills` | missing file, no entry, a path that does not exist | | tool not installed, or code-graph off |
  | `markers` | zero `_TBD_` / `<!-- FILL` in `.github/copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md` (each that exists) | any marker (lists file:line) | | template checkout (`templates/` + `setup.sh` at the root) |
  | `tools` | each tool's expected files (init Step 3 lists) exist, for the tools in `projects.json`, or detected on disk when there is no registry | a registered tool's files are missing | files on disk for a tool the registry does not list; an unknown tool id | |
  | `hooks:git` | `post-commit`, `post-merge`, `post-rewrite` in the hooks dir (`git rev-parse --git-path hooks`, so `core.hooksPath` counts), each running `server.py --update` | | a hook is missing or does not call the graph update | not a git repo, or code-graph off |
  | `openspec` | `openspec/config.yaml` exists and parses (PyYAML when importable, else a stdlib structural check: no tabs in indentation, every line a `key:`, a list item or inside a block scalar) | missing or unparseable | | |

_Changed during apply: the structural-check result is PASS (its detail says "structural check; PyYAML not installed"), not WARN. A WARN would turn every fresh init on a machine without PyYAML into a WARN, against the "all PASS" acceptance._
  | `hooks:claude` | `.claude/settings.json` parses, and every `$CLAUDE_PROJECT_DIR/.claude/hooks/<x>.py` it wires exists | invalid JSON, or a wired hook file missing | | Claude Code not installed |
  | `sync` | files under `.coograph/upstream/` (sync kept a locally edited file and parked the new version there) | | N files waiting, listed | never synced |

- **The skill**, `.github/skills/coograph-doctor/SKILL.md`. It runs the script, shows the report, and for each FAIL or WARN offers the matching fix:
  - graph problems: `/coograph-rebuild-graph`;
  - missing files, markers or MCP entries: re-run `/coograph-init`, which handles a partial install;
  - git hooks: the copy commands from init Step 6h;
  - parked upstream copies: `sync.py --project`.
  
  It never fixes anything without an explicit yes.
- **The same invocation pattern as init, across all 8 tools.** The full file list is under Impact.
- **Init ends with the doctor.** A new last init step runs the script and expects all PASS (WARN only for options the user declined, such as git hooks). Init Step 8 names the tool ids, which the doctor's `tools` check needs: `claude`, `vscode`, `codex`, `opencode`, `cursor`, `devin` (`windsurf` accepted as an alias), `aider`, `cline`. The Codex copy line covers `.agents/skills/coograph-*/`.
- **The drift check covers the doctor.** `check-invocations.py` runs its assertions per skill (init and doctor), so CI catches a tool file that loses the doctor trigger.
- **Docs:** the README and SETUP.md invocation tables, the website getting-started page (separate repo, separate commit), and MIGRATION.
- **Release:** `VERSION` set to the next free number at merge (1.8.12 if the pending 1.8.9 to 1.8.11 land first), plugin rebuilt.

## Non-Goals

- No automatic fixing. The script is read-only; the skill asks before every fix.
- No comparison of template-managed file contents against upstream. `sync.py --dry-run` already does that; the doctor only reports what sync has already parked in `.coograph/upstream/`.
- No MCP check for Codex CLI, Devin Desktop, Aider or Cline: init writes no MCP config for them.
- No check that the MCP server actually starts. That needs `uv` to resolve dependencies, which can take minutes on a cold cache. A possible `--deep` flag later.
- No sync of Codex, Cursor, Devin, Aider or Cline files to registered projects. `sync.py` covers Claude Code, VS Code and OpenCode only, and changing that is a separate change. Noted under Risks.

## Decisions

- **A script inside the skill folder, not a prose-only skill.** Every check is deterministic, so it belongs in code that tests can break on purpose, which is the issue's third acceptance item. Inside `.github/skills/coograph-doctor/`, it ships everywhere skills already go (init's always-copy block, `sync.py`, the plugin), with no new distribution path. Tests live in `.github/skills/coograph-doctor/tests/`, which `sync.py` (`SKIP_DIRS`) and `build-plugin.py` (`SKIP_NAMES`) already skip. Init Step 3 gets a "never `tests/`" note for `.github/skills/`.
- **Registry access is opt-in.** `projects.json` lives in the coograph checkout, not in the project.
  - Run from coograph: `python3 <coograph>/.github/skills/coograph-doctor/doctor.py --project <path>` finds the registry next to itself.
  - Run inside a project: `--registry <path>` is needed; without it, `tools` falls back to the files on disk and says so.
  - Plugin installs have no registry; disk detection is the only mode.
- **Optional features are SKIP, not FAIL.** Code-graph off means the graph, server, MCP and git-hook checks are SKIP. Missing git hooks are a WARN, because init asks about them. "All PASS on a fresh init" means a fresh init with every option set to yes.
- **Three extra checks beyond the issue:** `hooks:claude`, `sync`, and the WARN in `graph` for 0 `calls` edges. Each comes from a real incident in this repo (hooks moving files, sync keeping local edits, the 1.8.7 tree-sitter venv). Each is a few lines. Strike any of them if you want the issue's list only.
- **Thresholds are constants in the script:** 1 h for graph age, 50 functions for the tree-sitter WARN. They are not configurable until someone needs that.

## Impact

Files to create:

| Tool | File |
|---|---|
| all (canonical) | `.github/skills/coograph-doctor/SKILL.md`, `.github/skills/coograph-doctor/doctor.py` |
| tests | `.github/skills/coograph-doctor/tests/test_doctor.py` |
| Claude Code | `.claude/commands/coograph-doctor.md` |
| OpenCode | `.opencode/commands/coograph-doctor.md` |
| Codex CLI | `.agents/skills/coograph-doctor/SKILL.md` (`$coograph-doctor`) |
| VS Code Copilot | none: it reads `.github/skills/coograph-doctor/` |

Files to modify:

- Rule files (Cursor, Devin Desktop, Aider, Cline, plus the shared `AGENTS.md`), each gaining an Invocation line for `/coograph-doctor`:
  - `templates/cursor/.cursor/rules/coograph.mdc`
  - `templates/windsurf/.windsurfrules`
  - `templates/aider/CONVENTIONS.md`
  - `templates/cline/.clinerules`
  - `AGENTS.md`
- `.github/scripts/check-invocations.py`: the manifest and assertions become per skill.
- `.github/workflows/checks.yml`: a step that runs the doctor tests.
- `.github/skills/coograph-init/SKILL.md`:
  - Step 3: the OpenCode and Claude Code command lists, the Codex `.agents/skills/coograph-*/` line, and a "never `tests/`" note;
  - Step 8: the tool ids;
  - a new final step that runs the doctor.
- The init wrappers `.claude/commands/coograph-init.md`, `.opencode/commands/coograph-init.md` and `.agents/skills/coograph-init/SKILL.md`. They currently say "every step (1–10)" and "(1–9)" while init has 11 steps; they will say "every step" and mention the final doctor run.
- `.github/scripts/build-plugin.py`: `TEMPLATE_PATHS` `.agents/skills/coograph-init` becomes `.agents/skills`, and `VERSION`.
- `README.md` and `SETUP.md`: invocation tables (a doctor row next to init) and the OpenCode "all four" note, which becomes five.
- `MIGRATION.md`.
- `plugin/**` and `.claude-plugin/marketplace.json`, regenerated.
- `C:\paul\code\coograph-website\src\pages\docs\getting-started.mdx` (separate repo): a "Check the install" section after init.

Dependencies affected: none. stdlib only; PyYAML is used when present, never required.

## Risks

- **Registry vs disk disagreement is noisy.** Old `projects.json` entries were written before tool ids were defined; some may hold names like `codex` that sync never used. Mitigation: unknown ids are WARN, never FAIL, and the measurement task runs the doctor on all 10 registered projects and reports what it says before release.
- **False FAIL on a healthy install** would make users distrust the tool. Mitigation: every FAIL condition is something that breaks a session (a missing file, a dead path, an empty graph). Anything fuzzier is WARN. The run on the registered projects is hand-checked.
- **Graph age compares mtime with commit time.** A checkout or `git pull` that didn't run the hooks leaves the db older, which is exactly what should be flagged. A 1 h tolerance avoids flagging a commit made seconds after a build.
- **Windows paths in MCP configs** (`C:\...`, `${workspaceFolder}`). Mitigation: tests with both forms, and the run on registered projects, which are all on Windows.
- **Codex, Cursor, Devin, Aider and Cline files are never refreshed by sync.** The doctor will report them stale if init changes, and only re-init fixes that. Reported, not solved, here.
- **Version and MIGRATION conflicts** with the three pending PRs. Rebased at merge time.

## Open questions

1. Keep the three extra checks (`hooks:claude`, `sync`, the tree-sitter WARN)? Proposed: yes.
2. Should init's new last step replace init Step 9's prose graph check? Proposed: no, keep Step 9 for now. It compares against source-file counts, which the doctor does not, and folding it in can come later.
