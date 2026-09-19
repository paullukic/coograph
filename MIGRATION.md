# Migration Notes

`sync.py` never overwrites user-owned files (`CLAUDE.md`, `.github/copilot-instructions.md`, `openspec/config.yaml` — see `SKIP_FILES` in `.github/sync.py`). When the template gains rules that must live in those files, existing users have to apply them by hand. Entries below are in reverse chronological order — apply any you haven't yet.

---

## 2026-09-19: Retro, self-tuning guardrails (plugin 1.1.0)

New: `.github/retro/` (analyzer, registry, README), `.claude/hooks/capture-signals.py` and `_coograph_signals.py`, `SessionEnd` + `SessionStart` wiring in `.claude/settings.json`, the `/coograph-retro` skill, the `@Retro` agent, and a retro prompt at the end of `coograph-apply` and `coograph-archive`.

Registered projects get all of it on the next `git pull` of coograph. `sync.py` seeds `.github/retro/rules.json` when absent and merges new seeded rules into an existing one without touching local edits.

Manual steps, because `sync.py` never overwrites `CLAUDE.md`, `AGENTS.md`, or `.github/copilot-instructions.md`:

1. Add the retro row to the subagent table in `CLAUDE.md`:
   `| Guardrail retro, instruction and hook tuning from evidence | /coograph-retro |`
2. In the workflow "Done" step, append: run `python3 .github/retro/retro.py --status`; if it exits 0, ask `Run /coograph-retro now? (<n> sessions since last retro)`; if the file is missing, skip silently.
3. Optional, `AGENTS.md` and `copilot-instructions.md`: add the `@Retro` agent row and the same "Done" instruction. The synced `coograph-apply` and `coograph-archive` skills already carry the prompt, so this is belt and braces.

Unregistered projects: copy `.github/retro/` (without `tests/` and without `rules.json`, which is coograph's own live registry), the two new hook files, and `.claude/settings.json` from the coograph repo, then run `python3 .github/retro/retro.py --merge-seed` (creates `rules.json` from `rules.seed.json`) and `python3 .github/retro/retro.py --validate`. Backfill past sessions with `python3 .claude/hooks/capture-signals.py --backfill ~/.claude/projects/<slug> --cwd .`; the slug is your absolute project path with every non-alphanumeric character replaced by `-`.

---

## 2026-05-18 — Skill rename to `coograph-*` namespace

All skills now live under the `coograph-*` prefix. Issue [#9](https://github.com/paullukic/coograph/issues/9).

| Old name | New name |
|---|---|
| `openspec-propose` | `coograph-propose` |
| `openspec-apply` | `coograph-apply` |
| `openspec-archive` | `coograph-archive` |
| `openspec-explore` | `coograph-explore` |
| `new-ticket` | `coograph-new-ticket` |
| `rebuild-code-graph` | `coograph-rebuild-graph` |

Slash command `/project:new-ticket` was removed. Use `/coograph-new-ticket` instead. The five renamed skills above are invoked directly by their new names (`/coograph-propose`, `/coograph-apply`, etc.).

Consumers registered in `projects.json` and tracked via the post-merge sync hook get this rename **automatically** on the next `git pull` of the coograph repo. `sync.py` now (phase 3 of the same patch) copies the new `coograph-*/` skill dirs and `coograph-*.md` wrappers, and removes the obsolete paths listed in `OBSOLETE_PATHS`. No manual `rm` needed for registered projects.

For projects **not** registered in `projects.json` (or pinned to an older `sync.py`), run the cleanup manually:

```bash
rm -rf .github/skills/openspec-propose \
       .github/skills/openspec-apply \
       .github/skills/openspec-archive \
       .github/skills/openspec-explore \
       .github/skills/new-ticket \
       .github/skills/rebuild-code-graph \
       .claude/commands/project/new-ticket.md
```

Hand-update any references in your own `CLAUDE.md`, agent prompts, or docs:

```bash
grep -rIn "openspec-propose\|openspec-apply\|openspec-archive\|openspec-explore\|\bnew-ticket\b\|rebuild-code-graph" \
  --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=archive .
```

After fixing, the same grep should return only matches in `openspec/changes/archive/` (frozen history is allowed to keep old names).

### Phase 2 — `/project:*` slash commands moved under `/coograph-*`

Same date, expanded scope. All shipped project-flow slash commands now sit in the `/coograph-*` namespace alongside the renamed skills.

| Old | New |
|---|---|
| `/project:plan` | `/coograph-plan` |
| `/project:review` | `/coograph-review` |
| `/project:verify` | `/coograph-verify` |
| `/project:debug` | `/coograph-debug` |
| `/project:explore` | `/coograph-search` |

`/project:explore` was renamed to `/coograph-search` (not `/coograph-explore`) to avoid colliding with the existing `coograph-explore` skill — a separate thinking-mode prompt. `coograph-search` also describes the slash command's actual purpose more accurately (codebase Q&A with evidence).

Registered consumers get the 5 old wrapper files removed automatically by the phase-3 `sync.py` patch. For unregistered or pinned projects, run:

```bash
rm -f .claude/commands/project/plan.md \
      .claude/commands/project/review.md \
      .claude/commands/project/verify.md \
      .claude/commands/project/debug.md \
      .claude/commands/project/explore.md
```

`.claude/commands/project/` is now empty for projects that only used coograph-shipped commands — leave the directory itself in place for any user-authored project-specific commands you want to add.

Hand-update any references in your own `CLAUDE.md`, agent prompts, or docs the same way as phase 1:

```bash
grep -rIn "/project:\(plan\|debug\|review\|verify\|explore\)" \
  --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=archive .
```

---

## 2026-04-15 — HARD RULE banners (code-graph + OpenSpec)

Two non-negotiable rules were added to the template's `CLAUDE.md` and `.github/copilot-instructions.md`. Paste both banners verbatim near the top of each file in your project (above the first `##` heading). Keep the exact wording — agents are trained to look for these literal strings.

```markdown
> **🛑 HARD RULE — CODE-GRAPH FIRST.** Before any codebase search, navigation, tracing, or exploration you MUST use the code-graph MCP tools first (`mcp__code-graph__*`). Only fall back to `sqlite3 .code-graph/graph.db`, and only then to `Glob`/`Grep`/`Read`, if the code-graph DB is genuinely NOT present in the workspace. Convenience is not a valid reason to skip.

> **🛑 HARD RULE — OPENSPEC OR STOP.** For any change that modifies 2+ files, touches a spec, alters a public interface, or adds new behavior, you MUST create an OpenSpec in `openspec/changes/<date>-<slug>/` and WAIT for user approval BEFORE writing code. Exemptions are narrow and literal:
> - Typo fix in a single file
> - Comment/docstring-only edit
> - Config-value bump the user explicitly dictates (e.g., "set X=2")
> - Follow-up fix for an already-approved, in-progress OpenSpec
>
> "Trivial," "obvious," "I already know what to do," "small," and "just one tweak" are NOT exemptions. If in doubt → propose, don't code.
```

Also update two phrases elsewhere in those same files so nothing contradicts the banners:

- In the **"When the workflow does NOT apply"** list: replace the bullet `Single-file fixes, typos, trivial changes — just do it.` with `Exempt changes (narrow literal list from the OPENSPEC OR STOP HARD RULE above): typo fix in a single file, comment/docstring-only edit, user-dictated config-value bump, follow-up for an already-approved in-progress OpenSpec. "Trivial", "obvious", "small", "just one tweak" are NOT exemptions — when in doubt, propose.`
- In the **Bug reports** bullet: replace `If fix is trivial, just fix it.` with `If the fix is a one-line exempt change (per literal list above), apply it.`

Verify:

```bash
grep -l "HARD RULE — CODE-GRAPH FIRST" CLAUDE.md .github/copilot-instructions.md
grep -l "HARD RULE — OPENSPEC OR STOP" CLAUDE.md .github/copilot-instructions.md
```

Both files should appear in each output.
