# Ultra review rounds

## Round 1: full, 8d8f45e (2026-10-25)

28 agents, 1.52M tokens, 6 min. Verdict REQUEST_CHANGES: 1 Critical, 9 Warning, 1 follow-up, 0 refuted.

| # | Sev | Where | Finding | Fix |
|---|---|---|---|---|
| 1 | Critical | doctor.py check_git_hooks | a hook owned by another tool (git lfs, husky, coograph's own sync post-merge) got an unconditional `cp` fix | missing and foreign hooks told apart; foreign ones get an append-one-line fix, never a copy. Seen live: coograph's own post-merge is the sync hook |
| 2 | Warning | check_graph_age | dated by db mtime; a no-op `--update` cannot clear the WARN | content comparison: file_hashes vs the sha1 of every committed, clean file |
| 3 | Warning | check_graph_age | committer dates miss a pull of older commits | same content comparison; also flags new and deleted files |
| 4 | Warning | REINIT, SKILL.md | "copies only what is missing" contradicts init Step 1b | text says re-init also offers to refresh differing template files; SKILL tells the agent to list them first |
| 5 | Warning | _mcp_entry | JSONC configs failed; fix said re-init | JSONC parsed for vscode, cursor, opencode; a broken file gets a fix-by-hand fix |
| 6 | Warning | check_server | an absolute uv path FAILed without uv on PATH | only a bare `uv` needs PATH |
| 7 | Warning | check_mcp | every `${...}` treated as unexpanded | per-tool expansion (`${VAR}`, `${VAR:-d}`, `${env:X}`, `${userHome}`, `{env:X}`); unset variable is WARN cannot verify |
| 8 | Warning | graph-age fix | `/coograph-rebuild-graph` is not registered in repo mode | raw `server.py --update` command in the fix |
| 9 | Warning | tests | `.github/agents/` user-agent case passed vacuously | own test with vscode unregistered and no coograph agents |
| 10 | Warning | tests | PyYAML branch never ran in CI | stubbed-yaml test; empty config FAILs on both paths |

13 of the new tests fail against 8d8f45e's doctor.py; the two coverage tests (9, 10) pass on both, as expected.

## Round 2: delta, 9025755 (2026-10-25)

8 agents, 0.45M tokens, 4 min. Verdict REQUEST_CHANGES. Previous: 9 of 10 fixed; #7 partly (variables the doctor does not model still FAILed).

| # | Sev | Where | Finding | Fix |
|---|---|---|---|---|
| 11 | Warning | check_graph_age | `git diff --name-only` names paths from the repo top, `ls-files` from the project: a project in a subfolder WARNed on uncommitted edits | `--relative` |
| 12 | Warning | _expand (= #7 rest) | `${input:x}`, `${workspaceFolderBasename}`, `{file:x}` left in the path, FAIL missing | any leftover variable is WARN cannot verify |
| 13 | Warning | check_git_hooks | foreign-hook fix had a `<hook>` placeholder, only covered a trailing exec, would break a non-shell hook | one concrete line per hook, before the first exit or exec; a non-shell hook gets call-it-in-its-language |

4 new tests, each fails against 9025755.

### Follow-up, not fixed here (pre-existing init text)

- `.github/skills/coograph-init/SKILL.md` Step 6e pip fallback writes `${workspaceFolder}` into every config, including `.mcp.json` and `opencode.json`, which pass it on literally; the doctor FAILs that config and its re-init fix writes it again. The OpenCode pip variant also passes `requirements.txt` as a python argument. Fix: project-relative paths outside VS Code, drop requirements.txt from the OpenCode python args. Separate change.

## Round 3: delta, 2426fbc (2026-10-25)

4 agents, 0.2M tokens, 2 min. Verdict APPROVE: previous 11-13 fixed, no new findings.

Open, non-blocking:
- Nit: the mcp "cannot verify" WARN text says the variable "is not set where the doctor runs", which misleads for `${input:x}` / `{file:x}` (not env variables). Word it neutrally.
- Missing tests the reviewer listed: foreign hook with no shebang, `${workspaceFolderBasename}` through check_mcp, deleted file in a subfolder project, a sh hook ending in exit, shebang edge cases.

Next per the skill: one `full` run with `pr: N` once the PR exists, then the human review.
