Initialize a new project with this Coograph template. Interactive setup that auto-detects the tech stack and fills all placeholders.

The full procedure is in `.github/skills/coograph-init/SKILL.md`. Follow those steps exactly, with these Claude Code-specific substitutions:

| SKILL.md tool | Claude Code equivalent |
|---------------|----------------------|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `manage_todo_list` | Use task tracking internally |
| `apply_patch` / `create_file` | Use Edit / Write tools |
| `read_file` | Use Read tool |
| `grep_search` | Use Grep tool |

## Steps (summary)

1. **Gather info** — Ask the user: target project path, which AI tools to set up (Claude Code / VS Code Copilot / both), sections to skip, project-specific rules, whether to enable code-graph, and whether to add global gitignore entries.

2. **Detect tech stack** — Read the target project's manifest files (package.json, pom.xml, go.mod, Cargo.toml, pyproject.toml, tsconfig.json, etc.) and `src/` structure. Extract language, framework, ORM, testing, build tool, linter, commands, and project structure. Present findings and ask the user to confirm before proceeding.

3. **Copy template files** — Copy only what's relevant to the selected tools:
   - Claude Code: `CLAUDE.md`, `.claude/commands/project/` (all except `initialize.md`), `.claude/hooks/` (all scripts), `.claude/settings.json`
   - VS Code Copilot: `.github/agents/`, `.github/skills/`, `.github/prompts/`, `AGENTS.md`
   - Always (shared by both tools): `.github/copilot-instructions.md`, `.github/instructions/`, `openspec/config.yaml`
   - Do NOT copy `node_modules/`, `.omc/`, or `.claude/settings.local.json`
   - Ask before overwriting any existing file (overwrite / skip / section-by-section)

4. **Fill placeholders** — Replace all `_TBD_` and `<!-- FILL: ... -->` markers using the detected stack info. Delete sections the user said to skip. Add project-specific rules.

5. **Verify** — Grep for remaining `_TBD_` or `<!-- FILL` markers. Ask the user for any still missing. Zero markers = done.

6. **Code-graph setup** (if enabled) — See SKILL.md § Step 6 for the full procedure:
   - Copy `.github/code-graph/` (exclude `node_modules/`)
   - Install d3: `cd .github/code-graph && npm install`
   - Ensure `uv` is available (install automatically if not)
   - Add `.code-graph/` to `.gitignore`
   - Write MCP config(s) for selected tools
   - Build initial graph: `uv run --with-requirements .github/code-graph/requirements.txt .github/code-graph/server.py --build`
   - Optionally install git hooks for auto-updates

7. **Register in projects.json** — Add the target project to `projects.json` in the coograph root (create with `{"projects": []}` if missing). Entry: `{ "path": "<absolute-path>", "tools": [...], "code_graph": true|false, "registered_at": "<date>" }`. Then run `./setup.sh` in the coograph root to ensure git hooks are configured for auto-sync on pull.

## Guardrails

- Never guess at commands — if you can't detect them, ask.
- Never invent project structure — read the actual filesystem.
- Initialization is complete only when there are zero `_TBD_` and `<!-- FILL` markers in copied instruction files.
- If code-graph is enabled, initialization is complete only when `.code-graph/graph.db` exists and at least one MCP config has been written.

$ARGUMENTS
