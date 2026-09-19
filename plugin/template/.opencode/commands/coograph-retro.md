---
description: Retro on the project's guardrails. Measures rule violations and session cost from captured signals and proposes edits as an OpenSpec. Never applies.
agent: build
---

Follow `.github/skills/coograph-retro/SKILL.md` exactly. That file is the single source of truth for the retro procedure across every supported tool.

Substitutions for OpenCode:

| SKILL.md tool | OpenCode equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use `read` tool |
| `run_in_terminal` | Use `bash` tool |

Note: OpenCode does not capture transcripts, so signals here come only from sessions run in Claude Code on the same project. If `retro.py --status` reports no signals, say so and offer the backfill step from the skill.

$ARGUMENTS
