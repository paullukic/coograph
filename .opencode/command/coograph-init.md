---
description: Initialize a project with Coograph — auto-detect stack, fill placeholders, set up code-graph
agent: build
---

Follow `.github/skills/coograph-init/SKILL.md` exactly. That file is the single source of truth for the initialization procedure across every supported tool.

Substitutions for OpenCode:

| SKILL.md tool | OpenCode equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `manage_todo_list` | Track steps in conversation |
| `apply_patch` / `create_file` | Use `edit` / `write` tools |
| `read_file` | Use `read` tool |
| `grep_search` | Use `grep` tool |

Run through every step (1–9) including code-graph health check at the end. Initialization complete only when zero `_TBD_` and zero `<!-- FILL` markers remain in copied instruction files.

$ARGUMENTS
