# Spec: sync.py propagates the OpenCode channel to registered projects

## Requirements

- A registered project whose `projects.json` entry lists `opencode` in `tools` receives, on every `git pull` of coograph: the four `.opencode/commands/coograph-*.md` mirrors and `.opencode/plugin/log-bash.ts`.
- When such a project also has `code_graph: true`, `sync.py` additionally creates `opencode.json` at the project root (write-if-missing only) with `skills.paths` pointing at `.github/skills` and a `mcp.code-graph` entry.
- Projects that do not list `opencode` get no `.opencode/` additions from this change; the Claude and VS Code channels keep their existing behavior (`opencode.json` generation is gated on the `opencode` tool tag, `.mcp.json` copying stays as before).
- `coograph-init` (SKILL.md Steps 3 and 6e) documents exactly the same file set, so an OpenCode project initialized from the template and one propagated by sync end up with identical OpenCode wiring.

## Scenarios

### Scenario: OpenCode-only registered project pulls coograph
- **Given**: a project registered with `tools: ["opencode"]` and `code_graph: true`
- **When**: `git pull` triggers the post-merge hook running `sync.py`
- **Then**: the project gains the four `.opencode/commands/coograph-*.md`, `.opencode/plugin/log-bash.ts`, and a generated `opencode.json` whose `mcp.code-graph.command` runs a working server

### Scenario: repeat sync is idempotent
- **Given**: a project already synced with the OpenCode channel
- **When**: `sync.py` runs again after further template edits
- **Then**: command mirrors and `log-bash.ts` refresh from the template, while an existing `opencode.json` (generated or hand-written) is left byte-for-byte untouched

### Scenario: no-opencode project is unaffected
- **Given**: a project registered with `tools: ["claude"]` only
- **When**: `sync.py` runs
- **Then**: nothing is written under `.opencode/` and no `opencode.json` is created
