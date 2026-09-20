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
`block-generated.py` append a line each time they fire. When Retro is not
enabled (no `rules.json`), nothing is written at all.

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
| `kind` | `session` (one per session), `violation` (rule-bound), `event` (not rule-bound) |
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
| `openspec-gate` | `openspec-gate` | heuristic | two or more source files edited, nothing in the session touched `openspec/changes`, and no active change directory exists at capture time |
| `scope-warning` | `scope` | deterministic | `warn-scope.py` printed its warning (hook-emitted) |
| `generated-file-block` | `generated-files` | deterministic | `block-generated.py` blocked an edit (hook-emitted) |
| `build-retry` | none | deterministic | the same shell command ran three or more times with at least two failures |
| `user-correction` | none | heuristic | a user message matched one of `correction_patterns` right after a tool call. Pattern id only. |
| `new-dependency` | `no-new-deps` | deterministic | `npm install <pkg>`, `pip install <pkg>`, `uv add`, `cargo add`, `go get`, and friends; or an edit to a dependency manifest (`package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `composer.json`, `Gemfile`). Installing what a manifest already lists does not count: `pip install -r requirements.txt`, `pip install -e .`, bare `npm install`. |
| `session` | none | deterministic | always: message count, tools used, edited-file count, skills invoked, whether the graph existed, start and end, token usage (`input`, `output`, `cache_read`, `cache_create`) summed per session, and the transcript size (`source_bytes`, used to skip unchanged transcripts without opening them) |

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
| Cursor, Windsurf, Aider, Cline | none | none | no | yes |

## The registry

`rules.json` (committed) lists the rules Retro measures, how each is
enforced (`prose`, `hook-warn`, `hook-block`), whether it is `hard` (never
pruned), which detector measures it, and when it was last changed. It also
carries the thresholds, the correction patterns, retention, and
`last_retro`.

| threshold | default | meaning |
|---|---|---|
| `deterministic_events` / `deterministic_sessions` | 3 / 2 | a deterministic rule is "over threshold" at this many events across this many sessions |
| `heuristic_events` / `heuristic_sessions` | 5 / 3 | a heuristic rule becomes "supporting only" evidence |
| `prune_sessions` | 10 | a non-hard prose rule with zero events across this many sessions is a prune candidate |
| `instruction_token_budget` | 8000 | above this, every added rule must be paired with a prune |
| `retro_prompt_min_sessions` | 3 | sessions since the last retro before the workflow offers to run one |
| `bootstrap_min_archives` | 10 | archived changes needed to bootstrap Retro in a project that never enabled it |

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
against thresholds with an `escalate to` column, path clusters, build
retries, tokens per session (with a before / after split around the most
recent rule change), workflow adherence (editing sessions that also ran a
review or verify skill), instruction file sizes against the budget, and
archive statistics.

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
