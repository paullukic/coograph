# Proposal: sync keeps a project's local edits

Status: approved 2026-10-06 (founder: "fix coograph and make a PR to coograph").

## Why

On 2026-10-06 a `git pull` of coograph ran `.github/sync.py` (post-merge hook) and
reverted committed local edits in a registered project's working tree. Sync copies
every template-managed file with `shutil.copy2`, no questions asked, and logs only
"97 files updated". The project had, on purpose:

- improved its copy of `.claude/hooks/warn-scope.py` (precision fixes, see below);
- added `guard.roots` and `--strict` to `.github/layout/layout.py` and documented them
  in `.github/layout/README.md`;
- pointed its command and skill briefs at `AGENTS.md` § Hard rules / § Commands,
  where the tier layout keeps them (the template briefs still say
  `.github/copilot-instructions.md`, which no longer holds the hard rules);
- escalated a retro rule to a block in `.claude/hooks/no-new-deps-warn.py` (a per
  project retro decision, see the retro skill's `edit-rule` hook upgrade);
- normalised every em dash in synced text files to its house style.

All of it was silently replaced. Retro's own design creates this situation: a retro
proposes edits to `.claude/hooks/*.py` in the project (hook upgrades, new hooks), and
the next sync deletes them. `MIGRATION.md` already lists two earlier instances of the
same class of bug (`AGENTS.md`, `.mcp.json`), each fixed for one file.

Several of the project's edits are general bugs or features. They belong upstream.

## Goals

1. **Sync never silently overwrites a local edit.** Every template-managed file sync
   writes goes through one function that tells "untouched since sync wrote it" from
   "edited here". An edited file is kept, the upstream version is written to
   `.coograph/upstream/<path>`, and sync prints one line per kept file naming it and
   how to take the upstream version.
2. **Upstream the general fixes:**
   - `layout.py`: optional `guard.roots`, `--strict` for `--guard`, deleted paths never
     reported uncovered. Documented, tested with the project's fixture cases.
   - `warn-scope.py`: precision fixes, on the new `warn_model` channel.
   - Agent, command and skill briefs name `AGENTS.md` § Hard rules and § Commands, with
     the old layout as fallback; the ultra-review brief names
     `.github/instructions/review.instructions.md` when it exists.
3. **Optional em-dash normalisation**, a project setting sync honours, so a project with
   that house style can keep receiving updates instead of having every synced file
   reported as a local edit.

## Non-Goals

- No upstreaming of the project's `no-new-deps` hard block: it is a per-project retro
  escalation. Goal 1 is what lets it survive.
- No upstreaming of any house style. Em-dash normalisation is opt-in and off by default.
- No change to user-owned files (`SKIP_FILES`, `AGENTS.md`, `.mcp.json` merge,
  `rules.json` / `layout.json` merges): they already never get overwritten.
- No three-way merge. A kept file stays as the project has it until someone takes the
  upstream copy by hand.
- Deleted template files are still re-created (unchanged behaviour); a project removes
  one for good through `OBSOLETE_PATHS` upstream, not locally.
- `templates/` (Aider, Cline, Cursor, Windsurf rule files) keep their wording.

## Decisions

- **Manifest of what sync wrote.** `.coograph/sync-manifest.json` maps each
  project-relative path to the sha256 of the content sync last wrote (or found equal to
  upstream). Hashes are taken after CRLF -> LF, so a `core.autocrlf` checkout is not an
  edit. `.coograph/` is already the per-project local state directory.
- **Decision per file** (`_write_managed`):
  1. missing: write it, record it;
  2. equal to the new upstream: record it, do not rewrite;
  3. equal to the manifest hash: untouched since the last sync, so overwrite;
  4. equal to any earlier upstream version of that template file: untouched, only
     outdated, so overwrite. Earlier versions come from the coograph checkout's git
     history (`git log --raw` over the synced trees, one `git cat-file --batch`);
  5. anything else: a local edit. Keep it, write `.coograph/upstream/<path>`, report.
  Rule 4 is why no manifest is needed for a safe first run: without it, the first sync
  after this change would report every outdated file in every project as edited and
  stop all updates. A file that matches no upstream version ever shipped, with no
  manifest entry, is a local edit, as the task requires. A checkout without git history
  degrades to rules 1-3 and 5 (more files kept, never one lost).
- **Taking upstream.** Copy `.coograph/upstream/<path>` over the file; the next sync sees
  rule 2 and records it. A stale upstream copy is removed once the file matches
  upstream again.
- **`coograph:managed` stays.** The layout workflow without the marker line is kept as
  before. With the marker, it now also goes through `_write_managed`, so an edit that
  keeps the marker is protected too.
- **`--project PATH`** limits a sync run to one registered project. Re-init in repo mode
  uses it, so init's refresh of template-managed files gets the same protection; in
  plugin mode init asks once before replacing differing files.
- **Em dash setting** lives in the project's `openspec/config.yaml` (already the
  project's, never synced), as a top-level block read with a line regex (no YAML
  dependency):
  ```yaml
  sync:
    em_dash: hyphen   # keep (default) | hyphen
  ```
  `hyphen` replaces U+2014 with `-` in every UTF-8 text file sync writes. Rules 2-4
  compare against the normalised content, so a normalised file is never "edited".
- **Layout guard.** `guard.roots` is an optional list of path prefixes; a root without a
  trailing `/` matches the path itself or anything under it. Not in the seed, so
  `DEFAULTS == seed` holds. Deleted paths come from `git diff --diff-filter=D`, not
  from the working tree, so the check is right for any `HEAD`.
- **Scope hook.** Keeps the `warn_model` channel (additionalContext, exit 0) and adds:
  silent outside the project root and under `openspec/`; active change = newest
  `tasks.md` mtime (directory mtime only when no change has one); a backticked token
  ending in `/` covers files under it; one warning per path per session (marker
  `.coograph/markers/scope-warned-<sid>`), repeats recorded as a `suppressed` decision
  with no violation; `NotebookEdit` handled; relative paths resolved against `cwd`.

## Impact

- `.github/sync.py`, `.github/layout/layout.py`, `.github/layout/README.md`,
  `.claude/hooks/warn-scope.py`, briefs in `.claude/commands/`, `.github/skills/`,
  `.github/agents/`, `coograph-ultra-review/workflow.js`, init skill (re-init refresh),
  tests (`.github/layout/tests/`, `.github/retro/tests/`), `README.md`, `MIGRATION.md`,
  plugin rebuild (1.8.2).
- Every registered project: the next sync writes `.coograph/sync-manifest.json` and may
  report kept files. Projects that hand-edited synced files get them back the way they
  were only if they restore them from git; sync no longer destroys them from then on.

## Risks

- **A kept file falls behind upstream.** Visible: one warning line per sync per file,
  and the upstream copy sits next to it under `.coograph/upstream/`.
- **Rule 4 overwrites a deliberate revert to an older upstream version.** Accepted:
  that content is upstream's own; the edit, if any, is "use the old version", which
  `OBSOLETE_PATHS`-style upstream fixes handle better.
- **Em dash in code.** `hyphen` also rewrites string literals in synced `.py`/`.js`.
  Today no synced code matches on an em dash (checked); documented as a caveat.
- **History read cost.** One `git log` and one `git cat-file` per sync run, shared by
  all projects; the coograph repo is small.
