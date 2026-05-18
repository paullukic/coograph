# Proposal: Unify skill names under `coograph-*` namespace

## Why

Skill naming is split across two prefixes and two no-prefix names, fragmenting slash-command autocomplete and hiding the umbrella product:

| Current | Issue |
|---|---|
| `coograph-init` | unified ✓ |
| `openspec-propose` | different prefix |
| `openspec-apply` | different prefix |
| `openspec-archive` | different prefix |
| `openspec-explore` | wrong category — explore is general codebase search, not an OpenSpec phase |
| `new-ticket` | no prefix |
| `rebuild-code-graph` | no prefix |

Two concrete problems:

1. **Autocomplete fragmentation.** Typing `/co` surfaces one skill; `/op` surfaces four. Users have to remember which prefix maps to which action.
2. **`openspec-explore` mislabels itself.** Explore is general codebase search — not an OpenSpec phase (Plan / Propose / Apply / Review / Archive). The current name implies spec work; it isn't.

Tracked in issue [#9](https://github.com/paullukic/coograph/issues/9).

## Goals

- All 6 affected skills renamed under the `coograph-*` prefix to match `coograph-init`.
- After rename, typing `/coograph-` surfaces the entire toolkit.
- The OpenSpec **system** (storage layer: `openspec/changes/`, spec format, frontmatter) keeps its name. Only **skills** are renamed.
- Slash-command wrapper for new-ticket moved to top-level under the new name so `/coograph-new-ticket` is the canonical entry.
- Every active reference in the repo points to the new names. Archived OpenSpecs keep their historical names.
- `MIGRATION.md` documents the rename for existing consumers.

## Non-Goals

- Compatibility shims, aliases, or symlinks for old names. Hard cut.
- Renaming `coograph-init` (already correct).
- Updating archived OpenSpecs in `openspec/changes/archive/` — frozen history.
- Landing the cross-tool drift checker from issue [#2](https://github.com/paullukic/coograph/issues/9) first. Issue #9 noted the bundling as preferred but it's not blocking; we'll verify by exhaustive grep instead.
- Renaming the existing `coograph-explore` skill (thinking-mode prompt — different purpose from `/project:explore` code-search). Phase 2 handles the naming collision by routing `/project:explore` to `/coograph-search` instead, keeping both functions distinct.

## Phase 2 — Unify `/project:*` slash commands under `/coograph-*`

Phase 1 left 5 generic project-flow slash commands at `.claude/commands/project/`. These ship with coograph and should sit in the same namespace as the rest of the toolkit. Phase 2 (added 2026-05-18, after phase-1 implementation) renames them so `/coograph-` autocomplete surfaces the entire shipped command set, not a subset.

| Old | New | Notes |
|---|---|---|
| `/project:plan` | `/coograph-plan` | 1:1 |
| `/project:review` | `/coograph-review` | 1:1 |
| `/project:verify` | `/coograph-verify` | 1:1 |
| `/project:debug` | `/coograph-debug` | 1:1 |
| `/project:explore` | `/coograph-search` | Renamed to "search" to avoid collision with the existing `coograph-explore` skill (thinking-mode prompt from former `openspec-explore`). `/project:explore` was a tactical codebase-search Q&A wrapper; "search" describes that more accurately. |

After Phase 2, `/coograph-` autocomplete surfaces:
- `/coograph-init`, `/coograph-doctor` (planned)
- `/coograph-new-ticket`, `/coograph-plan`, `/coograph-propose`, `/coograph-apply`, `/coograph-review`, `/coograph-verify`, `/coograph-archive`
- `/coograph-debug`, `/coograph-search`, `/coograph-rebuild-graph`
- `coograph-explore` skill (thinking-mode, invoked when user requests exploration mode)

## Decisions

- **`coograph-*` prefix, no exceptions.** The product is coograph; skill names should reflect it. `openspec` is an internal storage format and shouldn't leak into user-facing slash commands.
- **Move `.claude/commands/project/new-ticket.md` to `.claude/commands/coograph-new-ticket.md`** — top-level, matching `.claude/commands/coograph-init.md`. The `/project:` namespace is reserved for generic project-flow commands (plan, review, verify, debug, explore); `coograph-*` skills get their own top-level wrappers when one is needed for Claude Code substitutions.
- **No new slash wrappers for propose/apply/archive/explore/rebuild-graph.** They're invoked directly via skill auto-registration — `/coograph-propose` etc. work without a `.claude/commands/` file. Only `new-ticket` had a wrapper, because it needed Claude Code substitutions for `vscode_askQuestions` etc.
- **`rebuild-code-graph` → `coograph-rebuild-graph`** (not `coograph-rebuild-code-graph`). Issue #9 chose the shorter form; matches their listing.

## Impact

**Renamed directories (6):**
- `.github/skills/openspec-propose/` → `.github/skills/coograph-propose/`
- `.github/skills/openspec-apply/` → `.github/skills/coograph-apply/`
- `.github/skills/openspec-archive/` → `.github/skills/coograph-archive/`
- `.github/skills/openspec-explore/` → `.github/skills/coograph-explore/`
- `.github/skills/new-ticket/` → `.github/skills/coograph-new-ticket/`
- `.github/skills/rebuild-code-graph/` → `.github/skills/coograph-rebuild-graph/`

**Files modified:**
- 6 × `SKILL.md` frontmatter `name:` fields (inside the renamed dirs).
- `.github/skills/coograph-new-ticket/SKILL.md:54` — cross-link to propose skill.
- `.github/skills/coograph-apply/SKILL.md:92` — cross-link to archive skill.
- `.claude/commands/project/plan.md:20-21` — text refs.
- `.claude/commands/project/new-ticket.md` → moved to `.claude/commands/coograph-new-ticket.md`; body updated.
- `README.md` — workflow table (lines 104, 106, 107, 112, 114) and prose entry-point sentence.
- `.github/agents/planner.agent.md` — lines 50, 67, 68, 111, 116.
- `MIGRATION.md` — new section appended.

**Slash-command surface change (Phase 1 + Phase 2):**
- Removed: `/project:new-ticket`, `/project:plan`, `/project:review`, `/project:verify`, `/project:debug`, `/project:explore`.
- Added: `/coograph-new-ticket`, `/coograph-propose`, `/coograph-apply`, `/coograph-archive`, `/coograph-explore` (skill), `/coograph-rebuild-graph`, `/coograph-plan`, `/coograph-review`, `/coograph-verify`, `/coograph-debug`, `/coograph-search`.

**Phase 2 file moves (`.claude/commands/`):**
- `project/plan.md` → `coograph-plan.md`
- `project/review.md` → `coograph-review.md`
- `project/verify.md` → `coograph-verify.md`
- `project/debug.md` → `coograph-debug.md`
- `project/explore.md` → `coograph-search.md`

**Phase 2 additional doc updates:**
- `README.md` — workflow table rows for Plan/Review/Verify/Debug/Explore + entry-point sentence at line 114.
- `CLAUDE.md` — `## Subagent Delegation` table (lines 120-124) + 4 prose references (lines 83, 85, 101, 109).
- `.github/skills/coograph-apply/SKILL.md:66` — Review-gate cross-reference.
- `.claude/commands/coograph-new-ticket.md:17` — handoff line.
- `MIGRATION.md` — appended phase-2 entry with mapping table.

## Phase 3 — Patch `sync.py` so consumers actually receive the rename

`sync.py` is the script the post-merge git hook runs for every project listed in `projects.json`. Before this patch it had two gaps that would make phases 1 + 2 invisible to existing consumers:

1. **Top-level `.claude/commands/coograph-*.md` wrappers were never synced.** Sync only copied `.claude/commands/project/` (subdir). The new 7 `coograph-*.md` files at the top level were skipped. Consumers wouldn't see `/coograph-new-ticket`, `/coograph-plan`, etc.
2. **`.github/skills/` was only synced for VS Code Copilot consumers.** Claude-only consumers got nothing — old `openspec-*/`, `new-ticket/`, `rebuild-code-graph/` dirs would persist; new `coograph-*/` dirs wouldn't appear.

A third gap (no auto-cleanup of renamed paths) would have left old dirs/files in place alongside the new ones, cluttering `/` autocomplete forever.

Phase 3 patches `sync.py`:

- **`OBSOLETE_PATHS` constant** lists every path a previous template version placed in consumers that has since been renamed or removed. After each sync, `_cleanup_obsolete()` walks this list and removes any that exist at the consumer site. Adding entries here is now the canonical way to propagate a rename or removal.
- **Promote `.github/skills/` to always-copy** — moved outside the `if "vscode" in tools` block, removed from the per-tool subdir loop to avoid double-copy. Mirrors what `coograph-init` does at install time (archive OpenSpec 2026-05-13-init-copy-claude-skills).
- **Add top-level `coograph-*.md` glob to the Claude tool block** — globs `.claude/commands/coograph-*.md` from template and copies each to the consumer's `.claude/commands/`.
- **Keep `.claude/commands/project/` mirror for backwards compatibility** — guarded with `any(src.iterdir())` so it logs nothing when the template's `project/` is empty (current state).

After this patch, an existing consumer running `git pull` will:

1. Receive new `coograph-*/` skill dirs and `coograph-*.md` slash wrappers (additive).
2. Have old `openspec-*/`, `new-ticket/`, `rebuild-code-graph/` dirs and old `project/*.md` wrappers removed (subtractive).
3. Keep their own `CLAUDE.md` / `copilot-instructions.md` untouched (SKIP_FILES). They still need to hand-update those — `MIGRATION.md` documents the grep.

**Dependencies affected:** none.

**Downstream consumer impact:**
- Existing Claude-only installs that synced before this change have the old skill dirs and slash names. After their next `sync.py` pull they'll receive the new dirs but **also** retain the old dirs until manually removed (sync doesn't delete). `MIGRATION.md` documents the cleanup one-liner.

## Risks

- **Muscle memory.** Users typing `/project:new-ticket` will get "command not found." Migration note + obvious replacement (`/coograph-new-ticket`) keeps friction low.
- **Stale references in user projects.** Downstream `CLAUDE.md` files referencing `openspec-propose` etc. won't auto-update — `sync.py` doesn't touch user-owned files. Migration note calls this out with a grep recipe.
- **Sync leaves orphan dirs.** `sync.py` adds files but doesn't remove the old skill directories from consumer projects. Cleanup is one-line `rm -rf` per old name, documented in MIGRATION.
- **Archive consistency.** Archived OpenSpecs still reference old names. Acceptable — archives reflect history at the time of archival. New OpenSpecs will use new names.
