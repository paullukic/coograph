---
name: initialize-project
description: Initialize a new project with the Coograph template. Interactive setup that auto-detects the tech stack and fills in all template placeholders.
argument-hint: Target project path (optional — will ask if not provided).
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

Initialize a new project with this Coograph template. Auto-detect the tech stack from the target repo and fill in all template placeholders.

---

## Step 1: Gather Info

Ask the user these questions one at a time (wait for each answer before proceeding):

1. **Target project path** — "What is the full path to the project you want to initialize?" (If provided as argument, use that.)
2. **Which AI tools should I set up for?** (multi-select — accept any combination)
   - **Claude Code** — `CLAUDE.md`, `.claude/commands/`, `.claude/hooks/`, `.claude/settings.json`
   - **VS Code Copilot** — `.github/agents/`, `.github/skills/`, `AGENTS.md`
   - **Codex CLI** — `AGENTS.md` (auto-read; same file as VS Code Copilot)
   - **OpenCode** (sst/opencode) — `AGENTS.md` (auto-read; same file)
   - **Cursor** — `.cursor/rules/coograph.mdc` (from `templates/cursor/`)
   - **Windsurf** — `.windsurfrules` (from `templates/windsurf/`)
   - **Aider** — `CONVENTIONS.md` (from `templates/aider/`)
   - **Cline** — `.clinerules` (from `templates/cline/`)
   - Note: `.github/copilot-instructions.md` and `.github/instructions/` (which contains `brutal-honesty.instructions.md`) are always copied — every tool reads or references them.
3. **Any sections to skip entirely?** (e.g., i18n, API design, data layer) — optional, user can say "none"
4. **Any additional project-specific coding/review rules?**
  - Ask for concise bullets (for example: mandatory architecture patterns, domain invariants, naming restrictions, module boundaries, logging/security constraints).
5. **Enable standalone code-graph?**
   - Options: `yes` (recommended for projects with 10+ files), `no`
   - When enabled a minimal Python MCP server is shipped inside the project at `.github/code-graph/` and wired into the AI tool(s) selected in question 2 — no external package install required beyond `mcp>=1.0.0`.
   - Requires Python 3.10+. `uv` is recommended (auto-installs deps); `pip` works too.
6. **For local-only generated folders, add entries to global git ignore?**
  - Ask this only if Step 1 question 5 is `yes`.
  - Options: `yes`, `no`
  - If `yes`, ask for additional paths (optional). Include `.code-graph/` by default.

## Step 2: Detect Tech Stack

Investigate the TARGET project to auto-detect as much as possible. Read these files if they exist:

- `README.md` — project description, setup instructions, architecture
- `package.json` — Node.js deps, scripts
- `tsconfig.json` / `jsconfig.json` — TypeScript/JS config
- `Cargo.toml` — Rust
- `go.mod` — Go
- `pyproject.toml`, `setup.py`, `requirements.txt` — Python
- `pom.xml`, `build.gradle` — Java/Kotlin
- `Gemfile` — Ruby
- `.eslintrc*`, `.prettierrc*`, `biome.json` — linter/formatter
- `docker-compose.yml`, `Dockerfile` — infrastructure hints
- `Makefile` — build commands
- `src/` directory listing — project structure

Extract:
- **Language** (TypeScript, Python, Rust, Go, Java, etc.)
- **Framework** (React, Next.js, FastAPI, Axum, Spring Boot, etc.)
- **ORM / Data layer** (Prisma, Drizzle, SQLAlchemy, GORM, etc.)
- **Testing** (Jest, Vitest, pytest, go test, JUnit, etc.)
- **Build tool** (Vite, Webpack, esbuild, Cargo, Maven, etc.)
- **Linter/Formatter** (ESLint, Prettier, Biome, Ruff, rustfmt, etc.)
- **Commands** (dev, build, lint, test, format, typecheck)
- **Project structure** (key directories and purpose)
- **i18n** (mechanism if any)
- **API style** (REST, GraphQL, tRPC, etc.)

Present findings in a summary table and ask the user to confirm or correct before proceeding.

## Step 3: Copy Template Files

Copy files from the coograph repo to the target project. Only copy what's relevant to the tools selected in Step 1.

**Always copy (shared conventions used by every tool):**
- `.github/copilot-instructions.md` (CLAUDE.md pre-flight + on-demand reads depend on this)
- `.github/instructions/` (all instruction `.md` files — testing, styling, brutal-honesty)
- `openspec/config.yaml` (create `openspec/` dir if needed)

**For Claude Code:**
- `CLAUDE.md`
- `.claude/commands/project/` (all command files)
- `.claude/commands/coograph/init.md` (the init command itself, so the project can re-init others)
- `.claude/hooks/` (all hook scripts — block-generated, log-bash, report-graph, warn-scope)
- `.claude/settings.json` (wires the hooks into Claude Code lifecycle events)
- Do NOT copy `.claude/settings.local.json` — that's per-machine personal overrides

**For VS Code Copilot, Codex CLI, AND OpenCode** (all auto-read `AGENTS.md`):
- `.github/agents/` (all agent `.md` files — used by VS Code Copilot Chat)
- `.github/skills/` (all skill directories including `initialize-project/` — the target project can use it to initialize other projects later)
- `AGENTS.md`

**For Cursor:**
- `templates/cursor/.cursor/` → target project's `.cursor/` (preserves rules subdirectory structure)

**For Windsurf:**
- `templates/windsurf/.windsurfrules` → target project root `.windsurfrules`

**For Aider:**
- `templates/aider/CONVENTIONS.md` → target project root `CONVENTIONS.md`

**For Cline:**
- `templates/cline/.clinerules` → target project root `.clinerules`

**Multi-tool selections:** copy the union of all selected tool sections plus the always-copy section. Skip duplicate destinations (e.g. `AGENTS.md` is shared between VS Code Copilot and Codex CLI — copy once).

**Do NOT overwrite** existing files without asking. If a file exists, show both versions side by side (existing vs template) and ask the user how to proceed:
- **Overwrite** — replace entirely with the template version
- **Skip** — keep the existing file unchanged
- **Section-by-section** — show each differing section and let the user choose which version to keep for each one

Do NOT attempt automatic merging — the risk of duplicated or corrupted content is too high.

## Step 4: Fill In Placeholders

Using the detected info from Step 2, replace all `_TBD_` placeholders and `<!-- FILL: ... -->` comment blocks in the copied files.

**In `.github/copilot-instructions.md`:**
- Stack table — fill with detected technologies
- Commands table — fill with detected scripts/commands
- Project Structure table — fill with detected paths and purposes
- Code Style sections — fill based on language/framework conventions
- Naming Conventions — fill based on language idioms
- Data Layer, Testing, API Design, i18n, Errors and Logging — fill or delete as appropriate
- Remove `<!-- FILL: ... -->` comments after filling
- Delete sections the user said to skip
- Add user-provided project-specific rules under `## Project-Specific Rules` (create concise bullet points; do not duplicate existing global rules)

**In `CLAUDE.md`:**
- Quick Reference commands table
- Key Paths based on detected structure
- Keep workflow, critical rules, and delegation sections as-is (universal)

**In `AGENTS.md`:**
- Stack one-liner
- Structure summary

## Step 5: Verify

1. Grep target project instruction files for remaining `_TBD_` or `<!-- FILL` markers
2. If any remain, ask the user for the missing info and continue filling until the grep returns zero matches
3. Grep copied agent/skill files for deprecated tool aliases (`AskUserQuestion`, `TodoWrite`, `replace_string_in_file`, `multi_replace_string_in_file`) and replace with runtime-supported names where needed
4. Show a summary of all files created/modified
5. Ask if the user wants to commit the changes

## Step 6: Optional standalone code-graph setup

Run this step only if the user selected `yes` in Step 1 question 5.

### 6a. Copy server files

Copy `.github/code-graph/` from the coograph to the target project.
This includes:
- `builder.py` — parses source files into SQLite
- `server.py`  — MCP server exposing tools to the AI assistant
- `visualize.py` — generates standalone HTML graph visualization
- `parsers/` — per-language parser modules (regex + tree-sitter)
- `package.json` — d3 dependency for visualization
- `requirements.txt` — `mcp>=1.0.0` plus optional tree-sitter language packages
- `post-commit` / `post-merge` / `post-rewrite` — optional git hooks for automatic graph updates

Do NOT copy `node_modules/` — it will be installed in the next step.

### 6b. Install d3 dependency

```bash
cd <target-project>/.github/code-graph && npm install
```

This installs d3 (used by `visualize.py` to generate offline-capable HTML graphs).

### 6c. Ensure `uv` is installed

`uv` is the recommended way to run the MCP server (auto-installs Python deps without polluting the system).

Check availability:
```bash
command -v uv
```

If `uv` is not found, install it automatically:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After install, ensure `~/.local/bin` (or the printed install path) is on `$PATH` for the current session:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

Verify:
```bash
uv --version
```

Do NOT ask the user to install `uv` manually — install it automatically and report the result.
If the install script fails (e.g. no internet, corporate proxy), fall back to `pip install 'mcp>=1.0.0'` and use `python` instead of `uv` in MCP configs.

### 6d. Add `.code-graph/` to `.gitignore`

Append `.code-graph/` to the target project's `.gitignore` if not already present.
Also ensure `node_modules/` is in `.gitignore` (usually already present).
The graph database is local/generated — it must not be committed.

### 6e. Write MCP config(s) based on AI tools chosen in Step 1

By this point `uv` should be installed (step 6c). If step 6c fell back to pip, use `"command": "python"` and `"args": ["${workspaceFolder}/.github/code-graph/server.py"]` in all configs below instead of the `uv` variant.

**VS Code Copilot** → create or merge into `.vscode/mcp.json`:
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

**Claude Code** → create or merge into `.mcp.json` at repo root:
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

**Cursor** → create or merge into `.cursor/mcp.json`:
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

If `Both` was selected in Step 1, write all applicable configs.
Do NOT overwrite existing MCP configs — merge `code-graph` key into the `servers`/`mcpServers` object.

### 6f. Build the initial graph

The `--build` flag does NOT require the `mcp` package. Tree-sitter packages (installed via `requirements.txt`) are used automatically where available and fall back to regex parsers otherwise.
Run in the target project root:
```bash
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build
```

Expected output includes timed progress per phase, ending with:
`Graph built: N files → .code-graph/graph.db (X.XXs)`

If the build fails:
- Check Python 3.10+ is available: `python --version`
- The `--build` path does NOT import MCP — if you see an mcp error, something else is wrong.
- Report the exact error to the user; do not skip.

### 6g. Verify

Confirm `.code-graph/graph.db` exists. Report the file size and build time to the user as confirmation.

### 6h. Install git hooks for automatic updates

Ask the user a **Yes/No** question:
> **Install git hooks?** — "Auto-update the code graph on commit, merge, and rebase?"
> Options: `Yes` (recommended), `No`

If the user selects **No**, skip to 6i.

If the user selects **Yes**:

1. Find the git directory. The target project may be a subfolder in a monorepo:
```bash
GIT_DIR=$(git -C <target-project> rev-parse --git-dir)
```

2. Create the hooks directory if it doesn't exist:
```bash
mkdir -p "$GIT_DIR/hooks"
```

3. Copy and make executable:
```bash
cp <target-project>/.github/code-graph/post-commit "$GIT_DIR/hooks/post-commit"
cp <target-project>/.github/code-graph/post-merge "$GIT_DIR/hooks/post-merge"
cp <target-project>/.github/code-graph/post-rewrite "$GIT_DIR/hooks/post-rewrite"
chmod +x "$GIT_DIR/hooks/post-commit" "$GIT_DIR/hooks/post-merge" "$GIT_DIR/hooks/post-rewrite"
```

Each hook runs:

```bash
uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --update
```

(Falls back to `python .github/code-graph/server.py --update` if uv is unavailable.)

Behavior:
- If `.code-graph/graph.db` does not exist yet, the hook exits silently.
- Hook installation is local only (`.git/hooks/` is not committed), so each developer installs it once.
- `git fetch` alone does not update the graph because it does not change the checked-out files.
- Works in monorepos where `.git/` is above the target project root.

### 6i. Optional global gitignore entries for local-only folders

Run this only if Step 1 question 6 is `yes`.

1. Detect global ignore file path:
```bash
git config --global core.excludesfile
```
2. If empty, default to `~/.config/git/ignore` and set it:
```bash
git config --global core.excludesfile "$HOME/.config/git/ignore"
mkdir -p "$HOME/.config/git"
touch "$HOME/.config/git/ignore"
```
3. Add `.code-graph/` and any user-provided local-only folder entries if missing.
4. Report exactly which entries were added.

## Step 7: Agent references (when code-graph is enabled)

The copied agent files already include a mandatory "Step 0 — Orient with Code-Graph" section with HARD-RULE wording (code-graph first, non-negotiable, only fall back when the DB is genuinely absent).

Verify it is present in the target project by grepping each agent file for the literal string `MANDATORY — non-negotiable`:

```bash
grep -L "MANDATORY — non-negotiable" <target>/.github/agents/*.agent.md
```

Files returned (missing the marker) need the block restored — copy the Step 0 block from the matching file in `coograph/.github/agents/` verbatim. Do not improvise the wording; the literal HARD RULE phrasing is what enforces the rule.

## Step 8: Register in projects.json

Register the target project so future `git pull` updates in coograph auto-propagate.

1. Locate `projects.json` in the coograph root (create with `{"projects": []}` if missing).
2. Check if the target project path is already in the list — if so, update it; if not, append:
   ```json
   {
     "path": "<absolute-path-to-target-project>",
     "tools": ["claude", "vscode"],
     "code_graph": true,
     "registered_at": "YYYY-MM-DD"
   }
   ```
   Set `tools` to match what was selected in Step 1, `code_graph` to match Step 1 question 5, and `registered_at` to today's date.
3. Write the updated `projects.json` back.
4. Run `./setup.sh` in the coograph root to ensure git hooks are configured for auto-sync:
   ```bash
   cd <coograph-path> && ./setup.sh
   ```
   After setup, every `git pull` in coograph will automatically sync updated agents, skills, commands, code-graph files, and `.mcp.json` to all registered projects — and rebuild their graphs if `code_graph: true`.

## Guardrails

- Never guess at commands — if you can't detect them, ask.
- Never invent project structure — read the actual filesystem.
- If the target already has `CLAUDE.md` or `copilot-instructions.md`, warn and ask (merge/overwrite/skip).
- Keep the communication style, implementation workflow, and review role sections intact — those are template features.
- Prefer what the project already does over generic defaults.
- Initialization is complete only when there are zero `_TBD_` and `<!-- FILL` markers in copied instruction files.
- If code-graph setup is enabled, initialization is complete only when `.code-graph/graph.db` exists in the target project and at least one MCP config file has been written.
