# /coograph-init

Initialize a project with the Coograph template. Auto-detect tech stack, fill all placeholders, optionally set up the code-graph.

Follow `.github/skills/coograph-init/SKILL.md` exactly. That file is the single source of truth across every supported tool.

Substitutions for Codex CLI:

| SKILL.md tool | Codex CLI equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `manage_todo_list` | Track steps in conversation |
| `apply_patch` / `create_file` | Use `apply_patch` |
| `read_file` | Use `view` |
| `grep_search` | Use `grep` / `rg` via shell |

Run through every step (1–9) including code-graph health check at the end. Initialization complete only when zero `_TBD_` and zero `<!-- FILL` markers remain in copied instruction files.

$ARGUMENTS
