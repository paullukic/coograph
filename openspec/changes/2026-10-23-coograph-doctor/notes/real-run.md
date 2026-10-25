# Real-world run: the doctor on the 10 registered projects

Run from this checkout on 2026-10-23: `python .github/skills/coograph-doctor/doctor.py --project <path>`, which reads `projects.json` next to it. No FAIL in any project. Every WARN was checked by hand (below).

## False alarms found on the first runs, fixed before these reports

1. **`tools` FAIL "missing claude: AGENTS.md"** on coograph-website, metaspry, awaken and gastarbajter. These have an older self-contained `CLAUDE.md` (its hard rules inline, no `@AGENTS.md` import), so they need no `AGENTS.md`. Fix: `AGENTS.md` is required for Claude Code only when `CLAUDE.md` contains `@AGENTS.md`, which is when its absence really drops the rules. Tests: `test_claude_md_import_needs_agents_md`, `test_self_contained_claude_md_needs_no_agents_md`.
2. **`tools` WARN "codex on disk"** on coograph-website. Its `.agents/skills/` holds Firebase skills, not coograph's. Fix: tool detection counts only coograph's own files (`coograph-*` skill and command folders, coograph's agent names, rule files that mention coograph). Test: `test_other_tools_skills_are_not_a_codex_install`.
3. **`mcp:opencode` / `mcp:vscode` FAIL on the coograph checkout itself**, where `.opencode/commands/` and `.github/agents/` are template sources, not installs. Fix: in a template checkout an MCP check runs only when its config file exists. Test: `test_template_checkout_skips_markers` (now also asserts this).

## Hand check of every remaining WARN

| Project | WARN | Verdict |
|---|---|---|
| liftorra, metaspry/app, dueling-book-theme-editor | `tools`: `.github/agents/` on disk, `vscode` not registered | **Real.** Claude Code flows never read `.github/agents/`; sync refreshes it only for `vscode`, so these copies are stale: 6 of 6 agent files differ from the template in liftorra and metaspry/app, 1 of 6 in dueling-book-theme-editor. Register `vscode` or delete the folder. |
| awaken, metaspry/metaspry-website | `hooks:git`: all three graph hooks missing | **Real.** `git rev-parse --git-path hooks` holds no post-commit / post-merge / post-rewrite in either repo. |
| metaspry/metaspry, metaspry/metaspry-website | `sync`: 19 files parked in `.coograph/upstream/` | **Real.** Sampled `.claude/commands/coograph-debug.md`: the parked upstream copy differs from the local one. |
| liftorra, dueling-book-theme-editor | `sync`: 2 files parked | **Real.** liftorra: `.claude/hooks/warn-scope.py` and `.github/retro/_coograph_signals.py`; dueling-book-theme-editor: `.claude/settings.json` and `.github/code-graph/package-lock.json`. The sampled ones differ from their parked upstream copies. |

The coograph checkout itself: `graph-age` WARN (14 files the graph indexes, such as `.mcp.json` and `projects.json`, changed in commits after its last build 28 days ago; true) and `hooks:git` WARN (its `post-merge` is the sync hook from `setup.sh`, not a graph update, true).

## Fresh init from this branch (acceptance: all PASS)

A scratch copy of `coograph-testbed/projects/python-api`, `git init` + one commit, then a real `/coograph-init` in a nested non-interactive Claude Code session (session id `11111111-aaaa-4bbb-8ccc-00000d0c7012`, excluded from Retro by its prefix) with every option yes: Claude Code + VS Code Copilot + OpenCode, code-graph, git hooks, Retro, layout CI. Step 8 was skipped on purpose so the real `projects.json` stayed untouched (verified with `git diff`).

Init's own Step 12, re-run independently afterwards, gave the same result: **11 PASS, 0 WARN, 0 FAIL, 1 SKIP** (exit 0). The one SKIP is `sync` ("never synced"), expected for a project that is not registered.

Things the nested init noticed that are outside this change (not touched):
- `explore.agent.md` and `retro.agent.md` in the template lack the `MANDATORY — non-negotiable` Step 0 block that init Step 7 checks for.
- The graph build of the scratch project reported `css, react` stacks the project does not have (stack detection, code-graph).

## Reports (after the review fixes)

### awaken

```
coograph doctor: C:\paul\code\awaken
PASS  graph         1081 nodes, 3520 edges, 352 files, 576 calls; built 47 min ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
WARN  hooks:git     post-commit missing; post-merge missing; post-rewrite missing
      fix: copy them: for h in post-commit post-merge post-rewrite; do cp .github/code-graph/$h "$(git rev-parse --git-path hooks)/$h"; chmod +x "$(git rev-parse --git-path hooks)/$h"; done
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
PASS  sync          no upstream copies waiting
Summary: 9 PASS, 1 WARN, 0 FAIL, 0 SKIP
```

### coograph-website

```
coograph doctor: C:\paul\code\coograph-website
PASS  graph         280 nodes, 418 edges, 82 files, 74 calls; built 1.8 h ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
PASS  hooks:git     post-commit, post-merge, post-rewrite update the graph
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
PASS  sync          no upstream copies waiting
Summary: 10 PASS, 0 WARN, 0 FAIL, 0 SKIP
```

### dueling-book-theme-editor

```
coograph doctor: C:\paul\code\dueling-book-theme-editor
PASS  graph         4089 nodes, 14452 edges, 614 files, 8006 calls; built 1 min ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
WARN  tools         registered: claude; on disk but not in projects.json: vscode
      fix: update the project's tools in projects.json (ids: claude, vscode, codex, opencode, cursor, devin, aider, cline), or remove the stray files
PASS  hooks:git     post-commit, post-merge, post-rewrite update the graph
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  8 wired hook(s) present
WARN  sync          2 template file(s) kept as local edits, newer upstream waiting in .coograph/upstream/: .claude/settings.json, .github/code-graph/package-lock.json
      fix: compare each with your copy; to take upstream, copy it over yours and run coograph's sync.py --project again
Summary: 8 PASS, 2 WARN, 0 FAIL, 0 SKIP
```

### gastarbajter

```
coograph doctor: C:\paul\code\gastarbajter
PASS  graph         1324 nodes, 2947 edges, 328 files, 280 calls; built 1.8 h ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
SKIP  hooks:git     not a git repo
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
PASS  sync          no upstream copies waiting
Summary: 9 PASS, 0 WARN, 0 FAIL, 1 SKIP
```

### liftorra

```
coograph doctor: C:\paul\code\liftorra
PASS  graph         5579 nodes, 13962 edges, 933 files, 4594 calls; built 48 min ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
WARN  tools         registered: claude; on disk but not in projects.json: vscode
      fix: update the project's tools in projects.json (ids: claude, vscode, codex, opencode, cursor, devin, aider, cline), or remove the stray files
PASS  hooks:git     post-commit, post-merge, post-rewrite update the graph
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
WARN  sync          2 template file(s) kept as local edits, newer upstream waiting in .coograph/upstream/: .claude/hooks/warn-scope.py, .github/retro/_coograph_signals.py
      fix: compare each with your copy; to take upstream, copy it over yours and run coograph's sync.py --project again
Summary: 8 PASS, 2 WARN, 0 FAIL, 0 SKIP
```

### metaspry

```
coograph doctor: C:\paul\code\metaspry
SKIP  graph         code-graph not enabled
SKIP  graph-age     code-graph not enabled
SKIP  server        code-graph not enabled
SKIP  mcp:claude    code-graph not enabled
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
SKIP  hooks:git     code-graph not enabled
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
PASS  sync          no upstream copies waiting
Summary: 5 PASS, 0 WARN, 0 FAIL, 5 SKIP
```

### metaspry/app

```
coograph doctor: C:\paul\code\metaspry\app
PASS  graph         1927 nodes, 4279 edges, 424 files, 717 calls; built 47 min ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
WARN  tools         registered: claude; on disk but not in projects.json: vscode
      fix: update the project's tools in projects.json (ids: claude, vscode, codex, opencode, cursor, devin, aider, cline), or remove the stray files
PASS  hooks:git     post-commit, post-merge, post-rewrite update the graph
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
PASS  sync          no upstream copies waiting
Summary: 9 PASS, 1 WARN, 0 FAIL, 0 SKIP
```

### metaspry/metaspry-website

```
coograph doctor: C:\paul\code\metaspry\metaspry-website
PASS  graph         240 nodes, 350 edges, 70 files, 87 calls; built 1.6 h ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
WARN  hooks:git     post-commit missing; post-merge missing; post-rewrite missing
      fix: copy them: for h in post-commit post-merge post-rewrite; do cp .github/code-graph/$h "$(git rev-parse --git-path hooks)/$h"; chmod +x "$(git rev-parse --git-path hooks)/$h"; done
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
WARN  sync          19 template file(s) kept as local edits, newer upstream waiting in .coograph/upstream/: .claude/commands/coograph-debug.md, .claude/commands/coograph-init.md, .claude/commands/coograph-new-ticket.md, .claude/commands/coograph-plan.md, .claude/commands/coograph-review.md (+14 more)
      fix: compare each with your copy; to take upstream, copy it over yours and run coograph's sync.py --project again
Summary: 8 PASS, 2 WARN, 0 FAIL, 0 SKIP
```

### metaspry/metaspry

```
coograph doctor: C:\paul\code\metaspry\metaspry
PASS  graph         530 nodes, 1234 edges, 162 files, 182 calls; built 1.3 h ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
PASS  hooks:git     post-commit, post-merge, post-rewrite update the graph
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
WARN  sync          19 template file(s) kept as local edits, newer upstream waiting in .coograph/upstream/: .claude/commands/coograph-debug.md, .claude/commands/coograph-init.md, .claude/commands/coograph-new-ticket.md, .claude/commands/coograph-plan.md, .claude/commands/coograph-review.md (+14 more)
      fix: compare each with your copy; to take upstream, copy it over yours and run coograph's sync.py --project again
Summary: 9 PASS, 1 WARN, 0 FAIL, 0 SKIP
```

### wisehosting

```
coograph doctor: C:\paul\code\wisehosting
PASS  graph         31482 nodes, 65079 edges, 9781 files, 11792 calls; built 46 min ago
PASS  graph-age     no indexed file changed in a commit since the last build
PASS  server        .github/code-graph/server.py present; uv at C:\Users\paull\.local\bin\uv.EXE
PASS  mcp:claude    .mcp.json: code-graph via uv
PASS  markers       no _TBD_ or <!-- FILL markers left
PASS  tools         registered: claude
SKIP  hooks:git     not a git repo
PASS  openspec      openspec/config.yaml parses
PASS  hooks:claude  9 wired hook(s) present
PASS  sync          no upstream copies waiting
Summary: 9 PASS, 0 WARN, 0 FAIL, 1 SKIP
```
