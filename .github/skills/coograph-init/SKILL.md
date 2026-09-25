---
name: coograph-init
description: Initialize a new project with the Coograph template. Interactive setup that auto-detects the tech stack and fills in all template placeholders.
argument-hint: Target project path (optional — will ask if not provided).
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

Initialize a new project with this Coograph template. Auto-detect the tech stack from the target repo and fill in all template placeholders.

## Template source

Every "copy" instruction below copies from the **template root**. Resolve it once, before Step 1:

- **Repo mode** — this file is at `<coograph>/.github/skills/coograph-init/SKILL.md` inside a coograph checkout. Template root = `<coograph>`.
- **Plugin mode** — this file is at `<plugin>/skills/coograph-init/SKILL.md` and `<plugin>/template/` exists (Claude Code or Cowork plugin install). Template root = `<plugin>/template/`. There is no coograph checkout and no `projects.json`: detect install state from files on disk and skip Step 8. Marketplace **Update** refreshes only the plugin's own skills, agents, and hooks; files this procedure copies into the project do not auto-update, so tell the user to re-run init to refresh them.
- **Initialized-project mode** — this file is at `<project>/.github/skills/coograph-init/SKILL.md` in a project that was itself initialized (no `templates/` or `setup.sh` next to it). Template root = `<project>`. Per-tool files under `templates/` (Cursor, Devin Desktop, Aider, Cline) are unavailable here: if the user selects one of those tools, say so and point them to the plugin or a coograph checkout. Skip Step 8.

The template root mirrors the coograph repo layout (`.github/…`, `.claude/…`, `templates/…`), so every path below resolves the same way in every mode.

---

## Step 1: Gather Info

Ask the user these questions one at a time (wait for each answer before proceeding):

1. **Target project path** — "What is the full path to the project you want to initialize?" (If provided as argument, use that.)
2. **Which AI tools should I set up for?** (multi-select — accept any combination)
   - **Claude Code** — `CLAUDE.md`, `.claude/commands/`, `.claude/hooks/`, `.claude/settings.json`
   - **VS Code Copilot** — `.github/agents/`, `.github/skills/`, `AGENTS.md`
   - **Codex CLI** — `.agents/skills/coograph-init/SKILL.md` + `AGENTS.md` (Codex scans `.agents/skills/` from repo root for native slash)
   - **OpenCode** (sst/opencode) — `.opencode/commands/coograph-init.md` + `AGENTS.md` (native `/coograph-init` slash)
   - **Cursor** — `.cursor/rules/coograph.mdc` (from `templates/cursor/`)
   - **Devin Desktop** — `.windsurfrules` (from `templates/windsurf/`)
   - **Aider** — `CONVENTIONS.md` (from `templates/aider/`)
   - **Cline** — `.clinerules` (from `templates/cline/`)
   - Note: `.github/copilot-instructions.md` and `.github/instructions/` (which contains `brutal-honesty.instructions.md`) are always copied — every tool reads or references them.
3. **Any sections to skip entirely?** (e.g., i18n, API design, data layer) — optional, user can say "none"
4. **Any additional project-specific coding/review rules?**
  - Ask for concise bullets (for example: mandatory architecture patterns, domain invariants, naming restrictions, module boundaries, logging/security constraints).
5. **Enable standalone code-graph?**
   - Options: `yes` (recommended for projects with 10+ files), `no`
   - When enabled a minimal Python MCP server is shipped inside the project at `.github/code-graph/` and wired into the AI tool(s) selected in question 2 — no external package install required beyond `mcp>=1.0.0,<2`.
   - Requires Python 3.10+. `uv` is recommended (auto-installs deps); `pip` works too.
6. **For local-only generated folders, add entries to global git ignore?**
  - Ask this only if Step 1 question 5 is `yes`.
  - Options: `yes`, `no`
  - If `yes`, ask for additional paths (optional). Include `.code-graph/` by default.
7. **Enable Retro (self-tuning guardrails)?**
   - Options: `yes` (recommended), `no`
   - Explain in two lines: "Retro records when the agent breaks a project rule (grep before the code graph, edits outside the approved change, hand-edits to generated files, new dependencies) and what each session costs in tokens, then proposes fixes to the instruction files and hooks as an OpenSpec you approve. It stores tool names, counts, and paths only; no prompt text, code, or output, and nothing leaves the machine."
   - Capture needs Claude Code (transcripts and lifecycle hooks). Other tools get the analyzer and the `/coograph-retro` skill, but no capture. Say this if Claude Code was not selected in question 2.

## Step 1b: Detect Install State (idempotent re-init)

Before copying or filling anything, classify the target so a second run never
clobbers customized files. Run this immediately after the target path is known.

**Build the "expected files" set:**
- If the target is registered in the coograph `projects.json`, take its `tools` +
  `code_graph` entry and expand to the files those tools own (the per-tool lists in
  Step 3 plus the always-copy block).
- If the target is NOT in `projects.json`, derive the set from which coograph files
  already exist on disk (whatever is present defines what "complete" means here).
- Never hard-fail on a missing or stale `projects.json` — fall back to disk detection.

**Per-file signal** (the `_TBD_` / `<!-- FILL` markers are the only "customized vs
template" signal — reuse the same invariant Steps 4, 5 and the Guardrails key off):
- exists + contains `_TBD_` or `<!-- FILL` → **template-untouched** (safe to refill).
- exists + zero markers → **customized** (do NOT overwrite without explicit "yes
  overwrite").
- exists + *some* markers but clearly user-edited elsewhere → treat as **customized**;
  surface it for an explicit decision, never auto-refill.
- missing → **copy fresh**.

**Classify into one state:**
- **State A — fresh**: none of the expected coograph files exist.
  → Full init flow, unchanged. Proceed normally through Steps 2–10.
- **State B — partial**: some expected files exist, some are missing.
  → Copy ONLY the missing files (Step 3). Do not modify any existing file unless the
    user explicitly confirms overwrite for that specific file.
- **State C — initialized + customized**: all expected files exist with zero
  `_TBD_` / `<!-- FILL` markers.
  → Update mode. Only patch tool-config files for tools newly selected in Q2 that are
    not yet installed. Never touch instruction files (`.github/copilot-instructions.md`,
    `CLAUDE.md`, `AGENTS.md`, `openspec/config.yaml`). Skip Step 2 (stack detection) and
    Step 4 (placeholder fill) entirely — see the State-C guards in those steps.

**Template-managed files are exempt from the B and C restrictions.** Files that
users never customize and that `sync.py` overwrites on every pull are copied
whenever they are missing, in every state: `.github/skills/`, `.github/agents/`,
`.claude/commands/coograph-*.md`, `.claude/hooks/`, `.claude/settings.json`, and
`.github/retro/` (without `rules.json`). This is how a project initialized before a
template feature existed (for example Retro) receives it on re-init. Step 10 then
runs when the user enabled Retro in question 7 and `.github/retro/rules.json` is
absent.

State the detected state to the user before proceeding (e.g. "State C — already
initialized; entering update mode, instruction files will not be touched").

## Step 2: Detect Tech Stack

> **State C skip:** if Step 1b classified the target as State C (initialized +
> customized), skip this entire step — the instruction files are already filled and
> will not be touched. Stack detection only feeds placeholder filling (Step 4), which
> State C also skips.

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

Copy files from the template root (see Template source) to the target project. Only copy what's relevant to the tools selected in Step 1.

**Always copy (shared conventions used by every tool):**
- `.github/copilot-instructions.md` (CLAUDE.md pre-flight + on-demand reads depend on this)
- `.github/instructions/` (all instruction `.md` files — testing, styling, brutal-honesty)
- `.github/skills/` (all skill directories — every supported tool delegates here, including the Claude Code command wrappers in `.claude/commands/` and the multi-tool slash registrations under `templates/`)
- `openspec/config.yaml` (create `openspec/` dir if needed)
- `.github/retro/` (`retro.py`, `_coograph_signals.py`, `rules.seed.json`, `README.md`; never `tests/`, never `rules.json`). Always, whatever the answer to Step 1 question 7: the analyzer and the `/coograph-retro` skill must be able to bootstrap later. Only when question 7 is `yes`, also create the live registry: `cd <target> && python3 .github/retro/retro.py --merge-seed` (creates `rules.json` from `rules.seed.json`, or adds new seeded rules to an existing one without touching local edits). Never copy `rules.json` from the template root; it is the coograph repo's own live registry.

**For Claude Code:**
- `CLAUDE.md`
- `.claude/commands/coograph-*.md` (every Coograph slash command: `/coograph-init` itself, so the project can re-init others, plus `/coograph-new-ticket`, `/coograph-plan`, `/coograph-review`, `/coograph-ultra-review`, `/coograph-verify`, `/coograph-debug`, `/coograph-search`, `/coograph-retro`, which the copied `CLAUDE.md` references)
- `.claude/hooks/` (all hook scripts: block-generated, log-bash, report-graph, warn-scope, capture-signals, plus the shared `_coograph_guard.py` module and the `_coograph_signals.py` shim that loads `.github/retro/_coograph_signals.py`)
- `.claude/settings.json` (wires the hooks into Claude Code lifecycle events)
- Do NOT copy `.claude/settings.local.json` — that's per-machine personal overrides

**For VS Code Copilot:**
- `.github/agents/` (all agent `.md` files — used by VS Code Copilot Chat)
- `AGENTS.md`
- (`.github/skills/` is in the always-copy block above — VS Code Copilot consumes it but does not need a tool-specific copy directive)

**For Codex CLI:**
- `.agents/skills/coograph-init/SKILL.md` (Codex scans `.agents/skills/` from repo root and surfaces it as the `/coograph-init` slash)
- `AGENTS.md` (auto-read by Codex CLI; same file as VS Code Copilot — copy once)
- (delegates to `.github/skills/coograph-init/` — already supplied by the always-copy block)

**For OpenCode:**
- `.opencode/commands/coograph-init.md` (registers `/coograph-init` slash in OpenCode — note the plural `commands/`)
- `.opencode/commands/coograph-retro.md` (registers `/coograph-retro`)
- `AGENTS.md` (auto-read by OpenCode; same file as VS Code Copilot — copy once)
- (delegates to `.github/skills/coograph-init/` — already supplied by the always-copy block)

**For Cursor:**
- `templates/cursor/.cursor/` → target project's `.cursor/` (preserves rules subdirectory structure)
- Cursor has no native slash registration; the `coograph.mdc` rule tells the agent to follow `.github/skills/coograph-init/SKILL.md` whenever the user types `/coograph-init` (skills directory already supplied by the always-copy block).

**For Devin Desktop:**
- `templates/windsurf/.windsurfrules` → target project root `.windsurfrules`
- Devin Desktop (formerly Windsurf) has no native slash registration; the rule fires when the user types `/coograph-init` (skills directory already supplied by the always-copy block).

**For Aider:**
- `templates/aider/CONVENTIONS.md` → target project root `CONVENTIONS.md`
- Aider has no native slash registration; the convention fires when the user types `/coograph-init` (skills directory already supplied by the always-copy block).

**For Cline:**
- `templates/cline/.clinerules` → target project root `.clinerules`
- Cline has no native slash registration; the rule fires when the user types `/coograph-init` (skills directory already supplied by the always-copy block).

**Multi-tool selections:** copy the union of all selected tool sections plus the always-copy section. Skip duplicate destinations (e.g. `AGENTS.md` is shared between VS Code Copilot, Codex CLI, and OpenCode — copy once). `.github/skills/` is in the always-copy block; do not re-copy it from per-tool selections.

**Apply the Step 1b state before any copy** — decide per file, not with one
project-wide prompt:

- **State A (fresh):** copy everything per the selections (no existing files to guard).
- **State B (partial):** copy ONLY the **missing** files. For files that already exist,
  do not touch them unless the user explicitly says "yes overwrite" for that file.
- **State C (initialized + customized):** write ONLY tool-config files for tools newly
  selected in Q2 that are not already installed (e.g. user adds Codex CLI to a
  Claude-Code-only project). Never write instruction files
  (`.github/copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md`, `openspec/config.yaml`).
- **Every state:** template-managed files listed in Step 1b (skills, agents,
  `coograph-*` command wrappers, hooks, `settings.json`, `.github/retro/` without
  `rules.json`) are copied when missing. They are never user-customized, and
  `sync.py` overwrites them on every pull anyway.

**Per-file overwrite safety** (applies in every state): use the Step 1b signal.
- A **customized** file (exists, zero markers) SHALL NOT be overwritten without an
  explicit "yes overwrite" confirmation for that file.
- A **template-untouched** file (exists, has `_TBD_` / `<!-- FILL`) may be refilled
  normally.
- A **partially edited** file (some markers, user edits elsewhere) is treated as
  customized — surface it and ask; never auto-refill.

**When you do ask** (customized file the user might want replaced), show both versions
side by side (existing vs template) and offer:
- **Overwrite** — replace entirely with the template version
- **Skip** — keep the existing file unchanged
- **Section-by-section** — show each differing section and let the user choose which version to keep for each one

Do NOT attempt automatic merging — the risk of duplicated or corrupted content is too high.

## Step 4: Fill In Placeholders

> **State C skip:** if Step 1b classified the target as State C, skip this entire step.
> All instruction files are already filled (zero markers by definition) and must not be
> touched. Only the tool-config files written in Step 3 apply in update mode.
>
> **State B note:** fill placeholders only in files that were freshly copied in Step 3.
> Existing customized files are never refilled.

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

Copy `.github/code-graph/` from the template root to the target project.
This includes:
- `builder.py` — parses source files into SQLite
- `server.py`  — MCP server exposing tools to the AI assistant
- `visualize.py` — generates standalone HTML graph visualization
- `parsers/` — per-language parser modules (regex + tree-sitter)
- `package.json` — d3 dependency for visualization
- `requirements.txt` — `mcp>=1.0.0,<2` plus optional tree-sitter language packages
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
If the install script fails (e.g. no internet, corporate proxy), fall back to `pip install 'mcp>=1.0.0,<2'` and use `python` instead of `uv` in MCP configs.

**Pin the interpreter.** `uv run` resolves against the machine's *default* Python, not
the newest one installed. `mcp>=1.0.0,<2` requires Python 3.10+, so on a machine whose
default is older the server dies at start-up with
`your requirements are unsatisfiable` — and the MCP host reports only
`CONNECTION_CLOSED`, with the real cause buried in the server log.

Check the default:
```bash
python --version
```

If it is below 3.10, every `uv run` invocation this procedure writes or runs — the MCP
configs in 6e, the git hooks in 6h, and the build command in 6f — must carry an explicit
`-p <version>` pin immediately after `run` (`uv` downloads a managed interpreter on
demand, so no manual install is needed):
```bash
uv run -p 3.12 --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build
```
Report the pin to the user, since it has to stay in the committed config.

### 6d. Add `.code-graph/` to `.gitignore`

Append `.code-graph/` to the target project's `.gitignore` if not already present.
Also ensure `node_modules/` is in `.gitignore` (usually already present).
The graph database is local/generated — it must not be committed.

### 6e. Write MCP config(s) based on AI tools chosen in Step 1

By this point `uv` should be installed (step 6c). If step 6c fell back to pip, use `"command": "python"` and `"args": ["${workspaceFolder}/.github/code-graph/server.py"]` in all configs below instead of the `uv` variant.

The configs below carry the `-p 3.12` interpreter pin from step 6c. Drop it only when the machine's default `python` is already 3.10 or newer; keeping it is harmless either way.

**VS Code Copilot** → create or merge into `.vscode/mcp.json`:
```json
{
  "servers": {
    "code-graph": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "-p", "3.12", "--with-requirements", "${workspaceFolder}/.github/code-graph/requirements.txt", "${workspaceFolder}/.github/code-graph/server.py"]
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
      "args": ["run", "-p", "3.12", "--with-requirements", ".github/code-graph/requirements.txt", ".github/code-graph/server.py"]
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
      "args": ["run", "-p", "3.12", "--with-requirements", ".github/code-graph/requirements.txt", ".github/code-graph/server.py"]
    }
  }
}
```

If `Both` was selected in Step 1, write all applicable configs.
Do NOT overwrite existing MCP configs — merge the `code-graph` key into the `servers`/`mcpServers` object and leave every other key alone. `sync.py` follows the same rule on later pulls, so a hand-edited config survives.

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

Files returned (missing the marker) need the block restored — copy the Step 0 block from the matching file in `<template root>/.github/agents/` verbatim. Do not improvise the wording; the literal HARD RULE phrasing is what enforces the rule.

## Step 8: Register in projects.json (repo mode only)

Skip this step in plugin mode and initialized-project mode (see Template source) — there is no coograph checkout to register with.

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

## Step 9: Code-graph health check (only if code-graph enabled)

Run this step only if the user selected `yes` in Step 1 question 5. Skip if `.code-graph/graph.db` does not exist (the build in Step 6f failed earlier — surface that instead).

### 9a. Sanity-check the graph

Run these queries against the target project's `.code-graph/graph.db` and collect the results:

```bash
sqlite3 .code-graph/graph.db "SELECT COUNT(*) FROM nodes;"
sqlite3 .code-graph/graph.db "SELECT COUNT(*) FROM edges;"
sqlite3 .code-graph/graph.db "SELECT COUNT(DISTINCT file) FROM nodes;"
sqlite3 .code-graph/graph.db "SELECT kind, COUNT(*) FROM nodes GROUP BY kind ORDER BY COUNT(*) DESC LIMIT 5;"
```

Compare to expectations based on the source tree (Step 2 detection):

- **Source files on disk** (count: `find src/ -type f -name '*.<ext>' | wc -l` or equivalent for the detected language)
- **Distinct `file` values in graph** (from query above)

### 9b. Detect issues

Flag the graph as suspect if ANY of these are true:

- `nodes` count is 0 or "unrealistically low" (< 50% of source files for projects with 20+ files)
- `edges` count is 0 (parser produced symbols but no relationships — likely a parser fallback issue)
- Distinct `file` count is < 80% of detected source files (parser silently skipped files)
- Top `kind` values are missing expected categories for the language (e.g. Python project with zero `function` or `class` nodes)
- `graph.db` size is < 10kb (likely empty schema, no real content)

### 9c. Report and offer to fix

If the graph looks healthy, output a one-line summary:

```
[code-graph] healthy — N nodes, M edges, K files indexed.
```

If the graph looks suspect, output a structured report:

```
[code-graph] possible issues:
  - <issue 1, e.g. "only 12 of 47 source files indexed (26%)">
  - <issue 2, e.g. "0 edges — relationships may be missing">

The graph may not be returning useful results. Want me to try fixing it?
  (a) Yes — rebuild from scratch and try alternate parsers where available
  (b) No — leave as-is, I'll investigate manually
```

Wait for the user's choice. Do not auto-fix.

### 9d. If user chose (a) — fix attempt

1. Delete `.code-graph/graph.db` and any stale parser caches.
2. Rebuild with verbose output:
   ```bash
   uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build --verbose
   ```
3. Capture parser warnings/errors into a summary.
4. Re-run the sanity queries from 9a.
5. If the graph still looks suspect, hand off to the user with the verbose log:
   ```
   [code-graph] rebuild did not resolve all issues. See log above.
   Likely causes: tree-sitter language pack missing, source files using a dialect/version
   not supported by the fallback parsers, or symlinks/large generated files inflating counts.
   Open an issue at github.com/paullukic/coograph if you want help.
   ```
6. If healthy, output the success line from 9c and continue.

## Step 10: Retro first run (only if Retro enabled)

Run this step only if the user selected `yes` in Step 1 question 7.

### 10a. Verify the files landed

`<target>/.github/retro/rules.json`, `rules.seed.json`, `retro.py`, `_coograph_signals.py`, and `README.md` exist. If Claude Code was selected, `<target>/.claude/hooks/capture-signals.py` and the `_coograph_signals.py` shim exist and `<target>/.claude/settings.json` wires `capture-signals.py` under both `SessionStart` and `SessionEnd`. Run:

```bash
cd <target> && python3 .github/retro/retro.py --validate
```

It must print `retro: rules.json valid`.

### 10b. Backfill from existing transcripts (Claude Code only)

Claude Code keeps every transcript for the project under `~/.claude/projects/<slug>/`, where `<slug>` is the absolute target path with every character outside `A-Z a-z 0-9` replaced by `-`:

| OS | example path | slug |
|---|---|---|
| Windows | `C:\paul\code\app` | `C--paul-code-app` |
| macOS / Linux | `/home/paul/app` | `-home-paul-app` |

Work out the directory and count its `*.jsonl` files. If it does not exist or is empty, say so and skip to 10c. Otherwise ask a Yes/No question:

> **Backfill Retro from existing transcripts?** "Found <N> Claude Code transcripts for this project at `<path>`. Retro stores tool names, counts, rule ids, file paths, and token totals only; no prompt text, code, or output. Read them now?"

On yes:

```bash
cd <target> && python3 .claude/hooks/capture-signals.py --backfill "<path>" --cwd .
```

Report the printed `captured / skipped / failed` line verbatim.

### 10c. First report

```bash
cd <target> && python3 .github/retro/retro.py --report
```

Show the user the first paragraph it prints (the plain-language opener) and the path to `report.md`. If nothing was captured, the opener says so; that is fine. Tell the user: "From now on every Claude Code session start prints a `[retro]` line, and `/coograph-retro` turns the report into proposals when there is enough evidence."

## Guardrails

- Never guess at commands — if you can't detect them, ask.
- Never invent project structure — read the actual filesystem.
- If the target already has `CLAUDE.md` or `copilot-instructions.md`, warn and ask (merge/overwrite/skip).
- Keep the communication style, implementation workflow, and review role sections intact — those are template features.
- Prefer what the project already does over generic defaults.
- Initialization is complete only when there are zero `_TBD_` and `<!-- FILL` markers in copied instruction files.
- If code-graph setup is enabled, initialization is complete only when `.code-graph/graph.db` exists in the target project, at least one MCP config file has been written, AND Step 9 health check has run (either reporting healthy or finishing the user-chosen fix path).
- If Retro is enabled, initialization is complete only when `retro.py --validate` passed and Step 10c printed a report opener.
