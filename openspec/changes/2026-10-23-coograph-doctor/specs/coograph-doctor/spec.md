# Spec: coograph-doctor

## Requirements

- R1. `doctor.py` is stdlib-only, read-only (no write anywhere under the project), and runs as `python3 .github/skills/coograph-doctor/doctor.py [--project PATH] [--registry PATH] [--json]`.
- R2. Output is one line per check, `<STATUS>  <id>  <detail>`, with STATUS one of PASS / WARN / FAIL / SKIP and a `fix:` line under every WARN and FAIL, ending with `Summary: N PASS, N WARN, N FAIL, N SKIP`. `--json` emits the same results as a JSON list plus the summary.
- R3. Exit 0 when no check FAILs, 1 when any does, 2 on a usage error (bad `--project` / `--registry`).
- R4. Checks `graph`, `graph-age`, `server`, `mcp:<tool>`, `markers`, `tools`, `hooks:git`, `openspec`, `hooks:claude`, `sync` behave per the table in proposal.md.
- R5. Code-graph not enabled (no `.github/code-graph/` and the registry says `code_graph: false` or has no entry) makes `graph`, `graph-age`, `server`, `mcp:*` and `hooks:git` SKIP.
- R6. A coograph template checkout (`templates/` and `setup.sh` at the root) makes `markers` SKIP.
- R7. With a registry entry, `tools` checks the registered tools; without one, it detects tools from disk and says it did.
- R8. All 8 tools invoke the doctor the way they invoke init: `/coograph-doctor` (Claude Code, VS Code Copilot, OpenCode; string match in Cursor, Devin Desktop, Aider, Cline), `$coograph-doctor` in Codex CLI, plus a natural-language phrase ("check the install", "run the doctor"). `check-invocations.py` enforces it in CI.
- R9. coograph-init's final step runs the doctor; the init wrappers say so.
- R10. README, SETUP.md and the website getting-started page list the doctor next to init.

## Scenarios

### Scenario: fresh, fully enabled init passes
- Given: a fixture project laid out as init leaves it with every option yes (Claude Code + VS Code + OpenCode, code-graph with a non-empty graph built after the last commit, git hooks, filled instruction files, `openspec/config.yaml`), registered in a fixture `projects.json`
- When: the doctor runs with `--registry`
- Then: every check is PASS or SKIP, the exit code is 0

### Scenario: each broken category is caught (one test each)
- Given: the passing fixture with exactly one fault
- When: the doctor runs
- Then: the named check reports the named status, and only that check changes:
  - `graph.db` deleted -> `graph` FAIL
  - graph with 0 edges -> `graph` FAIL
  - 60 functions, 0 `calls` edges -> `graph` WARN
  - graph mtime two hours before the last commit -> `graph-age` WARN
  - `server.py` deleted -> `server` FAIL
  - `.mcp.json` without `code-graph` -> `mcp:claude` FAIL
  - `opencode.json` pointing at a missing absolute `server.py` -> `mcp:opencode` FAIL
  - `_TBD_` left in `AGENTS.md` -> `markers` FAIL naming `AGENTS.md:<line>`
  - registry lists `vscode` but `.github/agents/` is missing -> `tools` FAIL
  - `.cursor/` on disk, not in the registry -> `tools` WARN
  - `post-merge` hook missing -> `hooks:git` WARN
  - `openspec/config.yaml` with a tab-indented line -> `openspec` FAIL
  - `.claude/settings.json` wiring a missing hook -> `hooks:claude` FAIL
  - a file under `.coograph/upstream/` -> `sync` WARN

### Scenario: optional features off
- Given: a project initialized with code-graph disabled and not a git repo
- When: the doctor runs
- Then: `graph`, `graph-age`, `server`, `mcp:*`, `hooks:git` are SKIP and the exit code is 0

### Scenario: template checkout
- Given: the doctor runs on the coograph repo itself
- When: `markers` runs
- Then: it is SKIP ("template checkout"), not FAIL on the template's `_TBD_` placeholders

### Scenario: no registry
- Given: a project with Claude Code files and no `--registry`
- When: the doctor runs
- Then: `tools` detects `claude` from disk, says "detected from disk (no registry)", and passes

### Scenario: read-only
- Given: any fixture
- When: the doctor runs
- Then: no file under the project changes (mtime and content hash of every file before and after are equal)

### Scenario: invocation drift
- Given: one rule file loses its `/coograph-doctor` line
- When: `check-invocations.py` runs
- Then: it exits 1 naming that file and the doctor skill
