---
description: Health check of the Coograph install (graph, MCP configs, placeholders, tool files, hooks). Read-only; offers fixes.
agent: build
---

Follow `.github/skills/coograph-doctor/SKILL.md` exactly. That file is the single source of truth for the install check across every supported tool.

Substitutions for OpenCode:

| SKILL.md tool | OpenCode equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use `read` tool |
| `run_in_terminal` | Use `bash` tool |

The script is read-only. Apply a fix only after the user says yes to it.

$ARGUMENTS
