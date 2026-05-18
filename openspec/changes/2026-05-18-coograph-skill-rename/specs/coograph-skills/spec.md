# Spec: coograph-* skill naming convention

## Requirements

- All user-facing skills published by the coograph template use the `coograph-*` prefix in their directory name and SKILL.md frontmatter `name:` field.
- Skill directories live at `.github/skills/coograph-<action>/` with a `SKILL.md` whose frontmatter `name:` field equals `coograph-<action>` (verbatim).
- The OpenSpec storage layer (`openspec/changes/<date>-<slug>/`, `proposal.md`, `tasks.md`, spec files, frontmatter format) is unchanged. Only skill names move.
- All shipped Claude Code slash-command wrappers — both skill wrappers (`coograph-init`, `coograph-new-ticket`) AND generic project-flow commands (`plan`, `review`, `verify`, `debug`, `search`) — live at `.claude/commands/coograph-<action>.md` (top-level), not under `.claude/commands/project/`. The `.claude/commands/project/` directory holds only user-authored project-specific commands (none ship by default).
- The `explore` slash command (codebase search Q&A) is renamed to `/coograph-search` to avoid collision with the `coograph-explore` skill, which is a separate thinking-mode prompt.
- Cross-references between skills (in SKILL.md bodies, wrapper command files, agent definitions, README, etc.) use the new `coograph-*` names. No active file references the old names: `openspec-propose`, `openspec-apply`, `openspec-archive`, `openspec-explore`, `new-ticket`, `rebuild-code-graph`.
- Archived OpenSpecs in `openspec/changes/archive/` keep their historical names. They are not edited.

## Scenarios

### Scenario: Autocomplete surfaces the full toolkit
- **Given**: a Claude Code project initialized with coograph after this change
- **When**: the user types `/coograph-` at the prompt
- **Then**: autocomplete suggests every shipped command: `/coograph-init`, `/coograph-new-ticket`, `/coograph-plan`, `/coograph-propose`, `/coograph-apply`, `/coograph-review`, `/coograph-verify`, `/coograph-archive`, `/coograph-debug`, `/coograph-search`, `/coograph-rebuild-graph` (any subset that's installed)

### Scenario: Old slash names removed cleanly
- **Given**: a freshly synced consumer project
- **When**: the user types `/project:new-ticket`, `/project:plan`, `/project:review`, `/project:verify`, `/project:debug`, or `/project:explore`
- **Then**: Claude Code returns command-not-found (the wrappers were moved, not aliased)

### Scenario: SKILL.md frontmatter matches directory
- **Given**: any renamed skill directory under `.github/skills/coograph-*/`
- **When**: a reader inspects `SKILL.md` line 2
- **Then**: the `name:` value equals the directory's basename verbatim

### Scenario: No active file references old names
- **Given**: the post-rename repository
- **When**: a reader greps `openspec-(propose|apply|archive|explore)|new-ticket|rebuild-code-graph` across all tracked files
- **Then**: matches appear only inside `openspec/changes/archive/` (frozen history); zero matches in active code, docs, or skill files

### Scenario: Cross-skill references use new names
- **Given**: any active SKILL.md, agent definition, slash-command wrapper, or README workflow table
- **When**: a reader greps for references to other skills
- **Then**: every reference uses the `coograph-*` form

### Scenario: MIGRATION.md documents the rename
- **Given**: an existing consumer project synced before this change
- **When**: the user reads `MIGRATION.md`
- **Then**: a dated section documents (1) the old-to-new mapping, (2) a one-liner to remove orphan `.github/skills/<old>/` directories, (3) a verify grep, and (4) a note that downstream `CLAUDE.md` references must be hand-updated

### Scenario: Consumer `git pull` delivers the rename automatically
- **Given**: an existing consumer project registered in `projects.json` with `"tools": ["claude"]`, synced before the rename (its `.github/skills/` contains the old `openspec-*/`, `new-ticket/`, `rebuild-code-graph/` dirs; its `.claude/commands/project/` contains the old `plan.md`, `review.md`, etc.)
- **When**: the post-merge hook runs `sync.py` after `git pull` pulls in this OpenSpec
- **Then**:
  - The consumer's `.github/skills/` now contains all 7 `coograph-*/` directories (additive).
  - The consumer's `.claude/commands/` now contains all 7 `coograph-*.md` wrappers (additive).
  - The 6 old skill dirs and 6 old `project/*.md` wrappers listed in `OBSOLETE_PATHS` have been removed (subtractive).
  - The consumer's `CLAUDE.md` and `.github/copilot-instructions.md` are untouched (SKIP_FILES).
  - The sync log line for that project reports both the copy count and the obsolete-removal count.
