Check that this project's Coograph install is healthy: graph, server, MCP configs, placeholders, per-tool files, hooks, openspec config, pending sync copies. Read-only; fixes only after the user says yes.

The full procedure lives in `.github/skills/coograph-doctor/SKILL.md`. Follow those steps exactly, with these Claude Code specific substitutions:

| SKILL.md tool | Claude Code equivalent |
|---------------|------------------------|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use Read tool |
| `run_in_terminal` | Use Bash tool |

## Steps (summary)

1. **Run** `python3 .github/skills/coograph-doctor/doctor.py --project <path>` (current folder by default). From a coograph checkout, pass `--project` and the registry in `projects.json` is used.
2. **Report** the output as it is, then name the first problem to fix.
3. **Offer fixes one at a time** (rebuild the graph, re-run `/coograph-init`, install git hooks, review parked sync copies) and wait for a yes before each.
4. **Re-run** the script after any fix.

$ARGUMENTS
