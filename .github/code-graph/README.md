# Code Graph

A standalone, zero-dependency code graph builder and MCP server for AI coding assistants.

Parses your repository into a SQLite graph (`.code-graph/graph.db`) that AI tools can query for impact analysis, dependency tracing, and code navigation.

## Requirements

- **Python 3.10+**
- **`mcp>=1.0.0`** (MCP server only — not needed for `--build`/`--update`)
- **`uv`** (recommended — auto-installs dependencies)
- **`tree-sitter` + language packages** (optional but recommended — see `requirements.txt` for the full list; uninstalled languages fall back to regex parsers automatically)

## Quick Start

### Build the graph

From your **project root**:

```bash
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build
```

This parses all source files and writes `.code-graph/graph.db`.

### Update incrementally

After editing files, update only what changed:

```bash
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --update
```

Uses SHA-1 content hashes to detect changes. Also re-parses files that import from changed files so cross-file edges stay accurate. If `graph.db` doesn't exist yet, falls back to a full build.

### Visualize

Generate a standalone HTML graph visualization:

```bash
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --visualize
```

Outputs `.code-graph/graph.html`. Requires `node_modules/` (run `npm install` in this directory first).

### Start the MCP server

```bash
# With uv (recommended — auto-installs all dependencies):
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py

# With pip:
pip install "mcp>=1.0.0"
python .github/code-graph/server.py
```

## MCP Configuration

### VS Code Copilot (`.vscode/mcp.json`)

```json
{
  "servers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with-requirements", "${workspaceFolder}/.github/code-graph/requirements.txt", "${workspaceFolder}/.github/code-graph/server.py"]
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
      "args": ["run", "--with-requirements", ".github/code-graph/requirements.txt", ".github/code-graph/server.py"]
    }
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `build_graph` | Full rebuild of the graph |
| `update_graph` | Incremental update (changed files only) |
| `graph_stats` | Node/edge counts, stacks, top-connected files |
| `detect_changes` | Find changed files vs a git ref |
| `get_impact_radius` | Blast radius analysis for a set of files |
| `get_review_context` | Focused file set + risk scores for code review |
| `query_graph` | Flexible queries: importers, dependencies, calls, tests |
| `get_minimal_context` | Quick health check + task-relevant risk assessment |
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
