# Spec: coograph-init copies .github/skills/ on every install

## Requirements

- `.github/skills/` (entire tree) is listed in the **always-copy** section of `.github/skills/coograph-init/SKILL.md` Step 3, alongside `.github/copilot-instructions.md` and `.github/instructions/`.
- The `**For VS Code Copilot:**` block in Step 3 no longer lists `.github/skills/` (deduplication).
- Per-tool blocks for Codex CLI, OpenCode, Cursor, Windsurf, Aider, and Cline no longer issue trailing "Copy `.github/skills/coograph-init/` too." instructions — they may still reference the dependency but the copy is owned by always-copy.
- The parenthetical at SKILL.md line ~121 ("Multi-tool selections") does not contain the phrase "except Claude Code" with respect to `.github/skills/`.
- `.claude/commands/coograph-init.md` Step 3 summary lists `.github/skills/` in the "Always (shared by both tools)" line.
- After a Claude-only init run, the target project contains `.github/skills/coograph-init/SKILL.md`, `.github/skills/new-ticket/SKILL.md`, `.github/skills/openspec-propose/SKILL.md`, `.github/skills/openspec-apply/SKILL.md`, `.github/skills/openspec-archive/SKILL.md`, `.github/skills/openspec-explore/SKILL.md`, and `.github/skills/rebuild-code-graph/SKILL.md`.

## Scenarios

### Scenario: Claude-only init now copies skills
- **Given**: a fresh target project with no `.github/skills/` directory
- **When**: user runs `/coograph-init` selecting only "Claude Code" in Step 1 question 2
- **Then**: after init completes, `<target>/.github/skills/` exists and contains at minimum `coograph-init/`, `new-ticket/`, `openspec-propose/`, `openspec-apply/`, `openspec-archive/`, `openspec-explore/`, and `rebuild-code-graph/` subdirectories, each with a non-empty `SKILL.md`

### Scenario: Multi-tool init does not double-copy
- **Given**: a fresh target project
- **When**: user runs `/coograph-init` selecting both "Claude Code" AND "VS Code Copilot"
- **Then**: `.github/skills/` is copied exactly once (no duplicate copy operation, no overwrite prompt for the same files), and the resulting tree is identical to the Claude-only case for skills content

### Scenario: Existing always-copy semantics preserved
- **Given**: any tool selection
- **When**: init runs
- **Then**: `.github/copilot-instructions.md`, `.github/instructions/`, and `openspec/config.yaml` are still copied (existing always-copy behavior unchanged), and `.github/skills/` is now copied alongside them

### Scenario: Documentation consistency
- **Given**: the post-fix `.github/skills/coograph-init/SKILL.md` and `.claude/commands/coograph-init.md`
- **When**: a reader greps either file for `except Claude Code` in the context of `.github/skills/`
- **Then**: zero matches (the obsolete carve-out is gone)

### Scenario: Back-fill recipe works for paul's coograph-website
- **Given**: `C:/paul/code/coograph-website/` initialized before this fix (no `.github/skills/`)
- **When**: user runs the documented back-fill `cp -r <coograph>/.github/skills/ <target>/.github/skills/`
- **Then**: `/project:new-ticket` and other Claude command wrappers resolve their referenced SKILL.md files locally, without falling back to sibling repo reads
