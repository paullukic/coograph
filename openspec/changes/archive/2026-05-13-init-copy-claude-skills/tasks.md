# Tasks: init-copy-claude-skills

- [x] **Promote `.github/skills/` to always-copy in SKILL.md Step 3**
  - Files: `.github/skills/coograph-init/SKILL.md`
  - Acceptance: the "Always copy" bullet list at the top of Step 3 contains a new line `- .github/skills/ (all skill directories — every supported tool delegates to these)` between the `.github/instructions/` and `openspec/config.yaml` entries; the `**For VS Code Copilot:**` block no longer mentions `.github/skills/` (line removed); the trailing "Copy `.github/skills/coograph-init/` too." instruction is removed from each of the six per-tool blocks (Codex CLI, OpenCode, Cursor, Windsurf, Aider, Cline), with a brief preserved note that the tool *consumes* the canonical skill; the line-121-area parenthetical is rewritten to drop "except Claude Code" and instead read along the lines of: *"`.github/skills/` is in the always-copy section; do not re-copy in per-tool selections."*

- [x] **Sync user-facing summary in `.claude/commands/coograph-init.md`**
  - Files: `.claude/commands/coograph-init.md`
  - Acceptance: the "Always (shared by both tools)" line in the Step 3 summary table now lists `.github/skills/` between `.github/instructions/` and `openspec/config.yaml`; the "VS Code Copilot:" line no longer lists `.github/skills/`; no other content changed.

- [x] **Back-fill paul's coograph-website + propagate to registered consumers**
  - Files: none in this repo (operational task)
  - Acceptance: documented one-liner executed for `C:/paul/code/coograph-website/`: `cp -r .github/skills/ <target>/.github/skills/` from coograph repo root; verify `<target>/.github/skills/new-ticket/SKILL.md` exists; if other entries exist in `projects.json` with `tools` including `"claude"`, apply the same back-fill to each (manual loop — automation deferred to a future OpenSpec).

- [x] **Verification**
  - Acceptance: (1) `grep -r "except Claude Code" .github/skills/coograph-init/SKILL.md` returns no matches; (2) `grep -c ".github/skills/" .github/skills/coograph-init/SKILL.md` returns a count consistent with the new always-copy listing + per-tool *references* only (no per-tool *copy directives*); (3) a smoke dry-run of `/coograph-init` (no actual file copy — read-through review) confirms the procedure now copies skills for a Claude-only selection; (4) `cd C:/paul/code/coograph-website && ls .github/skills/new-ticket/SKILL.md` succeeds after back-fill task; (5) `/project:new-ticket` invoked in `coograph-website` resolves its referenced SKILL.md locally without falling back to sibling repo reads.
