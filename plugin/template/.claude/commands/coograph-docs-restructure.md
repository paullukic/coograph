Restructure this project's instruction and map files into the tier layout (always-loaded root files, workspace routers, on-demand feature docs, `GOTCHAS.md`) so they fit their budgets with no loss of current-state facts.

The full procedure lives in `.github/skills/coograph-docs-restructure/SKILL.md`. Follow it exactly, with these Claude Code specific substitutions:

| SKILL.md tool | Claude Code equivalent |
|---------------|------------------------|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use Read tool |
| `run_in_terminal` | Use Bash tool |

## Steps (summary)

1. **Take stock** with `python3 .github/layout/layout.py --budget` and `--json`.
2. **Work out the shape**: workspaces, tools in use, product areas, duplicated rules, buried gotchas.
3. **Write** `openspec/changes/<date>-docs-restructure/` with the area fact lists, and **stop for approval**.
4. **Apply** after approval: one subagent per area, every fact checked against the code (code-graph first) and marked kept, kept-unverifiable or dropped with a reason.
5. **Verify**: `layout.py --budget` exits 0, before and after per tier, then `/coograph-review`.

## Guardrails

- Never edit an instruction file before the OpenSpec is approved.
- Check every fact against the code. Keep what the code cannot confirm or contradict (marked); drop only what it contradicts, history, or duplicates, with the reason.
- Never write dated sections. Never state a rule in more than one file.

$ARGUMENTS

## Models

Read the `models` block in `openspec/config.yaml` before delegating. When `mode` is
`preset` or `per-task`, pass that agent's model on the Agent call; when it is `off`
or `unset`, pass nothing and let the agent inherit the session model.

End your report with one line naming what ran where, so the setting is visible
without reading config:

```
models: explore=haiku (mapping), reviewer=opus (mapping)
```

Print the footer in every mode. In `off` and `unset` it reads `(inherited)`.
