---
name: coograph-init
description: Initialize a new project with the Coograph template — auto-detect tech stack, fill all `_TBD_` placeholders, optionally set up the code-graph. Trigger when the user types `/coograph-init` or `$coograph-init`, asks to "initialize the project", "set up coograph", "wire up coograph", "add coograph to this repo", or otherwise wants the Coograph configuration installed in a fresh repository.
---

# /coograph-init (Codex CLI)

Coograph initializer. Follow `.github/skills/coograph-init/SKILL.md` exactly — that file is the single source of truth for the procedure across every supported tool.

Substitutions for Codex CLI:

| SKILL.md tool | Codex CLI equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `manage_todo_list` | Track steps in conversation |
| `apply_patch` / `create_file` | Use `apply_patch` |
| `read_file` | Use `view` |
| `grep_search` | Use `grep` / `rg` via shell |

Run through every step (1–9) including the code-graph health check at the end. Initialization is complete only when zero `_TBD_` and zero `<!-- FILL` markers remain in copied instruction files.
