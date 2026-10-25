---
name: coograph-doctor
description: Health check of a Coograph install. Runs a read-only script that checks the code graph, its server and MCP configs, unfilled placeholders, per-tool files, git and Claude Code hooks, openspec/config.yaml and pending sync copies, then offers the fix for each problem. Trigger when the user types `/coograph-doctor` or `$coograph-doctor`, or asks to "check the install", "run the doctor", or why coograph seems broken.
argument-hint: Optional. A project path (default the current folder); "--registry <coograph>/projects.json" to compare against the registry.
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

Check that this project's Coograph install is healthy. The script only reads. Fixes happen only after the user says yes, one at a time.

---

## Step 1: Locate the script

The script ships next to this file: `.github/skills/coograph-doctor/doctor.py`. In plugin mode it is `<plugin>/skills/coograph-doctor/doctor.py`. If neither exists, say the install predates the doctor and that re-running `/coograph-init` (or a coograph `git pull` for registered projects) delivers it. Then stop.

## Step 2: Run it

```bash
python3 .github/skills/coograph-doctor/doctor.py --project <project>
```

- `<project>` defaults to the current folder; pass the user's path if they named one.
- **Repo mode:** run the copy inside the coograph checkout (`<coograph>/.github/skills/coograph-doctor/doctor.py --project <project>`). It then compares against `projects.json` on its own. Inside a project, add `--registry <coograph>/projects.json` when the user knows where the checkout is.
- **Plugin mode:** there is no registry. Tools are detected from the files on disk, and the report says so.
- On Windows, use `python` when `python3` is missing.

Exit 0 means no FAIL, 1 means at least one FAIL, 2 means a bad argument (show the message and stop).

## Step 3: Report

Show the output as it is: one `PASS` / `WARN` / `FAIL` / `SKIP` line per check, a `fix:` line under each problem, and the summary. Then one sentence: "N problems, the first one to fix is <check>". Order: FAIL before WARN, then the order printed.

The checks, so you can explain any of them:

| Check | Looks at |
|---|---|
| `graph` | `.code-graph/graph.db` exists, its node/edge/file counts; WARN when many functions have no call edges (built without tree-sitter) |
| `graph-age` | every committed file of an indexed kind matches the content hash the graph holds (child repos too in a multi-repo workspace); uncommitted edits are left out |
| `server` | `.github/code-graph/server.py` and `requirements.txt`; `uv` on PATH |
| `mcp:<tool>` | the code-graph entry in `.mcp.json`, `.vscode/mcp.json`, `.cursor/mcp.json`, `opencode.json` (JSONC where the tool accepts it), and that every path in it exists after the tool's own variables are expanded; WARN when a variable is not set where the doctor runs |
| `markers` | `_TBD_` / `<!-- FILL` left in `.github/copilot-instructions.md`, `CLAUDE.md`, `AGENTS.md` (backticked mentions, as in the template guard line, do not count) |
| `tools` | each installed tool's files; registry vs disk |
| `hooks:git` | `post-commit`, `post-merge`, `post-rewrite` update the graph; tells a missing hook apart from one that belongs to another tool |
| `openspec` | `openspec/config.yaml` exists and parses |
| `hooks:claude` | every hook `.claude/settings.json` wires exists |
| `sync` | template files sync kept as local edits, with the newer upstream copy waiting in `.coograph/upstream/` |

SKIP means the check does not apply (feature not enabled, not a git repo, template checkout). It is never a problem.

## Step 4: Offer fixes, one at a time

For each FAIL, then each WARN, offer the fix and wait for a yes before doing anything:

| Check | Fix |
|---|---|
| `graph`, `graph-age` | the `coograph-rebuild-graph` skill (`build` for a missing or empty graph, the tree-sitter WARN, or a graph without file hashes; `update` for an old one), or the raw command on the `fix:` line |
| `server`, `mcp:<tool>`, `markers`, `tools`, `hooks:claude`, `openspec` | re-run `/coograph-init` on the project. Its Step 1b adds what is missing and also offers to refresh template-managed files that differ from the template (skills, agents, `.claude/hooks/`, `.claude/settings.json`); before the user answers, list the differing files and ask which to keep. For `markers`, offer to fill the listed lines directly instead. For a config that is not valid JSON, fix its syntax by hand: init cannot merge into it either |
| `hooks:git` | the command on the `fix:` line (init Step 6h) for a missing hook. Never copy over a hook that already exists: add the one line the `fix:` line names, before its first `exit` or `exec`; a hook in another language calls the coograph hook in its own language |
| `sync` | show the diff between each parked file and the local one; the user decides per file. Never copy over a local edit unasked |

A `tools` WARN about files on disk for an unregistered tool is the user's call: add the tool to `projects.json`, or delete the stray files. Never edit `projects.json` or delete files without that answer.

After any fix, run the script again and show the new summary.

## Guardrails

- The script is read-only; keep it that way. Never pass it flags that write, and never wrap it in commands that do.
- Never apply a fix without an explicit yes for that fix.
- Report every FAIL and WARN. Do not soften one into "probably fine". If a result looks wrong, say why and show the evidence (the file, the line, the command output).
