Suggest which model each Coograph agent should run on, for this project or the ticket in hand, with a reason and an estimated cost delta per line. Proposes; never applies without an explicit accept.

The full procedure lives in `.github/skills/coograph-suggest-multi-models/SKILL.md`. Follow those steps exactly, with these Claude Code specific substitutions:

| SKILL.md tool | Claude Code equivalent |
|---------------|------------------------|
| `vscode_askQuestions` | Ask the user directly, or use AskUserQuestion |
| `read_file` | Use Read tool |
| `run_in_terminal` | Use Bash tool |

## Steps (summary)

1. Read the `models` block in `openspec/config.yaml` (`mode`, `preset`). Missing means `unset`.
2. Decide scope: a ticket in progress means suggest for the task, otherwise for the project.
3. Produce one row per agent you propose to change: agent, model, a one-line reason grounded in this project or ticket, and the cost delta against the session model. Say the figures are estimates from list rates recorded 2026-09-20.
4. Let the user edit or decline. Write nothing before they accept.
5. On accept, set `mode` and `preset` in `openspec/config.yaml`. A task-scoped choice is not written to disk.

## Guardrails

- Never write config without an explicit accept.
- Never propose a cheaper model for `reviewer` or `debugger` unless the user asks.
- Say the cache cost out loud when proposing three or more models: caches are model-scoped.
- Never change the model the user's own session runs on.
