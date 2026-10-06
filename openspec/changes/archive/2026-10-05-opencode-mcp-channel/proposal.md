# Proposal: Register OpenCode in sync + a code-graph launcher that survives locked-down Windows

## Why

Two gaps that compound for OpenCode users and locked-down Windows machines:

1. **The `uv run --with-requirements … server.py` launch shape coograph ships can be dead on arrival on Windows machines with Smart App Control / Defender Application Control.** uv by default builds its run environment on a uv-managed or per-user Python download, and on this machine that download's `_overlapped.pyd` (pulled in via asyncio when `mcp.server.fastmcp` is imported) is blocked by the application-control policy — every server start dies with `Cannot import mcp.server.fastmcp: DLL load failed while importing _overlapped`. A project then *looks* code-graph-enabled while actually running a silently dead MCP server: `report-graph.py` at SessionStart reads the empty `server.log`, and the agents' `graph-first` rule gets bypassed (observed in a registered project as `graph-first bypass/total-bypass` signals plus an empty `.code-graph/server.log`). System-installed Pythons (e.g. the Microsoft Store 3.12) load that DLL fine — the fix is choosing a *trusted interpreter*, not changing code-graph itself.
2. **OpenCode is listed as a supported tool but nothing propagates anything to it.** OpenCode reads neither `.mcp.json` (that is Claude Code's file) nor `.github/skills/` (that directory is not auto-scanned). It had exactly one shipped artifact — `.opencode/commands` — and `sync.py` had **no `opencode` tool block at all**: a registered OpenCode-only project receives neither the code-graph MCP wiring nor the skills after `git pull`.

Measured on this machine, before and after: unpinned `uv run` → `Cannot import mcp.server.fastmcp: DLL load failed while importing _overlapped`; with `UV_NO_MANAGED_PYTHON=1` → env built on system Python 3.12 in 775 ms and the server processed JSON-RPC, `graph_stats` read the real `graph.db`. A harness running the new `sync.py` against a synthetic project rebuilt the graph via the pinned uv launcher and booted the server exactly as the generated `opencode.json` describes — `tools/list` returned the full tool list.

## Goals

- `sync.py` resolves **one launcher per project/machine**: project venv → `uv` with uv-managed Python pinned off → bare `python`; use it both for the on-pull graph rebuild and for the MCP config written into the project.
- Registered projects that list `opencode` in `tools` receive: the four `.opencode/commands/coograph-*.md`, the `.opencode/plugin/log-bash.ts` audit plugin, and — when `code_graph: true` — a generated `opencode.json` carrying `skills.paths: [".github/skills"]` plus the `mcp.code-graph` entry. Written only when missing.
- `coograph-init` (Step 1 question 2, Step 3 copy list, Steps 6c/6e) teaches the same priority and the same file placement, so init and sync do not diverge.

## Non-Goals

- No transcript capture for OpenCode (Retro's transcript detectors stay Claude-Code-only).
- No `templates/opencode/` directory and no `TEMPLATE_PATHS` change — `opencode.json` is *generated* per project; a machine-dependent launcher cannot live in a committed template file.
- sync never creates the venv; it uses one if present. Creating it stays a documented init/manual fallback (Step 6c).

## Decisions

- **Pin `UV_NO_MANAGED_PYTHON=1` + `UV_PYTHON_DOWNLOADS=never` via the `env`/`environment` keys** rather than `--python-preference` CLI flags — one mechanism readable by Claude Code (`.mcp.json`), VS Code (`.vscode/mcp.json`), and OpenCode (`opencode.json`). On machines with *no* system Python at all this errors instead of silently downloading a blocked build; the escape hatch (drop the pins, or build a venv) is in MIGRATION.md and Step 6c.
- **`opencode.json` created only when missing** — it may carry per-machine provider/model settings; sync must never rewrite it.
- **`"cwd": "."`** in the generated `opencode.json` (relative paths resolve from the workspace directory, so project-root and `.opencode/` placements both keep working) and **`timeout: 120000`** — the default 5 s MCP request timeout is too short for `build_graph`/`update_graph`.
- WSL paths skip `opencode.json` generation (OpenCode running inside WSL wants a hand-written file with native paths; sync must not write Windows interpreters into it).

## Impact

- `.github/sync.py`: new `import os`, `UV_PINNED_ENV`, `_graph_launcher()` resolver, `_write_opencode_config()`; `_rebuild_graph()` now routes both `--build` and `--visualize` through the resolver with the pinned env; new OpenCode block in `sync_project()`.
- `.mcp.json` (repo root, copied to projects): `env` block with the two pins.
- `.github/skills/coograph-init/SKILL.md`: question-2 OpenCode bullet, Step 3 For-OpenCode list (four command files, audit plugin, `opencode.json`), Step 6c App-Control note, Step 6e OpenCode config example + merge rule.
- `README.md`: OpenCode row in the tools matrix (and the audit-matrix claim now actually propagates). `.github/code-graph/README.md`: MCP config examples carry the env pins and gained an OpenCode variant. `MIGRATION.md`: 2026-10-05 entry.
- No registered project changes on this PR alone: propagation needs `projects.json` entries (machine-local, gitignored) to list `opencode`, and new `opencode.json` files only land where `code_graph: true`.

## Risks

- **Pinned uv with no system Python** → uv errors ("no Python found") instead of downloading → MCP stays dead until the user drops the pins or builds `.code-graph/venv`. Mitigated: Step 6c + MIGRATION.md document both fallbacks; the resolver's third tier (`plain python`) also stays available.
- **`environment`/`cwd`/relative-path semantics in opencode's own MCP spawn** were verified at shell level (spawn shape reproduced exactly, including `tools/list` against a real `graph.db`) but not yet from a restarted OpenCode session — first-run check after pulling: call `graph_stats` once and confirm it answers from the DB.
- Projects that already had a hand-written `opencode.json` get no generated file (write-if-missing rule) — merge recipe documented in MIGRATION.md.

## Approval

Scope approved by the project owner in-session (2026-10-05) before implementation; the OpenSpec and the implementation ship in one PR, per that approval and the /coograph-verify evidence above.
