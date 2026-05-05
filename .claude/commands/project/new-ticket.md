Start work on a new ticket below. Run pre-flight checks, investigate the codebase, and flow into an OpenSpec proposal.

The full procedure lives in `.github/skills/new-ticket/SKILL.md`. Follow those steps exactly, with these Claude Code–specific substitutions:

| SKILL.md tool | Claude Code equivalent |
|---------------|------------------------|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `manage_todo_list` | Use task tracking internally |
| `read_file` | Use Read tool |
| `grep_search` | Use Grep tool |

## Steps (summary)

1. **Pre-flight** — `get_minimal_context(...)` to confirm code-graph availability; check `openspec/changes/` for in-progress OpenSpecs; read `.github/copilot-instructions.md`.
2. **Parse the ticket** — extract title, requirements, acceptance criteria, linked references. Flag vagueness.
3. **Investigate** — use code-graph first (HARD RULE); identify affected files, existing patterns, risks, integration points. Scope investigation to the ticket.
4. **Flow into `/project:plan` or the `openspec-propose` skill** — do NOT implement. The proposal skill creates artifacts and waits for explicit user approval.

## Guardrails

- Never skip pre-flight (especially the code-graph check).
- Never start writing code before the OpenSpec is approved.
- If the ticket is vague, ask focused clarifying questions one at a time before proposing.
- If an overlapping in-progress OpenSpec exists, stop and ask whether to continue it or start fresh.

$ARGUMENTS
