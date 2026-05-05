---
name: openspec-apply
description: Implement tasks from an OpenSpec change. Use when the user wants to start or continue implementing a proposed change.
argument-hint: Change name or slug (e.g., "add-dark-mode"). If omitted, will prompt for selection.
license: MIT
metadata:
  author: copilot-template
  version: "2.0"
---

Implement tasks from an OpenSpec change in `openspec/changes/`.

---

## Step 1: Identify the change

If a name is provided, look for `openspec/changes/<name>/` or `openspec/changes/<date>-<name>/`.

If no name is provided:
- List directories in `openspec/changes/` (excluding `archive/`)
- If only one active change exists, use it and announce: "Using change: <name>"
- If multiple exist, ask the user to select

## Step 2: Read context

Read these files from the change directory:
- `proposal.md` — goals, scope, decisions
- `specs/<capability>/spec.md` — requirements and acceptance criteria
- `tasks.md` — task list and completion status

If any file is missing, report which one and ask the user for its location. Do not confabulate contents.

Show current progress: "N/M tasks complete — working on: <next task>"

## Step 3: Classify change size

- **Quick** (≤3 tasks, ≤50 lines changed, no new files): skip full self-verification and auto-review — run a lightweight logic check instead.
- **Standard** (everything else): run all verification and review steps.

## Step 4: Implement tasks

**CRITICAL**: Follow `tasks.md` literally. Never reinterpret or regenerate tasks. Never invent field names, API types, or schemas that don't exist in the actual source code.

For each pending task:
1. Announce which task is being worked on
2. Read every source file to be modified — in full — before making any change
3. Grep for every field/type name before using it. If a name cannot be found: STOP, report what's missing, ask the user
4. Make the code changes
5. Every task MUST result in actual file edits — if a task produces zero edits, it is not complete
6. Mark complete in tasks.md: `- [ ]` → `- [x]`

**Pause if:** task is unclear, implementation reveals a design issue, or an error is encountered.

## Step 5: Self-verification (standard changes only)

Before invoking the Reviewer:

1. **Feature inventory**: compare modified files against their original (`git show HEAD:<path>`). List features: PRESERVED or REMOVED. Restore any removed without explicit spec request.
2. **Spec text match**: re-read the spec. Verify every requirement is implemented. Flag mismatches.
3. **i18n checks** (if project uses i18n): verify new/changed keys exist in all language files.

Fix any failures before proceeding.

## Step 6: Review gate (standard changes only)

Invoke `@Reviewer` (VS Code) or run `/project:review` (Claude Code).

- If **REQUEST_CHANGES**: add findings as new tasks under a "Review Fixes" heading in `tasks.md`. Implement fixes, then re-review changed files only.
- **Circuit breaker**: after 3 review cycles on the same area, STOP and ask the user.
- If **APPROVE**: proceed to build verification.

**Lightweight gate (quick changes):** Run a targeted logic check on changed files. Fix issues before build verification.

## Step 7: Build verification

Read `.github/copilot-instructions.md` for the project's build/quality commands. Run them in documented order. Fix failures and re-run.

If commands are not documented, ask the user.

## Step 8: Report

```
## Implementation Complete

**Change:** <change-name>
**Progress:** N/N tasks complete

### Completed This Session
- [x] Task 1
- [x] Task 2

All tasks complete. Ready to archive — run openspec-archive.
```

If paused:
```
## Implementation Paused

**Progress:** N/M tasks complete

### Issue
<description>

**Options:**
1. <option>
2. <option>
```

## Guardrails

- Read all context files before starting
- Keep changes minimal and scoped to each task
- Pause on errors, blockers, or unclear requirements — never guess
- Update task checkbox immediately after completing each task
- Touch only files in the task scope — no drive-by improvements

## Red Flags

- Tasks marked done with zero file edits
- More than 100 lines written without running build/tests
- Skipping self-verification because "changes are small"
- Touching files outside task scope "while I'm here"
- Build or tests broken between tasks and not immediately fixed
