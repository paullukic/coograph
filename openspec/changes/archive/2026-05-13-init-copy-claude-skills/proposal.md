# Proposal: Copy `.github/skills/` to Claude Code installs

## Why

`coograph-init` ships `.claude/commands/project/*.md` thin wrappers that delegate to skill files at `.github/skills/<name>/SKILL.md` for the full procedure. But the current init flow only copies `.github/skills/` when the **VS Code Copilot** tool is selected. Claude-only installs end up with broken pointers.

**Confirmed in two consumer commands:**
- `.claude/commands/project/new-ticket.md:3` — *"The full procedure lives in `.github/skills/new-ticket/SKILL.md`"*
- `.claude/commands/coograph-init.md:3` — *"The full procedure is in `.github/skills/coograph-init/SKILL.md`"*

**Confirmed broken in the field:** a Claude-only install of `coograph-init` in `paullukic/coograph-website` (sibling repo) is missing `.github/skills/` entirely. The `/project:new-ticket` slash command had to fall back to reading the source files from the coograph product repo directly. Other consumers without sibling access would silently fail.

**Skills that Claude Code consumers depend on (currently uncopied):**
- `new-ticket/`
- `coograph-init/` (the project should be able to re-init others)
- `openspec-propose/`, `openspec-apply/`, `openspec-archive/`, `openspec-explore/`
- `rebuild-code-graph/`

Line 121 of `SKILL.md` makes the wrong assumption explicit: *"`.github/skills/coograph-init/` is needed by every tool except Claude Code — copy once"*. This is wrong on both counts (Claude needs it, and Claude needs more skills than just `coograph-init/`).

## Goals

- Add `.github/skills/` (entire directory tree) to the **always-copy** section of `coograph-init`, alongside `.github/copilot-instructions.md` and `.github/instructions/` (precedent: shared between every tool).
- Remove the "except Claude Code" carve-out at line 121 of `SKILL.md`.
- Update the user-facing summary in `.claude/commands/coograph-init.md` so the documented copy list matches the actual procedure.
- Provide a one-line back-fill recipe in the proposal so existing Claude-only consumers (paul's own `coograph-website`) can self-heal.

## Non-Goals

- Migrating skill content into `.claude/commands/*` (inline-everything approach). Rejected — it duplicates content and drifts on upgrade.
- Adding a sync verification step inside `coograph-init` (would belong in a separate Step 5 enhancement OpenSpec).
- Restructuring tool-section copy rules for VS Code, Codex, OpenCode, etc. — they already include `.github/skills/`, no change needed.
- Back-filling all already-registered consumer projects automatically (out of scope; users self-heal via the recipe).

## Decisions

- **Always-copy over Claude-section** — `.github/skills/` is consumed by Claude Code, VS Code Copilot, Codex CLI, OpenCode, Cursor, Windsurf, Aider, and Cline (all eight tools the init supports). That's "always-copy" semantics, not tool-specific.
- **Remove the VS Code Copilot duplicate listing** — once it's always-copy, the VS Code section line *".github/skills/ (all skill directories including coograph-init/...)"* should be deleted to avoid double-copy assertions.
- **Keep per-tool `coograph-init/` listings for other tools (Codex/OpenCode/Cursor/Windsurf/Aider/Cline)** — even though `.github/skills/` is now always-copied, those sections still describe *why* the directory matters for that tool ("delegates to the canonical procedure"). Trim wording so they don't claim to copy the directory themselves; just reference it.
- **Update line 121 parenthetical** — replace "every tool except Claude Code" with the truth: it's always-copied for every tool.

## Impact

**Files to modify:**
- `.github/skills/coograph-init/SKILL.md` — Step 3
  - Add `.github/skills/` bullet to always-copy section (after `.github/instructions/`)
  - Remove `.github/skills/` line from `**For VS Code Copilot:**` block
  - Remove "Copy `.github/skills/coograph-init/` too." trailing sentences from Codex/OpenCode/Cursor/Windsurf/Aider/Cline sections (still mention the dependency, but no per-tool copy)
  - Rewrite the line-121 parenthetical: remove "except Claude Code" carve-out
- `.claude/commands/coograph-init.md` — Step 3 summary table (lines 19-24)
  - Add `.github/skills/` to "Always (shared by both tools)" line

**Files to create:**
- `openspec/changes/2026-05-13-init-copy-claude-skills/specs/coograph-init/spec.md`
- `openspec/changes/2026-05-13-init-copy-claude-skills/tasks.md`

**Dependencies affected:** none.

**Downstream consumer impact:**
- Future `coograph-init` runs on Claude-only setups will get the full `.github/skills/` tree.
- Existing Claude-only consumers (e.g. `paullukic/coograph-website`) need a one-time manual back-fill. Recipe documented in `tasks.md` verification step.

## Risks

- **Disk footprint** — copying `.github/skills/` adds 7 directories of markdown. Each SKILL.md is ~5-15kb. Total ~70kb extra per consumer. Negligible.
- **Future skill additions** — adding a new skill to coograph automatically propagates to all consumers on next sync (via `setup.sh` / `projects.json` pull). This is *desired* behavior — same as `.github/instructions/`. Document that adding skills now affects all registered consumers.
- **Sync conflicts** — if a consumer hand-edits a skill file in their copy, the next sync overwrites it. Existing pattern for `.github/instructions/` already handles this with the overwrite/skip/section prompt. No new risk.
- **Documentation drift** — the line-121 parenthetical has been wrong for ≥ 3 commits per `git log` of the file. After this fix, add a smoke test (out of scope here) that greps `SKILL.md` for the obsolete phrase. Filed mentally; not in tasks.
