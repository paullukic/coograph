---
name: coograph-suggest-multi-models
description: Suggest which model each Coograph agent should run on, for this project or for the ticket in hand, with a reason and an estimated cost delta per line. Use when the user asks about per-task models, wants to change an existing mapping, or wants to re-enable model selection in a project that turned it off.
argument-hint: Optional. "project" suggests a saved mapping; "task" suggests one for the ticket in hand. Default is whichever fits the conversation.
license: MIT
metadata:
  author: coograph
  version: "1.0"
---

You propose a per-agent model mapping. You never apply one the user has not accepted, and you never touch the model their own session runs on.

## Why This Matters

Coograph delegates to six agents whose demands differ by an order of magnitude. `explore` reads a great deal and decides little; `debugger` reads little and decides everything. Running all six on one model either overpays for the reading or underpowers the thinking. The right split depends on the change in front of you, which is why this is a suggestion at a moment you know something about the work, not a table shipped in a template.

## The catalogue

Read `models.catalog` in `openspec/config.yaml`. It is the project's own: each alias bound to the model id their tool loads, and rough per-million-token rates.

```yaml
models:
  catalog:
    cheap:   { id: claude-haiku-4-5, in: 1,  out: 5  }
    capable: { id: claude-opus-5,    in: 5,  out: 25 }
```

Reason about **what is in there**, never a table you remember. The rates are theirs; say so, and say they are estimates rather than measured spend.

**No catalogue declared.** Nothing changes: on Claude Code the built-in aliases `fable`, `opus`, `sonnet`, `haiku` still work exactly as before. On any other tool, say that a catalogue is needed because that tool loads different model ids, show the block above, and stop. Do not invent ids.

**An alias in `preset` with no catalogue entry** is an error, not a guess. Name the alias and stop.

**Never infer a catalogue.** Not from an API key, an installed SDK, an environment variable, or the tool in use. If it is not declared, it does not exist.

Two things to keep saying: a top-tier model usually costs several times the mid one and is for genuinely hard, long-horizon work rather than a default, and a cheap model on a judgment task spends the saving again on the next session.

## The starting mapping

Begin from this and adjust for the project or ticket. Reasons matter more than the table; give one per line.

Roles map to catalogue aliases, not to model names. The shape below uses the example aliases; substitute whatever the project declared.

| Agent | Tier | Reason |
|---|---|---|
| `explore` | cheapest | Bulk reading and summarising, high token volume, little judgment. The largest saving available. |
| `search` | cheapest | Same shape as explore. |
| `verifier` | middle | Runs commands and checks results against stated criteria. Mechanical. |
| `debugger` | capable | Root-causing is where a cheap model burns turns guessing and costs more than it saved. |
| `reviewer` | capable | One caught defect repays the difference many times. |
| `planner` | capable | Low volume, high leverage; it sets the shape of everything after it. |
| `retro` | capable | Reads a deterministic report and argues from it. |

Adjust when the work says so. A one-file change with an obvious fix does not need the capable tier on review. A concurrency bug, a migration, an auth path or anything touching money argues for capable everywhere and the top tier on the hardest step.

## Steps

1. **Read the current state** from `openspec/config.yaml`, the `models` block: `mode` (`unset`, `off`, `preset`, `per-task`) and any saved `preset`. Missing block means `unset`.
2. **Decide the scope.** A ticket in progress means suggest for the task; otherwise suggest a saved mapping for the project. If the user named one, use that.
3. **Check the tool can honour it**, and how. See "Reach" below. Five tools take a mapping and each wants it in a different place. Two do not delegate at all, so there is nothing to map: say so and stop. Never write config a tool will not load.
4. **Produce the table.** One row per agent you propose to change: agent, model, a one-line reason grounded in this project or ticket, and the cost delta against the session model. Say which figures are estimates.
5. **Offer the edit.** The user may change any line, accept all, or decline. Nothing is written before they answer.
6. **Write it.** On accept, update the `models` block in `openspec/config.yaml`: set `mode` (`preset` for a saved mapping, `per-task` if they want to be asked each time) and the `preset` map. A task-scoped choice is used for that task only and is not written to disk.
7. **Say what changed** in one line, and name the file if you wrote one.

## Reach

Five tools delegate to Coograph's agents, so a model per role is a real setting. Each wants it somewhere different.

| Tool | Where the mapping goes |
|---|---|
| Claude Code | the `model` parameter on the Agent call |
| Cursor | `model:` frontmatter on subagent markdown in `.cursor/agents/` or `.claude/agents/` |
| VS Code Copilot | `model:` frontmatter in `.github/agents/*.agent.md` |
| Codex CLI | TOML agent definitions under `~/.codex/agents/`, which also take `model_reasoning_effort` |
| OpenCode | agents in `opencode.json`, ids in `provider/model-id` form |

A role with no mapping is left to inherit. Never pin one the user did not choose.

**Refuse rather than substitute.** If the catalogue names an id the target cannot load, stop and say which id and which constraint. Two known ones: VS Code Copilot resolves only `copilot`-vendor models, and its `model` frontmatter field takes a different form in Copilot CLI than in VS Code Copilot Chat. Writing a near-miss and letting it fail at load is worse than refusing.

### Aider and Cline

Coograph runs as rules there. There is one agent, and it runs everything, so there are no roles to assign and no mapping to write.

Aider's `--model` / `--editor-model` / `--weak-model` and Cline's separate Plan and Act models are those tools' **own** pipeline stages, not Coograph agents. Assigning `reviewer` to Aider's editor slot is not a lossy collapse; there is no reviewer at runtime to collapse. Say this plainly, suggest nothing, and write nothing. Do not describe it as unsupported-for-now: it is not coming.

## Guardrails

- Never write config without an explicit accept.
- Never propose a cheaper model for `reviewer` or `debugger` unless the user asks. A missed defect costs more than the saving.
- Say the cache cost out loud when you propose three or more different models: prompt caches are model-scoped, so each model is its own cache namespace, and short agent runs can lose more to cache misses than they save on rate. The read-heavy agents are where a cheap model still wins.
- Never change the user's own session model, and never suggest they change it.
- The rate table above is dated. If the user asks whether it is current, say when it was recorded and that live rates are on Anthropic's pricing page.
