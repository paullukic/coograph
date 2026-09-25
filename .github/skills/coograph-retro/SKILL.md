---
name: coograph-retro
description: Turn the guardrail signals Coograph captured from past sessions into an OpenSpec that proposes evidence-backed edits to instructions, hooks, and skills. Use when the session-start line says "run /coograph-retro", after archiving a change, or to bootstrap Retro in a project with many archived changes.
argument-hint: Optional. "--templates" targets the coograph template files instead of this project's (maintainer mode, coograph checkout only).
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

Run a retro: measure how the guardrails held up across past sessions, then propose concrete changes as an OpenSpec. You propose. You never apply. Nothing outside `openspec/changes/<date>-retro-<n>/` is written.

Read `.github/retro/README.md` once if you have not this session. It defines every detector, the registry, and the thresholds.

---

## Step 0: Where do we stand

Run:

```bash
python3 .github/retro/retro.py --status
```

Branch on the exit code and the line printed:

| exit | line | what to do |
|---|---|---|
| 2 | `_coograph_signals.py not found`, or the command itself cannot be found | `.github/retro/` is not installed in this project. Tell the user to run `/coograph-init` (it copies `.github/retro/` for every tool) or, for a registered project, to `git pull` coograph so `sync.py` delivers it. Stop. Write nothing. |
| 4 | `not enabled; N archived changes found, bootstrap available` | Go to **Bootstrap** below, then continue at Step 1. |
| 3 | `not enabled` | Fewer archived changes than `bootstrap_min_archives`. Say Retro is not enabled here, that init enables it, and stop. Write nothing. |
| 3 | `no signals captured` | Offer a backfill (see **Bootstrap**, part 2 only). If the user declines or it captures nothing, stop. |
| 3 | `N sessions since last retro ...` | Evidence is thin. Say so with the numbers and ask whether to proceed anyway. Proceed only on a yes. |
| 0 | `N sessions since last retro ...` | Continue at Step 1. |

### Bootstrap

Part 1, registry. Only when `rules.json` is absent:

```bash
python3 .github/retro/retro.py --merge-seed
```

This copies `.github/retro/rules.seed.json` (always shipped next to `retro.py`) to `rules.json`. Confirm it printed `retro: registry ... (added graph-first, ...)`.

Part 2, backfill. Claude Code keeps every transcript for this project under `~/.claude/projects/<slug>/`, where `<slug>` is the absolute project path with every character outside `A-Z a-z 0-9` replaced by `-` (for example `C:\paul\code\app` becomes `C--paul-code-app`, `/home/paul/app` becomes `-home-paul-app`). Work out the path, check it exists, then ask:

> Retro can read the Claude Code transcripts for this project at `<path>` (N files). It stores only tool names, counts, rule ids, file paths, and token totals. No prompt text, code, or output. Backfill now? (yes / give another path / no)

On yes:

```bash
python3 .claude/hooks/capture-signals.py --backfill "<path>" --cwd .
```

Report the `captured / skipped / failed` line verbatim. Zero captured means there is nothing to analyze; stop.

## Step 1: Analyze

```bash
python3 .github/retro/retro.py --report
```

Read `.coograph/retro/report.md` in full. Read `.coograph/retro/report.json` for exact numbers. Read `.github/retro/rules.json`. Do not compute statistics yourself; the report is the only source of numbers you may cite.

## Step 2: Decide what to propose

Work through the report and build a change list. Every change has exactly one of these types.

| type | when | target |
|---|---|---|
| `new-hook` | a rule with `status: over_threshold` and `enforcement: prose` (`escalate_to: hook-warn`) | new `.claude/hooks/<rule>-warn.py` + wiring in `.claude/settings.json`. It records a decision on every firing, and a violation only if the rule has no transcript detector, see rule 6 |
| `edit-rule` (hook upgrade) | `enforcement: hook-warn`, over threshold, and the report says `escalate_to: hook-block`. A `hold:` value in that column means keep the warning, see rule 7 | the existing hook: exit 1 becomes exit 2 |
| `edit-rule` (prose) | a rule whose wording is ambiguous AND whose evidence shows the ambiguity (for example the same path pattern in most events). Never to add emphasis, capitals, or "NOT an exemption" lists to an existing rule. | the instruction file named in `source` |
| `add-rule` | a recurring `build_retry` program, `path_cluster`, or `new-dependency` pattern that no registry rule covers | `CLAUDE.md` / `.github/copilot-instructions.md` and a new registry entry |
| `new-instruction-file` | a `path_cluster` with events in `>= deterministic_sessions` sessions under one directory prefix | `.github/instructions/<name>.instructions.md` with `applyTo` set to that prefix |
| `prune-rule` | an id in `prune_candidates` | remove the prose, remove the registry entry |

Rules that decide what survives:

1. **Evidence first.** A rule listed only under `supporting_only`, or whose only signals are `user-correction`, gets no change of any type. It may appear in a "Watching" list.
2. **Escalate, do not shout.** A prose rule that is still violated becomes a hook. If a hook already exists and its warnings are ignored, warn becomes block (rule 7). Rewording an existing rule louder is never a proposal; the report shows that does not work.
3. **Budget.** If `over_budget` is true, every `add-rule` or `new-instruction-file` must be paired in the same proposal with a `prune-rule` or a token-reducing `edit-rule`, and the summed token delta must be zero or negative.
4. **Self-targeting is allowed, loosening is gated.** You may propose changes to `.github/skills/coograph-retro/SKILL.md`, the detectors in `.claude/hooks/capture-signals.py`, and `correction_patterns`. You may not change `thresholds`, set a pattern or detector to disabled, or raise a threshold unless `tasks.md` carries a task whose title starts with `Loosen:` naming the field. Without it, drop the change and note it under Risks.
5. **Numbers come from the report.** Every count, session count, date, and token figure in the proposal is copied from `report.json`. If a number is not there, it is not in the proposal.
6. **A hook records decisions, and a violation only when nothing else observes the rule.** Every rule hook calls `signals.emit_decision(cwd, payload, rule, action, __file__, path)` when it warns, blocks, or would have warned again in the same session (`suppressed`). Decisions are never counted as violations; `capture-signals.py` joins them to the transcript by `tool_use_id` at session end and writes one `outcome` per decision (`proceeded`, `corrected`, `reconciled`, `repeated`). A hook emits a **violation** only when its rule has no detector in `capture-signals.py`: `scope` and `generated-files`. Every other rule (`graph-first`, `openspec-gate`, `no-new-deps`, `defect`, `user-correction`) is already recorded from the transcript, and a hook-emitted violation is counted a second time: `replace_session` keeps hook-origin records, `summarize` counts every violation equally, and `retro.py` never reads `origin`. Say in the evidence block what the hook records, and why.
7. **Warn becomes block on ignored outcomes, never on counts alone.** A `hook-warn` rule over threshold reads `escalate_to: hook-block` only when it has at least `deterministic_events` outcomes and its `ignored_rate` (the rule fired again later in the same session and nothing reconciled it) reaches `thresholds.escalate_ignored_rate`. Otherwise the report shows `hold: no_outcomes` (the hook has not run under decision records yet) or `hold: warnings_change_behaviour` (warnings are followed by reconciliation, or never repeat). A held rule is not a change; list it under Watching with its row from the Decisions table. `corrected` comes from the heuristic correction patterns and is colour, never a gate.

Where the token trend is available (`tokens.before_after`), state it in the Why section. Where `workflow_adherence.rate` is below 0.5 and there are at least `deterministic_sessions` editing sessions, add an Observation (not a change) saying most editing sessions never ran a review or verify skill.

If the change list is empty, still write the OpenSpec with the Why section, an empty Changes section stating that nothing crossed threshold, the Observations, and a single task to record `last_retro`. An honest "nothing to change" is a valid retro.

## Step 3: Scope

Default scope is this project: targets are its `CLAUDE.md`, `.github/copilot-instructions.md`, `.github/instructions/`, `.claude/hooks/`, `.claude/settings.json`, `.github/retro/rules.json`.

`--templates` (maintainer mode) is honoured only when both `templates/` and `setup.sh` exist at the repo root, meaning this is a coograph checkout. Then targets are the template files so `sync.py` propagates them. Otherwise say maintainer mode is unavailable here and run in project scope.

## Step 4: Write the OpenSpec

Directory: `openspec/changes/<YYYY-MM-DD>-retro-<n>/` where `<n>` is one more than the highest `*-retro-<n>` in `openspec/changes/` and `openspec/changes/archive/` combined (start at 1).

Files:

`.openspec.yaml`

```yaml
schema: spec-driven
name: retro-<n>
created: <YYYY-MM-DD>
```

`proposal.md`

```markdown
# Proposal: Retro <n>, <date>

## Why
<the opener paragraph from report.md, verbatim>
<one sentence on the token trend if tokens.before_after exists>

## Changes

### 1. <type>: <rule or target>

What happened: <one plain sentence, no rule ids, no jargon>
Why it matters: <one plain sentence on the cost to the user>
What changes: <one plain sentence on the edit>

```
Type: <type>
Rule: <rule id or "none">
Events: <events> across <sessions> sessions (<first date>, <last date>)
Detector: <detector> (<confidence>)
Current: <enforcement>, <hard|not hard>, <source.file> § <source.anchor>
Proposed: <one line>
Token delta: <+/-N instructions, +/-N hook files>
Patch: patches/<NN>-<slug>.md
```

### 2. ...

## Watching
- <rule>: <events> events, <status>, not enough to act on.

## Observations
- <archive_stats, workflow_adherence, build_retry facts that inform but do not change anything>

## Non-Goals
- No auto-apply. No threshold changes. No changes to rules with only heuristic evidence.

## Risks
- <dropped changes and why, for example a loosening without a Loosen: task>
- <known false positives of the detectors involved>
```

Every change carries the three plain sentences and the complete evidence block. A change missing either is deleted before writing, not written with blanks.

`specs/guardrails/spec.md`: one `## Requirement:` per change, stated as the behavior after the change, with one `### Scenario:` that the next retro can check (for example: "GIVEN 5 sessions after the hook ships, THEN graph-first events per session is below the rate_before in report.json").

`tasks.md`: one task per change, referencing its patch file; then a task **Update registry** (set `last_changed` on touched rules, add or remove entries, then run `python3 .github/retro/retro.py --mark-retro <this session's id>` which writes `last_retro` with a UTC timestamp and the captured session count); then a task **Rollback** listing every file to delete or restore and every registry entry to revert. `Loosen:` tasks, if any, come before the registry task. The session id is in the hook payloads and in the transcript filename; if you cannot determine it, pass `unknown` and say so.

`patches/<NN>-<slug>.md`: the exact edit. For an instruction file: the file path, the old block, the new block. For a new hook: the full file, starting with the provenance header, plus the `settings.json` block to add. For a prune: the block to remove and the registry entry to delete.

## Step 5: Reference patch for the most common escalation

The rule broken most often in practice is `graph-first`. When you propose its hook, use this design; it is cheap, has no transcript parsing, and is one warning per session:

- One hook file `.claude/hooks/graph-first-warn.py` wired twice in `.claude/settings.json` under `PreToolUse`: once with matcher `mcp__code-graph__.*`, once with matcher `Grep|Glob`.
- On a code-graph tool call: create the marker `.coograph/graph-touched-<session_id>` and exit 0.
- On Grep or Glob: if `.code-graph/graph.db` exists, the marker does not exist, and `.coograph/graph-warned-<session_id>` does not exist, print `[graph-first] Grep/Glob before any code-graph call this session. Call get_minimal_context or query_graph first.` to stderr, create the warned marker, exit 1. Otherwise exit 0.
- Import `should_skip` from `_coograph_guard` like every other hook. Record a decision through `signals.emit_decision(cwd, payload, "graph-first", "warned", __file__)` at the warning, and with `"suppressed"` when the warned marker already exists. **Do not emit a violation.** `graph-first` already has a transcript detector (`capture-signals.py`), so a hook-emitted violation counts every event twice, see rule 6 in Step 2. The hook is measured by the detector's own `graph-first` count falling and by its row in the report's Decisions table.
- Header line: `# generated by coograph-retro on <date> from openspec/changes/<dir>`.

Model the file on `.claude/hooks/warn-scope.py` (payload parsing, guard import, stderr message, exit code). Do not invent a different structure.

## Step 5b: Prove the hook fires (hook changes only)

Skip this when the change adds no hook. Otherwise it is not optional, and unit tests do not replace
it: they prove the hook is self-consistent with a payload you wrote yourself, not that the host
sends that payload or invokes the hook at all.

**A hook cannot be verified by the session that writes it.** `.claude/settings.json` is read at
session start, so wiring added now is inert until a restart. Every artifact your own probes leave
behind carries a session id you invented, which is indistinguishable from evidence.

Run a nested session with an id you choose, so the artifacts are named with it:

```bash
claude -p "<one tight instruction that triggers the hook>"   --allowedTools Write Bash --permission-mode acceptEdits   --session-id 11111111-aaaa-4bbb-8ccc-000000000001
```

- Take the session id prefix from `ignore_session_prefixes` in `rules.json` (seeded
  `11111111-aaaa-4bbb-8ccc-`) and append a fresh suffix. A session whose id starts with that
  prefix is captured but excluded from every count, so a probe cannot escalate the rule it tests.
- Keep the probe non-mutating: `git commit --dry-run`, `npm install --dry-run`, scratch files under
  a gitignored directory.
- Check the hook's own artifacts (markers, `.coograph/signals.jsonl`) carry that exact session id.
- Run the negative case too: the situation where the hook must stay silent.
- Delete the probe files and markers afterwards. The nested session is captured by
  `capture-signals.py` but its records are dropped from every count and from the report's session
  total because of the prefix; say in the proposal which id you used.

Report what the probe showed. "Tests pass" is not the same claim as "the hook fired".

## Step 6: Report and stop

Print:

```
## Retro <n> written

**Change:** openspec/changes/<dir>/
**Window:** <sessions> sessions, <first> to <last>
**Over threshold:** <ids or none>

| # | type | target | events | sessions |
|---|---|---|---|---|
| 1 | new-hook | graph-first | 11 | 3 |

Review the proposal. Approve to apply with /coograph-apply, or reject any line item.
```

Then stop. Do not apply. Do not edit any file outside the change directory. Do not run `/coograph-apply`.

## Guardrails

- Numbers only from `report.json`. Never estimate, never round differently, never cite memory.
- No change without both the three plain sentences and the evidence block.
- No louder prose. Escalate to a hook or do nothing.
- No `thresholds` edits, no disabling, without a `Loosen:` task.
- No files written outside `openspec/changes/<date>-retro-<n>/`.
- If in doubt whether something crossed a threshold, it did not.
