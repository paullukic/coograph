# Tasks: coograph-doctor

- [x] **1. Tests first.** `.github/skills/coograph-doctor/tests/test_doctor.py`: a fixture builder for the passing project (real `sqlite3` graph, real `git init`), then one test per scenario in `specs/coograph-doctor/spec.md` (each broken category, optional features off, template checkout, no registry, read-only, `--json`, exit codes).
  - Acceptance: every test fails before `doctor.py` exists (import error counts) and is written against the spec, not the implementation.

- [x] **2. `doctor.py`.** The ten checks, output format, `--project` / `--registry` / `--json`, exit codes; stdlib only, read-only.
  - Files: `.github/skills/coograph-doctor/doctor.py`
  - Acceptance: task 1 green; `python3 doctor.py --project <coograph checkout>` runs and SKIPs `markers`.

- [x] **3. Skill and per-tool invocation.** Canonical `SKILL.md` (run, report, offer fixes, never auto-fix); `.claude/commands/coograph-doctor.md`, `.opencode/commands/coograph-doctor.md`, `.agents/skills/coograph-doctor/SKILL.md`; an Invocation line in `AGENTS.md`, `templates/cursor/.cursor/rules/coograph.mdc`, `templates/windsurf/.windsurfrules`, `templates/aider/CONVENTIONS.md`, `templates/cline/.clinerules`.
  - Acceptance: each file names `.github/skills/coograph-doctor/SKILL.md` and the trigger form its tool uses.

- [x] **4. Drift check and CI.** `check-invocations.py` asserts per skill (init, doctor); a doctor-tests step in `.github/workflows/checks.yml`.
  - Files: `.github/scripts/check-invocations.py`, `.github/workflows/checks.yml`
  - Acceptance: `python .github/scripts/check-invocations.py` exits 0; removing the doctor line from one rule file makes it exit 1 naming the file (checked by hand, then restored).

- [x] **5. Init integration.** `.github/skills/coograph-init/SKILL.md`: Step 3 command lists and Codex `.agents/skills/coograph-*/`, "never `tests/`" for `.github/skills/`, Step 8 tool ids, a new final step that runs the doctor; init wrappers say "every step" and mention it; `build-plugin.py` `TEMPLATE_PATHS` ships `.agents/skills`.
  - Files: `.github/skills/coograph-init/SKILL.md`, `.claude/commands/coograph-init.md`, `.opencode/commands/coograph-init.md`, `.agents/skills/coograph-init/SKILL.md`, `.github/scripts/build-plugin.py`
  - Acceptance: `check-reinit-idempotency.py` and `check-invocations.py` still exit 0.

- [x] **6. Real-world run.**
  - Run the doctor on all 10 registered projects (`--project <path>` from this checkout) and on a scratch project freshly initialized from this branch with every option yes.
  - Write each report to `notes/real-run.md` and hand-check every FAIL and WARN (real problem, or false alarm?).
  - Acceptance: the scratch init gives all PASS; no hand-checked FAIL is a false alarm; any false WARN is fixed or explained.

- [x] **7. Docs and release.** `README.md` and `SETUP.md` invocation tables (doctor row; OpenCode "all four" becomes five); `MIGRATION.md` entry; `VERSION` (next free number at merge, 1.8.12 if 1.8.9 to 1.8.11 land first) in `.github/scripts/build-plugin.py`; run `python .github/scripts/build-plugin.py` and revert plugin files whose diff is only line endings. Website: `coograph-website/src/pages/docs/getting-started.mdx` "Check the install" section, committed in that repo on its own branch.
  - Acceptance: `build-plugin.py --check` passes; the website builds (`npm run build` there) or the reason it can't is reported.

## Review Fixes

- [x] **R1. graph-age false WARN** (Warning): a commit after the build counts only when it touched a file of a kind the graph indexes (`git log --since --relative --name-only`, per child repo in a multi-repo workspace). Tests: `test_docs_only_commit_after_the_graph_passes`, `test_code_commit_after_the_graph_warns`, `test_code_commit_within_tolerance_passes`, `test_multi_repo_workspace_dates_the_graph_by_its_child_repos`.
- [x] **R2. `__pycache__` into projects** (Warning): tests set `sys.dont_write_bytecode` before importing doctor; init Step 3 excludes `__pycache__/` from `.github/skills/`; the no-op line in doctor.py removed.
- [x] **R3. `${workspaceFolder}` expanded for every tool** (Warning): only VS Code and Cursor; elsewhere a leftover `${...}` is a FAIL. Test: `test_workspace_variable_outside_vscode_fails`.
- [x] **R4. openspec status vs proposal** (Warning): the proposal now says PASS for the structural check (and why); test `test_openspec_config_passes_without_pyyaml`.
- [x] **R5. Nits:** code-graph off only when no folder and no registry `true` (spec R5, test); "not in projects.json" label (test); non-object registry exits 2 (test); uv WARN text without MCP configs; `BUILD_CMD` constant; `${CLAUDE_PROJECT_DIR}` / backslash hook paths (test); unused defaults in check-invocations; init "Steps 2–12" and the OpenCode delegation line; website "a WARN only for a declined option" (en, zh-CN, zh-TW); notes liftorra row. Not done: the `sync.py` comment about `tests/` dirs (file out of scope; the comment is stale, the behaviour is right).

- [x] **R6. graph-age, second round** (Warning): a changed file counts only when it is already in the graph, or has an indexed extension outside the folders the builder skips (dot-folders, its `_IGNORE_DIRS`, mirrored as `BUILDER_SKIPS_DIRS`), so a sync commit of `.github/` tooling stays PASS. Tests: `test_commit_only_where_the_builder_never_looks_passes` (fails on the previous version), `test_commit_to_a_file_already_in_the_graph_warns`.

- [x] **8. Verification.** Doctor tests, retro and layout suites, `check-invocations.py`, `check-reinit-idempotency.py` and `build-plugin.py --check` all green; feature inventory of the init skill and the edited rule files (every existing invocation line kept); `@Reviewer` gate; local commits only (coograph on `feat/coograph-doctor`, website on its own branch).
