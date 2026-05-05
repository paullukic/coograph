# Coograph Conventions

This project ships with the Coograph AI coding template. Aider should follow these rules.

## Invocation

If the user types `/coograph:init` (or asks to "initialize the project", "set up coograph"), follow `.github/skills/initialize-project/SKILL.md` exactly.

## On session start

1. Read `.github/copilot-instructions.md` for full project conventions.
2. Read `.github/instructions/brutal-honesty.instructions.md` for communication style.
3. Check `openspec/changes/` for in-progress work (skip `archive/`).

## Code-graph first

If `.code-graph/graph.db` exists, use it via the MCP server (`get_minimal_context`, `query_graph`) or direct `sqlite3` queries before grep/glob navigation. Only fall back to grep when the database is genuinely absent.

## OpenSpec gate

Any change modifying 2+ files, touching a spec, altering a public interface, or adding new behavior MUST go through `openspec/changes/<date>-<slug>/` with user approval BEFORE code.

Exemptions are narrow and literal: typo fix, comment-only edit, user-dictated config bump, or follow-up on an approved in-progress OpenSpec.

## Workflow

Plan → Propose (OpenSpec) → Apply → Quality Gates → Review Gate → Archive. Skip only for the literal exemptions above. After 3 failed attempts, stop and ask.

## Communication

Direct, evidence-based, severity-rated. Every finding cites `file:line` with verbatim quotes. No filler, no praise padding, no softening.
