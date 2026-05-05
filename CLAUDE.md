# Claude Code Instructions

> **🛑 HARD RULE — CODE-GRAPH FIRST.** Before any codebase search, navigation, tracing, or exploration you MUST use the code-graph MCP tools first (`mcp__code-graph__*`). Only fall back to `sqlite3 .code-graph/graph.db`, and only then to `Glob`/`Grep`/`Read`, if the code-graph DB is genuinely NOT present in the workspace. Convenience is not a valid reason to skip. See "Tool Preferences" below.

> **🛑 HARD RULE — OPENSPEC OR STOP.** For any change that modifies 2+ files, touches a spec, alters a public interface, or adds new behavior, you MUST create an OpenSpec in `openspec/changes/<date>-<slug>/` and WAIT for user approval BEFORE writing code. Exemptions are narrow and literal:
> - Typo fix in a single file
> - Comment/docstring-only edit
> - Config-value bump the user explicitly dictates (e.g., "set X=2")
> - Follow-up fix for an already-approved, in-progress OpenSpec
>
> "Trivial," "obvious," "I already know what to do," "small," and "just one tweak" are NOT exemptions. If in doubt → propose, don't code. See § Implementation Workflow for the full Plan → Propose → Apply flow.

## Pre-flight (run on every session start)

Before doing any work, execute this checklist:

1. **Code-graph availability** — call `get_minimal_context` with a summary of the task. If it succeeds, code-graph is available and MUST be used for all navigation this session. If it fails, note that code-graph is unavailable and grep/glob fallback is permitted for this session.
2. **Read conventions** — read `.github/copilot-instructions.md` (if not already loaded by the system).
3. **Check in-progress work** — look for open OpenSpecs in `openspec/changes/` (skip `archive/`). If one exists, summarize its status before starting new work.
4. **OpenSpec gate** — does this task already have an OpenSpec? If NO and it does not fit the exemption list in the HARD RULE above → STOP. Create the OpenSpec (`proposal.md`, `specs/<capability>/spec.md`, `tasks.md`) and wait for approval before any code edits.

This checklist primes correct tool usage for the entire session. Do not skip it.

Read `.github/copilot-instructions.md` at the start of every implementation task. It contains all project conventions, code style, data layer patterns, i18n rules, and agent configuration.

Domain-specific instructions (testing, styling) are in `.github/instructions/` and are loaded automatically by VS Code when editing matching files. For Claude Code, read them on demand: check `.github/instructions/testing.instructions.md` when writing tests, `.github/instructions/styling.instructions.md` when writing CSS.

## Communication Style

Read `.github/instructions/brutal-honesty.instructions.md` at session start and apply throughout. Direct, evidence-based, concise. No filler, no praise padding, no softening. See also `.github/copilot-instructions.md`.

## Quick Reference

| Task | Command |
|------|---------|
| Dev server | `_TBD_` |
| Build | `_TBD_` |
| Lint | `_TBD_` |
| Type-check | `_TBD_` |
| Format | `_TBD_` |
| Test | `_TBD_` |

## Branching Strategy

<!-- FILL: e.g. "Feature branches off `main`. Branch naming: `feature/<ticket>-<slug>`, `fix/<ticket>-<slug>`." -->

## Key Paths

- Source code: `src/`
- Shared components: `_TBD_`
- API types: `_TBD_`
- Translations: `_TBD_`
- Navigation index: `_TBD_`

## Critical Rules (from copilot-instructions — surfaced here because they cause the most damage when missed)

- **Regenerate API types** using the appropriate command. Editing generated types directly will be overwritten.
- **Preserve all existing features** unless the ticket explicitly says to remove them. A feature absent from the ticket means "keep it." When in doubt, ask.
- **Feature inventory before editing.** Before modifying a container or page, list all existing features (sections, hooks, conditional blocks, admin-only UI) and verify each is preserved in the final result.
- **No new dependencies** without explicit user approval.

## Tool Preferences

- **MANDATORY — Code-graph first, no exceptions.** Before ANY codebase navigation, exploration, tracing, or search — including every "what calls X?", "where is Y defined?", "what imports Z?", "find files named…", "find references to…" — you MUST attempt code-graph tools BEFORE any other search, file-listing, or read tool. This rule is non-negotiable.
  1. **MCP code-graph tools** (`mcp__code-graph__get_minimal_context`, `query_graph`, `get_impact_radius`, `get_review_context`). ALWAYS start here.
  2. **`sqlite3 .code-graph/graph.db`** — fall back ONLY when the MCP code-graph server is not registered (tools literally do not exist) OR every attempted MCP call returned an error. Use the `sqlite3` CLI directly, not Python scripts. Example: `sqlite3 .code-graph/graph.db "SELECT COUNT(*) FROM nodes;"`.
  3. **`Glob` / `Grep` / `Read` chains** — fall back ONLY when Step 1 AND Step 2 are both impossible because the code-graph DB is absent from the workspace.

  The only valid reason to bypass code-graph is that it is genuinely not present. "Slow", "unwieldy", "less convenient", "I already know the file", or "it's a simple lookup" are NOT valid reasons. Never skip Step 1 for Step 2, and never skip Step 2 for Step 3.

## Implementation Workflow (MANDATORY)

Before any non-trivial implementation, follow: **Plan → Propose → Apply**. Never skip straight to writing code. Full rules are in `.github/copilot-instructions.md` § Workflow — read that section. Summary below.

### When the workflow does NOT apply

- **Review only** — deliver the review and stop.
- **Exploration / research** — answer the question, not an implementation task.
- **Exempt changes** (narrow literal list from the OPENSPEC OR STOP HARD RULE above): typo fix in a single file, comment/docstring-only edit, user-dictated config-value bump, follow-up for an already-approved in-progress OpenSpec. "Trivial", "obvious", "small", "just one tweak" are NOT exemptions — when in doubt, propose.

### Step 1: Plan

- **Run `/project:plan`** for new tickets, unclear requirements, or non-obvious scope.
- **Skip planning** when review output already exists in conversation, or the user specifies the problem, files, and fix direction.
- **Bug reports**: Run `/project:debug`. If the fix is a one-line exempt change (per literal list above), apply it. Otherwise go to Step 2.

### Step 2: Propose (OpenSpec)

Create an OpenSpec in `openspec/changes/<date>-<slug>/` with `.openspec.yaml`, `proposal.md`, `specs/<capability>/spec.md`, and `tasks.md`.

`proposal.md` sections: Why, Goals/Non-Goals, Decisions, Impact, Risks.

`tasks.md`: group by logical unit (not per-file), final group is verification, each task independently verifiable.

See `openspec/changes/archive/` for reference. **Wait for user approval** before implementing.

### Step 3: Apply

- Work through `tasks.md` in order. Mark tasks done as you go.
- Read every file before editing. Check API spec / generated types before assuming names.
- If you hit a non-obvious build error, run `/project:debug`.
- Mid-implementation requirement changes: update the OpenSpec, then continue.
- Continuing previous work: check `openspec/changes/` for in-progress OpenSpec.

**After all tasks are done:**

1. **Quality gates** — run typecheck, lint, format. Fix until clean.
2. **Feature inventory** — for every modified file, verify all pre-existing features are preserved. For new files, verify against spec.
3. **Review gate** — run `/project:review`. Fix Critical/Warning findings. Re-run quality gates after fixes. Re-review only if fixes were substantial.
4. **Done** — declare completion, ask user for next steps.

### Archiving

Move completed OpenSpecs from `openspec/changes/<slug>/` to `openspec/changes/archive/<slug>/`.

## Subagent Delegation

| Situation | Command |
|-----------|---------|
| Code review or convention audit | `/project:review` |
| Bug investigation, build errors | `/project:debug` |
| Planning / unclear requirements | `/project:plan` |
| Completion evidence, verification | `/project:verify` |
| Codebase search, research | `/project:explore` |

Pass the full task description and relevant file paths when delegating.

## Context Management

### Preservation on compaction
When the conversation context is compacted, always preserve:
- The current task from `tasks.md` (if working through an OpenSpec)
- The full list of files modified in this session
- Any failing test or build output not yet resolved
- Acceptance criteria for the current task
- Any user decisions or scope changes made during this session

### Memory pointer pattern
When intermediate results are large (investigation findings, audit reports, dependency maps), write them to a file in the OpenSpec change directory (e.g., `openspec/changes/<name>/notes/<topic>.md`) and reference the file path in conversation instead of keeping the full content in context. This prevents context overflow on complex tasks and preserves findings across conversation compaction.

### Context hygiene
Long conversations accumulate stale state. To prevent acting on outdated information:
- **After every 10+ turns of implementation**: re-read all files you've modified from disk. Your memory of their contents may have drifted from reality.
- **Never cite your own prior output as evidence.** Only fresh `read_file` / tool output counts. If you said "line 42 has X" five turns ago, re-read line 42 before acting on it.
- **When conversation history contradicts a file on disk**, trust the file. The file is the source of truth — conversation history may contain hallucinations that got referenced and compounded.
