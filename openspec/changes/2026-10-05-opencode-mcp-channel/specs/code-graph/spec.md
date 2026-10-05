# Spec: resolve a working code-graph launcher per machine and register it for OpenCode

## Requirements

- `sync.py` resolves exactly one launcher for running `server.py` inside a project: an existing `.code-graph/venv` interpreter (Windows `Scripts/python.exe` / POSIX `bin/python`) → `uv run --with-requirements` with `UV_NO_MANAGED_PYTHON=1` and `UV_PYTHON_DOWNLOADS=never` pinned into the child environment → a plain `python`/`sys.executable` fallback.
- The on-pull graph rebuild (`--build`) and visualizer (`--visualize`) runs execute through that same resolution, with the pinned environment passed to `subprocess.run(env=...)`.
- The repo-root `.mcp.json` template carries the two `UV_*` pins in its `env` block, and the generated `opencode.json` carries them under `mcp.code-graph.environment`.
- When a registered project lists `opencode` in `tools` **and** `code_graph` is true, `sync.py` writes `opencode.json` at the project root — only if the file is missing — containing `skills.paths: [".github/skills"]` and an `mcp.code-graph` entry with `type: "local"`, the resolved `command` (absolute paths), `cwd: "."`, `enabled: true`, `timeout: 120000`, and `environment` with the uv pins when (and only when) uv was chosen.
- `coograph-init` Step 6e documents the OpenCode variant with the same fields and the same resolution priority, so init and sync write the same shape.
- OpenCode-only registered projects additionally receive `.opencode/commands/coograph-*.md` (four files) and `.opencode/plugin/log-bash.ts`.

## Scenarios

### Scenario: locked-down Windows without a system-Python venv
- **Given**: a registered project where uv exists but every uv-managed/per-user Python build has its `_overlapped.pyd` blocked by Application Control, and no `.code-graph/venv`
- **When**: `git pull` in coograph fires `sync.py`
- **Then**: the rebuild command runs uv with `UV_NO_MANAGED_PYTHON=1` and `UV_PYTHON_DOWNLOADS=never` pinned, uv builds its env on a system Python install, and `server.py --build` completes (instead of dying at `import mcp.server.fastmcp`)

### Scenario: generated opencode.json launches a live server
- **Given**: a synthetic project synced with `tools: ["opencode"]`, `code_graph: true`
- **When**: its generated `opencode.json` `mcp.code-graph.command`/`cwd`/`environment` are executed verbatim
- **Then**: the MCP server starts, answers `initialize` and `tools/list`, and lists `graph_stats` — i.e. the OpenCode-equivalent config is functional, not merely present

### Scenario: existing opencode.json is never rewritten
- **Given**: a registered OpenCode project whose `opencode.json` already exists (provider settings or an earlier init write)
- **When**: `sync.py` runs again
- **Then**: the file is byte-for-byte untouched

### Scenario: WSL project gets no generated config
- **Given**: a registered project whose path is a `\\wsl.localhost\…` path
- **When**: `sync.py` syncs it
- **Then**: no `opencode.json` is written (OpenCode inside WSL gets a hand-written file with native paths; sync must not bake a Windows interpreter into it)

### Scenario: multi-tool project keeps working
- **Given**: a registered project with `tools: ["claude", "opencode"]`, `code_graph: true`
- **When**: `git pull` re-syncs
- **Then**: Claude still receives `.mcp.json` + `.claude/hooks` + `settings.json`, and OpenCode additionally receives `opencode.json`, `.opencode/commands`, and `.opencode/plugin/log-bash.ts`
