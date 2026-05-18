# Migration Notes

`sync.py` never overwrites user-owned files (`CLAUDE.md`, `.github/copilot-instructions.md`, `openspec/config.yaml` — see `SKIP_FILES` in `.github/sync.py`). When the template gains rules that must live in those files, existing users have to apply them by hand. Entries below are in reverse chronological order — apply any you haven't yet.

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
