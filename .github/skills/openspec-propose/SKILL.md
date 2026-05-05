---
name: openspec-propose
description: Propose a new change with all artifacts generated in one step. Use when the user wants to describe what they want to build and get a complete proposal with specs and tasks ready for implementation.
argument-hint: Change name or description (e.g., "add user settings page").
license: MIT
metadata:
  author: copilot-template
  version: "2.0"
---

Propose a new change — investigate the codebase, create all artifacts, and wait for approval before implementing.

---

## Step 1: Understand what to build

If no input was provided, ask the user:
> "What change do you want to work on? Describe what you want to build or fix."

From their description, derive a kebab-case slug (e.g., "add user auth"). Wait for their answer before proceeding.

## Step 2: Investigate the codebase

Before writing anything:
1. Read `.github/copilot-instructions.md` for conventions and stack.
2. Search for related files, existing patterns, integration points, and risks relevant to this change.
3. Identify which files will likely be modified or created.

## Step 3: Create the change directory

Create `openspec/changes/<YYYY-MM-DD>-<slug>/` using today's date.

Create `.openspec.yaml` with:
```yaml
schema: spec-driven
name: <slug>
created: <YYYY-MM-DD>
```

## Step 4: Create proposal.md

Write `openspec/changes/<slug>/proposal.md`:

```markdown
# Proposal: <human-readable title>

## Why
[Problem being solved and motivation]

## Goals
- [Concrete, measurable deliverable]

## Non-Goals
- [Explicit out-of-scope items]

## Decisions
- [Key design decisions and why they were made]

## Impact
- Files to modify: [specific file paths]
- Files to create: [specific file paths]
- Dependencies affected: [if any]

## Risks
- [Risk]: [mitigation]
```

## Step 5: Create specs/<capability>/spec.md

Write `openspec/changes/<slug>/specs/<capability>/spec.md`:

```markdown
# Spec: <capability name>

## Requirements
- [Requirement 1]
- [Requirement 2]

## Scenarios
### Scenario: <description>
- Given: [precondition]
- When: [action]
- Then: [expected outcome]
```

## Step 6: Create tasks.md

Write `openspec/changes/<slug>/tasks.md` with 3-8 tasks grouped by logical unit (not per-file):

```markdown
# Tasks: <change-name>

- [ ] **<Logical group title>** — [description of what this group accomplishes]
  - Files: [file paths]
  - Acceptance: [measurable criteria]

- [ ] **Verification** — Run quality gates and confirm all acceptance criteria are met
```

**Rules for tasks:**
- Group mechanical changes by logical unit, not per-file ("add validation" not "update file X, update file Y")
- 3-8 tasks max — more than 10 means the scope is too large, split the change
- Every task must have measurable acceptance criteria
- Final task is always verification

## Step 7: Verify artifacts

Before presenting to the user, confirm:
- [ ] `proposal.md` has all sections (Why, Goals, Non-Goals, Decisions, Impact, Risks)
- [ ] Impact section lists specific file paths, not vague module names
- [ ] `tasks.md` has 3-8 tasks grouped by logical unit
- [ ] Every task has acceptance criteria
- [ ] Risks section is honest — not empty

## Step 8: Present and wait for approval

Show the user:
- Change location: `openspec/changes/<slug>/`
- Summary of proposal (1-2 sentences)
- Task list

Then ask: "Does this capture what you want? Say **proceed** to start implementation, or tell me what to adjust."

**Do NOT implement anything until the user explicitly says to proceed.**

## Red Flags

- Proposal created without reading any existing source code
- Tasks that are per-file ("update UserService.java") instead of per-logical-unit
- Missing Risks or Non-Goals sections
- More than 10 tasks — scope is too large, split the change
- Proceeding to implementation without explicit user approval
