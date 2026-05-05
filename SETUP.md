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

## 4. Communication style

`.github/instructions/brutal-honesty.instructions.md` ships with the template. VS Code Copilot loads it automatically (`applyTo: "**"` matches every file). Claude Code reads it via the directive in `CLAUDE.md` § Communication Style at session start.

No manual copy required.

## 5. `/coograph-init` invocation per tool

Every supported tool understands the same `/coograph-init` command, but the registration mechanism differs.

| Tool | Config file (copy to your project) | Autocomplete? |
|---|---|---|
| **Claude Code** | `.claude/commands/coograph-init.md` | yes — appears in `/` menu |
| **VS Code Copilot** | `.github/skills/coograph-init/SKILL.md` | yes — folder name = slash command |
| **Codex CLI** | `.agents/skills/coograph-init/SKILL.md` | yes — Codex scans `.agents/skills/` from repo root |
| **OpenCode** | `.opencode/commands/coograph-init.md` | yes — custom command (plural `commands/` dir) |
| **Cursor** | `.cursor/rules/coograph.mdc` § Invocation | no — type the string, rule fires |
| **Windsurf** | `.windsurfrules` § Invocation | no — type the string, rule fires |
| **Aider** | `CONVENTIONS.md` § Invocation | no — type the string, convention fires |
| **Cline** | `.clinerules` § Invocation | no — type the string, rule fires |

For the four "no autocomplete" tools, just type `/coograph-init` literally in chat. The agent reads its config file, sees the `## Invocation` directive, and runs `.github/skills/coograph-init/SKILL.md`. Paraphrases work too: "initialize the project", "set up coograph", "wire up coograph in this repo".

For Cursor/Windsurf/Aider/Cline you must copy the matching config file from `templates/<tool>/` into your project root before the rule will fire.
