---
name: openspec-archive
description: Archive a completed change. Use when implementation is done and the change is ready to be moved to the archive.
argument-hint: Change name to archive. If omitted, will prompt for selection.
license: MIT
metadata:
  author: copilot-template
  version: "2.0"
---

Archive a completed OpenSpec change by moving it from `openspec/changes/` to `openspec/changes/archive/`.

---

## Step 1: Identify the change

If a name is provided, look for `openspec/changes/<name>/` or `openspec/changes/<date>-<name>/`.

If no name is provided:
- List directories in `openspec/changes/` (excluding `archive/`)
- Ask the user to select — do NOT auto-select

## Step 2: Check task completion

Read `tasks.md` and count:
- `- [x]` items (complete)
- `- [ ]` items (incomplete)

If incomplete tasks exist, warn the user:
> "X tasks are still incomplete. Archive anyway?"

Wait for confirmation before proceeding. Do not skip this check.

## Step 3: Check for delta specs

Look for `openspec/changes/<name>/specs/` — if it contains spec files, compare each against its counterpart in `openspec/specs/<capability>/spec.md`.

If delta specs exist:
- Show what would change (additions, modifications, removals)
- Ask: "Sync these specs to the main spec files before archiving?"
- If yes: merge each delta spec into its corresponding main spec file. Show what was merged.
- If no: proceed without syncing (delta specs will be archived with the change)

If no delta specs exist: skip this step.

## Step 4: Archive

Create the archive directory if it doesn't exist:
```bash
mkdir -p openspec/changes/archive
```

Generate the target name: `YYYY-MM-DD-<slug>` using today's date.

Check if the target already exists — if so, fail with a clear error and ask the user how to proceed.

Move the change directory:
```bash
mv openspec/changes/<name> openspec/changes/archive/YYYY-MM-DD-<slug>
```

## Step 5: Report

```
## Archive Complete

**Change:** <name>
**Archived to:** openspec/changes/archive/YYYY-MM-DD-<slug>/
**Specs:** [Synced to main specs / No delta specs / Sync skipped]
**Tasks:** [All complete / X incomplete — user confirmed]
```

## Guardrails

- Never auto-select a change — always ask the user
- Always check task completion and warn if incomplete — never silently skip
- Always run the delta spec assessment if specs exist
- If the archive target already exists, fail clearly — do not overwrite
- Show a summary of what happened
