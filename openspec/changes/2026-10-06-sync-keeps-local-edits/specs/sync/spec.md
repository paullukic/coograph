# Spec: sync keeps local edits

## Requirement: template-managed files are written only when untouched

Every file sync copies from the template (skills, agents, prompts, instructions,
retro, layout, code-graph, hooks, commands, `settings.json`, the managed layout
workflow) is decided by one rule, in order:

1. missing in the project: written;
2. equal to the new upstream content (CRLF -> LF, after the project's em-dash setting):
   left alone, recorded;
3. equal to the hash recorded in `.coograph/sync-manifest.json`: overwritten;
4. equal to any earlier upstream version of that template file in the coograph git
   history (same normalisation): overwritten;
5. otherwise: kept; the upstream content is written to `.coograph/upstream/<path>`;
   sync logs `KEPT <path> (local edit). Upstream: .coograph/upstream/<path>. To take
   it, copy that file over yours and sync again.`

The manifest records the hash of what the project holds after the run for rules 1-4.
`--dry-run` decides and logs the same, and writes nothing.

### Scenario: untouched file refreshed
- Given a project synced once (manifest present)
- When the template file changes and sync runs again
- Then the project file equals the new template file

### Scenario: edited file kept and reported
- Given a project synced once, and the project then edits a synced hook
- When sync runs again with a changed template
- Then the hook keeps the project's content, `.coograph/upstream/<path>` holds the
  template content, and the log has one `KEPT` line naming the path

### Scenario: first sync onto an existing customised file
- Given no manifest, and a project file that matches no template version ever shipped
- When sync runs
- Then the file is kept and reported

### Scenario: first sync onto an outdated untouched file
- Given no manifest, and a project file equal to an earlier committed version of the
  template file
- When sync runs
- Then the file is overwritten with the current template

### Scenario: taking upstream
- Given a kept file
- When the user copies `.coograph/upstream/<path>` over it and sync runs
- Then nothing is reported, the manifest records it, and the upstream copy is removed

### Scenario: deleted marker respected
- Given `.github/workflows/coograph-layout.yml` without the `coograph:managed` line
- When sync runs
- Then the workflow is unchanged and logged as kept (customized)

## Requirement: em-dash setting

When the project's `openspec/config.yaml` has a top-level `sync:` block with
`em_dash: hyphen`, every UTF-8 text file sync writes has U+2014 replaced by `-`.
Default (`keep`, or no block): content is copied byte for byte.

### Scenario: normalised files stay in sync
- Given `em_dash: hyphen` and a template file containing an em dash
- When sync runs twice, with the template changed in between
- Then the project file never contains U+2014, and no `KEPT` line is logged

## Requirement: single-project run

`sync.py --project PATH` syncs only the registered project at `PATH` (path compared
after resolving). An unregistered path exits 2 with a message.

## Requirement: layout guard roots and strict mode

- `guard.roots` (optional list of non-empty strings) limits `--guard` to changed paths
  equal to a root or under it; others are neither failures nor uncovered. Invalid
  values make the config invalid at `guard.roots` (exit 2).
- `--strict` with `--guard`: when any changed path under the roots is covered by no
  doc, print `UNCOVERED  <path>` per path and exit 1.
- A path deleted between BASE and HEAD is never reported uncovered.
- Without `roots` and `--strict`, behaviour is unchanged.

## Requirement: scope hook precision

`warn-scope.py`, on the `warn_model` channel (exit 0):
- is silent for targets outside the project root and for anything under `openspec/`;
- picks the active change by the newest `tasks.md` mtime (directory mtime when no open
  change has a `tasks.md`);
- treats a backticked `tasks.md` token ending in `/` as covering every file under it;
- warns once per path per session; a repeat prints nothing and records a `suppressed`
  decision, no violation;
- handles `NotebookEdit` (`notebook_path`) and relative paths (resolved against `cwd`).

## Requirement: briefs name where the rules live

Agent, command and skill briefs that point at project rules say `AGENTS.md` § Hard
rules and `.github/copilot-instructions.md`, and for commands `AGENTS.md` § Commands,
with `.github/copilot-instructions.md` as the fallback when `AGENTS.md` has no such
section. The ultra-review workflow also names `.github/instructions/review.instructions.md`
when it exists. No project-specific names.
