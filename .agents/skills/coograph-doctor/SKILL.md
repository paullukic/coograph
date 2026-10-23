---
name: coograph-doctor
description: Health check of a Coograph install: graph, code-graph server and MCP configs, unfilled placeholders, per-tool files, git hooks, openspec config, pending sync copies. Read-only, then offers fixes. Trigger when the user types `$coograph-doctor`, asks to "check the install", "run the doctor", or why coograph seems broken.
---

# /coograph-doctor (Codex CLI)

Coograph install check. Follow `.github/skills/coograph-doctor/SKILL.md` exactly. That file is the single source of truth for the procedure across every supported tool.

Substitutions for Codex CLI:

| SKILL.md tool | Codex CLI equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use `view` |
| `run_in_terminal` | Use the shell |

The script is read-only. Apply a fix only after the user says yes to it.
