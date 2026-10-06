# Claude Code Instructions

@AGENTS.md
@.github/copilot-instructions.md

The two imports above hold the hard rules, workflow, commands, routing, and code conventions. Each rule is stated once, there. This file adds only what is specific to Claude Code.

## Claude Code specifics

- **Instruction files.** Domain rules in `.github/instructions/` load automatically in VS Code; in Claude Code read them on demand (`testing.instructions.md` when writing tests, `styling.instructions.md` when writing CSS). A workspace with its own `AGENTS.md` gets a one-line `CLAUDE.md` holding `@AGENTS.md`, which Claude Code loads only when you touch files there.
- **Gotchas.** A hook puts the `GOTCHAS.md` entries that match a file you edit or a command you run in front of you, once per session. Treat them as rules for that call.
- **Retro.** Sessions are measured against the hard rules (see `.github/retro/README.md`). When the session-start line says `run /coograph-retro`, mention it to the user once. Never run it unprompted.

## Subagent Delegation

| Situation | Command |
|-----------|---------|
| Code review or convention audit | `/coograph-review` |
| Deep review of a big change before approvals (multi-agent, adversarial; optional, costly): full PR, fix batch (delta) or a plan before code | `/coograph-ultra-review` |
| Bug investigation, build errors | `/coograph-debug` |
| Planning / unclear requirements | `/coograph-plan` |
| Completion evidence, verification | `/coograph-verify` |
| Codebase search, research | `/coograph-search` |
| Guardrail retro, instruction and hook tuning from evidence | `/coograph-retro` |
| Instruction files over budget (`layout.py --budget` says STRUCTURAL) | `/coograph-docs-restructure` |

Pass the full task description and relevant file paths when delegating. Claude Code subagents do receive their tools, so the hand-off rule in `AGENTS.md` does not apply here.

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
