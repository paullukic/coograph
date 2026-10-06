# Agent Context

<!--
  Tool-neutral rules. Read automatically by VS Code Copilot, OpenAI Codex CLI,
  OpenCode and other AGENTS.md-aware agents; Claude Code imports it from
  CLAUDE.md. Each rule lives in exactly one file: hard rules and workflow here,
  code conventions in .github/copilot-instructions.md, Claude-only extras in
  CLAUDE.md. Budgets per file: .github/layout/README.md.
  Other tools have native config files: .cursor/rules/, .windsurfrules,
  CONVENTIONS.md (Aider), .clinerules.
-->

## Invocation

If the user types `/coograph-init`, `$coograph-init`, or asks to "initialize the project" / "set up coograph" / "wire up coograph in this repo", follow `.github/skills/coograph-init/SKILL.md` exactly. That single procedure is the source of truth across every tool.

Note for Codex CLI: `/` is reserved for built-in commands. The Codex skill at `.agents/skills/coograph-init/SKILL.md` auto-triggers from description match, or invoke explicitly with `$coograph-init`.

## Hard rules

> **🛑 HARD RULE — CODE-GRAPH FIRST.** Before any codebase search, navigation, tracing, or exploration you MUST use the code-graph MCP tools first (`mcp__code-graph__*`). Only fall back to `sqlite3 .code-graph/graph.db`, and only then to `Glob`/`Grep`/`Read`, if the code-graph DB is genuinely NOT present in the workspace. Convenience is not a valid reason to skip. See § Tool Preferences below.

> **🛑 HARD RULE — OPENSPEC OR STOP.** For any change that modifies 2+ files, touches a spec, alters a public interface, or adds new behavior, you MUST create an OpenSpec in `openspec/changes/<date>-<slug>/` and WAIT for user approval BEFORE writing code. Exemptions are narrow and literal:
> - Typo fix in a single file
> - Comment/docstring-only edit
> - Config-value bump the user explicitly dictates (e.g., "set X=2")
> - Follow-up fix for an already-approved, in-progress OpenSpec
>
> "Trivial," "obvious," "I already know what to do," "small," and "just one tweak" are NOT exemptions. If in doubt → propose, don't code. See § Workflow below.

## Pre-flight (run on every session start)

1. **Code-graph availability** - call `get_minimal_context` with a summary of the task. If it succeeds, code-graph is available and MUST be used for all navigation this session. If it fails, note that code-graph is unavailable and grep/glob fallback is permitted for this session.
2. **Read conventions** - read `.github/copilot-instructions.md` and `.github/instructions/brutal-honesty.instructions.md` if not already loaded.
3. **Check in-progress work** - look for open OpenSpecs in `openspec/changes/` (skip `archive/`). If one exists, summarize its status before starting new work.
4. **OpenSpec gate** - does this task already have an OpenSpec? If NO and it does not fit the exemption list in the HARD RULE above → STOP. Create the OpenSpec and wait for approval before any code edits.

## Tool Preferences

- **MANDATORY: code-graph first, no exceptions.** Before ANY codebase navigation, exploration, tracing, or search - including every "what calls X?", "where is Y defined?", "what imports Z?", "find files named…", "find references to…" - you MUST attempt code-graph tools BEFORE any other search, file-listing, or read tool. This rule is non-negotiable.
  1. **MCP code-graph tools** (`mcp__code-graph__get_minimal_context`, `query_graph`, `get_impact_radius`, `get_review_context`). ALWAYS start here.
  2. **`sqlite3 .code-graph/graph.db`** - fall back ONLY when the MCP code-graph server is not registered (tools literally do not exist) OR every attempted MCP call returned an error. Use the `sqlite3` CLI directly, not Python scripts. Example: `sqlite3 .code-graph/graph.db "SELECT COUNT(*) FROM nodes;"`.
  3. **`Glob` / `Grep` / `Read` chains** - fall back ONLY when Step 1 AND Step 2 are both impossible because the code-graph DB is absent from the workspace.

  The only valid reason to bypass code-graph is that it is genuinely not present. "Slow", "unwieldy", "less convenient", "I already know the file", or "it's a simple lookup" are NOT valid reasons. Never skip Step 1 for Step 2, and never skip Step 2 for Step 3. The graph has pre-indexed call edges, imports, containment, and test mappings - use it.

## Workflow

**Plan → Propose → Apply → Quality Gates → Review Gate → Archive.** Never skip straight to code.

Does not apply to: review only (deliver the review and stop), exploration / research (answer the question), and the exempt changes in the OPENSPEC HARD RULE above.

1. **Plan.** New tickets, unclear requirements, non-obvious scope: run `@Planner` (investigate the codebase, interview the user). Skip it when review output already exists in the conversation or the user named the problem, files, and fix direction. Vague requests (no files, 3+ areas, no clear deliverable): explore first, then plan. Bug reports go to `@Debugger`; a one-line exempt fix is applied, anything else is proposed.
2. **Propose.** `openspec/changes/<date>-<slug>/` with `.openspec.yaml`, `proposal.md` (Why, Goals/Non-Goals, Decisions, Impact, Risks; no separate `design.md`), `specs/<capability>/spec.md`, and `tasks.md` (grouped by logical unit, not per file; final group is verification; each task independently verifiable). See `openspec/changes/archive/` for examples. **Wait for approval.**
3. **Apply.** Work through `tasks.md` in order, marking tasks done. Read every file before editing; check API specs and generated types before assuming names. Requirement changes mid-way: update the OpenSpec, then continue. Progress tracking outside the OpenSpec CLI (feature inventories, test summaries) is JSON, not markdown checkboxes.
4. **Quality gates.** Run typecheck, lint, format and tests; fix until clean. Feature inventory: every pre-existing feature in a modified file is preserved; new files are verified against the spec.
5. **Review gate.** Separate authoring from review: never self-approve in the same context. Run `@Reviewer`; fix Critical and Warning findings; re-run the gates; re-review only if the fixes were substantial. For a big change (more than ~15 files, a commit stack going to people for approval, or anything with queue jobs, locks, state transitions, data migrations or cross-service contracts) say that the `coograph-ultra-review` skill exists - a multi-agent hostile review with adversarial verification, about a million tokens and twenty minutes - and offer it. Never run it unasked.
6. **Done and archive.** Declare completion with evidence and ask the user for next steps. Move the finished change to `openspec/changes/archive/<slug>/`. Then run `python3 .github/retro/retro.py --status`; exit 0 means enough sessions were captured: ask one line, `Run /coograph-retro now? (<n> sessions since last retro)`, and wait. Missing file: skip silently. Never run a retro unprompted.

- **Stuck rule.** After 3 failed attempts at the same fix, stop and ask for direction. Do not try variation after variation of the same approach.
- **Context hygiene.** In long conversations (10+ turns of implementation), re-read modified files from disk before acting on them. Never cite your own prior output as evidence - only fresh tool output counts. When conversation history contradicts a file on disk, trust the file.

## Commands <!-- FILL: your project's commands. Delete rows that don't apply. -->

| Task | Command |
|------|---------|
| Dev server | _TBD_ |
| Build | _TBD_ |
| Lint | _TBD_ |
| Type-check | _TBD_ |
| Format | _TBD_ |
| Test | _TBD_ |

## Routing: touching X, read Y <!-- FILL: one row per area; delete the example rows that don't apply. -->

Read only the row you need. Feature docs describe current state; history lives in OpenSpec and git.

| Touching | Read first |
|----------|-----------|
| _TBD_ (e.g. `src/auth/**`) | _TBD_ (e.g. `docs/features/auth.md`) |
| Tests | `.github/instructions/testing.instructions.md` |
| Styles | `.github/instructions/styling.instructions.md` |
| Generated API types (_TBD_ path) | regenerate with _TBD_, never edit |

**Gotchas.** Traps learned the hard way live in `GOTCHAS.md` (one entry per trap, with the paths and commands it applies to). Check the entries whose `paths:` match what you are about to touch. Claude Code surfaces matching entries automatically.

Instruction files are budgeted per tier (`python3 .github/layout/layout.py --budget`). Add to the doc that owns the area, never a dated section; when files outgrow their budgets, run `/coograph-docs-restructure`.

## Agents

| Agent | Purpose |
|-------|---------|
| `@Reviewer` | Read-only code review: conventions, specs, bugs |
| `@Debugger` | Root-cause analysis and minimal fixes for bugs and build errors |
| `@Planner` | Interview-driven planning with codebase investigation |
| `@Verifier` | Evidence-based completion checks - runs tests, validates acceptance criteria |
| `@Explore` | Fast read-only codebase search and Q&A - prefer over manual search chains |
| `@Retro` | Measures how the guardrails held up across sessions and proposes instruction, hook, and skill edits as an OpenSpec. Proposes only. |

No separate `@Implementer`: the agent that plans and proposes also implements.

**Hand-off, not auto-dispatch.** Where an agent's tools do not carry over to a subagent (VS Code `runSubagent`), do not auto-delegate: stop, name the agent to invoke, give a ready-to-copy prompt, and wait. Hand-off format:

```
## Agent: <agent-name>
**Task**: <one-line summary>  **Verdict**: <PASS/FAIL/APPROVE/REQUEST_CHANGES>
**Key findings**: <numbered list, max 5, each with file:line>
**Open items**: <anything unresolved>
```

| Situation | Agent |
|-----------|-------|
| Code review / conventions | `@Reviewer` |
| Deep review of a big change before approvals - optional, costly | `coograph-ultra-review` skill (one `@Reviewer` per dimension, then refuters) |
| Bug investigation / build errors | `@Debugger` |
| New ticket / unclear requirements | `@Planner` |
| Completion evidence / test verification | `@Verifier` |
| Codebase search / research | `@Explore` |
| Single-line fix, quick clarification | Handle directly |
