---
name: new-ticket
description: Start work on a new ticket. Runs pre-flight checks, investigates the codebase, and flows into OpenSpec proposal. Use when the user pastes a ticket, issue, or task description.
argument-hint: Paste ticket description, URL, or summary
license: MIT
metadata:
  author: copilot-template
  version: "1.0"
---

Start work on a new ticket — run pre-flight, investigate, and propose a change.

---

## Step 1: Pre-flight checks

Before doing anything else:

1. **Code-graph availability** — call `get_minimal_context` with a one-line summary of the ticket. Record whether code-graph is available. If available, use it for ALL navigation in subsequent steps.
2. **Check for in-progress work** — list `openspec/changes/` (skip `archive/`). If an existing OpenSpec overlaps with this ticket, stop and ask: "There's an in-progress change `<name>` — is this ticket related, or should I start fresh?"
3. **Read conventions** — read `.github/copilot-instructions.md` if not already loaded.

## Step 2: Parse the ticket

Extract from the user's input:
- **Title/summary** — one-line description
- **Requirements** — what needs to be built or changed
- **Acceptance criteria** — if provided
- **Linked references** — URLs, ticket IDs, file paths mentioned

If the ticket is vague (no specific files, unclear deliverable, touches 3+ areas), note this — it affects Step 3.

## Step 3: Investigate the codebase

Use code-graph tools (or fallback chain) to:
1. Identify files and modules affected by the ticket
2. Read relevant source code to understand current behavior
3. Find existing patterns the implementation should follow
4. Surface risks, dependencies, and integration points

**Scope the investigation to the ticket.** Don't audit the entire codebase.

If the ticket is vague or complex (identified in Step 2):
- Run deeper investigation
- Ask the user focused clarifying questions (one at a time, with choices when possible)
- Do NOT proceed to Step 4 until requirements are clear

If the ticket is specific and well-scoped:
- Investigation can be brief
- Proceed directly to Step 4

## Step 4: Flow into OpenSpec proposal

Once investigation is complete and requirements are clear, invoke the **openspec-propose** skill to create the proposal.

Pass it a clear description synthesized from the ticket + your investigation findings.

**Do NOT implement anything.** The propose skill will create artifacts and wait for user approval.

## Red Flags

- Skipping pre-flight (especially code-graph check)
- Starting to write code before proposing
- Not checking for existing in-progress OpenSpecs
- Using grep/glob when code-graph is available
- Proceeding with vague requirements without asking clarifying questions
