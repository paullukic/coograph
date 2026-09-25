# Retro: guardrails that harden from evidence

Coograph ships guardrails as prose rules plus hooks. Retro closes the loop:
it records when those rules get broken, measures what each session costs,
and proposes concrete edits to the instructions, hooks, and skills, as an
OpenSpec you approve or reject line by line.

Nothing here talks to a network. Everything lives in the project directory.

## What it records

`capture-signals.py` (a Claude Code `SessionEnd` hook) parses the session
transcript Claude Code already keeps on disk and appends metadata to
`.coograph/signals.jsonl` (gitignored). `warn-scope.py` and
`block-generated.py` append a violation each time they fire, and every rule
hook appends a decision saying what it did about which tool call. When Retro
is not enabled (no `rules.json`), nothing is written at all.

The store logic lives in one file, `.github/retro/_coograph_signals.py`,
shared by the hooks and the analyzer. `.claude/hooks/_coograph_signals.py`
is a shim that locates it through `CLAUDE_PROJECT_DIR` (plugin mode) or the
hook's own project root, so the analyzer works in projects set up for any
tool, and the hooks degrade to their pre-Retro behaviour when
`.github/retro/` is absent.

Each line is one JSON record:

| field | meaning |
|---|---|
| `v` | schema version |
| `ts` | when it was written |
| `tool` | `claude-code`, `codex`, `opencode`, `unknown` |
| `session_id` | Claude Code session id, filename-safe |
| `kind` | `session` (one per session), `violation` (rule-bound, the only kind thresholds count), `event` (not rule-bound), `decision` (a hook's action on one tool call: `warned`, `blocked` or `suppressed`, with its `tool_use_id`), `outcome` (what the transcript shows followed a decision, derived at capture and joined by `tool_use_id`) |
| `rule` | rule id from `rules.json`, or `none` |
| `detector` | which detector wrote it |
| `confidence` | `deterministic` or `heuristic` |
| `origin` | `transcript` or `hook` |
| `evidence` | detector-specific keys, allow-listed below |

### Privacy

Records never contain prompt text, assistant text, tool output, file
contents, or full shell commands. The allow-list lives in
`.claude/hooks/_coograph_signals.py` (`ALLOWED_EVIDENCE`); any other key is
dropped before writing. Paths are repo-relative; anything outside the
project is recorded as the literal `external`. Shell commands are reduced
to the program name and a 12-character hash. A sentinel test in `tests/`
fails if a marker string planted in every part of a transcript reaches the
signals file.

### Detectors

| detector | rule | confidence | fires when |
|---|---|---|---|
| `graph-first` | `graph-first` | deterministic | a `Grep` or `Glob` call happens before the session's first graph access (a `mcp__code-graph__*` tool or a shell command containing both `sqlite3` and `.code-graph`), while `.code-graph/graph.db` exists. `proof` says what happened later: `mcp-later`, `sqlite-later`, or `total-bypass`. Subagent (sidechain) calls are ignored. |
| `openspec-gate` | `openspec-gate` | heuristic | two or more source files edited, nothing in the session touched `openspec/changes`, and no active change directory exists at capture time. `openspec-gate-warn.py` warns live on the same conditions, once per session, at the second distinct source file; the detector stays heuristic |
| `scope-warning` | `scope` | deterministic | `warn-scope.py` printed its warning (hook-emitted) |
| `generated-file-block` | `generated-files` | deterministic | `block-generated.py` blocked an edit (hook-emitted) |
| `build-retry` | none | deterministic | the same shell command ran three or more times with at least two failures |
| `user-correction` | none | heuristic | a user message matched one of `correction_patterns` right after a tool call. Pattern id only. |
| `new-dependency` | `no-new-deps` | deterministic | `npm install <pkg>`, `pip install <pkg>`, `uv add`, `cargo add`, `go get`, and friends; or an edit to a dependency manifest (`package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `composer.json`, `Gemfile`). Installing what a manifest already lists does not count: `pip install -r requirements.txt`, `pip install -e .`, bare `npm install`. |
| `session` | none | deterministic | always: message count, tools used, edited-file count, skills invoked, whether the graph existed, start and end, token usage (`input`, `output`, `cache_read`, `cache_create`) summed per session, and the transcript size (`source_bytes`, used to skip unchanged transcripts without opening them) |
| `decision` | the hook's rule | deterministic | a rule hook warned, blocked, or suppressed a repeat warning (hook-emitted through `emit_decision`; never counted as a violation) |
| `outcome` | the decision's rule | deterministic | at capture, for each decision whose `tool_use_id` is in the transcript: `proceeded` (a tool result exists and the action was not `blocked`), `corrected` (the next user message matched a correction pattern), `reconciled` (rule-specific: `scope` a later `tasks.md` edit under `openspec/changes/`, `openspec-gate` a later touch of `openspec/changes`, `defect` a later review or verify skill, `generated-files` the path left alone afterwards; null for every other rule), `repeated` (later decisions for the same rule in the session) |

Known false positives, by design:

- `graph-first` when the user explicitly asks for a grep, or when the graph
  was built partway through the session.
- `openspec-gate` when the work was an exempt follow-up on an already
  approved change that lives only in `archive/`.
- `user-correction` on any message that happens to start with "No" or
  contain "again". It is never used as sole evidence for a change.

### Per-tool support

Only Claude Code exposes transcripts and lifecycle hooks. Other tools get
the skill and the analyzer but no capture.

| Tool | transcript detectors | hook-emitted | session-start line | feature-end prompt |
|---|---|---|---|---|
| Claude Code / Cowork plugin | all | scope, generated-files | yes | yes |
| Codex CLI | none | none (Bash audit log only) | no | yes |
| OpenCode | none | none (Bash audit log only) | no | yes |
| Cursor, Devin Desktop, Aider, Cline | none | none | no | yes |

## The registry

`rules.json` (committed) lists the rules Retro measures, how each is
enforced (`prose`, `hook-warn`, `hook-block`), whether it is `hard` (never
pruned), which detector measures it, and when it was last changed. It also
carries the thresholds, the correction patterns, retention,
`ignore_session_prefixes` (a session whose id starts with one of these is
captured but dropped from every count; seeded with the retro skill's probe
prefix `11111111-aaaa-4bbb-8ccc-`), and `last_retro`.

| threshold | default | meaning |
|---|---|---|
| `deterministic_events` / `deterministic_sessions` | 3 / 2 | a deterministic rule is "over threshold" at this many events across this many sessions |
| `heuristic_events` / `heuristic_sessions` | 5 / 3 | a heuristic rule becomes "supporting only" evidence |
| `prune_sessions` | 10 | a non-hard prose rule with zero events across this many sessions is a prune candidate |
| `instruction_token_budget` | 8000 | above this, every added rule must be paired with a prune |
| `retro_prompt_min_sessions` | 3 | sessions since the last retro before the workflow offers to run one |
| `bootstrap_min_archives` | 10 | archived changes needed to bootstrap Retro in a project that never enabled it |
| `escalate_ignored_rate` | 0.5 | a `hook-warn` rule over threshold reads `escalate_to: hook-block` only when this share of its outcomes were ignored (the rule fired again later, nothing reconciled it), over at least `deterministic_events` outcomes; otherwise the report says `hold: no_outcomes` or `hold: warnings_change_behaviour` |

`rules.seed.json` next to it is the shipped seed: init, sync, and the
plugin refresh it, and `rules.json` is created from it the first time.
New seeded rules reach existing projects through `retro.py --merge-seed`
(default seed: that file); local edits, thresholds, and `last_retro` are
never overwritten. `last_retro` is written by `retro.py --mark-retro
<session_id>` and counts sessions by start time, so the count keeps working
at the retention cap.

The SessionStart catch-up walks the transcript directory newest first,
skips any transcript whose size still matches the recorded `source_bytes`
without opening it, and parses at most 20 files in 2 seconds. A directory
full of old transcripts never starves a recently killed session.

## Commands

```bash
# capture every transcript Claude Code kept for this project (idempotent)
python3 .claude/hooks/capture-signals.py --backfill ~/.claude/projects/<slug> --cwd .

# re-capture after a detector change
python3 .claude/hooks/capture-signals.py --backfill ~/.claude/projects/<slug> --cwd . --force

# analyze
python3 .github/retro/retro.py --report      # writes .coograph/retro/report.{json,md}
python3 .github/retro/retro.py --status      # exit 0 = enough sessions to run a retro
python3 .github/retro/retro.py --validate    # check rules.json
python3 .github/retro/retro.py --merge-seed  # create rules.json from rules.seed.json, or add newly seeded rules
python3 .github/retro/retro.py --mark-retro <session_id>   # record that a retro ran (the skill does this)

# tests
python -m unittest discover -s .github/retro/tests
```

`<slug>` is the absolute project path with every character outside
`[A-Za-z0-9]` replaced by `-` (for example `C--paul-code-myapp` or
`-home-paul-code-myapp`). The `/coograph-retro` skill works this out for
you and asks before reading.

## The report

`report.md` opens with a plain-language paragraph, then tables: rules
against thresholds with an `escalate to` column (a rung, or `hold: <reason>`
when a `hook-warn` rule has no outcome evidence for blocking), a Decisions
table (per rule: warned, blocked, suppressed, outcomes, and the proceeded,
corrected, reconciled and ignored rates), path clusters, build retries,
tokens per session (with a before / after split around the most recent rule
change), workflow adherence (editing sessions that also ran a review or
verify skill), instruction file sizes against the budget, and archive
statistics. Sessions matching `ignore_session_prefixes` are left out of all
of it and counted once as "Ignored sessions".

## The skill

`/coograph-retro` runs the analyzer, reads the report, and writes
`openspec/changes/<date>-retro-<n>/` with a proposal, a spec, tasks, and
ready patches. Every proposed change opens with three plain sentences (what
happened, why it matters, what changes) and carries an evidence block. It
never edits anything outside that directory. You approve, then
`/coograph-apply` applies it like any other change.

Rules of the skill, in one place:

- Heuristic signals are never sole evidence.
- A prose rule that is still violated is escalated to a hook, never
  reworded louder.
- Over budget, every addition is paired with a prune.
- Warn becomes block on ignored outcomes, never on counts alone.
- Retro may target its own skill, detectors, and hooks, but may not change
  thresholds or disable a detector without a task titled `Loosen:`.
- Every generated hook file carries a provenance header; every retro
  `tasks.md` ends with a rollback task.

Retro is not recursive self-improvement in the model sense. It is the
instruction-layer version: the system observes its own failures and
proposes changes to its own scaffolding, with a human at the gate.
Whether rules keep improving over many cycles is unproven; the first retro
usually finds most of the value.

### Upgrading an existing project

`no-new-deps` and `defect` ship as `hook-warn` since the default-rule-hooks change.
`sync.py` delivers `no-new-deps-warn.py` and `defect-warn.py` into `.claude/hooks/`,
but a project's own `rules.json` is never overwritten, so an existing project keeps
whatever `enforcement` it already recorded until its next retro flips it. Expect the
hooks to fire while the registry still reads `prose`; the signals are recorded either
way and the next report reconciles it.

`openspec-gate` ships as `hook-warn` since the decision-records change, enforced by
`openspec-gate-warn.py`, and the same lag applies. That change also added
`thresholds.escalate_ignored_rate` and `ignore_session_prefixes`; `retro.py --merge-seed`
adds both to an existing registry without touching any value already there. Until the
hooks have run under that version, every `hook-warn` rule over threshold reads
`hold: no_outcomes`: the block rung now needs outcome evidence, and old records carry none.

## Writing a hook for a rule

Three things bite in order, and the first two are silent.

**1. Record a decision always; a violation only if nothing else observes the rule.** Every rule
hook calls `signals.emit_decision(cwd, payload, rule, action, __file__, path)` where it warns
(`warned`), blocks (`blocked`), or would have warned again in the same session (`suppressed`).
That record is never counted as a violation; at session end `capture-signals.py` joins it to the
transcript by `tool_use_id` and writes an `outcome`, which is what lets the next retro tell a
warning that changed behaviour from one that was ignored. A hook emits a **violation** only when
its rule has **no detector in `capture-signals.py`**. Today that is `scope` and `generated-files`,
and only those. `graph-first`, `openspec-gate`, `no-new-deps`, `defect` and `user-correction` are
recorded from the transcript already; a hook-emitted violation is counted twice, because
`replace_session` keeps hook-origin records, `summarize` counts every violation equally, and
`retro.py` never reads `origin`. `tests/test_capture.py::HookEmissionRulesTests` and
`HookDecisionRulesTests` enforce both halves.

**2. Unknown evidence keys vanish without an error.** `ALLOWED_EVIDENCE` is a per-detector
allow-list and `make_record` filters against it silently. Emit a key the detector does not declare
and the record is written with `"evidence": {}` — accepted, stored, useless. Look up your
detector's keys in that mapping before you emit, and assert on them in a test, the way
`test_warn_scope_emits` does.

**3. A hook cannot be verified by the session that wrote it.** `.claude/settings.json` is read at
session start, so new wiring is inert until a restart, and any artifact your own probe leaves
behind carries a session id you invented. Prove it with a nested run that names its own session:

```bash
claude -p "<one instruction that triggers the hook>" --allowedTools Write Bash   --permission-mode acceptEdits --session-id 11111111-aaaa-4bbb-8ccc-000000000001
```

The markers and records the hook writes then carry that id. Run the negative case too, keep the
probe non-mutating (`--dry-run`), and delete the artifacts afterwards. The nested session is
captured, but an id that starts with a prefix in `ignore_session_prefixes` is dropped from every
count, so the probe cannot escalate the rule it tests.
