Run a retro on this project's guardrails: measure which rules got broken across past sessions, what each session cost, and propose evidence-backed edits to instructions, hooks, and skills as an OpenSpec. Propose only; never apply.

The full procedure lives in `.github/skills/coograph-retro/SKILL.md`. Follow those steps exactly, with these Claude Code specific substitutions:

| SKILL.md tool | Claude Code equivalent |
|---------------|------------------------|
| `vscode_askQuestions` | Ask the user directly in the conversation |
| `read_file` | Use Read tool |
| `run_in_terminal` | Use Bash tool |

## Steps (summary)

1. **Status** `python3 .github/retro/retro.py --status`. Exit 4 means bootstrap (seed the registry, offer a transcript backfill from `~/.claude/projects/<slug>/`, with the user's consent). Exit 2 means the hooks are not installed; stop.
2. **Analyze** `python3 .github/retro/retro.py --report`, then read `.coograph/retro/report.md` and `report.json`. Those are the only numbers you may cite.
3. **Decide** changes by type (new-hook, edit-rule, add-rule, new-instruction-file, prune-rule) using the rules in the skill: evidence first, escalate instead of shouting, budget pairing, no silent loosening.
4. **Write** `openspec/changes/<date>-retro-<n>/` with `.openspec.yaml`, `proposal.md`, `specs/guardrails/spec.md`, `tasks.md` (ending with Update registry and Rollback), and `patches/`.
5. **Report** the summary table and stop.

## Guardrails

- Never write outside the change directory.
- Never run `/coograph-apply` yourself.
- Never cite a number that is not in `report.json`.
- Never propose louder prose for an existing rule.

$ARGUMENTS
