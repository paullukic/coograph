# Tasks: sync-keeps-local-edits

- [x] **1. Sync keeps local edits.** `_write_managed`, manifest, upstream history, upstream copies, `KEPT` report, `--project`, em-dash setting. Every template copy in `sync_project` goes through it.
  - Files: `.github/sync.py`
  - Acceptance: the sync scenarios in `specs/sync/spec.md` pass.

- [x] **2. Sync tests.**
  - Files: `.github/layout/tests/test_sync.py`
  - Acceptance: untouched file refreshed; edited file kept and reported; first sync onto a customised file kept; first sync onto an outdated untouched file refreshed (git history); taking upstream; deleted marker respected; em-dash setting; dry run writes nothing; `--project`.

- [x] **3. Layout guard roots and strict.**
  - Files: `.github/layout/layout.py`, `.github/layout/README.md`, `.github/layout/tests/test_layout.py`
  - Acceptance: the project's fixture cases (covered with/without doc, uncovered strict / not strict, outside roots, skip marker, deleted file) pass as unit tests; invalid `guard.roots` exits 2; `DEFAULTS == seed` still holds.

- [x] **4. Scope hook precision.**
  - Files: `.claude/hooks/warn-scope.py`, `.github/retro/tests/test_capture.py`
  - Acceptance: tests for outside root, `openspec/` path, newest `tasks.md`, directory token, once per path with `suppressed`, NotebookEdit, relative path; existing warn-channel tests stay green.

- [x] **5. Briefs.**
  - Files: `.claude/commands/coograph-{debug,new-ticket,plan,review,search,verify}.md`, `.github/skills/coograph-{apply,new-ticket,propose}/SKILL.md`, `.github/skills/coograph-ultra-review/workflow.js`, `.github/agents/{debugger,planner,reviewer,verifier}.agent.md`
  - Acceptance: no brief calls `.github/copilot-instructions.md` the single source of the hard rules or of the commands; fallback stated; no project names.

- [x] **6. Init re-run refresh.**
  - Files: `.github/skills/coograph-init/SKILL.md`
  - Acceptance: template-managed refresh uses `sync.py --project` in repo mode and asks once in plugin mode; never states that these files are never customised.

- [x] **7. Docs and release.**
  - Files: `README.md`, `MIGRATION.md`, `.github/scripts/build-plugin.py` (`VERSION` 1.8.2), `plugin/`, `.claude-plugin/marketplace.json`
  - Acceptance: README sync section and settings note describe kept files; MIGRATION entry says what projects see and how to take upstream; `build-plugin.py --check` passes.

- [x] **8. Verification.**
  - Acceptance:
    - every CI job command in `.github/workflows/checks.yml` passes locally (invocation drift, re-init idempotency, plugin check, retro tests, layout tests + template budget, code-graph tests);
    - `python .github/sync.py --dry-run` against the real registry runs clean (7 projects, 0 KEPT: their working trees hold earlier upstream versions, recognised through history). On an export of the motivating project's committed `HEAD`: 45 KEPT without the em-dash setting, 15 with `em_dash: hyphen` (exactly its real local edits); a second real run writes 0;
    - review gate run on the diff, Critical/Warning findings fixed.

## Review Fixes

- [x] An unreadable or unwritable target is `SKIPPED`, never treated as missing and never recorded; one locked file no longer aborts the run (tests: directory in place of a file, a failing write).
- [x] `_History._cat` skips the body of any object type and stops on a malformed size (test: commit sha and missing sha in the input).
- [x] Init's agent-marker grep accepts `-` as well as an em dash, and the restore step writes the block normalised under `em_dash: hyphen`, so re-init cannot undo the setting.
- [x] `warn-scope.py` resolves the root from `CLAUDE_PROJECT_DIR` like the other hooks (test: session cwd in a subdirectory).
- [x] `guard.roots` rejects roots that can never match (`./x`, backslashes, globs, spaces).
- [x] New tests: binary template file unchanged under `hyphen`; file mode kept on a rendered write (POSIX).
