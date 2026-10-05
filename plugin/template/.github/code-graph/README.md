# Code Graph

A standalone, zero-dependency code graph builder and MCP server for AI coding assistants.

Parses your repository into a SQLite graph (`.code-graph/graph.db`) that AI tools can query for impact analysis, dependency tracing, and code navigation.

## Requirements

- **Python 3.10+**
- **`mcp>=1.0.0,<2`** (MCP server only — not needed for `--build`/`--update`; SDK 2.x renamed `mcp.server.fastmcp` and is not supported yet)
- **`uv`** (recommended — auto-installs dependencies)
- **`tree-sitter` + language packages** (optional but recommended — see `requirements.txt` for the full list; uninstalled languages fall back to regex parsers automatically)

## Quick Start

### Build the graph

From your **project root**:

```bash
uv run -p ">=3.10" --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build
```

This parses all source files and writes `.code-graph/graph.db`.

### Update incrementally

After editing files, update only what changed:

```bash
uv run -p ">=3.10" --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --update
```

Uses SHA-1 content hashes to detect changes. Also re-parses files that import from changed files so cross-file edges stay accurate. If `graph.db` doesn't exist yet, falls back to a full build.

### Visualize

Generate a standalone HTML graph visualization:

```bash
uv run -p ">=3.10" --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --visualize
```

Outputs `.code-graph/graph.html`. Requires `node_modules/` (run `npm install` in this directory first).

### Start the MCP server

```bash
# With uv (recommended — auto-installs all dependencies):
uv run -p ">=3.10" --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py

# With pip:
pip install "mcp>=1.0.0,<2"
python .github/code-graph/server.py

# On Windows machines where Smart App Control / Application Control blocks
# uv-managed Python builds (every start dies with "DLL load failed while
# importing _overlapped"), pin uv onto a system Python install first:
$env:UV_NO_MANAGED_PYTHON="1"; $env:UV_PYTHON_DOWNLOADS="never"   # PowerShell
# export UV_NO_MANAGED_PYTHON=1 UV_PYTHON_DOWNLOADS=never           # bash/WSL
uv run -p ">=3.10" --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py

# Or skip uv entirely with a system-Python venv:
# python -m venv .code-graph/venv
# .code-graph/venv/Scripts/python .github/code-graph/server.py   (after pip install -r requirements.txt)
```

## MCP Configuration

### VS Code Copilot (`.vscode/mcp.json`)

```json
{
  "servers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "-p", ">=3.10", "--with-requirements", "${workspaceFolder}/.github/code-graph/requirements.txt", "${workspaceFolder}/.github/code-graph/server.py"],
      "env": { "UV_NO_MANAGED_PYTHON": "1", "UV_PYTHON_DOWNLOADS": "never" }
    }
  }
}
```

### Claude Code (`.mcp.json` at repo root)

```json
{
  "mcpServers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "-p", ">=3.10", "--with-requirements", ".github/code-graph/requirements.txt", ".github/code-graph/server.py"],
      "env": { "UV_NO_MANAGED_PYTHON": "1", "UV_PYTHON_DOWNLOADS": "never" }
    }
  }
}
```

### OpenCode (`opencode.json` in the workspace root)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": { "paths": [".github/skills"] },
  "mcp": {
    "code-graph": {
      "type": "local",
      "command": ["uv", "run", "-p", ">=3.10", "--with-requirements", ".github/code-graph/requirements.txt", ".github/code-graph/server.py"],
      "cwd": ".",
      "enabled": true,
      "timeout": 120000,
      "environment": { "UV_NO_MANAGED_PYTHON": "1", "UV_PYTHON_DOWNLOADS": "never" }
    }
  }
}
```

The `env`/`environment` pins keep uv on a system Python install where the machine's
application-control policy blocks uv-managed Python builds; drop them if `uv run`
works unmodified on your machine (see Requirements above). Keep `-p ">=3.10"` either way: a range, so uv takes any system Python new enough for `mcp`, where an exact version would fail under the pins on a machine without that exact system install. `timeout` matters for
OpenCode — `build_graph`/`update_graph` exceed its 5-second MCP default.

## MCP Tools

| Tool | Description |
|------|-------------|
| `build_graph` | Full rebuild of the graph |
| `update_graph` | Incremental update (changed files only) |
| `graph_stats` | Node/edge/file/function/test-file counts + DB path |
| `detect_changes` | Find changed files vs a git ref, with per-file risk scores |
| `get_impact_radius` | Blast radius analysis for a set of files, with per-file BFS distance |
| `get_review_context` | Ranked review file set with token estimates; optional `budget_tokens` cap |
| `query_graph` | Flexible queries: importers, dependencies, calls, tests |
| `get_minimal_context` | **Call first.** Resolves the symbols named in the task and returns `files_to_read` (defining files, their dependencies, then one tier of dependents; max 6) plus graph health and the next tool to use. Empty list always carries a `files_reason` |
| `find_large_functions` | Find functions/methods exceeding a line threshold |
| `visualize_graph` | Generate HTML visualization |

## Supported Stacks

Python, React/Next.js, Angular, Vue, Svelte, Java/Kotlin/Scala, C#/F# (.NET), Go, Rust, PHP/Laravel, Ruby/Rails, Swift, Dart/Flutter, CSS/SCSS/LESS.

Stack detection is automatic — the builder reads `pom.xml`, `package.json`, `go.mod`, `Cargo.toml`, etc.

## Git Hooks (optional)

Auto-update the graph on commit/merge/rebase:

```bash
GIT_DIR=$(git rev-parse --git-dir)
cp .github/code-graph/post-commit "$GIT_DIR/hooks/post-commit"
cp .github/code-graph/post-merge "$GIT_DIR/hooks/post-merge"
cp .github/code-graph/post-rewrite "$GIT_DIR/hooks/post-rewrite"
chmod +x "$GIT_DIR/hooks/post-commit" "$GIT_DIR/hooks/post-merge" "$GIT_DIR/hooks/post-rewrite"
```

Hooks run `--update` silently. If `graph.db` doesn't exist, they exit without error.

## Graph Schema

```
nodes: id, kind (file|function|method|class), name, file, start_line, end_line
edges: src, dst, kind (imports|contains|calls|tests_for)
meta:  key, value (root, files_parsed, stacks)
file_hashes: file, sha1 (for incremental updates)
```

## Files

| File | Purpose |
|------|---------|
| `builder.py` | Parser engine — walks repo, builds SQLite graph |
| `server.py` | MCP server + CLI entry point (`--build`, `--update`, `--visualize`) |
| `visualize.py` | HTML graph generator (uses d3 from `node_modules/`) |
| `parsers/` | Per-language parser modules |
| `post-commit` | Git hook template for auto-update |

## Notes

- `.code-graph/` is generated and should be in `.gitignore`.
- `builder.py` is a library — use `server.py --build` as the CLI entry point, not `python builder.py` directly.
- The `--build` and `--update` flags do **not** require the `mcp` package.
- Tree-sitter language packages are optional — uninstalled languages fall back to regex parsers automatically. Install via `pip install -r requirements.txt` or `uv pip install -r requirements.txt`.
