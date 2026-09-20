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

## Rates

Published per-million-token rates, recorded 2026-09-20. Re-state to the user that these are list prices, not their measured spend.

| Alias | Model | Input | Output | Context |
|---|---|---|---|---|
| `fable` | Claude Fable 5.1 | $10 | $50 | 1M |
| `opus` | Claude Opus 5 | $5 | $25 | 1M |
| `sonnet` | Claude Sonnet 5 | $2 | $10 | 1M |
| `haiku` | Claude Haiku 4.5 | $1 | $5 | 200K |

Use the aliases in config and in Agent calls. Note that Fable costs twice Opus: it is for genuinely hard, long-horizon work, not a default.

## The starting mapping

Begin from this and adjust for the project or ticket. Reasons matter more than the table; give one per line.

| Agent | Model | Reason |
|---|---|---|
| `explore` | `haiku` | Bulk reading and summarising, high token volume, little judgment. The largest saving available. |
| `search` | `haiku` | Same shape as explore. |
| `verifier` | `sonnet` | Runs commands and checks results against stated criteria. Mechanical. |
| `debugger` | `opus` | Root-causing is where a cheap model burns turns guessing and costs more than it saved. |
| `reviewer` | `opus` | One caught defect repays the difference many times. |
| `planner` | `opus` | Low volume, high leverage; it sets the shape of everything after it. |
| `retro` | `opus` | Reads a deterministic report and argues from it. |

Adjust when the work says so. A one-file change with an obvious fix does not need `opus` on review. A concurrency bug, a migration, an auth path or anything touching money argues for `opus` everywhere and `fable` on the hardest step.

## Steps

1. **Read the current state** from `openspec/config.yaml`, the `models` block: `mode` (`unset`, `off`, `preset`, `per-task`) and any saved `preset`. Missing block means `unset`.
2. **Decide the scope.** A ticket in progress means suggest for the task; otherwise suggest a saved mapping for the project. If the user named one, use that.
3. **Check the tool can honour it.** A per-invocation model override works in Claude Code. For any other tool, say plainly that the mapping cannot be applied there and stop rather than writing config that will do nothing.
4. **Produce the table.** One row per agent you propose to change: agent, model, a one-line reason grounded in this project or ticket, and the cost delta against the session model. Say which figures are estimates.
5. **Offer the edit.** The user may change any line, accept all, or decline. Nothing is written before they answer.
6. **Write it.** On accept, update the `models` block in `openspec/config.yaml`: set `mode` (`preset` for a saved mapping, `per-task` if they want to be asked each time) and the `preset` map. A task-scoped choice is used for that task only and is not written to disk.
7. **Say what changed** in one line, and name the file if you wrote one.

## Guardrails

- Never write config without an explicit accept.
- Never propose a cheaper model for `reviewer` or `debugger` unless the user asks. A missed defect costs more than the saving.
- Say the cache cost out loud when you propose three or more different models: prompt caches are model-scoped, so each model is its own cache namespace, and short agent runs can lose more to cache misses than they save on rate. The read-heavy agents are where a cheap model still wins.
- Never change the user's own session model, and never suggest they change it.
- The rate table above is dated. If the user asks whether it is current, say when it was recorded and that live rates are on Anthropic's pricing page.
