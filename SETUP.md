# Manual Setup

If you prefer not to use the automated initializer, follow these steps.

## 1. Copy files

```bash
TARGET=/path/to/your/project

# Core convention file (required)
cp -r .github/                "$TARGET/.github/"

# Claude Code (if using)
cp CLAUDE.md                  "$TARGET/CLAUDE.md"
cp -r .claude/                "$TARGET/.claude/"

# Cursor / Windsurf (if using)
cp AGENTS.md                  "$TARGET/AGENTS.md"

# OpenSpec workflow (recommended)
cp -r openspec/               "$TARGET/openspec/"
```

Do not copy `.omc/`, `.claude/settings.local.json`, or `.github/code-graph/node_modules/` — these are machine-local.

## 2. Fill placeholders

Open `.github/copilot-instructions.md` and fill every `_TBD_` and `<!-- FILL: ... -->` section:

- **Stack table** — your language, framework, ORM, testing tools
- **Commands table** — dev, build, lint, test, format, typecheck
- **Project Structure** — key directories and their purpose
- **Code Style** — language-specific rules (functions, imports, exports)
- **Naming Conventions** — your project's patterns
- **Data Layer, Testing, API Design, i18n** — fill or delete as appropriate
- **Project-Specific Rules** — domain invariants, module boundaries, naming restrictions

Then fill `CLAUDE.md`:
- **Quick Reference** commands table
- **Key Paths** — your actual source/component/API paths
- **Branching Strategy** — your branch naming convention

And `AGENTS.md`:
- Stack one-liner
- Structure summary

Verification — grep for remaining placeholders:
```bash
grep -r "_TBD_\|<!-- FILL" .github/copilot-instructions.md CLAUDE.md AGENTS.md
```
Zero results = done.

## 3. Code-graph setup (optional but recommended for 10+ file projects)

### Prerequisites

- Python 3.10+
- `uv` (recommended): `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Install and build

```bash
# Install d3 for visualization (one-time)
cd .github/code-graph && npm install && cd -

# Build the initial graph
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build
# Output: .code-graph/graph.db
```

### Add MCP config

**Claude Code** — create `.mcp.json` at your project root:
```json
{
  "mcpServers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp>=1.0.0", ".github/code-graph/server.py"]
    }
  }
}
```

**VS Code Copilot** — create `.vscode/mcp.json`:
```json
{
  "servers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp>=1.0.0", "${workspaceFolder}/.github/code-graph/server.py"]
    }
  }
}
```

**Cursor** — create `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp>=1.0.0", ".github/code-graph/server.py"]
    }
  }
}
```

### Install git hooks (auto-update on commit)

```bash
GIT_DIR=$(git rev-parse --git-dir)
mkdir -p "$GIT_DIR/hooks"
cp .github/code-graph/post-commit  "$GIT_DIR/hooks/post-commit"
cp .github/code-graph/post-merge   "$GIT_DIR/hooks/post-merge"
cp .github/code-graph/post-rewrite "$GIT_DIR/hooks/post-rewrite"
chmod +x "$GIT_DIR/hooks/post-commit" "$GIT_DIR/hooks/post-merge" "$GIT_DIR/hooks/post-rewrite"
```

Each hook runs `uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --update` silently after every commit, merge, and rebase (falls back to `python` if uv is unavailable). If `graph.db` doesn't exist yet, hooks exit silently — safe to install before the first build.

### Add to .gitignore

```
.code-graph/
```

The graph database is generated — never commit it.

## 4. User-level communication style (VS Code, optional)

```bash
# macOS / Linux
cp user/brutal-honesty.instructions.md ~/.config/Code/User/prompts/

# Windows (PowerShell)
Copy-Item user/brutal-honesty.instructions.md "$env:APPDATA/Code/User/prompts/"
```

Sets a global direct/evidence-based communication style across all workspaces. VS Code Settings Sync does not sync the `prompts/` folder — re-copy on each machine.
