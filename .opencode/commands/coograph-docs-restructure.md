---
description: Restructure instruction and map files into the tier layout so they fit their budgets. Proposes an OpenSpec first; migrates only after approval.
agent: build
---

Follow `.github/skills/coograph-docs-restructure/SKILL.md` exactly. That file is the single source of truth for the restructure procedure across every supported tool.

Substitutions for OpenCode:

| SKILL.md tool | OpenCode equivalent |
|---|---|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use `read` tool |
| `run_in_terminal` | Use `bash` tool |

$ARGUMENTS
