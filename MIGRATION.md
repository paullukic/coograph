# Migration Notes

`sync.py` never overwrites user-owned files (`CLAUDE.md`, `.github/copilot-instructions.md`, `openspec/config.yaml` — see `SKIP_FILES` in `.github/sync.py`). When the template gains rules that must live in those files, existing users have to apply them by hand. Entries below are in reverse chronological order — apply any you haven't yet.

---

## 2026-10-07: Layout follow-ups from the first real runs (plugin 1.8.5)

- **The CI docs check runs where tooling is kept out of git.** `coograph-layout.yml` downloads `layout.py` from coograph `main` when the checkout has none. A managed workflow (first line `coograph:managed`) gets this on the next sync.
- **Nested `CLAUDE.md` files are measured as routers.** The seed `routers` now include `*/CLAUDE.md` and `*/*/CLAUDE.md`. Your `layout.json` is yours and is not changed: add those two globs to `routers` by hand.
- **Linked git worktrees are skipped.** Folders like `Panel-wt-*` (a `.git` file pointing into another repo's `worktrees/`) are no longer measured as workspaces.
- **Do not commit the generated `opencode.json`.** It holds absolute, machine-specific paths on purpose: OpenCode resolves `cwd: "."` against the folder it was started in, so project-relative paths break when you start it from a subfolder (verified with OpenCode 1.18.34). Sync writes it per machine, only when missing.

---

## 2026-10-06: OpenCode channel + Application-Control-safe code-graph launcher (plugin 1.8.4)

Two changes, both automatic for **registered** projects on the next `git pull` of coograph:

1. `sync.py` now picks the code-graph launcher per machine — an existing `.code-graph/venv` if present, else `uv` pinned to system-only Python (`UV_NO_MANAGED_PYTHON=1`, `UV_PYTHON_DOWNLOADS=never`), else plain `python`. On Windows machines whose Smart App Control / Defender Application Control policy blocks the `_overlapped.pyd` of uv-managed and per-user Python builds, every unpinned `uv run` silently died at `import mcp.server.fastmcp` — the graph stayed empty and the MCP server never answered. The pins are baked into the copied `.mcp.json` and into generated `opencode.json` files, and used for the on-pull rebuild.
2. `sync.py` gained an OpenCode tool block: a registered project whose `projects.json` `tools` list includes `"opencode"` receives the four `.opencode/commands/coograph-*.md`, `.opencode/plugin/log-bash.ts`, and — with `code_graph: true` — a generated `opencode.json` (`skills.paths` + the `mcp.code-graph` entry). `opencode.json` is only created when missing; existing files are never rewritten.

Manual steps:

1. In `projects.json` (coograph root, machine-local), add `"opencode"` to the project's `tools` list — or re-run `/coograph-init` and select OpenCode.
2. Projects that already hand-wrote an `opencode.json`: merge `"skills": {"paths": [".github/skills"]}` and the `mcp.code-graph` key in by hand, and on uv-pinned Windows add `"environment": {"UV_NO_MANAGED_PYTHON": "1", "UV_PYTHON_DOWNLOADS": "never"}` plus `timeout: 120000` (the 5-second default is too short for `build_graph`).
3. Restart the tools — OpenCode reads `opencode.json` and `.opencode/plugin/` only at session start; Claude Code likewise reads `.mcp.json` only at startup.

**Interpreter constraint is now a range.** `.mcp.json`, the on-pull rebuild and the generated configs use `uv run -p ">=3.10"` instead of `-p 3.12`. With the system-only pins above, an exact `3.12` fails on any machine whose system Python is another 3.1x (uv: "Python downloads are set to 'never'"). A hand-written MCP config that still says `-p 3.12` next to those pins needs the same change.

---

## 2026-10-06: File-neutral OpenSpec-gate warning (plugin 1.8.3)

`openspec-gate-warn.py` said "CLAUDE.md OPENSPEC OR STOP". Since the tiered template the rule lives in `AGENTS.md`, so a restructured project reworded it locally, and sync then kept the hook as a local edit, cut off from upstream fixes. The message now reads "Hard rule OPENSPEC OR STOP". Nothing to do: a project whose copy matches any earlier upstream version is updated on the next sync. A project that reworded it locally can take `.coograph/upstream/.claude/hooks/openspec-gate-warn.py`.

---

## 2026-10-06: Sync keeps local edits (plugin 1.8.2)

**Fixed: sync no longer overwrites a project's edits to template-managed files.** Until now every sync copied `.github/skills/`, `.github/retro/`, `.github/layout/`, `.github/code-graph/`, `.claude/hooks/`, `.claude/commands/coograph-*.md`, `.claude/settings.json` and the managed layout workflow over the project's copies, so a retro hook upgrade, a local fix or a house-style pass was reverted in the working tree on the next `git pull` of coograph, with only "N files updated" in the log.

Sync now records what it wrote in `.coograph/sync-manifest.json`. A file that matches neither that record nor any version coograph ever shipped is a local edit: sync keeps it, writes the upstream version to `.coograph/upstream/<path>`, and logs one line per file:

```
KEPT .claude/hooks/warn-scope.py (local edit). Upstream: .coograph/upstream/.claude/hooks/warn-scope.py. To take it, copy that file over yours and sync again.
```

What to do after this pull:

1. **Check whether an earlier sync already overwrote your edits:** `git status` / `git diff` in the project. A file sync replaced shows as modified against your last commit. To get your version back: `git restore <path>` (or `git checkout -- <path>`). The next sync keeps it.
2. **Read the `KEPT` lines** of the next sync (`.github/sync.log`, or `python3 .github/sync.py --dry-run --project <path>` in coograph). For each one, either keep your version, or take upstream with `cp .coograph/upstream/<path> <path>`, or merge the two by hand. A file whose content then equals upstream is tracked again from the next sync.
3. **If your project normalised em dashes in synced files,** add this to `openspec/config.yaml` before syncing, or every such file is reported as `KEPT`:

   ```yaml
   sync:
     em_dash: hyphen
   ```

Also in this release:

- `layout.py`: optional `guard.roots` in `layout.json` limits `--guard` to the listed paths; `--guard --strict` fails on changed code no feature doc covers (`UNCOVERED  <path>`); a deleted path is never reported uncovered. Nothing changes for a `layout.json` without them.
- `warn-scope.py`: silent outside the project and for anything under `openspec/`; the active change is the one whose `tasks.md` changed last; a backticked `tasks.md` path ending in `/` covers everything under it; one warning per path per session (repeats are recorded as `suppressed`); `NotebookEdit` is checked.
- Command, skill and agent briefs point at `AGENTS.md` § Hard rules and § Commands (the tier layout), with `.github/copilot-instructions.md` as the fallback. The review briefs also read `.github/instructions/review.instructions.md` when it exists.
- Re-running init refreshes template-managed files through `sync.py --project` in repo mode, or asks once in plugin mode, instead of replacing them.

**Update the installed plugin too** (marketplace Update to 1.8.2), so the plugin's own `warn-scope.py` matches the project's.

---

## 2026-10-06: Warn hooks the model can see (plugin 1.8.1)

`warn-scope.py`, `openspec-gate-warn.py`, `no-new-deps-warn.py` and `defect-warn.py` used to warn by printing to stderr and exiting 1. Claude Code never shows that text to the model, so since they shipped they warned only the user's log, not the agent. They now speak through `hookSpecificOutput.additionalContext` (the model) and `systemMessage` (the terminal) and exit 0. Registered projects get the new hooks on the next `git pull` of coograph.

**Update the installed plugin too** (marketplace Update to 1.8.1). When a project's hooks and the plugin's hooks are both wired, whichever copy claims the event first answers it; an old plugin copy still warns through stderr, and the model never sees it. The 2026-10-06 verification probe hit exactly this: the plugin copy won, and the agent saw nothing until the plugin was kept out.

Retro now counts a rule's outcomes only from its `outcomes_since` date on. That is a new, optional rule field: the last change to the hook's behaviour. `last_changed` still marks any edit and no longer touches outcome evidence. The seed sets `outcomes_since` on `scope`, `openspec-gate`, `no-new-deps` and `defect`, but `rules.json` is yours and is never overwritten, and no retro sets it for you. **Add `"outcomes_since": "<YYYY-MM-DD>"` to those four rules in `.github/retro/rules.json` by hand, using the date this project had both the new hooks and the updated plugin.** Not 2026-10-06: until both are updated here, the old hooks keep warning invisibly. Until you do, retro still weighs outcomes from warnings the agent never saw, and a rule could be proposed for `hook-block` on that false evidence.

---

## 2026-10-06: Instruction budget by tier (plugin 1.8.0, issue #43)

New: `.github/layout/` (`layout.py`, `layout.seed.json`, README, an opt-in CI workflow and pre-commit hook), `GOTCHAS.md`, `.claude/hooks/gotcha-surface.py`, the `/coograph-docs-restructure` skill, and a restructured template: hard rules and workflow live once in `AGENTS.md`, code conventions in `.github/copilot-instructions.md`, and `CLAUDE.md` imports both with `@`.

**Fixed: sync no longer overwrites `AGENTS.md`.** Before this, every sync of a project with the `vscode` tool copied the template `AGENTS.md` over the project's, destroying any edits. Sync now creates `AGENTS.md` only when it is missing. If yours was overwritten, restore it from git history (`git log -p -- AGENTS.md`).

Registered projects get, on the next `git pull` of coograph:

- `.github/layout/` and a `layout.json` seeded from `layout.seed.json`. It is yours from then on and is never overwritten. For a monorepo, set `routers` to one `<workspace>/AGENTS.md` glob per workspace; for a single package set it to `[]`.
- The gotcha hook, wired in `.claude/settings.json`. It does nothing until `GOTCHAS.md` has entries. Copy the template's `GOTCHAS.md` for the format, or let `/coograph-debug` and `/coograph-retro` propose entries.

Every Claude Code session start now adds a `[layout]` line when the instruction files are over budget, and `retro.py --status` prints a `layout:` line, with or without captured signals. A STRUCTURAL project is told to run `/coograph-docs-restructure` there, not only in a retro report.

On Windows with `core.autocrlf=true`, add `**/coograph-ultra-review/workflow.js text eol=lf` to your `.gitattributes` and re-checkout that file, or `/coograph-ultra-review` is refused for "control characters".

Check where you stand:

```bash
python3 .github/layout/layout.py --budget
```

- **Within budget:** nothing to do.
- **Over budget but not STRUCTURAL:** move duplicated rules to the one file that owns them (the report lists repeated paragraphs), and delete dated sections.
- **STRUCTURAL** (maps that grew into changelogs, a root file far over budget): run `/coograph-docs-restructure`. It writes an OpenSpec first and changes nothing until you approve.

**Budget semantics changed.** Retro's budget used to be `thresholds.instruction_token_budget` (8000) over `CLAUDE.md`, root `AGENTS.md`, `copilot-instructions.md` and `.github/instructions/*.md`. With `.github/layout/` installed it is `budgets.always_loaded` in `layout.json` (default 9000) over the always-loaded files with `@` imports resolved. `.github/instructions/*.md` count as on-demand now. Your reported total may drop, and the budget rises, so a project that read OVER may now read within. The old threshold still applies to projects without `.github/layout/`.

Manual steps, because `sync.py` never overwrites `CLAUDE.md`, `AGENTS.md`, or `.github/copilot-instructions.md`:

1. Optional, recommended: adopt the new root layout. Compare your three files with the template's. The anchors in `.github/layout/tests/test_layout.py` (`TemplateTests.ANCHORS`) list every rule and the one file it now lives in. `/coograph-docs-restructure` does this for you, and is the safer route for large files.
2. Add the routing row and gotcha pointer to your `AGENTS.md` (template § Routing), and the `/coograph-docs-restructure` row to the delegation table in `CLAUDE.md`.
3. Optional: run `/coograph-init` again and answer question 8 to add the CI workflow or the pre-commit hook. Init is idempotent and does not touch customized instruction files.

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
