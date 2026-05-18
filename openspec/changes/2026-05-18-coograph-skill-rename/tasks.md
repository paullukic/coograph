# Tasks: coograph-skill-rename

- [ ] **Rename skill directories**
  - Files: `.github/skills/{openspec-propose,openspec-apply,openspec-archive,openspec-explore,new-ticket,rebuild-code-graph}/`
  - Acceptance: `git mv` used for each rename (preserves history). Resulting tree contains `.github/skills/coograph-{propose,apply,archive,explore,new-ticket,rebuild-graph}/` and none of the old names. `coograph-init/` is untouched.

- [ ] **Update SKILL.md frontmatter `name:` in all 6 renamed skills**
  - Files: `.github/skills/coograph-{propose,apply,archive,explore,new-ticket,rebuild-graph}/SKILL.md` line 2.
  - Acceptance: each file's `name:` matches its new dir name. No frontmatter `name:` field still references an old name.

- [ ] **Update intra-skill cross-references**
  - Files:
    - `.github/skills/coograph-new-ticket/SKILL.md:54` — "openspec-propose" → "coograph-propose"
    - `.github/skills/coograph-apply/SKILL.md:92` — "openspec-archive" → "coograph-archive"
  - Acceptance: no SKILL.md body references an old skill name.

- [ ] **Migrate the new-ticket slash command wrapper**
  - Files:
    - `.claude/commands/project/new-ticket.md` → moved (via `git mv`) to `.claude/commands/coograph-new-ticket.md`
    - Update body: skill path `.github/skills/new-ticket/SKILL.md` → `.github/skills/coograph-new-ticket/SKILL.md`; "openspec-propose" → "coograph-propose"
  - Acceptance: `/coograph-new-ticket` resolves to the wrapper; `/project:new-ticket` no longer exists. Body has no old refs.

- [ ] **Update `.claude/commands/project/plan.md` references**
  - Files: `.claude/commands/project/plan.md` lines 20-21.
  - Acceptance: both refs read `coograph-propose`. No old names remain in this file.

- [ ] **Update README.md workflow table + prose**
  - Files: `README.md` lines 104, 106, 107, 112, 114.
  - Acceptance: workflow table rows for Start a new ticket / Propose / Apply / Archive list the new `coograph-*` names in both columns. Entry-point sentence at line 114 references `/coograph-new-ticket` and `coograph-propose`.

- [ ] **Update `.github/agents/planner.agent.md` references**
  - Files: `.github/agents/planner.agent.md` lines 50, 67, 68, 111, 116.
  - Acceptance: all hand-off references read `/coograph-propose` and `/coograph-apply`. No `openspec-propose` or `openspec-apply` strings remain.

- [ ] **Append MIGRATION.md section**
  - Files: `MIGRATION.md`.
  - Acceptance: new dated section documents the rename, includes a rename table, a one-liner cleanup recipe for orphan dirs in consumer projects, and a verify grep.

- [ ] **Phase 2 — Move 5 `/project:*` slash commands under `/coograph-*`**
  - Files (git mv): `.claude/commands/project/{plan,review,verify,debug,explore}.md` → `.claude/commands/coograph-{plan,review,verify,debug,search}.md` (explore → search to avoid skill collision).
  - Acceptance: `.claude/commands/project/` is empty (or contains no shipped coograph commands). `.claude/commands/` top-level lists all 7 wrappers: `coograph-init`, `coograph-new-ticket`, `coograph-plan`, `coograph-review`, `coograph-verify`, `coograph-debug`, `coograph-search`.

- [ ] **Phase 2 — Update prose references**
  - Files:
    - `README.md` lines 105, 108, 109, 110, 111, 114 — workflow table + entry-point sentence
    - `CLAUDE.md` lines 83, 85, 101, 109, 120-124 — workflow prose + Subagent Delegation table
    - `.github/skills/coograph-apply/SKILL.md:66` — Review-gate cross-reference
    - `.claude/commands/coograph-new-ticket.md:17` — handoff line
  - Acceptance: no active file references `/project:plan|review|verify|debug|explore`. Matches remain only in OpenSpec docs (this dir + archive) and MIGRATION.md.

- [ ] **Phase 2 — Append MIGRATION.md entry**
  - Files: `MIGRATION.md`.
  - Acceptance: new dated section under the existing rename entry documents the 5 slash-command moves with old→new mapping, cleanup recipe (`rm -rf .claude/commands/project/{plan,review,verify,debug,explore}.md` for users who synced phase-1 only).

- [ ] **Phase 3 — Patch `sync.py` so consumers receive the rename**
  - Files: `.github/sync.py`.
  - Acceptance:
    - New `OBSOLETE_PATHS` tuple lists the 6 old skill dirs + 6 old `.claude/commands/project/*.md` wrappers.
    - New `_cleanup_obsolete(project_path)` helper removes each entry that exists at the consumer site, logging each removal.
    - `.github/skills/` copy block lives outside `if "vscode" in tools` (always-copy). The vscode subdir loop no longer includes `skills`.
    - Inside `if "claude" in tools`, a new block globs `.claude/commands/coograph-*.md` from template and copies each to the consumer top-level `.claude/commands/`.
    - The existing `.claude/commands/project/` copy is guarded by `any(src.iterdir())` so it no-ops when the template's `project/` is empty.
    - `sync_project()` calls `_cleanup_obsolete(path)` after the copies and includes the removed count in the SYNC summary log line.
    - `python -m py_compile .github/sync.py` (or `python -c "import ast; ast.parse(open('.github/sync.py').read())"`) succeeds.

- [ ] **Phase 3 — Update MIGRATION.md and OpenSpec**
  - Files: `MIGRATION.md`, this OpenSpec.
  - Acceptance: MIGRATION.md notes that the manual cleanup commands are no longer required for consumers using auto-sync; manual hand-update of user-owned files (CLAUDE.md, copilot-instructions.md) is still required. OpenSpec proposal/tasks/spec all reflect phase-3 scope.

- [ ] **Verification**
  - Acceptance:
    1. Phase 1 grep `openspec-(propose|apply|archive|explore)|\bnew-ticket\b|rebuild-code-graph` returns matches only in `openspec/changes/archive/`, this OpenSpec dir, and MIGRATION.md.
    2. Phase 2 grep `/project:(plan|debug|review|verify|explore)` returns matches only in this OpenSpec dir, MIGRATION.md, and `openspec/changes/archive/`.
    3. `ls .github/skills/` shows only `coograph-*` directories.
    4. `ls .claude/commands/project/` is empty.
    5. `ls .claude/commands/` lists 7 `coograph-*` wrappers.
    6. `grep -n "name:" .github/skills/coograph-*/SKILL.md` shows each frontmatter `name:` matching its directory.
    7. `python -c "import ast; ast.parse(open('.github/sync.py').read())"` exits 0.
