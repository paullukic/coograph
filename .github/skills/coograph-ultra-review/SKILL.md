---
name: coograph-ultra-review
description: Optional deep review for a big change - a multi-agent hostile review of a PR, a commit batch, a fix batch (delta) or a plan before code (plan): one reviewer per dimension, adversarial verification of every finding, one report with a verdict. Costs a lot more than /coograph-review; use it before asking people to approve something large, or anything with queue jobs, locks, state transitions, data migrations or cross-service contracts. Trigger phrases - "ultra review", "deep review of the PR", "run the review gate on #42", "review this plan before I build it".
---

# coograph-ultra-review

`/coograph-review` is the everyday review: one reviewer, the working tree, minutes. This one is for a change that is big or dangerous enough that a single reader misses things: several hostile reviewers, each with one question in mind, every finding attacked by independent refuters before it reaches the report. It found, on one real stack, a lock released twice, a test that passed without its fix, and a queued job that could wipe a customer's files - each after an ordinary review had approved. It costs about a million tokens and twenty minutes per run. Optional, on purpose: suggest it, do not run it unasked.

**Claude Code only** (it runs as a saved workflow through the `Workflow` tool). In other tools, do the same by hand: one `@Reviewer` per dimension below, then a second pass that tries to refute each finding.

## When to suggest it

Say that it exists - one sentence, with the cost - when the change in front of you is any of:

- more than about fifteen files, or a stack of several commits going to people for approval;
- queue jobs, cache claims, locks, retries, redelivery, timeouts, status transitions;
- anything that deletes, moves, overwrites or migrates data;
- a contract between two services or a client and a server;
- a plan for such a change, before the code exists (`plan` mode is the cheapest place to find a design hole).

Do not suggest it for a small, local change: `/coograph-review` is enough.

## 1. Pick the mode

| Mode | When | Reviewers | Lenses | Cost (measured) |
|---|---|---|---|---|
| `plan` | before writing code that touches lifecycle or concurrency | 2 on the session model, over the plan text and the code it names and its callers | 1 | 1.0–1.4M tokens, ~20 min |
| `full` | the first review of a PR or commit batch, and the one review of the whole PR once every fix is in (`pr: N`) | 4 on the session model, blast radius from the code graph | 2 (Opus, high effort) | 1.2–1.6M, 17–22 min; a 33-commit PR: 3.1M, 39 min |
| `delta` | a fix batch after a `full` run: are the previous findings fixed, and what did the changed lines break | 2 on Sonnet, no blast radius | 1 | ~0.5M, ~17 min |

The loop: `plan` (when it applies) → code → `full` on the batch → fix → `delta` with the previous findings → at most two deltas → one last `full` with `pr: N` over the whole PR → a person.

## 2. Scope in the conversation

Collect: the repository's absolute path; for `full`/`delta` either the PR number or the commit hashes (newest last) - a stacked PR: review its own commits, not the base's; for `delta` the previous run's `findings` (file, line, claim, fix, severity - the last result has them ready as `findings`); for `plan` the plan text (or a path the reviewers can read) and the files it names. Count the commits and the changed files (`git show --stat`) so the plan below has numbers. When the repository has open review threads on the PR (people, bots), handle them first.

## 3. Propose the model plan, then ask

Read the `models` block of `openspec/config.yaml`:

- `mode: preset` or `per-task` - the mapping comes from there (`reviewer`, `verifier`, `explore` → scout, `report` if present; the `catalog` binds the aliases). Show it.
- `mode: unset` or `off` - the mode's defaults from the table above (scout Haiku, report Sonnet in every mode).

Show the table for the chosen mode with the numbers from the scope, then ask (one choice): **Proposed plan (Recommended)** · **Everything on the session model** · **Cheaper** (reviewers and verifiers on Sonnet) · a custom mix. The answer becomes `models: {scout, reviewer, verifier, report, post}` with the aliases `haiku`, `sonnet`, `opus`, `inherit`. Nothing starts before the answer. When the user already picked the plan for the same PR in the same breath, say which plan runs and go.

## 4. Run

```
Workflow scriptPath: "<absolute path to the project>/.github/skills/coograph-ultra-review/workflow.js"
args: {"repo": "<absolute path to the project>", "pr": 364, "models": {"scout": "haiku", "reviewer": "inherit", "verifier": "opus", "report": "sonnet"}}
args: {"repo": "...", "commits": ["c78bdd7", "f04a228"], ...}
args: {"repo": "...", "commits": ["3d6046a8"], "previous": [{"severity": "critical", "file": "app/Jobs/X.php", "line": 105, "claim": "...", "fix": "..."}], ...}   (delta)
args: {"repo": "...", "plan": "<the plan text>", "files": ["app/Jobs/X.php"], ...}   (plan)
```

Always the absolute `scriptPath` (a relative one resolves against the session's current directory, which a `cd` changes). `mode` is inferred (`plan` given → plan, `previous` given → delta, else full) or set explicitly. Optional: `dimensions: [...]` (strings, or `{key, title, questions}`) to replace the mode's defaults with the project's own questions; `votes: 3` for a third verification lens (existing test coverage); `allowCommands: ["go vet ./...", "bunx oxlint"]` for the project's read-only checks the reviewers may run (the test suite, builds and formatters stay off); `post: true` to post the report as a PR review comment - only when the user asked for that in the same message.

The workflow runs in the background; read its result when the task notification arrives. The result holds `verdict`, `report` (Markdown), `findings` (the surviving findings **in the change** - what blocks, and what to feed the next delta run as `previous`), `followups` (surviving findings in code the commits did not touch - pre-existing, not blocking), `previous_status` (delta: each previous finding fixed / not fixed with evidence), `dropped` (refuted, with reasons), `nits`, `agents`, `tokens`.

## 5. What the reviewers work under (in their briefs)

Code-graph first, grep as fallback; the project's conventions and, with OpenSpec, the active change's proposal, spec and tasks; every finding from a fresh read at the reviewed commit with a verbatim quote, file:line and a concrete failure scenario; no edits, no stash, no checkout; no test suite, build, formatter or server unless `allowCommands` lists the command; style the formatters cover is skipped.

## 6. After a run - the stop rule

1. `git status` in the repository must show nothing new. Anything else is a reviewer that broke the brief: revert it and say so.
2. **Blocking = `findings` (in the change) plus, in delta, a previous finding not fixed.** Fix those on the branch that owns the code, with a test where the finding names one.
3. **`followups` (adjacent, pre-existing code) do not loop.** List them in the change's notes and the PR description; fix one in the same batch only when it is a Critical the change made reachable, and say so.
4. Re-run in `delta` mode with the previous `findings`; stop when `verdict` is APPROVE. After at most two deltas, stop anyway and hand the PR to a person with the open items listed: a third round of machine findings on the same lines means the design, not the code, needs a look (run `plan` on the next attempt).
5. Once every fix is in, one `full` run with `pr: N` over the whole PR, then the human review.
6. Record every round (mode, agents, tokens, finding → fix → commit) in the change's notes and paste the report table into the PR description; the report's footer carries mode, agent count and tokens.

Refuted findings are listed in the report with the refuter's reason - read them; a refuter can be wrong too, and a human disagreement reopens one.
