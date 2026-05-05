# Agent Context

<!--
  Quick summary for AI agents that auto-read AGENTS.md
  (VS Code Copilot, OpenAI Codex CLI, generic AGENTS.md-aware agents).
  Other tools have native config files: .cursor/rules/, .windsurfrules,
  CONVENTIONS.md (Aider), .clinerules. CLAUDE.md is loaded by Claude Code.
  Full conventions: .github/copilot-instructions.md
-->

When working on this codebase:

- **Rules**: Follow `.github/copilot-instructions.md`.
- **Pre-flight**: On session start, call `get_minimal_context` to verify code-graph availability. Code-graph is MANDATORY for ALL navigation — fall back to grep/glob ONLY when the DB is genuinely absent. Check `openspec/changes/` for in-progress work.
- **OpenSpec gate**: Any change that modifies 2+ files, touches a spec, alters a public interface, or adds new behavior MUST go through `openspec/changes/<date>-<slug>/` with user approval before code. Exemptions are narrow and literal: typo fix, comment-only edit, user-dictated config bump, or follow-up on an approved in-progress OpenSpec. "Trivial", "obvious", "small" are NOT exemptions.
- **Stack**: <!-- FILL: e.g. "Next.js 16, React 19, TypeScript, TanStack Query" -->
- **Structure**: <!-- FILL: e.g. "src/app/ pages, src/components/ shared, src/lib/ utilities" -->
- **Communication**: Read `.github/instructions/brutal-honesty.instructions.md` at session start and apply throughout. Direct, evidence-based, severity-rated. Every finding cites `file:line` with verbatim quotes.
- **Workflow**: Plan → Propose (OpenSpec) → Apply → Quality Gates → Review Gate → Archive. Skip only for exemptions above. After 3 failed attempts, stop and ask.

If `.github/copilot-instructions.md` has unfilled sections (`FILL` or `_TBD_`), ask the user before coding.

### Agents

| Agent | Purpose |
|-------|---------|
| `@Reviewer` | Read-only code review |
| `@Debugger` | Root-cause analysis, minimal fixes |
| `@Planner` | Interview-driven planning |
| `@Verifier` | Evidence-based completion checks |
| `@Explore` | Codebase search and Q&A |

No separate `@Implementer` — the agent that plans also implements.
