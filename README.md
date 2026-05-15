<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo-light.svg" alt="Coograph — graph-first context for AI coding" width="520">
  </picture>
</p>

<p align="center">
  <a href="https://coograph.com"><img src="https://img.shields.io/badge/site-coograph.com-D4501F?style=flat-square&labelColor=1A1A1A" alt="Website"></a>
  <a href="https://coograph.com/docs/"><img src="https://img.shields.io/badge/docs-read-2A2A2A?style=flat-square&labelColor=1A1A1A" alt="Docs"></a>
  <a href="https://coograph.com/roadmap/"><img src="https://img.shields.io/badge/roadmap-public-2A2A2A?style=flat-square&labelColor=1A1A1A" alt="Roadmap"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2A2A2A?style=flat-square&labelColor=1A1A1A" alt="License"></a>
  <a href="https://github.com/paullukic/coograph/stargazers"><img src="https://img.shields.io/github/stars/paullukic/coograph?style=flat-square&labelColor=1A1A1A&color=2A2A2A" alt="Stars"></a>
  <a href="https://github.com/paullukic/coograph/issues"><img src="https://img.shields.io/github/issues/paullukic/coograph?style=flat-square&labelColor=1A1A1A&color=2A2A2A" alt="Issues"></a>
  <a href="https://codespaces.new/paullukic/coograph"><img src="https://github.com/codespaces/badge.svg" alt="Open in GitHub Codespaces" height="20"></a>
</p>

Reusable AI coding assistant configuration for any project. Works with **Claude Code**, **VS Code Copilot**, **Codex CLI**, **OpenCode**, **Cursor**, **Windsurf**, **Aider**, and **Cline** — eight tools, one unified workflow.

Ships a structured workflow, specialized agents with anti-hallucination guardrails, Claude Code lifecycle hooks, and an optional code-graph MCP server that replaces brute-force file searching with targeted SQLite queries.

**Links:** [coograph.com](https://coograph.com) · [docs](https://coograph.com/docs/) · [getting started](https://coograph.com/docs/getting-started/) · [code graph](https://coograph.com/docs/code-graph/) · [workflow](https://coograph.com/docs/workflow/) · [roadmap](https://coograph.com/roadmap/) · [pro](https://coograph.com/pro/)

## Contents

- [Quick Start](#quick-start)
- [What's Inside](#whats-inside)
- [How it compares](#how-it-compares)
- [Workflow](#workflow)
- [Agents](#agents)
- [Claude Code Hooks](#claude-code-hooks)
- [Code Graph](#code-graph)
- [Customization](#customization)
- [Star history](#star-history)
- [Acknowledgments](#acknowledgments)
- [Sponsor](#sponsor)

## Quick Start

Trigger the initializer in your AI tool's chat. Each tool has its own invocation syntax — there is **no single command that works everywhere**, because each tool registers custom workflows differently. Coograph ships native config for all eight.

| Tool | Invoke with | Wired via |
|---|---|---|
| **Claude Code** | `/coograph-init` | `.claude/commands/coograph-init.md` |
| **VS Code Copilot** | `/coograph-init` | `.github/skills/coograph-init/` skill folder |
| **Codex CLI** | `$coograph-init` (explicit skill) **or** "initialize the project" (auto-trigger) | `.agents/skills/coograph-init/SKILL.md` (Codex scans repo root). Codex reserves `/` for built-ins, so custom workflows use `$name` |
| **OpenCode** | `/coograph-init` | `.opencode/commands/coograph-init.md` |
| **Cursor** | `/coograph-init` (string match — no autocomplete) | `.cursor/rules/coograph.mdc` § Invocation |
| **Windsurf** | `/coograph-init` (string match) | `.windsurfrules` § Invocation |
| **Aider** | `/coograph-init` (string match) | `CONVENTIONS.md` § Invocation |
| **Cline** | `/coograph-init` (string match) | `.clinerules` § Invocation |

Natural-language paraphrases ("initialize the project", "set up coograph", "wire up coograph in this repo") work in **every** tool — each config file lists those triggers alongside the slash form, and Codex CLI's skill auto-activates from the description match.

The initializer prompts which tools to set up (multi-select), detects your stack, fills all `_TBD_` placeholders, and optionally sets up the code-graph. About 2 minutes.

Manual setup: see [SETUP.md](SETUP.md). Prerequisites and visualizer: see [.github/code-graph/README.md](.github/code-graph/README.md).

## What's Inside

| Component | Purpose |
|-----------|---------|
| **Workflow** | Plan → Propose → Apply → Review → Archive pipeline |
| **Agents** | 5 specialized agents (Planner, Reviewer, Debugger, Verifier, Explore) |
| **Claude Code Hooks** | Lifecycle hooks — block generated files, log bash, warn on out-of-scope edits, inject graph status |
| **Code Graph** | SQLite dependency graph with MCP server for targeted queries |
| **Instructions** | Domain-specific guidance (testing, styling) loaded on demand |
| **Sync** | Template updates propagate to every registered project on `git pull` |

## How it compares

|  | **Coograph** | cookiecutter / copier | plain `CLAUDE.md` | raw cursor rules |
|---|---|---|---|---|
| AI tools supported | 8 (unified) | template-only | 1 (Claude) | 1 (Cursor) |
| Code graph (MCP) | yes — SQLite + tree-sitter | no | no | no |
| Workflow gate | OpenSpec proposal flow | none | manual / ad-hoc | manual / ad-hoc |
| Sync template updates | `git pull` → all projects | re-render template | manual edit | manual edit |
| Anti-hallucination guards | hooks + agent constraints | none | depends on prose | none |
| Cost to adopt | 2 min `/coograph-init` | scaffold one repo | copy-paste a file | copy-paste rules |
| License | MIT | varies | n/a | n/a |

Cookiecutter scaffolds files. Coograph scaffolds **a workflow** — files plus the agent procedures, hooks, and graph that make those files actually load when the AI runs.

## Workflow

Every task goes through the full sequence. The only exemptions are narrow and literal: typo fix in a single file, comment/docstring-only edit, user-dictated config-value bump, or follow-up for an already-approved in-progress OpenSpec. "Trivial", "obvious", "small", and "just one tweak" are NOT exemptions.

```mermaid
flowchart LR
    PLAN["PLAN\nInvestigate\nInterview"]
    PROPOSE["PROPOSE\nOpenSpec\nproposal + tasks"]
    APPLY["APPLY\nWork through\ntasks.md"]
    QA["QA GATES\nbuild + test"]
    REVIEW["REVIEW\nfile:line\nevidence"]
    ARCHIVE["ARCHIVE\nMove to\narchive/"]

    PLAN --> PROPOSE --> APPLY --> QA --> REVIEW --> ARCHIVE
    PLAN -. "Exempt fix" .-> APPLY
    APPLY -. "Build fail\n3-retry limit" .-> APPLY
```

| Step | Claude Code | VS Code Copilot |
|------|-------------|----------------|
| Start a new ticket | `/project:new-ticket` | `new-ticket` prompt / skill |
| Plan | `/project:plan` | `@Planner` |
| Propose | `openspec-propose` skill | `openspec-propose` skill |
| Apply | `openspec-apply` skill | `openspec-apply` skill |
| Review | `/project:review` | `@Reviewer` |
| Verify | `/project:verify` | `@Verifier` |
| Debug | `/project:debug` | `@Debugger` |
| Explore | `/project:explore` | `@Explore` |
| Archive | `openspec-archive` skill | `openspec-archive` skill |

`/project:new-ticket` is the recommended entry point when you paste a ticket, issue, or task description — it runs pre-flight, investigates the codebase, and hands off to `/project:plan` or the `openspec-propose` skill. Use the individual steps directly when you already know where you are in the workflow.

OpenSpec changes live in `openspec/changes/<date>-<slug>/` with `proposal.md`, `specs/<capability>/spec.md`, and `tasks.md`. Completed changes move to `openspec/changes/archive/`.

## Agents

There is no separate `@Implementer` — the agent that plans also implements.

| Agent | Purpose | Key constraint |
|-------|---------|----------------|
| **Planner** | Interview-driven planning | One question at a time. Never implements. |
| **Reviewer** | Strict read-only code review | Every finding needs a verbatim quote from a fresh read. |
| **Debugger** | Root-cause analysis, minimal fixes | Reproduce → Evidence → Fix → Verify. 3-attempt circuit breaker. |
| **Verifier** | Evidence-based completion checks | Runs commands itself. PASS/FAIL/INCOMPLETE verdict. |
| **Explore** | Fast read-only codebase Q&A | Quick / medium / thorough depth levels. |

All agents MUST call code-graph first — the rule is non-negotiable. Fallback to `sqlite3 .code-graph/graph.db`, and only then to grep/read, is permitted ONLY when the code-graph DB is genuinely absent from the workspace. Convenience is not a valid reason to skip.

## Claude Code Hooks

Lifecycle hooks in `.claude/hooks/`, wired via `.claude/settings.json`. They run automatically on every session — no agent decision, no prompt engineering required.

| Hook | Event | What it does |
|------|-------|--------------|
| **`block-generated.py`** | PreToolUse (Edit/Write) | **Blocks** edits to files under `generated/`, `dist/`, `build/`, `.next/`, `node_modules/`, or anything with `@generated` / `DO NOT EDIT` / `AUTO-GENERATED` in the first 5 lines. Protects codegen output from accidental hand-edits. |
| **`log-bash.py`** | PreToolUse (Bash) | Appends every bash command to `.coograph/session.log` *and* `.coograph/sessions/<session_id>.log` (both gitignored, per-project). Two-layer audit trail. Codex CLI + OpenCode variants write to the same files — see [Bash audit log](#bash-audit-log) below. |
| **`report-graph.py`** | SessionStart | Reports code-graph state at session start: `[code-graph] N nodes, M edges, SIZEkb, updated Xh ago`. Prints a rebuild hint if `graph.db` is missing but the server is present. |
| **`warn-scope.py`** | PreToolUse (Edit/Write) | If an active OpenSpec exists, **warns** (non-blocking) when editing a file not referenced in its `tasks.md`. Surfaces scope creep without stopping work. |

Personal or machine-specific overrides go in `.claude/settings.local.json` (gitignored, never synced). `.claude/settings.json` is template-managed and gets overwritten on sync.

### Bash audit log

Every supported agent writes every Bash command it runs to **two** files inside the project, before the command executes:

| File | Format per line | When to read |
|---|---|---|
| `.coograph/session.log` | `[YYYY-MM-DD HH:MM:SS] [<agent>] [<sid8>] <command>` | One chronological tail across every agent + every session. Grep by date, by agent name (`claude-code`, `codex-cli`, `opencode`), by short session id, or by command pattern. Best for cross-session questions. |
| `.coograph/sessions/<session_id>.log` | `[YYYY-MM-DD HH:MM:SS] [<agent>] <command>` | One file per agent session. No session-id prefix because the filename already carries it. Attach to incident reports or share with a reviewer when you only need the scope of one session. |

Both files are gitignored, per-project, append-only, and local-first — nothing leaves the machine. Concurrent agents writing in parallel are safe: each per-session file has a single writer, and the global tail relies on POSIX `O_APPEND` (4 KB-atomic) on Linux/macOS and NTFS `FILE_APPEND_DATA` (atomic per syscall) on Windows. Lines interleave cleanly at line boundaries, never mid-line.

Write failures are swallowed silently — the hook never blocks the tool call.

#### Per-tool support

Eight tools, three of them have hook APIs we can use:

| Tool | Audit support | How |
|---|---|---|
| **Claude Code** | ✅ shipped | `.claude/hooks/log-bash.py` wired via `.claude/settings.json` PreToolUse Bash hook. |
| **Codex CLI** | ✅ shipped | `.codex/hooks/log-bash.py` — same script shape. Wire it once per machine in `~/.codex/config.toml` (see [setup](#codex-cli-audit-setup) below). Codex passes the same `tool_name` / `tool_input.command` / `session_id` / `cwd` payload shape so the script Just Works. |
| **OpenCode** | ✅ shipped | `.opencode/plugin/log-bash.ts` — uses OpenCode's `tool.execute.before` plugin event. Loaded automatically by OpenCode at session start. |
| **VS Code Copilot** | ⛔ no hook API | Copilot Chat does not expose a pre-tool-use hook in any public API as of 2026-05. Commands run inside the VS Code process with no interception point. Falls back to VS Code's own command history if you need a trail. |
| **Cursor** | ⛔ no hook API | Rules files only; no pre-tool-use hook surface. Use Cursor's terminal history. |
| **Windsurf** | ⛔ no hook API | Same — rules-only, no hook system exposed. |
| **Aider** | ⛔ no shell-level hook | Aider has lint/test hooks but no pre-shell-execute hook. Use shell-level `trap DEBUG` if you must. |
| **Cline** | ⛔ no hook API | VS Code extension with no public hook surface. |

For tools without an audit hook, the honest fallback is shell-level instrumentation (`PROMPT_COMMAND`, `trap DEBUG`, `auditd` on Linux). That's outside the scope of what Coograph can configure for you, but the design pattern is the same: capture the command before it runs, write to `.coograph/session.log` with an agent prefix.

#### Codex CLI audit setup

Codex reads hook config from `~/.codex/config.toml` only (no project-local override yet). Add this once per machine:

```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/log-bash.py"'
timeout = 5
```

The `$(git rev-parse --show-toplevel)` indirection means one global config row works across every Coograph-initialized project on the machine.

#### Useful grep recipes

```bash
# scope an incident to one session (any agent)
cat .coograph/sessions/4f1c8b3e-a2d1-4f9c-8e7a-2b3c5d6e7f8a.log

# every `npm install` ever, across all agents + sessions
grep "npm install" .coograph/session.log

# every command Codex CLI ran in the last week
grep "\[codex-cli\]" .coograph/session.log | awk -F'] ' '$1 >= "['"$(date -d '7 days ago' '+%Y-%m-%d')"'"'

# which sessions ran something suspicious, ranked by frequency
grep "curl.*| *sh" .coograph/session.log | grep -oE '\[[a-f0-9]{8}\]' | sort | uniq -c | sort -rn

# tail the live stream while debugging an agent run
tail -f .coograph/session.log
```

**Migrating from the legacy `.claude/session.log` path:** earlier versions of Coograph wrote audit lines to `.claude/session.log` and `.claude/sessions/`. If you have old logs there, `mv .claude/session.log .coograph/session.log.legacy` once and the new path takes over from the next command on. No automatic migration — the legacy file is not touched on its own.

## Code Graph

A standalone Python MCP server that parses your codebase into a SQLite dependency graph. Agents query it before reading any files, replacing broad searches with exact lookups.

```mermaid
flowchart LR
    subgraph WITHOUT ["Without code-graph"]
        direction TB
        A1["grep 'OrderService'"] --> A2["87 matches,<br/>30+ files"] --> A3["Read each<br/>for context"] --> A4["~50K tokens<br/>20+ tool calls"]
    end

    subgraph WITH ["With code-graph"]
        direction TB
        B1["get_minimal_context(<br/>'add caching')"] --> B2["query_graph(<br/>'callers_of', X)"] --> B3["Read 4<br/>returned files"] --> B4["~2K tokens<br/>3 tool calls"]
    end

    WITHOUT ~~~ WITH
```

- **Build once** — tree-sitter parsers for Java, TS, Python, Go, Rust, C#, Ruby, and more walk your source into `.code-graph/graph.db`.
- **Auto-updated** — git hooks (`post-commit`, `post-merge`, `post-rewrite`) re-parse only files whose SHA-1 changed. Millisecond updates.
- **Query first** — agents call `get_minimal_context()` before any file read, falling back to grep only on failure.

### Visualize

The MCP server ships an interactive D3 force-directed view of your graph. Useful for sanity-checking a fresh build, spotting orphan modules, and showing teammates what the agent actually sees.

```bash
uv run --with-requirements .github/code-graph/requirements.txt \
  .github/code-graph/server.py --visualize
```

Outputs `.code-graph/graph.html` — a standalone HTML file (no server needed). Open in any browser. Drag nodes, hover for symbol details, filter by language or kind.

![Coograph code-graph visualization — interactive D3 force-directed view of nodes and edges](docs/visualize.png)

Full reference (install, MCP config, supported stacks, tool list): [.github/code-graph/README.md](.github/code-graph/README.md).

<details>
<summary><strong>Project Sync</strong> — template updates propagate to every registered project on <code>git pull</code></summary>

<br>

Template updates propagate to every registered project automatically.

1. `/coograph-init` writes your project to `projects.json`.
2. Install the hook once in the coograph repo:
   ```bash
   cp .github/hooks/post-merge .git/hooks/post-merge
   chmod +x .git/hooks/post-merge
   ```
3. From then on, `git pull` in coograph triggers `sync.py`, which copies updated template files to every registered project and rebuilds their code-graphs.

| Synced (template-managed) | Not synced (user-owned) |
|---|---|
| `.github/agents/` | `CLAUDE.md` |
| `.github/skills/` | `.github/copilot-instructions.md` |
| `.github/prompts/` | `openspec/config.yaml` |
| `.github/instructions/` | `.claude/settings.local.json` |
| `.github/code-graph/` | |
| `.claude/commands/project/` | |
| `.claude/hooks/` | |
| `.claude/settings.json` | |
| `AGENTS.md` | |

Sync output appends to `.github/sync.log`.

**Migrations:** when a template update changes a user-owned file (`CLAUDE.md`, `.github/copilot-instructions.md`, `openspec/config.yaml`), sync skips it to preserve your customizations. Any such change is recorded in [MIGRATION.md](MIGRATION.md) with the exact text to apply by hand. Check that file after every `git pull` in coograph.

</details>

## Customization

After initialization, review these manually:

1. **`copilot-instructions.md`** — Project-Specific Rules section (domain invariants, naming, module boundaries)
2. **`openspec/config.yaml`** — stack and domain context for better AI-generated proposals
3. **`testing.instructions.md`** / **`styling.instructions.md`** — uncomment rules that match your stack

**Trimming for small projects:** only `.github/copilot-instructions.md` is required. Delete any of `.github/agents/`, `.github/skills/`, `.claude/`, `openspec/`, or `.github/code-graph/` you don't use.

<details>
<summary><strong>Reliability</strong> — anti-hallucination, workflow safety, token efficiency</summary>

<br>

**Anti-hallucination**
- Every review/verify finding must cite a verbatim quote from a fresh file read — diffs and memory are not valid sources.
- Agents grep for every name before using it. Never invent types or APIs.
- Re-read modified files after 10+ turns. Never cite prior output as evidence.
- Template guard: if `_TBD_` markers remain in instruction files, agents stop and ask before coding.

**Workflow safety**
- Circuit breakers: 3-retry limit on fixes, 3-cycle limit on review loops.
- Feature inventory: before editing any file, list existing features and verify each is preserved.
- Scope-creep detection: debugger reviews its own diff after every fix and reverts unrelated changes.
- Risk-based classification: auth/security/payments/migrations always get Complex treatment regardless of file count.

**Token efficiency**
- Graph-first: `get_minimal_context(task)` returns 4-6 relevant files instead of grepping 200+.
- Progressive disclosure: testing/styling instructions load only when editing matching files.
- Memory-pointer pattern: large intermediate results written to files, referenced by path.

</details>

## Star history

<a href="https://star-history.com/#paullukic/coograph&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=paullukic/coograph&type=Date&theme=dark">
    <img alt="Star history" src="https://api.star-history.com/svg?repos=paullukic/coograph&type=Date">
  </picture>
</a>

## Acknowledgments

Coograph stands on top of work done by many others.

- [Tree-sitter](https://tree-sitter.github.io/) — parser frontend powering every language in the code graph
- [Model Context Protocol](https://modelcontextprotocol.io/) — Anthropic's open standard the code-graph server speaks
- [Anthropic Claude Code](https://docs.anthropic.com/claude/docs/claude-code), [GitHub Copilot](https://github.com/features/copilot), [OpenAI Codex CLI](https://github.com/openai/codex), [sst/opencode](https://opencode.ai), [Cursor](https://cursor.com), [Windsurf](https://windsurf.com), [Aider](https://aider.chat), [Cline](https://cline.bot) — the eight tools coograph plugs into
- [D3](https://d3js.org/) — force-directed visualization
- [SQLite](https://sqlite.org/) — the only database that earns its way into every machine

## Sponsor

If coograph saves you grep-reads, consider [sponsoring on GitHub](https://github.com/sponsors/paullukic). Funds maintenance, language coverage, and the public roadmap.

## Share

Tell someone about it: [tweet about coograph](https://twitter.com/intent/tweet?text=Graph-first%20context%20for%20AI%20coding.%20%2Fcoograph-init%20works%20across%208%20tools.&url=https%3A%2F%2Fcoograph.com&hashtags=ai,coding,opensource)

## License

[MIT](LICENSE). Free forever for everyone.
